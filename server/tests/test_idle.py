"""무발화 타임아웃(client-contract 2.10). 시간 경과는 sweep_idle에 now를 넘겨 흉내 낸다."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import ConversationSession, SessionStatus
from app.db.types import utcnow
from app.jobs.idle import sweep_idle
from app.main import create_app
from tests.test_sessions import FAKE_CLI_SESSION_ID, load, session_row, start, turn, turns_of


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def make(fake_cli, home, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")

    def _make():
        client = TestClient(create_app(fake_cli.settings))
        client.fake_cli = fake_cli
        return client

    return _make


def sweep(api, minutes_later: float) -> list[str]:
    now = utcnow() + timedelta(minutes=minutes_later)
    return api.portal.call(sweep_idle, api.app, now)


def test_ends_only_sessions_idle_for_30_minutes(make):
    with make() as api:
        session_id = start(api)["session"]["id"]
        turn(api, session_id, "바나나는?")
        assert sweep(api, 29) == []
        assert session_row(api, session_id).status is SessionStatus.ACTIVE

        assert sweep(api, 31) == [session_id]
        row = session_row(api, session_id)
        assert row.status is SessionStatus.ENDED and row.ended_at is not None
        assert api.app.state.llm.active_count == 0
        assert api.app.state.runtimes.get(session_id) is None
        assert sweep(api, 60) == []  # 이미 끝난 세션은 다시 보지 않는다


def test_idle_end_time_is_last_activity(make):
    """서버가 오래 꺼져 있다 켜져도 끝난 시각은 감시가 돈 때가 아니라 마지막 턴 시각이다."""
    with make() as api:
        session_id = start(api)["session"]["id"]
        turn(api, session_id, "바나나는?")
        last_turn_at = max(t.created_at for t in turns_of(api, session_id))
        assert sweep(api, 3 * 24 * 60) == [session_id]  # 사흘 뒤
        assert session_row(api, session_id).ended_at == last_turn_at


def test_idle_is_measured_from_last_turn_and_includes_paused(make):
    with make() as api:
        session_id = start(api)["session"]["id"]

        async def pause_and_age(db):
            convo = await db.get(ConversationSession, session_id)
            convo.status = SessionStatus.PAUSED
            convo.started_at = utcnow() - timedelta(hours=2)  # 시작은 오래전, 인사말은 방금
            await db.commit()

        load(api, pause_and_age)
        assert sweep(api, 10) == []  # 마지막 턴(인사말) 기준으로는 10분
        assert sweep(api, 31) == [session_id]  # 쉬는 중이어도 끝낸다


def test_turn_in_progress_is_skipped(make):
    with make() as api:
        session_id = start(api)["session"]["id"]
        runtime = api.app.state.runtimes.get(session_id)
        api.portal.call(runtime.turn_lock.acquire)
        try:
            assert sweep(api, 31) == []
        finally:
            runtime.turn_lock.release()
        assert sweep(api, 31) == [session_id]


def test_session_left_before_restart_is_cleaned(make, home):
    with make() as api:
        session_id = start(api)["session"]["id"]
        turn(api, session_id, "바나나는?")
    # 끝내지 않고 서버가 꺼졌다. CLI 기록 파일이 남아 있다
    transcript = home / ".claude" / "projects" / "-tmp-cli" / f"{FAKE_CLI_SESSION_ID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}")
    with make() as api:  # 런타임이 없는 새 서버
        assert sweep(api, 31) == [session_id]
        assert session_row(api, session_id).status is SessionStatus.ENDED
    assert not transcript.exists()  # 남은 CLI 기록 파일도 지운다


def test_one_failure_does_not_block_other_sessions(make, monkeypatch):
    from app.services import conversation

    with make() as api:
        first = start(api)["session"]["id"]
        second = start(api)["session"]["id"]
        original = conversation.end_session

        async def flaky(app, db, convo, **kwargs):
            if convo.id == first:
                await db.get(ConversationSession, convo.id)  # 쿼리 뒤 실패(세션 객체 만료 유발)
                raise RuntimeError("일시 오류")
            await original(app, db, convo, **kwargs)

        monkeypatch.setattr(conversation, "end_session", flaky)
        assert sweep(api, 31) == [second]
        assert session_row(api, first).status is SessionStatus.ACTIVE


def test_session_spoken_to_during_sweep_is_kept(make, monkeypatch):
    from app.jobs import idle

    with make() as api:
        session_id = start(api)["session"]["id"]
        original = idle._idle_sessions
        calls = []

        async def spoken_after_listing(app, cutoff, sid=None):
            calls.append(sid)
            if sid is not None:
                return {}  # 다시 확인하니 그사이 말을 걸었다
            return await original(app, cutoff, sid)

        monkeypatch.setattr(idle, "_idle_sessions", spoken_after_listing)
        assert sweep(api, 31) == []
        assert calls == [None, session_id]
        assert session_row(api, session_id).status is SessionStatus.ACTIVE
