import asyncio
import logging
from datetime import UTC, date, datetime

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.naver import NaverBlogSearch, NaverNewsSearch, parse_post_date, parse_pub_date
from app.services.search import SearchError

CLIENT_ID = "test-client-id-value"
CLIENT_SECRET = "test-client-secret-value"
NOW = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)  # 2026-10-21 10:00 KST


def make_search(
    handler,
    *,
    cls=NaverNewsSearch,
    client_id=CLIENT_ID,
    secret=CLIENT_SECRET,
    max_results=5,
    timeout_s=5,
):
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return cls(
        client,
        client_id=SecretStr(client_id) if client_id else None,
        client_secret=SecretStr(secret) if secret else None,
        base_url="https://naver.test",
        timeout_s=timeout_s,
        max_results=max_results,
        fetch_count=50,
        now=lambda: NOW,
    )


def item(n=1, pub="Wed, 21 Oct 2026 09:42:00 +0900", host="news1.kr", **kw):
    values = {
        "title": f"기사 {n}",
        "originallink": f"https://{host}/a{n}",
        "link": f"https://n.news.naver.com/a{n}",
        "description": f"요약 {n}",
        "pubDate": pub,
    }
    values.update(kw)
    return values


def ok(items):
    return httpx2.Response(200, json={"total": len(items), "items": items})


async def test_request_and_parsing(caplog):
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = request.url
        seen["headers"] = request.headers
        return ok(
            [
                item(
                    1,
                    title="코스피 <b>5700선</b> 회복 &quot;반등&quot;",
                    description="외국인 &amp; 기관<b>매수</b>\n이어져",
                )
            ]
        )

    with caplog.at_level(logging.INFO, logger="trailtalk.search"):
        results = await make_search(handler).search("코스피 마감 시황")

    assert seen["url"].path == "/search/v1/news"
    assert dict(seen["url"].params) == {"query": "코스피 마감 시황", "sort": "sim", "display": "10"}
    assert seen["headers"]["x-ncp-apigw-api-key-id"] == CLIENT_ID
    assert seen["headers"]["x-ncp-apigw-api-key"] == CLIENT_SECRET
    assert "x-naver-client-id" not in seen["headers"]  # 개발자센터 방식 헤더는 보내지 않는다
    [r] = results
    assert r.title == '코스피 5700선 회복 "반등"'
    assert r.snippet == "외국인 & 기관매수 이어져"
    assert r.url == "https://news1.kr/a1"  # 언론사 원문 주소
    assert r.host == "news1.kr" and r.published == date(2026, 10, 21)
    # 키와 검색어는 로그에 남기지 않는다
    assert CLIENT_ID not in caplog.text and CLIENT_SECRET not in caplog.text
    assert "코스피 마감 시황" not in caplog.text and "fetched=1 results=1" in caplog.text


async def test_filtering_uses_date_sort_and_fetches_many():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return ok([])

    await make_search(handler).search("코스피", time_range="week")
    assert seen["params"]["sort"] == "date" and seen["params"]["display"] == "50"
    await make_search(handler).search("코스피", domains=["ytn.co.kr"])
    assert seen["params"]["sort"] == "date" and seen["params"]["display"] == "50"


async def test_site_sends_plain_and_domain_queries_and_merges_newest_first():
    seen = []

    def handler(request):
        q = request.url.params["query"]
        seen.append(q)
        if q.endswith("ytn.co.kr"):  # 도메인을 붙인 검색어: 오래된 기사와 겹치는 기사
            return ok(
                [
                    item(2, host="ytn.co.kr", pub="Tue, 20 Oct 2026 12:00:00 +0900"),
                    item(3, host="ytn.co.kr", pub="Fri, 16 Oct 2026 12:00:00 +0900"),
                ]
            )
        return ok(
            [
                item(1, host="ytn.co.kr", pub="Wed, 21 Oct 2026 09:42:00 +0900"),
                item(2, host="ytn.co.kr", pub="Tue, 20 Oct 2026 12:00:00 +0900"),  # 중복
                item(4, host="mk.co.kr"),  # 다른 매체
            ]
        )

    results = await make_search(handler).search(
        "YTN 증시", domains=["https://www.YTN.co.kr/news", "yna.co.kr"]
    )
    assert sorted(seen) == ["YTN 증시", "YTN 증시 ytn.co.kr"]
    assert [r.title for r in results] == ["기사 1", "기사 2", "기사 3"]  # 최신순, 중복 없음


