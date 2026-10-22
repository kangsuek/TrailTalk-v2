"""Claude CLI stream-json 한 줄을 LlmEvent 목록으로 바꾼다.

턴 경계는 result 이벤트다. system/init은 턴마다 다시 오고, assistant 메시지는 블록 종료
이벤트보다 먼저 올 수 있으며, thinking 블록·status·rate_limit 이벤트가 섞인다.
rate_limit 이벤트는 M5(사용량 막대)까지 버린다.
"""

import json
import logging
from typing import Any

from app.llm.events import (
    LlmEvent,
    TextDelta,
    ToolCalled,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnStarted,
)

logger = logging.getLogger("trailtalk.llm")

_SUMMARY_LIMIT = 500


def _tool_summary(raw: Any) -> dict[str, Any] | None:
    """도구 결과에서 SSE에 필요한 부분만 남긴다(본문 전체는 싣지 않는다). 종류는 kind로 구분한다
    (클라이언트 규약 2.6). 앱 도구(MCP) 결과만 다루며 알 수 없는 결과면 None.
    웹 검색·fetch 요약은 검색을 만드는 M5에서 더한다."""
    if not isinstance(raw, dict) or "structuredContent" not in raw:
        return None
    content = raw.get("structuredContent")
    # 문자열을 돌려주는 도구는 SDK가 {"result": 문자열}로 감싼다. 클라이언트에는 그 값만 준다
    if isinstance(content, dict) and set(content) == {"result"}:
        content = content["result"]
    return {"kind": "result", "result": content}


class StreamJsonParser:
    def feed(self, line: str) -> list[LlmEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("JSON이 아닌 CLI 출력 줄을 건너뜀")
            return []
        if not isinstance(event, dict):
            return []
        try:
            return self._convert(event)
        except Exception:  # 출력 형식이 바뀌어도 대화 전체가 끊기지 않게 한 줄만 버린다
            logger.warning("CLI 이벤트 해석 실패(type=%s)", event.get("type"), exc_info=True)
            return []

    def _convert(self, event: dict[str, Any]) -> list[LlmEvent]:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            return [
                TurnStarted(
                    cli_session_id=event.get("session_id"),
                    model=event.get("model"),
                    tools=tuple(event.get("tools") or ()),
                )
            ]
        if kind == "stream_event":
            return self._stream_event(event.get("event") or {})
        if kind == "assistant":
            return self._assistant(event.get("message") or {})
        if kind == "user":
            return self._tool_results(event)
        if kind == "result":
            return [self._result(event)]
        return []

    @staticmethod
    def _stream_event(inner: dict[str, Any]) -> list[LlmEvent]:
        inner_type = inner.get("type")
        if inner_type == "content_block_delta":
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [TextDelta(delta["text"])]
        elif inner_type == "content_block_start":
            block = inner.get("content_block") or {}
            if block.get("type") in ("tool_use", "server_tool_use"):
                return [ToolStarted(tool_use_id=block.get("id", ""), name=block.get("name", ""))]
        return []

    @staticmethod
    def _assistant(message: dict[str, Any]) -> list[LlmEvent]:
        events: list[LlmEvent] = []
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "server_tool_use"):
                events.append(
                    ToolCalled(
                        tool_use_id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input") or {},
                    )
                )
        return events

    @staticmethod
    def _tool_results(event: dict[str, Any]) -> list[LlmEvent]:
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            return []
        events: list[LlmEvent] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                events.append(
                    ToolFinished(
                        tool_use_id=block.get("tool_use_id", ""),
                        is_error=bool(block.get("is_error")),
                        summary=_tool_summary(event.get("tool_use_result")),
                    )
                )
        return events

    @staticmethod
    def _result(event: dict[str, Any]) -> TurnFinished:
        is_error = bool(event.get("is_error"))
        interrupted = event.get("terminal_reason") == "aborted_streaming"
        result_text = event.get("result") if isinstance(event.get("result"), str) else ""
        error_message = None
        if is_error and not interrupted:
            error_message = (result_text or str(event.get("subtype") or "오류"))[:_SUMMARY_LIMIT]
        return TurnFinished(
            text="" if is_error else result_text,
            is_error=is_error,
            interrupted=interrupted,
            error_message=error_message,
            duration_ms=event.get("duration_ms"),
            usage=event.get("usage") or {},
        )
