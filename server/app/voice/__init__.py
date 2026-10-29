"""음성 인식·합성(M3). 서버 시작 때 설정에 맞는 백엔드를 만들어 app.state에 둔다."""

import httpx2

from app.config import Settings
from app.voice.fake import FakeStt, FakeTts
from app.voice.speech import TtsService
from app.voice.stt import OpenAiStt, SttProvider
from app.voice.tts import OpenAiTts, TtsBackend


def build_voice(
    settings: Settings, client: httpx2.AsyncClient
) -> tuple[SttProvider, TtsBackend, TtsService]:
    """(음성 인식, 합성 백엔드, 합성 서비스). VOICE_BACKEND=fake면 과금 없는 가짜다."""
    stt: SttProvider
    backend: TtsBackend
    if settings.voice_backend == "fake":
        stt, backend = FakeStt(settings.fake_stt_text), FakeTts()
    else:
        stt, backend = (
            OpenAiStt.from_settings(client, settings),
            OpenAiTts.from_settings(client, settings),
        )
    service = TtsService(
        backend,
        primary_model=settings.tts_model,
        fallback_model=settings.tts_fallback_model,
        first_hedge_s=settings.tts_first_hedge_s,
        first_fallback_s=settings.tts_first_fallback_s,
        sentence_timeout_s=settings.tts_sentence_timeout_s,
    )
    return stt, backend, service
