"""일지 정리(추출) 품질 평가(Spec 5.5, 계획서 M2-05). 실제 Claude CLI를 써서 구독 사용량이 든다.

    (cd server && RUN_REAL_CLI=1 uv run python -m tests.extract_eval.run_eval [--limit N])

대화 전문(cases.yaml)을 앱과 같은 방식(app/jobs/extract.py의 프롬프트·스키마, 경량 모델)으로
추출하고, 채점 모델(대화 모델, 추출 모델보다 강한 것)이 다음 두 가지를 판정한다.
- 재현율: 사람이 정한 정답 아이디어·할 일이 같은 종류의 추출 결과에 들어 있는지(분류가 틀리면
  못 찾은 것으로 센다. 할 일은 완료 체크 대상이라 분류가 중요하다)
- 근거: 추출한 아이디어·할 일이 대화에서 사용자가 말했거나 받아들인 것인지(지어낸 항목 찾기)
- 중복: 대화 중 이미 저장한 노트(cases.yaml의 saved)와 같은 항목을 다시 뽑았는지
- 메모 품질: 메모가 대화 진행 기록(정하지 않음, 답하지 않음, 누가 저장했다 등)인지
- 수락하지 않은 제안: 캐릭터가 제안했지만 사용자가 받아들이지 않은 것(cases.yaml의 rejected)이
  아이디어·할 일·메모 어디에든 뽑혔는지(Spec 5.5)
아이디어·할 일을 합친 재현율 80% 이상이고 수락하지 않은 제안이 하나도 뽑히지 않으면 통과. 리포트는
docs/eval/extract-<날짜>.md에 쓴다. 캐릭터 이름은 YAML에서만 읽는다(NFR-08).
"""

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.config import REPO_DIR, Settings
from app.db.models import NoteKind, Turn, TurnRole
from app.jobs.extract import SAVED_LABELS, Extraction, build_prompt, build_transcript
from app.llm.claude_cli import run_oneshot
from app.persona.loader import load_persona

CASES = Path(__file__).with_name("cases.yaml")
RECALL_MIN = 0.8
CONCURRENCY = 3


def load_cases() -> list[dict]:
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]


def case_turns(case: dict) -> list[Turn]:
    cut = set(case.get("interrupted", []))
    return [
        Turn(seq=i, role=TurnRole(role), text=text, interrupted=i in cut)
        for i, (role, text) in enumerate(case["turns"])
    ]


FLAG_KEYS = (
    "gold_found",
    "extracted_supported",
    "extracted_duplicate",
    "memo_process",
    "rejected_extracted",
)


def judge_schema(
    gold: int, extracted: int, memos: int, summary: int = 0, rejected: int = 0
) -> dict:
    def flags(n: int) -> dict:
        return {"type": "array", "items": {"type": "boolean"}, "minItems": n, "maxItems": n}

    sizes = dict(zip(FLAG_KEYS, (gold, extracted, extracted, memos, rejected), strict=True))
    return {
        "type": "object",
        "properties": {
            **{key: flags(n) for key, n in sizes.items()},
            "summary_process": flags(summary),
            "repeated_fact": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [*FLAG_KEYS, "summary_process", "repeated_fact", "reason"],
        "additionalProperties": False,
    }


def numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1)) or "(없음)"


