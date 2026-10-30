"""외부 MCP 앱 보호 계층(MA-06): 노출 범위, 호출 기록, 속도·하루 상한, 확인 값, 쓰기 경합."""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr
from starlette.testclient import TestClient

from app.db.migrate import upgrade_to_head
from app.mcp_external.app import ToolRuntime, create_external_app
from app.mcp_external.guard import (
    CONFIRM_TTL_S,
    ConfirmSigner,
    DailyWriteCounter,
    SlidingWindowLimiter,
    ToolGuard,
)
from app.mcp_external.rpclog import parse_rpc
from tests.test_mcp_oauth import BASE, PASSWORD, full_flow

SECRET_TEXT = "비밀내용-절대로-기록되면-안-됨"
TOOL_CALL = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "echo", "arguments": {"item_id": "abcdef0123456789", "text": SECRET_TEXT}},
}


@pytest.fixture
def settings(make_settings, tmp_path):
    return make_settings(
        mcp_public_url=BASE,
        mcp_owner_password=SecretStr(PASSWORD),
        mcp_call_log=tmp_path / "logs" / "calls.jsonl",
    )


@pytest.fixture
async def ready(settings):
    await upgrade_to_head(settings.database_url)
    return settings


def register_echo(mcp, runtime: ToolRuntime) -> None:
    @mcp.tool()
    @runtime.guard.wrap(write=True, target_arg="item_id")
    async def echo(item_id: str, text: str) -> str:
        """시험용 도구."""
        if text == "boom":
            raise ToolError("실패")
        return f"받음: {text}"


@pytest.fixture
def client(ready):
    app = create_external_app(ready, register_tools=register_echo)
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        yield c


def call(client, token, text=SECRET_TEXT, item_id="abcdef0123456789"):
    body = {
        **TOOL_CALL,
        "params": {"name": "echo", "arguments": {"item_id": item_id, "text": text}},
    }
    return client.post(
        "/mcp",
        json=body,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )


# --- 노출 범위 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/api/journal", "/internal/mcp/", "/", "/journal", "/assets/x.js", "/docs"],
)
def test_only_mcp_and_oauth_paths_are_served(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path, json={}).status_code in (404, 405)


def test_mcp_requires_token(client):
    response = client.post("/mcp", json=TOOL_CALL, headers={"Accept": "application/json"})
    assert response.status_code == 401


def test_other_host_header_is_rejected(client):
    _, tokens = full_flow(client)
    response = client.post(
        "/mcp",
        json=TOOL_CALL,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {tokens['access_token']}",
            "Host": "evil.example",
        },
    )
    assert response.status_code in (400, 403, 421)


# --- 호출 기록: 내용이 남지 않는다 -------------------------------------------------------------


def test_logs_have_no_arguments_or_results(client, settings):
    _, tokens = full_flow(client)
    assert call(client, tokens["access_token"]).status_code == 200
    assert call(client, tokens["access_token"], text="boom").status_code == 200  # isError 결과
    calls = (settings.mcp_call_log).read_text(encoding="utf-8")
    rpc = (settings.mcp_call_log.with_name("mcp-rpc.jsonl")).read_text(encoding="utf-8")
    for text in (calls, rpc):
        assert SECRET_TEXT not in text
        assert "받음" not in text
        assert tokens["access_token"] not in text
    lines = [json.loads(line) for line in calls.splitlines()]
    assert [(r["tool"], r["ok"], r["target"]) for r in lines] == [
        ("echo", True, "abcdef01"),
        ("echo", False, "abcdef01"),
    ]
    assert set(lines[0]) == {"at", "tool", "ok", "ms", "target"}
    rpc_lines = [json.loads(line) for line in rpc.splitlines()]
    assert any(r["tool"] == "echo" and r["error"] is True for r in rpc_lines)


def test_parse_rpc():
    assert parse_rpc(json.dumps(TOOL_CALL).encode()) == ("tools/call", "echo")
    assert parse_rpc(b"[1]") == ("batch", None)
    assert parse_rpc(b"not json") == (None, None)


# --- 속도 제한·하루 상한 -----------------------------------------------------------------------


def test_sliding_window_limit():
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=3, window_s=60, now=lambda: now[0])
    assert [limiter.allow() for _ in range(4)] == [True, True, True, False]
    now[0] = 59.9
    assert not limiter.allow()
    now[0] = 60.1  # 첫 호출이 창을 벗어났다
    assert limiter.allow()


def test_default_limits_match_spec():
    limiter = SlidingWindowLimiter(now=lambda: 0.0)
    assert sum(limiter.allow() for _ in range(100)) == 60


def test_daily_write_limit_resets_next_local_day():
    tz = ZoneInfo("Asia/Seoul")
    now = [datetime(2026, 10, 30, 14, 0, tzinfo=UTC)]  # 서울 23시
    counter = DailyWriteCounter(limit=2, tz=tz, now=lambda: now[0])
    assert [counter.allow() for _ in range(3)] == [True, True, False]
    now[0] += timedelta(hours=2)  # 서울 자정을 넘김
    assert counter.allow()
    assert DailyWriteCounter(tz=tz).limit == 200


