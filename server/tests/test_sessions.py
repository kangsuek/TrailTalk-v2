"""세션·턴 API(S1-08). 녹화를 재생하는 가짜 CLI로 전체 흐름을 확인한다."""

import inspect
import json
import threading
import time
from contextlib import aclosing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import text as sql_text

from app.api.events import parse_sse_data
from app.db.models import (
    ConversationSession,
    Note,
    NoteKind,
    Persona,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.llm.events import TextDelta, TurnStarted
from app.main import create_app
from app.persona.loader import load_persona

FAKE_CLI_SESSION_ID = "00000000-0000-4000-8000-00000000fake"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def api(fake_cli, home, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    app = create_app(fake_cli.settings)
    with TestClient(app) as client:
        client.fake_cli = fake_cli
        client.persona_name = load_persona(
            fake_cli.settings.persona_dir, "jenny"
        ).persona.name  # 이름은 YAML에서만 가져온다
        yield client


def events_of(response) -> list:
    """SSE 본문을 이벤트 목록으로. splitlines는 U+2028에서도 줄을 나누므로 쓰지 않는다."""
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.split("\n\n"):
        lines = block.split("\n")
        data = [line[len("data: ") :] for line in lines if line.startswith("data: ")]
        if data:
            event = parse_sse_data(data[0])
            assert f"event: {event.type}" in lines
            events.append(event)
    return events


def start(api, mode: str = "text") -> dict:
    response = api.post("/api/sessions", json={"mode": mode})
    assert response.status_code == 201, response.text
    return response.json()


def turn(api, session_id: str, text: str) -> list:
    response = api.post(f"/api/sessions/{session_id}/turns", json={"text": text})
    assert response.status_code == 200, response.text
    return events_of(response)


def load(api, fn):
    async def run():
        async with api.app.state.session_factory() as db:
            return await fn(db)

    return api.portal.call(run)


def turns_of(api, session_id: str) -> list[Turn]:
    async def fn(db):
        rows = await db.execute(
            select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq)
        )
        return list(rows.scalars())

    return load(api, fn)


def session_row(api, session_id: str) -> ConversationSession | None:
    return load(api, lambda db: db.get(ConversationSession, session_id))


class HookedSession:
    """실제(가짜 CLI) 세션의 이벤트를 지나가며 훔쳐보는 래퍼. MCP 도구의 부수 효과를 흉내 낸다."""

    def __init__(self, inner, on_event) -> None:
        self._inner = inner
        self._on_event = on_event

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def send(self, text):
        async with aclosing(self._inner.send(text)) as stream:
            async for event in stream:
                result = self._on_event(event)
                if inspect.isawaitable(result):
                    await result
                yield event


def hook_llm(api, on_event) -> None:
    manager = api.app.state.llm
    original = manager.get

    async def get(key, **kwargs):
        return HookedSession(await original(key, **kwargs), on_event)

    manager.get = get


def test_start_session_saves_greeting(api):
    body = start(api)
    session = body["session"]
    assert session["mode"] == "text" and session["status"] == "active"
    persona = load_persona(api.fake_cli.settings.persona_dir, "jenny").persona
    assert body["persona"] == {
        "id": "jenny",
        "name": api.persona_name,
        "ack": [{"text": text, "audio": None} for text in persona.ack],
    }
    assert body["greeting"]["audio"] is None
    assert (
        body["greeting"]["text"]
        == "사과는 보통 빨간색이지만 품종에 따라 초록색이나 노란색도 있습니다."
    )
    [greeting] = turns_of(api, session["id"])
    assert greeting.greeting is True
    assert greeting.id == body["greeting"]["turn_id"]
    assert greeting.seq == 0 and greeting.role is TurnRole.ASSISTANT
    assert session_row(api, session["id"]).cli_session_id == FAKE_CLI_SESSION_ID

    args = api.fake_cli.records()[-1]["args"]
    prompt = args[args.index("--system-prompt") + 1]
    assert "앱 화면의 텍스트 대화" in prompt
    assert "사용자님" not in prompt  # 호칭은 시스템 프롬프트에 넣지 않는다(Spec 5.7)
    assert "--mcp-config" in args
    assert api.app.state.runtimes.get(session["id"]) is not None


def test_persona_yaml_change_needs_no_code_change(fake_cli, home, monkeypatch, tmp_path):
    """NFR-08: YAML만 바꿔도 캐릭터 이름·말투가 화면 응답과 프롬프트에 반영된다."""
    import yaml

    source = fake_cli.settings.persona_dir / f"{fake_cli.settings.default_persona}.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    old_name = data["name"]
    data["name"] = "테스트캐릭터"
    data["speech_style"]["register"] = "차분하고 느긋한 존댓말"
    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / source.name).write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")

    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    settings = fake_cli.settings.model_copy(update={"persona_dir": personas})
    with TestClient(create_app(settings)) as client:
        body = client.post("/api/sessions", json={"mode": "voice"}).json()
    assert body["persona"]["name"] == "테스트캐릭터"
    args = fake_cli.records()[-1]["args"]
    prompt = args[args.index("--system-prompt") + 1]
    assert "너의 이름: 테스트캐릭터" in prompt and "말투: 차분하고 느긋한 존댓말" in prompt
    assert old_name not in prompt


