"""일지·노트 API(client-contract 3절): 일지 목록·상세·제목 수정·삭제·다시 정리, 노트 별표·완료·
내용 수정, 시작 화면의 "지난 아이디어 이어 가기".

날짜는 서버 시간대(settings.timezone)의 현지 날짜다. 목록 항목에 현지 날짜(date)를 실어 클라이언트가
시간대 계산 없이 날짜별로 묶게 한다. 요약은 줄 목록으로 준다.
검색 출처 인용(summary_cites·citations·노트 cites)과 첨부(turns[].attachments)는 검색·첨부가
생기는 M5 전까지 빈 목록이다.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, StrictBool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    NOTE_MAX_CHARS,
    ConversationSession,
    ExtractStatus,
    Note,
    NoteKind,
    SessionStatus,
    Turn,
)
from app.db.session import DbSession
from app.jobs import extract
from app.services import conversation
from app.services import journal as journal_service
from app.services import notes as note_service
from app.services.conversation import SessionNotEnded
from app.services.journal import TITLE_MAX_CHARS

router = APIRouter(tags=["journal"])

IDEA_LIST_DEFAULT = 5
IDEA_LIST_MAX = 20


class NoteCounts(BaseModel):
    idea: int
    todo: int
    memo: int


class JournalItem(BaseModel):
    id: str
    date: date  # 대화를 시작한 현지 날짜
    started_at: datetime
    ended_at: datetime | None
    status: Literal["active", "paused", "ended"]
    title: str | None
    summary: list[str]
    tags: list[str]
    # 일지 정리 상태. null이면 정리 기록이 없다(끝나지 않은 대화, 정리가 생기기 전에 끝난 대화)
    journal_status: Literal["pending", "done", "failed"] | None
    counts: NoteCounts
    # 저장한 곳: Claude 앱 MCP("app") 또는 웹 대화("web"). 클라이언트는 모르는 값을 web처럼 다룬다
    source: Literal["app", "web"]


class NoteOut(BaseModel):
    id: str
    kind: Literal["idea", "todo", "memo"]
    content: str
    starred: bool
    done: bool
    created_at: datetime
    cites: list[int]  # 메모의 근거 출처 번호(citations의 n). 없으면 빈 목록

    @classmethod
    def of(cls, note: Note, cites: list[int] | None = None) -> "NoteOut":
        return cls(
            id=note.id,
            kind=note.kind.value,
            content=note.content,
            starred=note.starred,
            done=note.done,
            created_at=note.created_at,
            cites=cites or [],
        )


class AttachmentOut(BaseModel):
    """턴에 붙은 첨부(M5). 파일은 GET /api/attachments/{id}(썸네일은 ?thumb=1)."""

    id: str
    name: str
    mime: str
    size: int
    thumb: bool  # 썸네일이 있다(이미지)


class TurnOut(BaseModel):
    id: str
    seq: int
    role: Literal["user", "assistant"]
    text: str
    interrupted: bool  # 끝까지 말하지 못한 답변(연결 끊김·끼어들기 등)
    merged_from: str | None  # 병합된 뒷말이면 앞말 턴 ID(두 행을 한 말풍선으로)
    created_at: datetime
    attachments: list[AttachmentOut]

    @classmethod
    def of(cls, turn: Turn) -> "TurnOut":
        return cls(
            id=turn.id,
            seq=turn.seq,
            role=turn.role.value,
            text=turn.text,
            interrupted=turn.interrupted,
            merged_from=turn.merged_from,
            created_at=turn.created_at,
            attachments=[],
        )


class CitationOut(BaseModel):
    n: int
    title: str  # 기사·문서 제목(없으면 호스트 이름)
    url: str


class JournalDetail(BaseModel):
    session: JournalItem
    # session.summary 줄마다 근거 출처 번호(같은 길이, 없으면 빈 목록)와 인용 목록
    summary_cites: list[list[int]]
    citations: list[CitationOut]
    # 확인할 것. null이면 예전 형식이다(요약 첫 줄이 결론이 아니다. 끝난 대화면 다시 정리할 수
    # 있다). 새 형식이면 session.summary 첫 줄이 결론, 나머지가 '알게 된 것'이다
    checks: list[str] | None
    # 전문의 캐릭터 화자 이름(그 대화의 페르소나 YAML). 클라이언트는 이름을 코드에 두지 않는다
    persona_name: str
    notes: list[NoteOut]
    turns: list[TurnOut]


def _content(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= NOTE_MAX_CHARS:
        raise ValueError(f"1~{NOTE_MAX_CHARS}자로 입력하세요")
    return value


def _title(value: str) -> str:
    value = " ".join(value.split())  # 목록에 한 줄로 보이므로 줄바꿈·연속 공백은 한 칸으로
    if not 1 <= len(value) <= TITLE_MAX_CHARS:
        raise ValueError(f"1~{TITLE_MAX_CHARS}자로 입력하세요")
    return value


class JournalPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, AfterValidator(_title)]


class NotePatch(BaseModel):
    """보낸 필드만 바꾼다."""

    model_config = ConfigDict(extra="forbid")

    starred: StrictBool | None = None
    done: StrictBool | None = None
    content: Annotated[str, AfterValidator(_content)] | None = None


class OpenIdea(BaseModel):
    id: str
    content: str
    starred: bool
    session_id: str  # 이 아이디어가 나온 대화(일지 상세로 연다)
    created_at: datetime
    counts: NoteCounts  # 그 대화에 저장된 종류별 개수(일지 목록의 counts와 같은 기준)


def _number(
    convo: ConversationSession, notes: list[Note]
) -> tuple[list[list[int]], dict[str, list[int]], list[dict]]:
    """인용 번호: 남아 있는 요약 줄 → 메모(만든 순) 차례로 처음 인용된 출처부터 1번.
    (요약 줄마다 번호, 노트 ID → 번호, 인용 목록)"""
    lines = (convo.summary or "").splitlines()
    stored = list(convo.summary_cites or [])
    summary_urls = [
        stored[i] if i < len(stored) and isinstance(stored[i], list) else []
        for i in range(len(lines))
    ]
    memos = [n for n in notes if n.kind is NoteKind.MEMO and n.cites]
    titles = {c["url"]: c["title"] for c in convo.citations or [] if isinstance(c, dict)}
    summary_ids, memo_ids, citations = extract.number_citations(
        summary_urls, [n.cites for n in memos], titles
    )
    return summary_ids, {n.id: ids for n, ids in zip(memos, memo_ids, strict=True)}, citations


def _counts_of(counts: dict[NoteKind, int]) -> NoteCounts:
    return NoteCounts(**{kind.value: counts.get(kind, 0) for kind in NoteKind})


def _item(convo: ConversationSession, counts: dict[NoteKind, int], tz: ZoneInfo) -> JournalItem:
    return JournalItem(
        id=convo.id,
        date=convo.started_at.astimezone(tz).date(),
        started_at=convo.started_at,
        ended_at=convo.ended_at,
        status=convo.status.value,
        title=convo.title,
        summary=(convo.summary or "").splitlines(),
        tags=list(convo.tags or []),
        journal_status=convo.extract_status.value if convo.extract_status else None,
        counts=_counts_of(counts),
        source="app" if journal_service.is_app_session(convo) else "web",
    )


async def _item_of(request: Request, db: AsyncSession, convo: ConversationSession) -> JournalItem:
    tz = ZoneInfo(request.app.state.settings.timezone)
    counts = await journal_service.note_counts(db, [convo.id])
    return _item(convo, counts[convo.id], tz)


@router.get("/journal")
async def list_journal(
    request: Request,
    db: DbSession,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> list[JournalItem]:
    """현지 날짜 범위(from~to, 둘 다 포함)의 일지. 기본은 최근 30일. 최신순.

    사용자가 한마디도 하지 않은 대화(인사말만 있는 것)는 빼고 준다. 진행 중인 대화는 나온다.
    """
    tz = ZoneInfo(request.app.state.settings.timezone)
    rows = await journal_service.list_journals(db, tz, from_, to)
    return [_item(row.convo, row.counts, tz) for row in rows]


@router.get("/journal/{session_id}")
async def get_journal(session_id: str, request: Request, db: DbSession) -> JournalDetail:
    """일지 상세. 목록에서 빠지는 대화(사용자 발화 없음)도 ID로는 조회된다."""
    parts = await journal_service.get_journal(db, session_id)
    convo, note_rows = parts.convo, parts.notes
    tz = ZoneInfo(request.app.state.settings.timezone)
    counts = parts.counts
    summary_ids, note_ids, citations = _number(convo, note_rows)
    return JournalDetail(
        session=_item(convo, counts, tz),
        summary_cites=summary_ids,
        citations=[CitationOut(**c) for c in citations],
        checks=list(convo.checks) if convo.checks is not None else None,
        persona_name=(
            request.app.state.settings.app_speaker_name
            if journal_service.is_app_session(convo)
            else extract.assistant_name(request.app, convo.persona_id)
        ),
        notes=[NoteOut.of(n, note_ids.get(n.id)) for n in note_rows],
        turns=[TurnOut.of(t) for t in parts.turns],
    )


@router.patch("/journal/{session_id}")
async def update_journal(
    session_id: str, body: JournalPatch, request: Request, db: DbSession
) -> JournalItem:
    """대화 제목을 고친다. 고친 제목은 일지를 다시 정리해도 바뀌지 않는다."""
    tz = ZoneInfo(request.app.state.settings.timezone)
    convo = await journal_service.rename_journal(db, session_id, body.title, tz)
    return await _item_of(request, db, convo)


@router.delete("/journal/{session_id}", status_code=204)
async def delete_journal(session_id: str, request: Request, db: DbSession) -> None:
    """대화를 지운다(전문·노트까지). 진행 중인 대화는 409 session_active, 답변을 만드는 중이면
    409 turn_in_progress. 쉬는 중이면 CLI를 정리하고, 돌던 일지 정리는 멈춘다."""
    await journal_service.delete_journal(request.app, db, session_id)


@router.post("/journal/{session_id}/retry", status_code=202)
async def retry_journal(session_id: str, request: Request, db: DbSession) -> JournalItem:
    """정리에 실패한(또는 정리 기록이 없는) 끝난 대화, 예전 형식으로 정리된 대화를 다시 정리한다.
    정리 중이거나 새 형식으로 정리를 마쳤으면 그대로 둔다.

    정리는 백그라운드로 돈다. 응답의 journal_status가 pending이면 상세를 다시 불러와 끝을 본다.
    """
    app = request.app
    convo = await conversation.get_session(db, session_id)
    if journal_service.is_app_session(convo):
        return await _item_of(
            request, db, convo
        )  # 앱이 정리한 것을 저장한 일지라 다시 정리하지 않는다
    if convo.status is not SessionStatus.ENDED:
        raise SessionNotEnded()
    # 예전 형식(확인할 것 없이 요약 줄만)으로 정리를 마친 일지도 새 형식으로 다시 정리한다. 그 다시
    # 정리가 실패해(failed) 다시 누른 경우도 같은 요청이다(요약이 있으면 예전 형식이고, 새 대화의 첫
    # 정리 실패는 요약이 없다). 인사만 나눈 대화(요약 없음)는 예전 형식이 아니다
    old_format = (
        convo.extract_status in (ExtractStatus.DONE, ExtractStatus.FAILED)
        and convo.checks is None
        and bool(convo.summary)
    )
    if convo.extract_status in (None, ExtractStatus.FAILED) or old_format:
        if old_format:
            app.state.reformat_requests.add(session_id)
        convo.extract_status = ExtractStatus.PENDING
        await db.commit()
        extract.ensure_extraction(app, session_id)
    return await _item_of(request, db, convo)


@router.get("/notes/open-ideas")
async def open_ideas(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=IDEA_LIST_MAX)] = IDEA_LIST_DEFAULT,
) -> list[OpenIdea]:
    """시작 화면의 "지난 아이디어 이어 가기" 목록. 완료하지 않은 아이디어를 대화당 하나씩(그 대화의
    가장 최근 아이디어) 만든 날짜의 역순으로 최대 limit개 주고, 항목마다 그 대화의 종류별 노트
    개수를 붙인다. 없으면 빈 목록."""
    rank = (
        func.row_number()
        .over(
            partition_by=Note.session_id,
            order_by=(Note.created_at.desc(), Note.id.desc()),
        )
        .label("rank")
    )
    newest = (
        select(Note.id, rank).where(Note.kind == NoteKind.IDEA, Note.done.is_(False)).subquery()
    )
    rows = await db.scalars(
        select(Note)
        .join(newest, newest.c.id == Note.id)
        .where(newest.c.rank == 1)
        .order_by(Note.created_at.desc(), Note.id.desc())
        .limit(limit)
    )
    notes = list(rows)
    counts = await journal_service.note_counts(db, list({n.session_id for n in notes}))
    return [
        OpenIdea(
            id=n.id,
            content=n.content,
            starred=n.starred,
            session_id=n.session_id,
            created_at=n.created_at,
            counts=_counts_of(counts[n.session_id]),
        )
        for n in notes
    ]


@router.patch("/notes/{note_id}")
async def update_note(note_id: str, body: NotePatch, db: DbSession) -> NoteOut:
    """별표·완료·내용 중 보낸 필드만 바꾼다. 보낸 필드에 null은 쓸 수 없다."""
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    note = await note_service.update_note(db, note_id, changes)
    cites: list[int] = []
    if note.kind is NoteKind.MEMO and note.cites:
        # 상세와 같은 번호를 돌려준다(그 일지의 요약·메모 전체로 매긴다)
        convo = await db.get(ConversationSession, note.session_id)
        rows = await db.execute(
            select(Note)
            .where(Note.session_id == note.session_id)
            .order_by(Note.created_at, Note.id)
        )
        _, note_ids, _ = _number(convo, list(rows.scalars()))
        cites = note_ids.get(note.id, [])
    return NoteOut.of(note, cites)
