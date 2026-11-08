"""web_fetch 서비스: 사설 대역 차단·재바인딩 방어·리다이렉트 검사·한도·본문 추출.

실제 인터넷 요청은 하지 않는다. 이름 해석은 가짜 리졸버, 서버는 MockTransport다."""

import asyncio
import logging

import httpx2
import pytest

from app.services.web_fetch import (
    FetchError,
    WebFetcher,
    extract_text,
    is_blocked_ip,
    system_resolver,
)

PUBLIC = "93.184.216.34"
OTHER_PUBLIC = "8.8.4.4"


class Resolver:
    """이름 → 주소 목록. 값이 리스트의 리스트면 호출할 때마다 차례로 돌려준다(재바인딩 시험)."""

    def __init__(self, table):
        self.table = table
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host, port):
        self.calls.append((host, port))
        value = self.table.get(host)
        if value is None:
            raise OSError("not found")
        if value and isinstance(value[0], list):
            return value[min(len(self.calls_for(host)) - 1, len(value) - 1)]
        return value

    def calls_for(self, host):
        return [c for c in self.calls if c[0] == host]


def make(handler, resolver=None, **kw):
    values = {"timeout_s": 5, "max_bytes": 100_000, "max_redirects": 4, "max_chars": 8_000}
    values.update(kw)
    return WebFetcher(
        resolver=resolver or Resolver({"example.test": [PUBLIC], "other.test": [OTHER_PUBLIC]}),
        transport=httpx2.MockTransport(handler),
        **values,
    )


def html(body, status=200, ctype="text/html; charset=utf-8", **headers):
    return httpx2.Response(
        status, content=body.encode() if isinstance(body, str) else body,
        headers={"content-type": ctype, **headers},
    )  # fmt: skip


def never(request):
    raise AssertionError(f"연결하면 안 된다: {request.url}")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "127.1.2.3", "10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.1",
        "192.168.0.1", "192.168.255.254", "169.254.169.254", "169.254.0.1", "0.0.0.0",
        "100.64.0.1", "224.0.0.1", "255.255.255.255", "240.0.0.1", "192.0.0.1", "198.18.0.1",
        "::1", "::", "fc00::1", "fd12:3456::1", "fe80::1", "ff02::1", "::ffff:127.0.0.1",
        "::ffff:10.0.0.1", "::ffff:169.254.169.254", "2002:7f00:1::", "64:ff9b::a00:1",
        "::127.0.0.1", "fe80::1%en0", "not-an-ip", "",
        "fec0::1", "192.88.99.1",  # site-local(폐지), 6to4 릴레이
    ],
)  # fmt: skip
def test_blocked_ips(ip):
    assert is_blocked_ip(ip)


@pytest.mark.parametrize(
    "ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "172.15.0.1", "172.32.0.1", "2606:4700::1111"]
)
def test_public_ips_are_allowed(ip):
    assert not is_blocked_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://LOCALHOST:8000/x",
        "http://foo.localhost/",
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/internal/mcp/",
        "http://10.1.2.3/",
        "http://192.168.0.10/admin",
        "http://172.16.5.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::1]:8000/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://0.0.0.0/",
        "http://localhost./",
    ],
)
async def test_internal_addresses_are_refused_without_connecting(url):
    with pytest.raises(FetchError) as exc:
        await make(never).fetch(url)
    assert exc.value.code == "blocked_address"


@pytest.mark.parametrize(
    "name", ["private.test", "loopback.test", "metadata.test", "v6.test", "mapped.test"]
)
async def test_names_resolving_to_internal_addresses_are_refused(name):
    resolver = Resolver(
        {
            "private.test": ["10.0.0.5"],
            "loopback.test": ["127.0.0.1"],
            "metadata.test": ["169.254.169.254"],
            "v6.test": ["::1"],
            "mapped.test": ["::ffff:192.168.1.1"],
        }
    )
    with pytest.raises(FetchError) as exc:
        await make(never, resolver).fetch(f"http://{name}/")
    assert exc.value.code == "blocked_address"


async def test_any_blocked_address_among_several_refuses():
    resolver = Resolver({"mixed.test": [PUBLIC, "10.0.0.1"]})
    with pytest.raises(FetchError) as exc:
        await make(never, resolver).fetch("http://mixed.test/")
    assert exc.value.code == "blocked_address"


