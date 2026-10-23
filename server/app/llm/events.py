"""LLM 백엔드가 내보내는 턴 이벤트.

Claude CLI stream-json 출력을 서버가 쓰기 쉬운 형태로 줄인 것이다.
API 백엔드(서비스화)도 같은 이벤트를 내보낸다.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TurnStarted:
    """턴 시작. cli_session_id는 프로세스 복구(--resume)에 쓴다."""

    cli_session_id: str | None
    model: str | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    """도구 호출 시작. 이 시점에는 입력이 비어 있다(검색어 등은 ToolCalled에서)."""

    tool_use_id: str
    name: str


@dataclass(frozen=True)
class ToolCalled:
    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolFinished:
    tool_use_id: str
    is_error: bool
    summary: dict[str, Any] | None = None  # 종류(kind)를 붙인 요약(parser._tool_summary)


@dataclass(frozen=True)
class TurnFinished:
    """턴 끝. 오류 여부는 is_error로 판정한다(CLI의 subtype은 오류여도 success일 수 있다)."""

    text: str
    is_error: bool = False
    interrupted: bool = False
    error_message: str | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)


LlmEvent = TurnStarted | TextDelta | ToolStarted | ToolCalled | ToolFinished | TurnFinished
