"""MCP 요청 기록: POST /mcp마다 JSON-RPC 종류와 결과(HTTP 상태, 오류 여부)를 한 줄씩 남긴다.

도구 호출 기록(guard.py)은 도구 함수까지 온 호출만 남기므로, 이 기록은 그 앞단(initialize·
tools/list 같은 연결 요청, 인자 검증에서 거절된 호출, 인증 실패)을 구분하는 진단용이다.
인자 값, 도구 결과, 토큰은 남기지 않는다(메서드, 도구 이름, 상태, 오류 여부, 시간만).
"""

import json
import logging
import time
from pathlib import Path

from app.db.types import utcnow
from app.mcp_external.guard import append_log_line

logger = logging.getLogger("trailtalk.mcp_external")

MAX_BODY = 64 * 1024
MAX_NAME = 64


def parse_rpc(body: bytes) -> tuple[str | None, str | None]:
    """요청 본문에서 (method, 도구 이름). 해석할 수 없으면 (None, None)."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return None, None
    if isinstance(data, list):
        return "batch", None
    if not isinstance(data, dict):
        return None, None
    method = data.get("method") if isinstance(data.get("method"), str) else None
    params = data.get("params")
    tool = params.get("name") if isinstance(params, dict) else None
    if method != "tools/call" or not isinstance(tool, str):
        tool = None
    return (method[:MAX_NAME] if method else method), (tool[:MAX_NAME] if tool else tool)


def response_has_error(body: bytes) -> bool | None:
    """JSON-RPC 오류이거나 도구 결과가 isError면 True. 해석할 수 없으면 None."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    return "error" in data or (isinstance(result, dict) and result.get("isError") is True)


class RpcLogMiddleware:
    def __init__(self, app, path: str, log_path: Path) -> None:
        self.app = app
        self.path = path
        self.log_path = log_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        messages, chunks, size, complete = [], [], 0, False
        while True:  # 본문을 한도까지 읽어 두고, 앱에는 같은 메시지를 다시 들려준다
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if not message.get("more_body", False):
                complete = True
                break
            if size > MAX_BODY:
                break
        complete = complete and size <= MAX_BODY  # 큰 본문은 해석하지 않는다
        pending = list(messages)

        async def replay():
            return pending.pop(0) if pending else await receive()

        status, reply, reply_size = 0, [], 0

        async def capture(message):
            nonlocal status, reply_size
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and reply_size <= MAX_BODY:
                reply.append(message.get("body", b""))
                reply_size += len(reply[-1])
            await send(message)

        try:
            await self.app(scope, replay, capture)
        finally:
            self._record(chunks, complete, reply, reply_size, status, started, scope)

    def _record(self, chunks, complete, reply, reply_size, status, started, scope) -> None:
        """기록 실패(깨진 입력 포함)가 요청 처리나 원래 예외를 가리지 않게 모든 예외를 삼킨다."""
        try:
            method, tool = parse_rpc(b"".join(chunks)) if complete else (None, None)
            error = response_has_error(b"".join(reply)) if reply_size <= MAX_BODY else None
            agent = dict(scope.get("headers") or []).get(b"user-agent", b"")
            self._write(
                {
                    "at": utcnow().isoformat(),
                    "method": method,
                    "tool": tool,
                    "status": status,
                    "error": error,
                    "ms": round((time.perf_counter() - started) * 1000),
                    "ua": agent.decode("latin-1")[:40],
                }
            )
        except Exception:
            logger.exception("rpc log failed")

    def _write(self, line: dict) -> None:
        try:
            append_log_line(self.log_path, line)
        except OSError:
            logger.exception("rpc log write failed")