async def test_numeric_host_forms_are_refused_through_resolution():
    """2130706433·0x7f.1 같은 변형은 시스템 해석기가 127.0.0.1로 푼다(로컬 해석만)."""
    fetcher = WebFetcher(
        timeout_s=5, max_bytes=1000, max_redirects=2, max_chars=1000,
        resolver=system_resolver, transport=httpx2.MockTransport(never),
    )  # fmt: skip
    for host in ("2130706433", "0x7f.1", "127.1"):
        with pytest.raises(FetchError) as exc:
            await fetcher.fetch(f"http://{host}/")
        assert exc.value.code in {"blocked_address", "resolve_failed"}, host


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.test/x",
        "gopher://example.test/",
        "javascript:alert(1)",
        "//example.test/x",
        "example.test/x",
        "http://",
        "http://user:pass@example.test/",
        "http://user@example.test/",
        "http://example.test:99999/",
        "",
    ],
)
async def test_only_plain_http_urls_are_accepted(url):
    with pytest.raises(FetchError) as exc:
        await make(never).fetch(url)
    assert exc.value.code == "invalid_url"


async def test_unresolvable_name():
    with pytest.raises(FetchError) as exc:
        await make(never).fetch("http://nowhere.test/")
    assert exc.value.code == "resolve_failed"


async def test_connects_to_the_checked_ip_with_original_host_and_sni():
    """재바인딩 방어: 해석은 한 번이고 연결은 확인한 IP로, Host·SNI는 원래 이름으로 한다."""
    seen = {}

    def handler(request):
        seen["host"] = request.url.host
        seen["port"] = request.url.port
        seen["header"] = request.headers["host"]
        seen["sni"] = request.extensions["sni_hostname"]
        seen["target"] = request.url.raw_path
        return html("<p>안녕</p>")

    resolver = Resolver({"example.test": [PUBLIC]})
    result = await make(handler, resolver).fetch("https://Example.test/a/b?x=1&y=한글")
    assert seen["host"] == PUBLIC and seen["port"] in (None, 443)  # 기본 포트는 None
    assert seen["header"] == "example.test" and seen["sni"] == "example.test"
    assert seen["target"].startswith(b"/a/b?x=1&y=")
    assert resolver.calls == [("example.test", 443)]
    assert result.code == 200 and result.text == "안녕"
    assert result.url == "https://Example.test/a/b?x=1&y=한글" and result.host == "example.test"


async def test_nondefault_port_goes_in_the_host_header():
    seen = {}

    def handler(request):
        seen["header"] = request.headers["host"]
        seen["port"] = request.url.port
        return html("x")

    await make(handler).fetch("http://example.test:8080/")
    assert seen == {"header": "example.test:8080", "port": 8080}


async def test_dns_rebinding_second_answer_is_never_used():
    """이름이 처음엔 공인 IP, 두 번째엔 사설 IP를 줘도 첫 해석으로 확인한 IP로만 연결한다."""
    resolver = Resolver({"evil.test": [[PUBLIC], ["127.0.0.1"]]})
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return html("ok")

    result = await make(handler, resolver).fetch("http://evil.test/")
    assert hosts == [PUBLIC] and result.text == "ok"
    assert len(resolver.calls) == 1  # 한 번만 해석한다


async def test_rebinding_on_a_redirect_hop_is_refused():
    """리다이렉트로 같은 이름을 다시 해석하는 단계에서 사설 IP가 나오면 거절한다."""
    resolver = Resolver({"evil.test": [[PUBLIC], ["10.0.0.9"]]})
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx2.Response(302, headers={"location": "http://evil.test/second"})

    with pytest.raises(FetchError) as exc:
        await make(handler, resolver).fetch("http://evil.test/first")
    assert exc.value.code == "blocked_address" and hosts == [PUBLIC]


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/",
        "http://localhost:8000/internal/mcp/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://private.test/",
        "file:///etc/passwd",
    ],
)
async def test_redirect_into_internal_network_is_refused(location):
    resolver = Resolver({"example.test": [PUBLIC], "private.test": ["192.168.1.1"]})
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == PUBLIC:
            return httpx2.Response(302, headers={"location": location})
        raise AssertionError("두 번째 단계에 연결하면 안 된다")

    with pytest.raises(FetchError) as exc:
        await make(handler, resolver).fetch("http://example.test/")
    assert exc.value.code in {"blocked_address", "invalid_url"} and hosts == [PUBLIC]


