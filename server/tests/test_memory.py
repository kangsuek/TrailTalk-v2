"""기억 블록 입력(S2-05): 조회 조건과 예산 자르기."""

from datetime import UTC, datetime, timedelta

from app.db.models import (
    ConversationSession,
    Note,
    NoteKind,
    SessionMode,
    SessionStatus,
    UserProfile,
)
from app.persona.memory import fit_to_budget, load_memory
from app.persona.prompt import MemoryContext

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 한국 시각 10월 15일 낮 12시


def test_budget_keeps_priority_order_and_skips_what_does_not_fit():
    memory = MemoryContext(
        recent_summaries=["가" * 40, "나" * 40],
        open_ideas=["다" * 30, "라" * 5],
        open_todos=["마" * 10],
        interests=["등산"],
    )
    # 40 + 40 = 80, 아이디어 30은 넘친다, 5는 들어간다(85), 할 일 10은 넘친다, 관심사 2는 들어간다
    fitted = fit_to_budget(memory, 90)
    assert fitted == MemoryContext(
        recent_summaries=["가" * 40, "나" * 40],
        open_ideas=["라" * 5],
        open_todos=[],
        interests=["등산"],
    )
    assert fit_to_budget(memory, 0) == MemoryContext()
    assert fit_to_budget(memory, 10_000) == memory


def test_budget_counts_cleaned_text():
    fitted = fit_to_budget(MemoryContext(open_ideas=["  여러\n줄  아이디어 ", " "]), 100)
    assert fitted.open_ideas == ["여러 줄 아이디어"]


async def test_load_memory_selects_recent_open_items(db_session, make_settings):
    db = db_session

    def session(days_ago: float, *, summary="요약 한 줄", status=SessionStatus.ENDED, title="제목"):
        convo = ConversationSession(
            mode=SessionMode.TEXT,
            started_at=NOW - timedelta(days=days_ago),
            status=status,
            summary=summary,
            title=title,
        )
        db.add(convo)
        return convo

    recent = session(1, title="쓰레기통 지도", summary="첫 줄\n둘째 줄")
    session(2, summary=None)  # 정리되지 않은 세션
    session(3, status=SessionStatus.ACTIVE)  # 끝나지 않은 세션
    session(8)  # 7일보다 오래됨
    for days in (4, 5, 6):
        session(days, title=f"{days}일 전")
    await db.flush()

    def note(kind, content, *, done=False, starred=False, minutes=0):
        db.add(
            Note(
                session_id=recent.id,
                kind=kind,
                content=content,
                done=done,
                starred=starred,
                created_at=NOW - timedelta(minutes=minutes),
            )
        )

    note(NoteKind.IDEA, "새 아이디어", minutes=1)
    note(NoteKind.IDEA, "별표 아이디어", starred=True, minutes=100)
    note(NoteKind.IDEA, "끝난 아이디어", done=True)
    note(NoteKind.TODO, "할 일", minutes=5)
    note(NoteKind.TODO, "끝난 할 일", done=True)
    note(NoteKind.MEMO, "메모는 기억에 넣지 않는다")
    await db.commit()

    profile = UserProfile(id=1, interests=["등산", "앱"])
    memory = await load_memory(db, make_settings(), profile, NOW)
    assert memory.recent_summaries == [
        "10월 14일 '쓰레기통 지도': 첫 줄 둘째 줄",
        "10월 11일 '4일 전': 요약 한 줄",
        "10월 10일 '5일 전': 요약 한 줄",
    ]
    assert memory.open_ideas == ["별표 아이디어", "새 아이디어"]
    assert memory.open_todos == ["할 일"]
    assert memory.interests == ["등산", "앱"]
