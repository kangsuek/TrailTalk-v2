"""본인용 프로필(user_profile 단일 행) 조회·변경."""

from pathlib import Path
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from app.config import Settings
from app.db.models import Persona, UserProfile
from app.db.types import utcnow
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
    """persona 행(FK 대상)을 YAML 파일 기준으로 만들거나 갱신한다.

    읽고 나서 넣는 방식은 빈 DB에서 두 세션이 동시에 처음 시작될 때 둘 다 INSERT를 시도해
    UNIQUE constraint failed: persona.id가 난다. DB가 원자적으로 처리하는 upsert를 쓴다."""
    statement = sqlite_insert(Persona).values(
        id=loaded.persona.id, yaml_path=str(loaded.path), version=loaded.version
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[Persona.id],
            set_={
                "yaml_path": statement.excluded.yaml_path,
                "version": statement.excluded.version,
                "updated_at": utcnow(),  # ON CONFLICT에는 모델의 onupdate가 적용되지 않는다
            },
        )
    )
    # 이 세션이 이미 들고 있던 행 객체는 DB 값과 다를 수 있어 다시 읽게 한다
    row = db.identity_map.get(identity_key(Persona, loaded.persona.id))
    if row is not None:
        await db.refresh(row)


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
