"""변경성 요청의 CSRF 방어(client-contract 1.5, Spec 9절, D3).

로그인이 없는 /api를 다른 출처 페이지가 사용자의 브라우저로 두드리지 못하게 한다. 공유 토큰은 쓰지
않는다. POST·PUT·PATCH·DELETE는 다음을 모두 지켜야 한다.

1. 헤더 `X-TrailTalk: 1`: 사용자 정의 헤더라 교차 출처 요청은 CORS 사전 요청을 거쳐야 하고,
   CORS를 열지 않으므로 이것이 주된 방어선이다.
2. `Origin`이 있으면 허용 목록(`ALLOWED_ORIGINS`)에 있어야 한다. Host 헤더와 같다는 이유로
   허용하지 않는다(DNS 리바인딩은 Origin과 Host가 같게 온다). `Origin`이 없으면 1번만 본다.
3. 본문이 있으면 `Content-Type`이 application/json·multipart/form-data·audio/* 중 하나여야 한다.

면제: `/internal/*`(루프백 전용, 프록시 경유 차단은 별도 규칙). GET 등 읽기 요청은 검사하지 않는다.
알려진 한계: 읽기(GET)는 보호하지 않는다. Host를 검증하지 않아 DNS 리바인딩 페이지가
읽기 응답(일지·프로필·첨부)을 볼 수 있다. 이 모듈이 막는 것은 상태를 바꾸는 요청이다
(허용 Host 검사는 후속 과제, 13절).
거절은 403 `csrf_rejected`이고, 로그에는 이유 코드만 남긴다(헤더·본문·닉네임 등은 남기지 않는다).
"""

import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import error_response

logger = logging.getLogger("trailtalk.csrf")

CSRF_HEADER = b"x-trailtalk"
CSRF_VALUE = b"1"
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_EXEMPT_PREFIXES = ("/internal/", "/internal")
_BODY_TYPES = ("application/json", "multipart/form-data", "audio/")


def normalize_origin(origin: str) -> str:
    """대소문자·끝의 '/'·기본 포트를 무시해 비교하게 한다(브라우저는 :80·:443을 Origin에서 뺀다)."""
    value = origin.strip().rstrip("/").lower()
    if value.startswith("https://") and value.endswith(":443"):
        return value[: -len(":443")]
    if value.startswith("http://") and value.endswith(":80"):
        return value[: -len(":80")]
    return value


class CsrfMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self._allowed = frozenset(normalize_origin(o) for o in allowed_origins if o.strip())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _MUTATING:
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :]  # 라우팅과 같은 경로로 면제를 판정한다
        if path == "/internal" or path.startswith("/internal/"):
            await self.app(scope, receive, send)
            return
        reason = self._violation(scope)
        if reason is None:
            await self.app(scope, receive, send)
            return
        logger.warning(
            "변경성 요청 거절 reason=%s method=%s path=%s", reason, scope["method"], path
        )
        response = error_response(403, "csrf_rejected", "허용되지 않은 요청입니다.")
        await response(scope, receive, send)

    def _violation(self, scope: Scope) -> str | None:
        headers = {name: value for name, value in scope.get("headers", [])}
        if headers.get(CSRF_HEADER) != CSRF_VALUE:
            return "missing_header"
        if b"origin" in headers:
            origin = headers[b"origin"].decode("latin-1")
            if normalize_origin(origin) not in self._allowed:
                return "origin_not_allowed"
        if _has_body(headers):
            content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
            if not content_type.startswith(_BODY_TYPES):
                return "content_type"
        return None


def _has_body(headers: dict[bytes, bytes]) -> bool:
    if b"transfer-encoding" in headers:
        return True
    length = headers.get(b"content-length")
    return length is not None and length.strip() not in (b"", b"0")
