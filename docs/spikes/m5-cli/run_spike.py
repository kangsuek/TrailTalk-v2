"""M5-01 CLI 도구 권한 스파이크 재현 스크립트. 실제 Claude CLI를 부르므로 구독 사용량이 든다.

서버 코드(app.llm.claude_cli)의 환경 구성·CLI 경로를 그대로 쓰고 `Settings()`가 .env를 읽는다
(이 스크립트는 값을 출력하지 않는다). 모든 호출은 haiku, 한 턴, 짧은 프롬프트다.

사용: cd server && uv run python ../docs/spikes/m5-cli/run_spike.py <check> [--keep]
  allow     ① 허용 밖 MCP 도구 호출 차단 여부(가짜 stdio 서버, 호출 기록 파일로 판정)
  fetch     ② 내장 WebFetch가 localhost·사설·메타데이터 주소에 가는지(로컬 HTTP 서버 적중 여부)
  names     ③ 전체 도구 이름 64자 한도(CLI 호출 없음. 이름 길이 계산)
  latency   ④ 더미 도구 0·20·60개일 때 첫 토큰 지연·입력 토큰
  events    ⑤ WebSearch·WebFetch(외부 주소) stream-json 이벤트 원문 저장
결과(원문 이벤트·요약)는 ../docs/spikes/m5-cli/logs/<check>.json 에 쓴다(경로·토큰은 가림).
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "server"))

from app.config import Settings  # noqa: E402
from app.llm.claude_cli import build_env  # noqa: E402

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"
MODEL = "haiku"
TIMEOUT_S = 120
SCRUB = re.compile(r"/(?:private/)?(?:tmp|var/folders|Users)/[^\"\s\\]*")


def scrub(text: str) -> str:
    return SCRUB.sub("<path>", text)


async def run_cli(
    prompt: str,
    *,
    tools: str = "",
    allowed: str = "",
    disallowed: str = "",
    mcp_config: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """claude -p 한 턴을 stream-json으로 실행하고 이벤트·지연을 돌려준다."""
    settings = Settings()
    cmd = [
        settings.claude_cli_path, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--model", MODEL, "--tools", tools, "--restricted", "--strict-mcp-config",
        "--setting-sources", "", "--no-session-persistence",
    ]  # fmt: skip
    if allowed:
        cmd += ["--allowedTools", allowed]
    if disallowed:
        cmd += ["--disallowedTools", disallowed]
    if mcp_config:
        cmd += ["--mcp-config", str(mcp_config)]
    env = build_env(settings) | (extra_env or {})
    cwd = Path(tempfile.mkdtemp(prefix="m5spike-"))
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    first_delta = None
    events: list[dict] = []

    async def read() -> None:
        nonlocal first_delta
        assert proc.stdout
        async for raw in proc.stdout:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            events.append(event)
            if first_delta is None and event.get("type") == "stream_event":
                inner = event.get("event", {})
                if inner.get("type") == "content_block_delta":
                    first_delta = time.monotonic() - started

    try:
        await asyncio.wait_for(read(), TIMEOUT_S)
    except TimeoutError:
        proc.kill()
    await proc.wait()
    token = settings.claude_code_oauth_token
    secret = token.get_secret_value() if token else None
    dump = scrub(json.dumps(events, ensure_ascii=False))
    if secret:
        dump = dump.replace(secret, "***")
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "cmd_flags": [a for a in cmd if a.startswith("--")],
        "elapsed_s": round(time.monotonic() - started, 2),
        "first_delta_s": None if first_delta is None else round(first_delta, 2),
        "usage": result.get("usage"),
        "is_error": result.get("is_error"),
        "result_text": scrub(str(result.get("result", ""))[:500]),
        "events": json.loads(dump),
    }


def write_log(name: str, data: object) -> None:
    LOGS.mkdir(exist_ok=True)
    (LOGS / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"기록: {LOGS / (name + '.json')}")


def fake_config(tmp: Path, extra_tools: int = 0) -> tuple[Path, Path]:
    """가짜 서버 mcp.json(0600)과 호출 기록 파일 경로."""
    tmp.mkdir(parents=True, exist_ok=True)
    call_log = tmp / "calls.log"
    config = tmp / "mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"fake": {
            "command": sys.executable, "args": [str(HERE / "fake_mcp.py")],
            "env": {"CALL_LOG": str(call_log), "EXTRA_TOOLS": str(extra_tools)},
        }}}),
        encoding="utf-8",
    )  # fmt: skip
    config.chmod(0o600)
    return config, call_log


def called(call_log: Path) -> list[str]:
    return call_log.read_text().split() if call_log.exists() else []


def tool_events(events: list[dict]) -> list[dict]:
    """assistant tool_use와 user tool_result만 추려 판정 근거로 남긴다."""
    out = []
    for e in events:
        for block in (e.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                out.append(
                    {
                        "type": block["type"],
                        **{
                            k: block[k]
                            for k in ("name", "input", "content", "is_error")
                            if k in block
                        },
                    }
                )  # noqa: E501
    return out


async def check_allow() -> None:
    summary = {}
    with tempfile.TemporaryDirectory(prefix="m5allow-") as d:
        tmp = Path(d)
        prompt = "도구 allowed_ping과 denied_ping을 각각 한 번씩 호출하고 결과를 한 줄로 알려줘."
        cases = {
            "allowedTools만(허용 밖 호출 시도)": dict(allowed="mcp__fake__allowed_ping"),
            "allowedTools+disallowedTools": dict(
                allowed="mcp__fake__allowed_ping", disallowed="mcp__fake__denied_ping"
            ),
        }
        for label, kw in cases.items():
            config, call_log = fake_config(tmp / f"case{len(summary)}")  # 사례별 폴더
            result = await run_cli(prompt, mcp_config=config, **kw)
            summary[label] = {
                "서버가 받은 호출": called(call_log),
                "tool 이벤트": tool_events(result["events"]),
                "result": result["result_text"],
            }
            print(label, "→ 서버가 받은 호출:", called(call_log))
    write_log("allow", summary)


class _Hit(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _Hit.hits.append(self.path)
        body = b"<html><body>SPIKE-MARKER hello</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


async def check_fetch() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hit)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    summary = {}
    targets = {
        "localhost": f"http://localhost:{port}/a",
        "127.0.0.1": f"http://127.0.0.1:{port}/b",
        "메타데이터 169.254.169.254(응답 없음이 정상, CLI 판단만 본다)": "http://169.254.169.254/latest/meta-data/",
    }
    rule_sets = {
        "WebFetch 전체 허용": dict(allowed="WebFetch"),
        "도메인 허용 규칙만(example.com)": dict(allowed="WebFetch(domain:example.com)"),
        "WebFetch 허용 + localhost·127.0.0.1 거부 규칙": dict(
            allowed="WebFetch", disallowed="WebFetch(domain:localhost),WebFetch(domain:127.0.0.1)"
        ),
    }
    for rname, kw in rule_sets.items():
        for tname, url in targets.items():
            _Hit.hits.clear()
            result = await run_cli(
                f"WebFetch 도구로 {url} 를 읽고 본문에 SPIKE-MARKER가 있는지 한 줄로 알려줘.",
                tools="WebFetch", **kw,
            )  # fmt: skip
            summary[f"{rname} | {tname}"] = {
                "로컬 서버 적중": list(_Hit.hits),
                "tool 이벤트": tool_events(result["events"]),
                "result": result["result_text"],
            }
            print(f"{rname} | {tname} → 적중 {_Hit.hits}")
    server.shutdown()
    write_log("fetch", summary)


def check_names() -> None:
    """CLI 전체 도구 이름은 mcp__<서버>__<도구>. 모델 API 한도 64자(문서 확인용 계산)."""
    rows = []
    for server in ("trailtalk", "a" * 32):
        for tool in ("save_note", "search_conversations", "t" * 40):
            full = f"mcp__{server}__{tool}"
            rows.append({"name": full, "len": len(full), "over_64": len(full) > 64})
    write_log("names", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=1))


async def check_latency() -> None:
    summary = {}
    with tempfile.TemporaryDirectory(prefix="m5lat-") as d:
        for count in (0, 20, 60):
            runs = []
            for i in range(3):
                config, call_log = fake_config(Path(d) / f"{count}-{i}", count)
                result = await run_cli(
                    "아무 도구도 쓰지 말고 '네'라고만 답해줘.",
                    allowed="mcp__fake__*", mcp_config=config,
                    extra_env={"ENABLE_TOOL_SEARCH": "false"},
                )  # fmt: skip
                usage = result["usage"] or {}
                runs.append(
                    {
                        "first_delta_s": result["first_delta_s"],
                        "elapsed_s": result["elapsed_s"],
                        "input_tokens": usage.get("input_tokens"),
                        "cache_creation": usage.get("cache_creation_input_tokens"),
                        "cache_read": usage.get("cache_read_input_tokens"),
                    }
                )
            summary[f"더미 도구 {count}개(+기본 2)"] = runs
            print(count, runs)
    write_log("latency", summary)


async def check_events() -> None:
    summary = {}
    cases = (
        ("WebSearch", "WebSearch로 '파이썬 3.14 출시일'을 검색하고 한 줄로 알려줘."),
        ("WebFetch", "WebFetch로 https://example.com 을 읽고 제목을 한 줄로 알려줘."),
    )
    for label, prompt in cases:
        tools = allowed = label
        result = await run_cli(prompt, tools=tools, allowed=allowed)
        summary[label] = {
            "tool 이벤트": tool_events(result["events"]),
            "전체 이벤트(원문)": result["events"],
        }
        print(label, "tool 이벤트", len(summary[label]["tool 이벤트"]))
    write_log("events", summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("check", choices=["allow", "fetch", "names", "latency", "events"])
    args = parser.parse_args()
    if args.check == "names":
        check_names()
    else:
        asyncio.run(
            {"allow": check_allow, "fetch": check_fetch,
             "latency": check_latency, "events": check_events}[args.check]()
        )  # fmt: skip


if __name__ == "__main__":
    main()
