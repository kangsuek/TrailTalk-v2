import logging
import re

from app.request_context import _VALID_REQUEST_ID


def test_request_id_is_generated(client):
    response = client.get("/api/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_valid_request_id_is_echoed(client):
    response = client.get("/api/health", headers={"X-Request-ID": "web-abc_123.4"})
    assert response.headers["x-request-id"] == "web-abc_123.4"


def test_invalid_request_id_is_replaced(client):
    for bad in ("has space", "x" * 65, "a/b", "<script>"):
        response = client.get("/api/health", headers={"X-Request-ID": bad})
        assert response.headers["x-request-id"] != bad
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_access_log_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="trailtalk.access"):
        response = client.get("/api/health?token=secret", headers={"X-Request-ID": "req-1"})
    records = [r for r in caplog.records if r.name == "trailtalk.access"]
    assert len(records) == 1
    line = records[0].getMessage()
    assert re.fullmatch(r"GET /api/health 200 \d+\.\dms", line)
    assert "secret" not in line
    assert response.headers["x-request-id"] == "req-1"


def test_request_id_rejects_trailing_newline():
    assert _VALID_REQUEST_ID.fullmatch("abc") is not None
    assert _VALID_REQUEST_ID.fullmatch("abc\n") is None


def test_uvicorn_access_log_disabled(client):
    # uvicorn 기본 access 로그는 쿼리스트링을 남기므로 꺼져 있어야 한다
    assert logging.getLogger("uvicorn.access").disabled
