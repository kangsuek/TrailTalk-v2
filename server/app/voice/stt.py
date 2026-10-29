"""음성 인식(계획서 S3-01, 결정 D2: OpenAI 음성 인식 API)."""

from typing import Protocol

import httpx2
from pydantic import SecretStr

from app.config import Settings
from app.voice import openai_http
from app.voice.audio import AudioFile


class SttProvider(Protocol):
    async def transcribe(self, audio: AudioFile, *, prompt: str | None = None) -> str:
        """인식한 문장(앞뒤 공백 제거). 말이 없으면 빈 문자열."""
        ...


class OpenAiStt:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: SecretStr | None,
        base_url: str,
        model: str,
        language: str,
        timeout_s: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._language = language
        self._timeout_s = timeout_s

    @classmethod
    def from_settings(cls, client: httpx2.AsyncClient, settings: Settings) -> "OpenAiStt":
        return cls(
            client,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.stt_model,
            language=settings.stt_language,
            timeout_s=settings.stt_timeout_s,
        )

    async def transcribe(self, audio: AudioFile, *, prompt: str | None = None) -> str:
        # gpt-transcribe는 languages(목록)를, 예전 모델은 language 하나를 받는다
        data: dict[str, str | list[str]] = {"model": self._model, "response_format": "json"}
        if self._model.startswith("gpt-transcribe"):
            data["languages"] = [self._language]
        else:
            data["language"] = self._language
        if prompt:
            data["prompt"] = prompt
        response = await openai_http.post(
            self._client,
            base_url=self._base_url,
            api_key=self._api_key,
            path="/audio/transcriptions",
            timeout_s=self._timeout_s,
            error_prefix="stt",
            data=data,
            files={"file": (audio.filename, audio.data, audio.mime)},
        )
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise openai_http.failed("stt") from exc
        if not isinstance(text, str):
            raise openai_http.failed("stt")
        return text.strip()
