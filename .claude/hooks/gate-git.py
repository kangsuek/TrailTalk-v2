#!/usr/bin/env python3
"""PreToolUse(Bash) 훅: git push의 게이트(.githooks/pre-push)가 켜져 있는지 지키고 우회를 막는다.

실제 검증은 git의 pre-push 훅(.githooks/pre-push)이 한다. 그 훅은 push할 ref마다 커밋을 정확히 받아
전체 검증 통과 기록을 확인한다(없으면 백그라운드 검증을 시작해 기다리고, 실패면 막는다). 커밋·병합 뒤의
백그라운드 검증 시작도 git 훅(post-commit·post-merge)이 한다. 이 훅은 그 층이 비어 있지 않게 한다:

  - `git push`인데 core.hooksPath가 .githooks를 가리키지 않거나 pre-push가 없으면 막는다
    (켜는 법: git config core.hooksPath .githooks).
  - `git push --no-verify`, 같은 명령 안의 `-c core.hooksPath=...` 변경처럼 게이트를 건너뛰는 시도를 막는다.
  - `gh pr merge`는 git 훅이 없으므로 현재 폴더 HEAD의 전체 검증 통과 기록을 직접 확인한다
    (이 프로젝트는 PR을 쓰지 않는다. 쓰게 되면 PR의 머지 결과가 아니라 로컬 HEAD를 본다는 한계가 있다).

명령을 `;` `&&` `||` `|` 줄바꿈 단위로 나눠 각각 판정한다(환경 변수·env·sudo·time 접두와
`git -C 경로`·`--no-pager` 같은 전역 옵션, `bash -c "..."` 안의 명령도 본다). 훅 자체 오류는
통과시킨다(fail-open): 그때도 켜진 pre-push 훅이 push를 지킨다.
"""

import json
import os
import re
import shlex
import signal
import subprocess
import sys

GATE_WAIT_S = 900  # gh pr merge 때 verify-bg.sh gate가 검증을 기다리는 최대 시간(settings.json 훅 제한 시간보다 짧게)
SPLIT = re.compile(r"\|\||&&|;|\||\n")
PREFIX = {"env", "sudo", "time", "command", "nohup", "exec"}
GLOBAL_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
HOOKS_DIR = ".githooks"


def _git_info(tokens):
    """git 명령 토큰을 (서브명령, 나머지, 전역 옵션 토큰)으로. 서브명령이 없으면 (None, [], [])."""
    i = 0
    opts = []
    while i < len(tokens):
        tok = tokens[i]
        if tok in GLOBAL_OPT_WITH_ARG:
            opts += tokens[i : i + 2]
            i += 2
        elif tok.startswith("-"):
            opts.append(tok)
            i += 1
        else:
            break
    if i >= len(tokens):
        return None, [], opts
    return tokens[i], tokens[i + 1 :], opts


def _segment_checks(tokens, depth):
    """한 명령 조각에서 ('push' | 'ghmerge' | 'bypass', 이유)를 모은 목록."""
    while tokens and (tokens[0] in PREFIX or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
        if "core.hooksPath" in tokens[0]:  # GIT_CONFIG_KEY_0=core.hooksPath 같은 환경 변수로 게이트를 끄는 시도
            return [("bypass", "환경 변수로 core.hooksPath를 바꾸려는 시도입니다")]
        tokens = tokens[1:]
    if not tokens:
        return []
    head = os.path.basename(tokens[0])
    found = []
    if head == "git":
        sub, rest, opts = _git_info(tokens[1:])
        if sub == "push" and not any(t in ("--delete", "-d", "--dry-run", "-n") for t in rest):
            found.append(("push", ""))
            if "--no-verify" in rest:
                found.append(("bypass", "git push --no-verify는 pre-push 게이트를 건너뜁니다"))
            if any("core.hooksPath" in t for t in opts):
                found.append(("bypass", "git -c core.hooksPath=...로 게이트를 끄려는 시도입니다"))
    elif head == "gh" and tokens[1:3] == ["pr", "merge"]:
        found.append(("ghmerge", ""))
    elif head in ("bash", "sh", "zsh") and "-c" in tokens and depth < 3:
        idx = tokens.index("-c")
        if idx + 1 < len(tokens):
            found += checks_for(tokens[idx + 1], depth + 1)
    return found


def checks_for(command, depth=0):
    found = []
    for segment in SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        found += _segment_checks(tokens, depth)
    return found


def hooks_enabled(cwd):
    """cwd의 저장소에서 core.hooksPath가 .githooks를 가리키고 pre-push가 실행 가능한지. (참/거짓, 설명)"""
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        cfg = subprocess.run(
            ["git", "-C", cwd, "config", "--get", "core.hooksPath"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return True, ""  # 알 수 없으면 막지 않는다(fail-open)
    if not top:
        return True, ""
    hooks = cfg if os.path.isabs(cfg) else os.path.join(top, cfg)
    if not cfg or os.path.realpath(hooks) != os.path.realpath(os.path.join(top, HOOKS_DIR)):
        return False, "core.hooksPath가 %s를 가리키지 않습니다(현재: %s)." % (HOOKS_DIR, cfg or "비어 있음")
    pre_push = os.path.join(top, HOOKS_DIR, "pre-push")
    if not (os.path.isfile(pre_push) and os.access(pre_push, os.X_OK)):
        return False, "%s/pre-push가 없거나 실행할 수 없습니다." % HOOKS_DIR
    return True, ""


def head_sha(cwd):
    """명령을 실행한 폴더의 HEAD 커밋. 알 수 없으면 'HEAD'."""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else "HEAD"
    except Exception:
        return "HEAD"


def run_gate(root, sha):
    script = os.path.join(root, "scripts", "verify-bg.sh")
    env = dict(os.environ, VERIFY_GATE_TIMEOUT=str(GATE_WAIT_S))
    proc = subprocess.Popen(
        [script, "gate", sha], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, start_new_session=True, env=env,
    )
    try:
        out, _ = proc.communicate(timeout=GATE_WAIT_S + 30)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # 기다리던 sleep 같은 자식까지 정리한다
        proc.communicate()
        return 1, "verify-bg.sh gate가 %d초 안에 끝나지 않았습니다." % (GATE_WAIT_S + 30)


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=False,
        )
    )


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    found = checks_for(command)
    kinds = {kind for kind, _ in found}
    if not kinds:
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    cwd = data.get("cwd") or root

    bypass = [why for kind, why in found if kind == "bypass"]
    if bypass:
        deny("푸시 게이트 우회는 허용하지 않습니다: %s" % "; ".join(sorted(set(bypass))))
        return
    if "push" in kinds:
        enabled, why = hooks_enabled(cwd)
        if not enabled:
            deny(
                "푸시 게이트(.githooks/pre-push)가 꺼져 있어 push를 막습니다. %s\n"
                "켜는 법: git config core.hooksPath .githooks (clone마다 한 번)" % why
            )
            return
    if "ghmerge" in kinds and os.path.exists(os.path.join(root, "scripts", "verify-bg.sh")):
        code, out = run_gate(root, head_sha(cwd))
        if code != 0:
            tail = "\n".join(out.strip().splitlines()[-40:])
            deny("머지 게이트 실패(현재 HEAD의 전체 검증 통과 기록 없음). 원인을 고친 뒤 다시 시도하세요.\n%s" % tail)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 훅 결함이 작업을 막지 않게 한다
        print("gate-git 훅 오류(무시): %r" % (exc,), file=sys.stderr)
