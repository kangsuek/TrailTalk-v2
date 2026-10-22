"""비동기 DB 엔진과 요청별 세션 의존성.

SSE 스트리밍 도중에도 이벤트 루프를 막지 않도록 비동기 세션을 쓴다.
엔진은 앱 시작 때 만들어 app.state에 두고, 종료 때 정리한다.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_for(url: str, *, foreign_keys: bool = True) -> AsyncEngine:
    """foreign_keys=False는 마이그레이션 전용이다(SQLite batch가 테이블을 다시 만들 때
    DROP TABLE이 ON DELETE CASCADE를 일으켜 자식 행이 지워지는 것을 막는다)."""
    parsed = make_url(url)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

    # 연결 끊김 등으로 취소된 작업이 죽은 커넥션을 풀에 남겨도 다음 요청이 새로 연결하도록
    engine = create_async_engine(url, pool_pre_ping=True)
    if is_sqlite and foreign_keys:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """요청마다 세션 하나. 예외가 나면 rollback한다. commit은 서비스 코드에서 명시적으로 한다."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]
"""엔드포인트 인자 타입: `db: DbSession`."""