def judge_prompt(
    transcript: str,
    gold_ideas: list[str],
    gold_todos: list[str],
    ideas: list[str],
    todos: list[str],
    memos: list[str],
    saved: list[tuple[str, str]],
    summary: list[str] = (),
    checks: list[str] = (),
    rejected: list[str] = (),
) -> str:
    gold = [f"[아이디어] {x}" for x in gold_ideas] + [f"[할 일] {x}" for x in gold_todos]
    extracted = [f"[아이디어] {x}" for x in ideas] + [f"[할 일] {x}" for x in todos]
    return f"""너는 대화 정리 결과를 채점한다.

1) gold_found: 정답 목록의 항목마다, 같은 종류([아이디어]는 [아이디어], [할 일]은 [할 일])의
   추출 항목 가운데 같은 내용이 있으면 true. 표현이 달라도 뜻이 같으면 인정한다. 다른 종류에만
   있거나, 숫자·시간·대상이 다르거나, 뜻이 반대면 false.
2) extracted_supported: 추출 목록의 항목마다, 대화에서 사용자가 직접 말했거나 받아들인 내용이면
   true. 대화에 없는 내용을 지어냈거나, 사용자가 거절한 제안이거나, 사용자가 말한 것과 뜻이
   반대이거나 숫자·시간을 바꿨으면 false.
3) extracted_duplicate: 추출 목록의 항목마다, 대화 중 이미 저장한 노트와 같은 일이면 true
   (표현이 달라도 같은 일이면 true).
4) memo_process: 메모 목록의 항목마다, 사용자에게 쓸모 있는 정보가 아니라 대화 진행 기록이면 true.
   예: 아직 정하지 않았다, 질문에 답하지 않았다, 누가 무엇을 물었거나 저장했다,
   지난 대화를 언급했다.
5) summary_process: 정리 문장 목록(첫 줄은 결론, 나머지는 알게 된 것)의 항목마다, 대화나 검색이
   어떻게 흘러갔는지를 적은 문장이면 true. 예: 찾아봤다, 찾지 못했다, 검색 결과는 ~였다,
   ~에 대한 대화였다. 대화로 알게 되거나 정한 내용 자체면 false.
6) repeated_fact: 정리 문장(결론 제외)·확인할 것·메모·추출 목록 사이(또는 각 목록 안)에 같은
   사실이나 같은 일이 두 번 이상 나오면 true. 결론과 추출(아이디어·할 일)이 겹치는 것은 허용한다.
7) rejected_extracted: 수락하지 않은 제안 목록의 항목마다, 추출 목록이나 메모 목록에 그 제안과
   같은 내용이 있으면 true. 표현이 달라도 뜻이 같으면 true다.
reason에는 1·2번이 false이거나 3·4·5·6·7번이 true인 항목의 이유를 한국어로 짧게 쓴다.

<대화>
{transcript}
</대화>

대화 중 이미 저장한 노트:
{numbered([f"[{SAVED_LABELS[NoteKind(k)]}] {c}" for k, c in saved])}

정답 목록:
{numbered(gold)}

추출 목록:
{numbered(extracted)}

메모 목록:
{numbered(memos)}

정리 문장 목록:
{numbered(list(summary))}

확인할 것 목록:
{numbered(list(checks))}

수락하지 않은 제안 목록:
{numbered(list(rejected))}"""


@dataclass
class Result:
    cid: str
    note: str
    gold_ideas: list[str]
    gold_todos: list[str]
    extraction: Extraction | None = None
    saved: list[tuple[str, str]] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    rejected_extracted: list[bool] = field(default_factory=list)
    gold_found: list[bool] = field(default_factory=list)
    supported: list[bool] = field(default_factory=list)
    duplicate: list[bool] = field(default_factory=list)
    memo_process: list[bool] = field(default_factory=list)
    summary_process: list[bool] = field(default_factory=list)
    repeated: bool = False
    reason: str = ""
    seconds: float = 0.0
    error: str = ""

    @property
    def gold(self) -> list[str]:
        return self.gold_ideas + self.gold_todos

    @property
    def extracted(self) -> list[str]:
        return (self.extraction.ideas + self.extraction.todos) if self.extraction else []

    def found(self, kind: str) -> tuple[int, int]:
        n_ideas = len(self.gold_ideas)
        flags = self.gold_found[:n_ideas] if kind == "idea" else self.gold_found[n_ideas:]
        total = n_ideas if kind == "idea" else len(self.gold_todos)
        return sum(flags), total


