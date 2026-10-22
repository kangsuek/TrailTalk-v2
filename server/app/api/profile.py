"""프로필 API (client-contract 4.1)."""

import re
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.client_config import ClientConfig
from app.config import Settings
from app.db.models import ChatModel, UserProfile
from app.db.session import DbSession
from app.services.profile import get_or_create_profile, update_profile

router = APIRouter()

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _stripped(value: str) -> str:
    return value.strip()


def _one_line(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("한 줄이어야 합니다")
    return value


Nickname = Annotated[
    str, AfterValidator(_stripped), Field(min_length=1, max_length=20), AfterValidator(_one_line)
]
Interest = Annotated[str, AfterValidator(_stripped), Field(min_length=1, max_length=30)]
Voice = Annotated[str, AfterValidator(_stripped), Field(min_length=1, max_length=100)]


class ProfileResponse(BaseModel):
    nickname: str | None
    email: str | None
    mail_ready: bool  # 서버에 메일 보내기(SMTP) 설정이 있는지. M5 전까지 항상 false
    interests: list[str]
    persona_id: str  # 저장값이 없으면 서버 기본 페르소나
    voice: str | None
    speaking_rate: float | None
    ack_enabled: bool
    keep_audio: bool
    chat_model: ChatModel | None  # null이면 default_chat_model
    default_chat_model: ChatModel
    client: ClientConfig  # 읽기 전용


class ProfileUpdate(BaseModel):
    """보낸 필드만 바꾼다. 읽기 전용 필드(client 등)를 보내면 422다."""

    model_config = ConfigDict(extra="forbid")

    nickname: Nickname | None = None
    email: Annotated[str, AfterValidator(_stripped), Field(max_length=254)] | None = None
    interests: list[Interest] | None = None
    persona_id: str | None = None
    voice: Annotated[str, AfterValidator(_stripped), Field(min_length=1, max_length=100)] | None = (
        None
    )
    speaking_rate: Annotated[float, Field(ge=0.75, le=1.5)] | None = None
    ack_enabled: StrictBool | None = None
    keep_audio: StrictBool | None = None
    chat_model: ChatModel | None = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL.fullmatch(value):
            raise ValueError("이메일 주소 형식이 아닙니다")
        return value

    @field_validator("interests")
    @classmethod
    def _interests(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unique = list(dict.fromkeys(value))
        if len(unique) > 10:
            raise ValueError("관심사는 최대 10개입니다")
        return unique

    @model_validator(mode="after")
    def _required_fields_are_not_null(self) -> "ProfileUpdate":
        for name in ("interests", "ack_enabled", "keep_audio"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name}는 null일 수 없습니다")
        return self

    def changes(self) -> dict:
        """실제로 보낸 필드만. null을 보낸 선택 필드는 값을 지운다."""
        return {name: getattr(self, name) for name in self.model_fields_set}


def _response(request: Request, profile: UserProfile) -> ProfileResponse:
    settings: Settings = request.app.state.settings
    return ProfileResponse(
        nickname=profile.nickname,
        email=profile.email,
        mail_ready=False,
        interests=list(profile.interests or []),
        persona_id=profile.persona_id or settings.default_persona,
        voice=profile.voice,
        speaking_rate=profile.speaking_rate,
        ack_enabled=profile.ack_enabled,
        keep_audio=profile.keep_audio,
        chat_model=profile.chat_model,
        default_chat_model=ChatModel(settings.llm_chat_model),
        client=request.app.state.client_config,
    )


@router.get("/profile")
async def get_profile(request: Request, db: DbSession) -> ProfileResponse:
    return _response(request, await get_or_create_profile(db))


@router.put("/profile")
async def put_profile(request: Request, body: ProfileUpdate, db: DbSession) -> ProfileResponse:
    settings: Settings = request.app.state.settings
    profile = await update_profile(db, settings.persona_dir, body.changes())
    return _response(request, profile)
