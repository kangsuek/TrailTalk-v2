# ruff: noqa: E501
"""실제 글 대화 3개로 일지가 맞게 정리되는지 확인한다(계획서 M2-15). 실제 Claude CLI를 써서 구독 사용량이 든다.

    (cd server && RUN_REAL_CLI=1 uv run python -m tests.journal_eval.run_journal)

임시 폴더(DB·첨부·오디오·CLI 작업 폴더)로 격리 서버(포트 8120)를 스스로 띄우고 HTTP API로 대화한다.
사용자의 실제 서버(8000)와 DB는 건드리지 않는다. 시나리오:
- A: 아이디어·할 일을 저장하고, 사용자가 받아들이지 않은 제안(쓰레기 신고 기능)이 노트로 뽑히지 않는지 본다
- B: 정보를 묻고 결정을 내리는 대화가 요약·확인할 것·메모로 정리되는지 본다
- C: 끝낸 대화를 다시 열어 이어 간다. 재개 인사말과 이후 답변에 호칭이 없는지, 처음 노트·제목이 남고
  새 노트가 더해지는지 본다
호칭(프로필 nickname)은 인사말에서만 쓰여야 한다(규약 2.2). 리포트는 docs/eval/journal-real-<날짜>.md.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from app.config import REPO_DIR

PORT = 8120
BASE = f"http://127.0.0.1:{PORT}"
NICKNAME = "산들"
EXTRACT_WAIT_S = 150
LOG_PATH = Path(tempfile.gettempdir()) / "trailtalk-journal-eval-server.log"
TURN_DEADLINE_S = 200


def call(method: str, path: str, body: dict | None = None, timeout: float = 120):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"X-TrailTalk": "1", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, (json.loads(raw) if raw else None)


def send_turn(session_id: str, text: str) -> tuple[str, float, list[str]]:
    """글 턴을 보내고 (답변 전문, 걸린 초, 쓴 도구 이름)을 돌려준다."""
    started = time.monotonic()
    request = urllib.request.Request(
        f"{BASE}/api/sessions/{session_id}/turns",
        data=json.dumps({"text": text}).encode(),
        method="POST",
        headers={"X-TrailTalk": "1", "Content-Type": "application/json"},
    )
    answer = ""
    tools: list[str] = []
    with urllib.request.urlopen(request, timeout=240) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event["type"] == "tool" and event["phase"] == "call":
                tools.append(event["name"])
            elif event["type"] == "done":
                answer = event["text"]
            elif event["type"] == "error":
                raise RuntimeError(f"턴 오류: {event}")
            if time.monotonic() - started > TURN_DEADLINE_S:
                raise RuntimeError(f"턴이 {TURN_DEADLINE_S}초 안에 끝나지 않았습니다")
    return answer, time.monotonic() - started, tools


def wait_journal(session_id: str) -> dict:
    deadline = time.monotonic() + EXTRACT_WAIT_S
    while True:
        status, detail = call("GET", f"/api/journal/{session_id}")
        assert status == 200, detail
        if detail["session"]["journal_status"] != "pending" or time.monotonic() > deadline:
            return detail
        time.sleep(3)


def end_session(session_id: str) -> dict:
    status, body = call("POST", f"/api/sessions/{session_id}/end", {}, timeout=180)
    assert status == 200, body
    return body


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)
        print(text, flush=True)

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.add(f"- {'통과' if ok else '**실패**'}: {label}" + (f" ({detail})" if detail else ""))
        if not ok:
            self.failures.append(label)


def notes_text(detail: dict, kind: str) -> list[str]:
    return [n["content"] for n in detail["notes"] if n["kind"] == kind]


def describe(report: Report, detail: dict) -> None:
    session = detail["session"]
    report.add(
        f"- 정리 상태 `{session['journal_status']}`, 제목 「{session['title']}」, 저장 {session['counts']}"
    )
    report.add(f"- 요약: {' / '.join(session['summary'])}")
    report.add(f"- 확인할 것: {detail['checks']}")
    report.add(f"- 태그: {session['tags']}")
    for note in detail["notes"]:
        report.add(f"  - [{note['kind']}] {note['content']}")


def converse(report: Report, session_id: str, messages: list[str]) -> None:
    for text in messages:
        answer, seconds, tools = send_turn(session_id, text)
        report.add(f"- 나: {text}")
        report.add(f"  - 답변({seconds:.1f}초, 도구 {tools or '없음'}): {answer}")


def assistant_turns_after_greeting(detail: dict) -> list[str]:
    return [t["text"] for t in detail["turns"] if t["role"] == "assistant" and t["seq"] > 0]


def scenario_a(report: Report) -> None:
    report.add("## A. 아이디어·할 일 저장, 수락하지 않은 제안")
    status, body = call("POST", "/api/sessions", {"mode": "text"})
    assert status == 201, body
    sid = body["session"]["id"]
    report.add(f"- 인사말: {body['greeting']['text']}")
    report.check(NICKNAME in body["greeting"]["text"], "첫 인사말에는 호칭이 있다(호칭 주입 확인)")
    converse(
        report,
        sid,
        [
            "등산로 곳곳의 쓰레기통 위치를 지도로 보여 주는 앱을 만들어 보면 어떨까 생각 중이야.",
            "좋아, 그 아이디어는 꼭 저장해 줘. 누가 쓰레기 신고 기능도 넣으라고 했는데 그건 안 하기로 했어.",
            "이번 주말에 북한산 입구 쓰레기통 위치를 사진으로 찍어 오는 걸 할 일로 남겨 줘.",
        ],
    )
    closing = end_session(sid)
    report.add(f"- 마무리 멘트: {closing['closing']}")
    detail = wait_journal(sid)
    describe(report, detail)
    session = detail["session"]
    report.check(session["journal_status"] == "done", "정리가 끝났다")
    report.check(bool(session["title"]) and bool(session["summary"]), "제목과 요약이 있다")
    ideas, todos = notes_text(detail, "idea"), notes_text(detail, "todo")
    report.check(any("쓰레기통" in t and "지도" in t for t in ideas), "아이디어: 쓰레기통 지도")
    report.check(any("북한산" in t for t in todos), "할 일: 북한산 입구 사진")
    # 거절한 결정을 "넣지 않기로 함"으로 적은 것은 괜찮다. 신고 기능을 할 일·아이디어로 뽑으면 실패다
    negations = ("않", "뺀", "빼", "제외", "없", "안 ")
    proposed = [
        n["content"]
        for n in detail["notes"]
        if "신고" in n["content"] and not any(word in n["content"] for word in negations)
    ]
    report.check(
        not proposed, "수락하지 않은 제안(쓰레기 신고 기능)을 노트로 뽑지 않았다", str(proposed)
    )
    after = assistant_turns_after_greeting(detail)
    report.check(not any(NICKNAME in t for t in after), "인사말 뒤 답변에 호칭이 없다")


def scenario_b(report: Report) -> None:
    report.add("## B. 정보를 묻고 결정하는 대화")
    status, body = call("POST", "/api/sessions", {"mode": "text"})
    assert status == 201, body
    sid = body["session"]["id"]
    converse(
        report,
        sid,
        [
            "북한산 우이동 입구에서 시작하는 코스는 보통 몇 시간 걸려?",
            "그럼 일요일 아침 일찍 출발하는 걸로 정할게. 비 오면 다음 주로 미룰 거야.",
        ],
    )
    end_session(sid)
    detail = wait_journal(sid)
    describe(report, detail)
    session = detail["session"]
    report.check(session["journal_status"] == "done", "정리가 끝났다")
    report.check(bool(session["title"]) and bool(session["summary"]), "제목과 요약이 있다")
    report.check(detail["checks"] is not None, "확인할 것 목록이 있다(새 형식)")
    report.check(sum(session["counts"].values()) >= 1, "노트가 하나 이상 저장됐다")
    after = assistant_turns_after_greeting(detail)
    report.check(not any(NICKNAME in t for t in after), "인사말 뒤 답변에 호칭이 없다")


def scenario_c(report: Report) -> None:
    report.add("## C. 끝낸 대화를 다시 열어 이어 간 대화")
    status, body = call("POST", "/api/sessions", {"mode": "text"})
    assert status == 201, body
    sid = body["session"]["id"]
    converse(
        report,
        sid,
        [
            "산책 코스에 맞춰 날씨 알림을 붙이는 앱 아이디어를 생각 중이야. 이 아이디어 저장해 줘.",
            "그리고 날씨 API 무료 한도를 알아보는 걸 할 일로 남겨 줘.",
        ],
    )
    end_session(sid)
    first = wait_journal(sid)
    report.add("### 처음 정리")
    describe(report, first)
    first_title = "내가 고친 제목"
    status, _ = call("PATCH", f"/api/journal/{sid}", {"title": first_title})
    assert status == 200
    first_notes = {n["id"]: n["content"] for n in first["notes"]}
    report.check(first["session"]["journal_status"] == "done", "처음 정리가 끝났다")

    status, reopened = call("POST", f"/api/sessions/{sid}/reopen", {"mode": "text"}, timeout=180)
    assert status == 200, reopened
    greeting = reopened["greeting"]["text"]
    report.add(f"### 다시 열기\n- 재개 인사말: {greeting}")
    report.check(NICKNAME not in greeting, "재개 인사말에 호칭이 없다")
    converse(
        report,
        sid,
        ["알림은 출발 한 시간 전에 보내는 게 좋겠어. 이것도 아이디어로 저장해 줘."],
    )
    end_session(sid)
    second = wait_journal(sid)
    report.add("### 다시 끝낸 뒤 정리")
    describe(report, second)
    report.check(second["session"]["journal_status"] == "done", "다시 정리가 끝났다")
    report.check(second["session"]["date"] == first["session"]["date"], "일지 날짜가 그대로다")
    report.check(second["session"]["title"] == first_title, "고친 제목이 다시 정리해도 그대로다")
    second_notes = {n["id"]: n["content"] for n in second["notes"]}
    report.check(
        all(second_notes.get(i) == c for i, c in first_notes.items()),
        "처음 노트가 그대로 남았다",
    )
    new_ideas = [c for i, c in second_notes.items() if i not in first_notes]
    report.check(
        any("시간" in c for c in new_ideas),
        "다시 연 뒤 말한 아이디어가 새 노트로 더해졌다",
        str(new_ideas),
    )
    after = assistant_turns_after_greeting(second)
    report.check(not any(NICKNAME in t for t in after), "인사말 뒤 모든 답변에 호칭이 없다")


def main() -> int:
    if os.environ.get("RUN_REAL_CLI") != "1":
        print("실제 Claude CLI를 쓰므로 RUN_REAL_CLI=1 이 필요합니다.", file=sys.stderr)
        return 2
    try:
        call("GET", "/api/health", timeout=2)
    except OSError:
        pass
    else:
        print(f"포트 {PORT}에 이미 서버가 떠 있습니다. 끄고 다시 실행하세요.", file=sys.stderr)
        return 2
    report = Report()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trailtalk-journal-eval-") as tmp:
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/trailtalk.db",
            "ATTACHMENTS_DIR": f"{tmp}/attachments",
            "AUDIO_DIR": f"{tmp}/audio",
            "CLI_WORK_DIR": f"{tmp}/cli",
            "WEB_DIST_DIR": f"{tmp}/no-dist",
            "INTERNAL_BASE_URL": BASE,
        }
        server_log = open(LOG_PATH, "w", encoding="utf-8")  # noqa: SIM115
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            env=env,
            cwd=Path(__file__).resolve().parents[2],
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError("격리 서버가 바로 종료됐습니다")
                try:
                    if call("GET", "/api/health")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("격리 서버가 뜨지 않았습니다")
            status, _ = call("PUT", "/api/profile", {"nickname": NICKNAME})
            assert status == 200
            report.add(f"# 실제 글 대화 3개 확인 ({date.today().isoformat()})\n")
            report.add(
                f"실제 Claude CLI, 격리 서버(포트 {PORT}, 임시 DB), 프로필 호칭 「{NICKNAME}」. "
                "호칭은 인사말에서만 쓰여야 한다.\n"
            )
            only = os.environ.get("JOURNAL_EVAL_ONLY", "A,B,C").split(",")
            for name, scenario in zip("ABC", (scenario_a, scenario_b, scenario_c), strict=True):
                if name not in only:
                    continue
                scenario(report)
                report.add()
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            server_log.close()
    report.add(
        f"## 결과\n\n실패 {len(report.failures)}건, 걸린 시간 {time.monotonic() - started:.0f}초."
    )
    for label in report.failures:
        report.add(f"- 실패: {label}")
    out = REPO_DIR / "docs" / "eval" / f"journal-real-{date.today().isoformat()}.md"
    out.write_text("\n".join(report.lines) + "\n", encoding="utf-8")
    print(f"리포트: {out}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
