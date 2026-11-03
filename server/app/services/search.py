"""웹 검색 도구들이 함께 쓰는 값과 도우미(M5-09).

검색 결과 어댑터(naver.py·hasdata.py)는 실패를 SearchError로 통일하고 다시 시도하지 않는다
(응답이 느려진다). 빈 결과·재검색·폴백은 호출하는 도구와 규칙이 맡는다."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

TimeRange = Literal["day", "week", "month"]
ErrorKind = Literal["unavailable", "rate_limited", "timeout", "failed"]


class SearchError(Exception):
    """kind: unavailable(키 없음·키 오류·한도 소진), rate_limited, timeout, failed."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published: date | None
    host: str | None  # 출처로 보일 호스트(www. 뗌). 블로그는 블로거 이름
    source: str | None = None  # 호스트 대신 보일 출처 이름(블로그의 bloggername)
    date_text: str | None = None  # 날짜를 해석하지 못한 원문('12 hours ago' 등, 구글 검색)


def host_of(url: Any) -> str | None:
    """출처로 보일 호스트 이름(www. 뗌). URL이 아니거나 읽을 수 없으면 None."""
    if not isinstance(url, str):
        return None
    try:
        host = urlsplit(url).hostname  # "http://[::1" 같은 값은 ValueError
    except ValueError:
        return None
    if not host:
        return None
    return host.removeprefix("www.") or None  # "www." 뿐이면 None


_URL_MAX = 2000


def safe_url(url: str) -> bool:
    """http(s) 주소이고 공백·제어·서식 문자가 없다. 아니면 그 결과를 버린다(목록 형식 위조 방지)."""
    return (
        url.startswith(("http://", "https://"))
        and len(url) <= _URL_MAX
        and not any(c.isspace() or unicodedata.category(c) in {"Cc", "Cf"} for c in url)
    )


_SOURCE_SUFFIX = re.compile(r"\s[-|–—]\s[^-|–—]{2,40}$")
_NON_WORD = re.compile(r"[^\w]+")


def title_key(title: str, host: str | None = None) -> str:
    """같은 기사를 여러 매체가 실은 중복을 알아보는 키: 끝의 ' - 매체명'을 떼고 글자만 남긴다.

    접미사가 매체명으로 보일 때만(그 결과의 호스트에 접미사의 낱말이 들어 있을 때) 뗀다. 제목
    안의 ' - '(예: 'Dow rises - oil jumps')를 매체명으로 오해해 다른 기사를 같은 기사로 보지
    않게 한다."""
    text = title.strip()
    match = _SOURCE_SUFFIX.search(text)
    if match and host:
        host_key = _NON_WORD.sub("", host.casefold())
        words = [w for w in _NON_WORD.split(match.group(0).casefold()) if len(w) >= 3]
        if any(w in host_key for w in words):
            text = text[: match.start()]
    return _NON_WORD.sub("", text.casefold())


def dedupe_by_title(results: list[SearchResult]) -> list[SearchResult]:
    """제목이 같은 결과는 먼저 나온 것만 남긴다(순서 유지). 제목이 비면 중복으로 보지 않는다."""
    seen: set[str] = set()
    kept = []
    for result in results:
        key = title_key(result.title, result.host)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(result)
    return kept


def clean_text(value: Any) -> str:
    """한 줄로 정리한다: 제어·서식 문자(줄바꿈 위조, 방향 전환 문자 등)를 지우고 공백을 접는다."""
    if not isinstance(value, str):
        return ""
    kept = (c for c in value if c.isspace() or unicodedata.category(c) not in {"Cc", "Cf"})
    return " ".join("".join(kept).split())
