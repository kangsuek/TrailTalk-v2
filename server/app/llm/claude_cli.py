"""Claude Code CLI 상주 프로세스 백엔드 (Spec 5.8).

세션마다 `claude -p`를 stream-json 입출력으로 띄워 두고 턴을 주고받는다.
토큰은 자식 프로세스 환경으로만 넘기고 로그·오류 메시지에 넣지 않는다.

호출 규약: `send()`가 돌려주는 이벤트 스트림은 반드시 `contextlib.aclosing(...)`으로 감싸
끝까지 읽거나 닫는다. 닫지 않고 버리면 턴이 잠긴 채 남는다(매니저가 시간 초과로 강제 정리한다).
"""

import asyncio
import contextlib
import fnmatch
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from app.config import Settings
from app.errors import AppError
from app.llm.backend import LlmProcessError, LlmTimeoutError, TurnInProgressError
from app.llm.events import LlmEvent, TurnFinished, TurnStarted
from app.llm.parser import StreamJsonParser

logger = logging.getLogger("trailtalk.llm")

# 자체 도구 서버(trailtalk) 허용 패턴. 외부 MCP 서버(M5)는 extra_allowed_tools로 더한다
OWN_ALLOWED_TOOLS = ("mcp__trailtalk__*",)
SESSION_KEY = re.compile(r"[A-Za-z0-9_-]{1,64}")
# 자식 프로세스에 넘기는 환경 변수(그 밖의 서버 비밀값·ANTHROPIC_* 키는 넘기지 않는다)
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_*", "TMPDIR", "TZ", "TERM",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
)  # fmt: skip
_STDOUT_LIMIT = 16 * 1024 * 1024
_STDERR_TAIL = 20
_ABORT_GRACE_S = 5.0
_EXIT_WAIT_S = 1.0


def build_command(
    settings: Settings,
    *,
    system_prompt: str,
    model: str,
    resume_id: str | None = None,
    mcp_config_path: Path | None = None,
    extra_allowed_tools: Sequence[str] = (),
) -> list[str]:
    """CLI 실행 인자. 내장 도구는 모두 끄고(`--tools ""`, 웹 검색은 M5) 앱 도구만 허용한다."""
    command = [
        settings.claude_cli_path,
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--model", model,
        "--tools", "",
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--allowedTools", ",".join((*OWN_ALLOWED_TOOLS, *extra_allowed_tools)),
        "--system-prompt", system_prompt,
    ]  # fmt: skip
    if mcp_config_path is not None:
        command += ["--mcp-config", str(mcp_config_path)]
    if resume_id:
        command += ["--resume", resume_id]
    return command


def build_env(settings: Settings) -> dict[str, str]:
    patterns = (*ENV_ALLOWLIST, *settings.cli_env_passthrough)
    env = {k: v for k, v in os.environ.items() if any(fnmatch.fnmatchcase(k, p) for p in patterns)}
    env["ENABLE_TOOL_SEARCH"] = "false"  # MCP 도구 정의를 처음부터 노출(지연 로딩 끔)
    env["DISABLE_AUTOUPDATER"] = "1"  # 출력 형식이 바뀌지 않도록 버전 고정
    if settings.claude_code_oauth_token is not None:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = settings.claude_code_oauth_token.get_secret_value()
    return env


_CLI_SESSION_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def delete_cli_session_file(cli_session_id: str | None) -> bool:
    """CLI가 남긴 대화 기록 파일(~/.claude/projects/<폴더>/<세션 ID>.jsonl)을 지운다.

    자식 CLI는 서버와 같은 HOME을 쓴다(ENV_ALLOWLIST). 이름이 정확히 같은 파일만 지우고,
    그 폴더가 비면 폴더도 지운다.
    """
    if not cli_session_id or not _CLI_SESSION_ID.fullmatch(cli_session_id):
        return False
    deleted = False
    for path in (Path.home() / ".claude" / "projects").glob(f"*/{cli_session_id}.jsonl"):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
            deleted = True
        with contextlib.suppress(OSError):
            path.parent.rmdir()  # 작업 폴더마다 생기는 프로젝트 폴더가 비었으면 함께 지운다
    return deleted


def session_work_dir(settings: Settings, key: str) -> Path:
    """프로세스마다 고유한 작업 폴더(cli_work_dir/<key>/<무작위>).

    종료 때 통째로 지우므로, 같은 키의 옛 프로세스 정리가 새 프로세스 폴더를 지우지 않게
    프로세스마다 따로 만든다(다른 폴더에서도 --resume은 동작한다).
    """
    if not SESSION_KEY.fullmatch(key):
        raise AppError("invalid_session_key", "세션 키 형식이 올바르지 않습니다.", 400)
    base = settings.cli_work_dir.resolve()
    path = (base / key / uuid.uuid4().hex[:12]).resolve()
    if not path.is_relative_to(base / key):
        raise AppError("invalid_session_key", "세션 키 형식이 올바르지 않습니다.", 400)
    return path


