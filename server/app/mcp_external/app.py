"""외부 MCP 앱(Claude 앱 연계): MCP(/mcp)와 OAuth 경로만 가진 별도 ASGI 앱.

기존 서버(/api·웹·/internal)와 다른 포트로 띄우고 Funnel은 이 포트만 가리킨다
(docs/MCP/design.md 1.1).
DB와 서비스 계층(app/services)은 기존 서버와 같은 파일·같은 코드를 쓴다. 스키마는 기존 서버가
맞추므로(Alembic) 이 앱은 마이그레이션하지 않고, head가 아니면 시작을 거부한다.
"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import Settings
from app.db.migrate import alembic_config, current_revision
from app.db.session import create_engine_for, create_session_factory
from app.mcp_external.config import MCP_PATH, McpConfig
from app.mcp_external.login import LoginLimiter, make_login_handler
from app.mcp_external.oauth import SCOPE_MCP, SCOPES, OwnerOAuthProvider

logger = logging.getLogger("trailtalk.mcp_external")
SERVER_NAME = "trailtalk"

# 같은 호스트에서 v1 TrailTalk PWA를 쓴 브라우저에는 v1 서비스 워커(/sw.js, scope /)가 남아 있어
# /authorize·/login 같은 탐색을 가로챌 수 있다. 브라우저가 /sw.js를 갱신하러 오면 이 스크립트로
# 서비스 워커와 캐시를 스스로 지우게 한다.
SW_KILL_SCRIPT = """\
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil((async () => {
  for (const key of await caches.keys()) await caches.delete(key);
  await self.registration.unregister();
  for (const client of await self.clients.matchAll({ type: 'window' })) client.navigate(client.url);
})()));
"""


async def serve_sw_kill(request: Request) -> Response:
    return Response(
        SW_KILL_SCRIPT, media_type="text/javascript", headers={"Cache-Control": "no-store"}
    )


class SchemaNotReady(RuntimeError):
    """DB가 최신 스키마가 아니다. 기존 서버를 먼저 띄워 마이그레이션해야 한다."""


async def ensure_schema_ready(database_url: str) -> None:
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()
    if await current_revision(database_url) != head:
        raise SchemaNotReady("DB가 최신 스키마가 아닙니다. 기존 서버(./run.sh)를 먼저 띄우세요.")


def build_mcp_server(
    config: McpConfig,
    provider: OwnerOAuthProvider,
    limiter: LoginLimiter,
    register_tools: Callable[[MCPServer], None] | None = None,
) -> MCPServer:
    auth = AuthSettings(
        issuer_url=config.public_url,
        resource_server_url=config.resource_url,
        client_registration_options=ClientRegistrationOptions(enabled=True, default_scopes=SCOPES),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[SCOPE_MCP],
        validate_token_resource=True,
    )
    mcp = MCPServer(SERVER_NAME, subscriptions=False, auth=auth, auth_server_provider=provider)
    mcp.custom_route("/sw.js", methods=["GET"])(serve_sw_kill)
    mcp.custom_route("/login", methods=["GET", "POST"])(
        make_login_handler(provider, limiter, config.owner_password)
    )
    if register_tools is not None:
        register_tools(mcp)
    return mcp


def create_external_app(
    settings: Settings,
    *,
    config: McpConfig | None = None,
    check_schema: bool = True,
    register_tools: Callable[[MCPServer], None] | None = None,
    limiter: LoginLimiter | None = None,
) -> Starlette:
    """외부 MCP 앱을 만든다. 설정이 틀리면 McpConfigError, 스키마가 오래됐으면 SchemaNotReady."""
    config = config or McpConfig.from_settings(settings)
    engine = create_engine_for(settings.database_url)
    session_factory = create_session_factory(engine)
    provider = OwnerOAuthProvider(
        session_factory, config.resource_url, config.allowed_redirects, config.max_clients
    )
    mcp = build_mcp_server(config, provider, limiter or LoginLimiter(), register_tools)
    # 공개 호스트명으로만 받는다(DNS 리바인딩 방어). 로컬 시험용 localhost도 허용한다
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[config.public_host, "127.0.0.1:*", "localhost:*"],
    )
    inner: Starlette = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: ASGIApp):
        if check_schema:
            await ensure_schema_ready(settings.database_url)
        async with inner_lifespan(app):
            yield
        await engine.dispose()

    inner.router.lifespan_context = lifespan
    inner.state.session_factory = session_factory
    inner.state.config = config
    return inner
