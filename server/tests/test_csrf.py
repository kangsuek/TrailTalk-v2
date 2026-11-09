"""변경성 요청 보안(계약 1.5, Spec 9절 D3): X-TrailTalk 헤더·Origin 허용 목록·Content-Type."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def _default_csrf_header():
    """conftest의 기본 헤더 주입을 끈다(이 모듈은 헤더 없는 요청을 직접 보낸다)."""
    yield


@pytest.fixture
def raw(app):
    with TestClient(app) as test_client:
        yield test_client


OK = {"X-TrailTalk": "1"}


def assert_rejected(response, reason_hint: str | None = None):
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "csrf_rejected"
    assert error["request_id"]
    return error


# ① 헤더


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("PUT", "/api/profile", {"json": {"nickname": "해커"}}),
        ("POST", "/api/sessions", {"json": {"mode": "text"}}),
        ("POST", "/api/sessions/prepare", {"json": {"mode": "text"}}),
        ("DELETE", "/api/journal/not-a-real-id", {}),
        ("PATCH", "/api/journal/not-a-real-id", {"json": {"title": "x"}}),
    ],
)
def test_mutating_requests_without_the_header_are_rejected(raw, method, path, kwargs):
    assert_rejected(raw.request(method, path, **kwargs))


def test_header_value_must_be_exactly_one(raw):
    for value in ("0", "true", "", "11"):
        response = raw.put("/api/profile", json={"nickname": "a"}, headers={"X-TrailTalk": value})
        assert_rejected(response)


def test_a_rejected_profile_update_changes_nothing(raw):
    assert_rejected(raw.put("/api/profile", json={"nickname": "해커"}))
    assert raw.get("/api/profile").json()["nickname"] is None


def test_simple_cross_site_form_posts_are_all_rejected(raw):
    """다른 출처 페이지의 <form>이 보낼 수 있는 단순 요청(사용자 정의 헤더 없음)."""
    evil = {"Origin": "https://evil.example"}
    forms = [
        {"content": "nickname=x", "headers": {"Content-Type": "application/x-www-form-urlencoded"}},
        {"content": '{"nickname":"x"}', "headers": {"Content-Type": "text/plain"}},
        {"files": {"f": ("a.txt", b"x")}},
    ]
    for form in forms:
        headers = {**evil, **form.pop("headers", {})}
        assert_rejected(raw.post("/api/sessions", headers=headers, **form))
        assert_rejected(raw.delete("/api/journal/some-id", headers=evil))


def test_get_requests_do_not_need_the_header(raw):
    assert raw.get("/api/health").status_code == 200
    assert raw.get("/api/profile").status_code == 200
    # 읽기 요청은 Origin이 낯설어도 막지 않는다(CORS를 열지 않아 응답을 읽을 수 없다)
    assert raw.get("/api/profile", headers={"Origin": "https://evil.example"}).status_code == 200


def test_header_alone_is_enough_without_an_origin(raw):
    """Origin이 없는 요청(curl·서버 간 호출)은 헤더만 있으면 받는다."""
    assert raw.put("/api/profile", json={"nickname": "지은"}, headers=OK).status_code == 200


# ② Origin


def test_allowed_origins_default_covers_local_server_and_dev_server(raw):
    for origin in (
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ):
        response = raw.put("/api/profile", json={"nickname": "a"}, headers={**OK, "Origin": origin})
        assert response.status_code == 200, origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",  # 샌드박스 iframe·file:// 페이지
        "http://127.0.0.1:8001",  # 같은 호스트의 다른 포트
        "http://127.0.0.1.evil.example",
        "https://127.0.0.1:8000",  # 다른 scheme
        "",
    ],
)
def test_unlisted_origins_are_rejected_even_with_the_header(raw, origin):
    response = raw.put("/api/profile", json={"nickname": "해커"}, headers={**OK, "Origin": origin})
    assert_rejected(response)
    assert raw.get("/api/profile").json()["nickname"] is None


def test_origin_matching_ignores_case_and_a_trailing_slash(raw):
    response = raw.put(
        "/api/profile", json={"nickname": "a"}, headers={**OK, "Origin": "HTTP://LOCALHOST:5173"}
    )
    assert response.status_code == 200


def test_host_header_never_allows_an_origin(make_settings):
    """DNS 리바인딩: 공격자 도메인이 127.0.0.1로 풀려도 Origin=Host일 뿐 허용 목록에는 없다."""
    with TestClient(create_app(make_settings()), base_url="http://evil.example:8000") as c:
        response = c.put(
            "/api/profile",
            json={"nickname": "해커"},
            headers={**OK, "Origin": "http://evil.example:8000"},
        )
        assert_rejected(response)


def test_allowed_origins_can_be_extended_by_setting(make_settings):
    settings = make_settings(
        allowed_origins="https://mac.tail1234.ts.net:8443, http://localhost:5173"
    )
    with TestClient(create_app(settings)) as c:
        ok = c.put(
            "/api/profile",
            json={"nickname": "a"},
            headers={**OK, "Origin": "https://mac.tail1234.ts.net:8443"},
        )
        assert ok.status_code == 200
        # 목록을 직접 지정하면 기본값은 쓰지 않는다
        gone = c.put(
            "/api/profile",
            json={"nickname": "b"},
            headers={**OK, "Origin": "http://127.0.0.1:8000"},
        )
        assert_rejected(gone)


# ③ Content-Type


def test_body_requests_need_a_supported_content_type(raw):
    base = {**OK}
    bad = [
        {
            "content": b"nickname=x",
            "headers": {**base, "Content-Type": "application/x-www-form-urlencoded"},
        },
        {"content": b'{"nickname":"x"}', "headers": {**base, "Content-Type": "text/plain"}},
        {"content": b'{"nickname":"x"}', "headers": {**base, "Content-Type": "application/xml"}},
        {
            "content": b'{"nickname":"x"}',
            "headers": base,
        },  # httpx가 Content-Type을 붙이지 않는 바이트 본문
    ]
    for kwargs in bad:
        assert_rejected(raw.put("/api/profile", **kwargs))
    assert raw.get("/api/profile").json()["nickname"] is None


def test_supported_content_types_pass_the_check(raw):
    assert raw.put("/api/profile", json={"nickname": "a"}, headers=OK).status_code == 200
    # 공통 검사만 통과하면 된다(이 경로의 본문 오류는 각 경로가 처리한다)
    form = raw.post(
        "/api/sessions/no-such/turns/files",
        data={"text": "x"},
        files={"files": ("a.txt", b"x")},
        headers=OK,
    )
    assert form.status_code != 403
    audio = raw.post(
        "/api/sessions/no-such/turns/audio",
        content=b"\x00\x01",
        headers={**OK, "Content-Type": "audio/webm"},
    )
    assert audio.status_code != 403
    odd_audio = raw.post(
        "/api/sessions/no-such/turns/audio",
        content=b"\x00\x01",
        headers={**OK, "Content-Type": "audio/x-unsupported"},
    )
    assert (
        odd_audio.status_code != 403
    )  # 지원하지 않는 오디오는 csrf가 아니라 오디오 오류로 처리된다


def test_bodyless_requests_skip_the_content_type_check(raw):
    assert raw.post("/api/sessions/prepare", headers=OK).status_code != 403
    assert raw.delete("/api/journal/some-id", headers=OK).status_code != 403


# 면제와 응답 형식


def test_internal_paths_are_not_checked_by_csrf(raw):
    """/internal/*은 루프백 전용이라 이 규칙의 대상이 아니다(프록시 경유 차단은 별도 규칙)."""
    response = raw.post("/internal/mcp", json={}, headers={"Origin": "https://evil.example"})
    error = (
        response.json().get("error")
        if response.headers.get("content-type", "").startswith("application/json")
        else None
    )
    assert not (error and error.get("code") == "csrf_rejected")


def test_rejection_logs_only_the_reason(raw, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="trailtalk.csrf"):
        assert_rejected(
            raw.put(
                "/api/profile",
                json={"nickname": "비밀닉네임"},
                headers={"Origin": "https://evil.example"},
            )
        )
    text = caplog.text
    assert "csrf" in text.lower()
    assert "비밀닉네임" not in text
