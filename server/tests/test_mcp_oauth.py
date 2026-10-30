"""외부 MCP 앱의 OAuth: 등록 → 인가 → 로그인 → 토큰 → MCP 호출 → 회전·폐기·만료(MA-05).

`trailTalk-MCP/tests/test_oauth.py`를 v2 설정·앱으로 옮겼다."""

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from app.db.migrate import upgrade_to_head
from app.mcp_external import login as login_module
from app.mcp_external.app import SchemaNotReady, create_external_app
from app.mcp_external.config import CLAUDE_CALLBACK, McpConfig, McpConfigError
from app.mcp_external.login import LOCK_FAILS, LoginLimiter
from app.mcp_external.oauth import ACCESS_TTL_S, REFRESH_TTL_S

PASSWORD = "owner-password-123"
BASE = "http://localhost"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


@pytest.fixture(autouse=True)
def no_fail_delay(monkeypatch):
    monkeypatch.setattr(login_module, "FAIL_DELAY_S", 0.0)
    original = login_module.make_login_handler

    def fast(provider, limiter, owner_password, fail_delay_s=0.0):
        return original(provider, limiter, owner_password, 0.0)

    monkeypatch.setattr("app.mcp_external.app.make_login_handler", fast)


@pytest.fixture
def settings(make_settings, tmp_path):
    return make_settings(
        mcp_public_url=BASE,
        mcp_owner_password=PASSWORD,
        mcp_call_log=tmp_path / "calls.jsonl",
    )


@pytest.fixture
async def ready(settings):
    await upgrade_to_head(settings.database_url)
    return settings


@pytest.fixture
def client(ready):
    app = create_external_app(ready)
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        yield c


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def register(client, redirect=CLAUDE_CALLBACK, scope=None):
    body = {
        "redirect_uris": [redirect],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "Claude",
    }
    if scope:
        body["scope"] = scope
    return client.post("/register", json=body)


def authorize(client, client_id, challenge, **extra):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "scope": "mcp offline_access",
        "resource": f"{BASE}/mcp",
        **extra,
    }
    return client.get("/authorize", params=params)


def login(client, req, password=PASSWORD):
    return client.post("/login", data={"req": req, "password": password})


def req_of(response) -> str:
    location = response.headers["location"]
    assert location.startswith("/login?req="), location
    return parse_qs(urlparse(location).query)["req"][0]


def code_of(response) -> str:
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


def exchange(client, client_id, code, verifier, **extra):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": CLAUDE_CALLBACK,
            "code_verifier": verifier,
            **extra,
        },
    )


def full_flow(client) -> tuple[str, dict]:
    client_id = register(client).json()["client_id"]
    verifier, challenge = pkce()
    req = req_of(authorize(client, client_id, challenge))
    code = code_of(login(client, req))
    response = exchange(client, client_id, code, verifier)
    assert response.status_code == 200, response.text
    return client_id, response.json()


def call_mcp(client, token=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", json=INIT, headers=headers)


def refresh(client, client_id, refresh_token):
    return client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )


# --- 발견(디스커버리) ------------------------------------------------------------------------


def test_unauthenticated_mcp_points_to_resource_metadata(client):
    response = call_mcp(client)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert (
        'resource_metadata="http://localhost/.well-known/oauth-protected-resource/mcp"' in challenge
    )


def test_metadata_documents(client):
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == f"{BASE}/mcp"
    assert resource["authorization_servers"] == [BASE]
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == BASE
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["registration_endpoint"].endswith("/register")


# --- 전체 흐름 -------------------------------------------------------------------------------


