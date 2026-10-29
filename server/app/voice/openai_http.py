"""OpenAI 음성 API 공통 호출(STT·TTS). 키는 요청 머리말에만 쓰고 로그에 남기지 않는다."""

import asyncio
import logging
from typing import Any

import httpx2
from pydantic import SecretStr

from app.errors import AppError

logger = logging.getLogger("trailtalk.voice")


def unavailable() -> AppError:
    return AppError("voice_unavailable", "음성 서비스를 쓸 수 없습니다.", 503)


def failed(prefix: str) -> AppError:
    return AppError(f"{prefix}_failed", "음성 처리에 실패했습니다.", 502)


def _error_field(response: httpx2.Response, field: str) -> str | None:
    try:
        return response.json()["error"][field]
    except (ValueError, KeyError, TypeError):
        return None


def _error_type(response: httpx2.Response) -> str | None:
    return _error_field(response, "type")


def _error_code(response: httpx2.Response) -> str | None:
    return _error_field(response, "code")


RETRY_PAUSE_S = 0.5  # 429·5xx 재시도 사이 쉬는 시간(Retry-After가 없을 때)
RETRY_AFTER_MAX_S = (
    2.0  # Retry-After가 이보다 길면 기다리지 않고 바로 실패한다(문장이 오래 막히지 않게)
)


async def _pause(seconds: float) -> None:
    """재시도 사이 쉬는 시간(테스트에서 바꿔 끼운다). 쉬는 중 취소되면 그대로 전파된다."""
    await asyncio.sleep(seconds)


def _retry_delay(response: httpx2.Response) -> float | None:
    """429·5xx를 다시 시도할 때 쉴 시간. 너무 길게 기다리라고 하면 None(다시 시도하지 않는다)."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return RETRY_PAUSE_S
    try:
        seconds = float(raw)
    except ValueError:
        return RETRY_PAUSE_S
    return seconds if 0 <= seconds <= RETRY_AFTER_MAX_S else None


async def post(
    client: httpx2.AsyncClient,
    *,
    base_url: str,
    api_key: SecretStr | None,
    path: str,
    timeout_s: float,
    error_prefix: str,
    attempts: int = 1,
    **kwargs: Any,
) -> httpx2.Response:
    """POST 후 성공 응답을 돌려준다. 실패는 {prefix}_timeout·{prefix}_failed·voice_unavailable.

    attempts(총 시도 횟수)가 2 이상이면 시간 초과·연결 오류·429·5xx를 다시 시도한다. 요청이
    응답 없이 멈추는 일이 있어 시도당 제한을 짧게 두고 새로 보낸다(멈춘 연결은 풀에서 빠진다).
    키 오류·크레딧 소진·그 밖의 4xx는 다시 해도 풀리지 않으므로 바로 실패한다. 모두 소진하면
    마지막 시도의 오류를 던진다."""
    if api_key is None or not api_key.get_secret_value():
        logger.error("OPENAI_API_KEY가 설정되지 않았습니다")
        raise unavailable()
    headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"}
    url = base_url.rstrip("/") + path
    for attempt in range(1, max(attempts, 1) + 1):
        more = attempt < attempts
        try:
            response = await client.post(url, headers=headers, timeout=timeout_s, **kwargs)
        except httpx2.TimeoutException as exc:
            if more:
                logger.warning("%s 재시도 %d/%d (시간 초과)", path, attempt, attempts)
                continue
            raise AppError(
                f"{error_prefix}_timeout", "음성 처리 시간이 초과되었습니다.", 504
            ) from exc
        except httpx2.TransportError as exc:
            if more:
                logger.warning("%s 재시도 %d/%d (%s)", path, attempt, attempts, type(exc).__name__)
                continue
            logger.warning("%s 요청 실패: %s", path, type(exc).__name__)
            raise failed(error_prefix) from exc
        except httpx2.HTTPError as exc:
            logger.warning("%s 요청 실패: %s", path, type(exc).__name__)
            raise failed(error_prefix) from exc
        if response.status_code < 400:
            return response
        if response.status_code in (401, 403):
            # 인증 오류 본문에는 키 뒷자리가 들어 있어 종류만 남긴다
            detail = f"{_error_type(response)}/{_error_code(response)}"
        else:
            detail = response.text[:500].replace("\n", " ")
        # 키 오류·크레딧 소진은 다시 시도해도 풀리지 않는다(429여도 쿼터 소진은 여기서 끝낸다)
        if response.status_code in (401, 403) or _error_type(response) == "insufficient_quota":
            logger.warning("%s 오류 %s: %s", path, response.status_code, detail)
            raise unavailable()
        retryable = response.status_code == 429 or response.status_code >= 500
        delay = _retry_delay(response) if retryable and more else None
        if delay is not None:
            # 다시 시도할 때는 상태 코드만 남긴다(본문은 마지막 실패에서 한 번만)
            logger.warning(
                "%s 재시도 %d/%d (HTTP %d)", path, attempt, attempts, response.status_code
            )
            await _pause(delay)
            continue
        logger.warning("%s 오류 %s: %s", path, response.status_code, detail)
        raise failed(error_prefix)
    raise failed(error_prefix)  # attempts가 0 이하일 때만 닿는다
