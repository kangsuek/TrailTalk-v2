"""외부 MCP의 CLI 연결·이벤트(M5-13). 시험 항목 ①~⑥(⑦ 화면 표시는 web/src의 시험).

실제 Claude CLI·외부 서비스는 쓰지 않는다: 가짜 CLI(tests/fakes/fake_claude.py)가 mcp.json의 stdio
서버(tests/fakes/fake_mcp.py)를 실제로 띄워 tools/call을 보낸다.
"""

# ruff: noqa: F811  (다른 시험 모듈의 fixture를 가져와 쓴다)
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.external_mcp import LAUNCHER, load_external_mcp
from app.llm.claude_cli import ClaudeCliBackend, purge_mcp_leftovers
from app.llm.events import ToolFinished, TurnFinished
from app.main import create_app
from tests.conftest import FAKE_TOKEN
from tests.test_llm_cli import run_turn
from tests.test_sessions import events_of, home, hook_llm, start, turns_of  # noqa: F401

FAKE_MCP = Path(__file__).parent / "fakes" / "fake_mcp.py"
SECRET = "sk-fake-external-secret-0451"
ENVIRON = {"MCP_FAKE_API_KEY": SECRET, "MCP_WEB_TOKEN": "web-token-0451"}


def fake_server(calls: Path, **extra) -> dict:
    entry = {
        "name": "fake",
        "command": sys.executable,
        "args": [str(FAKE_MCP)],
        "env": {"CALL_LOG": str(calls), "FAKE_API_KEY": "${MCP_FAKE_API_KEY}"},
        "allowed_tools": [
            "allowed_ping",
            "probe",
            "leak",
            "leak_error",
            "long",
            "searchish",
        ],
        "denied_tools": ["denied_ping"],
    }
    entry.update(extra)
    return entry


def web_server() -> dict:
    return {
        "name": "web",
        "url": "https://mcp.example.com/v1?mode=ro",
        "headers": {"Authorization": "Bearer ${MCP_WEB_TOKEN}", "X-Region": "kr-seoul"},
        "allowed_tools": ["lookup"],
    }


@pytest.fixture
def config_path(tmp_path):
    folder = tmp_path / "mcpcfg"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)

    def write(servers) -> Path:
        path = folder / "mcp-servers.yaml"
        path.write_text(yaml.safe_dump({"servers": servers}))
        path.chmod(0o600)
        return path

    return write


@pytest.fixture
def calls(tmp_path) -> Path:
    return tmp_path / "calls.log"


def recorded(calls: Path) -> list[str]:
    return calls.read_text().split() if calls.exists() else []


@pytest.fixture
def external(config_path, calls):
    return load_external_mcp(config_path([fake_server(calls), web_server()]), ENVIRON)


async def open_with(fake_cli, external, key="s1"):
    backend = ClaudeCliBackend(fake_cli.settings, external_mcp=external)
    return await backend.open_session(
        key,
        system_prompt="너는 제니야.",
        model="sonnet",
        mcp_config={"mcpServers": {"trailtalk": {"type": "http", "url": "http://127.0.0.1:1/"}}},
    )


async def cli_args(fake_cli, session) -> list[str]:
    await run_turn(session, "안녕")  # 가짜 CLI가 인자 로그를 남길 때까지 한 턴 돌린다
    return fake_cli.records()[-1]["args"]


def flag(args: list[str], name: str) -> list[str]:
    return args[args.index(name) + 1].split(",") if name in args else []


# ① 구성 파일 생성·권한 0600·종료·시작 때 정리


async def test_mcp_json_is_written_0600_in_a_private_dir_and_removed_on_close(fake_cli, external):
    session = await open_with(fake_cli, external)
    try:
        args = await cli_args(fake_cli, session)
        path = Path(args[args.index("--mcp-config") + 1])
        assert path.parent == session._cwd and path.name == "mcp.json"
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        servers = json.loads(path.read_text())["mcpServers"]
        assert set(servers) == {"trailtalk", "fake", "web"}
        # 인자(프로세스 목록)에는 비밀도 mcp.json 내용도 없다
        joined = " ".join(args)
        assert (
            SECRET not in joined and "web-token-0451" not in joined and "mcpServers" not in joined
        )
    finally:
        await session.close()
    assert not path.exists() and not path.parent.exists()


