"""M1에서 더한 LLM·CLI 설정 키."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_llm_defaults():
    settings = Settings(_env_file=None)
    assert settings.claude_cli_path == "claude"
    assert settings.claude_code_oauth_token is None
    assert settings.cli_turn_timeout_s == 120
    assert settings.llm_chat_model == "sonnet"
    assert settings.internal_base_url == "http://127.0.0.1:8000"
    assert settings.cli_env_passthrough == ()


def test_llm_env_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI_PATH", "/opt/fake-claude")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-secret-token")
    monkeypatch.setenv("CLI_TURN_TIMEOUT_S", "30")
    monkeypatch.setenv("LLM_CHAT_MODEL", "haiku")
    monkeypatch.setenv("INTERNAL_BASE_URL", "http://127.0.0.1:8100/")
    monkeypatch.setenv("CLI_ENV_PASSTHROUGH", "FAKE_CLAUDE_*, HTTPS_PROXY")
    settings = Settings(_env_file=None)
    assert settings.claude_cli_path == "/opt/fake-claude"
    assert settings.claude_code_oauth_token.get_secret_value() == "sk-secret-token"
    assert settings.cli_turn_timeout_s == 30
    assert settings.llm_chat_model == "haiku"
    assert settings.internal_base_url == "http://127.0.0.1:8100"  # 끝의 /는 뗀다
    assert settings.cli_env_passthrough == ("FAKE_CLAUDE_*", "HTTPS_PROXY")


def test_oauth_token_is_not_shown_in_repr():
    settings = Settings(_env_file=None, claude_code_oauth_token="sk-secret-token")
    assert "sk-secret-token" not in repr(settings)
    assert "sk-secret-token" not in str(settings.model_dump())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_chat_model", "gpt"),
        ("cli_turn_timeout_s", 0),
        ("internal_base_url", "ftp://127.0.0.1"),
        ("claude_cli_path", ""),
    ],
)
def test_invalid_llm_settings_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
