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


FAKE_TOKEN = "sk-ant-oat01-fake-token-for-tests"


@pytest.fixture
def fake_cli(tmp_path, make_settings, monkeypatch):
    """녹화를 재생하는 가짜 Claude CLI(tests/fakes/fake_claude.py)를 쓰는 설정."""
    import sys
    from pathlib import Path

    from pydantic import SecretStr

    script = Path(__file__).parent / "fakes" / "fake_claude.py"
    wrapper = tmp_path / "fake-claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    args_log = tmp_path / "fake-args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS_LOG", str(args_log))
    monkeypatch.delenv("FAKE_CLAUDE_FIXTURE", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_DELAY", raising=False)

    class FakeCli:
        settings = make_settings(
            claude_cli_path=str(wrapper),
            claude_code_oauth_token=SecretStr(FAKE_TOKEN),
            cli_work_dir=tmp_path / "cli-sessions",
            cli_turn_timeout_s=10,
            cli_env_passthrough=("FAKE_CLAUDE_*",),
        )
        log = args_log

        @staticmethod
        def records() -> list[dict]:
            import json

            if not args_log.exists():
                return []
            return [json.loads(line) for line in args_log.read_text().splitlines()]

    return FakeCli
