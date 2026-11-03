"""출처 인용 평가(M5-10): 번호를 자동으로 비교한다(채점 모델 없음).

cases.yaml의 cited_cases는 대화 전문과 그 대화에서 본 출처(sources)를 주고, 추출 결과의 요약 줄
(결론·알게 된 것)·메모가 단 출처 번호를 본다.
- 범위 밖 번호: 출처 목록에 없는 번호(서버는 이를 버리지만 모델이 지어내는 정도를 센다)
- 빠뜨린 인용: must_cite 번호가 어디에도 인용되지 않았다
- 잘못된 인용: no_cite 번호를 인용했다
- 출처가 없는 케이스에서 번호를 단 경우도 범위 밖 번호로 센다
기준은 범위 밖 번호 0, 잘못된 인용 0, must_cite 재현율 80% 이상이다.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.db.models import Turn, TurnRole
from app.jobs.extract import Extraction

CASES = Path(__file__).with_name("cases.yaml")
CITE_RECALL_MIN = 0.8


def load_cited_cases() -> list[dict]:
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))["cited_cases"]


def cited_turns(case: dict) -> list[Turn]:
    return [
        Turn(seq=i, role=TurnRole(role), text=text) for i, (role, text) in enumerate(case["turns"])
    ]


def cited_sources(case: dict) -> list[dict]:
    """extract.build_prompt에 넘기는 출처 목록([{title, url}])."""
    return [{"title": title, "url": url} for title, url in case.get("sources", [])]


def used_numbers(extraction: Extraction) -> list[int]:
    """요약 줄(결론 + 알게 된 것)과 메모가 단 출처 번호(중복 포함, 순서대로)."""
    items = [extraction.conclusion, *extraction.findings, *extraction.memos]
    return [n for item in items for n in item.sources]


@dataclass
class CitedResult:
    cid: str
    note: str
    sources: int  # 출처 수
    must_cite: list[int]
    no_cite: list[int]
    extraction: Extraction | None = None
    seconds: float = 0.0
    error: str = ""
    used: list[int] = field(default_factory=list)

    @property
    def out_of_range(self) -> list[int]:
        return sorted({n for n in self.used if not 1 <= n <= self.sources})

    @property
    def missed(self) -> list[int]:
        return [n for n in self.must_cite if n not in self.used]

    @property
    def wrong(self) -> list[int]:
        return sorted({n for n in self.used if n in self.no_cite})


def score_cited(case: dict, extraction: Extraction) -> CitedResult:
    result = CitedResult(
        case["id"],
        case["note"],
        len(case.get("sources", [])),
        list(case.get("must_cite", [])),
        list(case.get("no_cite", [])),
        extraction=extraction,
    )
    result.used = used_numbers(extraction)
    return result


def cited_report(results: list[CitedResult]) -> list[str]:
    """리포트에 붙일 줄들. 결과가 없으면 빈 목록."""
    if not results:
        return []
    done = [r for r in results if not r.error]
    must = sum(len(r.must_cite) for r in done)
    hit = sum(len(r.must_cite) - len(r.missed) for r in done)
    out_of_range = sum(len(r.out_of_range) for r in done)
    wrong = sum(len(r.wrong) for r in done)
    recall = hit / must if must else 1.0
    if len(done) < len(results):
        verdict = "오류 있음(기준 판정 안 함)"
    else:
        ok = out_of_range == 0 and wrong == 0 and recall >= CITE_RECALL_MIN
        verdict = "통과" if ok else "미달"
    lines = [
        "",
        "## 출처 인용",
        "",
        f"- 결과: **인용 재현율 {hit}/{must}, 범위 밖 번호 {out_of_range}, 잘못된 인용 {wrong} "
        f"— {verdict}** (기준 재현율 {CITE_RECALL_MIN:.0%} 이상·범위 밖 번호 0·잘못된 인용 0, "
        "계획서 M5-10). 채점 모델 없이 번호만 비교한다(`tests/extract_eval/cited.py`).",
        "",
        "| # | 대화 | 출처 수 | 인용한 번호 | 빠뜨린 인용 | 잘못된 인용 | 범위 밖 | 설명 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        if r.error:
            lines.append(f"| {i} | `{r.cid}` | {r.sources} | 오류 | - | - | - | {r.error} |")
            continue
        used = ", ".join(str(n) for n in sorted(set(r.used))) or "(없음)"
        lines.append(
            f"| {i} | `{r.cid}` | {r.sources} | {used} | "
            f"{', '.join(map(str, r.missed)) or '-'} | "
            f"{', '.join(map(str, r.wrong)) or '-'} | "
            f"{', '.join(map(str, r.out_of_range)) or '-'} | {r.note} |"
        )
    return lines
