"""종료 API와 턴의 경합(M1에서 있던 결함): 종료가 CLI를 닫은 직후 이미 시작 검사를 통과한 턴이
CLI를 다시 띄우면, 그 턴이 끝나기를 종료 API가 기다리느라 오래 걸렸다(부하가 있을 때 드러났다)."""

# ruff: noqa: F401, F811  (가져온 픽스처 이름을 시험 인자로 다시 쓴다)

import pytest

from app.db.models import SessionStatus
from app.services import conversation
from tests.test_sessions import api, home, start, turn


def test_turn_that_reopened_the_cli_after_end_closes_it_and_reports_session_ended(api, monkeypatch):
    session_id = start(api)["session"]["id"]
    real_open_llm = conversation.open_llm

    async def racing(app, db, convo):
        session = await real_open_llm(app, db, convo)
        # 종료 API가 상태를 끝남으로 바꾼 직후, 이 턴이 CLI를 (다시) 띄운 상황
        await conversation._set_status(db, convo.id, SessionStatus.ENDED, None, None)
        await db.commit()
        return session

    monkeypatch.setattr(conversation, "open_llm", racing)
    events = turn(api, session_id, "안녕")
    assert events[-1].type == "error" and events[-1].code == "session_ended"
    assert not [e for e in events if e.type == "sentence"]  # 끝난 대화에는 답하지 않는다
    assert api.app.state.llm.active_count == 0  # 다시 띄운 CLI를 남기지 않는다


@pytest.mark.parametrize("repeat", range(3))
def test_end_during_turn_is_fast_even_when_it_lands_before_the_cli_send(api, repeat):
    """턴 잠금을 잡자마자 종료해도(CLI 기동 전후 어느 때든) 종료가 5초 안에 끝난다."""
    import threading
    import time

    session_id = start(api)["session"]["id"]
    worker = threading.Thread(target=lambda: turn(api, session_id, "__hang_until_interrupt__"))
    worker.start()
    runtime = api.app.state.runtimes.get(session_id)
    deadline = time.monotonic() + 5
    while not runtime.turn_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.001)
    started = time.monotonic()
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    worker.join(10)
    assert time.monotonic() - started < 5
    assert api.app.state.llm.active_count == 0
