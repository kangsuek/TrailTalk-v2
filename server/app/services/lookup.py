"""id 접두사 조회: 목록에는 id 앞 8자만 보여 주고, 다른 도구는 4~36자 접두사로 한 건을 찾는다."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SHORT_ID_CHARS = 8
MIN_PREFIX_CHARS = 4
_PREFIX = re.compile(r"[0-9a-f-]+")


class LookupFailure(Exception):
    """접두사로 한 건을 정하지 못했다. 메시지는 사용자(모델)가 고칠 수 있는 한국어 한 문장."""


def short_id(full_id: str) -> str:
    return full_id[:SHORT_ID_CHARS]


async def resolve_prefix[T](db: AsyncSession, model: type[T], prefix: str, label: str) -> T:
    prefix = prefix.strip().lower()
    if len(prefix) < MIN_PREFIX_CHARS or not _PREFIX.fullmatch(prefix):
        raise LookupFailure(
            f"{label} id는 목록에 나온 영숫자 {SHORT_ID_CHARS}자를 그대로 넣으세요."
        )
    rows = (await db.scalars(select(model).where(model.id.like(f"{prefix}%")).limit(2))).all()
    if not rows:
        raise LookupFailure(f"일치하는 {label}가 없습니다. 목록에서 id를 다시 확인하세요.")
    if len(rows) > 1:
        raise LookupFailure("id가 여러 건과 일치합니다. 더 긴 id를 쓰세요.")
    return rows[0]