async def test_guard_errors_are_tool_errors_and_logged(tmp_path):
    guard = ToolGuard(
        call_log=tmp_path / "c.jsonl",
        limiter=SlidingWindowLimiter(limit=2, window_s=60, now=lambda: 0.0),
        writes=DailyWriteCounter(limit=1),
    )

    @guard.wrap(write=True)
    async def write_tool() -> str:
        return "ok"

    @guard.wrap()
    async def read_tool() -> str:
        return "ok"

    assert await write_tool() == "ok"
    with pytest.raises(ToolError, match="한도"):
        await write_tool()  # 하루 쓰기 상한
    with pytest.raises(ToolError, match="너무 많습니다"):
        await read_tool()  # 세 번째 호출은 속도 제한
    ok = [json.loads(line)["ok"] for line in (tmp_path / "c.jsonl").read_text().splitlines()]
    assert ok == [True, False, False]


# --- 확인 값 ---------------------------------------------------------------------------------


def test_confirm_token_binds_action_target_and_expires():
    now = [1_000_000.0]
    signer = ConfirmSigner(PASSWORD, now=lambda: now[0])
    token = signer.issue("delete_note", "note-1")
    assert signer.valid(token, "delete_note", "note-1")
    assert not signer.valid(token, "delete_journal", "note-1")  # 다른 행동
    assert not signer.valid(token, "delete_note", "note-2")  # 다른 대상
    assert not signer.valid("", "delete_note", "note-1")
    assert not signer.valid("abc.def", "delete_note", "note-1")
    expires, _, sig = token.partition(".")
    assert not signer.valid(f"{int(expires) + 999}.{sig}", "delete_note", "note-1")  # 만료 늘리기
    now[0] += CONFIRM_TTL_S - 1
    assert signer.valid(token, "delete_note", "note-1")
    now[0] += 2
    assert not signer.valid(token, "delete_note", "note-1")  # 5분 만료


def test_confirm_token_survives_restart_but_not_password_change():
    now = lambda: 1_000_000.0  # noqa: E731
    token = ConfirmSigner(PASSWORD, now=now).issue("delete_note", "n1")
    assert ConfirmSigner(PASSWORD, now=now).valid(token, "delete_note", "n1")  # 재시작
    assert not ConfirmSigner(PASSWORD + "x", now=now).valid(token, "delete_note", "n1")


# --- 두 프로세스 쓰기 경합 -----------------------------------------------------------------------

WRITER = """
import asyncio, sys
from app.db.models import ConversationSession, Note, NoteKind, SessionMode, SessionStatus
from app.db.session import create_engine_for, create_session_factory

async def main(url, session_id, tag):
    engine = create_engine_for(url)
    factory = create_session_factory(engine)
    for i in range(40):
        async with factory() as db:
            db.add(Note(session_id=session_id, kind=NoteKind.IDEA, content=f"{tag}-{i}"))
            await db.commit()
    await engine.dispose()

asyncio.run(main(*sys.argv[1:]))
"""


async def test_two_processes_can_write_the_same_sqlite_file(ready):
    from sqlalchemy import func, select

    from app.db.models import ConversationSession, Note, SessionMode, SessionStatus
    from app.db.session import create_engine_for, create_session_factory

    engine = create_engine_for(ready.database_url)
    factory = create_session_factory(engine)
    async with factory() as db:
        convo = ConversationSession(mode=SessionMode.TEXT, status=SessionStatus.ENDED)
        db.add(convo)
        await db.commit()
        session_id = convo.id

    async def spawn(tag):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            WRITER,
            ready.database_url,
            session_id,
            tag,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        return proc.returncode, err.decode()

    results = await asyncio.gather(spawn("a"), spawn("b"))
    assert results == [(0, ""), (0, "")], results
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Note)) == 80
    await engine.dispose()


# --- 리뷰 반영: Host 검사, 확인 값 경계, 로그 회전, 로그인 대기 상한 ---------------------


@pytest.mark.parametrize(
    "path", ["/login?req=x", "/.well-known/oauth-authorization-server", "/sw.js"]
)
def test_host_check_covers_oauth_paths(client, path):
    assert client.get(path, headers={"Host": "evil.example"}).status_code == 421
    assert client.get(path).status_code != 421  # localhost(시험용)는 통과


def test_confirm_token_rejects_huge_numbers_and_ambiguous_ids():
    signer = ConfirmSigner(PASSWORD, now=lambda: 1_000_000.0)
    assert not signer.valid("9" * 5000 + ".sig", "delete_note", "n1")  # ValueError 없이 거절
    token = signer.issue("delete_note", "a|b")
    assert signer.valid(token, "delete_note", "a|b")
    assert not signer.valid(token, "delete_note|a", "b")  # 구분자 이동으로 속일 수 없다


def test_log_rotates_instead_of_stopping(tmp_path, monkeypatch):
    from app.mcp_external import guard

    monkeypatch.setattr(guard, "MAX_LOG_BYTES", 100)
    path = tmp_path / "calls.jsonl"
    for i in range(20):
        guard.append_log_line(path, {"i": i, "pad": "x" * 30})
    assert path.exists() and path.with_name("calls.jsonl.1").exists()
    last = json.loads(path.read_text().splitlines()[-1])
    assert last["i"] == 19  # 상한을 넘어도 새 기록이 계속 남는다


def test_pending_login_requests_are_capped(ready, monkeypatch):
    from app.mcp_external import oauth

    monkeypatch.setattr(oauth, "MAX_PENDING", 2)
    app = create_external_app(ready)
    from tests.test_mcp_oauth import authorize, pkce, register

    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        client_id = register(c).json()["client_id"]
        first = [authorize(c, client_id, pkce()[1]).headers["location"] for _ in range(2)]
        assert all("/login?req=" in loc for loc in first)
        third = authorize(c, client_id, pkce()[1]).headers["location"]
        assert "/login" not in third and "temporarily_unavailable" in third
