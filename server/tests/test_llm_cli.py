import asyncio
import contextlib
import json
import logging
from contextlib import aclosing
from pathlib import Path

import anyio
import pytest

from app.errors import AppError
from app.llm.backend import LlmProcessError, LlmTimeoutError, TurnInProgressError
from app.llm.claude_cli import ClaudeCliBackend, build_command
from app.llm.events import TextDelta, TurnFinished, TurnStarted
from app.llm.manager import LlmSessionManager
from tests.conftest import FAKE_TOKEN


async def run_turn(session, text: str) -> list:
    async with aclosing(session.send(text)) as stream:
        return [event async for event in stream]


def finished(events: list) -> TurnFinished:
    assert isinstance(events[-1], TurnFinished)
    return events[-1]


async def open_session(fake_cli, key="s1", **kwargs):
    backend = ClaudeCliBackend(fake_cli.settings)
    return await backend.open_session(key, system_prompt="너는 제니야.", model="sonnet", **kwargs)


def test_build_command_has_isolation_and_tool_limits(fake_cli, tmp_path):
    command = build_command(
        fake_cli.settings,
        system_prompt="P",
        model="haiku",
        resume_id="abc",
        mcp_config_path=tmp_path / "m.json",
    )
    assert command[0] == fake_cli.settings.claude_cli_path
    joined = " ".join(command)
    for flag in ["--restricted", "--strict-mcp-config", "--include-partial-messages", "--verbose"]:
        assert flag in command
    assert command[command.index("--tools") + 1] == ""  # 내장 도구는 모두 끈다(웹 검색은 M5)
    assert command[command.index("--allowedTools") + 1] == "mcp__trailtalk__*"
    assert command[command.index("--setting-sources") + 1] == ""
    assert command[command.index("--model") + 1] == "haiku"
    assert command[command.index("--system-prompt") + 1] == "P"
    assert command[command.index("--resume") + 1] == "abc"
    assert "--no-session-persistence" not in joined


async def test_multiple_turns_on_one_process(fake_cli):
    session = await open_session(fake_cli)
    try:
        pid = session.pid
        texts = []
        for question in ["사과?", "바나나?", "둘 다?"]:
            events = await run_turn(session, question)
            assert isinstance(events[0], TurnStarted)
            texts.append(finished(events).text)
            assert "".join(e.text for e in events if isinstance(e, TextDelta)) == texts[-1]
        assert texts[-1] == "사과와 바나나입니다."
        assert session.pid == pid and session.alive
        assert session.cli_session_id
    finally:
        await session.close()
    record = fake_cli.records()[0]
    assert record["ENABLE_TOOL_SEARCH"] == "false"
    assert record["DISABLE_AUTOUPDATER"] == "1"
    assert record["has_token"] is True
    assert "/cli-sessions/s1/" in record["cwd"]


def test_extra_allowed_tools_are_appended_and_empty_list_keeps_default(fake_cli):
    base = build_command(fake_cli.settings, system_prompt="P", model="sonnet")
    assert (
        build_command(fake_cli.settings, system_prompt="P", model="sonnet", extra_allowed_tools=())
        == base
    )
    extra = build_command(
        fake_cli.settings,
        system_prompt="P",
        model="sonnet",
        extra_allowed_tools=["mcp__maps__search", "mcp__maps__route"],
    )
    allowed = extra[extra.index("--allowedTools") + 1]
    assert allowed == "mcp__trailtalk__*,mcp__maps__search,mcp__maps__route"


async def test_rate_limit_events_are_ignored(fake_cli):
    """사용량 막대는 M5. 그 전에는 rate_limit_event가 와도 턴 이벤트로 새지 않는다."""
    session = await open_session(fake_cli)
    try:
        events = await run_turn(session, "사과?")
        assert all(type(e).__name__ != "RateLimitUpdated" for e in events)
        assert finished(events).text
    finally:
        await session.close()


