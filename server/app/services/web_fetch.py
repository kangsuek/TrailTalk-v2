"""web_fetch: 서버가 직접 웹 페이지를 읽는다(M5-11, D7).

CLI 내장 WebFetch는 localhost·사설 대역·메타데이터 주소를 규칙으로 막지 못해(M5-01 ②, docs/
spikes/m5-cli.md) 끄고, 같은 일을 이 모듈이 검사하며 한다.

- http/https만, 주소에 사용자 정보(user:pass@)가 있으면 거절한다.
- 루프백·사설·링크로컬(169.254.x, 메타데이터 포함)·CGNAT·예약·멀티캐스트·미지정 주소와 IPv6 중
  같은 대역(IPv4 매핑·6to4·Teredo·NAT64에 든 IPv4 포함)을 막는다. 이름을 해석한 주소가 하나라도
  막힌 대역이면 거절한다.
- DNS 재바인딩 방어: 이름은 이 모듈이 한 번 해석해 확인한 IP로만 연결한다(URL의 호스트를 IP로
  바꾸고 Host 머리말과 TLS SNI·인증서 검사는 원래 이름으로 둔다).
- 리다이렉트는 따라가되 단계마다 위 검사를 다시 하고 횟수를 제한한다. 환경 변수 프록시는
  쓰지 않는다(프록시가 검사를 우회하지 못하게).
- 전체 시간·받는 본문 크기(압축을 푼 뒤 기준)·모델에 주는 글자 수에 한도를 둔다.

URL·본문은 로그에 남기지 않는다(길이·상태만)."""

import asyncio
import ipaddress
import logging
import socket
import time
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

import httpx2

from app.config import Settings
from app.services.search import host_of

logger = logging.getLogger("trailtalk.web_fetch")

Resolver = Callable[[str, int], Awaitable[list[str]]]

_URL_SAFE = "/%:@!$&'()*+,;=-._~"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_TEXT_TYPES = ("text/", "application/xhtml+xml", "application/json", "application/xml")
_HEADERS = {
    "User-Agent": "TrailTalk-web-fetch/2",
    "Accept": "text/html,text/plain,application/xhtml+xml,application/json;q=0.9,*/*;q=0.1",
}


class FetchError(Exception):
    """code: invalid_url, blocked_address, resolve_failed, too_many_redirects, timeout,
    connect_failed, unsupported_content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchResult:
    url: str  # 마지막으로 읽은 주소(리다이렉트를 따라갔으면 그 주소)
    host: str | None
    code: int  # HTTP 상태. 400 이상이면 읽지 못한 것
    bytes: int  # 받은 본문 크기
    text: str  # 추출한 본문(HTTP 오류면 빈 글)
    truncated: bool  # 크기·글자 수 한도로 잘렸나


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    found = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found += list(ip.teredo)
    packed = ip.packed
    if packed[:12] == bytes.fromhex("0064ff9b0000000000000000"):  # NAT64 64:ff9b::/96
        found.append(ipaddress.IPv4Address(packed[12:]))
    if packed[:12] == bytes(12):  # IPv4 호환(::a.b.c.d)
        found.append(ipaddress.IPv4Address(packed[12:]))
    return found


def is_blocked_ip(value: str) -> bool:
    """내부망·특수 용도 주소인가(읽지 못하는 주소). 해석할 수 없는 값도 막는다."""
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if any(is_blocked_ip(str(v4)) for v4 in _embedded_v4(ip)):
            return True
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _TextExtractor(HTMLParser):
    """태그를 지우고 script·style 등은 통째로 버리며 블록 경계에서 줄을 나눈다."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "object"}
    _LINE = {"br", "li", "tr", "dt", "dd", "hr"}  # 줄바꿈 하나
    _BLOCK = {
        "p",
        "div",
        "ul",
        "ol",
        "table",
        "section",
        "article",
        "header",
        "footer",
        "nav",
        "main",
        "aside",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "blockquote",
        "form",
        "figure",
        "figcaption",
    }  # 빈 줄로 나눈다

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip_depth += 1
        else:
            self._break(tag)

    def _break(self, tag):
        if tag in self._BLOCK:
            self.parts.append("\n\n")
        elif tag in self._LINE:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self._break(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK:  # 줄 단위 태그(li 등)는 시작에서만 줄을 바꾼다
            self._break(tag)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip_depth == 0:
            self.parts.append(data)


def _tidy(text: str) -> str:
    kept = "".join(
        c
        for c in text
        if c in "\n\t " or c.isspace() or unicodedata.category(c) not in {"Cc", "Cf"}
    )
    lines = (" ".join(line.split()) for line in kept.splitlines())
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):  # 빈 줄은 연속으로 두지 않는다
            out.append(line)
    return "\n".join(out).strip()


def extract_text(body: str, content_type: str) -> str:
    """HTML이면 태그·script·style을 지운 본문(제목을 맨 앞에), 아니면 정리한 글 그대로."""
    if "html" not in content_type and not body.lstrip().lower().startswith(("<!doctype", "<html")):
        return _tidy(body)
    parser = _TextExtractor()
    try:
        parser.feed(body)
        parser.close()
    except Exception:  # 깨진 HTML도 가진 만큼은 쓴다
        logger.debug("HTML 해석 중 오류", exc_info=True)
    text = _tidy("".join(parser.parts))
    title = _tidy(parser.title)
    return f"{title}\n\n{text}".strip() if title and title not in text[:300] else text


