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
from app.llm.parser import StreamJsonParser, _tool_summary, tool_sources

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
    assert tool_turn[-1].text == text_of(tool_turn)  # 도구를 쓴 턴도 최종 글은 델타의 합


def test_unknown_tool_result_has_no_summary():
    assert _tool_summary({"something": 1}) is None
    assert _tool_summary("text") is None
    # 웹 검색·fetch 결과의 요약은 아래 test_web_*_summary가 확인한다
    assert _tool_summary({"query": "q"}) is None
    assert _tool_summary({"code": 200}) is None


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


def test_rate_limit_events_go_to_the_callback_only():
    """한도 이벤트는 턴 이벤트로 새지 않고 콜백으로만 마지막 값이 간다(사용량 막대)."""
    seen: list[dict] = []
    parser = StreamJsonParser(seen.append)
    assert (
        parser.feed('{"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}') == []
    )
    assert parser.feed('{"type": "rate_limit_event", "rate_limit_info": "x"}') == []
    assert seen == [{"status": "allowed"}]


def test_rate_limit_callback_errors_do_not_break_parsing():
    def boom(info: dict) -> None:
        raise RuntimeError("기록 실패")

    parser = StreamJsonParser(boom)
    assert (
        parser.feed('{"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}') == []
    )


def test_builtin_web_search_summary_from_tool_use_result():
    raw = {
        "query": "uv 최신 버전",
        "results": [
            {
                "tool_use_id": "srv1",
                "content": [
                    {"title": "릴리스", "url": "https://www.github.com/astral-sh/uv"},
                    {"title": None, "url": "https://github.com/astral-sh/uv/2"},
                    {"title": "문서", "url": "https://docs.astral.sh/uv/"},
                    {"title": "넷째", "url": "https://fourth.example.org/"},
                    {"title": "깨짐"},
                ],
            },
            "요약 문자열",
        ],
    }
    summary = _tool_summary(raw)
    assert summary["kind"] == "web_search" and summary["query"] == "uv 최신 버전"
    assert [link["url"] for link in summary["links"]][:2] == [
        "https://www.github.com/astral-sh/uv",
        "https://github.com/astral-sh/uv/2",
    ]
    assert summary["links"][1]["title"] is None
    assert summary["sources"] == ["github.com", "docs.astral.sh", "fourth.example.org"]


def test_web_search_links_are_capped_at_ten():
    results = [{"content": [{"title": str(n), "url": f"https://s{n}.test/"} for n in range(15)]}]
    summary = _tool_summary({"query": "q", "results": results})
    assert len(summary["links"]) == 10 and len(summary["sources"]) == 3


def test_search_tool_structured_result_becomes_the_same_web_search_summary():
    structured = {
        "query": "제주 후기",
        "results": [
            {"title": "글", "url": "https://blog.naver.com/u/1", "source": "산책러"},
            {"title": 3, "url": "https://www.example.com/a"},
            {"title": "주소 없음"},
        ],
    }
    assert _tool_summary({"structuredContent": structured}) == {
        "kind": "web_search",
        "query": "제주 후기",
        "links": [
            {"title": "글", "url": "https://blog.naver.com/u/1"},
            {"title": None, "url": "https://www.example.com/a"},
        ],
        "sources": ["blog.naver.com", "example.com"],
    }
    assert _tool_summary({"structuredContent": {"query": "q", "results": []}}) == {
        "kind": "web_search",
        "query": "q",
        "links": [],
        "sources": [],
    }


def test_web_fetch_summary_from_server_tool_and_builtin_event():
    expected = {
        "kind": "web_fetch",
        "code": 200,
        "bytes": 10,
        "url": "https://www.a.test/p",
        "host": "a.test",
    }
    assert _tool_summary({"code": 200, "bytes": 10, "url": "https://www.a.test/p"}) == expected
    assert (
        _tool_summary(
            {
                "structuredContent": {
                    "code": 200,
                    "bytes": 10,
                    "url": "https://www.a.test/p",
                    "host": "a.test",
                }
            }
        )
        == expected
    )
    # 형식이 어긋난 값은 null로 둔다
    odd = _tool_summary({"code": "200", "bytes": True, "url": 5})
    assert odd == {"kind": "web_fetch", "code": None, "bytes": None, "url": None, "host": None}


def test_public_tool_names_merge_search_tools():
    from app.api.events import public_tool_name

    for name in ("search_naver", "search_naver_blog", "search_google", "search_google_detail"):
        assert public_tool_name(f"mcp__trailtalk__{name}") == "web_search"
    assert public_tool_name("WebSearch") == "web_search"
    assert public_tool_name("mcp__trailtalk__web_fetch") == "web_fetch"
    assert public_tool_name("mcp__trailtalk__save_note") == "save_note"
    assert public_tool_name("mcp__maps__search") == "mcp__maps__search"  # 외부 MCP는 그대로


def test_tool_sources_from_search_and_fetch_results():
    search = {
        "query": "q",
        "results": [
            {
                "content": [
                    {"title": "릴리스", "url": "https://www.github.com/a"},
                    {"title": None, "url": "https://docs.astral.sh/uv/"},
                ]
            }
        ],
    }
    assert tool_sources(search) == (
        {"title": "릴리스", "url": "https://www.github.com/a", "host": "github.com"},
        {"title": None, "url": "https://docs.astral.sh/uv/", "host": "docs.astral.sh"},
    )
    structured = {
        "structuredContent": {"query": "q", "results": [{"title": "글", "url": "https://a.test/1"}]}
    }
    assert [s["url"] for s in tool_sources(structured)] == ["https://a.test/1"]
    fetched = {"code": 200, "bytes": 10, "url": "https://www.a.test/p"}
    assert tool_sources(fetched) == (
        {"title": None, "url": "https://www.a.test/p", "host": "a.test"},
    )


def test_tool_sources_skip_failed_fetch_and_other_results():
    assert tool_sources({"code": 404, "bytes": 10, "url": "https://a.test/p"}) == ()
    assert tool_sources({"structuredContent": {"result": "저장 완료"}}) == ()
    assert tool_sources(None) == ()
    assert tool_sources({"query": "q", "results": []}) == ()
