#!/usr/bin/env python3
"""Bash 훅: 커밋·병합 뒤에는 전체 검증을 백그라운드로 시작하고, push 전에는 통과 기록을 확인한다.

  PreToolUse  (인자 없음): `git push`·`gh pr merge` 전에 scripts/verify-bg.sh gate를 돌린다.
                           통과 기록이 있으면 바로 통과, 검증이 돌고 있으면 끝날 때까지 기다리고,
                           실패했거나 시작하지 못했으면 명령을 막는다(deny).
  PostToolUse (--post):    `git commit`·`merge`·`pull` 뒤에 scripts/verify-bg.sh start로
                           전체 검증을 백그라운드에서 시작한다(기다리지 않는다. 끝나면 맥 알림).

검증 대상은 명령을 실행한 셸의 현재 폴더(cwd) HEAD 커밋이다. 명령을 `;` `&&` `||` `|` 줄바꿈 단위로
나눠 각각 판정한다(환경 변수·env·sudo·time 접두와 `git -C 경로`·`--no-pager` 같은 전역 옵션,
`bash -c "..."` 안의 명령도 본다). 훅 자체 오류는 통과시킨다(fail-open).
"""

import json
import os
import re
import shlex
import signal
import subprocess
import sys

GATE_WAIT_S = 900  # verify-bg.sh gate가 검증을 기다리는 최대 시간(settings.json 훅 제한 시간보다 짧게)
SPLIT = re.compile(r"\|\||&&|;|\||\n")
PREFIX = {"env", "sudo", "time", "command", "nohup", "exec"}
GLOBAL_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GATE = {"push"}
START = {"commit", "merge", "pull"}


def _git_mode(tokens):
    """git 명령 토큰에서 'gate'/'start'/None."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in GLOBAL_OPT_WITH_ARG:
            i += 2
        elif tok.startswith("-"):
            i += 1
        else:
            break
    if i >= len(tokens):
        return None
    sub, rest = tokens[i], tokens[i + 1 :]
    if sub == "merge" and any(t in ("--abort", "--quit", "--continue") for t in rest):
        return None
    if sub == "push" and any(t in ("--delete", "-d", "--dry-run", "-n") for t in rest):
        return None
    if sub == "commit" and any(t in ("--dry-run",) for t in rest):
        return None
    if sub in GATE:
        return "gate"
    if sub in START:
        return "start"
    return None


def _segment_mode(tokens, depth):
    while tokens and (tokens[0] in PREFIX or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
        tokens = tokens[1:]
    if not tokens:
        return None
    head = os.path.basename(tokens[0])
    if head == "git":
        return _git_mode(tokens[1:])
    if head == "gh" and tokens[1:3] == ["pr", "merge"]:
        return "gate"
    if head in ("bash", "sh", "zsh") and "-c" in tokens and depth < 3:
        idx = tokens.index("-c")
        if idx + 1 < len(tokens):
            return mode_for(tokens[idx + 1], depth + 1)
    return None


def mode_for(command, depth=0):
    best = None
    for segment in SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        mode = _segment_mode(tokens, depth)
        if mode == "gate":
            return "gate"
        best = best or mode
    return best


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


def run_bg(root, action, sha, timeout):
    script = os.path.join(root, "scripts", "verify-bg.sh")
    env = dict(os.environ, VERIFY_GATE_TIMEOUT=str(GATE_WAIT_S))
    proc = subprocess.Popen(
        [script, action, sha], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, start_new_session=True, env=env,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # 기다리던 sleep 같은 자식까지 정리한다
        proc.communicate()
        return 1, "verify-bg.sh %s가 %d초 안에 끝나지 않았습니다." % (action, timeout)


def main():
    post = "--post" in sys.argv[1:]
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    mode = mode_for(command)
    if mode is None or (post and mode != "start") or (not post and mode != "gate"):
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    if not os.path.exists(os.path.join(root, "scripts", "verify-bg.sh")):
        return
    sha = head_sha(data.get("cwd") or root)
    if post:
        code, out = run_bg(root, "start", sha, 120)
        message = out.strip().splitlines()[-1] if out.strip() else ""
        if message:
            print(
                json.dumps(
                    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}},
                    ensure_ascii=False,
                )
            )
        return
    code, out = run_bg(root, "gate", sha, GATE_WAIT_S + 30)
    if code == 0:
        return
    tail = "\n".join(out.strip().splitlines()[-40:])
    reason = "푸시 게이트 실패(전체 검증 통과 기록 없음). 원인을 고친 뒤 다시 시도하세요.\n%s" % tail
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


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 훅 결함이 작업을 막지 않게 한다
        print("gate-git 훅 오류(무시): %r" % (exc,), file=sys.stderr)
