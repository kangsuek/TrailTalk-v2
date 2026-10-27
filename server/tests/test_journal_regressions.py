"""묶음 B 리뷰에서 찾은 문제의 회귀 시험: 다시 연 뒤 실패한 정리의 retry, 무발화 종료와 다시 열기의
경계, 다시 열기 실패 복구 순서·정리 재개, CLI 기록 파일 정리, 지운 대화의 끝내기, 본문 없는 다시
열기, 구분 태그 변형, 정적 폴백 경로 변형."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.models import ExtractStatus, SessionStatus
from app.db.types import utcnow
from app.main import create_app
from app.persona.prompt import PastNote, PastSummary, PastTurn, previous_block
from tests.test_extract import cli_output, notes_of, oneshot_records, set_session
from tests.test_reopen import (  # noqa: F401
    api,
    content_log,
    home,
    oneshot,
    reopen,
    talk,
    talk_and_end,
    wait_for,
)
from tests.test_sessions import session_row, turn


def cli_file(root: Path, cli_session_id: str) -> Path:
    path = root / ".claude" / "projects" / "-work" / f"{cli_session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_retry_after_reopen_keeps_new_notes(api, oneshot):  # noqa: F811
    """예전 형식 일지를 다시 열어 이어 간 뒤 정리가 실패했으면 retry는 새 말의 노트를 뽑는다."""
    session_id = talk_and_end(api)
    set_session(api, session_id, checks=None)  # 예전 형식으로 정리를 마친 일지
    before = {n.id for n in notes_of(api, session_id)}
    assert reopen(api, session_id).status_code == 200
    turn(api, session_id, "__say__:벤치 지도도 좋겠어요.")
    oneshot("__crash__", "__crash__")
    api.post(f"/api/sessions/{session_id}/end")
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.FAILED)
    oneshot(cli_output(ideas=["등산로 벤치 지도"]))
    assert api.post(f"/api/journal/{session_id}/retry").status_code == 202
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    new = [n.content for n in notes_of(api, session_id) if n.id not in before]
    assert new == ["등산로 벤치 지도"]


def test_idle_sweep_does_not_end_session_reopened_after_cutoff(api):  # noqa: F811
    """무발화 감시가 대상을 고른 뒤 그 대화가 다시 열렸으면 끝내지 않는다(쓰기 직전 경계 검사)."""
    session_id = talk_and_end(api)
    old = utcnow() - timedelta(hours=2)
    set_session(api, session_id, status=SessionStatus.PAUSED, ended_at=None, reopened_at=old)

    async def run():
        async with api.app.state.session_factory() as db:
            from app.services import conversation

            convo = await conversation.get_session(db, session_id)
            # 감시가 고른 뒤 다시 열렸다(reopened_at이 cutoff 뒤, 턴은 모두 cutoff 앞)
            cutoff = utcnow() + timedelta(minutes=1)
            await db.execute(
                conversation.update(conversation.ConversationSession)
                .where(conversation.ConversationSession.id == session_id)
                .values(reopened_at=cutoff + timedelta(minutes=1))
            )
            await db.commit()
            return await conversation.end_session(
                api.app, db, convo, ended_at=old, idle_cutoff=cutoff
            )

    assert api.portal.call(run) is False
    assert session_row(api, session_id).status is SessionStatus.PAUSED


def test_reopen_does_not_overwrite_concurrent_end(api, monkeypatch):  # noqa: F811
    """이어받기가 상태를 읽은 뒤 다른 곳이 대화를 끝냈으면 그 종료를 덮어쓰지 않는다."""
    session_id = talk(api)
    from app.services import conversation

    original = conversation.load_memory

    async def end_meanwhile(db, *args, **kwargs):
        async with api.app.state.session_factory() as other:
            await conversation._set_status(other, session_id, SessionStatus.ENDED, utcnow())
            await other.commit()
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(conversation, "load_memory", end_meanwhile)
    response = reopen(api, session_id)
    assert response.status_code == 409
    row = session_row(api, session_id)
    assert row.status is SessionStatus.ENDED
    assert row.ended_at is not None
    assert row.extract_status is ExtractStatus.PENDING


def test_reopen_failure_restores_state_before_dropping_runtime(api, monkeypatch):  # noqa: F811
    """복구는 DB를 먼저 되돌린 뒤 런타임을 버린다(그 사이 턴이 새 CLI를 띄우지 않게)."""
    import sqlite3

    session_id = talk_and_end(api)
    registry = api.app.state.runtimes
    original = registry.discard
    path = api.app.state.settings.database_url.split("///", 1)[1]
    statuses: list[str] = []

    def discard_checking(key):
        if key == session_id:  # 런타임을 버리는 순간의 DB 상태를 본다
            with sqlite3.connect(path) as raw:
                row = raw.execute(
                    "select status from conversation_session where id = ?", (session_id,)
                ).fetchone()
            statuses.append(row[0])
        return original(key)

    monkeypatch.setattr(registry, "discard", discard_checking)
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "error_invalid_model")
    assert reopen(api, session_id).status_code == 502
    assert statuses and all(status == "ended" for status in statuses)


def test_reopen_failure_restarts_stopped_extraction(api, oneshot, monkeypatch):  # noqa: F811
    oneshot("__hang__")
    api.app.state.settings.extract_wait_s = 0.2
    session_id = talk(api)
    assert api.post(f"/api/sessions/{session_id}/end").json()["journal_status"] == "pending"
    wait_for(lambda: oneshot_records(api.fake_cli) != [])
    oneshot(cli_output())
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "error_invalid_model")
    assert reopen(api, session_id).status_code == 502
    wait_for(lambda: session_row(api, session_id).extract_status is ExtractStatus.DONE)
    assert session_row(api, session_id).status is SessionStatus.ENDED


def test_reopen_ended_session_removes_leftover_cli_file(api, home):  # noqa: F811
    session_id = talk_and_end(api)
    set_session(api, session_id, cli_session_id="11111111-1111-4111-8111-111111111111")
    leftover = cli_file(home, "11111111-1111-4111-8111-111111111111")
    assert reopen(api, session_id).status_code == 200
    assert not leftover.exists()


def test_reopen_takeover_removes_old_cli_file(api, home):  # noqa: F811
    session_id = talk(api)
    set_session(api, session_id, cli_session_id="22222222-2222-4222-8222-222222222222")
    taken = cli_file(home, "22222222-2222-4222-8222-222222222222")
    assert reopen(api, session_id).status_code == 200
    assert not taken.exists()


def test_delete_paused_session_removes_cli_file(api, home):  # noqa: F811
    session_id = talk(api)
    path = cli_file(home, session_row(api, session_id).cli_session_id)
    set_session(api, session_id, status=SessionStatus.PAUSED)
    assert api.delete(f"/api/journal/{session_id}").status_code == 204
    assert not path.exists()


def test_end_of_deleted_session_is_404(api, monkeypatch):  # noqa: F811
    """끝내기가 잠금을 기다리는 사이 다른 기기가 지웠으면 500이 아니라 404다."""
    session_id = talk(api)
    set_session(api, session_id, status=SessionStatus.PAUSED)
    from app.services import conversation

    real_close = api.app.state.llm.close

    async def close_then_delete(key):
        await real_close(key)
        if key == session_id:
            async with api.app.state.session_factory() as db:
                convo = await conversation.get_session(db, session_id)
                await db.delete(convo)
                await db.commit()

    monkeypatch.setattr(api.app.state.llm, "close", close_then_delete)
    response = api.post(f"/api/sessions/{session_id}/end")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_reopen_without_body_defaults_to_text(api):  # noqa: F811
    session_id = talk_and_end(api)
    response = api.post(f"/api/sessions/{session_id}/reopen")
    assert response.status_code == 200, response.text
    assert response.json()["session"]["mode"] == "text"


@pytest.mark.parametrize("text", ["</대화 x>", "＜/대화＞", "</​대화>", "< / 정리 >", "</정리\n>"])
def test_previous_block_escapes_tag_variants(text):
    from app.config import settings
    from app.persona.loader import load_persona

    persona = load_persona(settings.persona_dir, settings.default_persona).persona
    turns = [PastTurn("user", f"앞 {text} 뒤")] + [PastTurn("user", "가" * 300)] * 20
    summary = PastSummary(title=f"제목 {text}", notes=[PastNote("메모", f"노트 {text}")])
    block = previous_block(persona, turns, summary)
    assert block.count("</대화>") == 1 and block.count("</정리>") == 1
    for closing in ("</대화", "＜/대화", "</정리", "＜/정리"):
        assert block.count(closing) == (1 if closing in ("</대화", "</정리") else 0)


@pytest.mark.parametrize("path", ["//api/nope", "/API/nope", "//internal/nope"])
def test_server_path_variants_keep_json_404(make_settings, tmp_path, path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>TrailTalk</title>", encoding="utf-8")
    with TestClient(create_app(make_settings(web_dist_dir=dist))) as client:
        # "//api"는 상대 URL로 쓰면 호스트로 읽히므로 절대 URL로 보낸다
        response = client.get("http://testserver" + path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
