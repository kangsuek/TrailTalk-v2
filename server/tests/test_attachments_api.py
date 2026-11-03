"""첨부 턴과 CLI 전달(M5-07, client-contract 2.13): 업로드 → 저장 → CLI 입력 블록 → 내려받기 →
일지 전문 → 다시 열기 → 삭제·고아 정리. 녹화를 재생하는 가짜 CLI를 쓴다."""

import json
import stat
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import (
    Attachment,
    ConversationSession,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.jobs.extract import build_transcript
from app.main import create_app
from app.services import attachments
from tests.attachments_helpers import jpeg_bytes, pdf_bytes, png_bytes
from tests.test_extract import cli_output
from tests.test_sessions import events_of, load, start, turns_of

PNG = png_bytes((40, 30))
TEXT = "회의 메모: 지도 앱 아이디어\n두 번째 줄"


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def content_log(tmp_path, monkeypatch):
    path = tmp_path / "content.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_CONTENT_LOG", str(path))

    def read() -> list:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    return read


@pytest.fixture
def api(fake_cli, home, content_log, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    oneshot = tmp_path / "oneshot.jsonl"
    oneshot.write_text(cli_output() + "\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT", str(oneshot))
    with TestClient(create_app(fake_cli.settings)) as client:
        client.fake_cli = fake_cli
        client.att_dir = fake_cli.settings.attachments_dir
        yield client


def send(api, session_id, text="이거 봐 줘", files=None, **kw):
    files = files if files is not None else [("files", ("a.png", PNG, "image/png"))]
    return api.post(
        f"/api/sessions/{session_id}/turns/files", data={"text": text}, files=files, **kw
    )


def attachment_rows(api) -> list[Attachment]:
    async def fn(db):
        return list((await db.scalars(select(Attachment).order_by(Attachment.created_at))).all())

    return load(api, fn)


def folder(api, session_id):
    return api.att_dir / session_id


def error_of(response) -> str:
    return response.json()["error"]["code"]


def test_files_turn_sends_blocks_and_stores_only_text(api, content_log):
    session_id = start(api)["session"]["id"]
    files = [
        ("files", ("그림.png", PNG, "image/png")),
        ("files", ("메모.txt", TEXT.encode(), "text/plain")),
        ("files", ("문서.pdf", pdf_bytes(2), "application/pdf")),
    ]
    response = send(api, session_id, "이 파일들 요약해 줘", files)
    assert response.status_code == 200, response.text
    events = events_of(response)
    assert events[0].type == "turn" and events[-1].type == "done"

    # CLI 입력: [이미지, document(PDF), 텍스트(래퍼 + 글)] 순서
    sent = content_log()[-1]
    assert [b["type"] for b in sent] == ["image", "document", "text"]
    assert sent[0]["source"]["media_type"] == "image/png"  # 투명 PNG는 PNG 그대로
    assert sent[1]["source"]["media_type"] == "application/pdf"
    body = sent[2]["text"]
    assert '<attachment name="메모.txt">' in body and TEXT in body
    assert body.rindex("</attachment>") < body.index("이 파일들 요약해 줘")  # 래퍼가 글 앞에

    # turn.text에는 글만 저장하고 첨부는 행·파일로 남는다
    user = turns_of(api, session_id)[1]
    assert user.role is TurnRole.USER and user.text == "이 파일들 요약해 줘"
    rows = attachment_rows(api)
    assert sorted(r.name for r in rows) == ["그림.png", "메모.txt", "문서.pdf"]
    assert {r.turn_id for r in rows} == {user.id}
    assert stat.S_IMODE(folder(api, session_id).stat().st_mode) == 0o700
    for row in rows:
        assert (api.att_dir / row.path).is_file()
        assert stat.S_IMODE((api.att_dir / row.path).stat().st_mode) == 0o600

    # 일지 상세 전문의 turns[].attachments
    detail = api.get(f"/api/journal/{session_id}").json()
    by_name = {a["name"]: a for t in detail["turns"] for a in t["attachments"]}
    assert set(by_name) == {"그림.png", "메모.txt", "문서.pdf"}
    assert by_name["그림.png"]["thumb"] is True and by_name["메모.txt"]["thumb"] is False
    assert by_name["문서.pdf"]["mime"] == "application/pdf"
    assert set(by_name["그림.png"]) == {"id", "name", "mime", "size", "thumb"}
    assert all(t["attachments"] == [] for t in detail["turns"] if t["role"] == "assistant")


def test_text_only_attachment_is_sent_as_string(api, content_log):
    session_id = start(api)["session"]["id"]
    files = [("files", ("a.md", b"# hi", "text/markdown"))]
    assert send(api, session_id, "읽어 줘", files).status_code == 200
    sent = content_log()[-1]
    assert isinstance(sent, str) and '<attachment name="a.md">\n# hi\n</attachment>' in sent
    assert sent.endswith("읽어 줘")


def test_download_headers_for_each_kind(api):
    session_id = start(api)["session"]["id"]
    files = [
        ("files", ("그림.png", PNG, "image/png")),
        ("files", ("메모.txt", TEXT.encode(), "text/plain")),
        ("files", ("문서.pdf", pdf_bytes(1), "application/pdf")),
    ]
    assert send(api, session_id, "봐 줘", files).status_code == 200
    rows = {r.name: r for r in attachment_rows(api)}

    image = api.get(f"/api/attachments/{rows['그림.png'].id}")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["content-disposition"].startswith("inline")
    assert image.headers["x-content-type-options"] == "nosniff"
    thumb = api.get(f"/api/attachments/{rows['그림.png'].id}?thumb=1")
    assert thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["x-content-type-options"] == "nosniff"

    text = api.get(f"/api/attachments/{rows['메모.txt'].id}")
    assert text.headers["content-type"] == "text/plain; charset=utf-8"
    assert text.headers["content-disposition"].startswith("attachment")
    assert text.headers["x-content-type-options"] == "nosniff"
    assert text.text == TEXT
    # 썸네일이 없는 첨부는 ?thumb=1이어도 원본이다
    assert api.get(f"/api/attachments/{rows['메모.txt'].id}?thumb=1").text == TEXT

    pdf = api.get(f"/api/attachments/{rows['문서.pdf'].id}")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("attachment")
    assert pdf.headers["x-content-type-options"] == "nosniff"

    missing = api.get("/api/attachments/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404 and error_of(missing) == "attachment_not_found"


def test_download_404_when_file_missing_or_path_escapes(api):
    session_id = start(api)["session"]["id"]
    assert send(api, session_id).status_code == 200
    (row,) = attachment_rows(api)
    (api.att_dir / row.path).unlink()
    assert api.get(f"/api/attachments/{row.id}").status_code == 404

    async def point_outside(db):
        att = await db.get(Attachment, row.id)
        att.path = "../../../etc/hosts"
        await db.commit()

    load(api, point_outside)
    assert api.get(f"/api/attachments/{row.id}").status_code == 404


def test_voice_session_is_rejected_without_a_user_turn(api):
    session_id = start(api, "voice")["session"]["id"]
    before = len(turns_of(api, session_id))
    response = send(api, session_id)
    assert response.status_code == 400 and error_of(response) == "attachment_invalid"
    assert len(turns_of(api, session_id)) == before
    assert attachment_rows(api) == []


def test_validation_errors_are_json_and_leave_no_turn_or_file(api):
    session_id = start(api)["session"]["id"]
    before = len(turns_of(api, session_id))

    def check(response, status, code):
        assert response.status_code == status, response.text
        assert error_of(response) == code
        assert len(turns_of(api, session_id)) == before
        assert attachment_rows(api) == []
        assert not folder(api, session_id).exists() or not any(folder(api, session_id).iterdir())

    check(send(api, session_id, text="  "), 400, "attachment_invalid")  # 글 필수
    check(send(api, session_id, text="가" * 4001), 400, "attachment_invalid")
    check(send(api, session_id, files=[]), 400, "attachment_invalid")  # 파일 없음
    four = [("files", (f"{i}.txt", b"hi", "text/plain")) for i in range(4)]
    check(send(api, session_id, files=four), 400, "attachment_invalid")
    fake = [("files", ("a.jpg", PNG, "image/jpeg"))]
    check(send(api, session_id, files=fake), 400, "attachment_invalid")
    huge = [("files", ("a.png", b"\x89PNG" + b"0" * (5 * 1024 * 1024 + 1), "image/png"))]
    check(send(api, session_id, files=huge), 413, "attachment_too_large")
    two_pdf = [("files", (f"{i}.pdf", pdf_bytes(1), "application/pdf")) for i in range(2)]
    check(send(api, session_id, files=two_pdf), 400, "attachment_invalid")


def test_oversized_body_rejected_before_parsing(api):
    session_id = start(api)["session"]["id"]
    big = b"0" * (3 * 5 * 1024 * 1024 + 2 * 1024 * 1024)
    response = send(api, session_id, files=[("files", ("a.txt", big, "text/plain"))])
    assert response.status_code == 413 and error_of(response) == "attachment_too_large"


def test_session_cumulative_image_limit(api):
    session_id = start(api)["session"]["id"]
    for _ in range(10):  # 세션당 이미지 10장
        files = [("files", ("a.png", png_bytes((8, 8)), "image/png"))]
        assert send(api, session_id, files=files).status_code == 200
    response = send(api, session_id)
    assert response.status_code == 400 and error_of(response) == "attachment_invalid"
    assert len(attachment_rows(api)) == 10


def test_ended_session_and_unknown_session(api):
    session_id = start(api)["session"]["id"]
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    response = send(api, session_id)
    assert response.status_code == 409 and error_of(response) == "session_ended"
    assert attachment_rows(api) == []
    missing = send(api, "00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404 and error_of(missing) == "session_not_found"


def test_exif_is_removed_in_stored_file(api):
    session_id = start(api)["session"]["id"]
    files = [("files", ("p.jpg", jpeg_bytes((64, 48), orientation=6), "image/jpeg"))]
    assert send(api, session_id, files=files).status_code == 200
    (row,) = attachment_rows(api)
    assert b"TestCamera" not in (api.att_dir / row.path).read_bytes()


def end_and_delete(api, session_id):
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    assert api.delete(f"/api/journal/{session_id}").status_code == 204


def test_delete_session_removes_rows_and_folder(api):
    session_id = start(api)["session"]["id"]
    assert send(api, session_id).status_code == 200
    other = start(api)["session"]["id"]
    assert send(api, other).status_code == 200
    assert len(attachment_rows(api)) == 2
    end_and_delete(api, session_id)
    rows = attachment_rows(api)
    assert [r.path.split("/")[0] for r in rows] == [other]  # 다른 대화 첨부는 그대로
    assert not folder(api, session_id).exists() and folder(api, other).is_dir()


def test_reopen_keeps_names_for_images_and_pdf_and_text_content(api, content_log):
    session_id = start(api)["session"]["id"]
    files = [
        ("files", ("그림.png", PNG, "image/png")),
        ("files", ("메모.txt", TEXT.encode(), "text/plain")),
        ("files", ("문서.pdf", pdf_bytes(1), "application/pdf")),
    ]
    assert send(api, session_id, "이 파일들 봐 줘", files).status_code == 200
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200

    response = api.post(f"/api/sessions/{session_id}/reopen", json={"mode": "text"})
    assert response.status_code == 200, response.text
    reopened = response.json()
    user_turn = next(t for t in reopened["turns"] if t["role"] == "user")
    assert {a["name"] for a in user_turn["attachments"]} == {"그림.png", "메모.txt", "문서.pdf"}

    records = [r for r in api.fake_cli.records() if "--json-schema" not in r["args"]]
    args = records[-1]["args"]
    prompt = args[args.index("--system-prompt") + 1]
    assert "사용자: 이 파일들 봐 줘 [첨부: 그림.png] [첨부: 메모.txt] [첨부: 문서.pdf]" in prompt
    # 텍스트 첨부만 내용이 다시 들어가고 이미지·PDF는 이름만 남는다
    assert "<첨부기록>" in prompt and TEXT.splitlines()[0] in prompt
    assert prompt.count("<첨부기록>") == 1
    assert "[메모.txt]" in prompt.split("<첨부기록>")[1]
    assert "iVBOR" not in prompt  # 이미지 바이트(base64)는 넣지 않는다


def test_reopen_text_budget_is_newest_first_10k_chars(api):
    session_id = start(api)["session"]["id"]
    old = "옛날파일내용" + "가" * 4000
    new = "새파일내용" + "나" * 4000
    mid = "중간파일내용" + "다" * 4000
    for name, content in (("old.txt", old), ("mid.txt", mid), ("new.txt", new)):
        files = [("files", (name, content.encode(), "text/plain"))]
        assert send(api, session_id, f"{name} 읽어", files).status_code == 200
    assert api.post(f"/api/sessions/{session_id}/end").status_code == 200
    assert api.post(f"/api/sessions/{session_id}/reopen", json={}).status_code == 200
    records = [r for r in api.fake_cli.records() if "--json-schema" not in r["args"]]
    args = records[-1]["args"]
    prompt = args[args.index("--system-prompt") + 1]
    block = prompt.split("<첨부기록>")[1]
    assert "새파일내용" in block and "중간파일내용" in block  # 최신순 1만 자 안
    assert "옛날파일내용" not in block  # 넘친 파일은 이름만
    assert "[첨부: old.txt]" in prompt


def test_transcript_for_journal_extraction_has_names_only(api):
    session_id = start(api)["session"]["id"]
    files = [("files", ("메모.txt", TEXT.encode(), "text/plain"))]
    assert send(api, session_id, "이거 정리", files).status_code == 200
    transcript = build_transcript(turns_of(api, session_id), "제니")
    assert "사용자: 이거 정리 [첨부: 메모.txt]" in transcript
    assert TEXT.splitlines()[0] not in transcript


# ---- 고아 정리 ----


@pytest.fixture
def purgeable(api, monkeypatch):
    """임시 폴더를 기본 첨부 폴더로 바꿔 안전장치를 통과시킨다(실제 data 폴더는 건드리지 않는다)."""
    monkeypatch.setattr(attachments, "DEFAULT_ATTACHMENTS_DIR", api.att_dir)
    return api


def purge(api, now: float | None = None) -> int:
    return api.portal.call(lambda: attachments.purge_orphans(api.app, now))


def put_file(root, session_id, name, mtime):
    path = root / session_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    import os

    os.utime(path, (mtime, mtime))
    return path


SID = "22222222-2222-4222-8222-222222222222"


def test_purge_removes_only_old_files_without_rows(purgeable):
    api = purgeable
    session_id = start(api)["session"]["id"]
    assert send(api, session_id).status_code == 200
    now = time.time()
    known = [api.att_dir / r.path for r in attachment_rows(api)]
    old = put_file(api.att_dir, SID, "old.png", now - 2 * 3600)
    fresh = put_file(api.att_dir, SID, "fresh.png", now - 60)
    # 행이 있는 파일은 오래돼도 지우지 않는다
    assert purge(api, now + 10 * 3600) == 2  # old·fresh는 10시간 뒤엔 둘 다 오래됨
    assert not old.exists() and not fresh.exists()
    assert all(p.exists() for p in known)


def test_purge_grace_period_keeps_fresh_files(purgeable):
    api = purgeable
    now = time.time()
    fresh = put_file(api.att_dir, SID, "fresh.png", now - 60)
    old = put_file(api.att_dir, SID, "old.png", now - 3601 - 5)
    assert purge(api, now) == 1
    assert fresh.exists() and not old.exists()


def test_purge_does_nothing_when_dir_is_not_the_default_path(api):
    now = time.time()
    old = put_file(api.att_dir, SID, "old.png", now - 3 * 3600)
    assert purge(api, now) == 0  # 기본 경로가 아니면 동작하지 않는다(Spec 9절)
    assert old.exists()


def test_purge_ignores_foreign_layouts(purgeable):
    api = purgeable
    now = time.time()
    stray = api.att_dir / "notes.txt"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("x")
    other = put_file(api.att_dir, "not-a-uuid-folder", "f.png", now - 5 * 3600)
    assert purge(api, now) == 0
    assert stray.exists() and other.exists()


def test_purge_does_not_mistake_claude_app_session_attachments_for_orphans(purgeable):
    api = purgeable
    now = time.time()
    old = now - 5 * 3600
    kept = put_file(api.att_dir, SID, "app.png", old)

    async def seed(db):
        convo = ConversationSession(
            id=SID,
            mode=SessionMode.CLAUDE_APP,
            status=SessionStatus.ENDED,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        db.add(convo)
        await db.flush()
        turn = Turn(session_id=SID, seq=1, role=TurnRole.USER, text="앱 메모")
        turn.attachments = [
            Attachment(name="app.png", mime="image/png", size=1, path=f"{SID}/app.png")
        ]
        db.add(turn)
        await db.commit()

    load(api, seed)
    assert purge(api, now) == 0
    assert kept.exists()


def test_busy_session_rejects_files_turn_before_saving_anything(api):
    session_id = start(api)["session"]["id"]
    runtime = api.app.state.runtimes.ensure(session_id)
    api.portal.call(runtime.turn_lock.acquire)
    try:
        response = send(api, session_id)
    finally:
        runtime.turn_lock.release()
    assert response.status_code == 409 and error_of(response) == "turn_in_progress"
    assert attachment_rows(api) == []
    assert not folder(api, session_id).exists()