async def test_empty_work_folders_are_private_and_removed_on_close(fake_cli, external):
    session = await open_with(fake_cli, external)
    try:
        work = session._cwd / "mcp-fake"
        assert work.is_dir() and work.stat().st_mode & 0o777 == 0o700
        assert list(work.iterdir()) == []
        assert not (session._cwd / "mcp-web").exists()  # http 서버는 작업 폴더가 필요 없다
    finally:
        await session.close()
    assert not work.exists()


async def test_mcp_json_and_folders_removed_when_open_fails(fake_cli, external, monkeypatch):
    import app.llm.claude_cli as claude_cli

    def broken(*args, **kwargs):
        raise ValueError("bad args")

    monkeypatch.setattr(claude_cli, "build_command", broken)
    backend = ClaudeCliBackend(fake_cli.settings, external_mcp=external)
    with pytest.raises(ValueError):
        await backend.open_session("s1", system_prompt="P", model="sonnet")
    base = fake_cli.settings.cli_work_dir
    assert not list(base.glob("**/mcp.json")) and not list(base.glob("**/mcp-fake"))


def test_startup_purges_leftover_mcp_files_only(fake_cli):
    base = fake_cli.settings.cli_work_dir
    old = base / "session-key" / "abc123"
    (old / "mcp-fake").mkdir(parents=True)
    (old / "mcp-fake" / "scratch").write_text("x")
    (old / "mcp.json").write_text('{"secret": "left over"}')
    (old / "other.txt").write_text("keep")
    (base / "oneshot").mkdir()
    outside = base.parent / "outside"
    outside.mkdir()
    (outside / "mcp.json").write_text("not ours")
    (old / "mcp-link").symlink_to(outside)  # 심볼릭 링크는 링크만 지우고 대상은 건드리지 않는다
    assert purge_mcp_leftovers(fake_cli.settings) == 3
    assert not (old / "mcp.json").exists() and not (old / "mcp-fake").exists()
    assert not (old / "mcp-link").is_symlink()
    assert (old / "other.txt").read_text() == "keep" and (outside / "mcp.json").exists()
    assert purge_mcp_leftovers(fake_cli.settings) == 0


def test_server_start_purges_leftover_mcp_json(fake_cli):
    leftover = fake_cli.settings.cli_work_dir / "k" / "p1" / "mcp.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}")
    with TestClient(create_app(fake_cli.settings)):
        assert not leftover.exists()


# ② stdio·http 구성과 치환, 허용·차단 인자


async def test_stdio_and_http_entries_with_substituted_secrets(fake_cli, external):
    session = await open_with(fake_cli, external)
    try:
        args = await cli_args(fake_cli, session)
        config = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())["mcpServers"]
    finally:
        await session.close()
    stdio, http = config["fake"], config["web"]
    assert stdio["type"] == "stdio" and stdio["env"]["FAKE_API_KEY"] == SECRET
    assert stdio["env"]["CALL_LOG"].endswith("calls.log")
    # 서버 python이 실행기를 -I로 띄우고, 실행기가 셸 없이 외부 명령으로 바꾼다
    assert stdio["command"] == sys.executable
    launcher_args = stdio["args"]
    assert launcher_args[:2] == ["-I", str(LAUNCHER)]
    assert launcher_args[launcher_args.index("--") + 1 :] == [sys.executable, str(FAKE_MCP)]
    assert launcher_args[launcher_args.index("--env") + 1] == "CALL_LOG,FAKE_API_KEY"
    assert SECRET not in json.dumps(launcher_args)  # 비밀은 env에만, args에는 없다
    assert http == {
        "type": "http",
        "url": "https://mcp.example.com/v1?mode=ro",
        "headers": {"Authorization": "Bearer web-token-0451", "X-Region": "kr-seoul"},
    }
    assert config["trailtalk"]["url"] == "http://127.0.0.1:1/"  # 자체 도구 서버 항목은 그대로


