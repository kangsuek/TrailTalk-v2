import asyncio
import logging

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.hasdata import HasDataClient
from app.services.search import SearchError

KEY = "hd-test-key-value"


def make(handler, *, key=KEY, search_timeout_s=5, scrape_timeout_s=5, max_results=5, max_chars=200):
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return HasDataClient(
        client,
        api_key=SecretStr(key) if key else None,
        base_url="https://hasdata.test",
        search_path="/scrape/google-light/serp/",
        scrape_path="/scrape/web/",
        key_header="x-api-key",
        search_timeout_s=search_timeout_s,
        scrape_timeout_s=scrape_timeout_s,
        max_results=max_results,
        detail_max_chars=max_chars,
    )


def organic(n=1, **kw):
    values = {
        "title": f"결과 {n}",
        "link": f"https://www.example{n}.com/p",
        "snippet": f"요약 {n}",
        "date": "12 hours ago",
    }
    values.update(kw)
    return values


def serp(items):
    return httpx2.Response(
        200,
        json={
            "requestMetadata": {"status": "ok"},
            "organicResults": items,
            "relatedSearches": [{"query": "안 쓴다"}],
        },
    )


async def test_search_request_and_parsing(caplog):
    seen = {}

    def handler(request):
        seen["url"] = request.url
        seen["method"] = request.method
        seen["headers"] = request.headers
        return serp([organic(1), organic(2, date=None)])

    with caplog.at_level(logging.DEBUG, logger="trailtalk.search"):
        results = await make(handler).search("Nvidia earnings", gl="us", hl="en", recency="week")
    assert seen["method"] == "GET" and seen["url"].path == "/scrape/google-light/serp/"
    assert dict(seen["url"].params) == {
        "q": "Nvidia earnings",
        "num": "10",
        "gl": "us",
        "hl": "en",
        "tbs": "qdr:w",
    }
    assert seen["headers"]["x-api-key"] == KEY
    assert [(r.title, r.url, r.host) for r in results] == [
        ("결과 1", "https://www.example1.com/p", "example1.com"),
        ("결과 2", "https://www.example2.com/p", "example2.com"),
    ]
    assert results[0].date_text == "12 hours ago" and results[1].date_text is None
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("trailtalk"))
    assert KEY not in ours and "Nvidia earnings" not in ours and "HasData 검색 완료" in ours


@pytest.mark.parametrize(
    ("recency", "tbs"),
    [("day", "qdr:d"), ("week", "qdr:w"), ("month", "qdr:m"), ("year", "qdr:y"), (None, None)],
)
async def test_recency_maps_to_tbs(recency, tbs):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return serp([])

    await make(handler).search("q", recency=recency)
    assert seen["params"].get("tbs") == tbs


async def test_drops_unsafe_duplicate_and_cuts_to_max():
    items = [
        organic(1),
        organic(1),
        organic(2, link="javascript:alert(1)"),
        organic(3, link="https://x.test/a\n2. 가짜"),
        "문자열",
        organic(4, title="진짜\n2. 가짜‮"),
    ] + [organic(n) for n in range(10, 20)]
    results = await make(lambda r: serp(items), max_results=3).search("q")
    assert [r.title for r in results] == ["결과 1", "진짜 2. 가짜", "결과 10"]


async def test_missing_key_does_not_call():
    def handler(request):
        raise AssertionError("키가 없으면 호출하지 않는다")

    for key in (None, ""):
        with pytest.raises(SearchError) as exc:
            await make(handler, key=key).search("q")
        assert exc.value.kind == "unavailable"
    with pytest.raises(SearchError):
        await make(handler, key=None).scrape("https://a.test/")


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "unavailable"), (402, "unavailable"), (403, "unavailable"), (429, "rate_limited"),
     (400, "failed"), (500, "failed")],
)  # fmt: skip
async def test_http_errors_do_not_leak(status, kind, caplog):
    body = {"message": f"bad {KEY} q-secret"}
    with caplog.at_level(logging.DEBUG, logger="trailtalk.search"):
        with pytest.raises(SearchError) as exc:
            await make(lambda r: httpx2.Response(status, json=body)).search("q-secret")
    assert exc.value.kind == kind
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("trailtalk"))
    assert KEY not in ours and "q-secret" not in ours and KEY not in str(exc.value)


async def test_timeout_connection_and_bad_body():
    def slow(request):
        raise httpx2.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx2.ConnectError("down", request=request)

    for handler, kind in ((slow, "timeout"), (down, "failed")):
        with pytest.raises(SearchError) as exc:
            await make(handler).search("q")
        assert exc.value.kind == kind
    for response in (
        httpx2.Response(200, content=b"not json"),
        httpx2.Response(200, json={"requestMetadata": {}}),
        httpx2.Response(200, json={"organicResults": "x"}),
        httpx2.Response(200, json=["x"]),
    ):
        with pytest.raises(SearchError) as exc:
            await make(lambda r, response=response: response).search("q")
        assert exc.value.kind == "failed"


