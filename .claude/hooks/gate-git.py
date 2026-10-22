#!/usr/bin/env python3
"""PreToolUse(Bash) 훅: git commit 전에는 verify.sh --quick, push·merge 전에는 전체 검증을 돌린다.

실패하면 명령을 막고(deny) 실패 출력을 사유로 돌려준다. 훅 자체 오류는 통과시킨다(fail-open).
"""

import json
import os
import re
import subprocess
import sys

COMMIT = re.compile(r"(^|[;&|(]\s*)git(\s+-[cC]\s+\S+)*\s+commit\b")
PUSH_MERGE = re.compile(r"(^|[;&|(]\s*)git(\s+-[cC]\s+\S+)*\s+(push|merge)\b")
SKIP = re.compile(r"\bmerge\s+--(abort|quit)\b|\bpush\b.*--delete\b|--dry-run")
TIMEOUT_S = 900


def mode_for(command):
    if SKIP.search(command):
        return None
    if PUSH_MERGE.search(command):
        return "full"
    if COMMIT.search(command):
        return "quick"
    return None


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    mode = mode_for(command)
    if mode is None:
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    script = os.path.join(root, "scripts", "verify.sh")
    if not os.path.exists(script):
        return
    args = [script] + (["--quick"] if mode == "quick" else [])
    try:
        result = subprocess.run(
            args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, timeout=TIMEOUT_S,
        )
        code, out = result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        code, out = 1, "verify.sh가 %d초 안에 끝나지 않았습니다." % TIMEOUT_S
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