async def test_follows_public_redirects_including_relative_and_reports_final_url():
    def handler(request):
        if request.headers["host"] == "example.test" and request.url.path == "/old":
            return httpx2.Response(301, headers={"location": "/new"})
        if request.headers["host"] == "example.test" and request.url.path == "/new":
            return httpx2.Response(307, headers={"location": "https://other.test/final"})
        assert request.headers["host"] == "other.test" and request.url.host == OTHER_PUBLIC
        return html("<h1>끝</h1>")

    result = await make(handler).fetch("http://example.test/old")
    assert result.url == "https://other.test/final" and result.host == "other.test"
    assert result.text == "끝"


async def test_too_many_redirects():
    def handler(request):
        return httpx2.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchError) as exc:
        await make(handler, max_redirects=3).fetch("http://example.test/")
    assert exc.value.code == "too_many_redirects"


async def test_redirect_count_boundary():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) <= 2:
            return httpx2.Response(302, headers={"location": f"/{len(calls)}"})
        return html("도착")

    assert (await make(handler, max_redirects=2).fetch("http://example.test/")).text == "도착"


async def test_redirect_without_location_is_returned_as_is():
    result = await make(lambda r: httpx2.Response(302)).fetch("http://example.test/")
    assert result.code == 302 and result.text == ""


async def test_environment_proxy_is_not_used(monkeypatch):
    """프록시가 검사를 우회하지 못하게 환경 변수 프록시를 쓰지 않는다."""
    created = {}
    real = httpx2.AsyncClient

    class Spy(real):
        def __init__(self, *args, **kwargs):
            created.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", Spy)
    await make(lambda r: html("x")).fetch("http://example.test/")
    assert created["trust_env"] is False and created["follow_redirects"] is False


async def test_extracts_text_from_html_without_scripts_and_styles(caplog):
    page = """<!doctype html><html><head><title>제목 입니다</title>
    <style>body { color: red }</style><script>var secret = "SCRIPT";</script></head>
    <body><nav>메뉴</nav><h1>큰   제목</h1><p>첫 문단 &amp; <b>굵게</b></p>
    <script>alert("SCRIPT2")</script><noscript>NOSCRIPT</noscript>
    <ul><li>하나</li><li>둘</li></ul><!-- 주석 --><p>마지막&nbsp;문단</p></body></html>"""
    with caplog.at_level(logging.DEBUG, logger="trailtalk.web_fetch"):
        result = await make(lambda r: html(page)).fetch("http://example.test/p")
    assert (
        result.text == "제목 입니다\n\n메뉴\n\n큰 제목\n\n첫 문단 & 굵게\n\n하나\n둘\n\n마지막 문단"
    )
    assert "SCRIPT" not in result.text and "color" not in result.text
    assert "example.test" not in caplog.text and "큰 제목" not in caplog.text
    assert "web_fetch 완료 code=200" in caplog.text


def test_extract_text_plain_and_broken_html():
    assert extract_text("  줄1 \n\n\n\n줄2\x07 ", "text/plain") == "줄1\n\n줄2"
    assert extract_text('{"a": 1}', "application/json") == '{"a": 1}'
    assert extract_text("<p>열린 태그 <b>굵게", "text/html") == "열린 태그 굵게"
    assert extract_text("<html><body>타입 없음</body></html>", "text/plain") == "타입 없음"


async def test_decodes_declared_charset_and_falls_back_to_cp949():
    euckr = "<p>한글 본문</p>".encode("euc-kr")
    result = await make(lambda r: html(euckr, ctype="text/html; charset=euc-kr")).fetch(
        "http://example.test/"
    )
    assert result.text == "한글 본문"
    result = await make(lambda r: html(euckr, ctype="text/html")).fetch("http://example.test/")
    assert result.text == "한글 본문"  # 선언이 없으면 utf-8 실패 뒤 cp949
    result = await make(lambda r: html(b"<p>\xff\xfe</p>", ctype="text/html; charset=nope")).fetch(
        "http://example.test/"
    )
    assert result.code == 200 and "<" not in result.text


async def test_http_errors_report_the_status_without_text():
    for status in (404, 403, 500):
        result = await make(lambda r, s=status: html("<p>본문</p>", status=s)).fetch(
            "http://example.test/missing"
        )
        assert (result.code, result.bytes, result.text) == (status, 0, "")


async def test_unsupported_content_type():
    for ctype in ("application/pdf", "image/png", "application/octet-stream"):
        with pytest.raises(FetchError) as exc:
            await make(lambda r, c=ctype: html(b"%PDF", ctype=c)).fetch("http://example.test/")
        assert exc.value.code == "unsupported_content"


