"""기억 블록 입력(Spec 5.7): 지난 대화에서 다음 세션에 이어 갈 것을 고른다.

- 최근 7일 일지 요약(최신순 3개), 열린 아이디어(별표 먼저, 최신순 5개), 안 끝난 할 일(최신순 5개),
  프로필 관심사를 모은다.
- 예산(글자 수) 안에서 이 우선순위대로 채우고, 들어가지 않는 항목은 건너뛴다(뒤의 짧은 항목은 들어갈
  수 있다). 글자 수는 토큰의 대용이다(한국어는 대략 글자당 1토큰 안팎).
"""

from dataclasses import fields
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ConversationSession, Note, NoteKind, SessionStatus, UserProfile
from app.persona.prompt import MemoryContext, one_line

RECENT_DAYS = 7
MAX_SUMMARIES = 3
MAX_IDEAS = 5
MAX_TODOS = 5
ITEM_MAX = 300  # 프롬프트 조립기가 항목을 자르는 길이와 같다

# 예산을 채우는 우선순위(MemoryContext 필드 이름)
PRIORITY = ("recent_summaries", "open_ideas", "open_todos", "interests")


def _summary_line(convo: ConversationSession, timezone: str) -> str:
    local = convo.started_at.astimezone(ZoneInfo(timezone))
    title = f" '{convo.title}'" if convo.title else ""
    summary = " ".join((convo.summary or "").splitlines())
    return f"{local.month}월 {local.day}일{title}: {summary}"


async def load_memory(
    db: AsyncSession,
    settings: Settings,
    profile: UserProfile,
    now: datetime,
    exclude_session_id: str | None = None,
) -> MemoryContext:
    """exclude_session_id: 요약에서 뺄 대화(다시 여는 대화 자신, S3-26)."""
    since = now - timedelta(days=RECENT_DAYS)
    sessions = await db.execute(
        select(ConversationSession)
        .where(
            ConversationSession.status == SessionStatus.ENDED,
            ConversationSession.summary.is_not(None),
            ConversationSession.started_at >= since,
            ConversationSession.id != (exclude_session_id or ""),
        )
        .order_by(ConversationSession.started_at.desc())
        .limit(MAX_SUMMARIES)
    )
    ideas = await db.execute(
        select(Note.content)
        .where(Note.kind == NoteKind.IDEA, Note.done.is_(False))
        .order_by(Note.starred.desc(), Note.created_at.desc())
        .limit(MAX_IDEAS)
    )
    todos = await db.execute(
        select(Note.content)
        .where(Note.kind == NoteKind.TODO, Note.done.is_(False))
        .order_by(Note.created_at.desc())
        .limit(MAX_TODOS)
    )
    memory = MemoryContext(
        recent_summaries=[_summary_line(s, settings.timezone) for s in sessions.scalars()],
        open_ideas=list(ideas.scalars()),
        open_todos=list(todos.scalars()),
        interests=list(profile.interests or []),
    )
    return fit_to_budget(memory, settings.memory_budget_chars)


def fit_to_budget(memory: MemoryContext, budget: int) -> MemoryContext:
    """우선순위대로 예산(글자 수) 안에 드는 항목만 남긴다."""
    assert set(PRIORITY) == {f.name for f in fields(MemoryContext)}
    used = 0
    kept: dict[str, list[str]] = {}
    for name in PRIORITY:
        kept[name] = []
        for item in getattr(memory, name):
            text = one_line(item, ITEM_MAX)
            if not text or used + len(text) > budget:
                continue
            kept[name].append(text)
            used += len(text)
    return MemoryContext(**kept)
