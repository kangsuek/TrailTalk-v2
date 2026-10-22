"""본인용 프로필(user_profile 단일 행) 조회·변경."""

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Persona, UserProfile
from app.persona.loader import load_persona

PROFILE_ID = 1


async def get_or_create_profile(db: AsyncSession) -> UserProfile:
    """처음 조회하면 기본값으로 만든다."""
    profile = await db.get(UserProfile, PROFILE_ID)
    if profile is None:
        profile = UserProfile(id=PROFILE_ID, interests=[])
        db.add(profile)
        await db.commit()
    return profile


async def _ensure_persona_row(db: AsyncSession, persona_dir: Path, persona_id: str) -> None:
    """persona 행(FK 대상)을 YAML 파일 기준으로 만들거나 갱신한다. 없는 페르소나는 404."""
    loaded = load_persona(persona_dir, persona_id)
    row = await db.get(Persona, persona_id)
    if row is None:
        db.add(Persona(id=persona_id, yaml_path=str(loaded.path), version=loaded.version))
    else:
        row.yaml_path = str(loaded.path)
        row.version = loaded.version


async def update_profile(
    db: AsyncSession, persona_dir: Path, changes: dict[str, Any]
) -> UserProfile:
    """보낸 필드만 바꾼다. 하나라도 틀리면(없는 페르소나) 아무것도 바꾸지 않는다."""
    profile = await get_or_create_profile(db)
    persona_id = changes.get("persona_id")
    if persona_id is not None:
        await _ensure_persona_row(db, persona_dir, persona_id)
    for field, value in changes.items():
        setattr(profile, field, value)
    await db.commit()
    return profile
