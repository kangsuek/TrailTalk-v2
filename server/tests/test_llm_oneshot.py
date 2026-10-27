"""CLI 단발 호출(run_oneshot, 일지 정리용): 인자·환경·결과 검증·실패 구분·시간 초과 정리."""

import asyncio
import json
import time

import pytest

from app.llm.backend import LlmError, LlmProcessError, LlmTimeoutError
from app.llm.claude_cli import build_oneshot_command, oneshot_work_dir, run_oneshot
from tests.conftest import FAKE_TOKEN

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}


def output(structured: object = None, **fields) -> str:
    body = {"type": "result", "subtype": "success", "is_error": False, "result": ""}
    if structured is not None:
        body["structured_output"] = structured
    body.update(fields)
    return json.dumps(body, ensure_ascii=False)


@pytest.fixture
def oneshot(tmp_path, monkeypatch):
    """가짜 CLI 단발 호출이 차례로 낼 출력 줄을 정한다."""
    path = tmp_path / "oneshot.jsonl"

    def set_lines(*lines: str) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setenv("FAKE_CLAUDE_ONESHOT", str(path))
    monkeypatch.delenv("FAKE_CLAUDE_ONESHOT_DELAY", raising=False)
    set_lines(output({"title": "제목"}))
    return set_lines


def oneshot_records(fake_cli) -> list[dict]:
    return [r for r in fake_cli.records() if "--json-schema" in r["args"]]


async def call(fake_cli, prompt: str = "전문", timeout_s: float = 10) -> dict:
    return await run_oneshot(
        fake_cli.settings, prompt, model="haiku", json_schema=SCHEMA, timeout_s=timeout_s
    )


def test_command_turns_off_tools_settings_mcp_and_persistence(make_settings):
    command = build_oneshot_command(make_settings(), model="haiku", json_schema=SCHEMA)
    assert command[:2] == ["claude", "-p"]
    flags = {
        command[i]: command[i + 1] if i + 1 < len(command) else None for i in range(len(command))
    }
    assert flags["--model"] == "haiku"
    assert flags["--output-format"] == "json"
    assert json.loads(flags["--json-schema"]) == SCHEMA
    assert flags["--tools"] == ""
    assert flags["--setting-sources"] == ""
    assert "--strict-mcp-config" in command
    assert "--no-session-persistence" in command
    # 도구 허용·MCP 설정·이어 하기가 없다
    assert not {"--allowedTools", "--mcp-config", "--resume", "--system-prompt"} & set(command)


async def test_returns_structured_output_and_sends_prompt_by_stdin(fake_cli, oneshot, monkeypatch):
    monkeypatch.setenv("TRAILTALK_TEST_OTHER_SECRET", "x")
    long_prompt = "가" * 300_000  # 인자 길이 한도를 넘는 전문도 stdin으로 넘어간다
    assert await call(fake_cli, long_prompt) == {"title": "제목"}

    [record] = oneshot_records(fake_cli)
    assert record["stdin"] == long_prompt
    assert long_prompt not in record["args"]
    assert record["cwd"] == str(oneshot_work_dir(fake_cli.settings))
    assert record["has_token"] is True
    assert record["has_other_secret"] is False  # 허용 목록 밖의 환경 변수는 넘기지 않는다


@pytest.mark.parametrize(
    "line",
    [
        output(is_error=True, result="오류"),  # CLI가 오류로 끝남
        output(None),  # structured_output 없음(스키마를 맞추지 못함)
        output(["목록"]),  # 객체가 아님
        json.dumps(["결과 아님"]),
    ],
)
async def test_error_output_is_llm_error(fake_cli, oneshot, line):
    oneshot(line)
    with pytest.raises(LlmError) as raised:
        await call(fake_cli)
    assert raised.value.code == "llm_error"


async def test_crash_is_process_error_without_token(fake_cli, oneshot):
    oneshot("__crash__")
    with pytest.raises(LlmProcessError) as raised:
        await call(fake_cli)
    assert raised.value.code == "llm_process_exited"
    assert "fake crash" in raised.value.message
    assert FAKE_TOKEN not in raised.value.message


async def test_missing_cli_is_process_error(fake_cli, tmp_path):
    settings = fake_cli.settings.model_copy(update={"claude_cli_path": str(tmp_path / "없음")})
    with pytest.raises(LlmProcessError):
        await run_oneshot(settings, "전문", model="haiku", json_schema=SCHEMA, timeout_s=5)


async def test_timeout_kills_process(fake_cli, oneshot):
    oneshot("__hang__")
    started = time.monotonic()
    with pytest.raises(LlmTimeoutError) as raised:
        await call(fake_cli, timeout_s=1)
    assert raised.value.code == "llm_timeout"
    assert time.monotonic() - started < 5  # 멈춘 프로세스를 기다리지 않는다


async def test_cancel_kills_process(fake_cli, oneshot):
    oneshot("__hang__")
    task = asyncio.create_task(call(fake_cli, timeout_s=60))
    for _ in range(100):  # 가짜 CLI가 떠서 기록을 남길 때까지
        if oneshot_records(fake_cli):
            break
        await asyncio.sleep(0.05)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 5


async def test_successive_calls_use_next_lines(fake_cli, oneshot):
    oneshot(output({"title": "첫째"}), output({"title": "둘째"}))
    assert await call(fake_cli) == {"title": "첫째"}
    assert await call(fake_cli) == {"title": "둘째"}
    assert await call(fake_cli) == {"title": "둘째"}  # 마지막 줄은 계속 쓴다


def test_extract_settings_defaults(make_settings, monkeypatch):
    monkeypatch.delenv("LLM_EXTRACT_MODEL", raising=False)
    monkeypatch.delenv("EXTRACT_TIMEOUT_S", raising=False)
    settings = make_settings()
    assert settings.llm_extract_model == "haiku"
    assert settings.extract_timeout_s == 60
    monkeypatch.setenv("LLM_EXTRACT_MODEL", "gpt")
    with pytest.raises(ValueError):
        make_settings()
