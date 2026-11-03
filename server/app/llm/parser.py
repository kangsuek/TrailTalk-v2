"""Claude CLI stream-json 한 줄을 LlmEvent 목록으로 바꾼다.

턴 경계는 result 이벤트다. system/init은 턴마다 다시 오고, assistant 메시지는 블록 종료
이벤트보다 먼저 올 수 있으며, thinking 블록·status·rate_limit 이벤트가 섞인다.
rate_limit 이벤트는 턴 이벤트로 내보내지 않고 on_rate_limit 콜백으로 마지막 값만 넘긴다
(구독 사용 한도, app/llm/usage.py).
"""

import json
import logging
from collections.abc import Callable
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
from app.services.search import host_of

logger = logging.getLogger("trailtalk.llm")

_SUMMARY_LIMIT = 500


_MAX_LINKS = 10
_MAX_SOURCES = 3


def _web_search_summary(query: Any, links: list[dict[str, Any]]) -> dict[str, Any]:
    links = links[:_MAX_LINKS]
    hosts = (host_of(link["url"]) for link in links)
    sources = list(dict.fromkeys(h for h in hosts if h))[:_MAX_SOURCES]
    return {
        "kind": "web_search",
        "query": query if isinstance(query, str) else None,
        "links": links,
        "sources": sources,
    }


def _web_fetch_summary(raw: dict[str, Any]) -> dict[str, Any]:
    url = raw.get("url")
    return {
        "kind": "web_fetch",
        "code": raw.get("code") if type(raw.get("code")) is int else None,
        "bytes": raw.get("bytes") if type(raw.get("bytes")) is int else None,
        "url": url if isinstance(url, str) else None,
        "host": host_of(url),
    }


def _tool_summary(raw: Any) -> dict[str, Any] | None:
    """도구 결과에서 SSE에 필요한 부분만 남긴다(본문 전체는 싣지 않는다). 종류는 kind로 구분한다
    (클라이언트 규약 2.6). 알 수 없는 결과면 None.

    - 내장 WebSearch: user 이벤트의 tool_use_result `{query, results:[{content:[{title,url}]}]}`
      (M5-01 ⑤, 문자열 파싱보다 안정적이다)
    - 앱 도구(MCP)는 structuredContent에 담긴다. 검색 도구(search_naver 등)는 `{query, results:
      [{title,url,...}]}`를 돌려주어 같은 web_search 요약이 되고, web_fetch는 `{code, bytes,
      url}`를 돌려주어 web_fetch 요약이 된다."""
    if not isinstance(raw, dict):
        return None
    if "query" in raw and "results" in raw:  # 내장 WebSearch
        links = []
        for result in raw.get("results") or []:
            if not isinstance(result, dict):  # 결과 목록에 요약 문자열이 섞여 온다
                continue
            for item in result.get("content") or []:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    title = item.get("title")
                    links.append(
                        {"title": title if isinstance(title, str) else None, "url": item["url"]}
                    )
        return _web_search_summary(raw.get("query"), links)
    if "code" in raw and "bytes" in raw:  # 내장 WebFetch 형식
        return _web_fetch_summary(raw)
    if "structuredContent" not in raw:
        return None
    content = raw.get("structuredContent")
    # 문자열을 돌려주는 도구는 SDK가 {"result": 문자열}로 감싼다. 클라이언트에는 그 값만 준다
    if isinstance(content, dict) and set(content) == {"result"}:
        content = content["result"]
    if isinstance(content, dict):
        if "query" in content and isinstance(content.get("results"), list):
            links = [
                {
                    "title": r.get("title") if isinstance(r.get("title"), str) else None,
                    "url": r["url"],
                }
                for r in content["results"]
                if isinstance(r, dict) and isinstance(r.get("url"), str)
            ]
            return _web_search_summary(content.get("query"), links)
        if "code" in content and "bytes" in content:
            return _web_fetch_summary(content)
    return {"kind": "result", "result": content}


def tool_sources(raw: Any) -> tuple[dict[str, str | None], ...]:
    """도구 결과에서 답변의 출처(turn.sources)가 될 항목 [{title, url, host}]을 뽑는다. 웹 검색
    결과 링크(최대 10개)와 web_fetch로 읽은 페이지(HTTP 400 미만)만 해당한다. host는 화면에 보일
    출처 호스트(www. 뗌)이며 요약의 sources와 같은 규칙이다."""
    summary = _tool_summary(raw)
    if summary is None:
        return ()
    if summary["kind"] == "web_fetch":
        url, code = summary["url"], summary["code"]
        if not url or (code is not None and code >= 400):
            return ()
        return ({"title": None, "url": url, "host": summary["host"]},)
    if summary["kind"] != "web_search":
        return ()
    return tuple(
        {"title": link["title"], "url": link["url"], "host": host_of(link["url"])}
        for link in summary["links"]
    )


def _result_text(content: Any) -> str | None:
    """tool_result.content(문자열 또는 {type: text, text} 블록 목록)의 글."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        return "\n".join(texts) if texts else None
    return None


class StreamJsonParser:
    def __init__(self, on_rate_limit: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._on_rate_limit = on_rate_limit

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
        if kind == "rate_limit_event":
            info = event.get("rate_limit_info")
            if self._on_rate_limit is not None and isinstance(info, dict):
                try:
                    self._on_rate_limit(info)
                except Exception:  # 사용량 기록 실패가 턴 해석을 막지 않게 한다
                    logger.warning("사용 한도 콜백 실패", exc_info=True)
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
                        sources=tool_sources(event.get("tool_use_result")),
                        result_text=_result_text(block.get("content")),
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