async def test_site_does_not_repeat_domain_already_in_query_or_without_site():
    seen = []

    def handler(request):
        seen.append(request.url.params["query"])
        return ok([])

    search = make_search(handler)
    await search.search("ytn.co.kr 증시", domains=["ytn.co.kr"])
    await search.search("증시 코스피", time_range="day")
    assert seen == ["ytn.co.kr 증시", "증시 코스피"]


async def test_site_partial_failure_uses_the_other_request():
    def handler(request):
        if request.url.params["query"].endswith("ytn.co.kr"):
            return httpx2.Response(500, json={"errorCode": "SE99", "errorMessage": "x"})
        return ok([item(1, host="ytn.co.kr")])

    results = await make_search(handler).search("YTN 증시", domains=["ytn.co.kr"])
    assert [r.title for r in results] == ["기사 1"]


async def test_site_all_requests_failing_raises_first_error():
    with pytest.raises(SearchError) as exc:
        await make_search(lambda r: httpx2.Response(401, json={})).search(
            "증시", domains=["ytn.co.kr"]
        )
    assert exc.value.kind == "unavailable"


@pytest.mark.parametrize(
    ("time_range", "kept"),
    [
        ("day", [1, 2]),  # 24시간 이내: 10-21 09:42, 10-20 12:00(KST)
        ("week", [1, 2, 3]),
        ("month", [1, 2, 3, 4]),
    ],
)
async def test_time_range_filters_by_pub_date(time_range, kept):
    items = [
        item(1, pub="Wed, 21 Oct 2026 09:42:00 +0900"),
        item(2, pub="Tue, 20 Oct 2026 12:00:00 +0900"),
        item(3, pub="Fri, 16 Oct 2026 12:00:00 +0900"),
        item(4, pub="Sun, 04 Oct 2026 12:00:00 +0900"),
        item(5, pub="Mon, 01 Sep 2026 12:00:00 +0900"),
        item(6, pub="깨진 날짜"),
        item(7, pub=None),
    ]
    results = await make_search(lambda r: ok(items)).search("코스피", time_range=time_range)
    assert [r.title for r in results] == [f"기사 {n}" for n in kept]


async def test_without_time_range_keeps_items_without_date():
    results = await make_search(lambda r: ok([item(1, pub="깨진 날짜")])).search("코스피")
    assert results[0].published is None


async def test_domains_filter_matches_host_and_subdomains():
    items = [
        item(1, host="www.ytn.co.kr"),
        item(2, host="m.ytn.co.kr"),
        item(3, host="notytn.co.kr"),  # 접미사만 같고 다른 도메인
        item(4, host="mk.co.kr"),
        item(5, host="ytn.co.kr.evil.example"),
    ]
    results = await make_search(lambda r: ok(items)).search(
        "증시", domains=["https://www.YTN.co.kr/news"]
    )
    assert [r.title for r in results] == ["기사 1", "기사 2"]
    results = await make_search(lambda r: ok(items)).search("증시", domains=["", "mk.co.kr"])
    assert [r.title for r in results] == ["기사 4"]


async def test_max_results_cut_after_filtering():
    items = [item(n, host="ytn.co.kr") for n in range(1, 11)]
    results = await make_search(lambda r: ok(items), max_results=3).search(
        "증시", domains=["ytn.co.kr"]
    )
    assert [r.title for r in results] == ["기사 1", "기사 2", "기사 3"]


