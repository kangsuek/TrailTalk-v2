from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette._utils import get_route_path
from starlette.routing import Match, Mount
from starlette.types import Scope

from app.api import health
from app.client_config import load_client_config
from app.config import Settings, settings
from app.db.migrate import upgrade_to_head
from app.db.session import create_engine_for, create_session_factory
from app.errors import install_error_handlers
from app.request_context import RequestContextMiddleware, configure_logging


class WebMount(Mount):
    """빌드된 웹 앱 마운트. /api 경로는 맡지 않아 라우터의 404·405가 그대로 나간다."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        path = get_route_path(scope)  # 프록시 root_path를 뺀 경로
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
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="TrailTalk", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.client_config = load_client_config(app_settings)  # 틀린 파일이면 시작하지 않는다
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    app.include_router(api)

    # 빌드된 웹 앱이 있으면 같은 서버에서 정적 파일로 서빙한다.
    # 라우터는 모두 이 마운트보다 먼저 등록해야 한다(뒤에 붙인 라우트는 가려진다).
    if app_settings.web_dist_dir.is_dir():
        static = StaticFiles(directory=app_settings.web_dist_dir, html=True)
        app.router.routes.append(WebMount("/", app=static, name="web"))
    return app


app = create_app()