async def test_total_timeout_covers_slow_response():
    async def slow(request):
        await asyncio.sleep(5)
        return serp([])

    with pytest.raises(SearchError) as exc:
        await make(slow, search_timeout_s=0.05).search("q")
    assert exc.value.kind == "timeout"


async def test_calls_are_serialized_and_waiting_counts_toward_the_timeout():
    """무료 요금제(동시 1개): 호출이 겹치지 않고, 앞 호출을 기다린 시간도 제한에 든다."""
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.15)
        active -= 1
        return serp([organic(1)])

    hasdata = make(handler, search_timeout_s=0.2)
    first, second = await asyncio.gather(
        hasdata.search("a"), hasdata.search("b"), return_exceptions=True
    )
    assert peak == 1
    assert not isinstance(first, BaseException)
    # 둘째는 0.15초 기다린 뒤 0.15초 요청이라 0.2초 제한을 넘는다
    assert isinstance(second, SearchError) and second.kind == "timeout"
    # 제한 시간으로 취소된 뒤에도 잠금이 풀려 다음 호출이 된다
    assert (await hasdata.search("c"))[0].title == "결과 1"


async def test_scrape_request_and_markdown_extraction(caplog):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = request.read()
        return httpx2.Response(200, json={"status": 200, "markdown": "# 제목\n\n본문   \n"})

    with caplog.at_level(logging.DEBUG, logger="trailtalk.search"):
        text = await make(handler).scrape("https://news.example/topic?id=1")
    import json

    assert seen["method"] == "POST" and seen["path"] == "/scrape/web/" and seen["key"] == KEY
    body = json.loads(seen["body"])
    assert body["url"] == "https://news.example/topic?id=1"
    assert body["outputFormat"] == ["markdown"] and body["removeBase64Images"] is True
    assert text == "# 제목\n\n본문"
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("trailtalk"))
    assert KEY not in ours and "news.example" not in ours and "HasData 스크래핑 완료" in ours


@pytest.mark.parametrize(
    "payload",
    [{"content": "내용 A"}, {"data": {"markdown": "내용 A"}}, {"content": {"text": "내용 A"}}],
)
async def test_scrape_accepts_common_response_shapes(payload):
    text = await make(lambda r: httpx2.Response(200, json=payload)).scrape("https://a.test/")
    assert text == "내용 A"


async def test_scrape_clips_long_text_and_rejects_empty():
    long = "가" * 500
    text = await make(lambda r: httpx2.Response(200, json={"markdown": long})).scrape(
        "https://a.t/"
    )
    assert text == "가" * 200 + "\n…(이하 생략)"
    for payload in ({"markdown": "  "}, {"status": 200}, ["x"]):
        with pytest.raises(SearchError) as exc:
            await make(lambda r, payload=payload: httpx2.Response(200, json=payload)).scrape(
                "https://a.t/"
            )
        assert exc.value.kind == "failed"


async def test_scrape_accepts_plain_text_markdown_body():
    """실제 HasData(2026-11-04 확인)는 markdown 출력이면 JSON이 아니라 text/plain 본문을 준다."""
    body = "# 제목\n\n본문 내용   \n"
    response = httpx2.Response(
        200, content=body.encode(), headers={"content-type": "text/plain; charset=utf-8"}
    )
    text = await make(lambda r: response).scrape("https://a.test/")
    assert text == "# 제목\n\n본문 내용"
    empty = httpx2.Response(200, content=b"  \n", headers={"content-type": "text/plain"})
    with pytest.raises(SearchError) as exc:
        await make(lambda r: empty).scrape("https://a.test/")
    assert exc.value.kind == "failed"


def test_from_settings():
    settings = Settings(
        _env_file=None,
        hasdata_api_key="  k  ",
        hasdata_base_url="https://other.test/",
        hasdata_key_header="Authorization",
        hasdata_search_timeout_s=3,
    )
    hasdata = HasDataClient.from_settings(httpx2.AsyncClient(), settings)
    assert hasdata._api_key.get_secret_value() == "k"
    assert hasdata._base_url == "https://other.test" and hasdata._key_header == "Authorization"
    assert hasdata._search_timeout_s == 3 and hasdata._max_results == 5
    assert Settings(_env_file=None, hasdata_api_key="   ").hasdata_api_key is None


def test_http_client_loggers_do_not_record_request_urls():
    """httpx2는 INFO에 쿼리스트링(검색어)이 든 주소를 남기므로 서버 로깅 설정이 막는다."""
    from app.request_context import configure_logging

    configure_logging("INFO")
    assert logging.getLogger("httpx2").getEffectiveLevel() >= logging.WARNING
