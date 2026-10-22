from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent


class Settings(BaseSettings):
    """서버 설정. 값은 환경 변수 또는 저장소 루트의 .env에서 읽는다.

    M0 항목만 있다. CLI·음성·검색·메일 항목은 쓰는 마일스톤에서 추가한다.
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

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"알 수 없는 로그 수준: {value}")
        return level

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"알 수 없는 시간대: {value}") from exc
        return value


settings = Settings()
