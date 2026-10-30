"""claude_app 세션(앱 일지·앱 메모)을 무발화 종료·일지 정리가 건드리지 않는다(MA-04)."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.db.models import (
    AppKind,
    ConversationSession,
    ExtractStatus,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.jobs import extract, idle
from app.main import create_app

LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


def _app_session(**kw) -> ConversationSession:
    values = {
        "mode": SessionMode.CLAUDE_APP,
        "started_at": LONG_AGO,
        "ended_at": LONG_AGO,
        "status": SessionStatus.ENDED,
        "title": "산책",
        "summary": "앱이 정리한 요약",
        "checks": [],
        "extract_status": ExtractStatus.DONE,
        "app_kind": AppKind.JOURNAL,
        "app_day": date(2026, 1, 1),
    }
    return ConversationSession(**{**values, **kw})


def test_idle_sweep_and_extraction_skip_app_sessions(make_settings, tmp_path):
    settings = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    app = create_app(settings)
    with TestClient(app):

        async def seed() -> tuple[str, str, str]:
            async with app.state.session_factory() as db:
                journal = _app_session()
                memo = _app_session(title="앱 메모", app_kind=AppKind.MEMO, summary=None)
                # 정리 대기(pending)로 남았더라도 앱 세션은 다시 정리하지 않는다
                stuck = _app_session(
                    title="대기", extract_status=ExtractStatus.PENDING, app_day=date(2026, 1, 2)
                )
                db.add_all([journal, memo, stuck])
                await db.flush()
                db.add(Turn(session_id=journal.id, seq=1, role=TurnRole.USER, text="안녕"))
                await db.commit()
                return journal.id, memo.id, stuck.id

        async def run() -> None:
            journal_id, memo_id, stuck_id = await seed()
            now = datetime.now(UTC) + timedelta(days=30)
            assert await idle.sweep_idle(app, now=now) == []
            assert await extract.run_extraction(app, stuck_id) is None
            async with app.state.session_factory() as db:
                journal = await db.get(ConversationSession, journal_id)
                memo = await db.get(ConversationSession, memo_id)
                stuck = await db.get(ConversationSession, stuck_id)
            assert (journal.status, journal.ended_at) == (SessionStatus.ENDED, LONG_AGO)
            assert journal.summary == "앱이 정리한 요약" and journal.checks == []
            assert memo.extract_status is ExtractStatus.DONE
            assert stuck.summary == "앱이 정리한 요약"

        from anyio.from_thread import start_blocking_portal

        with start_blocking_portal() as portal:
            portal.call(run)
