from app.db.session import create_engine_for, create_session_factory


def test_health_returns_ok_with_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_returns_503_when_db_is_down(app, client, tmp_path):
    # 실제 get_db·세션 팩토리·엔진 경로: 디렉터리를 DB 파일로 가리키면 연결이 실패한다
    broken = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}")
    app.state.session_factory = create_session_factory(broken)
    response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "db_unavailable"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "연결 불가" not in response.text
