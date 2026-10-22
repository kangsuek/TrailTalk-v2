"""공통 오류 응답 형식.

모든 오류는 {"error": {"code", "message", "request_id", "details"?}} 형식으로 내려간다
(docs/client-contract.md 9절). 서비스 코드는 AppError를 던진다.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.request_context import get_request_id

logger = logging.getLogger("trailtalk.errors")

_STATUS_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    401: "unauthorized",
    403: "forbidden",
    409: "conflict",
    429: "too_many_requests",
}


class AppError(Exception):
    """클라이언트에 그대로 전달해도 되는 오류."""

    def __init__(
        self, code: str, message: str, status_code: int = 400, details: Any = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_response(
    status_code: int, code: str, message: str, details: Any = None, headers: dict | None = None
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _status_code_name(status_code: int) -> str:
    if status_code in _STATUS_CODES:
        return _STATUS_CODES[status_code]
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "http_error"


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    return error_response(
        exc.status_code, _status_code_name(exc.status_code), message, headers=exc.headers
    )


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "요청 형식이 올바르지 않습니다.", details)


def unhandled_error_response(exc: Exception) -> JSONResponse:
    logger.error("처리되지 않은 오류", exc_info=exc)
    return error_response(500, "internal_error", "서버 내부 오류가 발생했습니다.")


def install_error_handlers(app: FastAPI) -> None:
    """처리되지 않은 예외(500)는 RequestContextMiddleware가 unhandled_error_response로 처리한다."""
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
