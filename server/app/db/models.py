"""서버 DB 모델 (Spec 6절).

ID는 UUID 문자열, 시각은 UTC다. 열거값은 SQLite에서도 CHECK 제약으로 막는다.
M0에는 persona와 user_profile만 있고, 나머지 테이블은 쓰는 마일스톤에서 리비전으로 더한다.
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
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class ChatModel(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


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
    chat_model: Mapped[ChatModel | None] = mapped_column(_enum(ChatModel, "chat_model"))
    keep_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
