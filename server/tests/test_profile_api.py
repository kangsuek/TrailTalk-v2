"""GET/PUT /api/profile (client-contract 4.1)."""

import pytest
from sqlalchemy import create_engine, text


def put(test_client, **fields):
    return test_client.put("/api/profile", json=fields)


def test_first_get_creates_default_profile(client):
    response = client.get("/api/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["nickname"] is None
    assert "email" not in body and "mail_ready" not in body  # 이메일 기능 제거(2026-11-02)
    assert body["interests"] == []
    assert body["persona_id"] == "jenny"  # 저장값이 없으면 기본 페르소나
    assert body["voice"] is None
    assert body["speaking_rate"] is None
    assert body["ack_enabled"] is True
    assert body["keep_audio"] is False
    assert body["chat_model"] is None
    assert body["default_chat_model"] == "sonnet"
    assert body["client"]["session"]["idle_timeout_minutes"] == 30
    assert body["client"]["vad"]["end_of_speech_silence_ms"] == 1800


def test_get_twice_keeps_a_single_row(client, app):
    client.get("/api/profile")
    client.get("/api/profile")
    url = app.state.settings.database_url.replace("+aiosqlite", "")
    with create_engine(url).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM user_profile")).scalar_one() == 1


def test_put_changes_only_sent_fields_and_persists(client):
    assert put(client, nickname="  지은  ", interests=["등산", "사진"]).status_code == 200
    response = put(client, ack_enabled=False)
    assert response.status_code == 200
    body = client.get("/api/profile").json()
    assert body["nickname"] == "지은"  # 앞뒤 공백은 뗀다
    assert body["interests"] == ["등산", "사진"]  # 보내지 않은 필드는 그대로
    assert body["ack_enabled"] is False


def test_put_empty_body_changes_nothing(client):
    put(client, nickname="지은")
    assert put(client).status_code == 200
    assert client.get("/api/profile").json()["nickname"] == "지은"


@pytest.mark.parametrize("value", ["", "   ", "가" * 21, "두\n줄", "탭\r끝"])
def test_nickname_must_be_one_to_twenty_chars_on_one_line(client, value):
    response = put(client, nickname=value)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_nickname_accepts_twenty_chars_and_null_resets(client):
    assert put(client, nickname="가" * 20).json()["nickname"] == "가" * 20
    assert put(client, nickname=None).json()["nickname"] is None


def test_email_is_not_a_profile_field_any_more(client):
    """이메일 기능을 제거했다(FR-21, 2026-11-02). 보내면 알 수 없는 필드로 422다."""
    assert put(client, email="me@example.com").status_code == 422
    assert put(client, email=None).status_code == 422
    assert "email" not in client.get("/api/profile").json()


def test_interests_are_trimmed_and_deduplicated_in_order(client):
    body = put(client, interests=[" 등산 ", "사진", "등산", "사진 "]).json()
    assert body["interests"] == ["등산", "사진"]


def test_interests_request_length_is_capped_before_deduplication(client):
    """중복 제거 전의 배열 길이에도 상한이 있어, 같은 값 수만 개를 보내 서버를 붙잡을 수 없다."""
    assert put(client, interests=["등산"] * 100).json()["interests"] == ["등산"]
    assert put(client, interests=["등산"] * 101).status_code == 422
    assert put(client, interests=["등산"] * 50_000).status_code == 422


def test_interests_limits(client):
    assert put(client, interests=[f"관심{i}" for i in range(10)]).status_code == 200
    assert put(client, interests=[f"관심{i}" for i in range(11)]).status_code == 422
    assert put(client, interests=["가" * 31]).status_code == 422
    assert put(client, interests=["가" * 30]).status_code == 200
    assert put(client, interests=[""]).status_code == 422
    assert put(client, interests=None).status_code == 422


@pytest.mark.parametrize("rate", [0.75, 1.0, 1.5])
def test_speaking_rate_in_range(client, rate):
    assert put(client, speaking_rate=rate).json()["speaking_rate"] == rate


@pytest.mark.parametrize("rate", [0.7, 1.6, 0])
def test_speaking_rate_out_of_range(client, rate):
    assert put(client, speaking_rate=rate).status_code == 422


def test_speaking_rate_and_voice_null_return_to_persona_default(client):
    put(client, speaking_rate=1.2, voice="nova")
    body = put(client, speaking_rate=None, voice=None).json()
    assert body["speaking_rate"] is None
    assert body["voice"] is None


@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
def test_chat_model_accepts_known_models(client, model):
    assert put(client, chat_model=model).json()["chat_model"] == model


def test_chat_model_rejects_unknown_and_null_returns_to_default(client):
    assert put(client, chat_model="gpt").status_code == 422
    put(client, chat_model="opus")
    assert put(client, chat_model=None).json()["chat_model"] is None


@pytest.mark.parametrize("field", ["ack_enabled", "keep_audio"])
def test_booleans_are_strict(client, field):
    assert put(client, **{field: True}).json()[field] is True
    assert put(client, **{field: "yes"}).status_code == 422
    assert put(client, **{field: None}).status_code == 422


def test_persona_id_must_exist(client):
    assert put(client, persona_id="jenny").json()["persona_id"] == "jenny"
    missing = put(client, persona_id="nobody")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "persona_not_found"
    assert put(client, persona_id="Bad Id").status_code == 404


def test_persona_id_null_returns_to_default_persona(client):
    put(client, persona_id="jenny")
    assert put(client, persona_id=None).json()["persona_id"] == "jenny"


def test_client_settings_are_read_only(client):
    response = client.put("/api/profile", json={"client": {"vad": {}}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_fields_are_rejected(client):
    assert put(client, favorite_color="blue").status_code == 422
    assert put(client, mail_ready=True).status_code == 422
    assert put(client, default_chat_model="opus").status_code == 422


def test_failed_put_changes_nothing(client):
    put(client, nickname="지은")
    assert put(client, nickname="새이름", speaking_rate=9).status_code == 422
    assert client.get("/api/profile").json()["nickname"] == "지은"


def test_failed_persona_check_keeps_other_fields_unchanged(client):
    """persona 404가 나면 같은 요청의 다른 필드도 바뀌지 않는다(원자성)."""
    put(client, nickname="지은")
    response = put(client, nickname="바뀌면 안 됨", persona_id="nobody")
    assert response.status_code == 404
    assert client.get("/api/profile").json()["nickname"] == "지은"


def _db_rows(app, sql: str):
    url = app.state.settings.database_url.replace("+aiosqlite", "")
    with create_engine(url).connect() as conn:
        return conn.execute(text(sql)).all()


def test_put_persona_id_creates_persona_row_and_refreshes_version(client, app):
    from app.persona.loader import load_persona

    version = load_persona(app.state.settings.persona_dir, "jenny").version
    assert put(client, persona_id="jenny").status_code == 200
    rows = _db_rows(app, "SELECT id, version FROM persona")
    assert [(r.id, r.version) for r in rows] == [("jenny", version)]

    url = app.state.settings.database_url.replace("+aiosqlite", "")
    with create_engine(url).begin() as conn:
        conn.execute(text("UPDATE persona SET version = 'stale'"))
    assert put(client, persona_id="jenny").status_code == 200
    assert _db_rows(app, "SELECT version FROM persona")[0].version == version


def test_persona_id_null_clears_the_stored_value(client, app):
    put(client, persona_id="jenny")
    assert _db_rows(app, "SELECT persona_id FROM user_profile")[0].persona_id == "jenny"
    put(client, persona_id=None)
    assert _db_rows(app, "SELECT persona_id FROM user_profile")[0].persona_id is None


@pytest.mark.parametrize("value", ["", "   "])
def test_voice_rejects_blank(client, value):
    assert put(client, voice=value).status_code == 422


def test_voice_is_trimmed(client):
    assert put(client, voice="  nova  ").json()["voice"] == "nova"
