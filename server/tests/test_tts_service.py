"""합성 서비스(헤징·재시도·대체 모델, Spec 5.2)와 음성 설정 시험. 시간은 작게 줄여 시험한다."""

import asyncio
import base64
import time

import pytest

from app.config import Settings
from app.persona.schema import VoiceStyle
from app.voice.speech import TtsService
from app.voice.text import has_speech, speech_text

VOICE = VoiceStyle(
    tts_voice="nova", speaking_rate=1.0, instructions="밝게", search_notice="찾아볼게요"
)
PRIMARY, FALLBACK = "primary", "fallback"
MP3 = b"\xff\xfbMP3"


class ScriptedBackend:
    """호출 번호별로 (모델, 동작)을 정해 둔다. 동작: 지연 초(성공) 또는 'fail'."""

    def __init__(self, script: dict[str, list]) -> None:
        self.script = {model: list(actions) for model, actions in script.items()}
        self.calls: list[str] = []
        self.cancelled: list[str] = []

    async def synthesize(self, text: str, voice: VoiceStyle, *, model: str | None = None) -> bytes:
        assert model is not None
        self.calls.append(model)
        actions = self.script.get(model, [])
        action = actions.pop(0) if actions else 0
        try:
            if action == "fail":
                raise RuntimeError("합성 실패")
            await asyncio.sleep(action)
        except asyncio.CancelledError:
            self.cancelled.append(model)
            raise
        return MP3


def service(backend: ScriptedBackend, **kw) -> TtsService:
    params = dict(first_hedge_s=0.2, first_fallback_s=0.4, sentence_timeout_s=0.3)
    params.update(kw)
    return TtsService(backend, primary_model=PRIMARY, fallback_model=FALLBACK, **params)


async def test_first_sentence_fast_primary_wins():
    backend = ScriptedBackend({PRIMARY: [0.01]})
    result = await service(backend).first("안녕하세요!", VOICE, deadline_s=2)
    assert result.model == PRIMARY and not result.fallback
    assert base64.b64decode(result.audio) == MP3
    assert backend.calls == [PRIMARY]


async def test_first_sentence_hedges_after_hedge_time_and_cancels_loser():
    # 첫 요청은 느리고(1초), 헤징 요청이 빨리 끝난다
    backend = ScriptedBackend({PRIMARY: [1.0, 0.01]})
    started = time.monotonic()
    result = await service(backend).first("안녕하세요!", VOICE, deadline_s=3)
    assert time.monotonic() - started < 0.6
    assert result.model == PRIMARY and not result.fallback
    assert backend.calls == [PRIMARY, PRIMARY]
    assert backend.cancelled == [PRIMARY]  # 느린 쪽이 취소됐다


async def test_first_sentence_adds_fallback_model_request():
    backend = ScriptedBackend({PRIMARY: [5, 5], FALLBACK: [0.01]})
    result = await service(backend).first("안녕하세요!", VOICE, deadline_s=3)
    assert result.model == FALLBACK and result.fallback
    assert backend.calls == [PRIMARY, PRIMARY, FALLBACK]  # 동시에 최대 3개
    assert backend.cancelled == [PRIMARY, PRIMARY]


async def test_first_sentence_starts_next_stage_immediately_when_request_fails():
    backend = ScriptedBackend({PRIMARY: ["fail", "fail"], FALLBACK: [0.01]})
    started = time.monotonic()
    result = await service(backend, first_hedge_s=5, first_fallback_s=10).first(
        "안녕하세요!", VOICE, deadline_s=3
    )
    assert time.monotonic() - started < 0.5  # 실패하면 단계 시각을 기다리지 않는다
    assert result.model == FALLBACK and result.fallback


async def test_first_sentence_gives_up_after_deadline_without_sound():
    backend = ScriptedBackend({PRIMARY: [5, 5], FALLBACK: [5]})
    started = time.monotonic()
    result = await service(backend).first("안녕하세요!", VOICE, deadline_s=0.6)
    assert 0.5 < time.monotonic() - started < 1.0
    assert result.audio is None and result.fallback  # 글만 보내고 기기 TTS가 읽는다
    assert sorted(backend.cancelled) == [FALLBACK, PRIMARY, PRIMARY]  # 남은 요청이 모두 취소됐다


async def test_first_sentence_all_fail_returns_no_sound():
    backend = ScriptedBackend({PRIMARY: ["fail", "fail"], FALLBACK: ["fail"]})
    result = await service(backend).first("안녕하세요!", VOICE, deadline_s=3)
    assert result.audio is None and result.fallback


async def test_follow_retries_primary_then_uses_fallback_model():
    backend = ScriptedBackend({PRIMARY: [5, 5], FALLBACK: [0.01]})
    result = await service(backend).follow("둘째 문장이에요.", VOICE)
    assert backend.calls == [PRIMARY, PRIMARY, FALLBACK]
    assert result.model == FALLBACK and result.fallback


async def test_follow_retry_success_is_not_a_fallback():
    backend = ScriptedBackend({PRIMARY: [5, 0.01]})
    result = await service(backend).follow("둘째 문장이에요.", VOICE)
    assert backend.calls == [PRIMARY, PRIMARY]
    assert result.model == PRIMARY and not result.fallback


async def test_follow_all_fail_returns_no_sound():
    backend = ScriptedBackend({PRIMARY: ["fail", "fail"], FALLBACK: ["fail"]})
    result = await service(backend).follow("둘째 문장이에요.", VOICE)
    assert result.audio is None and result.fallback


async def test_text_without_speech_is_skipped_without_a_call():
    backend = ScriptedBackend({})
    svc = service(backend)
    assert (await svc.first("...", VOICE, deadline_s=1)).audio is None
    assert (await svc.follow("**", VOICE)).audio is None
    assert backend.calls == []
    assert not (await svc.first("...", VOICE, deadline_s=1)).fallback  # 읽을 것이 없을 뿐이다


async def test_cached_synthesizes_a_phrase_once_and_skips_failures():
    backend = ScriptedBackend({PRIMARY: ["fail", "fail", 0, 0], FALLBACK: ["fail"]})
    svc = service(backend)
    assert (await svc.cached("고정 문구", VOICE)).audio is None  # 실패는 캐시하지 않는다
    first = await svc.cached("고정 문구", VOICE)
    second = await svc.cached("고정 문구", VOICE)
    assert first.audio and first == second
    assert backend.calls.count(PRIMARY) == 3


def test_speech_text_strips_markdown_and_links():
    assert (
        speech_text("**약수터** 앞 [지도](https://a.com/x)를 보세요") == "약수터 앞 지도를 보세요"
    )
    assert not has_speech(speech_text("- ..."))


def test_voice_settings_defaults_and_blank_key(make_settings):
    s = make_settings()
    assert s.voice_backend == "openai" and s.openai_api_key is None
    assert (s.tts_first_hedge_s, s.tts_first_fallback_s, s.tts_first_deadline_s) == (3, 5, 12)
    assert s.tts_sentence_timeout_s == 6 and s.tts_fallback_model == "tts-1"
    assert make_settings(openai_api_key="  ").openai_api_key is None


def test_openai_key_is_not_exposed_in_repr(make_settings):
    s = make_settings(openai_api_key="sk-test-secret-123")
    assert "sk-test-secret-123" not in repr(s) and "sk-test-secret-123" not in str(s)


def test_invalid_voice_settings_are_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, voice_backend="nope")
    with pytest.raises(ValueError):
        Settings(_env_file=None, tts_first_deadline_s=0)