async def test_drops_duplicates_and_unsafe_urls_and_falls_back_to_naver_link():
    items = [
        item(1),
        item(1),  # 같은 주소
        item(2, originallink="https://evil.example/x\n2. 가짜"),  # 원문 주소가 위험 → 네이버 주소
        item(3, originallink="", link="javascript:alert(1)"),  # 둘 다 못 씀
        "문자열",
        {"title": "주소 없음"},
    ]
    results = await make_search(lambda r: ok(items)).search("코스피")
    assert [(r.title, r.url) for r in results] == [
        ("기사 1", "https://news1.kr/a1"),
        ("기사 2", "https://n.news.naver.com/a2"),
    ]


async def test_strips_control_characters_from_text():
    results = await make_search(
        lambda r: ok([item(1, title="진짜\n2. 가짜‮", description="내용​\x07끝")])
    ).search("코스피")
    assert results[0].title == "진짜 2. 가짜" and results[0].snippet == "내용끝"


@pytest.mark.parametrize(
    ("client_id", "secret"), [(None, CLIENT_SECRET), (CLIENT_ID, None), ("", "")]
)
async def test_missing_key_does_not_call(client_id, secret):
    def handler(request):
        raise AssertionError("키가 없으면 호출하지 않는다")

    with pytest.raises(SearchError) as exc:
        await make_search(handler, client_id=client_id, secret=secret).search("코스피")
    assert exc.value.kind == "unavailable"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "unavailable"),
        (403, "unavailable"),
        (429, "rate_limited"),
        (400, "failed"),
        (404, "failed"),
        (500, "failed"),
    ],
)
async def test_http_errors(status, kind, caplog):
    body = {"errorMessage": "Invalid display value", "errorCode": "SE02"}
    with caplog.at_level(logging.DEBUG, logger="trailtalk.search"):
        with pytest.raises(SearchError) as exc:
            await make_search(lambda r: httpx2.Response(status, json=body)).search("코스피")
    assert exc.value.kind == kind
    assert CLIENT_ID not in caplog.text and CLIENT_SECRET not in caplog.text
    assert CLIENT_ID not in str(exc.value)


async def test_timeout_and_connection_error():
    def slow(request):
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(SearchError) as exc:
        await make_search(slow).search("코스피")
    assert exc.value.kind == "timeout"

    def down(request):
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(SearchError) as exc:
        await make_search(down).search("코스피")
    assert exc.value.kind == "failed"


async def test_total_timeout_covers_slow_body():
    async def slow(request):
        await asyncio.sleep(5)
        return ok([])

    with pytest.raises(SearchError) as exc:
        await make_search(slow, timeout_s=0.05).search("코스피")
    assert exc.value.kind == "timeout"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, content=b"not json"),
        httpx2.Response(200, json={"total": 0}),
        httpx2.Response(200, json={"items": "none"}),
        httpx2.Response(200, json=["x"]),
    ],
)
async def test_bad_body(response):
    with pytest.raises(SearchError) as exc:
        await make_search(lambda r: response).search("코스피")
    assert exc.value.kind == "failed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Wed, 21 Oct 2026 09:42:00 +0900", datetime(2026, 10, 21, 0, 42, tzinfo=UTC)),
        ("Wed, 21 Oct 2026 09:42:00 GMT", datetime(2026, 10, 21, 9, 42, tzinfo=UTC)),
        (None, None),
        ("", None),
        ("2026-10-21", None),
        (123, None),
    ],
)
def test_parse_pub_date(value, expected):
    assert parse_pub_date(value) == expected


def test_settings_and_from_settings(tmp_path, monkeypatch):
    for name in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text("NAVER_CLIENT_ID=  id-abc \nNAVER_CLIENT_SECRET=sec-xyz\n", encoding="utf-8")
    settings = Settings(_env_file=path)
    assert settings.naver_client_id.get_secret_value() == "id-abc"
    search = NaverNewsSearch.from_settings(httpx2.AsyncClient(), settings)
    assert search._client_secret.get_secret_value() == "sec-xyz"
    assert search._fetch_count == 50 and search._max_results == 5
    path.write_text("NAVER_CLIENT_ID=   \nNAVER_CLIENT_SECRET=x\n", encoding="utf-8")
    assert Settings(_env_file=path).naver_client_id is None
    path.write_text("", encoding="utf-8")
    assert Settings(_env_file=path).naver_client_secret is None


