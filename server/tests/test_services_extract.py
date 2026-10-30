"""서비스 계층 추출(MA-01·02): 일지·노트·호칭·기억 서비스의 단위 시험."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.db.models import (
    ConversationSession,
    Note,
    NoteKind,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
    UserProfile,
)
from app.errors import AppError
from app.services import journal, memory, nickname
from app.services import notes as note_service

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
KST = ZoneInfo("Asia/Seoul")


def _convo(**kw) -> ConversationSession:
    kw.setdefault("mode", SessionMode.TEXT)
    kw.setdefault("started_at", NOW)
    kw.setdefault("status", SessionStatus.ENDED)
    return ConversationSession(**kw)


def test_is_app_session_by_mode_value():
    assert journal.is_app_session(SimpleNamespace(mode="claude_app"))
    assert not journal.is_app_session(SimpleNamespace(mode=SessionMode.TEXT))
    assert not journal.is_app_session(SimpleNamespace(mode=SessionMode.VOICE))


def test_search_terms_and_escape():
    assert journal.search_terms("  장터   이름 세번째 넷째 ") == ["장터", "이름", "세번째"]
    assert journal.search_terms("   ") == []
    assert journal.escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"


def test_range_validation():
    journal.validate_range(journal.MIN_DATE, journal.MAX_DATE.replace(year=2000, month=12))
    for start, end in [
        (journal.MIN_DATE.replace(year=1999), journal.MIN_DATE),
        (journal.MAX_DATE, journal.MAX_DATE.replace(day=30)),
        (journal.MIN_DATE, journal.MIN_DATE.replace(year=2003)),
    ]:
        with pytest.raises(AppError) as err:
            journal.validate_range(start, end)
        assert err.value.code == "invalid_range"


async def test_list_journals_skips_silent_and_counts_notes(db_session):
    db = db_session
    spoke, silent = _convo(title="말한 대화"), _convo(title="인사만")
    db.add_all([spoke, silent])
    await db.flush()
    db.add_all(
        [
            Turn(session_id=spoke.id, seq=1, role=TurnRole.USER, text="안녕"),
            Turn(session_id=silent.id, seq=1, role=TurnRole.ASSISTANT, text="안녕하세요"),
            Note(session_id=spoke.id, kind=NoteKind.IDEA, content="가"),
            Note(session_id=spoke.id, kind=NoteKind.IDEA, content="나"),
            Note(session_id=spoke.id, kind=NoteKind.TODO, content="다"),
        ]
    )
    await db.commit()
    day = NOW.astimezone(KST).date()
    rows = await journal.list_journals(db, KST, day, day)
    assert [r.convo.title for r in rows] == ["말한 대화"]
    assert rows[0].counts == {NoteKind.IDEA: 2, NoteKind.TODO: 1}


async def test_rename_journal_sets_edited_and_blocks_app_duplicate(db_session, monkeypatch):
    db = db_session
    first, second = _convo(title="산책"), _convo(title="다른 제목")
    other_day = _convo(title="같은 제목", started_at=NOW - timedelta(days=2))
    db.add_all([first, second, other_day])
    await db.commit()

    renamed = await journal.rename_journal(db, second.id, "새 제목", KST)
    assert (renamed.title, renamed.title_edited) == ("새 제목", True)

    # 웹 세션은 같은 날 같은 제목을 막지 않는다
    await journal.rename_journal(db, second.id, "산책", KST)

    # 앱 세션은 같은 날 같은 제목을 막는다(다른 날은 허용)
    monkeypatch.setattr(journal, "is_app_session", lambda convo: True)
    with pytest.raises(AppError) as err:
        await journal.rename_journal(db, second.id, "산책", KST)
    assert (err.value.code, err.value.status_code) == ("title_conflict", 409)
    await journal.rename_journal(db, second.id, "같은 제목", KST)


async def test_search_conversations_excludes_current_question_and_after(db_session):
    db = db_session
    old, now = _convo(title="옛 대화"), _convo(title="지금 대화", status=SessionStatus.ACTIVE)
    db.add_all([old, now])
    await db.flush()
    rows = [
        Turn(session_id=old.id, seq=1, role=TurnRole.USER, text="장터 이름 정하자"),
        Turn(session_id=old.id, seq=2, role=TurnRole.ASSISTANT, text="어떤 장터?"),
        Turn(session_id=now.id, seq=1, role=TurnRole.USER, text="장터 이야기 앞선 말"),
        Turn(session_id=now.id, seq=2, role=TurnRole.USER, text="장터 지금 질문"),
    ]
    db.add_all(rows)
    await db.commit()

    found = await journal.search_conversations(
        db, ["장터"], current_session_id=now.id, current_user_turn_id=rows[3].id
    )
    texts = {h.turn.text for h in found.hits}
    assert texts == {"장터 이름 정하자", "어떤 장터?", "장터 이야기 앞선 말"}
    assert (old.id, 2) in found.neighbors

    everything = await journal.search_conversations(db, ["장터", "질문"])
    assert [h.turn.text for h in everything.hits] == ["장터 지금 질문"]
    assert (await journal.search_conversations(db, ["없는말"])).hits == []


async def test_note_service_save_search_update_delete(db_session):
    db = db_session
    convo = _convo()
    db.add(convo)
    await db.commit()

    saved = await note_service.save_note(
        db, session_id=convo.id, kind=NoteKind.IDEA, content="  쓰레기통 지도  "
    )
    assert saved.content == "쓰레기통 지도"

    since = note_service.since_days(datetime.now(UTC), 1)
    assert [n.id for n in await note_service.search_notes(db, ["쓰레기"], since)] == [saved.id]
    assert await note_service.search_notes(db, ["쓰레기", "없음"], since) == []

    changed = await note_service.update_note(db, saved.id, {"starred": True, "content": "수정"})
    assert (changed.starred, changed.content) == (True, "수정")
    with pytest.raises(AppError) as err:
        await note_service.update_note(db, saved.id, {"done": None})
    assert err.value.code == "validation_error"
    with pytest.raises(note_service.NoteNotFound):
        await note_service.update_note(db, "없는-노트", {"done": True})

    gone = await note_service.delete_note(db, saved.id)
    assert gone.id == saved.id
    with pytest.raises(note_service.NoteNotFound):
        await note_service.delete_note(db, saved.id)


def test_nickname_rules():
    assert nickname.nickname_core("영희 님") == "영희"
    assert nickname.nickname_core("철수씨") == "철수"
    assert nickname.nickname_core("님") == "님"
    assert nickname.check_nickname("영희님") == "영희"
    with pytest.raises(AppError):
        nickname.check_nickname("가님")
    assert nickname.utterance_supports("영희", "앞으로 영 희 라고 불러줘")
    assert not nickname.utterance_supports("영희", "철수라고 불러줘")


async def test_set_nickname_saves_profile(db_session):
    db = db_session
    assert await nickname.set_nickname(db, "영희님") == "영희님"
    db.expire_all()
    assert (await db.get(UserProfile, 1)).nickname == "영희님"
    with pytest.raises(AppError):
        await nickname.set_nickname(db, "가씨")


async def test_app_memory_drops_interests_and_caps_todos(db_session, make_settings):
    db = db_session
    convo = _convo()
    db.add(convo)
    await db.flush()
    for i in range(memory.MAX_TODOS + 3):
        db.add(
            Note(
                session_id=convo.id,
                kind=NoteKind.TODO,
                content=f"할 일 {i}",
                created_at=NOW - timedelta(minutes=i),
            )
        )
    db.add(Note(session_id=convo.id, kind=NoteKind.IDEA, content="열린 아이디어"))
    profile = UserProfile(id=1, interests=["등산"])
    db.add(profile)
    await db.commit()

    settings = make_settings()
    app_view = await memory.load_app_memory(db, settings, profile, NOW)
    assert app_view.interests == []
    assert len(app_view.open_todos) == memory.MAX_TODOS
    assert app_view.open_todos[0] == "할 일 0"
    assert app_view.open_ideas == ["열린 아이디어"]

    chat_view = await memory.load_memory(db, settings, profile, NOW)
    assert chat_view.interests == ["등산"]


async def test_empty_list_and_missing_journal(db_session):
    day = NOW.astimezone(KST).date()
    assert await journal.list_journals(db_session, KST, day, day) == []
    with pytest.raises(AppError) as err:
        await journal.get_journal(db_session, "없는-대화")
    assert err.value.code == "session_not_found"
