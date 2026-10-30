"""Claude 앱이 저장하는 일지·앱 메모(claude_app 세션)의 저장 규칙 (MCP/design.md 3절).

- 앱 일지: 같은 날(서버 시간대) 같은 제목이면 갱신한다. 조회 후 갱신이며 `app_day`·제목 유니크
  인덱스가 최후의 방어선이다(동시 호출로 충돌하면 다시 조회해 한 번 더 시도한다).
- 갱신은 넘긴 항목만 바꾼다. 노트(아이디어·할 일·메모)는 기존 노트를 유지하고 없는 내용만 더한다.
- 앱 메모: 일지 없이 저장하는 노트를 날짜별 세션 하나에 모은다.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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

USER_LABELS = frozenset({"나", "사용자", "me", "user"})
ASSISTANT_LABELS = frozenset({"claude", "assistant", "ai", "어시스턴트"})
_HEADER = re.compile(r"^\s*([^\s:：]{1,20})\s*[:：]\s?(.*)$")


class AppJournalError(Exception):
    """저장 규칙 위반. 메시지는 사용자에게 보여 줄 한국어 한 문장."""


def local_day(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def normalize(text: str) -> str:
    """노트 같은 내용 판정: 공백을 하나로 줄이고 대소문자를 무시한다."""
    return " ".join(text.split()).lower()


def split_transcript(
    text: str, assistant_names: frozenset[str] = frozenset()
) -> list[tuple[TurnRole, str]]:
    """'나: …'·'Claude: …' 머리표가 있는 줄을 발화로 풀고, 머리표 없는 줄은 앞 발화에 잇는다.

    머리표는 알려진 화자(나·사용자·Claude·assistant와 설정한 상대 이름)만 인정한다. 본문 속
    '예:'·'http:'·'10:30' 같은 줄은 새 발화로 쪼개지 않고 앞 발화에 이어 붙인다. 알려진 머리표가
    하나도 없으면 사용자 한 턴이다."""
    assistants = ASSISTANT_LABELS | {name.lower() for name in assistant_names}
    known = USER_LABELS | assistants

    def header(line: str):
        match = _HEADER.match(line)
        return match if match and match.group(1).lower() in known else None

    turns: list[tuple[TurnRole, list[str]]] = []
    for line in text.splitlines():
        match = header(line)
        if match:
            role = TurnRole.USER if match.group(1).lower() in USER_LABELS else TurnRole.ASSISTANT
            turns.append((role, [match.group(2)]))
        elif turns:
            turns[-1][1].append(line)
        elif line.strip():
            turns.append((TurnRole.USER, [line]))
    if not any(header(line) for line in text.splitlines()):
        stripped = text.strip()
        return [(TurnRole.USER, stripped)] if stripped else []
    result = [(role, "\n".join(lines).strip()) for role, lines in turns]
    return [(role, body) for role, body in result if body]


@dataclass
class SaveResult:
    convo: ConversationSession
    created: bool
    changed: list[str] = field(default_factory=list)
    counts: dict[NoteKind, int] = field(default_factory=dict)
    added_notes: int = 0


async def _find_journal(db: AsyncSession, day: date, title: str) -> ConversationSession | None:
    return await db.scalar(
        select(ConversationSession).where(
            ConversationSession.mode == SessionMode.CLAUDE_APP,
            ConversationSession.app_kind == AppKind.JOURNAL,
            ConversationSession.app_day == day,
            ConversationSession.title == title,
        )
    )


async def _save_once(
    db: AsyncSession,
    tz: ZoneInfo,
    now: datetime,
    title: str,
    fields: dict,
    notes: dict[NoteKind, list[str] | None],
    assistant_names: frozenset[str],
) -> SaveResult:
    day = local_day(now, tz)
    convo = await _find_journal(db, day, title)
    created = convo is None
    changed: list[str] = []
    if convo is None:
        summary = fields.get("summary")
        if not summary:
            raise AppJournalError("새 일지에는 summary(요약)가 필요합니다.")
        convo = ConversationSession(
            mode=SessionMode.CLAUDE_APP,
            status=SessionStatus.ENDED,
            started_at=now,
            ended_at=now,
            title=title,
            summary=None,
            tags=[],
            checks=[],
            extract_status=ExtractStatus.DONE,
            app_kind=AppKind.JOURNAL,
            app_day=day,
        )
        db.add(convo)
        await db.flush()
    if "summary" in fields:
        convo.summary = fields["summary"]
        changed.append("summary")
    if "tags" in fields:
        convo.tags = list(fields["tags"])
        changed.append("tags")
    if "transcript" in fields:
        await db.execute(delete(Turn).where(Turn.session_id == convo.id))
        for seq, (role, body) in enumerate(
            split_transcript(fields["transcript"], assistant_names), start=1
        ):
            db.add(Turn(session_id=convo.id, seq=seq, role=role, text=body, created_at=now))
        changed.append("transcript")

    existing = (await db.scalars(select(Note).where(Note.session_id == convo.id))).all()
    seen = {(n.kind, normalize(n.content)) for n in existing}
    added = 0
    for kind, items in notes.items():
        if items is None:
            continue
        added_here = 0
        for item in items:
            key = (kind, normalize(item))
            if key in seen:
                continue
            seen.add(key)
            db.add(Note(session_id=convo.id, kind=kind, content=item.strip()))
            added_here += 1
        if added_here:
            changed.append(f"{kind.value}s")
        added += added_here
    await db.commit()
    rows = (await db.scalars(select(Note).where(Note.session_id == convo.id))).all()
    counts = {kind: sum(n.kind is kind for n in rows) for kind in NoteKind}
    return SaveResult(convo, created, list(dict.fromkeys(changed)), counts, added)


async def save_app_journal(
    db: AsyncSession,
    tz: ZoneInfo,
    now: datetime,
    title: str,
    *,
    summary: str | None = None,
    ideas: list[str] | None = None,
    todos: list[str] | None = None,
    memos: list[str] | None = None,
    tags: list[str] | None = None,
    transcript: str | None = None,
    assistant_names: frozenset[str] = frozenset(),
) -> SaveResult:
    """앱 일지를 저장(새로 만들거나 같은 날 같은 제목을 갱신)한다. 동시 저장이 인덱스에 부딪히면
    한 번 다시 조회해 갱신한다."""
    title = " ".join(title.split())
    fields = {
        key: value
        for key, value in (("summary", summary), ("tags", tags), ("transcript", transcript))
        if value is not None
    }
    notes = {NoteKind.IDEA: ideas, NoteKind.TODO: todos, NoteKind.MEMO: memos}
    for attempt in (1, 2):
        try:
            return await _save_once(db, tz, now, title, fields, notes, assistant_names)
        except IntegrityError:
            await db.rollback()
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def memo_title(day: date) -> str:
    return f"앱 메모 · {day.month}월 {day.day}일"


async def ensure_memo_session(db: AsyncSession, tz: ZoneInfo, now: datetime) -> ConversationSession:
    """호출 시각의 현지 날짜 앱 메모 세션을 돌려준다(없으면 만든다). 병렬 호출이 같은 날 세션을
    둘 만들지 못하게 `app_day` 유니크 인덱스에 기대고, 충돌하면 다시 조회한다."""
    day = local_day(now, tz)
    query = select(ConversationSession).where(
        ConversationSession.mode == SessionMode.CLAUDE_APP,
        ConversationSession.app_kind == AppKind.MEMO,
        ConversationSession.app_day == day,
    )
    convo = await db.scalar(query)
    if convo is not None:
        return convo
    convo = ConversationSession(
        mode=SessionMode.CLAUDE_APP,
        status=SessionStatus.ENDED,
        started_at=now,
        ended_at=now,
        title=memo_title(day),
        tags=[],
        checks=[],
        extract_status=ExtractStatus.DONE,
        app_kind=AppKind.MEMO,
        app_day=day,
    )
    db.add(convo)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        convo = await db.scalar(query)
        if convo is None:
            raise
    return convo


async def save_app_note(
    db: AsyncSession, tz: ZoneInfo, now: datetime, kind: NoteKind, content: str
) -> tuple[Note, ConversationSession]:
    """일지 없이 저장하는 노트를 그날 앱 메모 세션에 붙인다."""
    memo = await ensure_memo_session(db, tz, now)
    note = Note(session_id=memo.id, kind=kind, content=content.strip(), created_at=now)
    db.add(note)
    await db.commit()
    return note, memo