async def test_interrupt_then_next_turn(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.02")
    session = await open_session(fake_cli)
    try:
        events = []
        async with aclosing(session.send("길게 말해줘")) as stream:
            async for event in stream:
                events.append(event)
                if isinstance(event, TextDelta) and len(events) > 5:
                    await session.interrupt()
        result = finished(events)
        assert result.interrupted
        monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0")
        assert not finished(await run_turn(session, "다음")).interrupted
        assert session.alive
    finally:
        await session.close()


async def test_second_send_while_turn_running_is_rejected(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.02")
    session = await open_session(fake_cli)
    try:
        first = session.send("첫 질문")
        await first.__anext__()
        with pytest.raises(TurnInProgressError):
            await session.send("끼어들기").__anext__()
        await first.aclose()  # 소비를 그만두면 턴을 인터럽트로 정리한다
        assert session.alive
        assert finished(await run_turn(session, "다시")).text
    finally:
        await session.close()


async def test_process_crash_raises_and_manager_resumes(fake_cli):
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        await run_turn(session, "안녕")
        cli_id = session.cli_session_id
        with pytest.raises(LlmProcessError) as excinfo:
            await run_turn(session, "__crash__")
        assert "code=3" in excinfo.value.message
        assert "fake crash" in excinfo.value.message
        revived = await manager.get("s1", system_prompt="P", model="sonnet")
        assert revived is not session and revived.alive
        await run_turn(revived, "이어서")
        assert revived.cli_session_id == cli_id
        args = fake_cli.records()[-1]["args"]
        assert args[args.index("--resume") + 1] == cli_id
    finally:
        await manager.shutdown()


async def test_manager_restarts_with_new_model_and_same_context(fake_cli, monkeypatch):
    """대화 모델이 바뀌면(S3-31) 같은 CLI 대화 기록으로 --resume해 새 모델로 다시 띄운다."""
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        await run_turn(session, "안녕")
        cli_id = session.cli_session_id
        assert await manager.get("s1", system_prompt="P", model="sonnet") is session  # 그대로
        switched = await manager.get("s1", system_prompt="P", model="opus")
        assert switched is not session and not session.alive and switched.model == "opus"
        await run_turn(switched, "이어서")
        args = fake_cli.records()[-1]["args"]
        assert args[args.index("--model") + 1] == "opus"
        assert args[args.index("--resume") + 1] == cli_id
    finally:
        await manager.shutdown()


async def test_model_change_after_crash_resumes_with_new_model(fake_cli):
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        await run_turn(session, "안녕")
        cli_id = session.cli_session_id
        with pytest.raises(LlmProcessError):
            await run_turn(session, "__crash__")
        revived = await manager.get("s1", system_prompt="P", model="haiku")
        await run_turn(revived, "이어서")
        args = fake_cli.records()[-1]["args"]
        assert args[args.index("--model") + 1] == "haiku"
        assert args[args.index("--resume") + 1] == cli_id
    finally:
        await manager.shutdown()


async def test_manager_does_not_restart_a_busy_session_for_model_change(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.05")
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        async with contextlib.aclosing(session.send("길게")) as stream:
            await stream.__anext__()
            assert session.busy
            # 답변 중(도구 실행 중 등)에는 닫지 않는다: 다음 턴 시작 때 바뀐다
            assert await manager.get("s1", system_prompt="P", model="opus") is session
            async for _ in stream:
                pass
        assert (await manager.get("s1", system_prompt="P", model="opus")).model == "opus"
    finally:
        await manager.shutdown()


async def test_turn_timeout_with_successful_interrupt(fake_cli):
    fake_cli.settings.cli_turn_timeout_s = 0.3
    session = await open_session(fake_cli)
    try:
        with pytest.raises(LlmTimeoutError):
            await run_turn(session, "__hang_until_interrupt__")
        # 인터럽트로 턴을 정리했으므로 같은 프로세스를 계속 쓴다
        assert session.alive and not session.busy
        assert finished(await run_turn(session, "다음")).text
    finally:
        await session.close()


async def test_turn_timeout_kills_unresponsive_process(fake_cli, monkeypatch):
    monkeypatch.setattr("app.llm.claude_cli._ABORT_GRACE_S", 0.3)
    fake_cli.settings.cli_turn_timeout_s = 0.3
    session = await open_session(fake_cli)
    try:
        with pytest.raises(LlmTimeoutError):
            await run_turn(session, "__hang__")  # 인터럽트도 무시하는 프로세스
        assert not session.alive and not session.busy
    finally:
        await session.close()


async def test_cancellation_mid_turn_kills_and_manager_revives(fake_cli, monkeypatch):
    """클라이언트 연결이 끊긴 것처럼 anyio 취소 범위로 턴을 끊는다.

    Starlette 스트리밍 응답이 연결 끊김을 처리하는 방식과 같다.
    """
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.05")
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        with anyio.move_on_after(0.15):
            async with aclosing(session.send("길게")) as stream:
                async for _ in stream:
                    pass
        assert not session.busy
        assert not session.alive  # 취소 중에는 기다릴 수 없어 즉시 죽였다
        await asyncio.wait_for(session._proc.wait(), 2)
        assert session._proc.returncode < 0  # stdin만 닫힌 게 아니라 kill됐다(생성 중단)
        monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0")
        revived = await manager.get("s1", system_prompt="P", model="sonnet")
        assert revived is not session
        assert finished(await run_turn(revived, "다시")).text
    finally:
        await manager.shutdown()


async def test_abandoned_stream_is_reaped_as_stuck(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.05")
    manager = LlmSessionManager(
        ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600, stuck_timeout_s=0.3
    )
    await manager.start()
    stream = None
    try:
        session = await manager.get("s1", system_prompt="P", model="sonnet")
        stream = session.send("길게")
        await stream.__anext__()  # 읽다가 닫지 않고 버린다
        assert session.busy
        for _ in range(60):
            if manager.active_count == 0 and not session.alive:
                break
            await asyncio.sleep(0.05)
        assert manager.active_count == 0 and not session.alive
    finally:
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.aclose()
        await manager.shutdown()


async def test_child_env_excludes_other_secrets(fake_cli, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    monkeypatch.setenv("TRAILTALK_TEST_OTHER_SECRET", "x")
    session = await open_session(fake_cli)
    try:
        await run_turn(session, "안녕")
    finally:
        await session.close()
    record = fake_cli.records()[-1]
    assert record["has_token"] is True
    assert record["has_anthropic_api_key"] is False
    assert record["has_other_secret"] is False


@pytest.mark.parametrize("key", ["../escape", "/abs", "a/b", "", "x" * 65, "."])
async def test_invalid_session_key_rejected(fake_cli, key):
    with pytest.raises(AppError) as excinfo:
        await open_session(fake_cli, key=key)
    assert excinfo.value.status_code == 400


async def test_start_failure_is_llm_error_and_cleans_dir(fake_cli, tmp_path):
    fake_cli.settings.claude_cli_path = str(tmp_path / "no-such-claude")
    with pytest.raises(LlmProcessError):
        await open_session(fake_cli, key="broken")
    assert not (fake_cli.settings.cli_work_dir / "broken").exists()


async def test_idle_reaper_and_shutdown_cleanup(fake_cli):
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=0.2)
    await manager.start()
    try:
        session = await manager.get("idle", system_prompt="P", model="sonnet")
        work_dir = session._cwd
        assert work_dir.exists()
        for _ in range(100):  # 목록에서 빠진 뒤 프로세스 종료·폴더 삭제까지 기다린다
            if manager.active_count == 0 and not session.alive and not work_dir.exists():
                break
            await asyncio.sleep(0.05)
        assert manager.active_count == 0
        assert not session.alive and not work_dir.exists()
        assert "idle" not in manager._key_locks  # 정리한 세션의 락도 남기지 않는다
        other = await manager.get("other", system_prompt="P", model="sonnet")
    finally:
        await manager.shutdown()
    assert not other.alive
    assert manager.active_count == 0


async def test_token_never_logged(fake_cli, caplog):
    with caplog.at_level(logging.DEBUG, logger="trailtalk.llm"):
        session = await open_session(fake_cli)
        try:
            await run_turn(session, "안녕")
            with pytest.raises(LlmProcessError) as excinfo:
                await run_turn(session, "__crash__")
        finally:
            await session.close()
    assert FAKE_TOKEN not in caplog.text
    assert FAKE_TOKEN not in excinfo.value.message
    assert "fake claude ready" in caplog.text  # stderr는 DEBUG 로그로 흘러간다


async def test_close_and_reopen_same_key_keeps_new_work_dir(fake_cli):
    """옛 프로세스 정리와 같은 키의 새 프로세스 기동이 겹쳐도 새 작업 폴더는 남는다."""
    manager = LlmSessionManager(ClaudeCliBackend(fake_cli.settings), idle_timeout_s=600)
    try:
        old = await manager.get("k", system_prompt="P", model="sonnet")
        closing = asyncio.create_task(manager.close("k"))
        await asyncio.sleep(0)
        new = await manager.get("k", system_prompt="P", model="sonnet")
        await closing
        assert new is not old and new.alive
        assert new._cwd.exists() and new._cwd != old._cwd and not old._cwd.exists()
        assert finished(await run_turn(new, "안녕")).text
    finally:
        await manager.shutdown()
    assert not (fake_cli.settings.cli_work_dir / "k").exists()


async def test_mcp_config_written_privately_and_passed(fake_cli):
    backend = ClaudeCliBackend(fake_cli.settings)
    config = {
        "mcpServers": {
            "trailtalk": {
                "type": "http",
                "url": "http://127.0.0.1:8000/internal/mcp/",
                "headers": {
                    "Authorization": "Bearer secret-mcp-token",
                    "X-TrailTalk-Session": "s1",
                },
            }
        }
    }
    session = await backend.open_session("s1", system_prompt="P", model="sonnet", mcp_config=config)
    try:
        await run_turn(session, "안녕")  # 가짜 CLI가 인자 로그를 남길 때까지 한 턴 돌린다
        args = fake_cli.records()[-1]["args"]
        path = Path(args[args.index("--mcp-config") + 1])
        assert path.parent == session._cwd
        assert json.loads(path.read_text()) == config
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700  # mcp.json이 든 폴더도 소유자만
        assert "secret-mcp-token" not in " ".join(args)  # 인자(프로세스 목록)에는 값이 없다
        assert "secret-mcp-token" not in session._redact("auth Bearer secret-mcp-token 실패")
    finally:
        await session.close()
    assert not path.exists()


async def test_mcp_config_removed_when_open_fails(fake_cli, monkeypatch):
    import app.llm.claude_cli as claude_cli

    def broken(*args, **kwargs):
        raise ValueError("bad args")

    monkeypatch.setattr(claude_cli, "build_command", broken)
    backend = ClaudeCliBackend(fake_cli.settings)
    config = {"mcpServers": {"trailtalk": {"headers": {"Authorization": "Bearer t"}}}}
    with pytest.raises(ValueError):
        await backend.open_session("s1", system_prompt="P", model="sonnet", mcp_config=config)
    assert not list(fake_cli.settings.cli_work_dir.glob("**/mcp.json"))
