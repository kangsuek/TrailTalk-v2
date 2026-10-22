import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbSession
from app.main import create_app


@pytest.fixture
def db_client(make_settings):
    app = create_app(make_settings())
    router = APIRouter(prefix="/test")

    @router.post("/setup")
    async def setup(db: DbSession):
        await db.execute(text("CREATE TABLE IF NOT EXISTS item (name TEXT)"))
        await db.commit()

    @router.post("/insert-then-fail")
    async def insert_then_fail(db: DbSession):
        await db.execute(text("INSERT INTO item (name) VALUES ('rolled-back')"))
        raise RuntimeError("실패")

    @router.get("/count")
    async def count(db: DbSession):
        return {"count": (await db.execute(text("SELECT COUNT(*) FROM item"))).scalar_one()}

    @router.get("/foreign-keys")
    async def foreign_keys(db: DbSession):
        return {"value": (await db.execute(text("PRAGMA foreign_keys"))).scalar_one()}

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_uncommitted_changes_are_rolled_back_on_error(db_client, monkeypatch):
    calls = []
    original = AsyncSession.rollback

    async def spy(self):
        calls.append(self)
        await original(self)

    monkeypatch.setattr(AsyncSession, "rollback", spy)
    db_client.post("/test/setup")
    assert db_client.post("/test/insert-then-fail").status_code == 500
    assert len(calls) == 1  # get_db가 명시적으로 rollback했는지
    assert db_client.get("/test/count").json() == {"count": 0}


def test_sqlite_foreign_keys_enabled(db_client):
    assert db_client.get("/test/foreign-keys").json() == {"value": 1}


def test_db_file_parent_directory_is_created(make_settings, tmp_path):
    db_path = tmp_path / "nested" / "dir" / "app.db"
    app = create_app(make_settings(database_url=f"sqlite+aiosqlite:///{db_path}"))
    with TestClient(app) as client:
        assert client.get("/api/health").json()["db"] == "ok"
    assert db_path.exists()
