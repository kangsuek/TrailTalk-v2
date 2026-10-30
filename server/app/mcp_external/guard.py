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
from sqlalchemy.exc import SQLAlchemyError

from app.db.types import utcnow
from app.errors import AppError
from app.services.app_journal import AppJournalError
from app.services.lookup import LookupFailure

logger = logging.getLogger("trailtalk.mcp_external")

RATE_LIMIT_CALLS = 60
RATE_LIMIT_WINDOW_S = 60.0
DAILY_WRITE_LIMIT = 200
CONFIRM_TTL_S = 300
SHORT_ID_CHARS = 8
MAX_LOG_BYTES = 5 * 1024 * 1024  # 이 크기가 되면 로그를 한 단계(.1) 돌리고 새로 시작한다


def append_log_line(path: Path, line: dict) -> None:
    """기록 한 줄을 덧붙인다. 파일이 MAX_LOG_BYTES를 넘으면 `<이름>.1`로 돌려(이전 .1은 덮어쓴다)
    인증 없는 요청이 쌓여도 디스크를 채우지 않고 새 기록도 계속 남긴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


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


CONFIRM_KDF_ITERATIONS = 100_000
CONFIRM_MAX_EXPIRY_CHARS = 12


def _confirm_key(owner_password: str) -> bytes:
    """로그인 비교에 쓰는 비밀번호와 다른 키를 얻는다. 확인 값이 노출돼도 비밀번호를 곧바로
    추측하기 어렵게 PBKDF2를 한 번 거친다(프로세스마다 한 번)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        owner_password.encode(),
        b"trailtalk-mcp-confirm-v1",
        CONFIRM_KDF_ITERATIONS,
    )


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
        # 구분자 문제가 없게 JSON 배열로 묶는다(어떤 글자가 있어도 경계가 모호하지 않다)
        message = json.dumps([action, target_id, expires]).encode()
        digest = hmac.new(self.key, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def issue(self, action: str, target_id: str) -> str:
        expires = int(self.now()) + self.ttl_s
        return f"{expires}.{self._sign(action, target_id, expires)}"

    def valid(self, token: str, action: str, target_id: str) -> bool:
        head, _, signature = token.partition(".")
        if not head.isdigit() or len(head) > CONFIRM_MAX_EXPIRY_CHARS or not signature:
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
            append_log_line(self.call_log, line)
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
                    try:
                        result = await fn(*args, **kwargs)
                    except (LookupFailure, AppJournalError) as exc:
                        raise ToolError(str(exc)) from None
                    except AppError as exc:
                        raise ToolError(exc.message) from None
                    except SQLAlchemyError:
                        # SQL·파라미터가 담긴 예외 문구를 앱에 넘기지 않는다
                        logger.exception("tool %s failed", fn.__name__)
                        raise ToolError("처리하지 못했습니다. 잠시 뒤에 다시 하세요.") from None
                    ok = True
                    return result
                finally:
                    elapsed = (time.perf_counter() - started) * 1000
                    self.log(fn.__name__, ok, elapsed, target if isinstance(target, str) else None)

            return wrapper

        return decorator
