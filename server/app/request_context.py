"""요청 ID와 요청 로깅.

모든 로그 줄에 요청 ID를 붙이고, 요청마다 method·path·status·지연 시간을 한 줄로 남긴다.
쿼리스트링·헤더·본문은 기록하지 않는다(비밀값 유출 방지, NFR-06).
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

access_logger = logging.getLogger("trailtalk.access")


def get_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    """trailtalk 로거에 요청 ID가 붙는 형식을 설정한다. 여러 번 불러도 핸들러는 하나다.

    uvicorn 기본 access 로그는 쿼리스트링까지 남기므로 끄고, 요청 로그는 이 모듈이 남긴다.
    루트 로거에 핸들러가 있어도 줄이 중복되지 않도록 전파하지 않는다.
    """
    logging.getLogger("uvicorn.access").disabled = True
    logger = logging.getLogger("trailtalk")
    logger.setLevel(level.upper())
    logger.propagate = False
    if not any(getattr(h, "_trailtalk", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler._trailtalk = True  # type: ignore[attr-defined]
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.fullmatch(candidate) else None
    return None


class RequestContextMiddleware:
    """요청 ID를 정하고 응답 헤더에 넣으며, 응답이 끝나면 한 줄 로그를 남긴다.

    순수 ASGI 미들웨어라 SSE처럼 오래 이어지는 응답도 스트림이 끝난 시점에 지연 시간을 잰다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status: int | None = None
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            # 처리되지 않은 예외도 요청 ID가 붙은 공통 오류 형식으로 응답한다.
            # (Starlette의 기본 500 처리는 이 미들웨어 바깥에서 일어나 요청 ID를 잃는다)
            if response_started:
                # 상태 코드는 이미 나갔다(SSE 도중 오류 등).
                # 한 번만 기록하고 연결은 서버가 정리한다.
                logging.getLogger("trailtalk.errors").error("응답 도중 오류", exc_info=exc)
                return
            from app.errors import unhandled_error_response

            await unhandled_error_response(exc)(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            # 응답을 시작하기 전에 연결이 끊기면(취소 등) 상태 코드 대신 "-"를 남긴다.
            access_logger.info(
                "%s %s %s %.1fms",
                scope["method"],
                scope["path"],
                status if status is not None else "-",
                duration_ms,
            )
            _request_id.reset(token)
