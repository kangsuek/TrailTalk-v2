import logging

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.errors import AppError
from app.main import create_app


@pytest.fixture
def error_client(make_settings):
    app = create_app(make_settings())
    router = APIRouter(prefix="/test")

    @router.get("/app-error")
    async def app_error():
        raise AppError("session_not_found", "세션이 없습니다.", 404, details={"id": "x"})

    @router.get("/validation")
    async def validation(count: int):
        return {"count": count}

    @router.get("/boom")
    async def boom():
        raise RuntimeError("비밀 내부 정보")

    @router.get("/odd-status")
    async def odd_status():
        raise HTTPException(599, detail={"x": 1})

    @router.get("/stream-fail")
    async def stream_fail():
        async def chunks():
            yield "data: first\n\n"
            raise RuntimeError("스트림 도중 오류")

        return StreamingResponse(chunks(), media_type="text/event-stream")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == code
    assert body["message"]
    assert body["request_id"] == response.headers["x-request-id"]
    return body


def test_unknown_api_path_returns_json_not_found(client):
    assert_error(client.get("/api/nope"), 404, "not_found")
    assert_error(client.post("/api/health/nope"), 404, "not_found")


def test_method_not_allowed(client):
    assert_error(client.post("/api/health"), 405, "method_not_allowed")


def test_app_error_keeps_code_and_details(error_client):
    body = assert_error(error_client.get("/test/app-error"), 404, "session_not_found")
    assert body["details"] == {"id": "x"}


def test_validation_error_lists_fields(error_client):
    body = assert_error(error_client.get("/test/validation?count=abc"), 422, "validation_error")
    assert body["details"][0]["loc"] == ["query", "count"]


def test_unhandled_error_hides_internals_but_logs(error_client, caplog):
    with caplog.at_level(logging.ERROR, logger="trailtalk.errors"):
        response = error_client.get("/test/boom")
    body = assert_error(response, 500, "internal_error")
    assert "비밀 내부 정보" not in response.text
    assert "details" not in body
    assert any("비밀 내부 정보" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


def test_api_errors_unchanged_when_web_is_served(make_settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>TrailTalk</title>", encoding="utf-8")
    with TestClient(create_app(make_settings(web_dist_dir=dist))) as client:
        assert "TrailTalk" in client.get("/").text
        assert client.get("/api/health").json()["status"] == "ok"
        assert_error(client.get("/api/nope"), 404, "not_found")
        assert_error(client.post("/api/nope"), 404, "not_found")
        assert_error(client.put("/api/health/1"), 404, "not_found")
        assert_error(client.post("/api/health"), 405, "method_not_allowed")


def test_non_standard_http_exception(error_client):
    assert_error(error_client.get("/test/odd-status"), 599, "http_error")


def test_error_during_stream_is_logged_once_with_request_id(error_client, caplog):
    with caplog.at_level(logging.ERROR, logger="trailtalk.errors"):
        response = error_client.get("/test/stream-fail", headers={"X-Request-ID": "sse-1"})
    # 상태 코드는 이미 200으로 나갔다(TestClient는 끊긴 본문을 비워서 돌려준다)
    assert response.status_code == 200
    errors = [r for r in caplog.records if r.name == "trailtalk.errors"]
    assert len(errors) == 1
    assert errors[0].getMessage() == "응답 도중 오류"
    assert errors[0].request_id == "sse-1"
