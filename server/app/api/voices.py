"""보이스 목록과 미리 듣기(client-contract 4.2)."""

import base64
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.db.session import DbSession
from app.errors import AppError
from app.services.profile import profile_with_persona
from app.services.voice import voice_style
from app.voice.text import OPENAI_VOICES, SPEAKING_RATE_MAX, SPEAKING_RATE_MIN

router = APIRouter(tags=["voices"])


class VoicesOut(BaseModel):
    voices: list[str]
    default_voice: str  # 프로필이 비었을 때 쓰는 캐릭터(페르소나 YAML)의 보이스
    default_rate: float
    min_rate: float
    max_rate: float


def _clamp_rate(rate: float) -> float:
    return min(max(rate, SPEAKING_RATE_MIN), SPEAKING_RATE_MAX)


@router.get("/voices")
async def list_voices(request: Request, db: DbSession) -> VoicesOut:
    _, loaded = await profile_with_persona(db, request.app.state.settings)
    await db.commit()
    return VoicesOut(
        voices=list(OPENAI_VOICES),
        default_voice=loaded.persona.voice.tts_voice,
        default_rate=_clamp_rate(loaded.persona.voice.speaking_rate),
        min_rate=SPEAKING_RATE_MIN,
        max_rate=SPEAKING_RATE_MAX,
    )


@router.get(
    "/voices/{voice}/sample",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}, "description": "미리 듣기 MP3"}},
)
async def voice_sample(
    voice: str,
    request: Request,
    db: DbSession,
    rate: Annotated[float | None, Query(ge=SPEAKING_RATE_MIN, le=SPEAKING_RATE_MAX)] = None,
) -> Response:
    """고정 문장을 이 보이스·속도로 합성한 MP3. 보이스·속도별로 한 번만 합성한다."""
    if voice not in OPENAI_VOICES:
        raise AppError("validation_error", "지원하지 않는 보이스입니다.", 422)
    app = request.app
    _, loaded = await profile_with_persona(db, app.state.settings)
    await db.commit()
    base = loaded.persona.voice
    style = voice_style(loaded.persona, None).model_copy(
        update={"tts_voice": voice, "speaking_rate": rate or _clamp_rate(base.speaking_rate)}
    )
    made = await app.state.tts.cached(base.sample, style)
    if made.audio is None:
        raise AppError("voice_unavailable", "음성 서비스를 쓸 수 없습니다.", 503)
    return Response(content=base64.b64decode(made.audio), media_type="audio/mpeg")
