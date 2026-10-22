"""앱 시작 때 Alembic 마이그레이션을 head까지 적용한다."""

import asyncio
import logging

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext

from app.config import SERVER_DIR
from app.db.session import create_engine_for

logger = logging.getLogger("trailtalk.db")


def alembic_config(database_url: str) -> Config:
    config = Config(str(SERVER_DIR / "alembic.ini"))
    # ConfigParser 보간 문자(%)가 경로·URL에 있어도 깨지지 않게 한다
    config.set_main_option("script_location", str(SERVER_DIR / "migrations").replace("%", "%%"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


async def current_revision(database_url: str) -> str | None:
    engine = create_engine_for(database_url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_revision()
            )
    finally:
        await engine.dispose()


async def upgrade_to_head(database_url: str) -> None:
    before = await current_revision(database_url)
    # env.py가 asyncio.run을 쓰므로 실행 중인 이벤트 루프 밖(별도 스레드)에서 돌린다
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")
    after = await current_revision(database_url)
    if before == after:
        logger.info("DB 스키마 최신 상태(%s)", after)
    else:
        logger.info("DB 마이그레이션 적용: %s → %s", before or "없음", after)
