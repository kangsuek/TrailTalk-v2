"""음성 세션·음성 턴·지연 API(M3-04·05·07). 가짜 Claude CLI와 가짜 음성 백엔드(과금 없음)를 쓴다."""

import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ConversationSession, Turn, TurnLatency, TurnRole, TurnTts
from app.main import create_app
from app.persona.loader import load_persona
from app.voice.fake import SILENCE_MP3
from tests.test_sessions import events_of, home, start  # noqa: F401  (home 픽스처 포함)

UPLOAD = {"content-type": "audio/webm"}
TRANSCRIPT = "오늘 산책하면서 생각난 아이디어가 있어"
SPEECH = b"FAKE_STT:" + TRANSCRIPT.encode()


def make_api(fake_cli, monkeypatch, **overrides):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    settings = fake_cli.settings.model_copy(update={"voice_backend": "fake", **overrides})
    return create_app(settings)


@pytest.fixture
def api(fake_cli, home, monkeypatch):  # noqa: F811
    with TestClient(make_api(fake_cli, monkeypatch)) as client:
        yield client


def rows(client: TestClient, model):
    async def go():
        async with client.app.state.session_factory() as db:
            return list(await db.scalars(select(model)))

    return asyncio.run(go())


def audio_turn(api, session_id: str, body: bytes = SPEECH):
    return api.post(f"/api/sessions/{session_id}/turns/audio", content=body, headers=UPLOAD)


def test_voice_session_has_greeting_audio_and_text_session_does_not(api):
    voice = start(api, "voice")
    assert base64.b64decode(voice["greeting"]["audio"]) == SILENCE_MP3
    assert voice["persona"]["ack"] and all(a["audio"] is None for a in voice["persona"]["ack"])
    assert start(api, "text")["greeting"]["audio"] is None


def test_audio_turn_streams_transcript_turn_sentences_with_sound_and_done(api):
    session_id = start(api, "voice")["session"]["id"]
    response = audio_turn(api, session_id)
    assert response.status_code == 200
    events = events_of(response)
    kinds = [event.type for event in events]
    assert kinds[:2] == ["transcript", "turn"] and kinds[-1] == "done"
    assert events[0].text == TRANSCRIPT
    sentences = [e for e in events if e.type == "sentence"]
    assert sentences
    for sentence in sentences:
        assert base64.b64decode(sentence.audio) == SILENCE_MP3 and sentence.speech_text is None
    turns = {t.role: t for t in rows(api, Turn) if not t.greeting}
    assert turns[TurnRole.USER].text == events[0].text  # 인식한 글이 사용자 턴으로 저장됐다
    assert turns[TurnRole.ASSISTANT].text == events[-1].text


def test_audio_turn_on_text_session_has_no_sound(api):
    session_id = start(api, "text")["session"]["id"]
    events = events_of(audio_turn(api, session_id))
    assert events[0].type == "transcript"
    for sentence in [e for e in events if e.type == "sentence"]:
        assert sentence.audio is None and sentence.speech_text is None


def test_no_speech_is_a_json_error_and_stores_nothing(api):
    session_id = start(api, "voice")["session"]["id"]
    response = audio_turn(api, session_id, b"FAKE_STT:")
    assert response.status_code == 422 and response.json()["error"]["code"] == "no_speech"
    assert [t for t in rows(api, Turn) if not t.greeting] == []
    assert rows(api, TurnLatency) == []


def test_empty_and_too_large_audio_are_rejected(fake_cli, home, monkeypatch):  # noqa: F811
    with TestClient(make_api(fake_cli, monkeypatch, stt_max_bytes=64)) as api:
        session_id = start(api, "voice")["session"]["id"]
        empty = audio_turn(api, session_id, b"")
        assert empty.status_code == 400 and empty.json()["error"]["code"] == "audio_invalid"
        big = audio_turn(api, session_id, b"FAKE_STT:" + b"x" * 200)
        assert big.status_code == 413 and big.json()["error"]["code"] == "audio_invalid"


