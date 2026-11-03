"""글 대화 턴의 서버 구간 기록과 검색 턴 분리 보고(M5-16, Spec 5.1, 규약 2.15)."""

import pytest

from app.db.models import TurnLatency
from tests.test_extract_end import home, make, oneshot  # noqa: F401  (fixture)
from tests.test_sessions import start, turn
from tests.test_voice_turn import rows


@pytest.fixture
def api(make):  # noqa: F811
    with make() as client:
        yield client


def test_text_turn_records_server_stages_with_text_mode(api):
    session_id = start(api)["session"]["id"]
    events = turn(api, session_id, "__say__:안녕하세요 좋아요.")
    [row] = rows(api, TurnLatency)
    assert row.turn_id == events[0].turn_id and row.session_id == session_id
    assert row.mode == "text" and row.searched is False
    assert row.first_token_ms is not None and row.done_ms >= row.first_token_ms
    assert row.reply_chars == len(events[-1].text)
    for name in ("upload_ms", "stt_ms", "audio_bytes"):
        assert getattr(row, name) is None


def test_search_turn_is_separated_in_text_summary_and_voice_summary_is_unchanged(api):
    session_id = start(api)["session"]["id"]
    before = api.get("/api/latency").json()
    turn(api, session_id, "__say__:일반 턴이에요.")
    turn(api, session_id, "__play__:web_search")
    assert [r.searched for r in rows(api, TurnLatency)].count(True) == 1
    after = api.get("/api/latency").json()
    assert after["turns"] == before["turns"] == []  # 글 턴은 음성 목록에 섞이지 않는다
    voice = {k: v for k, v in after["summary"].items() if k != "text"}
    assert voice == {k: v for k, v in before["summary"].items() if k != "text"}  # 음성 요약 불변
    assert after["summary"]["count"] == 0 and after["summary"]["search"]["count"] == 0
    text = after["summary"]["text"]
    assert text["count"] == 1 and text["search"]["count"] == 1
    assert text["first_token_ms"]["median"] >= 0 and text["first_token_ms"]["p90"] >= 0
    assert text["search"]["first_token_ms"] is not None
    assert text["search"]["done_ms"] is not None and text["done_ms"] is not None


def test_text_summary_is_empty_without_text_turns(api):
    text = api.get("/api/latency").json()["summary"]["text"]
    assert text == {
        "count": 0,
        "first_token_ms": None,
        "done_ms": None,
        "search": {"count": 0, "first_token_ms": None, "done_ms": None},
    }
