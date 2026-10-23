import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match, Mount
from starlette.types import Scope

from app.api import health, profile, sessions
from app.api.events import register_event_schemas
from app.client_config import load_client_config
from app.config import Settings, settings
from app.db.migrate import upgrade_to_head
from app.db.session import create_engine_for, create_session_factory
from app.errors import install_error_handlers
from app.jobs import idle
from app.llm.claude_cli import ClaudeCliBackend
from app.llm.manager import LlmSessionManager
from app.mcp.server import mount_mcp
from app.request_context import RequestContextMiddleware, configure_logging
from app.services.runtime import RuntimeRegistry


class WebMount(Mount):
    """빌드된 웹 앱 마운트. /api 경로는 맡지 않아 라우터의 404·405가 그대로 나간다."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        path = scope["path"]
        root_path = scope.get("root_path", "")  # 프록시 접두사는 뺀 경로로 판단한다
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :]
        if path == "/api" or path.startswith("/api/"):
            return Match.NONE, {}
        return super().matches(scope)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    app_settings = app_settings or settings
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app_settings.auto_migrate:
            await upgrade_to_head(app_settings.database_url)
        engine = create_engine_for(app_settings.database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        llm = LlmSessionManager(
            ClaudeCliBackend(app_settings),
            idle_timeout_s=app_settings.cli_idle_timeout_s,
            # 턴 시간 초과 처리가 끝날 여유를 더 둔다(스트림을 버린 경우의 안전망)
            stuck_timeout_s=app_settings.cli_turn_timeout_s + 30,
        )
        await llm.start()
        app.state.llm = llm
        idle_watch = asyncio.create_task(idle.run(app), name="idle-watch")
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            idle_watch.cancel()
            await asyncio.wait([idle_watch])
            await llm.shutdown()
            await engine.dispose()

    app = FastAPI(title="TrailTalk", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.client_config = load_client_config(app_settings)  # 틀린 파일이면 시작하지 않는다
    app.state.runtimes = RuntimeRegistry()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(profile.router)
    api.include_router(sessions.router)
    app.include_router(api)
    register_event_schemas(app)  # SSE 이벤트 스키마를 OpenAPI에 넣는다(웹 타입 생성)
    mcp = mount_mcp(app)  # 앱 도구 서버(/internal/mcp). 정적 마운트보다 먼저 붙인다

    # 빌드된 웹 앱이 있으면 같은 서버에서 정적 파일로 서빙한다.
    # 라우터는 모두 이 마운트보다 먼저 등록해야 한다(뒤에 붙인 라우트는 가려진다).
    if app_settings.web_dist_dir.is_dir():
        static = StaticFiles(directory=app_settings.web_dist_dir, html=True)
        app.router.routes.append(WebMount("/", app=static, name="web"))
    return app


app = create_app()