def test_audio_turn_on_ended_session_is_session_ended(api):
    session_id = start(api, "voice")["session"]["id"]
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    response = audio_turn(api, session_id)
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_ended"


def test_closing_and_reopen_greeting_have_sound_only_for_voice(api):
    voice_id = start(api, "voice")["session"]["id"]
    closed = api.post(f"/api/sessions/{voice_id}/end").json()
    assert base64.b64decode(closed["closing_audio"]) == SILENCE_MP3
    reopened = api.post(f"/api/sessions/{voice_id}/reopen", json={"mode": "voice"}).json()
    assert base64.b64decode(reopened["greeting"]["audio"]) == SILENCE_MP3

    text_id = start(api, "text")["session"]["id"]
    assert api.post(f"/api/sessions/{text_id}/end").json()["closing_audio"] is None
    again = api.post(f"/api/sessions/{text_id}/reopen", json={"mode": "text"}).json()
    assert again["greeting"]["audio"] is None


class FailingBackend:
    async def synthesize(self, text, voice, *, model=None):
        raise RuntimeError("합성 실패")


def test_failed_synthesis_sends_text_with_speech_text_and_the_session_continues(api):
    api.app.state.tts._backend = FailingBackend()
    started = start(api, "voice")
    assert started["greeting"]["audio"] is None  # 인사말 합성이 실패해도 세션은 시작된다
    session_id = started["session"]["id"]
    events = events_of(audio_turn(api, session_id))
    assert events[-1].type == "done"
    sentences = [e for e in events if e.type == "sentence"]
    assert sentences and all(s.audio is None and s.speech_text for s in sentences)


def test_first_sentence_over_deadline_goes_out_as_text(fake_cli, home, monkeypatch):  # noqa: F811
    with TestClient(
        make_api(
            fake_cli,
            monkeypatch,
            tts_first_deadline_s=0.3,
            tts_first_hedge_s=0.1,
            tts_first_fallback_s=0.2,
            tts_sentence_timeout_s=0.1,
        )
    ) as api:

        class Slow:
            async def synthesize(self, text, voice, *, model=None):
                await asyncio.sleep(5)
                return SILENCE_MP3

        session_id = start(api, "voice")["session"]["id"]
        api.app.state.tts._backend = Slow()
        events = events_of(audio_turn(api, session_id))
        first = next(e for e in events if e.type == "sentence")
        assert first.audio is None and first.speech_text  # 12초 규칙(여기서는 0.3초)
        assert events[-1].type == "done"


def test_latency_is_recorded_per_voice_turn_and_client_report_fills_total(api):
    session_id = start(api, "voice")["session"]["id"]
    events = events_of(audio_turn(api, session_id))
    turn_id = events[1].turn_id
    [row] = rows(api, TurnLatency)
    assert row.turn_id == turn_id and row.session_id == session_id
    for name in ("upload_ms", "stt_ms", "first_token_ms", "first_sentence_ms", "done_ms"):
        assert getattr(row, name) is not None
    assert row.audio_bytes == len(SPEECH) and row.reply_chars == len(events[-1].text)
    assert row.first_sentence_ms <= row.done_ms and row.speech_to_request_ms is None

    url = f"/api/sessions/{session_id}/turns/{turn_id}/latency"
    body = {"speech_to_request_ms": 1850, "request_to_playback_ms": 5000}
    assert api.post(url, json=body).status_code == 204
    again = body | {"request_to_playback_ms": 6000}
    assert api.post(url, json=again).status_code == 204  # 덮어쓰기
    latency = api.get("/api/latency").json()
    assert latency["turns"][0]["total_ms"] == 7850
    summary = latency["summary"]
    assert summary["count"] == 1 and summary["total_ms"] == {"median": 7850, "p90": 7850}
    assert summary["total_ms_reply"]["median"] == 7850
    assert summary["stages"]["stt_ms"] == row.stt_ms and summary["search"]["count"] == 0


