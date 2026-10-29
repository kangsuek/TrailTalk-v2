"""음성 합성 백엔드(Spec 5.2, 결정 D3: OpenAI TTS). 문장 하나를 MP3로 만든다.

기본 모델은 gpt-4o-mini-tts(말투 지시 적용), 대체 모델은 tts-1(말투 지시 없음)이다. 재시도·헤징·
대체 모델 전환은 app/voice/speech.py의 TtsService가 맡고, 이 백엔드는 모델 하나로 한 번 요청한다.
"""

from typing import Protocol

import httpx2
from pydantic import SecretStr

from app.config import Settings
from app.persona.schema import VoiceStyle
from app.voice import openai_http
from app.voice.text import has_speech, speech_text


class TtsBackend(Protocol):
    async def synthesize(self, text: str, voice: VoiceStyle, *, model: str | None = None) -> bytes:
        """MP3. 읽을 글자가 없으면 빈 bytes. model이 없으면 기본 모델."""
        ...


class OpenAiTts:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: SecretStr | None,
        base_url: str,
        model: str,
        timeout_s: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_s = timeout_s

    @classmethod
    def from_settings(cls, client: httpx2.AsyncClient, settings: Settings) -> "OpenAiTts":
        return cls(
            client,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.tts_model,
            # 둘째 문장부터의 시도당 제한. 첫 문장은 TtsService가 시각으로 취소한다
            timeout_s=settings.tts_sentence_timeout_s,
        )

    @staticmethod
    def _style(model: str, voice: VoiceStyle) -> dict[str, str]:
        # 말투 지시는 gpt-4o-mini-tts 계열만 받는다(tts-1·tts-1-hd는 받지 않음)
        return {"instructions": voice.instructions} if model.startswith("gpt-") else {}

    async def synthesize(self, text: str, voice: VoiceStyle, *, model: str | None = None) -> bytes:
        spoken = speech_text(text)
        if not has_speech(spoken):
            return b""
        use_model = model or self._model
        response = await openai_http.post(
            self._client,
            base_url=self._base_url,
            api_key=self._api_key,
            path="/audio/speech",
            timeout_s=self._timeout_s,
            error_prefix="tts",
            json={
                "model": use_model,
                "voice": voice.tts_voice,
                "input": spoken,
                "speed": voice.speaking_rate,
                "response_format": "mp3",
            }
            | self._style(use_model, voice),
        )
        if not response.content:
            raise openai_http.failed("tts")
        return response.content
