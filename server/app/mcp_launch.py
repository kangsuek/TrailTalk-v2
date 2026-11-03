"""외부 MCP stdio 서버 실행기(M5-13).

사용: `python -I mcp_launch.py --cwd <폴더> --env <이름,…> -- <명령> <인자…>`.

Claude CLI가 mcp.json의 command로 이 파일을 띄우면, 여기서 작업 폴더를 빈 하위 폴더로 옮기고 환경을
최소로 줄인 뒤 외부 서버 명령으로 바꿔 실행(execve)한다. 셸을 쓰지 않고 명령은 절대 경로여야 한다.
환경은 PATH·HOME·LANG·TMPDIR과 --env에 이름을 적은 변수(mcp.json의 env로 받은 값)만 남긴다.
표준 라이브러리만 쓴다. 오류 문구에 환경 값·인자를 넣지 않는다(CLI 로그로 새지 않게).
"""

import os
import sys

BASE_ENV = ("PATH", "HOME", "LANG", "TMPDIR")
DEFAULT_PATH = "/usr/bin:/bin"


def fail(message: str) -> None:
    print(f"mcp_launch: {message}", file=sys.stderr)
    sys.exit(127)


def main(argv: list[str]) -> None:
    if len(argv) < 5 or argv[0] != "--cwd" or argv[2] != "--env" or argv[4] != "--":
        fail("사용법이 올바르지 않습니다")
    cwd, names, command = argv[1], [n for n in argv[3].split(",") if n], argv[5:]
    if not command or not os.path.isabs(command[0]):
        fail("명령은 절대 경로여야 합니다")
    try:
        os.chdir(cwd)
    except OSError:
        fail("작업 폴더로 옮길 수 없습니다")
    env = {k: os.environ[k] for k in (*BASE_ENV, *names) if k in os.environ}
    env.setdefault("PATH", DEFAULT_PATH)
    try:
        os.execve(command[0], command, env)
    except OSError as exc:
        fail(f"실행하지 못했습니다({type(exc).__name__})")


if __name__ == "__main__":
    main(sys.argv[1:])
