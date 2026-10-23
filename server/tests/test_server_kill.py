"""서버 강제 종료 내성(client-contract 2.10): 답변 도중 SIGKILL로 죽어도 보낸 문장까지 남는다.

실제 프로세스(uvicorn)를 가짜 CLI로 띄우고 프로세스 그룹째 죽인 뒤 DB를 직접 읽는다.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.models import Turn, TurnRole
from app.db.session import create_engine_for, create_session_factory
from tests.conftest import FAKE_TOKEN
from tests.test_sessions import FAKE_CLI_SESSION_ID, THREE_SENTENCES, _http

SERVER_DIR = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _launch(settings, port: int, home: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "HOME": str(home),
        "DATABASE_URL": settings.database_url,
        "WEB_DIST_DIR": str(settings.web_dist_dir),
        "CLAUDE_CLI_PATH": settings.claude_cli_path,
        "CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN,
        "CLI_WORK_DIR": str(settings.cli_work_dir),
        "CLI_ENV_PASSTHROUGH": "FAKE_CLAUDE_*",
        "INTERNAL_BASE_URL": f"http://127.0.0.1:{port}",
        "FAKE_CLAUDE_FIXTURE": "multiturn",
        "FAKE_CLAUDE_DELAY": "0.02",
        # 개발자 .env·셸 값과 상관없이 인프로세스 테스트(fake_cli)와 같은 조건으로 띄운다
        "AUTO_MIGRATE": "true",
        "CLI_TURN_TIMEOUT_S": str(settings.cli_turn_timeout_s),
        "TIMEZONE": settings.timezone,
    }
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)]
    # 새 프로세스 그룹: 서버와 자식 CLI를 함께 죽인다
    process = subprocess.Popen(command, cwd=SERVER_DIR, env=env, start_new_session=True)
    # uvicorn은 시작 작업(마이그레이션 등)을 마친 뒤 포트를 연다
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError("서버가 시작하지 못했습니다.")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.05)
            continue
        writer.close()
        return process
    os.killpg(process.pid, signal.SIGKILL)
    raise RuntimeError("서버가 응답하지 않습니다.")


def _kill(process: subprocess.Popen, sig: signal.Signals) -> None:
    """프로세스 그룹(서버와 자식 CLI)을 끝낸다. 제때 끝나지 않으면 SIGKILL로 정리한다."""
    try:
        os.killpg(process.pid, sig)
        process.wait(10)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(10)


async def test_sigkill_during_reply_keeps_sent_sentences(fake_cli, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    settings = fake_cli.settings
    port = _free_port()
    server = await _launch(settings, port, home)
    try:
        created = await _http(port, "/api/sessions", {})
        session_id = json.loads(created.split(b"\r\n\r\n", 1)[1])["session"]["id"]
        path = f"/api/sessions/{session_id}/turns"
        # 두 번째 문장을 받은 순간(답변 도중) 서버를 죽인다
        received = await _http(
            port,
            path,
            {"text": f"__say_then_hang__:{THREE_SENTENCES}"},
            until=b"event: sentence",
            count=2,
        )
        _kill(server, signal.SIGKILL)
    except BaseException:
        _kill(server, signal.SIGKILL)
        raise
    assert received.count(b"event: sentence") == 2

    engine = create_engine_for(settings.database_url)
    try:
        async with create_session_factory(engine)() as db:
            rows = await db.execute(
                select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq)
            )
            saved = [(t.seq, t.role, t.text, t.interrupted) for t in rows.scalars()]
    finally:
        await engine.dispose()
    assert saved[1:] == [
        (1, TurnRole.USER, f"__say_then_hang__:{THREE_SENTENCES}", False),
        (2, TurnRole.ASSISTANT, "첫 문장입니다. 둘째 문장이에요.", True),
    ]

    # 다시 띄운 서버에서 같은 대화가 --resume으로 이어진다
    server = await _launch(settings, port, home)
    try:
        reply = await _http(port, path, {"text": "__say__:다시 왔어요."})
        assert b"event: done" in reply
    finally:
        _kill(server, signal.SIGTERM)
    args = fake_cli.records()[-1]["args"]
    assert args[args.index("--resume") + 1] == FAKE_CLI_SESSION_ID
