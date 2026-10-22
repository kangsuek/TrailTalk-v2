import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.migrate import upgrade_to_head
from app.db.session import create_engine_for, create_session_factory
from app.main import create_app


@pytest.fixture
def make_settings(tmp_path):
    def _make(**overrides) -> Settings:
        values = {
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            "web_dist_dir": tmp_path / "no-dist",
            "attachments_dir": tmp_path / "attachments",
            "audio_dir": tmp_path / "audio",
            "cli_work_dir": tmp_path / "cli-sessions",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def app(make_settings):
    return create_app(make_settings())


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'models.db'}"


@pytest.fixture
async def db_session(database_url):
    """마이그레이션을 적용한 임시 SQLite의 세션."""
    await upgrade_to_head(database_url)
    engine = create_engine_for(database_url)
    try:
        async with create_session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()
