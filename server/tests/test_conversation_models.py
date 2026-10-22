"""conversation_session·turn·note 모델의 제약·기본값·연쇄 동작(리비전 0002)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ConversationSession,
    Note,
    NoteKind,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)


async def _session(db, **values) -> ConversationSession:
    convo = ConversationSession(mode=SessionMode.TEXT, **values)
    db.add(convo)
    await db.flush()
    return convo


async def test_session_defaults(db_session):
    convo = await _session(db_session)
    assert len(convo.id) == 36
    assert convo.status == SessionStatus.ACTIVE
    assert convo.started_at.tzinfo is not None
    assert convo.title_edited is False
    assert convo.extract_status is None


async def test_turn_defaults_and_seq_is_unique_per_session(db_session):
    convo = await _session(db_session)
    turn = Turn(session_id=convo.id, seq=0, role=TurnRole.USER, text="안녕")
    db_session.add(turn)
    await db_session.flush()
    assert turn.interrupted is False
    assert turn.greeting is False

    other = await _session(db_session)
    db_session.add(Turn(session_id=other.id, seq=0, role=TurnRole.USER, text="다른 대화"))
    await db_session.flush()  # 다른 세션이면 같은 seq가 가능하다

    db_session.add(Turn(session_id=convo.id, seq=0, role=TurnRole.ASSISTANT, text="중복"))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: turn.session_id, turn.seq"):
        await db_session.flush()


async def test_deleting_session_cascades_to_turns_and_notes(db_session):
    convo = await _session(db_session)
    turn = Turn(session_id=convo.id, seq=0, role=TurnRole.USER, text="아이디어")
    db_session.add(turn)
    await db_session.flush()
    db_session.add(Note(session_id=convo.id, turn_id=turn.id, kind=NoteKind.IDEA, content="a"))
    await db_session.flush()

    await db_session.execute(text("DELETE FROM conversation_session"))
    assert (await db_session.execute(select(Turn))).first() is None
    assert (await db_session.execute(select(Note))).first() is None


async def test_deleting_turn_keeps_note_with_null_turn(db_session):
    convo = await _session(db_session)
    turn = Turn(session_id=convo.id, seq=0, role=TurnRole.USER, text="x")
    db_session.add(turn)
    await db_session.flush()
    note = Note(session_id=convo.id, turn_id=turn.id, kind=NoteKind.TODO, content="할 일")
    db_session.add(note)
    await db_session.flush()

    await db_session.execute(text("DELETE FROM turn"))
    row = (await db_session.execute(text("SELECT turn_id, content FROM note"))).one()
    assert row.turn_id is None
    assert row.content == "할 일"


async def test_enum_check_rejects_unknown_session_mode(db_session):
    with pytest.raises(IntegrityError, match="ck_conversation_session_session_mode"):
        await db_session.execute(
            text(
                "INSERT INTO conversation_session (id, mode, started_at, status, title_edited) "
                "VALUES ('s1', 'telepathy', '2026-10-23 00:00:00.000000', 'active', 0)"
            )
        )


async def test_enum_check_rejects_unknown_note_kind(db_session):
    convo = await _session(db_session)
    with pytest.raises(IntegrityError, match="ck_note_note_kind"):
        await db_session.execute(
            text(
                "INSERT INTO note (id, session_id, kind, content, created_at) "
                "VALUES ('n1', :sid, 'poem', 'x', '2026-10-23 00:00:00.000000')"
            ),
            {"sid": convo.id},
        )
