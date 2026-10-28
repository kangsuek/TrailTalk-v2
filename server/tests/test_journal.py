"""일지·노트 API(M2-06·07, client-contract 3절): 목록 범위·말 안 한 대화 제외·진행 중 포함, 상세,
제목 수정, 삭제(409 두 가지·쉬는 중·정리 중단), 다시 정리의 상태별 동작, 노트 수정, 열린
아이디어."""

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import (
    ConversationSession,
    ExtractStatus,
    Note,
    NoteKind,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.main import create_app
from app.persona.loader import load_persona
from tests.test_extract import cli_output, oneshot_records, set_session
from tests.test_sessions import load, session_row, start, turn


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def oneshot(tmp_path, monkeypatch):
    path = tmp_path / "oneshot.jsonl"

    def set_lines(*lines: str) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT", str(path))
    monkeypatch.delenv("FAKE_CLAUDE_ONESHOT_DELAY", raising=False)
    set_lines(cli_output())
    return set_lines


@pytest.fixture
def api(fake_cli, home, oneshot, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    with TestClient(create_app(fake_cli.settings)) as client:
        client.fake_cli = fake_cli
        yield client


def wait_for(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("시간 안에 조건이 맞지 않았다")


def talk(api) -> str:
    session_id = start(api)["session"]["id"]
    turn(api, session_id, "__say__:쓰레기통 지도 이야기예요.")
    return session_id


def talk_and_end(api) -> str:
    session_id = talk(api)
    assert api.post(f"/api/sessions/{session_id}/end").json()["journal_status"] == "done"
    return session_id


def seed(
    api,
    started_at: datetime,
    *,
    status: SessionStatus = SessionStatus.ENDED,
    spoke: bool = True,
    notes: tuple[tuple[NoteKind, str], ...] = (),
    **values,
) -> str:
    """DB에 대화를 바로 만든다(CLI 없이, 날짜·상태를 정해서)."""

    async def fn(db):
        convo = ConversationSession(
            mode=SessionMode.TEXT,
            started_at=started_at,
            status=status,
            ended_at=started_at + timedelta(minutes=5) if status is SessionStatus.ENDED else None,
            **values,
        )
        db.add(convo)
        await db.flush()
        db.add(
            Turn(session_id=convo.id, seq=0, role=TurnRole.ASSISTANT, text="안녕", greeting=True)
        )
        if spoke:
            db.add(Turn(session_id=convo.id, seq=1, role=TurnRole.USER, text="걷는 중이야"))
        for i, (kind, content) in enumerate(notes):
            db.add(
                Note(
                    session_id=convo.id,
                    kind=kind,
                    content=content,
                    created_at=started_at + timedelta(seconds=i + 1),
                )
            )
        await db.commit()
        return convo.id

    return load(api, fn)


def local_noon(api, days_ago: int = 0) -> datetime:
    tz = ZoneInfo(api.app.state.settings.timezone)
    today = datetime.now(tz).date() - timedelta(days=days_ago)
    return datetime(today.year, today.month, today.day, 12, tzinfo=tz).astimezone(UTC)


def count_rows(api, model, session_id: str) -> int:
    return load(
        api,
        lambda db: db.scalar(
            select(func.count()).select_from(model).where(model.session_id == session_id)
        ),
    )


# --- 목록 ---


def test_list_defaults_to_30_days_newest_first(api):
    today = seed(api, local_noon(api), notes=((NoteKind.IDEA, "지도"), (NoteKind.TODO, "사진")))
    older = seed(api, local_noon(api, 29))
    seed(api, local_noon(api, 30))  # 30일 범위 밖
    body = api.get("/api/journal").json()
    assert [item["id"] for item in body] == [today, older]
    first = body[0]
    assert (
        first["date"]
        == local_noon(api).astimezone(ZoneInfo(api.app.state.settings.timezone)).date().isoformat()
    )
    assert first["counts"] == {"idea": 1, "todo": 1, "memo": 0}
    assert first["summary"] == [] and first["tags"] == []
    assert first["journal_status"] is None
    assert "topics" not in first


def test_list_range_includes_both_ends(api):
    tz = ZoneInfo(api.app.state.settings.timezone)
    day = datetime(2026, 3, 10, 0, 0, 30, tzinfo=tz)  # 현지 자정 직후
    first = seed(api, day.astimezone(UTC))
    last = seed(api, (day + timedelta(days=2, hours=23, minutes=59)).astimezone(UTC))
    seed(api, (day + timedelta(days=3, minutes=1)).astimezone(UTC))
    body = api.get("/api/journal", params={"from": "2026-03-10", "to": "2026-03-12"}).json()
    assert [item["id"] for item in body] == [last, first]
    assert [item["date"] for item in body] == ["2026-03-12", "2026-03-10"]


def test_list_excludes_silent_sessions_and_includes_active(api):
    active = seed(api, local_noon(api), status=SessionStatus.ACTIVE)
    silent = seed(api, local_noon(api, 1), spoke=False)
    body = api.get("/api/journal").json()
    assert [item["id"] for item in body] == [active]
    assert body[0]["status"] == "active" and body[0]["ended_at"] is None
    # 목록에서 빠진 대화도 ID로는 조회된다
    assert api.get(f"/api/journal/{silent}").status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-03-12", "to": "2026-03-10"},  # 거꾸로
        {"from": "2025-01-01", "to": "2026-01-02"},  # 366일 초과(367일)
        {"from": "1999-12-31", "to": "2000-01-05"},  # 범위 밖
        {"to": "9999-01-01"},
    ],
)
def test_list_rejects_invalid_range(api, params):
    response = api.get("/api/journal", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_range"


def test_list_accepts_366_days(api):
    response = api.get("/api/journal", params={"from": "2025-01-01", "to": "2026-01-01"})
    assert response.status_code == 200


def test_list_rejects_malformed_date(api):
    response = api.get("/api/journal", params={"from": "어제"})
    assert response.json()["error"]["code"] == "validation_error"


# --- 상세 ---


def test_detail_has_transcript_notes_and_persona_name(api):
    session_id = talk_and_end(api)
    body = api.get(f"/api/journal/{session_id}").json()
    assert body["session"]["title"] == "등산로 쓰레기통 지도 아이디어"
    assert body["session"]["summary"][0].startswith("등산로 쓰레기통 위치를")
    assert body["session"]["journal_status"] == "done"
    assert body["checks"] == ["지자체 쓰레기통 위치 공개 데이터가 있는지(확인 필요)"]
    assert (
        body["persona_name"]
        == load_persona(api.app.state.settings.persona_dir, "jenny").persona.name
    )
    assert {n["kind"] for n in body["notes"]} == {"idea", "todo", "memo"}
    assert all(n["cites"] == [] for n in body["notes"])
    # 출처가 없으니(검색은 M5) 인용은 비어 있다
    assert body["citations"] == []
    assert body["summary_cites"] == [[] for _ in body["session"]["summary"]]
    roles = [t["role"] for t in body["turns"]]
    assert roles == ["assistant", "user", "assistant"]
    assert [t["seq"] for t in body["turns"]] == [0, 1, 2]
    assert all(t["merged_from"] is None and t["attachments"] == [] for t in body["turns"])


def test_detail_speaker_falls_back_when_session_has_no_persona(api):
    name = load_persona(api.app.state.settings.persona_dir, "jenny").persona.name
    session_id = seed(api, local_noon(api), persona_id=None)
    assert api.get(f"/api/journal/{session_id}").json()["persona_name"] == name


def test_detail_numbers_citations_from_remaining_lines(api):
    session_id = seed(
        api,
        local_noon(api),
        summary="결론\n알게 된 것",
        summary_cites=[["https://b.example/x"], ["https://a.example/y", "https://b.example/x"]],
        citations=[{"title": "B 문서", "url": "https://b.example/x"}],
        extract_status=ExtractStatus.DONE,
        checks=[],
    )
    body = api.get(f"/api/journal/{session_id}").json()
    assert body["summary_cites"] == [[1], [2, 1]]
    assert body["citations"] == [
        {"n": 1, "title": "B 문서", "url": "https://b.example/x"},
        {"n": 2, "title": "a.example", "url": "https://a.example/y"},
    ]


def test_detail_unknown_session_is_404(api):
    response = api.get("/api/journal/없는-대화")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


# --- 제목 수정 ---


def test_patch_title_collapses_spaces_and_survives_reextraction(api):
    session_id = talk_and_end(api)
    response = api.patch(f"/api/journal/{session_id}", json={"title": "  내 \n  제목\t입니다 "})
    assert response.status_code == 200
    assert response.json()["title"] == "내 제목 입니다"
    assert response.json()["counts"] == {"idea": 1, "todo": 1, "memo": 1}
    # 다시 정리해도 고친 제목은 그대로다
    set_session(api, session_id, extract_status=ExtractStatus.FAILED)
    assert api.post(f"/api/journal/{session_id}/retry").status_code == 202
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    assert session_row(api, session_id).title == "내 제목 입니다"


@pytest.mark.parametrize("title", ["", "  \n ", "가" * 201])
def test_patch_title_rejects_bad_length(api, title):
    session_id = seed(api, local_noon(api))
    response = api.patch(f"/api/journal/{session_id}", json={"title": title})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_patch_title_accepts_200_chars_and_404(api):
    session_id = seed(api, local_noon(api))
    response = api.patch(f"/api/journal/{session_id}", json={"title": "가" * 200})
    assert response.status_code == 200
    missing = api.patch("/api/journal/없는-대화", json={"title": "제목"})
    assert missing.json()["error"]["code"] == "session_not_found"


# --- 삭제 ---


def test_delete_removes_session_turns_and_notes(api):
    session_id = talk_and_end(api)
    assert api.delete(f"/api/journal/{session_id}").status_code == 204
    assert session_row(api, session_id) is None
    assert count_rows(api, Turn, session_id) == 0
    assert count_rows(api, Note, session_id) == 0
    again = api.delete(f"/api/journal/{session_id}")
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "session_not_found"


def test_delete_active_session_is_409(api):
    session_id = talk(api)
    response = api.delete(f"/api/journal/{session_id}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_active"
    assert session_row(api, session_id) is not None


def test_delete_paused_session_closes_cli(api):
    session_id = talk(api)
    assert api.app.state.llm.is_alive(session_id)
    set_session(api, session_id, status=SessionStatus.PAUSED)
    assert api.delete(f"/api/journal/{session_id}").status_code == 204
    assert not api.app.state.llm.is_alive(session_id)
    assert api.app.state.runtimes.get(session_id) is None
    assert session_row(api, session_id) is None


def test_delete_while_turn_runs_is_409(api, monkeypatch):
    session_id = talk(api)
    set_session(api, session_id, status=SessionStatus.PAUSED)
    monkeypatch.setattr("app.services.conversation._LOCK_WAIT_S", 0.2)
    runtime = api.app.state.runtimes.ensure(session_id)

    async def hold():
        await runtime.turn_lock.acquire()

    api.portal.call(hold)
    try:
        response = api.delete(f"/api/journal/{session_id}")
    finally:
        api.portal.call(lambda: _release(runtime))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "turn_in_progress"
    assert session_row(api, session_id) is not None


async def _release(runtime) -> None:
    runtime.turn_lock.release()


def test_delete_stops_running_extraction(api, oneshot):
    oneshot("__hang__")
    api.app.state.settings.extract_wait_s = 0.2
    session_id = talk(api)
    assert api.post(f"/api/sessions/{session_id}/end").json()["journal_status"] == "pending"
    wait_for(lambda: oneshot_records(api.fake_cli) != [])
    assert session_id in api.app.state.extractions
    assert api.delete(f"/api/journal/{session_id}").status_code == 204
    wait_for(lambda: session_id not in api.app.state.extractions)
    assert session_row(api, session_id) is None


# --- 다시 정리 ---


def test_retry_active_session_is_409(api):
    session_id = talk(api)
    response = api.post(f"/api/journal/{session_id}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_not_ended"


def test_retry_unknown_session_is_404(api):
    assert api.post("/api/journal/없는-대화/retry").json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize("before", [ExtractStatus.FAILED, None])
def test_retry_failed_or_unrecorded_runs_extraction(api, before):
    session_id = talk_and_end(api)
    set_session(api, session_id, extract_status=before, title=None, summary=None, checks=None)
    response = api.post(f"/api/journal/{session_id}/retry")
    assert response.status_code == 202
    assert response.json()["journal_status"] == "pending"
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    assert session_row(api, session_id).title == "등산로 쓰레기통 지도 아이디어"
    assert len(oneshot_records(api.fake_cli)) == 2


@pytest.mark.parametrize("status", [ExtractStatus.DONE, ExtractStatus.PENDING])
def test_retry_done_or_pending_does_nothing(api, status):
    session_id = talk_and_end(api)
    set_session(api, session_id, extract_status=status)
    response = api.post(f"/api/journal/{session_id}/retry")
    assert response.status_code == 202
    assert response.json()["journal_status"] == status.value
    time.sleep(0.2)
    assert len(oneshot_records(api.fake_cli)) == 1


def test_retry_old_format_rewrites_without_new_notes(api):
    session_id = talk_and_end(api)
    set_session(api, session_id, checks=None, summary="예전 요약 한 줄")
    before = count_rows(api, Note, session_id)
    response = api.post(f"/api/journal/{session_id}/retry")
    assert response.json()["journal_status"] == "pending"
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    row = session_row(api, session_id)
    assert row.checks is not None and row.summary.startswith("등산로 쓰레기통 위치를")
    assert count_rows(api, Note, session_id) == before
    assert session_id not in api.app.state.reformat_requests


# --- 노트 ---


def first_note(api, session_id: str, kind: NoteKind = NoteKind.IDEA) -> dict:
    notes = api.get(f"/api/journal/{session_id}").json()["notes"]
    return next(n for n in notes if n["kind"] == kind.value)


def test_patch_note_changes_only_sent_fields(api):
    session_id = seed(api, local_noon(api), notes=((NoteKind.IDEA, "지도 앱"),))
    note = first_note(api, session_id)
    starred = api.patch(f"/api/notes/{note['id']}", json={"starred": True}).json()
    assert (starred["starred"], starred["done"], starred["content"]) == (True, False, "지도 앱")
    done = api.patch(f"/api/notes/{note['id']}", json={"done": True}).json()
    assert (done["starred"], done["done"]) == (True, True)
    edited = api.patch(f"/api/notes/{note['id']}", json={"content": "  새 내용\n둘째 줄  "})
    assert edited.json()["content"] == "새 내용\n둘째 줄"
    assert edited.json()["starred"] is True and edited.json()["done"] is True
    assert first_note(api, session_id)["content"] == "새 내용\n둘째 줄"


@pytest.mark.parametrize(
    "body",
    [
        {"content": "   "},
        {"content": "가" * 501},
        {"starred": None},
        {"done": "yes"},
        {"kind": "todo"},
    ],
)
def test_patch_note_rejects_bad_fields(api, body):
    session_id = seed(api, local_noon(api), notes=((NoteKind.IDEA, "지도 앱"),))
    note = first_note(api, session_id)
    response = api.patch(f"/api/notes/{note['id']}", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert first_note(api, session_id) == note


def test_patch_note_accepts_500_chars_and_404(api):
    session_id = seed(api, local_noon(api), notes=((NoteKind.MEMO, "메모"),))
    note = first_note(api, session_id, NoteKind.MEMO)
    ok = api.patch(f"/api/notes/{note['id']}", json={"content": "가" * 500})
    assert ok.status_code == 200
    missing = api.patch("/api/notes/없는-노트", json={"done": True})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "note_not_found"


def test_open_ideas_one_per_session_newest_first(api):
    old = seed(
        api,
        local_noon(api, 3),
        notes=((NoteKind.IDEA, "옛 아이디어 1"), (NoteKind.IDEA, "옛 아이디어 2")),
    )
    new = seed(
        api,
        local_noon(api, 1),
        notes=(
            (NoteKind.IDEA, "새 아이디어"),
            (NoteKind.TODO, "할 일"),
            (NoteKind.IDEA, "새 아이디어 닫음"),
        ),
    )
    seed(api, local_noon(api, 2), notes=((NoteKind.TODO, "아이디어 없는 대화"),))
    closed = next(  # 가장 최근 아이디어를 닫는다
        n for n in api.get(f"/api/journal/{new}").json()["notes"] if n["content"].endswith("닫음")
    )
    api.patch(f"/api/notes/{closed['id']}", json={"done": True})
    body = api.get("/api/notes/open-ideas").json()
    assert [(i["session_id"], i["content"]) for i in body] == [
        (new, "새 아이디어"),
        (old, "옛 아이디어 2"),
    ]
    # counts는 완료한 것까지 센다(일지 목록과 같은 기준)
    assert body[0]["counts"] == {"idea": 2, "todo": 1, "memo": 0}
    assert body[1]["counts"] == {"idea": 2, "todo": 0, "memo": 0}
    assert set(body[0]) == {"id", "content", "starred", "session_id", "created_at", "counts"}


def test_open_ideas_limit(api):
    for days in range(1, 8):
        seed(api, local_noon(api, days), notes=((NoteKind.IDEA, f"아이디어 {days}"),))
    assert len(api.get("/api/notes/open-ideas").json()) == 5
    limited = api.get("/api/notes/open-ideas", params={"limit": 2}).json()
    assert [i["content"] for i in limited] == ["아이디어 1", "아이디어 2"]
    for bad in (0, 21):
        response = api.get("/api/notes/open-ideas", params={"limit": bad})
        assert response.json()["error"]["code"] == "validation_error"


def test_open_ideas_empty(api):
    assert api.get("/api/notes/open-ideas").json() == []