async def test_allowed_tools_get_full_names_without_wildcards_for_external(fake_cli, external):
    session = await open_with(fake_cli, external)
    try:
        args = await cli_args(fake_cli, session)
    finally:
        await session.close()
    allowed = flag(args, "--allowedTools")
    assert allowed[:2] == ["mcp__trailtalk__*", "WebSearch"]
    assert "mcp__fake__allowed_ping" in allowed and "mcp__web__lookup" in allowed
    assert [a for a in allowed if "*" in a] == ["mcp__trailtalk__*"]
    assert "mcp__fake__denied_ping" not in allowed
    assert flag(args, "--disallowedTools") == ["mcp__fake__denied_ping"]
    assert args[args.index("--tools") + 1] == "WebSearch"  # 내장 도구는 그대로


async def test_without_external_servers_the_command_has_no_disallowed_tools(fake_cli):
    backend = ClaudeCliBackend(fake_cli.settings)
    session = await backend.open_session("s1", system_prompt="P", model="sonnet")
    try:
        args = await cli_args(fake_cli, session)
    finally:
        await session.close()
    assert "--disallowedTools" not in args and "--mcp-config" not in args
    assert flag(args, "--allowedTools") == ["mcp__trailtalk__*", "WebSearch"]


def test_missing_or_blank_secret_variable_stops_the_server(make_settings, config_path, calls):
    path = config_path([fake_server(calls)])
    from app.external_mcp import ExternalMcpConfigError

    for environ in ({}, {"MCP_FAKE_API_KEY": ""}):
        with pytest.raises(ExternalMcpConfigError, match="MCP_FAKE_API_KEY"):
            load_external_mcp(path, environ)


# ③ 실행 격리: 셸 없음·최소 환경·빈 작업 폴더


def launch(
    workdir: Path, env_names: str, command: list[str], env: dict
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(LAUNCHER),
            "--cwd",
            str(workdir),
            "--env",
            env_names,
            "--",
            *command,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


PROBE = (
    "import os, json, sys;"
    "print(json.dumps([os.getcwd(), sorted(os.environ), sys.argv[1:], os.listdir('.')]))"
)


def test_launcher_runs_without_shell_in_the_empty_dir_with_a_minimal_environment(tmp_path):
    workdir = tmp_path / "w"
    workdir.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp_path),
        "KEY": "from-config",
        "OTHER_SECRET": "must-not-pass",
        "CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN,
        "OPENAI_API_KEY": "sk-openai",
        "SHELL": "/bin/zsh",
        "USER": "someone",
    }
    done = launch(workdir, "KEY", [sys.executable, "-c", PROBE, "$HOME;echo hi", "`id`"], env)
    assert done.returncode == 0, done.stderr
    cwd, names, argv, listing = json.loads(done.stdout)
    assert Path(cwd).resolve() == workdir.resolve() and listing == []
    assert argv == ["$HOME;echo hi", "`id`"]  # 셸이 해석하지 않는다
    # 남는 환경: PATH·HOME·LANG·TMPDIR + env에 적은 변수(파이썬 자신이 더하는 로케일 값은 제외)
    assert {"PATH", "HOME", "LANG", "TMPDIR", "KEY"} <= set(names)
    forbidden = {"OTHER_SECRET", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "SHELL", "USER"}
    assert not forbidden & set(names)
    assert set(names) - {"PATH", "HOME", "LANG", "TMPDIR", "KEY"} <= {
        "LC_CTYPE",
        "__CF_USER_TEXT_ENCODING",
    }


def test_launcher_refuses_relative_commands_and_missing_work_dirs(tmp_path):
    base_env = {"PATH": os.environ["PATH"]}
    relative = launch(tmp_path, "", ["python3", "-c", "print(1)"], base_env)
    assert relative.returncode == 127 and "절대 경로" in relative.stderr and not relative.stdout
    missing = launch(tmp_path / "nope", "", [sys.executable, "-c", "print(1)"], base_env)
    assert missing.returncode == 127 and "작업 폴더" in missing.stderr
    secret_arg = launch(tmp_path, "", ["/no/such/binary", "--token=abc123"], base_env)
    assert secret_arg.returncode == 127 and "abc123" not in secret_arg.stderr