def test_turns_stream_sentences_and_save_both_sides(api):
    session_id = start(api)["session"]["id"]
    events = turn(api, session_id, "  바나나는?  ")
    assert [e.type for e in events] == ["turn", "sentence", "done"]
    first, sentence, done = events
    assert sentence.index == 0 and sentence.text == "바나나는 보통 노란색입니다."
    assert done.turn_id == first.turn_id and done.text == sentence.text
    assert done.session_status == "active" and not done.interrupted

    events = turn(api, session_id, "둘 다 말해줘")
    assert events[-1].text == "사과와 바나나입니다."
    rows = turns_of(api, session_id)
    assert [(t.seq, t.role, t.text) for t in rows] == [
        (0, TurnRole.ASSISTANT, rows[0].text),
        (1, TurnRole.USER, "바나나는?"),
        (2, TurnRole.ASSISTANT, "바나나는 보통 노란색입니다."),
        (3, TurnRole.USER, "둘 다 말해줘"),
        (4, TurnRole.ASSISTANT, "사과와 바나나입니다."),
    ]
    assert rows[2].id == first.turn_id


THREE_SENTENCES = "첫 문장입니다. 둘째 문장이에요. 셋째 문장이죠."


def test_reply_is_committed_sentence_by_sentence(api):
    """문장을 보내기 전에 커밋한다. 끝나기 전까지는 끊긴 답변(interrupted)으로 남는다."""
    session_id = start(api)["session"]["id"]
    seen: list[tuple[str, bool]] = []

    async def snapshot(event):
        if isinstance(event, TextDelta):
            async with api.app.state.session_factory() as db:  # 다른 연결: 커밋된 것만 보인다
                row = await db.scalar(
                    select(Turn).where(Turn.session_id == session_id, Turn.seq == 2)
                )
            if row is not None and (row.text, row.interrupted) not in seen:
                seen.append((row.text, row.interrupted))

    hook_llm(api, snapshot)
    events = turn(api, session_id, f"__say__:{THREE_SENTENCES}")
    assert [e.text for e in events if e.type == "sentence"] == [
        "첫 문장입니다.",
        "둘째 문장이에요.",
        "셋째 문장이죠.",
    ]
    assert seen == [("첫 문장입니다.", True), ("첫 문장입니다. 둘째 문장이에요.", True)]
    reply = turns_of(api, session_id)[2]
    assert reply.id == events[0].turn_id
    assert (reply.text, reply.interrupted) == (THREE_SENTENCES, False)


