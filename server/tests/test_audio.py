import shutil
import subprocess

import pytest

from app.errors import AppError
from app.voice.audio import prepare_for_stt

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg가 없음")


def opts(**overrides):
    values = {"max_bytes": 1024 * 1024, "ffmpeg_path": FFMPEG or "ffmpeg", "timeout_s": 10}
    values.update(overrides)
    return values


def sine_ogg_opus() -> bytes:
    """0.5초 사인파를 48kHz 스테레오 ogg/opus로(webm 아닌 형식 업로드 흉내)."""
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=0.5:sample_rate=48000", "-ac", "2",
         "-c:a", "libopus", "-f", "ogg", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [
        ("audio/webm;codecs=opus", "speech.webm"),
        ("audio/wav", "speech.wav"),
        ("audio/mpeg", "speech.mp3"),
        ("audio/mp4", "speech.m4a"),
    ],
)
async def test_supported_formats_pass_through(content_type, filename):
    audio = await prepare_for_stt(b"raw-bytes", content_type, **opts())
    assert audio.data == b"raw-bytes"
    assert audio.filename == filename


def decoded_seconds(webm: bytes) -> float:
    """webm을 16kHz 모노 PCM으로 풀어 길이를 잰다."""
    pcm = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
        input=webm,
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    return len(pcm) / 2 / 16000


@needs_ffmpeg
@pytest.mark.parametrize(
    "content_type", ["audio/ogg;codecs=opus", "application/octet-stream", None]
)
async def test_other_formats_are_converted_to_webm_opus(content_type):
    source = sine_ogg_opus()
    audio = await prepare_for_stt(source, content_type, **opts())
    assert (audio.filename, audio.mime) == ("speech.webm", "audio/webm")
    assert audio.data[:4] == bytes.fromhex("1A45DFA3")  # EBML(webm) 머리말
    assert 0.4 < decoded_seconds(audio.data) < 0.6


@needs_ffmpeg
async def test_converted_audio_is_smaller_than_wav():
    """10초 음성을 WAV(16kHz 16bit, 320KB)보다 훨씬 작게 만든다."""
    source = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=300:duration=10:sample_rate=48000", "-c:a", "libopus",
         "-b:a", "96k", "-f", "ogg", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    audio = await prepare_for_stt(source, "audio/ogg", **opts())
    assert len(audio.data) < 320_000 // 5


async def test_empty_audio_is_rejected():
    with pytest.raises(AppError) as excinfo:
        await prepare_for_stt(b"", "audio/webm", **opts())
    assert excinfo.value.code == "audio_invalid"


async def test_too_large_audio_is_rejected():
    with pytest.raises(AppError) as excinfo:
        await prepare_for_stt(b"x" * 11, "audio/webm", **opts(max_bytes=10))
    assert (excinfo.value.code, excinfo.value.status_code) == ("audio_invalid", 413)


@needs_ffmpeg
async def test_broken_audio_is_rejected():
    with pytest.raises(AppError) as excinfo:
        await prepare_for_stt(b"not audio at all", "audio/ogg", **opts())
    assert excinfo.value.code == "audio_invalid"


async def test_missing_ffmpeg_is_unavailable(tmp_path):
    with pytest.raises(AppError) as excinfo:
        await prepare_for_stt(b"data", "audio/ogg", **opts(ffmpeg_path=str(tmp_path / "none")))
    assert (excinfo.value.code, excinfo.value.status_code) == ("voice_unavailable", 503)


async def test_slow_ffmpeg_is_killed(tmp_path):
    slow = tmp_path / "slow-ffmpeg"
    slow.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    slow.chmod(0o755)
    with pytest.raises(AppError) as excinfo:
        await prepare_for_stt(b"data", "audio/ogg", **opts(ffmpeg_path=str(slow), timeout_s=0.3))
    assert excinfo.value.code == "audio_invalid"