async def evaluate_case(settings: Settings, assistant: str, case: dict, r: Result) -> None:
    started = time.monotonic()
    turns = case_turns(case)
    raw = await run_oneshot(
        settings,
        build_prompt(turns, assistant, r.saved),
        model=settings.llm_extract_model,
        json_schema=Extraction.model_json_schema(),
        timeout_s=settings.extract_timeout_s,
    )
    r.extraction = Extraction.model_validate(raw)
    verdict = await run_oneshot(
        settings,
        judge_prompt(
            build_transcript(turns, assistant),
            r.gold_ideas,
            r.gold_todos,
            r.extraction.ideas,
            r.extraction.todos,
            [m.text for m in r.extraction.memos],
            r.saved,
            summary_lines(r.extraction),
            r.extraction.checks,
            r.rejected,
        ),
        model=settings.llm_chat_model,  # 추출 모델보다 강한 모델이 채점한다(자기 채점 관대함 방지)
        json_schema=judge_schema(
            len(r.gold),
            len(r.extracted),
            len(r.extraction.memos),
            len(summary_lines(r.extraction)),
            len(r.rejected),
        ),
        timeout_s=settings.extract_timeout_s,
    )
    sizes = (
        len(r.gold),
        len(r.extracted),
        len(r.extracted),
        len(r.extraction.memos),
        len(r.rejected),
    )
    flags = [[bool(x) for x in verdict[key]] for key in FLAG_KEYS]
    if [len(f) for f in flags] != list(sizes):
        raise ValueError("채점 결과 개수가 맞지 않습니다")
    r.gold_found, r.supported, r.duplicate, r.memo_process, r.rejected_extracted = flags
    r.summary_process = [bool(x) for x in verdict["summary_process"]]
    if len(r.summary_process) != len(summary_lines(r.extraction)):
        raise ValueError("채점 결과 개수가 맞지 않습니다")
    r.repeated = bool(verdict["repeated_fact"])
    r.reason = str(verdict.get("reason", "")).strip()
    r.seconds = time.monotonic() - started


def summary_lines(ex: Extraction) -> list[str]:
    """정리 문장: 결론(첫 줄)과 알게 된 것(Spec 5.4)."""
    return [line.text for line in [ex.conclusion, *ex.findings]]


def cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def pct(found: int, total: int) -> str:
    return f"{found}/{total} ({found / total:.0%})" if total else "-"