def test_cli_crash_keeps_sent_sentences(api):
    session_id = start(api)["session"]["id"]
    events = turn(api, session_id, f"__say_then_crash__:{THREE_SENTENCES}")
    assert events[-1].type == "error"
    sent = [e.text for e in events if e.type == "sentence"]
    assert sent[:2] == ["첫 문장입니다.", "둘째 문장이에요."]
    reply = turns_of(api, session_id)[2]
    assert (reply.role, reply.text, reply.interrupted) == (
        TurnRole.ASSISTANT,
        " ".join(sent),
        True,
    )
    assert turn(api, session_id, "괜찮아?")[-1].type == "done"
    assert [t.seq for t in turns_of(api, session_id)] == [0, 1, 2, 3, 4]


def test_tool_events_use_public_names(api, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "tool_call")
    session_id = start(api)["session"]["id"]
    events = turn(api, session_id, "등산로 쓰레기통 지도 아이디어, 이거 저장해줘.")
    tools = [e for e in events if e.type == "tool"]
    assert [t.phase for t in tools] == ["start", "call", "end"]
    assert {t.name for t in tools} == {"save_note"}
    assert len({t.tool_use_id for t in tools}) == 1
    assert tools[1].input == {"kind": "idea", "content": "등산로에 쓰레기통 지도를 만드는 아이디어"}
    assert not tools[2].is_error
    assert tools[2].summary.model_dump() == {"kind": "result", "result": "저장 완료"}
    types = [e.type for e in events]
    assert types[0] == "turn" and types[-1] == "done"
    assert types.index("sentence") > types.index("tool")  # 답변 문장은 도구 뒤에 온다


