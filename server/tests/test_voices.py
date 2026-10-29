"""보이스 목록·미리 듣기·프로필 보이스 검사(M3-06). 가짜 음성 백엔드(과금 없음)를 쓴다."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.persona.loader import load_persona
from app.voice.fake import SILENCE_MP3
from app.voice.text import OPENAI_VOICES


@pytest.fixture
def api(make_settings):
    with TestClient(create_app(make_settings(voice_backend="fake"))) as client:
        yield client


def test_voices_lists_provider_voices_and_persona_defaults(api):
    body = api.get("/api/voices").json()
    voice = load_persona(api.app.state.settings.persona_dir, "jenny").persona.voice
    assert body["voices"] == list(OPENAI_VOICES)
    assert body["default_voice"] == voice.tts_voice and body["default_voice"] in body["voices"]
    assert body["default_rate"] == voice.speaking_rate
    assert (body["min_rate"], body["max_rate"]) == (0.75, 1.5)


def test_sample_is_an_mp3_synthesized_once_per_voice_and_rate(api):
    first = api.get("/api/voices/nova/sample?rate=1.0")
    assert first.status_code == 200 and first.headers["content-type"] == "audio/mpeg"
    assert first.content == SILENCE_MP3
    api.get("/api/voices/nova/sample?rate=1.0")
    backend = api.app.state.tts_backend
    assert len(backend.texts) == 1  # 같은 보이스·속도는 다시 합성하지 않는다
    api.get("/api/voices/nova/sample?rate=1.2")
    api.get("/api/voices/onyx/sample?rate=1.0")
    assert len(backend.texts) == 3
    persona_sample = load_persona(api.app.state.settings.persona_dir, "jenny").persona.voice.sample
    assert backend.texts[0] == persona_sample


def test_sample_uses_the_persona_default_rate_when_omitted(api):
    assert api.get("/api/voices/nova/sample").status_code == 200


@pytest.mark.parametrize("path", ["/api/voices/nope/sample", "/api/voices/nova/sample?rate=0.5"])
def test_sample_rejects_unknown_voice_and_out_of_range_rate(api, path):
    response = api.get(path)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


def test_sample_is_503_when_synthesis_is_impossible(api):
    class Failing:
        async def synthesize(self, text, voice, *, model=None):
            raise RuntimeError("합성 실패")

    api.app.state.tts._backend = Failing()
    response = api.get("/api/voices/nova/sample?rate=1.0")
    assert response.status_code == 503 and response.json()["error"]["code"] == "voice_unavailable"


def test_profile_voice_must_be_in_the_list(api):
    assert api.put("/api/profile", json={"voice": "nova"}).json()["voice"] == "nova"
    bad = api.put("/api/profile", json={"voice": "no-such-voice"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    assert api.get("/api/profile").json()["voice"] == "nova"  # 틀린 값은 바꾸지 않는다
    assert api.put("/api/profile", json={"voice": None}).json()["voice"] is None
