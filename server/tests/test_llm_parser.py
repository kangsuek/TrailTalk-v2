"""CLI stream-json 녹화(tests/fixtures/claude_cli)를 LlmEvent로 바꾸는 파서."""

from pathlib import Path

import pytest

from app.llm.events import (
    TextDelta,
    ToolCalled,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnStarted,
)
from app.llm.parser import StreamJsonParser, _tool_summary

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"
KNOWN_EVENTS = (TurnStarted, TextDelta, ToolStarted, ToolCalled, ToolFinished, TurnFinished)


def parse(name: str) -> list:
    parser = StreamJsonParser()
    return [
        e
        for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()
        for e in parser.feed(line)
    ]


def split_turns(events: list) -> list[list]:
    turns, current = [], []
    for event in events:
        current.append(event)
        if isinstance(event, TurnFinished):
            turns.append(current)
            current = []
    return turns


def text_of(turn: list) -> str:
    return "".join(e.text for e in turn if isinstance(e, TextDelta))


def test_multiturn_text_matches_result():
    turns = split_turns(parse("multiturn"))
    assert len(turns) == 3
    for turn in turns:
        assert isinstance(turn[0], TurnStarted) and turn[0].cli_session_id
        finished = turn[-1]
        assert not finished.is_error and not finished.interrupted
        assert text_of(turn) == finished.text
    assert turns[2][-1].text == "사과와 바나나입니다."


def test_rate_limit_events_are_dropped_until_the_usage_bar():
    """사용량 막대는 M5. 녹화에는 rate_limit_event가 있지만 이벤트로 새지 않는다."""
    raw = (FIXTURES / "multiturn.jsonl").read_text()
    assert "rate_limit_event" in raw
    assert all(isinstance(e, KNOWN_EVENTS) for e in parse("multiturn"))
    assert StreamJsonParser().feed('{"type": "rate_limit_event", "rate_limit_info": {}}') == []


def test_tool_call_order_and_input():
    turns = split_turns(parse("tool_call"))
    tool_turn = turns[1]
    tool_events = [e for e in tool_turn if isinstance(e, (ToolStarted, ToolCalled, ToolFinished))]
    assert [type(e) for e in tool_events] == [ToolStarted, ToolCalled, ToolFinished]
    started, called, finished = tool_events
    assert started.name == called.name == "mcp__trailtalk__save_note"
    assert started.tool_use_id == called.tool_use_id == finished.tool_use_id
    assert called.input["kind"] == "idea"
    assert finished.summary == {"kind": "result", "result": "저장 완료"}
    assert tool_turn[-1].text.endswith(text_of(tool_turn)[-10:])


def test_unknown_tool_result_has_no_summary():
    assert _tool_summary({"something": 1}) is None
    assert _tool_summary("text") is None
    # 웹 검색·fetch 결과는 M5에서 요약을 만든다. 그 전에는 요약 없이 지나간다
    assert _tool_summary({"query": "q", "results": []}) is None
    assert _tool_summary({"code": 200, "bytes": 1, "url": "https://a.test"}) is None


def test_mcp_results_keep_result_kind():
    assert _tool_summary({"structuredContent": {"result": "저장 완료"}}) == {
        "kind": "result",
        "result": "저장 완료",
    }
    # 문자열 하나가 아닌 구조는 그대로 둔다
    assert _tool_summary({"structuredContent": {"query": "q", "results": "x"}}) == {
        "kind": "result",
        "result": {"query": "q", "results": "x"},
    }


def test_interrupted_turn():
    turns = split_turns(parse("interrupt"))
    first = turns[0][-1]
    assert first.interrupted and first.is_error
    assert first.error_message is None and first.text == ""
    assert text_of(turns[0])  # 중단 전까지 부분 출력은 있었다
    assert not turns[1][-1].interrupted


def test_error_uses_is_error_not_subtype():
    finished = parse("error_invalid_model")[-1]
    assert finished.is_error and not finished.interrupted
    assert "no-such-model-xyz" in finished.error_message
    assert finished.text == ""


ODD_LINES = [
    "",
    "not json",
    "[1, 2]",
    '{"type": "rate_limit_event"}',
    '{"type": "system", "subtype": "status"}',
    '{"type": "stream_event", "event": {"type": "content_block_delta", '
    '"delta": {"type": "thinking_delta"}}}',
    '{"type": "user", "message": {"content": "plain"}}',
    '{"type": "user", "message": {"content": [{"type": "tool_result"}]}, '
    '"tool_use_result": {"query": "q", "results": ["x", null]}}',
]


@pytest.mark.parametrize("line", ODD_LINES)
def test_odd_lines_do_not_crash(line):
    events = StreamJsonParser().feed(line)
    assert all(not isinstance(e, TextDelta) for e in events)
