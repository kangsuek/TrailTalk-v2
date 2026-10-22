#!/usr/bin/env python3
"""PreToolUse(Bash) 훅: git commit 전에는 verify.sh --quick, push·merge 전에는 전체 검증을 돌린다.

명령을 `;` `&&` `||` `|` 줄바꿈 단위로 나눠 각각 판정한다(환경 변수·env·sudo·time 접두와
`git -C 경로`·`--no-pager` 같은 전역 옵션, `bash -c "..."` 안의 명령도 본다).
실패하면 명령을 막고(deny) 실패 출력을 사유로 돌려준다. 훅 자체 오류는 통과시킨다(fail-open).
"""

import json
import os
import re
import shlex
import signal
import subprocess
import sys

TIMEOUT_S = 900
SPLIT = re.compile(r"\|\||&&|;|\||\n")
PREFIX = {"env", "sudo", "time", "command", "nohup", "exec"}
GLOBAL_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
FULL = {"push", "merge"}
QUICK = {"commit"}


def _git_mode(tokens):
    """git 명령 토큰에서 'quick'/'full'/None."""
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
    if sub in FULL:
        return "full"
    if sub in QUICK:
        return "quick"
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
        return "full"
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
        if mode == "full":
            return "full"
        best = best or mode
    return best


def run_verify(root, mode):
    script = os.path.join(root, "scripts", "verify.sh")
    args = [script] + (["--quick"] if mode == "quick" else [])
    proc = subprocess.Popen(
        args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=TIMEOUT_S)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # pytest·npm 같은 자식까지 정리한다
        proc.communicate()
        return 1, "verify.sh가 %d초 안에 끝나지 않았습니다." % TIMEOUT_S


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    mode = mode_for(command)
    if mode is None:
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    if not os.path.exists(os.path.join(root, "scripts", "verify.sh")):
        return
    code, out = run_verify(root, mode)
    if code == 0:
        return
    tail = "\n".join(out.strip().splitlines()[-40:])
    reason = "검증 게이트 실패(%s). 원인을 고친 뒤 다시 시도하세요.\n%s" % (
        "scripts/verify.sh" + (" --quick" if mode == "quick" else ""),
        tail,
    )
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
