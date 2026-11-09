"""빈 DB에서 두 세션이 동시에 처음 시작될 때 persona 시드가 겹쳐도 실패하지 않는다(M5 이월, M6)."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Persona
from app.db.session import create_session_factory
from app.persona.loader import load_persona
from app.services import profile as profile_service

PERSONA_DIR = Path(__file__).resolve().parents[1] / "personas"


async def test_upsert_survives_a_row_inserted_after_our_read(db_session: AsyncSession, monkeypatch):
    """읽을 때는 없었는데 커밋 전에 다른 세션이 먼저 넣은 경우(경합의 결과)를 그대로 만든다."""
    loaded = load_persona(PERSONA_DIR, "jenny")
    other = create_session_factory(db_session.bind)()
    try:
        await profile_service._upsert_persona_row(other, loaded)
        await other.commit()  # 다른 세션이 먼저 시드를 넣었다
    finally:
        await other.close()

    real_get = db_session.get

    async def stale_get(entity, ident, *args, **kwargs):
        if entity is Persona:
            return None  # 이 세션이 읽을 때는 아직 없었다
        return await real_get(entity, ident, *args, **kwargs)

    monkeypatch.setattr(db_session, "get", stale_get)
    await profile_service._upsert_persona_row(db_session, loaded)
    await db_session.commit()  # 예전에는 여기서 UNIQUE constraint failed: persona.id

    rows = (await db_session.scalars(select(Persona))).all()
    assert [row.id for row in rows] == ["jenny"]


@pytest.mark.parametrize("workers", [8])
async def test_many_first_sessions_at_once_all_succeed(db_session: AsyncSession, workers):
    factory = create_session_factory(db_session.bind)
    settings_like = type("S", (), {"persona_dir": PERSONA_DIR, "default_persona": "jenny"})()

    async def first_session():
        async with factory() as db:
            await profile_service.profile_with_persona(db, settings_like)
            await db.commit()

    await asyncio.gather(*(first_session() for _ in range(workers)))
    rows = (await db_session.scalars(select(Persona))).all()
    assert [row.id for row in rows] == ["jenny"]


async def test_upsert_still_refreshes_an_existing_row(db_session: AsyncSession):
    loaded = load_persona(PERSONA_DIR, "jenny")
    await profile_service._upsert_persona_row(db_session, loaded)
    await db_session.commit()
    row = await db_session.get(Persona, "jenny")
    row.version = "old"
    await db_session.commit()
    before = row.updated_at
    await profile_service._upsert_persona_row(db_session, loaded)
    await db_session.commit()
    await db_session.refresh(row)
    assert row.version == loaded.version
    assert row.updated_at >= before  # 갱신 시각도 함께 바뀐다