async def test_time_range_boundary_is_inclusive():
    # NOW(10-21 01:00 UTC)로부터 정확히 24시간 전은 남고, 1초 더 오래되면 빠진다
    items = [
        item(1, pub="Tue, 20 Oct 2026 10:00:00 +0900"),  # 정확히 24시간 전
        item(2, pub="Tue, 20 Oct 2026 09:59:59 +0900"),  # 24시간 1초 전
    ]
    results = await make_search(lambda r: ok(items)).search("코스피", time_range="day")
    assert [r.title for r in results] == ["기사 1"]


def test_parse_pub_date_without_timezone_is_utc():
    assert parse_pub_date("Wed, 21 Oct 2026 09:42:00 -0000") == datetime(
        2026, 10, 21, 9, 42, tzinfo=UTC
    )


async def test_site_partial_failure_other_direction():
    def handler(request):
        if request.url.params["query"].endswith("ytn.co.kr"):
            return ok([item(1, host="ytn.co.kr")])
        return httpx2.Response(500, json={"errorCode": "SE99", "errorMessage": "x"})

    results = await make_search(handler).search("YTN 증시", domains=["ytn.co.kr"])
    assert [r.title for r in results] == ["기사 1"]


@pytest.mark.parametrize(
    "domain", ["ytn.co.kr:443", "https://ytn.co.kr/news?x=1", "YTN.co.kr#top", "user@ytn.co.kr"]
)
async def test_domain_with_port_query_or_fragment_is_normalized(domain):
    results = await make_search(lambda r: ok([item(1, host="ytn.co.kr")])).search(
        "증시", domains=[domain]
    )
    assert [r.title for r in results] == ["기사 1"]


async def test_unexpected_exception_is_not_swallowed():
    def handler(request):
        if request.url.params["query"].endswith("ytn.co.kr"):
            raise RuntimeError("버그")
        return ok([item(1, host="ytn.co.kr")])

    with pytest.raises(RuntimeError):
        await make_search(handler).search("YTN 증시", domains=["ytn.co.kr"])


async def test_blank_secret_value_does_not_call():
    def handler(request):
        raise AssertionError("키가 비어 있으면 호출하지 않는다")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    search = NaverNewsSearch(
        client,
        client_id=SecretStr(""),
        client_secret=SecretStr(CLIENT_SECRET),
        base_url="https://naver.test",
        timeout_s=5,
        max_results=5,
        fetch_count=50,
    )
    with pytest.raises(SearchError) as exc:
        await search.search("코스피")
    assert exc.value.kind == "unavailable"


async def test_escaped_tags_in_text_are_removed():
    results = await make_search(
        lambda r: ok([item(1, title="&lt;b&gt;굵게&lt;/b&gt; 제목", description="&#x202E;뒤집힘")])
    ).search("코스피")
    assert results[0].title == "굵게 제목" and results[0].snippet == "뒤집힘"


async def test_duplicate_titles_dropped_but_site_filter_runs_first():
    items = [
        item(1, host="mk.co.kr", title="엔비디아, 보증 221조 <b>공개</b>"),
        item(2, host="ytn.co.kr", title="엔비디아 보증 221조 공개"),  # 지정한 매체의 같은 제목
        item(3, host="news1.kr", title="엔비디아, 보증 221조 공개"),
        item(4, host="news1.kr", title="다른 소식"),
    ]
    results = await make_search(lambda r: ok(items)).search("엔비디아")
    assert [r.title for r in results] == ["엔비디아, 보증 221조 공개", "다른 소식"]
    # 매체를 지정하면 그 매체 기사가 다른 매체와 제목이 같아도 남는다
    results = await make_search(lambda r: ok(items)).search("엔비디아", domains=["ytn.co.kr"])
    assert [r.host for r in results] == ["ytn.co.kr"]


# 블로그 검색(search_naver_blog)


