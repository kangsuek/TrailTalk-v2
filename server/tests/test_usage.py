"""Claude 구독 사용 한도(app/llm/usage.py, GET /api/usage)."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.llm.usage import UsageTracker
from app.main import create_app
from tests.test_sessions import start, turn


@pytest.fixture
def api(fake_cli, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    with TestClient(create_app(fake_cli.settings)) as client:
        yield client


INFO = {
    "status": "allowed",
    "resetsAt": 1791782400,
    "rateLimitType": "five_hour",
    "unifiedWindows": {
        "five_hour": {"utilization": 0.4, "resetsAt": 1791782400},
        "seven_day": {"utilization": 0.07, "resetsAt": 1792072800},
    },
}


def test_tracker_keeps_last_windows():
    tracker = UsageTracker()
    assert tracker.snapshot.five_hour is None and tracker.snapshot.updated_at is None
    tracker.update(INFO)
    snap = tracker.snapshot
    assert snap.status == "allowed"
    assert snap.five_hour.utilization == 0.4
    assert snap.five_hour.resets_at == datetime.fromtimestamp(1791782400, tz=UTC)
    assert snap.seven_day.utilization == 0.07
    assert snap.updated_at is not None

    # 한도 하나만 온 값: 없는 한도는 앞의 값을 둔다. 사용률은 0~1로 자른다
    tracker.update({"status": "rejected", "unifiedWindows": {"five_hour": {"utilization": 1.3}}})
    snap = tracker.snapshot
    assert snap.status == "rejected"
    assert snap.five_hour.utilization == 1.0 and snap.five_hour.resets_at is None
    assert snap.seven_day.utilization == 0.07


def test_tracker_ignores_unreadable_values():
    tracker = UsageTracker()
    tracker.update({"unifiedWindows": {"five_hour": {"utilization": True}, "seven_day": "x"}})
    tracker.update({"unifiedWindows": [1]})
    tracker.update({"unifiedWindows": {"five_hour": {"utilization": float("nan")}}})
    assert tracker.snapshot.five_hour is None and tracker.snapshot.updated_at is None
    tracker.update({"unifiedWindows": {"five_hour": {"utilization": 0.5, "resetsAt": 10**20}}})
    assert tracker.snapshot.five_hour.utilization == 0.5
    assert tracker.snapshot.five_hour.resets_at is None


def test_usage_api_empty_before_first_turn(client):
    body = client.get("/api/usage").json()
    assert body == {"status": None, "five_hour": None, "seven_day": None, "updated_at": None}


def test_usage_api_after_turn(api):
    session_id = start(api)["session"]["id"]
    turn(api, session_id, "바나나는?")
    body = api.get("/api/usage").json()
    assert body["status"] == "allowed"
    assert body["five_hour"]["utilization"] == 0.4
    assert body["five_hour"]["resets_at"].startswith("2026-")
    assert body["seven_day"]["utilization"] == 0.07
    assert body["updated_at"]
