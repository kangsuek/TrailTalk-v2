import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.migrate import alembic_config, upgrade_to_head
from app.db.session import create_engine_for
from app.main import create_app

TABLES = {"persona", "user_profile"}


async def table_names(url: str) -> set[str]:
    engine = create_engine_for(url)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    finally:
        await engine.dispose()
    return names - {"alembic_version"}


async def test_migrations_match_models(database_url):
    await upgrade_to_head(database_url)
    engine = create_engine_for(database_url)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync: compare_metadata(
                MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata
            )
        )
    await engine.dispose()
    assert diff == []
    assert await table_names(database_url) == TABLES


async def test_upgrade_is_idempotent_and_downgrade_removes_tables(database_url):
    import asyncio

    await upgrade_to_head(database_url)
    await upgrade_to_head(database_url)  # 이미 head면 아무 일도 하지 않는다
    await asyncio.to_thread(command.downgrade, alembic_config(database_url), "base")
    assert await table_names(database_url) == set()


async def test_app_startup_migrates_unless_disabled(make_settings, tmp_path):
    on_url = f"sqlite+aiosqlite:///{tmp_path / 'on.db'}"
    off_url = f"sqlite+aiosqlite:///{tmp_path / 'off.db'}"
    with TestClient(create_app(make_settings(database_url=on_url))):
        pass
    with TestClient(create_app(make_settings(database_url=off_url, auto_migrate=False))):
        pass
    assert await table_names(on_url) == TABLES
    assert await table_names(off_url) == set()


async def test_enum_check_constraints_match_models(database_url):
    """열거값(StrEnum)을 바꾸고 마이그레이션을 빠뜨리면 실패한다(autogenerate는 못 잡는다)."""
    import re

    from sqlalchemy import Enum

    await upgrade_to_head(database_url)
    engine = create_engine_for(database_url)
    try:
        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql("SELECT name, sql FROM sqlite_master")).all()
    finally:
        await engine.dispose()
    schema = {name: sql for name, sql in rows if sql}
    checked = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, Enum):
                match = re.search(rf"CHECK \({column.name} IN \(([^)]*)\)\)", schema[table.name])
                assert match, f"{table.name}.{column.name} CHECK 제약 없음"
                in_db = set(re.findall(r"'([^']*)'", match.group(1)))
                assert in_db == set(column.type.enums), f"{table.name}.{column.name}"
                checked.add(f"{table.name}.{column.name}")
    assert "user_profile.chat_model" in checked


async def test_batch_recreate_keeps_child_rows(database_url, tmp_path):
    """SQLite batch 재생성 중 DROP TABLE이 SET NULL/CASCADE로 자식 행을 바꾸지 않는지.

    마이그레이션 폴더를 복사해 부모 테이블을 다시 만드는 리비전을 덧붙이고, 실제 env.py 경로
    (command.upgrade)로 적용한다. env.py가 FK 검사를 켠 연결을 쓰면 persona_id가 null이 된다.
    """
    import asyncio
    import shutil

    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.config import SERVER_DIR

    await upgrade_to_head(database_url)
    data_engine = create_engine_for(database_url)
    try:
        async with data_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO persona (id, yaml_path, version, updated_at) "
                    "VALUES ('jenny', 'jenny.yaml', 'abc', '2026-10-22 00:00:00.000000')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO user_profile (id, interests, persona_id, keep_audio, updated_at) "
                    "VALUES (1, '[]', 'jenny', 0, '2026-10-22 00:00:00.000000')"
                )
            )
    finally:
        await data_engine.dispose()

    head = ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()
    scripts = tmp_path / "migrations"
    shutil.copytree(
        SERVER_DIR / "migrations", scripts, ignore=shutil.ignore_patterns("__pycache__")
    )
    (scripts / "versions" / "9999_recreate.py").write_text(
        f"""import sqlalchemy as sa
from alembic import op

revision = "9999"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("persona", recreate="always") as batch:
        batch.add_column(sa.Column("extra", sa.String(10)))


def downgrade():
    pass
""",
        encoding="utf-8",
    )
    config = alembic_config(database_url)
    config.set_main_option("script_location", str(scripts))
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_engine_for(database_url)
    try:
        async with engine.connect() as conn:
            persona_id = (
                await conn.execute(text("SELECT persona_id FROM user_profile"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert persona_id == "jenny"


async def _insert_profile(session, profile_id: int, chat_model: str | None = None) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            "INSERT INTO user_profile (id, interests, keep_audio, chat_model, updated_at) "
            "VALUES (:id, '[]', 0, :m, '2026-10-22 00:00:00.000000')"
        ),
        {"id": profile_id, "m": chat_model},
    )


async def test_user_profile_allows_only_one_row(db_session):
    from sqlalchemy.exc import IntegrityError

    await _insert_profile(db_session, 1)
    with pytest.raises(IntegrityError, match="ck_user_profile_single_row"):
        await _insert_profile(db_session, 2)


@pytest.mark.parametrize("chat_model", ["haiku", "sonnet", "opus", None])
async def test_chat_model_accepts_enum_values_and_null(db_session, chat_model):
    await _insert_profile(db_session, 1, chat_model)


async def test_chat_model_rejects_unknown_value(db_session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="ck_user_profile_chat_model"):
        await _insert_profile(db_session, 1, "gpt")