def test_full_flow_then_mcp_call(client):
    _, tokens = full_flow(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == ACCESS_TTL_S
    assert tokens["refresh_token"]
    assert call_mcp(client, tokens["access_token"]).status_code == 200
    assert call_mcp(client, "not-a-token").status_code == 401


def test_register_always_includes_our_scopes(client):
    info = register(client, scope="something-else").json()
    assert info["scope"].split() == ["mcp", "offline_access", "something-else"]
    assert register(client).json()["scope"] == "mcp offline_access"


def test_token_only_has_hashes_in_db(ready, client):
    import sqlite3

    _, tokens = full_flow(client)
    db = sqlite3.connect(ready.database_url.split("///")[1])
    stored = " ".join(row[0] for row in db.execute("select token_hash from oauth_token"))
    assert tokens["access_token"] not in stored and tokens["refresh_token"] not in stored


# --- 거부해야 하는 것 ------------------------------------------------------------------------


def test_register_rejects_unlisted_redirect(client):
    response = register(client, redirect="https://evil.example/cb")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_limit_prunes_unused_then_refuses_when_all_in_use(ready):
    app = create_external_app(ready.model_copy(update={"mcp_max_clients": 2}))
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        first = register(c).json()["client_id"]
        register(c)
        third = register(c)  # 토큰 없는 오래된 등록을 지우고 받는다
        assert third.status_code == 201
        assert c.get(f"/authorize?client_id={first}").status_code in (400, 404, 302)
    app = create_external_app(ready.model_copy(update={"mcp_max_clients": 1}))
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        full_flow(c)  # 유일한 클라이언트가 토큰을 쥐고 있다
        response = register(c)
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_client_metadata"


def test_authorize_rejects_other_resource(client):
    client_id = register(client).json()["client_id"]
    _, challenge = pkce()
    response = authorize(client, client_id, challenge, resource="http://evil.example/mcp")
    assert "/login" not in response.headers["location"]
    assert "error=invalid_target" in response.headers["location"]


def test_authorize_requires_state(client):
    client_id = register(client).json()["client_id"]
    _, challenge = pkce()
    response = authorize(client, client_id, challenge, state="")
    assert "/login" not in response.headers.get("location", "")


def test_authorize_requires_pkce_s256(client):
    client_id = register(client).json()["client_id"]
    response = authorize(client, client_id, "x" * 43, code_challenge_method="plain")
    assert response.status_code in (302, 400)
    assert "/login" not in response.headers.get("location", "")


def test_wrong_password_gives_no_code(client):
    client_id = register(client).json()["client_id"]
    req = req_of(authorize(client, client_id, pkce()[1]))
    response = login(client, req, "wrong-password-xyz")
    assert response.status_code == 401
    assert "location" not in response.headers


def test_lockout_after_repeated_failures(client):
    client_id = register(client).json()["client_id"]
    req = req_of(authorize(client, client_id, pkce()[1]))
    for _ in range(LOCK_FAILS):
        assert login(client, req, "wrong-password-xyz").status_code == 401
    locked = login(client, req, PASSWORD)  # 맞는 비밀번호여도 잠금 중이면 거부
    assert locked.status_code == 429
    assert "location" not in locked.headers


def test_failed_login_is_delayed(ready, monkeypatch):
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.undo()  # autouse가 지연을 0으로 덮은 것을 되돌린다
    monkeypatch.setattr(login_module.asyncio, "sleep", fake_sleep)
    app = create_external_app(ready)
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        client_id = register(c).json()["client_id"]
        req = req_of(authorize(c, client_id, pkce()[1]))
        assert login(c, req, "wrong-password-xyz").status_code == 401
    assert delays == [login_module.FAIL_DELAY_S]


def test_login_with_unknown_or_reused_request(client):
    assert client.get("/login?req=nope").status_code == 400
    assert login(client, "nope").status_code == 400
    client_id = register(client).json()["client_id"]
    req = req_of(authorize(client, client_id, pkce()[1]))
    assert login(client, req).status_code == 303
    assert login(client, req).status_code == 400  # 같은 요청으로 코드를 두 번 받을 수 없다


def test_login_page_is_escaped_and_not_cacheable(client):
    client_id = register(client).json()["client_id"]
    req = req_of(authorize(client, client_id, pkce()[1]))
    page = client.get(f"/login?req={req}")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_pkce_mismatch_rejected(client):
    client_id = register(client).json()["client_id"]
    _, challenge = pkce()
    code = code_of(login(client, req_of(authorize(client, client_id, challenge))))
    response = exchange(client, client_id, code, "wrong-verifier-" + "a" * 40)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_code_is_single_use(client):
    client_id = register(client).json()["client_id"]
    verifier, challenge = pkce()
    code = code_of(login(client, req_of(authorize(client, client_id, challenge))))
    assert exchange(client, client_id, code, verifier).status_code == 200
    again = exchange(client, client_id, code, verifier)
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


def test_code_bound_to_its_client(client):
    first = register(client).json()["client_id"]
    second = register(client).json()["client_id"]
    verifier, challenge = pkce()
    code = code_of(login(client, req_of(authorize(client, first, challenge))))
    assert exchange(client, second, code, verifier).status_code == 400


# --- 회전·폐기·만료 --------------------------------------------------------------------------


def test_refresh_rotates_and_old_tokens_die(client):
    client_id, first = full_flow(client)
    response = refresh(client, client_id, first["refresh_token"])
    assert response.status_code == 200, response.text
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert call_mcp(client, second["access_token"]).status_code == 200
    assert call_mcp(client, first["access_token"]).status_code == 401
    reuse = refresh(client, client_id, first["refresh_token"])
    assert reuse.status_code == 400
    assert reuse.json()["error"] == "invalid_grant"


def test_revoke_kills_the_pair(client):
    client_id, tokens = full_flow(client)
    response = client.post(
        "/revoke",
        data={"token": tokens["refresh_token"], "client_id": client_id, "client_secret": ""},
    )
    assert response.status_code == 200
    assert call_mcp(client, tokens["access_token"]).status_code == 401
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 400


def test_access_token_expires(client, monkeypatch):
    client_id, tokens = full_flow(client)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + ACCESS_TTL_S + 5)
    assert call_mcp(client, tokens["access_token"]).status_code == 401
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 200


