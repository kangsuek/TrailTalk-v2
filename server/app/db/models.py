"""서버 DB 모델 (Spec 6절).

ID는 UUID 문자열, 시각은 UTC다. 열거값은 SQLite에서도 CHECK 제약으로 막는다.
persona·user_profile(M0), conversation_session·turn·note(M1). 나머지 테이블(attachment,
turn_latency, briefing 등)은 쓰는 마일스톤에서 리비전으로 더한다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, new_id, utcnow


class ChatModel(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class SessionMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"


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
