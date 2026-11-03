"""HasData 구글 검색(search_google)·웹 스크래핑(search_google_detail) REST 호출(M5-09).

**주소·인증 머리말·요청 형식은 아직 실제 호출로 확인하지 못한 가정이다**(docs/spikes/m5-search.md:
커넥터가 보여 준 `api.hasdata.com/scrape/google-light/serp/`·`/scrape/web/`, 인증 `x-api-key`).
그래서 기본 주소·경로·머리말 이름은 Settings로 바꿀 수 있고, 시험은 가짜 HTTP 백엔드로만 한다.

무료 요금제는 동시 요청이 1개라 모든 호출을 세마포어로 직렬화한다. 대기 시간도 제한 시간에
포함해, 앞 요청이 느려도 호출자는 정해진 시간 안에 오류를 받고 내장 WebSearch로 폴백한다.
키와 검색어·URL은 로그에 남기지 않는다(길이만)."""

import asyncio
import logging
import time
from typing import Any

import httpx2
from pydantic import SecretStr

from app.config import Settings
from app.services.search import SearchError, SearchResult, clean_text, host_of, safe_url

logger = logging.getLogger("trailtalk.search")

_RECENCY_TBS = {
    "hour": "qdr:h",
    "day": "qdr:d",
    "week": "qdr:w",
    "month": "qdr:m",
    "year": "qdr:y",
}
_MIN_NUM = 10  # 구글 검색 num은 10 이상만 받는다(커넥터 스키마). 모델에는 max_results건만 준다