def report(results: list[Result], settings: Settings, minutes: float, full: bool) -> str:
    done = [r for r in results if not r.error]
    idea = [sum(x) for x in zip(*(r.found("idea") for r in done), strict=True)] or [0, 0]
    todo = [sum(x) for x in zip(*(r.found("todo") for r in done), strict=True)] or [0, 0]
    total_found, total = idea[0] + todo[0], idea[1] + todo[1]
    recall = total_found / total if total else 0.0
    unsupported = sum(r.supported.count(False) for r in done)
    extracted = sum(len(r.extracted) for r in done)
    duplicates = sum(r.duplicate.count(True) for r in done if r.saved)
    with_saved = sum(len(r.extracted) for r in done if r.saved)
    process = sum(r.memo_process.count(True) for r in done)
    memos = sum(len(r.extraction.memos) for r in done)
    summary_process = sum(r.summary_process.count(True) for r in done)
    summary_total = sum(len(r.summary_process) for r in done)
    repeated = sum(r.repeated for r in done)
    rejected_hit = sum(r.rejected_extracted.count(True) for r in done)
    rejected_total = sum(len(r.rejected) for r in done)
    rejected_cases = sum(bool(r.rejected) for r in done)
    if not full:
        verdict = f"일부 실행({len(results)}개, 기준 판정 안 함)"
    elif len(done) < len(results):
        verdict = "오류 있음(기준 판정 안 함)"
    else:
        verdict = "통과" if recall >= RECALL_MIN and rejected_hit == 0 else "미달"
    now = datetime.now(ZoneInfo(settings.timezone))
    lines = [
        f"# 일지 정리(추출) 평가 — {now:%Y-%m-%d}",
        "",
        f"- 결과: **재현율 {pct(total_found, total)}, 수락하지 않은 제안 추출 "
        f"{rejected_hit}/{rejected_total} — {verdict}** "
        f"(기준 재현율 {RECALL_MIN:.0%} 이상·수락하지 않은 제안 추출 0, 계획서 M2-05)",
        f"  - 수락하지 않은 제안 케이스 {rejected_cases}개(Spec 5.5 기준 3개 이상)",
        f"  - 아이디어 {pct(*idea)}, 할 일 {pct(*todo)}",
        f"  - 대화에 근거 없는 아이디어·할 일(지어냄·거절한 제안): {unsupported}/{extracted}",
        f"  - 대화 중 저장한 노트와 중복된 추출 항목: {duplicates}/{with_saved}",
        f"  - 대화 진행 기록 메모(쓸모없음): {process}/{memos}",
        f"  - 결론·알게 된 것 중 진행 기록·대화 설명: {summary_process}/{summary_total}",
        f"  - 같은 사실을 되풀이한 일지: {repeated}/{len(done)}",
        f"- 추출 모델 `{settings.llm_extract_model}`, 채점 모델 `{settings.llm_chat_model}`, "
        f"대화 {len(results)}개, "
        f"소요 {minutes:.1f}분, 실행 {now:%Y-%m-%d %H:%M}",
        "- 재실행: `(cd server && RUN_REAL_CLI=1 uv run python -m tests.extract_eval.run_eval)`",
        "- 정답은 사람이 정했다(`server/tests/extract_eval/cases.yaml`). 채점 모델이 관대하거나 "
        "엄격할 수 있으므로 아래 항목별 판정을 읽고 경계 사례를 적는다. 정답은 같은 종류끼리만 "
        "비교하고, 메모의 근거는 자동으로 판정하지 않는다(사람이 읽는다).",
        "",
        "## 대화별 결과",
        "",
        "| # | 대화 | 아이디어 | 할 일 | 근거 없음 | 중복 | 진행 기록 메모 "
        "| 수락 안 한 제안 | 설명 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        if r.error:
            lines.append(f"| {i} | `{r.cid}` | 오류 | 오류 | - | - | - | - | {cell(r.error)} |")
            continue
        lines.append(
            f"| {i} | `{r.cid}` | {pct(*r.found('idea'))} | {pct(*r.found('todo'))} | "
            f"{r.supported.count(False)}/{len(r.extracted)} | "
            f"{f'{r.duplicate.count(True)}/{len(r.extracted)}' if r.saved else '-'} | "
            f"{r.memo_process.count(True)}/{len(r.extraction.memos)} | "
            f"{f'{r.rejected_extracted.count(True)}/{len(r.rejected)}' if r.rejected else '-'} | "
            f"{cell(r.note)} |"
        )
    lines += ["", "## 대화별 상세", ""]
    for i, r in enumerate(results, 1):
        lines += [f"### {i}. `{r.cid}` ({r.seconds:.1f}초)", "", f"- 설명: {r.note}"]
        if r.error:
            lines += [f"- 오류: {r.error}", ""]
            continue
        ex = r.extraction
        lines.append(f"- 제목: {ex.title}")
        marks = iter(r.summary_process)
        for label, item in [("결론", ex.conclusion), *(("알게 된 것", f) for f in ex.findings)]:
            noise = next(marks, False)
            cites = "".join(f"[{n}]" for n in item.sources)
            lines.append(f"- {label}: {'**진행 기록** ' if noise else ''}{cell(item.text)}{cites}")
        if ex.checks:
            lines.append(f"- 확인할 것: {cell(' / '.join(ex.checks))}")
        if r.repeated:
            lines.append("- **같은 사실 되풀이**")
        if r.saved:
            notes = " / ".join(f"[{SAVED_LABELS[NoteKind(k)]}] {c}" for k, c in r.saved)
            lines.append(f"- 대화 중 저장한 노트: {cell(notes)}")
        lines.append("- 정답")
        for item, ok in zip(r.gold, r.gold_found, strict=True):
            lines.append(f"  - {'O' if ok else 'X'} {item}")
        lines.append("- 추출(아이디어·할 일)")
        kinds = ["아이디어"] * len(ex.ideas) + ["할 일"] * len(ex.todos)
        for kind, item, ok, dup in zip(kinds, r.extracted, r.supported, r.duplicate, strict=True):
            mark = ("O" if ok else "**근거 없음**") + (" **중복**" if dup else "")
            lines.append(f"  - {mark} [{kind}] {item}")
        if r.rejected:
            lines.append("- 수락하지 않은 제안(뽑히면 안 됨)")
            for item, hit in zip(r.rejected, r.rejected_extracted, strict=True):
                lines.append(f"  - {'**추출됨**' if hit else 'O'} {item}")
        if ex.memos:
            lines.append("- 메모")
            for item, noise in zip(ex.memos, r.memo_process, strict=True):
                cites = "".join(f"[{n}]" for n in item.sources)
                lines.append(f"  - {'**진행 기록**' if noise else 'O'} {item.text}{cites}")
        lines += [f"- 채점: {cell(r.reason) or '(없음)'}", ""]
    return "\n".join(lines)


def report_path(settings: Settings) -> Path:
    """docs/eval/extract-<날짜>.md. 같은 날 이미 있으면 -2, -3…을 붙인다(이전 회차 보존)."""
    now = datetime.now(ZoneInfo(settings.timezone))
    base = REPO_DIR / "docs" / "eval" / f"extract-{now:%Y-%m-%d}"
    path, n = base.with_suffix(".md"), 1
    while path.exists():
        n += 1
        path = Path(f"{base}-{n}.md")
    return path


async def evaluate(args: argparse.Namespace) -> int:
    # 앱과 같은 고정 단발 작업 폴더(cli_work_dir/oneshot)를 쓴다. CLI가 작업 폴더마다
    # ~/.claude/projects 항목을 만드므로 임시 폴더를 쓰면 실행할 때마다 항목이 하나씩 남는다
    settings = Settings()
    assistant = load_persona(settings.persona_dir, settings.default_persona).persona.name
    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]
    results = [
        Result(
            c["id"],
            c["note"],
            list(c["gold"]["ideas"]),
            list(c["gold"]["todos"]),
            saved=[(kind, content) for kind, content in c.get("saved", [])],
            rejected=list(c.get("rejected", [])),
        )
        for c in cases
    ]
    limit = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()

    async def run(case: dict, r: Result) -> None:
        async with limit:
            try:
                await evaluate_case(settings, assistant, case, r)
            except Exception as exc:  # 한 대화가 실패해도 나머지는 계속 평가한다
                r.error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"{'오류' if r.error else '완료'}  {r.cid}  ({r.seconds:.1f}초)", flush=True)

    await asyncio.gather(*(run(c, r) for c, r in zip(cases, results, strict=True)))
    minutes = (time.monotonic() - started) / 60
    out = args.out or report_path(settings)
    out.parent.mkdir(parents=True, exist_ok=True)
    full = len(results) == len(load_cases())
    out.write_text(report(results, settings, minutes, full), encoding="utf-8")
    print(f"리포트: {out}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="앞에서 N개만(시험용, 기준 판정 안 함)")
    parser.add_argument("--out", type=Path, help="리포트 경로(기본 docs/eval/extract-<날짜>.md)")
    args = parser.parse_args()
    if os.environ.get("RUN_REAL_CLI") != "1":
        print("실제 Claude CLI를 쓰므로 RUN_REAL_CLI=1이 필요합니다(구독 사용량 사용).")
        return 2
    return await evaluate(args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