def test_refresh_token_expires(client, monkeypatch):
    client_id, tokens = full_flow(client)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + REFRESH_TTL_S + 5)
    response = refresh(client, client_id, tokens["refresh_token"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_code_expires(client, monkeypatch):
    client_id = register(client).json()["client_id"]
    verifier, challenge = pkce()
    code = code_of(login(client, req_of(authorize(client, client_id, challenge))))
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 400)
    assert exchange(client, client_id, code, verifier).status_code == 400


def test_pending_login_expires(client, monkeypatch):
    client_id = register(client).json()["client_id"]
    req = req_of(authorize(client, client_id, pkce()[1]))
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 700)
    assert login(client, req).status_code == 400


def test_tokens_survive_server_restart(ready):
    app1 = create_external_app(ready)
    with TestClient(app1, base_url=BASE, follow_redirects=False) as c1:
        client_id, tokens = full_flow(c1)
    app2 = create_external_app(ready)
    with TestClient(app2, base_url=BASE, follow_redirects=False) as c2:
        assert call_mcp(c2, tokens["access_token"]).status_code == 200
        assert refresh(c2, client_id, tokens["refresh_token"]).status_code == 200


async def test_revoke_all_removes_tokens_and_clients(ready, client):
    from app.mcp_external.oauth import revoke_all

    client_id, tokens = full_flow(client)
    assert await revoke_all(client.app.state.session_factory) == 2  # 액세스+리프레시
    assert call_mcp(client, tokens["access_token"]).status_code == 401
    assert refresh(client, client_id, tokens["refresh_token"]).status_code in (400, 401)


def test_login_limiter_window():
    now = [1000.0]
    limiter = LoginLimiter(lambda: now[0])
    for _ in range(LOCK_FAILS):
        limiter.fail()
    assert limiter.locked()
    now[0] += 601
    assert not limiter.locked()


# --- 설정·스키마 검증 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"mcp_public_url": ""},
        {"mcp_public_url": "http://example.com"},
        {"mcp_public_url": "https://example.com/"},
        {"mcp_public_url": "https://example.com/mcp"},
        {"mcp_owner_password": SecretStr("short")},
        {"mcp_owner_password": None},
    ],
)
def test_config_validation(settings, overrides):
    with pytest.raises(McpConfigError):
        McpConfig.from_settings(settings.model_copy(update=overrides))


def test_config_defaults_to_claude_callback(settings):
    config = McpConfig.from_settings(settings)
    assert config.allowed_redirects == (CLAUDE_CALLBACK,)
    assert config.resource_url == f"{BASE}/mcp"


def test_refuses_to_start_on_stale_schema(settings):
    app = create_external_app(settings)  # DB가 비어 있다(마이그레이션 전)
    with pytest.raises(SchemaNotReady), TestClient(app, base_url=BASE):
        pass


# --- v1 서비스 워커 자기 해제 -------------------------------------------------------------------


def test_sw_kill_script_is_public_and_uncached(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    for needle in ("skipWaiting", "caches.delete", "registration.unregister", "client.navigate"):
        assert needle in response.text
