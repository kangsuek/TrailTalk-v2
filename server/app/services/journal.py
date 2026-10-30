"""일지 서비스: 웹 API(`api/journal.py`)와 Claude 앱 MCP가 같은 규칙을 쓰도록 모은 곳.

목록(현지 날짜 범위), 상세 구성 요소, 제목 수정, 삭제, 대화 전문 검색, 앱 출처 판정을 둔다.
HTTP·MCP 표현(응답 모델, 도구 문구)은 부르는 쪽이 만든다. 서비스는 DB 행과 단순한 값만 주고받는다.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from sqlalchemy import and_, exists, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.db.models import ConversationSession, Note, NoteKind, Turn, TurnRole
from app.errors import AppError
from app.services import conversation

logger = logging.getLogger("trailtalk.journal")

DEFAULT_DAYS = 30
MAX_DAYS = 366
# 시간대 변환이 넘치지 않는 범위(0001-01-01·9999-12-31 근처는 UTC로 바꿀 때 OverflowError)
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(9998, 12, 31)
TITLE_MAX_CHARS = 200

# 앱(Claude 앱 MCP)에서 만든 세션의 모드 값. 모드 열거(SessionMode)에 claude_app이 생기기 전에도
# 판정 함수를 부를 수 있도록 값으로 비교한다
APP_MODE = "claude_app"

# 대화 전문 검색
CONVO_HITS = 8  # 찾은 말 최대 건수(최신순)
CONVO_TERMS = 3  # 검색어를 공백으로 나눈 낱말 중 쓰는 개수(모두 들어간 말을 찾는다)


class AppTitleConflict(AppError):
    def __init__(self) -> None:
        super().__init__("title_conflict", "같은 날 같은 제목의 앱 일지가 이미 있습니다.", 409)


def is_app_session(convo: ConversationSession) -> bool:
    """Claude 앱에서 만든 세션(앱 일지·앱 메모)인가."""
    mode = convo.mode
    return getattr(mode, "value", mode) == APP_MODE


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_terms(keyword: str) -> list[str]:
    """검색어를 공백으로 나눈 낱말(최대 CONVO_TERMS개). 모두 들어간 것을 찾는다."""
    return keyword.split()[:CONVO_TERMS]


def validate_range(from_: date, to: date) -> None:
    if not (MIN_DATE <= from_ and to <= MAX_DATE):
        raise AppError("invalid_range", "조회할 수 없는 날짜입니다.", 422)
    if from_ > to:
        raise AppError("invalid_range", "시작 날짜가 끝 날짜보다 늦습니다.", 422)
    if (to - from_).days >= MAX_DAYS:
        raise AppError("invalid_range", f"한 번에 {MAX_DAYS}일까지 조회할 수 있습니다.", 422)


def default_range(tz: ZoneInfo, from_: date | None, to: date | None) -> tuple[date, date]:
    """생략한 쪽을 채운다: to는 오늘(현지), from은 to에서 30일 전까지."""
    to = to or datetime.now(tz).date()
    from_ = from_ or to - timedelta(days=DEFAULT_DAYS - 1)
    return from_, to


@dataclass
class JournalRow:
    convo: ConversationSession
    counts: dict[NoteKind, int]


async def note_counts(db: AsyncSession, session_ids: list[str]) -> dict[str, dict[NoteKind, int]]:
    """대화별 종류별 노트 개수."""
    result: dict[str, dict[NoteKind, int]] = {sid: {} for sid in session_ids}
    if not session_ids:
        return result
    rows = await db.execute(
        select(Note.session_id, Note.kind, func.count())
        .where(Note.session_id.in_(session_ids))
        .group_by(Note.session_id, Note.kind)
    )
    for session_id, kind, count in rows:
        result[session_id][kind] = count
    return result


async def list_journals(
    db: AsyncSession, tz: ZoneInfo, from_: date | None = None, to: date | None = None
) -> list[JournalRow]:
    """현지 날짜 범위(from~to, 둘 다 포함)의 일지, 최신순. 기본은 최근 30일.

    사용자가 한마디도 하지 않은 대화(인사말만 있는 것)는 뺀다. 진행 중인 대화는 나온다.
    """
    from_, to = default_range(tz, from_, to)
    validate_range(from_, to)
    start = datetime.combine(from_, time.min, tz)
    end = datetime.combine(to + timedelta(days=1), time.min, tz)
    spoke = exists().where(Turn.session_id == ConversationSession.id, Turn.role == TurnRole.USER)
    rows = await db.execute(
        select(ConversationSession)
        .options(defer(ConversationSession.system_prompt))  # 응답에 쓰지 않는 큰 글
        .where(
            ConversationSession.started_at >= start,
            ConversationSession.started_at < end,
            spoke,
        )
        .order_by(ConversationSession.started_at.desc(), ConversationSession.id)
    )
    sessions = list(rows.scalars())
    counts = await note_counts(db, [s.id for s in sessions])
    return [JournalRow(s, counts[s.id]) for s in sessions]


@dataclass
class JournalParts:
    convo: ConversationSession
    notes: list[Note]
    turns: list[Turn]

    @property
    def counts(self) -> dict[NoteKind, int]:
        return {kind: sum(n.kind is kind for n in self.notes) for kind in NoteKind}


async def get_journal(db: AsyncSession, session_id: str) -> JournalParts:
    """일지 상세의 DB 행들. 목록에서 빠지는 대화(사용자 발화 없음)도 ID로는 조회된다."""
    convo = await conversation.get_session(db, session_id)
    notes = await db.execute(
        select(Note).where(Note.session_id == session_id).order_by(Note.created_at, Note.id)
    )
    turns = await db.execute(select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq))
    return JournalParts(convo, list(notes.scalars()), list(turns.scalars()))


async def _same_day_title_taken(
    db: AsyncSession, convo: ConversationSession, title: str, tz: ZoneInfo
) -> bool:
    day = convo.started_at.astimezone(tz).date()
    start = datetime.combine(day, time.min, tz)
    end = start + timedelta(days=1)
    rows = await db.scalars(
        select(ConversationSession).where(
            ConversationSession.id != convo.id,
            ConversationSession.title == title,
            ConversationSession.started_at >= start,
            ConversationSession.started_at < end,
        )
    )
    return any(is_app_session(other) for other in rows)


async def rename_journal(
    db: AsyncSession, session_id: str, title: str, tz: ZoneInfo
) -> ConversationSession:
    """대화 제목을 고친다(검증된 제목). 고친 제목은 일지를 다시 정리해도 바뀌지 않는다.

    앱 세션이면 같은 날 같은 제목의 다른 앱 일지가 있을 때 409 title_conflict로 거절한다
    (앱의 저장 도구가 같은 날 같은 제목을 같은 일지로 보기 때문이다).
    """
    convo = await conversation.get_session(db, session_id)
    if is_app_session(convo) and await _same_day_title_taken(db, convo, title, tz):
        raise AppTitleConflict()
    convo.title = title
    convo.title_edited = True
    await db.commit()
    return convo


async def delete_journal(app: FastAPI, db: AsyncSession, session_id: str) -> None:
    """대화를 지운다(전문·노트까지). 진행 중이면 409 session_active, 답변 중이면
    409 turn_in_progress."""
    await conversation.delete_session(app, db, session_id)


@dataclass
class ConversationHit:
    turn: Turn
    title: str | None
    started_at: datetime


@dataclass
class ConversationSearch:
    hits: list[ConversationHit]
    neighbors: dict[tuple[str, int], Turn]  # (session_id, seq) → 앞뒤 말


async def search_conversations(
    db: AsyncSession,
    terms: list[str],
    *,
    current_session_id: str | None = None,
    current_user_turn_id: str | None = None,
) -> ConversationSearch:
    """모든 낱말이 들어간 말을 최신순으로 CONVO_HITS건과 앞뒤 말까지 찾는다(읽기만 한다).

    current_session_id를 주면 그 대화는 current_user_turn_id보다 앞선 말만 본다(방금 한 질문과
    하고 있는 답이 결과를 차지하지 않게). 그 턴이 없으면(인사말 중) 그 대화 전체를 본다.
    """
    cutoff = (
        await db.scalar(select(Turn.seq).where(Turn.id == current_user_turn_id))
        if current_user_turn_id
        else None
    )
    earlier = (
        or_(Turn.session_id != current_session_id, Turn.seq < cutoff)
        if cutoff is not None and current_session_id is not None
        else true()
    )
    query = (
        select(Turn, ConversationSession.title, ConversationSession.started_at)
        .join(ConversationSession, Turn.session_id == ConversationSession.id)
        .where(earlier)
    )
    for term in terms:
        query = query.where(Turn.text.like(f"%{escape_like(term)}%", escape="\\"))
    rows = (
        await db.execute(query.order_by(Turn.created_at.desc(), Turn.seq.desc()).limit(CONVO_HITS))
    ).all()
    hits = [ConversationHit(turn, title, started_at) for turn, title, started_at in rows]
    if not hits:
        return ConversationSearch([], {})
    around = or_(
        *(
            and_(
                Turn.session_id == h.turn.session_id,
                Turn.seq.in_((h.turn.seq - 1, h.turn.seq + 1)),
            )
            for h in hits
        )
    )
    neighbor_rows = await db.execute(select(Turn).where(around, earlier))
    return ConversationSearch(hits, {(t.session_id, t.seq): t for t in neighbor_rows.scalars()})
