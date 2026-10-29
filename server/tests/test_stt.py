import json
import logging

import httpx2
import pytest
from pydantic import SecretStr

from app.errors import AppError
from app.voice.audio import AudioFile
from app.voice.stt import OpenAiStt

KEY = "sk-test-secret-key"
AUDIO = AudioFile(b"webm-bytes", "speech.webm", "audio/webm")


def make_stt(handler, *, model="gpt-transcribe", api_key=KEY) -> OpenAiStt:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return OpenAiStt(
        client,
        api_key=SecretStr(api_key) if api_key else None,
        base_url="https://api.test/v1",
        model=model,
        language="ko",
        timeout_s=5,
    )


def form_fields(request: httpx2.Request) -> dict[str, list[str]]:
    """multipart 본문에서 텍스트 필드만 꺼낸다."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    fields: dict[str, list[str]] = {}
    for part in request.content.split(b"--" + boundary):
        head, _, body = part.partition(b"\r\n\r\n")
        if b'name="' not in head or b"filename=" in head:
            continue
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        fields.setdefault(name, []).append(body.removesuffix(b"\r\n").decode())
    return fields


async def test_transcribe_sends_model_language_and_file():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx2.Response(200, json={"text": "  안녕 제니  "})

    text = await make_stt(handler).transcribe(AUDIO, prompt="제니와 산책 대화")
    assert text == "안녕 제니"
    request = seen["request"]
    assert str(request.url) == "https://api.test/v1/audio/transcriptions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    fields = form_fields(request)
    assert fields["model"] == ["gpt-transcribe"]
    assert fields["languages"] == ["ko"]
    assert "language" not in fields
    assert fields["prompt"] == ["제니와 산책 대화"]
    assert b'filename="speech.webm"' in request.content
    assert b"webm-bytes" in request.content


async def test_older_models_use_single_language():
    seen = {}

    def handler(request):
        seen["fields"] = form_fields(request)
        return httpx2.Response(200, json={"text": "네"})

    await make_stt(handler, model="gpt-4o-mini-transcribe").transcribe(AUDIO)
    assert seen["fields"]["language"] == ["ko"]
    assert "languages" not in seen["fields"]
    assert "prompt" not in seen["fields"]


async def test_missing_key_is_unavailable_without_request():
    def handler(request):
        raise AssertionError("요청하면 안 된다")

    with pytest.raises(AppError) as excinfo:
        await make_stt(handler, api_key=None).transcribe(AUDIO)
    assert (excinfo.value.code, excinfo.value.status_code) == ("voice_unavailable", 503)


@pytest.mark.parametrize(
    ("status", "code", "http_status"),
    [
        (401, "voice_unavailable", 503),
        (403, "voice_unavailable", 503),
        (400, "stt_failed", 502),
        (429, "stt_failed", 502),
        (500, "stt_failed", 502),
    ],
)
async def test_error_status_is_mapped(status, code, http_status, caplog):
    def handler(request):
        return httpx2.Response(status, json={"error": {"message": "boom"}})

    with caplog.at_level(logging.WARNING), pytest.raises(AppError) as excinfo:
        await make_stt(handler).transcribe(AUDIO)
    assert (excinfo.value.code, excinfo.value.status_code) == (code, http_status)
    assert KEY not in caplog.text


async def test_timeout_is_mapped():
    def handler(request):
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(AppError) as excinfo:
        await make_stt(handler).transcribe(AUDIO)
    assert (excinfo.value.code, excinfo.value.status_code) == ("stt_timeout", 504)


async def test_connection_error_is_mapped():
    def handler(request):
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(AppError) as excinfo:
        await make_stt(handler).transcribe(AUDIO)
    assert excinfo.value.code == "stt_failed"


@pytest.mark.parametrize("body", [b"not json", json.dumps({"txt": "x"}).encode(), b'{"text": 3}'])
async def test_malformed_response_is_failed(body):
    def handler(request):
        return httpx2.Response(200, content=body)

    with pytest.raises(AppError) as excinfo:
        await make_stt(handler).transcribe(AUDIO)
    assert excinfo.value.code == "stt_failed"


def test_app_exposes_stt(client):
    assert isinstance(client.app.state.stt, OpenAiStt)
