"""음성 대화 도우미(M3): 보이스 고르기, 인사말·마무리 음성, 음성 턴 지연 기록.

합성 실패는 대화를 멈추지 않는다. 합성한 소리가 없으면 클라이언트가 글(speech_text)을 기기
TTS로 읽는다(Spec 5.2).
"""

import logging
import time
from dataclasses import dataclass, field

import anyio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionMode, TurnLatency, TurnTts, UserProfile
from app.persona.schema import Persona, VoiceStyle

logger = logging.getLogger("trailtalk.voice")


def voice_style(persona: Persona, profile: UserProfile | None) -> VoiceStyle:
    """프로필의 보이스·속도가 있으면 그것으로, 없으면 페르소나(YAML) 기본으로 합성한다."""
    base = persona.voice
    if profile is None:
        return base
    return base.model_copy(
        update={
            "tts_voice": profile.voice or base.tts_voice,
            "speaking_rate": profile.speaking_rate or base.speaking_rate,
        }
    )


def is_voice(mode: SessionMode) -> bool:
    return mode is SessionMode.VOICE


async def speak(app: FastAPI, text: str, voice: VoiceStyle) -> str | None:
    """인사말·마무리 멘트 같은 한 문장 소리(MP3 base64). 실패하면 None(세션은 계속된다)."""
    try:
        return (await app.state.tts.follow(text, voice)).audio
    except Exception:
        logger.exception("음성 합성 중 예외")
        return None


@dataclass
class VoiceTurn:
    """음성 업로드로 시작한 턴의 인식 결과와 서버 단계 시각(요청 처리 시작 기준 ms)."""

    started: float  # time.monotonic()
    transcript: str
    upload_ms: int
    stt_ms: int
    audio_bytes: int


@dataclass
class LatencyTracker:
    """한 턴의 서버 단계 시간을 모아 턴이 끝나면 한 번에 쓴다(Spec 5.1, 규약 2.15)."""

    started: float
    upload_ms: int | None = None
    stt_ms: int | None = None
    audio_bytes: int | None = None
    cli_age_ms: int | None = None
    first_token_ms: int | None = None
    first_queued_ms: int | None = None
    first_synth_ms: int | None = None
    first_sentence_ms: int | None = None
    searched: bool = False
    tts: list[tuple[int, str | None, bool]] = field(default_factory=list)

    def ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def mark(self, name: str) -> None:
        """name 단계를 처음 지난 시각만 남긴다."""
        if getattr(self, name) is None:
            setattr(self, name, self.ms())

    async def save(
        self, db: AsyncSession, session_id: str, turn_id: str, *, reply_chars: int
    ) -> None:
        """취소(연결 끊김)에서 보호해 쓴다. 실패해도 대화는 멈추지 않는다."""
        waited = None
        if self.first_queued_ms is not None and self.first_synth_ms is not None:
            waited = max(self.first_synth_ms - self.first_queued_ms, 0)
        try:
            with anyio.CancelScope(shield=True):
                db.add(
                    TurnLatency(
                        turn_id=turn_id,
                        session_id=session_id,
                        upload_ms=self.upload_ms,
                        stt_ms=self.stt_ms,
                        audio_bytes=self.audio_bytes,
                        cli_age_ms=self.cli_age_ms,
                        first_token_ms=self.first_token_ms,
                        first_queued_ms=self.first_queued_ms,
                        first_synth_ms=self.first_synth_ms,
                        synth_wait_ms=waited,
                        first_sentence_ms=self.first_sentence_ms,
                        done_ms=self.ms(),
                        reply_chars=reply_chars,
                        searched=self.searched,
                    )
                )
                for index, model, fallback in self.tts:
                    db.add(
                        TurnTts(
                            turn_id=turn_id,
                            session_id=session_id,
                            sentence_index=index,
                            model=model,
                            fallback=fallback,
                        )
                    )
                await db.commit()
        except Exception:
            logger.exception("지연 기록 저장 실패(turn=%s)", turn_id)
            with anyio.CancelScope(shield=True):
                await db.rollback()
