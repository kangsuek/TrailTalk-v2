"""서버 DB 모델 (Spec 6절).

ID는 UUID 문자열, 시각은 UTC다. 열거값은 SQLite에서도 CHECK 제약으로 막는다.
persona·user_profile(M0), conversation_session·turn·note(M1), turn_latency·turn_tts(M3).
나머지 테이블(attachment, briefing 등)은 쓰는 마일스톤에서 리비전으로 더한다.
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, new_id, utcnow

NOTE_MAX_CHARS = 500  # 노트 내용 최대 글자 수(저장 도구가 쓴다)


class ChatModel(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class SessionMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    CLAUDE_APP = "claude_app"  # Claude 앱 MCP 연계가 저장한 일지·앱 메모(MCP/design.md 3)


class AppKind(StrEnum):
    """claude_app 세션의 종류. 일반 앱 일지와 날짜별 앱 메모를 구분한다(제목 규칙을 쓰지 않는다)."""

    JOURNAL = "journal"
    MEMO = "memo"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class ExtractStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class TurnRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class NoteKind(StrEnum):
    IDEA = "idea"
    TODO = "todo"
    MEMO = "memo"


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda members: [m.value for m in members],
    )


class Persona(Base):
    __tablename__ = "persona"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    yaml_path: Mapped[str] = mapped_column(String(500))
    version: Mapped[str] = mapped_column(String(64))  # YAML 내용 해시
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UserProfile(Base):
    """본인용 단일 행(id=1)."""

    __tablename__ = "user_profile"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(254))  # 대화 내용을 보낼 본인 주소
    interests: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("persona.id", ondelete="SET NULL"))
    voice: Mapped[str | None] = mapped_column(String(100))  # null이면 페르소나 기본
    speaking_rate: Mapped[float | None] = mapped_column(Float)  # null이면 페르소나 기본
    ack_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    chat_model: Mapped[ChatModel | None] = mapped_column(_enum(ChatModel, "chat_model"))
    keep_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ConversationSession(Base):
    """대화 한 번. 추출 결과 열(title~checks, extract_status)은 M2에서 채운다."""

    __tablename__ = "conversation_session"
    __table_args__ = (
        # 앱 일지는 같은 날 같은 제목이 하나, 앱 메모는 같은 날 하나(병렬 호출이 둘을 만들지 못하게)
        Index(
            "uq_app_journal_day_title",
            "app_day",
            "title",
            unique=True,
            sqlite_where=text("app_kind = 'journal'"),
        ),
        Index(
            "uq_app_memo_day",
            "app_day",
            unique=True,
            sqlite_where=text("app_kind = 'memo'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode: Mapped[SessionMode] = mapped_column(_enum(SessionMode, "session_mode"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[SessionStatus] = mapped_column(
        _enum(SessionStatus, "session_status"), default=SessionStatus.ACTIVE
    )
    title: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    summary_cites: Mapped[list | None] = mapped_column(JSON)
    citations: Mapped[list | None] = mapped_column(JSON)
    checks: Mapped[list | None] = mapped_column(JSON)
    extract_status: Mapped[ExtractStatus | None] = mapped_column(
        _enum(ExtractStatus, "extract_status")
    )
    title_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    reopened_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("persona.id", ondelete="SET NULL"))
    system_prompt: Mapped[str | None] = mapped_column(Text)  # 시작 때 고정
    cli_session_id: Mapped[str | None] = mapped_column(String(100))
    # 일지 정리에 마지막으로 성공했을 때 전문의 마지막 턴 seq. 다시 연 대화를 다시 정리할 때 노트는
    # 이 뒤에서만 뽑는다(app/jobs/extract.py). 정리한 적이 없으면 null
    extracted_until_seq: Mapped[int | None] = mapped_column(Integer)
    # claude_app 세션만 값이 있다. app_day는 서버 시간대의 현지 날짜(저장 시각 기준)
    app_kind: Mapped[AppKind | None] = mapped_column(_enum(AppKind, "app_kind"))
    app_day: Mapped[date | None] = mapped_column(Date)


class Turn(Base):
    """대화의 한 발화. 오가는 즉시 쓴다(FR-12)."""

    __tablename__ = "turn"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="session_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_session.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[TurnRole] = mapped_column(_enum(TurnRole, "turn_role"))
    text: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str | None] = mapped_column(String(500))
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    greeting: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sources: Mapped[list | None] = mapped_column(JSON)  # 출처
    merged_from: Mapped[str | None] = mapped_column(ForeignKey("turn.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Note(Base):
    """대화 중 저장한 아이디어·할 일·메모."""

    __tablename__ = "note"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_session.id", ondelete="CASCADE")
    )
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turn.id", ondelete="SET NULL"))
    kind: Mapped[NoteKind] = mapped_column(_enum(NoteKind, "note_kind"))
    content: Mapped[str] = mapped_column(Text)
    cites: Mapped[list | None] = mapped_column(JSON)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TurnLatency(Base):
    """음성 턴 하나의 지연 기록(Spec 5.1, 규약 2.15). 서버 단계 값은 턴을 처리하며 쓰고,
    클라이언트 보고(`speech_to_request_ms` 등)는 `POST …/latency`가 덮어쓴다.

    turn_id는 답변 턴(`turn` 이벤트의 ID)이다. 첫 문장 전에 끊겨 답변 행이 없어도 기록은 남으므로
    turn 테이블 외래 키를 걸지 않고, 세션을 지우면 함께 지운다."""

    __tablename__ = "turn_latency"

    turn_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_session.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # 서버가 잰 단계(ms). 요청 처리를 시작한 때가 기준이다
    upload_ms: Mapped[int | None] = mapped_column(Integer)
    stt_ms: Mapped[int | None] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    first_queued_ms: Mapped[int | None] = mapped_column(Integer)
    first_synth_ms: Mapped[int | None] = mapped_column(Integer)
    synth_wait_ms: Mapped[int | None] = mapped_column(Integer)
    first_sentence_ms: Mapped[int | None] = mapped_column(Integer)
    done_ms: Mapped[int | None] = mapped_column(Integer)
    audio_bytes: Mapped[int | None] = mapped_column(Integer)
    cli_age_ms: Mapped[int | None] = mapped_column(Integer)  # CLI 프로세스를 띄운 지 얼마나 됐는지
    reply_chars: Mapped[int | None] = mapped_column(Integer)
    searched: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 클라이언트 보고
    speech_to_request_ms: Mapped[int | None] = mapped_column(Integer)
    request_to_playback_ms: Mapped[int | None] = mapped_column(Integer)
    first_sound_notice: Mapped[bool | None] = mapped_column(Boolean)
    ack_ms: Mapped[int | None] = mapped_column(Integer)


class TurnTts(Base):
    """답변 문장마다 쓴 합성 모델과 폴백 여부(Spec 5.2). 폴백 비율 집계에 쓴다."""

    __tablename__ = "turn_tts"
    __table_args__ = (UniqueConstraint("turn_id", "sentence_index", name="turn_sentence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_session.id", ondelete="CASCADE"), index=True
    )
    sentence_index: Mapped[int] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(100))  # 소리를 만든 모델, 소리 없으면 null
    fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class OAuthClient(Base):
    """DCR로 등록된 외부 MCP 클라이언트. info는 OAuthClientInformationFull의 JSON."""

    __tablename__ = "oauth_client"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    info: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OAuthPending(Base):
    """/authorize를 받았지만 로그인을 마치지 않은 요청. id가 로그인 폼의 CSRF 토큰 역할을 한다."""

    __tablename__ = "oauth_pending"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64))
    params: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class OAuthCode(Base):
    """인가 코드. 원문은 저장하지 않고 SHA-256만 둔다. 한 번 쓰면 지운다."""

    __tablename__ = "oauth_code"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class OAuthToken(Base):
    """액세스·리프레시 토큰(SHA-256만 저장). family_id가 같은 쌍은 함께 회전·폐기한다."""

    __tablename__ = "oauth_token"
    __table_args__ = (Index("ix_oauth_token_family_id", "family_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # access | refresh
    family_id: Mapped[str] = mapped_column(String(32))
    client_id: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[str] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(String(300))
    expires_at: Mapped[float] = mapped_column(Float)
