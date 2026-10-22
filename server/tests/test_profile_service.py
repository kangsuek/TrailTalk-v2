"""프로필 서비스: 첫 조회 경합."""

from sqlalchemy import func, select

from app.db.models import UserProfile
from app.db.session import create_engine_for, create_session_factory
from app.services.profile import get_or_create_profile


async def test_get_or_create_survives_losing_the_insert_race(db_session, database_url):
    """다른 요청이 먼저 행을 만들었는데 이쪽 db.get은 아직 비어 있다고 본 경우(경합)."""
    other_engine = create_engine_for(database_url)
    try:
        async with create_session_factory(other_engine)() as other:
            other.add(UserProfile(id=1, interests=["먼저"]))
            await other.commit()
    finally:
        await other_engine.dispose()

    real_get = db_session.get
    calls = 0

    async def stale_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_get(*args, **kwargs)

    db_session.get = stale_get
    profile = await get_or_create_profile(db_session)
    assert profile.interests == ["먼저"]  # 만들기에 실패하면 먼저 만들어진 행을 돌려준다
    count = (await db_session.execute(select(func.count()).select_from(UserProfile))).scalar_one()
    assert count == 1
