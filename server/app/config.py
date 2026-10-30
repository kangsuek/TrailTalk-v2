from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent


class Settings(BaseSettings):
    """서버 설정. 값은 환경 변수 또는 저장소 루트의 .env에서 읽는다.

    M0 항목, M1의 LLM·CLI 항목, M3의 음성 항목이 있다. 검색·메일 항목은 쓰는 마일스톤에서 추가한다.
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
    # 일지 정리(추출) 단발 호출 모델과 한 번 호출의 최대 시간(초, app/jobs/extract.py)
    llm_extract_model: Literal["haiku", "sonnet", "opus"] = "haiku"
    extract_timeout_s: float = Field(default=60, gt=0)
    # 끝내기 API가 일지 정리를 기다리는 최대 시간(초). 넘으면 journal_status pending으로 먼저 답한다
    extract_wait_s: float = Field(default=45, ge=0)
    # 다음 세션 프롬프트의 기억 블록 예산(글자 수, app/persona/memory.py)
    memory_budget_chars: int = Field(default=1200, gt=0)
    # CLI가 도구 서버(/internal/mcp)를 부를 때 쓰는 이 서버의 주소(루프백)
    internal_base_url: str = "http://127.0.0.1:8000"
    # CLI 자식 프로세스에 넘길 환경 변수 이름(끝의 *는 접두사 일치). 쉼표로 구분한다
    cli_env_passthrough: Annotated[tuple[str, ...], NoDecode] = ()

    # 음성 인식·합성(OpenAI, Spec 5.2). 키가 없어도 서버는 시작하고
    # 음성 호출만 voice_unavailable이다
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    stt_model: str = "gpt-transcribe"
    stt_language: str = "ko"
    stt_timeout_s: float = Field(default=15, gt=0)
    stt_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    # 합성: 기본 모델은 말투 지시를 받는다. 대체 모델(tts-1)은 받지 않는다(Spec 5.2)
    tts_model: str = "gpt-4o-mini-tts"
    tts_fallback_model: str = "tts-1"
    # 첫 문장: 이 시간 안에 소리가 없으면 같은 요청을 한 번 더 보내고(헤징), 더 지나면
    # 대체 모델 요청을 더하며, 요청 시작(턴 시작)부터 tts_first_deadline_s가 지나면 글만 보낸다
    tts_first_hedge_s: float = Field(default=3, gt=0)
    tts_first_fallback_s: float = Field(default=5, gt=0)
    tts_first_deadline_s: float = Field(default=12, gt=0)
    # 둘째 문장부터: 한 번 시도의 제한 시간(시도 → 재시도 → 대체 모델 순)
    tts_sentence_timeout_s: float = Field(default=6, gt=0)
    # openai: 실제 API, fake: 가짜(app/voice/fake.py, run.sh --fake·E2E용, 과금 없음)
    voice_backend: Literal["openai", "fake"] = "openai"
    # 가짜 음성 인식이 돌려줄 문장(업로드가 b"FAKE_STT:"로 시작하면 그 뒤 글을 쓴다)
    fake_stt_text: str = "오늘 산책하면서 생각난 아이디어가 있어"
    # 업로드 오디오 변환(app/voice/audio.py). 없으면 변환이 필요한 형식만 voice_unavailable이다
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_s: float = Field(default=10, gt=0)

    # Claude 앱 MCP 연계(외부 MCP 앱, 별도 포트, docs/MCP). 공개 주소와 소유자 비밀번호가 둘 다
    # 있어야 외부 앱을 띄울 수 있다(app/mcp_external/config.py가 검증). 저장소에는 값을 두지 않는다
    mcp_public_url: str = ""
    mcp_owner_password: SecretStr | None = None
    mcp_port: int = Field(default=8400, ge=1, le=65535)
    # OAuth 리다이렉트 허용 목록(쉼표 구분). 비면 Claude 콜백 하나
    mcp_allowed_redirects: Annotated[tuple[str, ...], NoDecode] = ()
    # 동적 클라이언트 등록(DCR) 수 상한
    mcp_max_clients: int = Field(default=50, gt=0)
    # 도구 호출 기록(이름·시각·성공 여부·대상 id만, 내용은 남기지 않는다)
    mcp_call_log: Path = SERVER_DIR / "data" / "mcp-calls.jsonl"
    # 앱 세션 전문의 상대(Claude 앱) 화자 이름. 캐릭터 이름이 아니라 설정값이다(코드에 박지 않는다)
    app_speaker_name: str = Field(default="Claude", min_length=1, max_length=20)

    @field_validator("mcp_owner_password", mode="before")
    @classmethod
    def _blank_mcp_password_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mcp_allowed_redirects", mode="before")
    @classmethod
    def _split_redirects(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

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

    @model_validator(mode="after")
    def _tts_first_sentence_times_are_ordered(self) -> "Settings":
        if not self.tts_first_hedge_s < self.tts_first_fallback_s < self.tts_first_deadline_s:
            raise ValueError(
                "tts_first_hedge_s < tts_first_fallback_s < tts_first_deadline_s여야 합니다"
            )
        return self

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _blank_openai_key_is_none(cls, value: object) -> object:
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
