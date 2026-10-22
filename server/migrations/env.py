"""Alembic 마이그레이션 환경 (비동기 SQLAlchemy).

URL 우선순위: 프로그램이 넘긴 sqlalchemy.url → app.config.Settings.database_url.
앱 시작 때(app.db.migrate) 호출되면 로그 설정을 건드리지 않는다.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.config import Settings
from app.db import models  # noqa: F401  모델을 metadata에 등록
from app.db.base import Base
from app.db.session import create_engine_for
from app.db.types import UTCDateTime

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def _render_item(type_, obj, autogen_context):
    # 사용자 정의 타입은 마이그레이션 파일에 표준 타입으로 남긴다(app 코드 import 없이 실행되도록)
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite ALTER 제약 대응
        compare_type=True,
        render_item=_render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _check_foreign_keys(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"마이그레이션 후 외래 키 위반: {violations[:5]}")


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
        # 같은 트랜잭션 안에서 검사해 위반이 있으면 마이그레이션이 롤백되게 한다
        _check_foreign_keys(connection)


async def run_migrations_online() -> None:
    # FK 검사를 끈 연결로 마이그레이션한다(batch 재생성 중 CASCADE 삭제 방지).
    # 외래 키 무결성은 _run_sync가 같은 트랜잭션 안에서 검사한다.
    engine = create_engine_for(database_url(), foreign_keys=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
