"""대화에서 쓰는 음성 합성 서비스(Spec 5.2): 타임아웃·헤징·재시도·대체 모델.

합성 실패는 대화를 멈추지 않는다. 최종 실패하면 audio=None을 돌려주고, 클라이언트는 그 문장의
speech_text를 기기 TTS로 읽는다. 문장마다 실제로 쓴 모델과 폴백 여부를 돌려줘 기록한다.

- 첫 문장(first): 시작 직후 기본 모델로 요청하고, hedge_s가 지나도 소리가 없으면
  같은 요청을 한 번 더,
  fallback_s가 지나도 없으면 대체 모델 요청을 더한다(동시에 최대 3개). 먼저 성공한 결과를 쓰고
  나머지는 취소한다. 요청이 빨리 실패하면 다음 단계를 기다리지 않고 바로 시작한다. deadline_s가
  지나면 소리 없이 끝낸다(글 먼저 전송).
- 둘째 문장부터(follow): 기본 모델 → 재시도 → 대체 모델, 시도마다 sentence_timeout_s 제한.
"""

import asyncio
import base64
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.persona.schema import VoiceStyle
from app.voice.text import has_speech, speech_text
from app.voice.tts import TtsBackend

logger = logging.getLogger("trailtalk.voice")

MAX_CACHED = 64  # 캐시하는 문구 수(보이스 미리 듣기 등). 넘으면 오래 안 쓴 것부터 버린다


@dataclass(frozen=True)
class Synthesis:
    audio: str | None  # MP3(base64). 읽을 글자가 없거나 최종 실패면 None
    model: str | None  # 소리를 만든 모델(소리가 없으면 None)
    fallback: bool  # 대체 모델이나 기기 TTS로 넘어갔는지(읽을 글자가 없어 소리가 없는 경우는 False)


NO_SOUND = Synthesis(None, None, False)


class TtsService:
    def __init__(
        self,
        backend: TtsBackend,
        *,
        primary_model: str,
        fallback_model: str,
        first_hedge_s: float,
        first_fallback_s: float,
        sentence_timeout_s: float,
    ) -> None:
        self._backend = backend
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self._hedge_s = first_hedge_s
        self._fallback_s = first_fallback_s
        self._timeout_s = sentence_timeout_s
        self._cache: OrderedDict[tuple[str, VoiceStyle], Synthesis] = OrderedDict()

    def _result(self, audio: bytes, model: str) -> Synthesis:
        return Synthesis(
            base64.b64encode(audio).decode("ascii"), model, model == self.fallback_model
        )

    async def _call(self, text: str, voice: VoiceStyle, model: str) -> bytes:
        try:
            return await self._backend.synthesize(text, voice, model=model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("음성 합성 실패(model=%s): %s", model, exc)
            return b""

    async def first(self, text: str, voice: VoiceStyle, *, deadline_s: float) -> Synthesis:
        """첫 문장. deadline_s는 이 호출 시작부터 소리 없이 포기하기까지의 시간이다."""
        if not has_speech(speech_text(text)):
            return NO_SOUND
        started = time.monotonic()
        schedule = [
            (self._hedge_at(), self.primary_model),
            (self._fallback_at(), self.fallback_model),
        ]
        tasks: dict[asyncio.Task[bytes], str] = {}

        def start(model: str) -> None:
            tasks[asyncio.ensure_future(self._call(text, voice, model))] = model

        start(self.primary_model)
        upcoming = 0
        try:
            while True:
                elapsed = time.monotonic() - started
                remaining = deadline_s - elapsed
                if remaining <= 0:
                    return Synthesis(None, None, True)
                if not tasks:  # 모두 실패했다: 기다리지 않고 다음 단계로
                    if upcoming >= len(schedule):
                        return Synthesis(None, None, True)
                    start(schedule[upcoming][1])
                    upcoming += 1
                    continue
                wait_s = remaining
                if upcoming < len(schedule):
                    wait_s = min(wait_s, max(schedule[upcoming][0] - elapsed, 0))
                done, _ = await asyncio.wait(
                    tasks, timeout=wait_s, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    model = tasks.pop(task)
                    audio = task.result()
                    if audio:
                        return self._result(audio, model)
                if not done and upcoming < len(schedule):
                    if time.monotonic() - started >= schedule[upcoming][0] - 0.001:
                        start(schedule[upcoming][1])
                        upcoming += 1
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _hedge_at(self) -> float:
        return self._hedge_s

    def _fallback_at(self) -> float:
        return self._fallback_s

    async def follow(self, text: str, voice: VoiceStyle) -> Synthesis:
        """둘째 문장부터: 기본 모델 → 재시도 → 대체 모델."""
        if not has_speech(speech_text(text)):
            return NO_SOUND
        for model in (self.primary_model, self.primary_model, self.fallback_model):
            try:
                audio = await asyncio.wait_for(self._call(text, voice, model), self._timeout_s)
            except TimeoutError:
                logger.warning("음성 합성 시간 초과(model=%s)", model)
                continue
            if audio:
                return self._result(audio, model)
        return Synthesis(None, None, True)

    async def cached(self, text: str, voice: VoiceStyle) -> Synthesis:
        """같은 문구는 한 번만 합성한다(실패는 캐시하지 않는다)."""
        key = (text, voice)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = await self.follow(text, voice)
        if result.audio is None:
            return result
        self._cache[key] = result
        while len(self._cache) > MAX_CACHED:
            self._cache.popitem(last=False)
        return result
