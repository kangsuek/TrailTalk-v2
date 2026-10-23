"""LLM 백엔드 인터페이스.

구독 CLI(ClaudeCliBackend)와 API 키 방식(서비스화)이 같은 모양을 따른다.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from app.errors import AppError
from app.llm.events import LlmEvent


class LlmError(AppError):
    """LLM 호출 실패. API 응답에서는 502로 나간다."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(code, message, status_code)


class LlmProcessError(LlmError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_process_exited", message)


class LlmTimeoutError(LlmError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_timeout", message, 504)


class TurnInProgressError(AppError):
    def __init__(self) -> None:
        super().__init__("turn_in_progress", "이전 답변이 아직 끝나지 않았습니다.", 409)


class LlmSession(Protocol):
    last_used: float  # 마지막 사용 시각(time.monotonic), 유휴 정리 기준
    busy_since: float | None  # 턴 진행 시작 시각, 멈춘 턴 정리 기준
    model: str  # 띄울 때 쓴 모델(바뀌면 매니저가 다시 띄운다)

    @property
    def cli_session_id(self) -> str | None: ...

    @property
    def alive(self) -> bool: ...

    @property
    def busy(self) -> bool: ...

    def send(self, content: "str | list[dict]") -> AsyncIterator[LlmEvent]:
        """사용자 메시지(글 또는 content 블록 배열)를 보내고 TurnFinished까지 이벤트를 낸다.

        반드시 contextlib.aclosing(session.send(...))으로 감싸 끝까지 읽거나 닫는다.
        """
        ...

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...


class LlmBackend(Protocol):
    async def open_session(
        self,
        key: str,
        *,
        system_prompt: str,
        model: str,
        resume_id: str | None = None,
        mcp_config: dict | None = None,
        extra_allowed_tools: Sequence[str] = (),
    ) -> LlmSession: ...