def test_turn_errors_before_stream_are_json(api):
    response = api.post("/api/sessions/nope/turns", json={"text": "안녕"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    session_id = start(api)["session"]["id"]
    for text in ["", "   ", "가" * 4001]:
        response = api.post(f"/api/sessions/{session_id}/turns", json={"text": text})
        assert response.status_code == 422, text


def test_turn_in_progress_is_rejected(api):
    session_id = start(api)["session"]["id"]
    lock = api.app.state.runtimes.get(session_id).turn_lock
    api.portal.call(lock.acquire)
    try:
        response = api.post(f"/api/sessions/{session_id}/turns", json={"text": "안녕"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "turn_in_progress"
    finally:
        api.portal.call(lock.release)
    assert turn(api, session_id, "안녕")[-1].type == "done"


def test_end_session_closes_cli_and_deletes_its_transcript(api, home):
    session_id = start(api)["session"]["id"]
    projects = home / ".claude" / "projects" / "-tmp-cli"
    projects.mkdir(parents=True)
    transcript = projects / f"{FAKE_CLI_SESSION_ID}.jsonl"
    other = projects / "11111111-2222-3333-4444-555555555555.jsonl"
    transcript.write_text("{}")
    other.write_text("{}")

    response = api.post(f"/api/sessions/{session_id}/end")
    assert response.status_code == 200
    closed = response.json()["session"]
    assert closed["status"] == "ended" and closed["ended_at"]
    assert not transcript.exists() and other.exists()
    assert api.app.state.llm.active_count == 0
    assert api.app.state.runtimes.get(session_id) is None

    again = api.post(f"/api/sessions/{session_id}/end")  # 두 번 끝내도 같은 결과
    assert again.status_code == 200
    assert again.json()["session"]["ended_at"] == closed["ended_at"]
    response = api.post(f"/api/sessions/{session_id}/turns", json={"text": "안녕"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_ended"
    assert api.post("/api/sessions/nope/end").status_code == 404


def test_tool_requested_pause_then_resume(api):
    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)
    seen_turn_ids = []
    pausing = [True]

    def pause_during_turn(event):
        if isinstance(event, TurnStarted) and pausing[0]:
            seen_turn_ids.append(runtime.current_user_turn_id)
            runtime.requested_status = SessionStatus.PAUSED  # pause_session 도구 호출 흉내

    hook_llm(api, pause_during_turn)
    done = turn(api, session_id, "잠깐 쉬자")[-1]
    assert done.session_status == "paused"
    assert session_row(api, session_id).status is SessionStatus.PAUSED
    user_turn = turns_of(api, session_id)[1]
    assert seen_turn_ids == [user_turn.id]  # 도구가 노트를 이 사용자 턴에 연결한다
    assert runtime.current_user_turn_id is None and runtime.requested_status is None

    pausing[0] = False
    assert turn(api, session_id, "다시 하자")[-1].session_status == "active"
    assert session_row(api, session_id).status is SessionStatus.ACTIVE


def test_tool_requested_end_closes_session(api):
    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)

    def end_during_turn(event):
        if isinstance(event, TurnStarted):
            runtime.requested_status = SessionStatus.ENDED

    hook_llm(api, end_during_turn)
    done = turn(api, session_id, "오늘은 여기까지")[-1]
    assert done.session_status == "ended"
    row = session_row(api, session_id)
    assert row.status is SessionStatus.ENDED and row.ended_at is not None
    assert api.app.state.llm.active_count == 0
    assert api.app.state.runtimes.get(session_id) is None


def test_cli_crash_becomes_error_event_and_next_turn_resumes(api):
    session_id = start(api)["session"]["id"]
    events = turn(api, session_id, "__crash__")
    assert [e.type for e in events] == ["turn", "error"]
    assert events[-1].code == "llm_process_exited"
    # CLI stderr("fake crash")·종료 코드 같은 내부 정보는 클라이언트에 보내지 않는다
    assert events[-1].message == "답변 도중 연결이 끊겼어요. 다시 말해 주세요."
    events = turn(api, session_id, "괜찮아?")
    assert events[-1].type == "done"
    args = api.fake_cli.records()[-1]["args"]
    assert args[args.index("--resume") + 1] == FAKE_CLI_SESSION_ID
    roles = [t.role for t in turns_of(api, session_id)]
    # 실패한 턴은 사용자 턴만 남는다
    assert roles == [TurnRole.ASSISTANT, TurnRole.USER, TurnRole.USER, TurnRole.ASSISTANT]


def test_greeting_failure_leaves_no_session(api, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "error_invalid_model")
    response = api.post("/api/sessions", json={"mode": "text"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_error"
    assert (
        response.json()["error"]["message"] == "대화를 시작하지 못했어요. 잠시 뒤 다시 해 주세요."
    )
    assert load(api, lambda db: db.scalar(select(ConversationSession.id))) is None
    assert api.app.state.llm.active_count == 0
    assert not api.app.state.runtimes._items  # MCP 토큰도 남기지 않는다


def test_openapi_documents_session_routes(api):
    paths = api.get("/openapi.json").json()["paths"]
    content = paths["/api/sessions/{session_id}/turns"]["post"]["responses"]["200"]["content"]
    assert content["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/StreamEvent"}
    assert "/api/sessions" in paths and "/api/sessions/{session_id}/end" in paths
    assert "/api/profile" in paths


def test_invalid_mode_is_rejected(api):
    response = api.post("/api/sessions", json={"mode": "video"})
    assert response.status_code == 422
    assert json.loads(response.text)["error"]["code"] == "validation_error"


def test_cli_transcript_folder_removed_when_empty(home):
    from app.llm.claude_cli import delete_cli_session_file

    folder = home / ".claude" / "projects" / "-tmp-cli-x"
    folder.mkdir(parents=True)
    (folder / f"{FAKE_CLI_SESSION_ID}.jsonl").write_text("{}")
    assert delete_cli_session_file(FAKE_CLI_SESSION_ID)
    assert not folder.exists()
    assert not delete_cli_session_file("../../etc/passwd")
    assert not delete_cli_session_file(None)


def test_concurrent_turn_gets_error_event(api):
    """라우트 검사를 지난 뒤 다른 턴이 먼저 락을 잡으면 SSE error로 알린다."""
    from app.services.conversation import stream_turn

    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)

    async def run():
        async with runtime.turn_lock:
            return [chunk async for chunk in stream_turn(api.app, session_id, "안녕")]

    [chunk] = api.portal.call(run)
    assert b"event: error" in chunk and b"turn_in_progress" in chunk
    assert len(turns_of(api, session_id)) == 1  # 사용자 턴도 저장하지 않는다


def test_other_writes_succeed_during_turn(api):
    """턴 동안 트랜잭션을 열어 두지 않는다(MCP save_note가 다른 DB 세션으로 쓴다)."""
    session_id = start(api)["session"]["id"]

    async def make_persona_stale(db):
        (await db.get(Persona, "jenny")).version = "old"  # 다음 턴에서 sync_persona가 UPDATE
        await db.commit()

    load(api, make_persona_stale)
    factory = api.app.state.session_factory

    async def save_note_elsewhere(event):
        if isinstance(event, TurnStarted):
            async with factory() as other:
                other.add(Note(session_id=session_id, kind=NoteKind.MEMO, content="턴 중 메모"))
                await other.commit()

    hook_llm(api, save_note_elsewhere)
    started = time.monotonic()
    assert turn(api, session_id, "바나나는?")[-1].type == "done"
    assert time.monotonic() - started < 3  # 잠금을 기다리면 5초 넘게 걸리고 실패한다
    notes = load(api, lambda db: db.scalar(select(Note.content)))
    assert notes == "턴 중 메모"


def test_end_during_turn_stops_it(api):
    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)
    result = {}

    def run_turn():
        result["events"] = turn(api, session_id, "__hang_until_interrupt__")

    worker = threading.Thread(target=run_turn)
    worker.start()
    deadline = time.monotonic() + 5
    while not runtime.turn_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runtime.turn_lock.locked()

    started = time.monotonic()
    response = api.post(f"/api/sessions/{session_id}/end")
    worker.join(10)
    assert response.status_code == 200 and response.json()["session"]["status"] == "ended"
    assert time.monotonic() - started < 5
    # 다른 곳에서 끝냈으면 "다시 말해 주세요" 대신 끝났다고 알린다(클라이언트가 끝난 화면으로 간다)
    assert result["events"][-1].type == "error"
    assert result["events"][-1].code == "session_ended"
    assert session_row(api, session_id).status is SessionStatus.ENDED
    assert api.app.state.llm.active_count == 0
    assert api.app.state.runtimes.get(session_id) is None


async def _http(
    port: int, path: str, body: dict, *, until: bytes | None = None, count: int = 1
) -> bytes:
    """원시 HTTP POST. until을 받으면 그 바이트가 count번 보이자마자 연결을 끊는다
    (클라이언트 끊김)."""
    import asyncio

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    payload = json.dumps(body).encode()
    writer.write(
        f"POST {path} HTTP/1.1\r\nHost: test\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
        + payload
    )
    await writer.drain()
    data = b""
    try:
        while chunk := await asyncio.wait_for(reader.read(65536), 10):
            data += chunk
            if until is not None and data.count(until) >= count:
                break
    finally:
        writer.close()
    return data


async def test_client_disconnect_releases_turn(fake_cli, home, monkeypatch):
    """실제 서버(uvicorn)에서 턴 도중 연결을 끊으면 CLI 턴을 멈추고 락을 바로 푼다."""
    import asyncio
    import socket

    import uvicorn

    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = fake_cli.settings.model_copy(
        update={"internal_base_url": f"http://127.0.0.1:{port}"}
    )
    app = create_app(settings)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=5
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if serving.done():
                serving.result()
                pytest.fail("서버가 시작하지 못했습니다.")
            await asyncio.sleep(0.05)
        created = await _http(port, "/api/sessions", {})
        session_id = json.loads(created.split(b"\r\n\r\n", 1)[1])["session"]["id"]
        runtime = app.state.runtimes.get(session_id)
        path = f"/api/sessions/{session_id}/turns"
        await _http(port, path, {"text": "__hang__"}, until=b"event: turn")
        for _ in range(100):
            if not runtime.turn_lock.locked():
                break
            await asyncio.sleep(0.05)
        assert not runtime.turn_lock.locked()

        # 첫 문장을 받고 끊으면 그 문장까지 끊긴 답변으로 남는다
        await _http(
            port, path, {"text": f"__say_then_hang__:{THREE_SENTENCES}"}, until=b"event: sentence"
        )
        for _ in range(100):
            if not runtime.turn_lock.locked():
                break
            await asyncio.sleep(0.05)
        assert not runtime.turn_lock.locked()

        assert b"event: done" in await _http(port, path, {"text": "바나나는?"})
        async with app.state.session_factory() as db:
            rows = await db.execute(
                select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq)
            )
            saved = [(t.role, t.interrupted) for t in rows.scalars()]
            partial = await db.scalar(
                select(Turn.text).where(Turn.session_id == session_id, Turn.seq == 3)
            )
        # 문장 전에 끊긴 턴은 사용자 메시지만 남는다
        assert saved == [
            (TurnRole.ASSISTANT, False),
            (TurnRole.USER, False),
            (TurnRole.USER, False),
            (TurnRole.ASSISTANT, True),
            (TurnRole.USER, False),
            (TurnRole.ASSISTANT, False),
        ]
        assert partial.startswith("첫 문장입니다.")
    finally:
        server.should_exit = True
        await serving


def wait_for_records(fake_cli, count: int) -> list[dict]:
    """가짜 CLI는 기동 직후 인자를 기록한다. 프로세스가 기록을 남길 때까지 잠깐 기다린다."""
    deadline = time.monotonic() + 5
    while len(records := fake_cli.records()) < count and time.monotonic() < deadline:
        time.sleep(0.02)
    return records


def system_prompt_of(record: dict) -> str:
    args = record["args"]
    return args[args.index("--system-prompt") + 1]


def test_profile_change_does_not_alter_running_session_prompt(api):
    """진행 중인 대화는 CLI를 다시 띄워도(--resume) 시작 때의 프롬프트를 쓴다."""
    session_id = start(api)["session"]["id"]
    original = system_prompt_of(api.fake_cli.records()[-1])
    assert session_row(api, session_id).system_prompt == original
    api.put("/api/profile", json={"nickname": "바뀐호칭"})
    assert turn(api, session_id, "__crash__")[-1].type == "error"
    assert turn(api, session_id, "괜찮아?")[-1].type == "done"
    resumed = api.fake_cli.records()[-1]
    assert "--resume" in resumed["args"]
    assert system_prompt_of(resumed) == original and "바뀐호칭" not in original


def test_session_prompt_survives_server_restart(fake_cli, home, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    with TestClient(create_app(fake_cli.settings)) as client:
        session_id = client.post("/api/sessions", json={"mode": "text"}).json()["session"]["id"]
        original = system_prompt_of(fake_cli.records()[-1])
        client.put("/api/profile", json={"nickname": "새호칭"})
    with TestClient(create_app(fake_cli.settings)) as client:  # 서버 재시작(메모리 상태 없음)
        response = client.post(f"/api/sessions/{session_id}/turns", json={"text": "안녕"})
        assert events_of(response)[-1].type == "done"
    restarted = fake_cli.records()[-1]
    assert "--resume" in restarted["args"] and system_prompt_of(restarted) == original


def test_end_request_survives_turn_error(api):
    """끝내기 도구를 부른 뒤 턴이 오류로 끝나도 세션은 끝난다."""
    from app.errors import AppError

    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)

    def end_then_fail(event):
        if isinstance(event, TurnStarted):
            runtime.requested_status = SessionStatus.ENDED  # end_session 도구 호출 흉내
            raise AppError("llm_error", "도구 뒤 오류", 502)

    hook_llm(api, end_then_fail)
    last = turn(api, session_id, "오늘은 여기까지")[-1]
    assert last.type == "error" and last.code == "session_ended"  # 클라이언트가 끝난 화면으로 간다
    row = session_row(api, session_id)
    assert row.status is SessionStatus.ENDED and row.ended_at is not None
    assert api.app.state.llm.active_count == 0
    assert api.app.state.runtimes.get(session_id) is None


def test_error_result_after_external_end_is_session_ended(api):
    """CLI가 오류 결과로 턴을 끝냈는데 그사이 다른 곳(끝내기 API·무발화 감시)이 세션을 끝냈으면
    "답변을 만들지 못했습니다" 대신 끝났다고 알린다."""
    import dataclasses

    from app.llm.events import TurnFinished
    from app.services.conversation import _set_status

    session_id = start(api)["session"]["id"]
    manager = api.app.state.llm
    original = manager.get

    class EndedThenError(HookedSession):
        async def send(self, text):
            async with aclosing(self._inner.send(text)) as stream:
                async for event in stream:
                    if isinstance(event, TurnFinished):
                        async with api.app.state.session_factory() as db:
                            await _set_status(db, session_id, SessionStatus.ENDED)
                            await db.commit()
                        event = dataclasses.replace(
                            event, is_error=True, text="", error_message="중단됨"
                        )
                    yield event

    async def get(key, **kwargs):
        return EndedThenError(await original(key, **kwargs), None)

    manager.get = get
    last = turn(api, session_id, "바나나는?")[-1]
    assert last.type == "error" and last.code == "session_ended"


def test_pause_request_survives_turn_error(api):
    from app.errors import AppError

    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)

    def pause_then_fail(event):
        if isinstance(event, TurnStarted):
            runtime.requested_status = SessionStatus.PAUSED
            raise AppError("llm_error", "도구 뒤 오류", 502)

    hook_llm(api, pause_then_fail)
    assert turn(api, session_id, "잠깐 쉬자")[-1].type == "error"
    assert session_row(api, session_id).status is SessionStatus.PAUSED


def test_user_turn_save_error_sends_error_event(api, monkeypatch):
    import app.services.conversation as conversation

    session_id = start(api)["session"]["id"]
    original = conversation._set_status
    calls = []

    async def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db down")
        return await original(*args, **kwargs)

    monkeypatch.setattr(conversation, "_set_status", fail_once)
    events = turn(api, session_id, "안녕")
    assert [e.type for e in events] == ["error"] and events[0].code == "internal_error"
    assert turn(api, session_id, "다시 안녕")[-1].type == "done"


def model_of(record: dict) -> str:
    args = record["args"]
    return args[args.index("--model") + 1]


def test_chat_model_from_profile_switches_on_next_turn_keeping_context(api):
    """설정·말로 바꾼 대화 모델(S3-31)은 다음 답변부터 쓰고, 같은 CLI 대화 기록을 잇는다."""
    session_id = start(api)["session"]["id"]
    assert model_of(api.fake_cli.records()[-1]) == "sonnet"  # 고르지 않으면 서버 기본값
    turn(api, session_id, "바나나는?")
    count = len(api.fake_cli.records())
    assert api.put("/api/profile", json={"chat_model": "opus"}).status_code == 200
    turn(api, session_id, "이어서")
    records = api.fake_cli.records()
    assert len(records) == count + 1  # 새 모델로 다시 띄웠다
    assert model_of(records[-1]) == "opus"
    args = records[-1]["args"]
    assert args[args.index("--resume") + 1] == FAKE_CLI_SESSION_ID  # 맥락을 잇는다
    turn(api, session_id, "또")
    assert len(api.fake_cli.records()) == count + 1  # 같은 모델이면 그대로 쓴다


def test_set_model_during_turn_applies_from_next_turn(api):
    """말로 바꾼 모델(set_model)은 그 턴은 옛 모델로 끝내고 다음 턴부터 새 모델로 다시 띄운다."""
    session_id = start(api)["session"]["id"]

    async def save_model(event):  # set_model 도구가 프로필을 바꾸는 것을 흉내
        if isinstance(event, TurnStarted):
            async with api.app.state.session_factory() as db:
                from app.db.models import ChatModel
                from app.services.profile import get_or_create_profile

                (await get_or_create_profile(db)).chat_model = ChatModel.HAIKU
                await db.commit()

    hook_llm(api, save_model)
    count = len(api.fake_cli.records())
    assert turn(api, session_id, "빠른 모델로 바꿔 줘")[-1].type == "done"
    assert len(api.fake_cli.records()) == count  # 이번 턴은 그대로
    turn(api, session_id, "이어서")
    records = api.fake_cli.records()
    assert model_of(records[-1]) == "haiku"
    args = records[-1]["args"]
    assert args[args.index("--resume") + 1] == FAKE_CLI_SESSION_ID


def test_nickname_goes_only_to_the_greeting_request(api, monkeypatch, tmp_path):
    """호칭은 인사말을 만드는 숨은 요청에만 붙고 시스템 프롬프트·다음 턴에는 없다(Spec 5.7)."""
    content_log = tmp_path / "content.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_CONTENT_LOG", str(content_log))
    assert api.put("/api/profile", json={"nickname": "민수"}).status_code == 200
    session_id = start(api, mode="voice")["session"]["id"]
    args = api.fake_cli.records()[-1]["args"]
    prompt = args[args.index("--system-prompt") + 1]
    assert "음성 대화" in prompt and "민수" not in prompt
    turn(api, session_id, "안녕")
    sent = [json.loads(line) for line in content_log.read_text(encoding="utf-8").splitlines()]
    assert "민수" in sent[0]  # 첫 요청(인사말)에만
    assert "민수" not in sent[1]


def test_failed_start_still_deletes_the_empty_session_when_teardown_fails(api, monkeypatch):
    from app.services import conversation

    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "error_invalid_model")

    async def broken_teardown(*args, **kwargs):
        raise RuntimeError("정리 실패")

    monkeypatch.setattr(conversation, "teardown", broken_teardown)
    assert api.post("/api/sessions", json={"mode": "text"}).status_code == 502
    assert load(api, lambda db: db.scalar(select(ConversationSession.id))) is None


