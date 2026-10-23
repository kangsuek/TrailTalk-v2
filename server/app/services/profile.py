"""본인용 프로필(user_profile 단일 행) 조회·변경."""

from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Persona, UserProfile
from app.persona.loader import LoadedPersona, load_persona

PROFILE_ID = 1


async def get_or_create_profile(db: AsyncSession) -> UserProfile:
    """처음 조회하면 기본값으로 만든다."""
    profile = await db.get(UserProfile, PROFILE_ID)
    if profile is None:
        profile = UserProfile(id=PROFILE_ID, interests=[])
        db.add(profile)
        try:
            await db.commit()
        except IntegrityError:
            # 다른 요청이 먼저 만들었다(첫 GET과 PUT이 동시에 온 경우). 그 행을 쓴다
            await db.rollback()
            profile = await db.get(UserProfile, PROFILE_ID)
            if profile is None:
                raise
    return profile


async def _upsert_persona_row(db: AsyncSession, loaded: LoadedPersona) -> None:
    """persona 행(FK 대상)을 YAML 파일 기준으로 만들거나 갱신한다."""
    persona_id = loaded.persona.id
    row = await db.get(Persona, persona_id)
    if row is None:
        db.add(Persona(id=persona_id, yaml_path=str(loaded.path), version=loaded.version))
    else:
        row.yaml_path = str(loaded.path)
        row.version = loaded.version


async def _ensure_persona_row(db: AsyncSession, persona_dir: Path, persona_id: str) -> None:
    """없는 페르소나는 404 persona_not_found."""
    await _upsert_persona_row(db, load_persona(persona_dir, persona_id))


async def profile_with_persona(
    db: AsyncSession, settings: Settings
) -> tuple[UserProfile, LoadedPersona]:
    """프로필과 지금 쓰는 페르소나(없으면 기본). persona 행도 맞춰 둔다(세션 FK, 커밋은 호출자)."""
    profile = await get_or_create_profile(db)
    loaded = load_persona(settings.persona_dir, profile.persona_id or settings.default_persona)
    await _upsert_persona_row(db, loaded)
    return profile, loaded


def profile_chat_model(profile: UserProfile, settings: Settings) -> str:
    """대화 모델: 프로필 값, 없으면 서버 기본(LLM_CHAT_MODEL)."""
    return profile.chat_model.value if profile.chat_model else settings.llm_chat_model


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
