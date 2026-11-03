"""Claude 구독 사용 한도의 마지막 값(GET /api/usage).

CLI는 턴마다 rate_limit_event로 5시간·7일 한도의 사용률(0~1)과 초기화 시각을 알려 준다
(구독이라 남은 토큰 수는 주지 않는다). 따로 조회하는 방법이 없어 서버가 시작한 뒤
첫 응답 전에는 값이 없다. 메모리에만 두며 서버를 다시 켜면 비어 있다.
"""

import contextlib
import logging
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("trailtalk.llm")

WINDOWS = ("five_hour", "seven_day")


@dataclass(frozen=True)
class UsageWindow:
    utilization: float  # 0~1(쓴 비율)
    resets_at: datetime | None


@dataclass(frozen=True)
class UsageSnapshot:
    status: str | None = None  # allowed·allowed_warning·rejected
    five_hour: UsageWindow | None = None
    seven_day: UsageWindow | None = None
    updated_at: datetime | None = None


def _window(raw: Any) -> UsageWindow | None:
    if not isinstance(raw, dict):
        return None
    utilization = raw.get("utilization")
    if isinstance(utilization, bool) or not isinstance(utilization, int | float):
        return None
    if not math.isfinite(utilization):
        return None
    resets = raw.get("resetsAt")
    resets_at = None
    if not isinstance(resets, bool) and isinstance(resets, int | float):
        with contextlib.suppress(OverflowError, OSError, ValueError):
            resets_at = datetime.fromtimestamp(resets, tz=UTC)
    return UsageWindow(utilization=min(max(float(utilization), 0.0), 1.0), resets_at=resets_at)


class UsageTracker:
    def __init__(self) -> None:
        self.snapshot = UsageSnapshot()

    def update(self, info: dict[str, Any]) -> None:
        """rate_limit_info를 반영한다. 이번 값에 없는 한도는 앞의 값을 둔다."""
        windows = info.get("unifiedWindows")
        windows = windows if isinstance(windows, dict) else {}
        changes: dict[str, Any] = {}
        for name in WINDOWS:
            window = _window(windows.get(name))
            if window is not None:
                changes[name] = window
        status = info.get("status")
        if isinstance(status, str):
            changes["status"] = status
        if not changes:
            logger.debug("사용 한도 이벤트에 읽을 값이 없음")
            return
        self.snapshot = replace(self.snapshot, **changes, updated_at=datetime.now(UTC))