def test_closing_message_uses_the_persona_the_session_started_with(
    fake_cli, home, monkeypatch, tmp_path
):
    """대화 중에 프로필의 페르소나를 바꿔도 마무리 멘트는 그 세션의 페르소나를 따른다."""
    import yaml

    source = fake_cli.settings.persona_dir / "jenny.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / "jenny.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")
    other = {**data, "id": "mina", "name": "미나"}
    other["closing"] = {**data["closing"], "nothing": "미나의 마무리 인사예요."}
    (personas / "mina.yaml").write_text(yaml.safe_dump(other, allow_unicode=True), "utf-8")

    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    settings = fake_cli.settings.model_copy(update={"persona_dir": personas})
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/sessions", json={"mode": "text"}).json()["session"]["id"]
        assert client.put("/api/profile", json={"persona_id": "mina"}).status_code == 200
        closing = client.post(f"/api/sessions/{session_id}/end").json()["closing"]
    assert closing == data["closing"]["nothing"]
    assert closing != "미나의 마무리 인사예요."


def test_end_falls_back_to_default_persona_when_session_persona_file_is_gone(api):
    """세션을 시작한 페르소나 파일이 사라져도 /end는 이미 끝난 세션의 마무리 응답을 준다."""
    session_id = start(api)["session"]["id"]

    async def point_to_missing_persona(db):
        await db.execute(
            sql_text(
                "INSERT INTO persona (id, yaml_path, version, updated_at) "
                "VALUES ('ghost', 'ghost.yaml', 'x', '2026-10-23 00:00:00.000000')"
            )
        )
        await db.execute(
            sql_text("UPDATE conversation_session SET persona_id = 'ghost' WHERE id = :id"),
            {"id": session_id},
        )
        await db.commit()

    load(api, point_to_missing_persona)
    response = api.post(f"/api/sessions/{session_id}/end")
    assert response.status_code == 200
    persona = load_persona(api.fake_cli.settings.persona_dir, "jenny").persona
    assert response.json()["closing"] == persona.closing.nothing