def test_latency_report_validation_and_unknown_turn(api):
    session_id = start(api, "voice")["session"]["id"]
    turn_id = events_of(audio_turn(api, session_id))[1].turn_id
    ok = {"speech_to_request_ms": 1, "request_to_playback_ms": 2}
    assert api.post(f"/api/sessions/{session_id}/turns/nope/latency", json=ok).status_code == 404
    other = start(api, "voice")["session"]["id"]  # 다른 세션의 턴 ID로는 보고할 수 없다
    assert api.post(f"/api/sessions/{other}/turns/{turn_id}/latency", json=ok).status_code == 404
    bad = ok | {"request_to_playback_ms": 600001}
    url = f"/api/sessions/{session_id}/turns/{turn_id}/latency"
    assert api.post(url, json=bad).status_code == 422
    assert api.get("/api/latency?limit=0").status_code == 422


def test_first_sound_notice_turns_are_excluded_from_reply_stats(api):
    session_id = start(api, "voice")["session"]["id"]
    turn_id = events_of(audio_turn(api, session_id))[1].turn_id
    body = {"speech_to_request_ms": 100, "request_to_playback_ms": 200, "first_sound_notice": True}
    api.post(f"/api/sessions/{session_id}/turns/{turn_id}/latency", json=body)
    summary = api.get("/api/latency").json()["summary"]
    assert summary["total_ms"]["median"] == 300 and summary["total_ms_reply"] is None


def test_tts_models_and_fallback_ratio_are_recorded_per_sentence(api):
    session_id = start(api, "voice")["session"]["id"]
    events_of(audio_turn(api, session_id))
    records = rows(api, TurnTts)
    sentences = [e for e in events_of(audio_turn(api, session_id)) if e.type == "sentence"]
    assert records and len(rows(api, TurnTts)) == len(records) + len(sentences)
    assert all(r.model == api.app.state.settings.tts_model and not r.fallback for r in records)
    tts = api.get("/api/latency").json()["summary"]["tts"]
    assert tts["fallback_ratio"] == 0.0
    assert tts["models"] == {api.app.state.settings.tts_model: len(rows(api, TurnTts))}


def test_fallback_ratio_counts_sentences_that_fell_back(api):
    api.app.state.tts._backend = FailingBackend()
    session_id = start(api, "voice")["session"]["id"]
    events_of(audio_turn(api, session_id))
    tts = api.get("/api/latency").json()["summary"]["tts"]
    assert tts["fallback_ratio"] == 1.0 and tts["models"].get("device", 0) >= 1


def test_deleting_the_journal_removes_latency_and_tts_rows(api):
    session_id = start(api, "voice")["session"]["id"]
    events_of(audio_turn(api, session_id))
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    assert rows(api, TurnLatency) and rows(api, TurnTts)
    assert api.delete(f"/api/journal/{session_id}").status_code == 204
    assert rows(api, TurnLatency) == [] and rows(api, TurnTts) == []
    assert rows(api, ConversationSession) == []


def test_profile_voice_and_rate_are_used_for_synthesis(api):
    api.put("/api/profile", json={"voice": "onyx", "speaking_rate": 1.3})
    seen = []
    backend = api.app.state.tts_backend
    original = backend.synthesize

    async def spy(text, voice, *, model=None):
        seen.append((voice.tts_voice, voice.speaking_rate))
        return await original(text, voice, model=model)

    backend.synthesize = spy
    session_id = start(api, "voice")["session"]["id"]
    events_of(audio_turn(api, session_id))
    assert seen and set(seen) == {("onyx", 1.3)}  # 인사말과 답변 문장 모두
    api.put("/api/profile", json={"voice": None, "speaking_rate": None})
    seen.clear()
    start(api, "voice")
    voice = load_persona(api.app.state.settings.persona_dir, "jenny").persona.voice
    assert set(seen) == {(voice.tts_voice, voice.speaking_rate)}  # 페르소나 YAML 값으로 돌아간다
