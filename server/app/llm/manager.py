"""세션별 LLM 프로세스를 관리한다(재사용, 죽은 프로세스 --resume 복구, 유휴·멈춘 세션 정리).

DB는 모른다. 호출하는 쪽이 TurnStarted.cli_session_id를 DB에 저장하고 resume_id로 넘긴다.
살아 있는 세션은 system_prompt가 바뀌어도 그대로 재사용한다(바꾸려면 close 후 get).
model이 바뀌면(대화 모델 선택) 답변 중이 아닐 때 닫고 같은 CLI 대화 기록으로
--resume해 새 모델로 다시 띄운다.
"""

import asyncio
import logging
import time
from collections.abc import Sequence

from app.llm.backend import LlmBackend, LlmSession

logger = logging.getLogger("trailtalk.llm")


class LlmSessionManager:
    def __init__(
        self, backend: LlmBackend, *, idle_timeout_s: float, stuck_timeout_s: float | None = None
    ) -> None:
        self._backend = backend
        self._idle_timeout_s = idle_timeout_s
        # 턴이 이 시간보다 오래 잠겨 있으면(스트림을 닫지 않고 버린 경우 등) 강제로 닫는다
        self._stuck_timeout_s = stuck_timeout_s
        self._sessions: dict[str, LlmSession] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._reaper: asyncio.Task | None = None

    async def start(self) -> None:
        self._reaper = asyncio.create_task(self._reap_loop())

    def _key_lock(self, key: str) -> asyncio.Lock:
        return self._key_locks.setdefault(key, asyncio.Lock())

    async def get(
        self,
        key: str,
        *,
        system_prompt: str,
        model: str,
        resume_id: str | None = None,
        mcp_config: dict | None = None,
        extra_allowed_tools: Sequence[str] = (),
    ) -> LlmSession:
        async with self._key_lock(key):
            session = self._sessions.get(key)
            if session is not None and session.alive:
                if session.model == model or session.busy:
                    session.last_used = time.monotonic()  # 돌려준 직후 유휴 정리되지 않게
                    return session
                # 모델이 바뀌었다: 지금까지의 맥락을 이어 새 모델로 다시 띄운다
                resume_id = session.cli_session_id or resume_id
                self._sessions.pop(key, None)
                await session.close()
                logger.info("모델 변경으로 CLI 재기동(session=%s, model=%s)", key, model)
            elif session is not None:
                # 죽은 프로세스: 방금까지 쓰던 CLI 세션 ID(메모리 값 우선)로 맥락을 이어 다시 띄운다
                if resume_id and session.cli_session_id and resume_id != session.cli_session_id:
                    logger.warning("resume ID 불일치(session=%s), 메모리 값을 사용", key)
                resume_id = session.cli_session_id or resume_id
                self._sessions.pop(key, None)
                await session.close()
                logger.info("CLI 프로세스 복구(session=%s, resume=%s)", key, bool(resume_id))
            session = await self._backend.open_session(
                key,
                system_prompt=system_prompt,
                model=model,
                resume_id=resume_id,
                mcp_config=mcp_config,
                extra_allowed_tools=extra_allowed_tools,
            )
            self._sessions[key] = session
            return session

    def is_alive(self, key: str) -> bool:
        session = self._sessions.get(key)
        return session is not None and session.alive

    async def close(self, key: str) -> None:
        lock = self._key_lock(key)
        async with lock:
            session = self._sessions.pop(key, None)
        if session is not None:
            await session.close()
        if not lock.locked() and key not in self._sessions:
            self._key_locks.pop(key, None)  # 대화 수만큼 락이 쌓이지 않게

    def _should_reap(self, session: LlmSession, now: float) -> str | None:
        if session.busy:
            since = session.busy_since
            if self._stuck_timeout_s is not None and since and now - since > self._stuck_timeout_s:
                return "멈춘 턴"
            return None
        if now - session.last_used > self._idle_timeout_s:
            return "유휴"
        if not session.alive:
            return "종료된 프로세스"
        return None

    async def reap(self) -> int:
        now = time.monotonic()
        reaped = 0
        for key, session in list(self._sessions.items()):
            reason = self._should_reap(session, now)
            if reason is None:
                continue
            lock = self._key_lock(key)
            if lock.locked():
                continue  # get()이 같은 세션을 다루는 중
            async with lock:
                if self._sessions.get(key) is not session:
                    continue
                self._sessions.pop(key)
            logger.info("CLI 프로세스 정리(session=%s, 이유=%s)", key, reason)
            await session.close()
            if not lock.locked() and key not in self._sessions:
                self._key_locks.pop(key, None)  # 대화 수만큼 락이 쌓이지 않게
            reaped += 1
        return reaped

    async def _reap_loop(self) -> None:
        timeouts = [self._idle_timeout_s]
        if self._stuck_timeout_s:
            timeouts.append(self._stuck_timeout_s)
        interval = max(min(min(timeouts) / 4, 30.0), 0.05)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reap()
            except Exception:
                logger.exception("CLI 프로세스 정리 실패")

    async def shutdown(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            await asyncio.wait([self._reaper])  # 바깥 취소는 삼키지 않는다
        sessions = list(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)

    @property
    def active_count(self) -> int:
        return len(self._sessions)
