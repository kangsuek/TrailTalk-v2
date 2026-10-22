from sqlalchemy.exc import OperationalError

from app.db.session import get_db


def test_health_returns_ok_with_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_returns_503_when_db_is_down(app, client):
    class BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("연결 불가"))

        async def rollback(self):
            pass

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "db_unavailable"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "연결 불가" not in response.text