class HasDataClient:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: SecretStr | None,
        base_url: str,
        search_path: str,
        scrape_path: str,
        key_header: str,
        search_timeout_s: float,
        scrape_timeout_s: float,
        max_results: int,
        detail_max_chars: int,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._search_path = search_path
        self._scrape_path = scrape_path
        self._key_header = key_header
        self._search_timeout_s = search_timeout_s
        self._scrape_timeout_s = scrape_timeout_s
        self._max_results = max_results
        self._detail_max_chars = detail_max_chars
        self._gate = asyncio.Semaphore(1)  # 무료 요금제의 동시 요청 1개

    @classmethod
    def from_settings(cls, client: httpx2.AsyncClient, settings: Settings) -> "HasDataClient":
        return cls(
            client,
            api_key=settings.hasdata_api_key,
            base_url=settings.hasdata_base_url,
            search_path=settings.hasdata_search_path,
            scrape_path=settings.hasdata_scrape_path,
            key_header=settings.hasdata_key_header,
            search_timeout_s=settings.hasdata_search_timeout_s,
            scrape_timeout_s=settings.hasdata_scrape_timeout_s,
            max_results=settings.search_max_results,
            detail_max_chars=settings.hasdata_detail_max_chars,
        )

    def _key(self) -> str:
        if self._api_key is None or not self._api_key.get_secret_value():
            raise SearchError("unavailable", "HasData API 키가 설정되지 않았습니다.")
        return self._api_key.get_secret_value()

    async def _call(
        self,
        method: str,
        path: str,
        timeout_s: float,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """직렬화한 요청 한 번. 대기 포함 전체 시간이 timeout_s를 넘으면 timeout."""
        key = self._key()
        try:
            async with asyncio.timeout(timeout_s):
                async with self._gate:
                    response = await self._client.request(
                        method,
                        f"{self._base_url}{path}",
                        params=params,
                        json=json,
                        headers={self._key_header: key},
                        timeout=timeout_s,
                    )
        except (TimeoutError, httpx2.TimeoutException) as exc:
            logger.warning("HasData 시간 초과 (%.1f초)", timeout_s)
            raise SearchError("timeout", "검색 시간이 초과되었습니다.") from exc
        except httpx2.HTTPError as exc:
            logger.warning("HasData 요청 실패: %s", type(exc).__name__)
            raise SearchError("failed", "검색 서비스에 연결하지 못했습니다.") from exc
        status = response.status_code
        if status in (401, 402, 403):  # 키 오류·크레딧 소진: 다시 해도 안 풀린다
            logger.error("HasData 사용 불가: HTTP %d (키 또는 크레딧 확인)", status)
            raise SearchError("unavailable", "검색 서비스를 쓸 수 없습니다.")
        if status == 429:  # 동시 요청 1개 제한 포함
            logger.warning("HasData 속도 제한: HTTP 429")
            raise SearchError("rate_limited", "검색 요청이 잠시 많습니다.")
        if status >= 400:
            logger.warning(
                "HasData 오류: HTTP %d", status
            )  # 본문에 검색어가 있을 수 있어 남기지 않는다
            raise SearchError("failed", "검색에 실패했습니다.")
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("HasData 응답을 읽지 못했습니다")
            raise SearchError("failed", "검색 응답을 읽지 못했습니다.") from exc

    async def search(
        self,
        query: str,
        *,
        gl: str | None = None,
        hl: str | None = None,
        recency: str | None = None,
    ) -> list[SearchResult]:
        params: dict[str, Any] = {"q": query, "num": _MIN_NUM}
        if gl:
            params["gl"] = gl
        if hl:
            params["hl"] = hl
        if recency:
            params["tbs"] = _RECENCY_TBS[recency]
        started = time.monotonic()
        data = await self._call("GET", self._search_path, self._search_timeout_s, params=params)
        try:
            organic = data["organicResults"]
            if not isinstance(organic, list):
                raise TypeError("organicResults")
        except (KeyError, TypeError) as exc:
            logger.warning("HasData 검색 응답에 organicResults가 없습니다")
            raise SearchError("failed", "검색 응답을 읽지 못했습니다.") from exc
        results = self._results(organic)[: self._max_results]
        logger.info(
            "HasData 검색 완료 range=%s query_len=%d results=%d %dms",
            recency,
            len(query),
            len(results),
            int((time.monotonic() - started) * 1000),
        )
        return results

    @staticmethod
    def _results(organic: list[Any]) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in organic:
            if not isinstance(item, dict):
                continue
            url = item.get("link")
            if not isinstance(url, str) or not safe_url(url) or url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=clean_text(item.get("title")),
                    url=url,
                    snippet=clean_text(item.get("snippet")),
                    published=None,
                    host=host_of(url),
                    date_text=clean_text(item.get("date")) or None,
                )
            )
        return results

    async def scrape(self, url: str) -> str:
        """URL의 본문을 HasData가 대신 가져온 마크다운(detail_max_chars까지)."""
        body = {"url": url, "outputFormat": ["markdown"], "removeBase64Images": True}
        started = time.monotonic()
        data = await self._call("POST", self._scrape_path, self._scrape_timeout_s, json=body)
        text = _markdown_of(data)
        if not text:
            logger.warning("HasData 스크래핑 응답에 본문이 없습니다")
            raise SearchError("failed", "페이지 내용을 읽지 못했습니다.")
        text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()
        clipped = text[: self._detail_max_chars]
        logger.info(
            "HasData 스크래핑 완료 url_len=%d chars=%d clipped=%s %dms",
            len(url),
            len(clipped),
            len(text) > len(clipped),
            int((time.monotonic() - started) * 1000),
        )
        return clipped + ("\n…(이하 생략)" if len(text) > len(clipped) else "")


def _markdown_of(data: Any) -> str:
    """스크래핑 응답에서 마크다운 본문. 필드 이름은 확인 전 가정이라 흔한 위치를 차례로 본다."""
    if not isinstance(data, dict):
        return ""
    for holder in (data, data.get("data"), data.get("content")):
        if isinstance(holder, str) and holder.strip():
            return holder
        if isinstance(holder, dict):
            for key in ("markdown", "content", "text"):
                value = holder.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return ""
