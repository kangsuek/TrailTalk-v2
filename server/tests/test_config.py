import pytest
from pydantic import ValidationError

from app.config import SERVER_DIR, Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.auto_migrate is True
    assert settings.default_persona == "jenny"
    assert settings.timezone == "Asia/Seoul"
    assert settings.idle_timeout_s == 1800
    assert settings.database_url.endswith("server/data/trailtalk.db")
    assert settings.attachments_dir == SERVER_DIR / "data" / "attachments"


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    monkeypatch.setenv("AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("IDLE_TIMEOUT_S", "60")
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("x.db")
    assert settings.audio_dir == tmp_path / "audio"
    assert settings.idle_timeout_s == 60


def test_dotenv_is_read_and_empty_values_are_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("DEFAULT_PERSONA", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "")  # 셸의 빈 변수가 .env 값을 가리지 않는다
    env = tmp_path / ".env"
    env.write_text("DEFAULT_PERSONA=mina\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    settings = Settings(_env_file=env)
    assert settings.default_persona == "mina"
    assert settings.log_level == "DEBUG"


def test_path_settings_come_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIENT_DEFAULTS_PATH", str(tmp_path / "c.json"))
    monkeypatch.setenv("PERSONA_DIR", str(tmp_path / "personas"))
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("CLI_WORK_DIR", str(tmp_path / "cli"))
    settings = Settings(_env_file=None)
    assert settings.client_defaults_path == tmp_path / "c.json"
    assert settings.persona_dir == tmp_path / "personas"
    assert settings.web_dist_dir == tmp_path / "dist"
    assert settings.cli_work_dir == tmp_path / "cli"


def test_log_level_is_normalized_and_validated():
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError, match="알 수 없는 로그 수준"):
        Settings(_env_file=None, log_level="FOO")


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValidationError, match="알 수 없는 시간대"):
        Settings(_env_file=None, timezone="Mars/Olympus")