async def test_isolation_holds_through_the_whole_chain(fake_cli, external, monkeypatch):
    """가짜 CLI → 실행기 → 외부 서버를 실제로 띄워 서버가 본 작업 폴더·환경을 확인한다."""
    monkeypatch.setenv("TRAILTALK_TEST_OTHER_SECRET", "must-not-reach-the-external-server")
    session = await open_with(fake_cli, external)
    try:
        events = await run_turn(session, "__mcp__:mcp__fake__probe")
        done = next(e for e in events if isinstance(e, ToolFinished))
        probe = json.loads(done.result_text)
        assert Path(probe["cwd"]).resolve() == (session._cwd / "mcp-fake").resolve()
        assert {"FAKE_API_KEY", "CALL_LOG", "PATH"} <= set(probe["env"])
        assert "TRAILTALK_TEST_OTHER_SECRET" not in probe["env"]
        assert not {"CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY"} & set(probe["env"])
    finally:
        await session.close()


# ④ tool 이벤트 변환


@pytest.fixture
def ext_api(fake_cli, home, config_path, calls, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "multiturn")
    monkeypatch.setenv("MCP_FAKE_API_KEY", SECRET)
    monkeypatch.setenv("MCP_WEB_TOKEN", "web-token-0451")
    settings = fake_cli.settings.model_copy(
        update={"mcp_servers_path": config_path([fake_server(calls), web_server()])}
    )
    with TestClient(create_app(settings)) as client:
        client.fake_cli = fake_cli
        yield client


def turn_raw(api, session_id: str, text: str):
    response = api.post(f"/api/sessions/{session_id}/turns", json={"text": text})
    assert response.status_code == 200, response.text
    return response, events_of(response)


def tools_of(events) -> list:
    return [e for e in events if e.type == "tool"]


def test_external_tool_events_keep_prefix_hide_input_and_summarize_the_result(ext_api, calls):
    session_id = start(ext_api)["session"]["id"]
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__allowed_ping")
    tools = tools_of(events)
    assert [t.phase for t in tools] == ["start", "call", "end"]
    assert {t.name for t in tools} == {"mcp__fake__allowed_ping"}  # 접두사를 포함한 전체 이름
    assert tools[1].input is None  # CLI 이벤트에는 입력이 있었지만 보내지 않는다
    assert tools[2].summary.model_dump() == {"kind": "result", "result": "allowed_ping ok"}
    assert tools[2].is_error is False
    assert recorded(calls) == ["allowed_ping"]


def test_external_result_is_cut_at_2000_chars(ext_api):
    session_id = start(ext_api)["session"]["id"]
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__long")
    assert tools_of(events)[2].summary.result == "가" * 2000


def test_external_result_is_not_stored_and_never_becomes_a_source(ext_api):
    session_id = start(ext_api)["session"]["id"]
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__searchish")
    end = tools_of(events)[2]
    assert end.summary.kind == "result"  # web_search 요약(출처 호스트)이 되지 않는다
    assert "evil.example" in end.summary.result  # 결과는 글자 그대로 보인다
    stored = turns_of(ext_api, session_id)
    assert all(t.sources in (None, []) for t in stored)
    dumped = " ".join(str(vars(t)) for t in stored)
    assert "evil.example" not in dumped and "악성" not in dumped  # 도구 결과는 DB에 없다


def test_a_tool_outside_the_allow_list_is_denied_and_the_server_is_never_called(ext_api, calls):
    session_id = start(ext_api)["session"]["id"]
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__denied_ping")
    end = tools_of(events)[2]
    assert end.is_error is True and end.summary is None
    assert recorded(calls) == []  # 서버를 띄우지도 않았다
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__never_listed")
    assert tools_of(events)[2].is_error is True and recorded(calls) == []


def test_external_tool_error_has_no_summary(ext_api):
    session_id = start(ext_api)["session"]["id"]
    _, events = turn_raw(ext_api, session_id, "__mcp__:mcp__fake__leak_error")
    end = tools_of(events)[2]
    assert end.is_error is True and end.summary is None


