"""대화 종료와 일지 정리 연결(M2-03): 끝내기 API·끝내기 도구·무발화 종료가 정리를 띄우고, 끝내기
API가 정리를 기다리며, 앱 시작 때 남은 정리를 다시 돌리고 종료 때 멈춘다(client-contract 2.9)."""

import threading
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import ExtractStatus, SessionStatus
from app.db.types import utcnow
from app.jobs.idle import sweep_idle
from app.llm.events import TurnStarted
from app.main import create_app
from tests.test_extract import cli_output, notes_of, oneshot_records, set_session
from tests.test_sessions import hook_llm, session_row, start, turn


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def oneshot(tmp_path, monkeypatch):
    path = tmp_path / "oneshot.jsonl"

    def set_lines(*lines: str) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT", str(path))
    monkeypatch.delenv("FAKE_CLAUDE_ONESHOT_DELAY", raising=False)
    set_lines(cli_output())
    return set_lines


@pytest.fixture
def make(fake_cli, home, oneshot, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")

    def _make(**overrides) -> TestClient:
        client = TestClient(create_app(fake_cli.settings.model_copy(update=overrides)))
        client.fake_cli = fake_cli
        return client

    return _make


@pytest.fixture
def api(make):
    with make() as client:
        yield client


def wait_for(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("시간 안에 조건이 맞지 않았다")


def talk(api) -> str:
    session_id = start(api)["session"]["id"]
    turn(api, session_id, "__say__:쓰레기통 지도 이야기예요.")
    return session_id


def test_end_waits_for_extraction_and_counts_extracted_notes(api):
    session_id = talk(api)
    response = api.post(f"/api/sessions/{session_id}/end")
    assert response.status_code == 200
    body = response.json()
    assert body["journal_status"] == "done"
    assert body["saved"] == {"idea": 1, "todo": 1, "memo": 1}
    assert "아이디어 1개, 할 일 1개, 메모 1개" in body["closing"]
    assert session_row(api, session_id).title == "등산로 쓰레기통 지도 아이디어"


def test_end_answers_pending_when_extraction_is_slow(make, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT_DELAY", "2")
    with make(extract_wait_s=0.2) as api:
        session_id = talk(api)
        started = time.monotonic()
        body = api.post(f"/api/sessions/{session_id}/end").json()
        assert time.monotonic() - started < 2
        assert body["journal_status"] == "pending"
        assert body["saved"] == {"idea": 0, "todo": 0, "memo": 0}
        # 정리는 응답 뒤에도 계속 돌아 끝난다
        wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
        # 다시 불러도 같은 대화이고(멱등) 이제 개수가 늘어 있다
        again = api.post(f"/api/sessions/{session_id}/end").json()
        assert again["journal_status"] == "done"
        assert again["saved"] == {"idea": 1, "todo": 1, "memo": 1}
    assert len(oneshot_records(api.fake_cli)) == 1


def test_failed_extraction_still_ends_session(api, oneshot):
    oneshot("__crash__")
    session_id = talk(api)
    body = api.post(f"/api/sessions/{session_id}/end").json()
    assert body["journal_status"] == "failed"
    assert body["session"]["status"] == "ended"


def test_greeting_only_session_is_done_without_cli(api):
    session_id = start(api)["session"]["id"]
    body = api.post(f"/api/sessions/{session_id}/end").json()
    assert body["journal_status"] == "done"
    assert oneshot_records(api.fake_cli) == []


def test_concurrent_ends_share_one_extraction(make, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT_DELAY", "0.5")
    with make() as api:
        session_id = talk(api)

        results = []

        def end():
            results.append(api.post(f"/api/sessions/{session_id}/end").json()["journal_status"])

        threads = [threading.Thread(target=end) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == ["done", "done", "done"]
        assert len(oneshot_records(api.fake_cli)) == 1


def test_end_tool_starts_extraction(api):
    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.get(session_id)

    def end_during_turn(event):
        if isinstance(event, TurnStarted):
            runtime.requested_status = SessionStatus.ENDED

    hook_llm(api, end_during_turn)
    assert turn(api, session_id, "__say__:오늘은 여기까지요.")[-1].session_status == "ended"
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    # 끝내기 도구 뒤에 클라이언트가 부르는 끝내기 API는 같은 정리 결과를 준다
    assert api.post(f"/api/sessions/{session_id}/end").json()["journal_status"] == "done"
    assert len(oneshot_records(api.fake_cli)) == 1


def test_idle_end_starts_extraction(api):
    session_id = talk(api)
    later = utcnow() + timedelta(seconds=api.app.state.settings.idle_timeout_s + 60)
    assert api.portal.call(sweep_idle, api.app, later) == [session_id]
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    assert len(notes_of(api, session_id)) == 3


def test_pending_extraction_resumes_at_startup(make):
    with make() as api:
        session_id = talk(api)
        # 정리 도중 서버가 꺼진 상태를 만든다(끝났고 pending, 정리 작업은 없다)
        set_session(
            api,
            session_id,
            status=SessionStatus.ENDED,
            ended_at=utcnow(),
            extract_status=ExtractStatus.PENDING,
        )
    with make() as api:
        wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)


def test_shutdown_leaves_running_extraction_pending(make, oneshot):
    oneshot("__hang__")
    with make(extract_wait_s=0.2) as api:
        session_id = talk(api)
        body = api.post(f"/api/sessions/{session_id}/end")
        assert body.status_code == 200
        wait_for(lambda: oneshot_records(api.fake_cli) != [])
        started = time.monotonic()
    assert time.monotonic() - started < 10  # 멈춘 정리를 기다리지 않고 끝난다
    oneshot(cli_output())
    with make() as api:  # 다음 시작 때 다시 정리한다
        wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
