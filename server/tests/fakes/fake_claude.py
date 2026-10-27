"""테스트용 가짜 Claude CLI: 녹화한 stream-json 출력(tests/fixtures/claude_cli)을 재생한다.

환경 변수
- FAKE_CLAUDE_FIXTURE: 재생할 녹화 이름(기본 multiturn). result 기준으로 턴을 나눠 n번째 사용자
  메시지에 n번째 턴을 재생하고, 마지막 턴 이후에는 마지막 턴을 반복한다.
- FAKE_CLAUDE_DELAY: 이벤트 사이 지연(초). 인터럽트 테스트용.
- FAKE_CLAUDE_ARGS_LOG: 받은 인자·환경을 JSON 한 줄씩 기록할 파일(토큰은 존재 여부만).
메시지 내용이 "__crash__"이면 종료 코드 3으로 죽는다. "__hang__"이면 아무것도 출력하지 않고
인터럽트도 무시한다. "__hang_until_interrupt__"이면 멈춰 있다가 인터럽트가 오면 중단 결과를 낸다.
"__say__:<글>"이면 녹화 대신 <글>을 몇 글자씩 text_delta로 보내고 정상 결과로 끝낸다
(여러 문장 답변용).
"__say_then_crash__:<글>"은 글을 보낸 뒤 죽고, "__say_then_hang__:<글>"은 글을 보낸 뒤
"__hang_until_interrupt__"처럼 멈춘다(답변 도중 끊김·서버 강제 종료 시험용).
content가 블록 배열이면(첨부, M5) 텍스트 블록만 모아 지시어를 뽑는다.
FAKE_CLAUDE_CONTENT_LOG 파일에는 받은 content를 JSON 한 줄로 남긴다(첨부를 보내는 M5에서
이미지 원문이 커지면 길이·해시만 남기게 고친다).
서버가 메시지 앞에 붙이는 앱 안내 문단("(앱 안내: …)\n\n", 지금 시각·끼어들기)은 건너뛰고 판단한다.

단발 모드: 인자에 --json-schema가 있으면(일지 정리 등) stdin 전체를 프롬프트로 읽고
FAKE_CLAUDE_ONESHOT 파일의 첫 줄(CLI JSON 출력)을 낸다. 줄이 여러 개면 첫 줄을 지워 다음 호출이
다음 줄을 쓰게 하고, 마지막 줄은 계속 쓴다(줄이 하나면 파일을 고치지 않는다). 줄 내용이
"__hang__"이면 멈추고, "__crash__"이면 출력 없이 죽는다. FAKE_CLAUDE_ONESHOT_DELAY(초)만큼
기다렸다 낸다. 기록 파일에는 받은 프롬프트도 남긴다(stdin).

stdin은 파일 객체 버퍼를 쓰지 않고 fd에서 직접 줄 단위로 읽는다(select와 섞어도 줄을 놓치지 않게).
"""

import json
import os
import select
import sys
import time
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "claude_cli"