# ⑤ 비밀 가림


def test_secret_never_reaches_the_screen_events_or_logs(ext_api, caplog):
    caplog.set_level(logging.DEBUG)
    session_id = start(ext_api)["session"]["id"]
    bodies = []
    for tool in ("leak", "leak_error", "allowed_ping"):
        response, events = turn_raw(ext_api, session_id, f"__mcp__:mcp__fake__{tool}")
        bodies.append(response.text)
        if tool == "leak":
            assert tools_of(events)[2].summary.result == "key is ***"
    assert SECRET not in "".join(bodies)
    assert SECRET not in caplog.text and "web-token-0451" not in caplog.text
    assert "사용자 발화 일부" not in caplog.text  # 도구 인자도 로그에 남기지 않는다
    startup = " ".join(r.getMessage() for r in caplog.get_records("setup"))
    assert "https://mcp.example.com/v1" in startup and "mode=ro" not in startup  # 등록 로그
    assert SECRET not in startup and "web-token-0451" not in startup
    stored = " ".join(str(vars(t)) for t in turns_of(ext_api, session_id))
    assert SECRET not in stored


async def test_redaction_covers_headers_env_values_and_error_message(fake_cli, external):
    session = await open_with(fake_cli, external)
    try:
        redact = session._redact
        # env 값 전체와 headers 값 전체·토큰 부분, 변수 값
        assert redact(f"x {SECRET} y") == "x *** y"
        assert redact("Bearer web-token-0451") == "***"
        assert redact("token web-token-0451!") == "token ***!"
        assert redact("kr-seoul") == "***"  # 비밀이 아닌 고정 헤더 값도 값 전체를 가린다
        assert FAKE_TOKEN not in redact(f"oauth {FAKE_TOKEN}")
        # CLI 결과의 error_message와 도구 결과 글
        error = TurnFinished(text="", is_error=True, error_message=f"401 {SECRET} rejected")
        assert SECRET not in session._redact_event(error).error_message
        result = ToolFinished(tool_use_id="t", is_error=True, result_text=f"bad {SECRET}")
        assert session._redact_event(result).result_text == "bad ***"
    finally:
        await session.close()


async def test_external_server_stderr_is_not_logged_or_put_in_errors(fake_cli, external, caplog):
    caplog.set_level(logging.DEBUG)
    session = await open_with(fake_cli, external)
    try:
        from app.llm.backend import LlmProcessError

        with pytest.raises(LlmProcessError) as excinfo:
            await run_turn(session, "__crash__")
    finally:
        await session.close()
    assert "stderr 생략" in excinfo.value.message
    assert "fake crash" not in excinfo.value.message
    assert "fake crash" not in caplog.text and "fake claude ready" not in caplog.text


# ⑥ 외부 도구 직후 턴의 쓰기 도구 검증


def test_external_tool_turns_on_the_write_tool_guard_until_the_turn_ends(ext_api):
    session_id = start(ext_api)["session"]["id"]
    seen = []

    def on_event(event):
        runtime = ext_api.app.state.runtimes.get(session_id)
        if isinstance(event, ToolFinished):
            seen.append(runtime.web_content_seen)

    hook_llm(ext_api, on_event)
    turn_raw(ext_api, session_id, "__mcp__:mcp__fake__allowed_ping")
    assert seen == [True]  # save_note 등이 웹 검색 직후와 같은 검증을 받는다(app/mcp/server.py)
    assert ext_api.app.state.runtimes.get(session_id).web_content_seen is False  # 다음 턴은 꺼짐


def test_own_tools_do_not_turn_the_guard_on(ext_api):
    session_id = start(ext_api)["session"]["id"]
    seen = []
    hook_llm(
        ext_api,
        lambda e: (
            seen.append(ext_api.app.state.runtimes.get(session_id).web_content_seen)
            if isinstance(e, ToolFinished)
            else None
        ),
    )
    ext_api.app.state.runtimes.get(session_id).web_content_seen = False
    from tests.test_sessions import turn

    turn(ext_api, session_id, "안녕")  # multiturn 녹화의 첫 턴(도구 없음)
    assert seen == []
