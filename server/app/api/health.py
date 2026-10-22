import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import DbSession
from app.errors import AppError

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    db: Literal["ok"]


logger = logging.getLogger("trailtalk.health")


@router.get("/health")
async def health(db: DbSession) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("DB 상태 확인 실패: %s", type(exc).__name__)
        raise AppError("db_unavailable", "데이터베이스에 연결할 수 없습니다.", 503) from exc
    return HealthResponse(status="ok", db="ok")