class ClaudeCliSession:
    def __init__(
        self,
        key: str,
        command: list[str],
        env: dict[str, str],
        cwd: Path,
        *,
        turn_timeout_s: float,
        secrets: tuple[str, ...] = (),
        model: str = "",
        resumed: bool = False,
    ) -> None:
        self.key = key
        self.model = model
        # 지연 계측용(동작에는 쓰지 않는다): --resume으로 뜬 프로세스인가, 언제 만들어졌나,
        # 마지막 턴 중단을 어떻게 정리했나(clean·terminated·killed)
        self.resumed = resumed
        self.created_at = time.monotonic()
        self.last_abort: str | None = None
        self._command = command
        self._env = env
        self._cwd = cwd
        self._turn_timeout_s = turn_timeout_s
        self._secrets = tuple(s for s in secrets if s)
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL)
        self._lock = asyncio.Lock()
        self._turn_active = False
        self._closing = False
        self._cli_session_id: str | None = None
        self.last_used = time.monotonic()
        self.busy_since: float | None = None

    @property
    def cli_session_id(self) -> str | None:
        return self._cli_session_id

    @property
    def alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and not self._closing
            and self._proc.stdin is not None
            and not self._proc.stdin.is_closing()
        )

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    async def start(self) -> None:
        self._cwd.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=self._cwd,
                env=self._env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STDOUT_LIMIT,
            )
        except OSError as exc:
            shutil.rmtree(self._cwd, ignore_errors=True)
            with contextlib.suppress(OSError):
                self._cwd.parent.rmdir()
            raise LlmProcessError(
                f"Claude CLI를 실행할 수 없습니다({type(exc).__name__}: {self._command[0]})"
            ) from exc
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        logger.info("CLI 프로세스 시작(session=%s, pid=%s)", self.key, self._proc.pid)

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    async def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        while line := await self._proc.stderr.readline():
            text = self._redact(line.decode(errors="replace").rstrip())
            self._stderr_tail.append(text)
            logger.debug("CLI stderr(session=%s): %s", self.key, text)

    async def _write(self, payload: dict) -> None:
        if self._closing:
            raise LlmProcessError("Claude CLI 프로세스를 닫는 중입니다.")
        if not self.alive or self._proc is None or self._proc.stdin is None:
            raise await self._exited_error()
        try:
            self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise await self._exited_error() from exc

    async def _exited_error(self) -> LlmProcessError:
        # stdout EOF 직후에는 종료 코드·stderr가 아직 비어 있을 수 있어 잠깐 기다린다
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._proc.wait(), _EXIT_WAIT_S)
        if self._stderr_task is not None and not self._stderr_task.done():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._stderr_task), _EXIT_WAIT_S)
        code = self._proc.returncode if self._proc else None
        tail = " | ".join(self._stderr_tail) or "stderr 없음"
        return LlmProcessError(f"Claude CLI 프로세스가 종료됐습니다(code={code}): {tail}"[:800])

    async def _read_line(self, timeout: float) -> bytes:
        assert self._proc and self._proc.stdout
        return await asyncio.wait_for(self._proc.stdout.readline(), timeout)

    async def send(self, content: str | list[dict]) -> AsyncIterator[LlmEvent]:
        """사용자 메시지를 보내고 TurnFinished까지 이벤트를 낸다. aclosing으로 감싸 쓴다.

        content는 글이거나 이미지·글 블록 배열(파일 첨부, FR-22)이다."""
        if self._lock.locked():
            raise TurnInProgressError()
        async with self._lock:
            self.busy_since = self.last_used = time.monotonic()
            parser = StreamJsonParser()
            try:
                # 쓰기 도중 취소돼도 이미 보낸 메시지의 턴을 정리하도록 먼저 켠다
                self._turn_active = True
                try:
                    await self._write(
                        {"type": "user", "message": {"role": "user", "content": content}}
                    )
                except LlmProcessError:
                    self._turn_active = False
                    raise
                deadline = time.monotonic() + self._turn_timeout_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        await self._abort_turn(parser)
                        raise LlmTimeoutError(
                            f"Claude 응답이 {self._turn_timeout_s:.0f}초 안에 끝나지 않았습니다."
                        )
                    try:
                        line = await self._read_line(remaining)
                    except TimeoutError:
                        continue
                    if not line:
                        self._turn_active = False
                        raise await self._exited_error()
                    for event in parser.feed(line.decode(errors="replace")):
                        if isinstance(event, TurnStarted) and event.cli_session_id:
                            self._cli_session_id = event.cli_session_id
                        if isinstance(event, TurnFinished):
                            self._turn_active = False
                        yield event
                        if isinstance(event, TurnFinished):
                            return
            finally:
                if self._turn_active:
                    # 소비자가 중간에 그만뒀다(연결 끊김·취소 등): 생성을 멈추고 턴을 정리한다
                    await self._abort_turn(parser)
                self.busy_since = None
                self.last_used = time.monotonic()

    async def _abort_turn(self, parser: StreamJsonParser) -> None:
        """인터럽트를 보내고 이 턴의 result까지 읽어 버린다.

        실패하거나 취소되면 프로세스를 죽인다.
        """
        if not self._turn_active:
            return
        try:
            await self.interrupt()
            deadline = time.monotonic() + _ABORT_GRACE_S
            while self._turn_active and time.monotonic() < deadline:
                line = await self._read_line(max(deadline - time.monotonic(), 0.01))
                if not line:
                    break
                for event in parser.feed(line.decode(errors="replace")):
                    if isinstance(event, TurnFinished):
                        self._turn_active = False
        except asyncio.CancelledError:
            # 취소 중에는 더 기다릴 수 없다(anyio는 await마다 다시 취소한다): 즉시 죽인다
            self.last_abort = "killed"
            self._kill_now()
            raise
        except (TimeoutError, LlmProcessError):
            pass
        except Exception:
            logger.warning("턴 정리 중 예외(session=%s)", self.key, exc_info=True)
        if self._turn_active:
            logger.warning("턴 정리 실패, 프로세스를 닫음(session=%s)", self.key)
            self._turn_active = False
            self.last_abort = "terminated"
            await self._terminate()
        else:
            self.last_abort = "clean"

    async def interrupt(self) -> None:
        if not self._turn_active or not self.alive:
            return
        await self._write(
            {
                "type": "control_request",
                "request_id": f"req_{uuid.uuid4().hex[:12]}",
                "request": {"subtype": "interrupt"},
            }
        )
        logger.info("CLI 인터럽트 전송(session=%s)", self.key)

    def _kill_now(self) -> None:
        """기다리지 않고 프로세스를 죽인다(취소 처리 중에도 안전)."""
        self._closing = True
        self._turn_active = False
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()

    async def _terminate(self) -> None:
        self._closing = True
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.is_closing():
                self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), _ABORT_GRACE_S)
                return
            except TimeoutError:
                pass
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 2)
            except TimeoutError:
                self._kill_now()
                await self._proc.wait()
        except asyncio.CancelledError:
            self._kill_now()
            raise

    async def close(self) -> None:
        try:
            await self._terminate()
        finally:
            if self._stderr_task:
                self._stderr_task.cancel()
                await asyncio.wait([self._stderr_task])  # 바깥 취소는 삼키지 않는다
            shutil.rmtree(self._cwd, ignore_errors=True)
            with contextlib.suppress(
                OSError
            ):  # 같은 키의 다른 프로세스 폴더가 없으면 키 폴더도 지운다
                self._cwd.parent.rmdir()
            logger.info(
                "CLI 프로세스 종료(session=%s, code=%s)",
                self.key,
                self._proc.returncode if self._proc else None,
            )


class ClaudeCliBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def open_session(
        self,
        key: str,
        *,
        system_prompt: str,
        model: str,
        resume_id: str | None = None,
        mcp_config: dict | None = None,
        extra_allowed_tools: Sequence[str] = (),
    ) -> ClaudeCliSession:
        """CLI 세션을 연다.

        mcp_config가 있으면 작업 폴더에 mcp.json(소유자만 읽기)으로 쓰고 --mcp-config로 넘긴다.
        """
        settings = self._settings
        token = settings.claude_code_oauth_token
        cwd = session_work_dir(settings, key)
        mcp_path = None
        secrets = [token.get_secret_value()] if token else []
        try:
            if mcp_config is not None:
                cwd.mkdir(mode=0o700, parents=True, exist_ok=True)
                mcp_path = cwd / "mcp.json"
                fd = os.open(mcp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(mcp_config, f, ensure_ascii=False)
                secrets += _header_secrets(mcp_config)
            session = ClaudeCliSession(
                key,
                build_command(
                    settings,
                    system_prompt=system_prompt,
                    model=model,
                    resume_id=resume_id,
                    mcp_config_path=mcp_path,
                    extra_allowed_tools=extra_allowed_tools,
                ),
                build_env(settings),
                cwd,
                turn_timeout_s=settings.cli_turn_timeout_s,
                secrets=tuple(secrets),
                model=model,
                resumed=resume_id is not None,
            )
        except BaseException:
            shutil.rmtree(cwd, ignore_errors=True)  # 토큰이 든 mcp.json을 남기지 않는다
            raise
        await session.start()
        return session


def _header_secrets(mcp_config: dict) -> list[str]:
    """MCP 설정 헤더의 토큰 값(로그에서 가린다)."""
    values = []
    for server in (mcp_config.get("mcpServers") or {}).values():
        for name, value in (server.get("headers") or {}).items():
            if name.lower() == "authorization" and isinstance(value, str):
                values.append(value.split(" ", 1)[-1])
    return values
