"""턴 출처 저장과 인용(M5-10): 검색·읽기 도구를 쓴 답변의 turn.sources, 일지 상세 turns[].sources,
끝난 대화의 일지 정리 인용(summary_cites·citations)."""

import pytest

from tests.test_extract import cli_output
from tests.test_extract_end import home, make, oneshot  # noqa: F401  (fixture)
from tests.test_sessions import start, turn, turns_of


@pytest.fixture
def api(make):  # noqa: F811
    with make() as client:
        yield client


def search_turn(api, session_id: str) -> list:
    return turn(api, session_id, "__play__:web_search")


def test_search_turn_saves_sources_and_shows_hosts_in_detail(api):
    session_id = start(api)["session"]["id"]
    events = search_turn(api, session_id)
    assert events[-1].type == "done"
    reply = turns_of(api, session_id)[2]
    assert [s["url"] for s in reply.sources] == [
        "https://www.github.com/astral-sh/uv/releases",
        "https://docs.astral.sh/uv/",
        "https://blog.example.com/uv",
        "https://fourth.example.org/a",
    ]
    assert reply.sources[0] == {
        "title": "uv 릴리스",
        "url": "https://www.github.com/astral-sh/uv/releases",
        "host": "github.com",
    }
    detail = api.get(f"/api/journal/{session_id}").json()
    by_seq = {t["seq"]: t for t in detail["turns"]}
    assert by_seq[2]["sources"] == [
        "github.com",
        "docs.astral.sh",
        "blog.example.com",
        "fourth.example.org",
    ]
    assert by_seq[1]["sources"] == [] and by_seq[0]["sources"] == []  # 검색하지 않은 턴


def test_turn_without_search_has_no_sources(api):
    session_id = start(api)["session"]["id"]
    turn(api, session_id, "__say__:그냥 대화예요.")
    assert turns_of(api, session_id)[2].sources is None


def test_ended_conversation_cites_only_listed_sources(api, oneshot):  # noqa: F811
    session_id = start(api)["session"]["id"]
    search_turn(api, session_id)
    # 모델이 지어낸 9번은 버려진다. 1·2번은 요약·메모에 남는다
    oneshot(
        cli_output(
            conclusion={"text": "uv 최신 버전을 확인했다.", "sources": [1, 9]},
            findings=[{"text": "문서가 계속 갱신된다.", "sources": [2]}],
            memos=[{"text": "릴리스 노트를 읽어 볼 것", "sources": [1]}],
        )
    )
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    body = api.get(f"/api/journal/{session_id}").json()
    assert body["summary_cites"][:2] == [[1], [2]]
    assert body["citations"] == [
        {"n": 1, "title": "uv 릴리스", "url": "https://www.github.com/astral-sh/uv/releases"},
        {"n": 2, "title": "uv 문서", "url": "https://docs.astral.sh/uv/"},
    ]
    memo = next(n for n in body["notes"] if n["kind"] == "memo")
    assert memo["cites"] == [1]


def test_conversation_without_search_has_empty_citations(api, oneshot):  # noqa: F811
    session_id = start(api)["session"]["id"]
    turn(api, session_id, "__say__:검색 없이 이야기해요.")
    oneshot(cli_output(conclusion={"text": "결론", "sources": [1]}))  # 목록에 없는 번호
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    body = api.get(f"/api/journal/{session_id}").json()
    assert body["citations"] == []
    assert all(cites == [] for cites in body["summary_cites"])
    assert all(n["cites"] == [] for n in body["notes"])
