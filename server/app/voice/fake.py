"""가짜 음성 인식·합성(설정 VOICE_BACKEND=fake). 과금 없이 화면·E2E를 확인할 때 쓴다.

- 인식: 업로드가 b"FAKE_STT:"로 시작하면 그 뒤 글을, 아니면 설정 FAKE_STT_TEXT를 돌려준다
  (b"FAKE_STT:"만 보내면 빈 결과라 말 없음(no_speech)을 시험할 수 있다).
- 합성: 0.3초 무음 MP3(silence.mp3)를 돌려준다.
"""

from pathlib import Path

from app.persona.schema import VoiceStyle
from app.voice.audio import AudioFile
from app.voice.text import has_speech, speech_text

_PREFIX = b"FAKE_STT:"
SILENCE_MP3 = (Path(__file__).parent / "silence.mp3").read_bytes()


class FakeStt:
    def __init__(self, text: str) -> None:
        self._text = text
        self.prompts: list[str | None] = []  # 테스트에서 넘어온 힌트를 확인한다

    async def transcribe(self, audio: AudioFile, *, prompt: str | None = None) -> str:
        self.prompts.append(prompt)
        if audio.data.startswith(_PREFIX):
            return audio.data[len(_PREFIX) :].decode(errors="replace").strip()
        return self._text.strip()


class FakeTts:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.models: list[str | None] = []

    async def synthesize(self, text: str, voice: VoiceStyle, *, model: str | None = None) -> bytes:
        spoken = speech_text(text)
        if not has_speech(spoken):
            return b""
        self.texts.append(spoken)
        self.models.append(model)
        return SILENCE_MP3
