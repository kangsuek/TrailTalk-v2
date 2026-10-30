"""외부 MCP 도구 공통 보호: 호출 기록, 속도 제한, 하루 쓰기 상한, 삭제 확인 값 서명.

- 호출 기록은 도구 이름·시각·성공 여부·걸린 시간·대상 id(앞 8자)만 남긴다. 인자·결과는
  남기지 않는다(MFR-11).
- 속도 제한은 전역 슬라이딩 60초당 60회, 쓰기 도구는 하루 200건(서버 시간대 날짜)이다.
  둘 다 프로세스 메모리에 두므로 재시작하면 처음부터 센다.
- 확인 값(`confirm_token`)은 삭제 같은 되돌릴 수 없는 호출 앞에 서버가 강제하는 2단계 확인이다.
  소유자 비밀번호에서 키를 파생한 HMAC 서명이라 상태를 저장하지 않고, 비밀번호를 바꾸면 모두 무효다.
  사용자가 두 호출 사이에 실제로 확인했는지는 서버가 알 수 없다(MCP/design.md 한계).
"""

import base64
import functools
import hashlib
import hmac
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.mcpserver.exceptions import ToolError

from app.db.types import utcnow

logger = logging.getLogger("trailtalk.mcp_external")

RATE_LIMIT_CALLS = 60
RATE_LIMIT_WINDOW_S = 60.0
DAILY_WRITE_LIMIT = 200
CONFIRM_TTL_S = 300
SHORT_ID_CHARS = 8
MAX_LOG_BYTES = 5 * 1024 * 1024  # 인증 없는 요청이 쌓여도 디스크를 채우지 않게 이 크기에서 멈춘다


def short_id(full_id: str) -> str:
    return full_id[:SHORT_ID_CHARS]


class SlidingWindowLimiter:
    """전역 슬라이딩 윈도우: window_s 동안 limit회까지."""

    def __init__(
        self,
        limit: int = RATE_LIMIT_CALLS,
        window_s: float = RATE_LIMIT_WINDOW_S,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.now = now or time.monotonic
        self.calls: deque[float] = deque()

    def allow(self) -> bool:
        current = self.now()
        while self.calls and self.calls[0] <= current - self.window_s:
            self.calls.popleft()
        if len(self.calls) >= self.limit:
            return False
        self.calls.append(current)
        return True


class DailyWriteCounter:
    """서버 시간대 날짜별 쓰기 호출 수. 날짜가 바뀌면 0부터 다시 센다."""

    def __init__(
        self,
        limit: int = DAILY_WRITE_LIMIT,
        tz: ZoneInfo | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.limit = limit
        self.tz = tz or ZoneInfo("Asia/Seoul")
        self.now = now or utcnow
        self.day: date | None = None
        self.count = 0

    def allow(self) -> bool:
        today = self.now().astimezone(self.tz).date()
        if today != self.day:
            self.day, self.count = today, 0
        if self.count >= self.limit:
            return False
        self.count += 1
        return True


def _confirm_key(owner_password: str) -> bytes:
    return hmac.new(owner_password.encode(), b"trailtalk-mcp-confirm-v1", hashlib.sha256).digest()


class ConfirmSigner:
    """삭제 확인 값: `<만료 epoch>.<서명>`. 행동(action)과 대상 id에 묶인다."""

    def __init__(
        self,
        owner_password: str,
        ttl_s: int = CONFIRM_TTL_S,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.key = _confirm_key(owner_password)
        self.ttl_s = ttl_s
        self.now = now or time.time

    def _sign(self, action: str, target_id: str, expires: int) -> str:
        message = f"{action}|{target_id}|{expires}".encode()
        digest = hmac.new(self.key, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def issue(self, action: str, target_id: str) -> str:
        expires = int(self.now()) + self.ttl_s
        return f"{expires}.{self._sign(action, target_id, expires)}"

    def valid(self, token: str, action: str, target_id: str) -> bool:
        head, _, signature = token.partition(".")
        if not head.isdigit() or not signature:
            return False
        expires = int(head)
        if expires < self.now():
            return False
        return hmac.compare_digest(signature, self._sign(action, target_id, expires))


@dataclass
class ToolGuard:
    """도구 함수를 감싸는 보호 계층. register_tools가 도구마다 `guard.wrap(...)`을 쓴다."""

    call_log: Path
    limiter: SlidingWindowLimiter = field(default_factory=SlidingWindowLimiter)
    writes: DailyWriteCounter = field(default_factory=DailyWriteCounter)
    signer: ConfirmSigner | None = None

    def log(self, tool: str, ok: bool, ms: float, target: str | None = None) -> None:
        line = {"at": utcnow().isoformat(), "tool": tool, "ok": ok, "ms": round(ms)}
        if target:
            line["target"] = short_id(target)
        try:
            if self.call_log.exists() and self.call_log.stat().st_size > MAX_LOG_BYTES:
                return
            self.call_log.parent.mkdir(parents=True, exist_ok=True)
            with self.call_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("call log write failed")

    def wrap(self, *, write: bool = False, target_arg: str | None = None):
        """속도 제한(쓰기 도구는 하루 상한도)과 호출 기록을 더한다. target_arg는 기록할 대상 id를
        담은 인자 이름이다."""

        def decorator(fn):
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                started = time.perf_counter()
                target = kwargs.get(target_arg) if target_arg else None
                ok = False
                try:
                    if not self.limiter.allow():
                        raise ToolError("요청이 너무 잦습니다. 잠시 뒤에 다시 하세요.")
                    if write and not self.writes.allow():
                        raise ToolError(
                            "오늘 저장·수정·삭제 한도에 도달했습니다. 내일 다시 하세요."
                        )
                    result = await fn(*args, **kwargs)
                    ok = True
                    return result
                finally:
                    elapsed = (time.perf_counter() - started) * 1000
                    self.log(fn.__name__, ok, elapsed, target if isinstance(target, str) else None)

            return wrapper

        return decorator
