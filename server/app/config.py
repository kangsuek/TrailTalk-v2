from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent


class Settings(BaseSettings):
    """서버 설정. 값은 환경 변수 또는 저장소 루트의 .env에서 읽는다.

    M0 항목과 M1의 LLM·CLI 항목이 있다. 음성·검색·메일 항목은 쓰는 마일스톤에서 추가한다.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_DIR / ".env",
        extra="ignore",
        # 빈 값(KEY=)은 없는 것으로 본다. 셸의 빈 환경 변수가 .env 값을 가리지 않게 한다
        env_ignore_empty=True,
    )

    database_url: str = f"sqlite+aiosqlite:///{SERVER_DIR / 'data' / 'trailtalk.db'}"
    log_level: str = "INFO"
    # 앱 시작 때 Alembic 마이그레이션을 head까지 적용한다
    auto_migrate: bool = True
    # 무발화 종료 기준. 클라이언트 설정값 session.idle_timeout_minutes를 이 값으로 덮어쓴다
    idle_timeout_s: float = 1800
    # 무발화 감시가 도는 간격(초, app/jobs/idle.py)
    idle_check_interval_s: float = Field(default=60, gt=0)

    # 데이터 폴더. 검증용 서버는 모두 임시 경로로 바꿔 띄운다(CLAUDE.md)
    attachments_dir: Path = SERVER_DIR / "data" / "attachments"
    audio_dir: Path = SERVER_DIR / "data" / "audio"
    cli_work_dir: Path = SERVER_DIR / "data" / "cli-sessions"

    persona_dir: Path = SERVER_DIR / "personas"
    default_persona: str = "jenny"
    timezone: str = "Asia/Seoul"
    web_dist_dir: Path = REPO_DIR / "web" / "dist"
    # 클라이언트 설정값 기본값(app/client_config.py, 규약 7절)
    client_defaults_path: Path = REPO_DIR / "shared" / "client-defaults.json"

    # Claude CLI(Spec 5.8). 테스트·E2E는 claude_cli_path를 가짜 실행 파일로 바꾼다
    claude_cli_path: str = Field(default="claude", min_length=1)
    claude_code_oauth_token: SecretStr | None = None
    # 답변 하나를 기다리는 최대 시간(초). 넘으면 턴을 끊는다
    cli_turn_timeout_s: float = Field(default=120, gt=0)
    # 쓰지 않는 CLI 프로세스를 닫는 시간(초). 세션 자체의 무발화 종료(idle_timeout_s)와 별개다
    cli_idle_timeout_s: float = Field(default=600, gt=0)
    # 프로필 chat_model이 비었을 때 쓰는 대화 모델(Spec 5.8)
    llm_chat_model: Literal["haiku", "sonnet", "opus"] = "sonnet"
    # 다음 세션 프롬프트의 기억 블록 예산(글자 수, app/persona/memory.py)
    memory_budget_chars: int = Field(default=1200, gt=0)
    # CLI가 도구 서버(/internal/mcp)를 부를 때 쓰는 이 서버의 주소(루프백)
    internal_base_url: str = "http://127.0.0.1:8000"
    # CLI 자식 프로세스에 넘길 환경 변수 이름(끝의 *는 접두사 일치). 쉼표로 구분한다
    cli_env_passthrough: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"알 수 없는 로그 수준: {value}")
        return level

    @field_validator("internal_base_url")
    @classmethod
    def _valid_internal_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"internal_base_url은 http(s) 주소여야 합니다: {value}")
        # CLI가 도구 서버 토큰을 실어 부르는 주소이므로 루프백만 허용한다(밖으로 새지 않게)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(f"internal_base_url은 루프백 주소여야 합니다: {value}")
        return value.rstrip("/")

    @field_validator("claude_code_oauth_token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cli_env_passthrough", mode="before")
    @classmethod
    def _split_names(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(name.strip() for name in value.split(",") if name.strip())
        return value

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"알 수 없는 시간대: {value}") from exc
        return value


settings = Settings()
