"""GET /api/usage: Claude 구독 사용 한도(app/llm/usage.py). 화면 위 남은 토큰 막대가 읽는다."""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.llm.usage import UsageWindow

router = APIRouter(tags=["usage"])


class UsageWindowOut(BaseModel):
    utilization: float  # 0~1(쓴 비율)
    resets_at: datetime | None


class UsageOut(BaseModel):
    status: str | None
    five_hour: UsageWindowOut | None
    seven_day: UsageWindowOut | None
    updated_at: datetime | None


def _window(window: UsageWindow | None) -> UsageWindowOut | None:
    if window is None:
        return None
    return UsageWindowOut(utilization=window.utilization, resets_at=window.resets_at)


@router.get("/usage")
async def get_usage(request: Request) -> UsageOut:
    snapshot = request.app.state.usage.snapshot
    return UsageOut(
        status=snapshot.status,
        five_hour=_window(snapshot.five_hour),
        seven_day=_window(snapshot.seven_day),
        updated_at=snapshot.updated_at,
    )
