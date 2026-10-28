"""빌드한 웹 앱 서빙(M2-09): 클라이언트 화면 경로(/journal/…)는 새로고침해도 index.html을 주고,
/api·/internal 아래 없는 경로와 없는 정적 파일은 JSON 404를 유지한다."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

INDEX = "<title>TrailTalk</title>"


@pytest.fixture
def web(make_settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with TestClient(create_app(make_settings(web_dist_dir=dist))) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/journal", "/journal/abc-123", "/settings", "/journal/x/"])
def test_client_routes_serve_index(web, path):
    response = web.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")


def test_static_files_are_served_and_missing_files_are_404(web):
    assert web.get("/assets/app.js").text == "console.log(1)"
    missing = web.get("/assets/nope.js")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/api/nope", "/api/journal/x/y", "/internal/nope", "/internal"])
def test_server_paths_keep_json_404(web, path):
    response = web.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_post_to_client_route_is_not_index(web):
    response = web.post("/journal/abc")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_api_journal_detail_is_not_shadowed(web):
    response = web.get("/api/journal/없는-대화")
    assert response.json()["error"]["code"] == "session_not_found"
