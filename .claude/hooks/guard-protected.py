#!/usr/bin/env python3
"""PreToolUse(Edit|Write) 훅: 기존 테스트·보호 파일을 고치려 하면 사용자 확인(ask)으로 돌린다.

새 파일을 만드는 것은 막지 않는다(테스트 추가는 자유). 훅 자체 오류는 통과시킨다(fail-open).
"""

import fnmatch
import json
import os
import sys

# 저장소 루트 기준 glob. 기존 파일을 고칠 때만 확인한다.
TESTS = [
    "server/tests/*",
    "web/src/*.test.ts",
    "web/src/*.test.tsx",
    "web/e2e/*",
    "shared/fixtures/*",
]
PROTECTED = [
    "docs/Spec.md",
    "docs/client-contract.md",
    "shared/client-defaults.json",
    "server/migrations/versions/*.py",
]


def decide(root, file_path):
    path = os.path.realpath(file_path)
    root = os.path.realpath(root)
    if not path.startswith(root + os.sep) or not os.path.exists(path):
        return None
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    if any(fnmatch.fnmatch(rel, pattern) for pattern in TESTS):
        return (
            "기존 테스트 파일 수정입니다(%s). 테스트를 지우거나 기대값을 낮추지 않았는지 확인하세요. "
            "계약이 바뀐 경우가 아니면 구현을 고치는 것이 맞습니다." % rel
        )
    if any(fnmatch.fnmatch(rel, pattern) for pattern in PROTECTED):
        return "보호 파일 수정입니다(%s). 명세·규약·기본값·기존 마이그레이션은 변경 이유를 확인합니다." % rel
    return None


def main():
    data = json.load(sys.stdin)
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path:
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    reason = decide(root, file_path)
    if reason:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
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
        print("guard-protected 훅 오류(무시): %r" % (exc,), file=sys.stderr)
