"""웹 API가 앱(claude_app) 세션을 다루는 방식(MA-10): 목록 노출, 출처 필드, 다시 열기·다시 정리
거절, 제목 중복 거부, 전문 화자 이름, 삭제."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db.models import (
    AppKind,
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

STARTED = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)  # 서울 10월 30일 12시


@pytest.fixture
def web(make_settings, tmp_path):
    settings = make_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'web.db'}", app_speaker_name="앱상대"
    )
    with TestClient(create_app(settings), headers={"X-TrailTalk": "1"}) as client:
        yield client


def seed(client, fn):
    async def run():
        async with client.app.state.session_factory() as db:
            return await fn(db)

    return client.portal.call(run)


def app_session(
    title="앱 일지", kind=AppKind.JOURNAL, *, summary="앱 요약", day=date(2026, 10, 30)
):
    return ConversationSession(
        mode=SessionMode.CLAUDE_APP,
        status=SessionStatus.ENDED,
        started_at=STARTED,
        ended_at=STARTED,
        title=title,
        summary=summary,
        tags=[],
        checks=[],
        extract_status=ExtractStatus.DONE,
        app_kind=kind,
        app_day=day,
    )


async def _make_app_journal(db, *, with_turns=False):
    convo = app_session()
    memo = app_session("앱 메모 · 10월 30일", AppKind.MEMO, summary=None)
    web_convo = ConversationSession(
        mode=SessionMode.TEXT,
        status=SessionStatus.ENDED,
        started_at=STARTED,
        title="웹 일지",
        extract_status=ExtractStatus.DONE,
    )
    db.add_all([convo, memo, web_convo])
    await db.flush()
    db.add(Note(session_id=convo.id, kind=NoteKind.IDEA, content="앱 아이디어"))
    db.add(Note(session_id=memo.id, kind=NoteKind.MEMO, content="메모 노트"))
    db.add(Turn(session_id=web_convo.id, seq=1, role=TurnRole.USER, text="안녕"))
    if with_turns:
        db.add(Turn(session_id=convo.id, seq=1, role=TurnRole.USER, text="나의 말"))
        db.add(Turn(session_id=convo.id, seq=2, role=TurnRole.ASSISTANT, text="상대 말"))
    await db.commit()
    return convo.id, memo.id, web_convo.id


def test_list_includes_app_sessions_without_turns_and_marks_source(web):
    app_id, memo_id, web_id = seed(web, _make_app_journal)
    items = {i["id"]: i for i in web.get("/api/journal?from=2026-10-30&to=2026-10-30").json()}
    assert set(items) == {app_id, memo_id, web_id}  # 턴이 없어도 앱 세션은 나온다
    assert items[app_id]["source"] == "app" and items[memo_id]["source"] == "app"
    assert items[web_id]["source"] == "web"
    assert items[app_id]["counts"]["idea"] == 1


def test_detail_has_source_speaker_name_and_new_format(web):
    app_id, _, web_id = seed(web, lambda db: _make_app_journal(db, with_turns=True))
    detail = web.get(f"/api/journal/{app_id}").json()
    assert detail["session"]["source"] == "app"
    assert detail["persona_name"] == "앱상대"  # 설정값, 캐릭터 이름이 아니다
    assert detail["checks"] == [] and [t["role"] for t in detail["turns"]] == ["user", "assistant"]
    assert web.get(f"/api/journal/{web_id}").json()["session"]["source"] == "web"


def test_reopen_app_session_is_rejected(web):
    app_id, memo_id, _ = seed(web, _make_app_journal)
    for session_id in (app_id, memo_id):
        response = web.post(f"/api/sessions/{session_id}/reopen", json={"mode": "text"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "app_session_not_reopenable"


def test_retry_on_app_session_does_nothing(web):
    app_id, _, _ = seed(web, _make_app_journal)

    async def break_it(db):
        convo = await db.get(ConversationSession, app_id)
        convo.extract_status = ExtractStatus.FAILED  # 웹이면 다시 정리 대상이 되는 상태
        await db.commit()

    seed(web, break_it)
    response = web.post(f"/api/journal/{app_id}/retry")
    assert response.status_code == 202
    assert response.json()["journal_status"] == "failed"  # 정리를 다시 띄우지 않는다
    assert web.get(f"/api/journal/{app_id}").json()["session"]["journal_status"] == "failed"


def test_patch_title_conflict_and_memo_title_locked(web):
    app_id, memo_id, _ = seed(web, _make_app_journal)

    async def second(db):
        other = app_session("다른 제목")
        other.app_day = date(2026, 10, 30)
        db.add(other)
        await db.commit()
        return other.id

    other_id = seed(web, second)
    conflict = web.patch(f"/api/journal/{other_id}", json={"title": "앱 일지"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "title_conflict"
    assert web.patch(f"/api/journal/{other_id}", json={"title": "또 다른 제목"}).status_code == 200
    locked = web.patch(f"/api/journal/{memo_id}", json={"title": "바꿈"})
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "app_memo_title_locked"


def test_web_session_titles_are_not_restricted(web):
    _, _, web_id = seed(web, _make_app_journal)
    assert web.patch(f"/api/journal/{web_id}", json={"title": "앱 일지"}).status_code == 200


def test_delete_app_session_from_web_removes_notes(web):
    app_id, _, _ = seed(web, _make_app_journal)
    assert web.delete(f"/api/journal/{app_id}").status_code == 204
    assert web.get(f"/api/journal/{app_id}").status_code == 404

    async def count(db):
        from sqlalchemy import func, select

        return await db.scalar(
            select(func.count()).select_from(Note).where(Note.session_id == app_id)
        )

    assert seed(web, count) == 0
