"""외부 MCP 앱 실행·관리: `python -m app.mcp_external [serve|revoke-all]`.

serve: 외부 MCP 앱을 MCP_PORT(기본 8400)에서 띄운다. 공개 주소·소유자 비밀번호가 없으면 시작하지
않고 이유를 알린다. revoke-all: 발급한 토큰·인가 코드·등록 클라이언트를 모두 지운다(분실 대응).
소유자 비밀번호를 바꾼 뒤에도 실행하면 옛 연결이 끊긴다.
"""

import asyncio
import sys

import uvicorn

from app.config import Settings
from app.db.session import create_engine_for, create_session_factory
from app.mcp_external.app import SchemaNotReady, create_external_app
from app.mcp_external.config import McpConfigError
from app.mcp_external.oauth import revoke_all


async def _revoke_all(settings: Settings) -> int:
    engine = create_engine_for(settings.database_url)
    try:
        return await revoke_all(create_session_factory(engine))
    finally:
        await engine.dispose()


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "serve"
    settings = Settings()
    if command == "revoke-all":
        count = asyncio.run(_revoke_all(settings))
        print(f"토큰 {count}개와 등록 클라이언트를 모두 지웠습니다. 앱에서 다시 연결하세요.")
        return 0
    if command != "serve":
        print("사용법: python -m app.mcp_external [serve|revoke-all]", file=sys.stderr)
        return 2
    try:
        app = create_external_app(settings)
    except McpConfigError as exc:
        print(f"외부 MCP 서버를 시작하지 않습니다: {exc}", file=sys.stderr)
        return 1
    try:
        uvicorn.run(app, host="127.0.0.1", port=settings.mcp_port, log_level="info")
    except SchemaNotReady as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
