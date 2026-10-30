"""소유자 로그인 화면(/login). 비밀번호를 맞게 넣어야만 인가 코드가 발급된다.

pending 요청 ID(추측할 수 없는 값)가 폼의 CSRF 토큰 역할을 한다. 연속 실패는 전역으로 잠그고,
틀릴 때마다 응답을 잠시 늦춘다. 비밀번호 비교는 상수 시간이다. `trailTalk-MCP/app/login.py`를
옮기며 실패 지연을 더했다.
"""

import asyncio
import hashlib
import hmac
import html
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.mcp_external.oauth import OwnerOAuthProvider

LOCK_FAILS = 5
LOCK_WINDOW_S = 600
FAIL_DELAY_S = 1.0
MAX_FORM_BYTES = 4096

_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrailTalk 로그인</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;max-width:360px;margin:12vh auto;padding:0 16px;color:#1c1c1c}}
@media (prefers-color-scheme:dark){{body{{background:#161616;color:#eee}}input{{background:#262626;color:#eee}}}}
input,button{{font-size:16px;width:100%;box-sizing:border-box;padding:12px;margin-top:12px;border-radius:8px;border:1px solid #888}}
button{{background:#c96442;color:#fff;border:0;font-weight:600}}
.err{{color:#c0392b;margin-top:12px}}
</style></head><body>
<h2>TrailTalk 연결 승인</h2>
<p><b>{client}</b> 앱이 이 서버({redirect_host})에 접근하려 합니다. 소유자 비밀번호를 입력하면 승인됩니다.</p>
<form method="post" action="/login" autocomplete="off">
<input type="hidden" name="req" value="{req}">
<input type="password" name="password" placeholder="소유자 비밀번호" autofocus required>
<button type="submit">승인</button>
</form>{error}</body></html>"""  # noqa: E501

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https:; "
        "frame-ancestors 'none'"
    ),
}


class LoginLimiter:
    """최근 LOCK_WINDOW_S 동안 실패가 LOCK_FAILS번이면 잠근다(전역, 메모리)."""

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self.now = now or (lambda: time.time())
        self.failures: deque[float] = deque()

    def _trim(self) -> None:
        cutoff = self.now() - LOCK_WINDOW_S
        while self.failures and self.failures[0] < cutoff:
            self.failures.popleft()

    def locked(self) -> bool:
        self._trim()
        return len(self.failures) >= LOCK_FAILS

    def fail(self) -> None:
        self.failures.append(self.now())

    def reset(self) -> None:
        self.failures.clear()


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def password_matches(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(_digest(supplied), _digest(expected))


def _page(info: dict, req: str, error: str = "", status: int = 200) -> HTMLResponse:
    redirect_host = urlparse(info["redirect_uri"]).netloc
    message = f'<p class="err">{html.escape(error)}</p>' if error else ""
    body = _PAGE.format(
        client=html.escape(info["client_name"]),
        redirect_host=html.escape(redirect_host),
        req=html.escape(req, quote=True),
        error=message,
    )
    return HTMLResponse(body, status_code=status, headers=_SECURITY_HEADERS)


def _plain(message: str, status: int) -> Response:
    return HTMLResponse(html.escape(message), status_code=status, headers=_SECURITY_HEADERS)


def make_login_handler(
    provider: OwnerOAuthProvider,
    limiter: LoginLimiter,
    owner_password: str,
    fail_delay_s: float = FAIL_DELAY_S,
):
    async def login(request: Request) -> Response:
        if request.method == "GET":
            req = request.query_params.get("req", "")
            info = await provider.pending_request(req)
            if info is None:
                return _plain("만료되었거나 잘못된 요청입니다. 앱에서 다시 연결하세요.", 400)
            return _page(info, req)

        body = await request.body()
        if len(body) > MAX_FORM_BYTES:
            return _plain("요청이 너무 큽니다.", 413)
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
        req = form.get("req", "")
        info = await provider.pending_request(req)
        if info is None:
            return _plain("만료되었거나 잘못된 요청입니다. 앱에서 다시 연결하세요.", 400)
        if limiter.locked():
            return _page(info, req, "시도가 너무 많습니다. 잠시 뒤에 다시 하세요.", 429)
        if not password_matches(form.get("password", ""), owner_password):
            limiter.fail()
            await asyncio.sleep(fail_delay_s)
            return _page(info, req, "비밀번호가 맞지 않습니다.", 401)
        limiter.reset()
        redirect = await provider.complete_login(req)
        if redirect is None:
            return _plain("만료되었거나 이미 사용한 요청입니다. 앱에서 다시 연결하세요.", 400)
        return RedirectResponse(redirect, status_code=303, headers=_SECURITY_HEADERS)

    return login
