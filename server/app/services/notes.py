"""노트 서비스: 웹 API·내부 MCP·Claude 앱 MCP가 같은 규칙을 쓰도록 모은 곳.

저장은 세션을 인자로 받는다(내부 MCP는 자기 대화 세션을, 앱 MCP는 앱 메모 세션을 넘긴다).
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, NoteKind
from app.errors import AppError
from app.services.text import escape_like

SEARCH_LIMIT = 10


class NoteNotFound(AppError):
    def __init__(self) -> None:
        super().__init__("note_not_found", "노트를 찾을 수 없습니다.", 404)


async def save_note(
    db: AsyncSession,
    *,
    session_id: str,
    kind: NoteKind,
    content: str,
    turn_id: str | None = None,
) -> Note:
    """노트를 저장한다(내용은 호출자가 길이를 검증한 글, 앞뒤 공백은 뺀다)."""
    note = Note(session_id=session_id, turn_id=turn_id, kind=kind, content=content.strip())
    db.add(note)
    await db.commit()
    return note


async def search_notes(
    db: AsyncSession, terms: list[str], since: datetime, limit: int = SEARCH_LIMIT
) -> list[Note]:
    """since 이후 만든 노트 중 모든 낱말이 들어간 것을 최신순으로 limit건."""
    query = select(Note).where(Note.created_at >= since)
    for term in terms:
        query = query.where(Note.content.like(f"%{escape_like(term)}%", escape="\\"))
    rows = await db.execute(query.order_by(Note.created_at.desc()).limit(limit))
    return list(rows.scalars())


def since_days(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


async def get_note(db: AsyncSession, note_id: str) -> Note:
    note = await db.get(Note, note_id)
    if note is None:
        raise NoteNotFound()
    return note


async def update_note(db: AsyncSession, note_id: str, changes: dict[str, Any]) -> Note:
    """별표·완료·내용 중 준 필드만 바꾼다. 값에 null은 쓸 수 없다(422 validation_error)."""
    note = await get_note(db, note_id)
    for name, value in changes.items():
        if value is None:
            raise AppError("validation_error", f"{name}에는 null을 쓸 수 없습니다.", 422)
    for name, value in changes.items():
        setattr(note, name, value)
    await db.commit()
    return note


async def delete_note(db: AsyncSession, note_id: str) -> Note:
    """노트를 지우고 지운 노트를 돌려준다(출처와 무관하게 지운다)."""
    note = await get_note(db, note_id)
    await db.delete(note)
    await db.commit()
    return note
