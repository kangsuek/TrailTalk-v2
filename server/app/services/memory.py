"""기억 서비스: 대화 프롬프트용 기억(`persona/memory.load_memory`)을 앱 MCP도 같이 쓴다.

대화 프롬프트는 관심사까지 넣고, 앱 `get_memory`는 관심사를 빼고 호칭과 함께 돌려준다
(MCP/README 결정 5).
"""

from dataclasses import replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import UserProfile
from app.persona.memory import MAX_TODOS, load_memory
from app.persona.prompt import MemoryContext

__all__ = ["MAX_TODOS", "load_app_memory", "load_memory"]


async def load_app_memory(
    db: AsyncSession, settings: Settings, profile: UserProfile, now: datetime
) -> MemoryContext:
    """앱용 기억: 최근 일지 요약·열린 아이디어·열린 할 일(`MAX_TODOS`개까지). 관심사는 비운다."""
    memory = await load_memory(db, settings, profile, now)
    return replace(memory, interests=[])
