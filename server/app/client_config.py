"""클라이언트 설정값(VAD·세션·오디오·턴). /api/profile이 내려준다(규약 7절).

기본값은 shared/client-defaults.json에서 읽는다.
웹은 프로필을 받기 전에 같은 파일을 대체값으로 쓴다.
"""

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import Settings

Probability = Annotated[float, Field(ge=0, le=1)]
PositiveMs = Annotated[int, Field(gt=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VadConfig(_Strict):
    """Silero VAD 확률 임계값과 발화 길이. 재생 중(setVadMode playback)에는 playback_* 값을 쓴다."""

    speech_threshold: Probability
    silence_threshold: Probability
    playback_speech_threshold: Probability
    playback_silence_threshold: Probability
    end_of_speech_silence_ms: PositiveMs
    min_speech_ms: PositiveMs

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.silence_threshold < self.speech_threshold:
            raise ValueError("silence_threshold는 speech_threshold보다 작아야 합니다")
        if not self.playback_silence_threshold < self.playback_speech_threshold:
            raise ValueError(
                "playback_silence_threshold는 playback_speech_threshold보다 작아야 합니다"
            )
        if self.playback_speech_threshold < self.speech_threshold:
            raise ValueError("재생 중 임계값은 평상시보다 낮을 수 없습니다")
        if self.playback_silence_threshold < self.silence_threshold:
            raise ValueError("재생 중 무음 임계값은 평상시보다 낮을 수 없습니다")
        return self


class ClientSessionConfig(_Strict):
    # 듣기·쉬기에서 이 시간 동안 말이 없으면 대화를 끝낸다. 서버 무발화 기준(idle_timeout_s)과 같다
    idle_timeout_minutes: Annotated[float, Field(gt=0)]


class UploadAudioConfig(_Strict):
    codec: Literal["opus"]
    sample_rate_hz: Literal[16000]
    channels: Literal[1]


class ResponseAudioConfig(_Strict):
    codec: Literal["mp3"]


class AudioConfig(_Strict):
    upload: UploadAudioConfig
    response: ResponseAudioConfig


class TurnConfig(_Strict):
    """맞장구(규약 6.4)와 쪼개진 발화 병합(2.8) 기준."""

    ack_delay_ms: PositiveMs
    ack_min_speech_ms: PositiveMs
    ack_overlap_max_ms: PositiveMs
    merge_min_speech_ms: PositiveMs


class ClientConfig(_Strict):
    vad: VadConfig
    session: ClientSessionConfig
    audio: AudioConfig
    turn: TurnConfig


def load_client_config(settings: Settings) -> ClientConfig:
    """기본값 파일을 읽어 검증한다. 무발화 시간은 서버 설정을 따른다. 파일이 없거나 틀리면 예외."""
    data = json.loads(settings.client_defaults_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("session"), dict):
        data["session"]["idle_timeout_minutes"] = settings.idle_timeout_s / 60  # 함께 검증한다
    return ClientConfig.model_validate(data)