async def test_body_size_limit_truncates_and_reports_bytes():
    body = "<p>" + "가나다라" * 5000 + "</p>"  # 약 60KB
    result = await make(lambda r: html(body), max_bytes=1000, max_chars=100_000).fetch(
        "http://example.test/"
    )
    assert result.bytes == 1000 and result.truncated
    assert 0 < len(result.text) < 400


async def test_streams_only_up_to_the_limit():
    """끝없는 본문도 한도까지만 읽고 멈춘다."""
    read = 0

    class Endless(httpx2.AsyncByteStream):
        async def __aiter__(self):
            nonlocal read
            for _ in range(10_000):
                read += 1
                yield b"a" * 1000

    def handler(request):
        return httpx2.Response(200, headers={"content-type": "text/plain"}, stream=Endless())

    result = await make(handler, max_bytes=5000).fetch("http://example.test/")
    assert result.bytes == 5000 and result.truncated and read < 20


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (httpx2.ReadError("reset"), "read_failed"),
        (httpx2.RemoteProtocolError("closed early"), "read_failed"),
        (httpx2.DecodingError("bad gzip"), "read_failed"),
        (httpx2.ReadTimeout("slow body"), "timeout"),
    ],
)
async def test_errors_while_reading_the_body_become_fetch_errors(raised, code):
    """헤더는 받았는데 본문을 읽다 끊기거나 느리거나 해제에 실패해도 FetchError 코드로 올린다."""

    class Broken(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield "<p>앞부분</p>".encode()
            raise raised

    def handler(request):
        return httpx2.Response(200, headers={"content-type": "text/html"}, stream=Broken())

    with pytest.raises(FetchError) as exc:
        await make(handler).fetch("http://example.test/")
    assert exc.value.code == code


async def test_char_limit_truncates():
    result = await make(lambda r: html("<p>" + "가" * 500 + "</p>"), max_chars=100).fetch(
        "http://example.test/"
    )
    assert result.text == "가" * 100 and result.truncated


async def test_small_page_is_not_marked_truncated():
    result = await make(lambda r: html("<p>짧음</p>")).fetch("http://example.test/")
    assert not result.truncated and result.bytes == len(b"<p>\xec\xa7\xa7\xec\x9d\x8c</p>")


async def test_timeout_covers_a_slow_server():
    async def slow(request):
        await asyncio.sleep(5)
        return html("늦음")

    with pytest.raises(FetchError) as exc:
        await make(slow, timeout_s=0.05).fetch("http://example.test/")
    assert exc.value.code == "timeout"


async def test_transport_timeout_and_connect_errors():
    def read_timeout(request):
        raise httpx2.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(FetchError) as exc:
        await make(read_timeout).fetch("http://example.test/")
    assert exc.value.code == "timeout"
    with pytest.raises(FetchError) as exc:
        await make(refused).fetch("http://example.test/")
    assert exc.value.code == "connect_failed"


def test_from_settings():
    from app.config import Settings

    fetcher = WebFetcher.from_settings(
        Settings(_env_file=None, web_fetch_timeout_s=3, web_fetch_max_bytes=77)
    )
    assert fetcher._timeout_s == 3 and fetcher._max_bytes == 77 and fetcher._max_redirects == 4


async def test_unicode_host_is_converted_to_punycode_for_resolver_host_and_sni():
    """한글·일본어 도메인은 IDNA로 바꿔 해석하고 Host·SNI에도 쓴다(UnicodeEncodeError 금지)."""
    seen = {}

    def handler(request):
        seen["host"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return html("<p>안녕</p>")

    punycode = "xn--r8jz45g.jp"  # 例え.jp
    resolver = Resolver({punycode: [PUBLIC]})
    result = await make(handler, resolver).fetch("http://例え.jp/")
    assert result.code == 200 and "안녕" in result.text
    assert seen == {"host": punycode, "sni": punycode}
    assert resolver.calls_for(punycode)


async def test_host_that_cannot_be_converted_to_idna_is_an_invalid_url():
    with pytest.raises(FetchError) as info:
        await make(never).fetch("http://" + "가" * 64 + ".example/")  # 한 레이블이 63자를 넘는다
    assert info.value.code == "invalid_url"


async def test_requests_ask_for_uncompressed_bodies():
    """압축 폭탄이 풀리며 메모리를 채우지 않도록 압축하지 않은 본문만 요청한다."""
    seen = {}

    def handler(request):
        seen["encoding"] = request.headers.get("accept-encoding")
        return html("ok")

    await make(handler).fetch("http://example.test/")
    assert seen["encoding"] == "identity"