def load_turns(name: str) -> list[list[dict]]:
    turns: list[list[dict]] = [[]]
    for line in (FIXTURE_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "control_response":
            continue
        turns[-1].append(event)
        if event.get("type") == "result":
            turns.append([])
    return [t for t in turns if t]


APP_NOTE = "(앱 안내:"


def strip_app_notes(content: str) -> str:
    """서버가 사용자 말 앞에 붙인 앱 안내 문단을 떼어 낸다(지시어는 그 뒤에 온다)."""
    while content.startswith(APP_NOTE) and "\n\n" in content:
        content = content.split("\n\n", 1)[1]
    return content


def plain_content(content) -> str:
    """M1은 글 content만 온다. 블록 배열(첨부, M5)이 오면 텍스트 블록만 모은다."""
    if isinstance(content, list):
        content = strip_app_notes(
            "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        )
    return content


def log_content(content) -> None:
    path = os.environ.get("FAKE_CLAUDE_CONTENT_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(content, ensure_ascii=False) + "\n")


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class StdinLines:
    """fd 0에서 직접 읽는 줄 버퍼. 대기 중인 줄이 있는지 select로 확인할 수 있다."""

    def __init__(self) -> None:
        self._buffer = b""
        self._eof = False

    def _fill(self, timeout: float | None) -> None:
        ready, _, _ = select.select([0], [], [], timeout)
        if ready:
            chunk = os.read(0, 65536)
            if chunk:
                self._buffer += chunk
            else:
                self._eof = True

    def next_line(self, timeout: float | None = None) -> str | None:
        """한 줄을 돌려준다. timeout 안에 없으면 None, EOF면 ""."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while b"\n" not in self._buffer:
            if self._eof:
                return ""
            remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
            if remaining == 0 and deadline is not None:
                self._fill(0)
                if b"\n" not in self._buffer:
                    return None
                break
            self._fill(remaining)
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode()


def emit_interrupted(control: dict, session_id: str) -> None:
    emit(
        {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": control.get("request_id")},
        }
    )
    emit(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "terminal_reason": "aborted_streaming",
            "result": None,
            "session_id": session_id,
            "duration_ms": 1,
        }
    )


def wait_for_interrupt(stdin: StdinLines, session_id: str) -> None:
    while (waiting := stdin.next_line()) not in ("", None):
        control = json.loads(waiting)
        if control.get("type") == "control_request":
            emit_interrupted(control, session_id)
            return


def say(text: str, session_id: str, stdin: StdinLines, delay: float) -> bool:
    """글을 몇 글자씩 text_delta로 보낸다. 도중에 인터럽트가 오면 중단 결과를 내고 False."""
    emit({"type": "system", "subtype": "init", "session_id": session_id, "model": "fake"})
    for start in range(0, len(text), _SAY_CHUNK):
        if delay:
            time.sleep(delay)
        pending = stdin.next_line(timeout=0)
        control = json.loads(pending) if pending else None
        if control is not None and control.get("type") == "control_request":
            emit_interrupted(control, session_id)
            return False
        delta = {"type": "text_delta", "text": text[start : start + _SAY_CHUNK]}
        emit(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "index": 0, "delta": delta},
                "session_id": session_id,
            }
        )
    return True


_SAY_CHUNK = 4


def oneshot(args: list[str]) -> None:
    prompt = sys.stdin.read()
    log_path = os.environ.get("FAKE_CLAUDE_ARGS_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            record = {
                "args": args,
                "stdin": prompt,
                "cwd": os.getcwd(),
                "has_token": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                "has_other_secret": "TRAILTALK_TEST_OTHER_SECRET" in os.environ,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    fixture = os.environ.get("FAKE_CLAUDE_ONESHOT")
    if not fixture:
        emit({"type": "result", "subtype": "success", "is_error": True, "result": "픽스처 없음"})
        return
    path = Path(fixture)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    line = lines[0]
    if len(lines) > 1:
        path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    if line == "__hang__":
        time.sleep(3600)
    if line == "__crash__":
        print(f"fake crash {os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', '')}", file=sys.stderr)
        sys.exit(3)
    time.sleep(float(os.environ.get("FAKE_CLAUDE_ONESHOT_DELAY", "0")))  # 느린 일지 정리 흉내
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> None:
    args = sys.argv[1:]
    if "--json-schema" in args:
        oneshot(args)
        return
    resume_id = args[args.index("--resume") + 1] if "--resume" in args else None
    session_id = resume_id or "00000000-0000-4000-8000-00000000fake"
    log_path = os.environ.get("FAKE_CLAUDE_ARGS_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            record = {
                "args": args,
                "cwd": os.getcwd(),
                "ENABLE_TOOL_SEARCH": os.environ.get("ENABLE_TOOL_SEARCH"),
                "DISABLE_AUTOUPDATER": os.environ.get("DISABLE_AUTOUPDATER"),
                "has_token": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                "has_anthropic_api_key": "ANTHROPIC_API_KEY" in os.environ,
                "has_other_secret": "TRAILTALK_TEST_OTHER_SECRET" in os.environ,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    turns = load_turns(os.environ.get("FAKE_CLAUDE_FIXTURE", "multiturn"))
    delay = float(os.environ.get("FAKE_CLAUDE_DELAY", "0"))
    print("fake claude ready", file=sys.stderr, flush=True)
    stdin = StdinLines()
    index = 0
    while (line := stdin.next_line()) != "":
        if not line:
            continue
        message = json.loads(line)
        if message.get("type") == "control_request":
            continue  # 턴 밖의 인터럽트는 무시
        raw = message.get("message", {}).get("content", "")
        log_content(raw)
        content = strip_app_notes(plain_content(raw))
        if content == "__crash__":
            print("fake crash", file=sys.stderr, flush=True)
            sys.exit(3)
        if content == "__hang__":
            continue
        if content == "__hang_until_interrupt__":
            wait_for_interrupt(stdin, session_id)
            continue
        directive, _, text = content.partition(":")
        if directive in ("__say__", "__say_then_crash__", "__say_then_hang__"):
            if not say(text, session_id, stdin, delay):
                continue
            if directive == "__say_then_crash__":
                print("fake crash", file=sys.stderr, flush=True)
                sys.exit(3)
            if directive == "__say_then_hang__":
                wait_for_interrupt(stdin, session_id)
                continue
            emit(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": text,
                    "session_id": session_id,
                    "duration_ms": 1,
                }
            )
            continue
        turn = turns[min(index, len(turns) - 1)]
        index += 1
        for event in turn:
            if "session_id" in event:
                event = {**event, "session_id": session_id}
            if delay:
                time.sleep(delay)
            pending = stdin.next_line(timeout=0)
            control = json.loads(pending) if pending else None
            if control is not None and control.get("type") == "control_request":
                emit_interrupted(control, session_id)
                break
            emit(event)


if __name__ == "__main__":
    main()
