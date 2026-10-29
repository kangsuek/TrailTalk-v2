"""음성 인식에 보낼 업로드 오디오 준비(계획서 S3-01).

OpenAI 음성 인식이 그대로 받는 형식(웹이 WebCodecs로 만든 webm/opus 등)은 변환하지 않는다.
그 밖의 형식(ogg/opus 등)은 ffmpeg로 16kHz 모노 webm/opus로 바꾼다.
WAV(약 32KB/s)보다 10배쯤 작아 OpenAI로 올리는 시간이 응답 지연(NFR-01)에 덜 더해진다.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.errors import AppError

logger = logging.getLogger("trailtalk.voice")

# MIME 타입(매개변수 제외) → 파일 확장자. 음성 인식 API가 그대로 받는 형식만 둔다
_PASSTHROUGH = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
}
_SAMPLE_RATE = 16000
_BITRATE = "24k"
# 변환 결과 길이 상한(초). 긴 녹음이 음성 인식 업로드 한도(25MB)와 시간 제한을 넘지 않게 한다
_MAX_SECONDS = 120


@dataclass(frozen=True)
class AudioFile:
    data: bytes
    filename: str
    mime: str


def _invalid(message: str, status_code: int = 400) -> AppError:
    return AppError("audio_invalid", message, status_code)


async def prepare_for_stt(
    data: bytes,
    content_type: str | None,
    *,
    max_bytes: int,
    ffmpeg_path: str,
    timeout_s: float,
) -> AudioFile:
    if not data:
        raise _invalid("오디오가 비어 있습니다.")
    if len(data) > max_bytes:
        raise _invalid("오디오가 너무 큽니다.", 413)
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if ext := _PASSTHROUGH.get(mime):
        return AudioFile(data, f"speech.{ext}", mime)
    webm = await _to_webm(data, ffmpeg_path=ffmpeg_path, timeout_s=timeout_s)
    return AudioFile(webm, "speech.webm", "audio/webm")


async def _to_webm(data: bytes, *, ffmpeg_path: str, timeout_s: float) -> bytes:
    # 파이프 출력은 컨테이너 머리말에 길이·색인을 못 적으므로 임시 파일로 받는다
    with tempfile.TemporaryDirectory(prefix="trailtalk-audio-") as tmp:
        out = Path(tmp) / "speech.webm"
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-t",
                str(_MAX_SECONDS),
                "-ac",
                "1",
                "-ar",
                str(_SAMPLE_RATE),
                "-c:a",
                "libopus",
                "-b:a",
                _BITRATE,
                "-vn",
                "-f",
                "webm",
                str(out),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError) as exc:
            logger.error("ffmpeg를 실행할 수 없습니다: %s", exc)
            raise AppError("voice_unavailable", "음성 변환 도구를 쓸 수 없습니다.", 503) from exc
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(data), timeout_s)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise _invalid("오디오 변환 시간이 초과되었습니다.") from exc
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning(
                "오디오 변환 실패(code=%s): %s",
                proc.returncode,
                stderr.decode(errors="replace")[-500:],
            )
            raise _invalid("오디오를 읽을 수 없습니다.")
        return out.read_bytes()