def _decode(raw: bytes, content_type: str) -> str:
    charset = None
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset":
            charset = value.strip("\"' ").lower()
    for encoding in [charset] if charset else []:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    for encoding in ("utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


class WebFetcher:
    def __init__(
        self,
        *,
        timeout_s: float,
        max_bytes: int,
        max_redirects: int,
        max_chars: int,
        resolver: Resolver = system_resolver,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_chars = max_chars
        self._resolver = resolver
        self._transport = transport  # 시험이 가짜 서버로 바꾼다

    @classmethod
    def from_settings(cls, settings: Settings) -> "WebFetcher":
        return cls(
            timeout_s=settings.web_fetch_timeout_s,
            max_bytes=settings.web_fetch_max_bytes,
            max_redirects=settings.web_fetch_max_redirects,
            max_chars=settings.web_fetch_max_chars,
        )

    async def _check(self, url: str) -> tuple[httpx2.URL, str, str]:
        """주소를 검사하고 (확인한 IP로 바꾼 URL, 원래 호스트, Host 머리말)을 돌려준다."""
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError:
            raise FetchError("invalid_url", "주소 형식이 올바르지 않습니다.") from None
        if parts.scheme not in ("http", "https"):
            raise FetchError("invalid_url", "http 또는 https 주소만 읽을 수 있습니다.")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise FetchError("invalid_url", "주소에 호스트가 없습니다.")
        if parts.username is not None or parts.password is not None:
            raise FetchError("invalid_url", "사용자 정보가 든 주소는 읽을 수 없습니다.")
        if host == "localhost" or host.endswith(".localhost"):
            raise FetchError("blocked_address", "내부 주소는 읽을 수 없습니다.")
        port = port or (443 if parts.scheme == "https" else 80)
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = await self._resolver(host, port)
            except OSError:
                raise FetchError("resolve_failed", "주소를 찾지 못했습니다.") from None
        if not addresses:
            raise FetchError("resolve_failed", "주소를 찾지 못했습니다.")
        if any(is_blocked_ip(a) for a in addresses):
            raise FetchError("blocked_address", "내부 주소는 읽을 수 없습니다.")
        pinned = addresses[0]
        # 비ASCII 글자는 퍼센트 인코딩한다(이미 있는 %XX는 그대로 둔다)
        path = quote(parts.path or "/", safe=_URL_SAFE)
        if parts.query:
            path += "?" + quote(parts.query, safe=_URL_SAFE + "?")
        target = httpx2.URL(scheme=parts.scheme, host=pinned, port=port, raw_path=path.encode())
        default = 443 if parts.scheme == "https" else 80
        host_header = host_for_header(host, parts.port, default)
        return target, host, host_header

    async def fetch(self, url: str) -> FetchResult:
        started = time.monotonic()
        try:
            async with asyncio.timeout(self._timeout_s):
                result = await self._fetch(url)
        except TimeoutError:
            raise FetchError("timeout", "시간이 초과되었습니다.") from None
        logger.info(
            "web_fetch 완료 code=%d bytes=%d chars=%d truncated=%s %dms",
            result.code,
            result.bytes,
            len(result.text),
            result.truncated,
            int((time.monotonic() - started) * 1000),
        )
        return result

    async def _fetch(self, url: str) -> FetchResult:
        current = url.strip()
        async with httpx2.AsyncClient(
            transport=self._transport, trust_env=False, follow_redirects=False
        ) as client:
            for _ in range(self._max_redirects + 1):
                target, host, host_header = await self._check(current)
                request = client.build_request(
                    "GET",
                    target,
                    headers={**_HEADERS, "Host": host_header},
                    extensions={"sni_hostname": host},
                )
                try:
                    response = await client.send(request, stream=True)
                except httpx2.TimeoutException:
                    raise FetchError("timeout", "시간이 초과되었습니다.") from None
                except httpx2.HTTPError:
                    raise FetchError("connect_failed", "연결하지 못했습니다.") from None
                try:
                    location = response.headers.get("location")
                    if response.status_code in _REDIRECT_STATUSES and location:
                        current = urljoin(current, location)
                        continue
                    return await self._read(response, current)
                finally:
                    await response.aclose()
        raise FetchError("too_many_redirects", "리다이렉트가 너무 많습니다.")

    async def _read(self, response: httpx2.Response, url: str) -> FetchResult:
        code = response.status_code
        host = host_of(url)
        if code >= 400:
            return FetchResult(url, host, code, 0, "", False)
        content_type = response.headers.get("content-type", "text/html").lower()
        if not content_type.startswith(_TEXT_TYPES):
            raise FetchError("unsupported_content", "글로 읽을 수 없는 형식입니다.")
        chunks: list[bytes] = []
        size = 0
        truncated = False
        async for chunk in response.aiter_bytes():
            room = self._max_bytes - size
            if len(chunk) > room:
                chunks.append(chunk[:room])
                size += room
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
        text = extract_text(_decode(b"".join(chunks), content_type), content_type)
        if len(text) > self._max_chars:
            text = text[: self._max_chars].rstrip()
            truncated = True
        return FetchResult(url, host, code, size, text, truncated)


def host_for_header(host: str, port: int | None, default: int) -> str:
    name = f"[{host}]" if ":" in host else host
    return name if port is None or port == default else f"{name}:{port}"