def post(n=1, date="20261021", name="산책러", **kw):
    values = {
        "title": f"<b>제주</b> 후기 {n}",
        "link": f"https://blog.naver.com/u{n}/{n}",
        "description": f"다녀온 <b>이야기</b> {n}",
        "bloggername": name,
        "bloggerlink": f"https://blog.naver.com/u{n}",
        "postdate": date,
    }
    values.update(kw)
    return values


def make_blog(handler, **kw):
    return make_search(handler, cls=NaverBlogSearch, **kw)


async def test_blog_request_and_parsing(caplog):
    seen = {}

    def handler(request):
        seen["url"] = request.url
        seen["headers"] = request.headers
        return ok([post(1)])

    with caplog.at_level(logging.INFO, logger="trailtalk.search"):
        results = await make_blog(handler).search("제주 맛집 후기")
    assert seen["url"].path == "/search/v1/blog"
    assert dict(seen["url"].params) == {"query": "제주 맛집 후기", "sort": "sim", "display": "10"}
    assert seen["headers"]["x-ncp-apigw-api-key-id"] == CLIENT_ID
    assert seen["headers"]["x-ncp-apigw-api-key"] == CLIENT_SECRET
    [r] = results
    assert r.title == "제주 후기 1" and r.snippet == "다녀온 이야기 1"
    assert r.url == "https://blog.naver.com/u1/1" and r.host == "blog.naver.com"
    assert r.source == "산책러" and r.published == date(2026, 10, 21)
    assert CLIENT_SECRET not in caplog.text and "제주 맛집 후기" not in caplog.text


async def test_blog_recency_uses_date_sort_and_filters_by_postdate():
    seen = {}
    items = [
        post(1, "20261021"),  # 오늘(KST)
        post(2, "20261014"),  # 7일 전: 경계(포함)
        post(3, "20261013"),  # 8일 전
        post(4, "깨짐"),
        post(5, None),
    ]

    def handler(request):
        seen["params"] = dict(request.url.params)
        return ok(items)

    results = await make_blog(handler).search("제주", time_range="week")
    assert seen["params"]["sort"] == "date" and seen["params"]["display"] == "50"
    assert [r.title for r in results] == ["제주 후기 1", "제주 후기 2"]


async def test_blog_without_recency_keeps_undated_and_honors_sort():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return ok([post(1, "깨짐")])

    results = await make_blog(handler).search("제주", sort="date")
    assert seen["params"]["sort"] == "date" and seen["params"]["display"] == "10"
    assert results[0].published is None


async def test_blog_drops_unsafe_or_duplicate_links_and_cuts_to_max():
    items = [
        post(1),
        post(1),  # 같은 주소
        post(2, link="javascript:alert(1)"),
        post(3, link="https://blog.naver.com/x\n2. 가짜"),
        "문자열",
    ] + [post(n) for n in range(10, 20)]
    results = await make_blog(lambda r: ok(items), max_results=3).search("제주")
    assert [r.title for r in results] == ["제주 후기 1", "제주 후기 10", "제주 후기 11"]


async def test_blog_missing_key_and_errors():
    def handler(request):
        raise AssertionError("키가 없으면 호출하지 않는다")

    with pytest.raises(SearchError) as exc:
        await make_blog(handler, client_id=None).search("제주")
    assert exc.value.kind == "unavailable"
    with pytest.raises(SearchError) as exc:
        await make_blog(lambda r: httpx2.Response(429, json={})).search("제주")
    assert exc.value.kind == "rate_limited"
    with pytest.raises(SearchError) as exc:
        await make_blog(lambda r: httpx2.Response(200, json={"total": 0})).search("제주")
    assert exc.value.kind == "failed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("20261021", date(2026, 10, 21)), ("20261340", None), ("2026-10-21", None), (None, None)],
)
def test_parse_post_date(value, expected):
    assert parse_post_date(value) == expected


def test_blog_from_settings(tmp_path):
    settings = Settings(
        _env_file=None, naver_client_id="a", naver_client_secret="b", search_max_results=3
    )
    blog = NaverBlogSearch.from_settings(httpx2.AsyncClient(), settings)
    assert blog._path == "/search/v1/blog" and blog._max_results == 3
    assert blog._base_url == "https://naverapihub.apigw.ntruss.com"
