"""추출 평가 세트(M2-05) 형식 검사와 리포트 계산. 실제 CLI 없이 돈다."""

from app.config import Settings
from app.jobs.extract import CitedLine, Extraction
from tests.extract_eval.run_eval import Result, case_turns, judge_schema, load_cases, report


def test_cases_are_well_formed():
    cases = load_cases()
    assert len(cases) == 12
    assert sum(bool(c.get("saved")) for c in cases) >= 2  # 대화 중 저장한 노트 사례
    # 수락하지 않은 제안 사례(거절·무응답·화제 전환·맞장구, Spec 5.5)
    assert sum(bool(c.get("rejected")) for c in cases) >= 3
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        turns = case_turns(case)
        assert turns[0].role.value == "assistant"  # 인사말로 시작한다
        assert any(t.role.value == "user" for t in turns)
        assert set(case["gold"]) == {"ideas", "todos"}
        for kind, content in case.get("saved", []):
            assert kind in ("idea", "todo", "memo") and content.strip()
        for item in case.get("rejected", []):
            assert item.strip()
        for i in case.get("interrupted", []):
            assert turns[i].interrupted and turns[i].role.value == "assistant"
    assert sum(len(c["gold"]["ideas"]) + len(c["gold"]["todos"]) for c in cases) >= 20


def make_extraction(**overrides) -> Extraction:
    values = {
        "title": "제목",
        "conclusion": {"text": "결론", "sources": []},
        "findings": [],
        "checks": [],
        "ideas": ["아이디어 A", "지어낸 것"],
        "todos": ["할 일 A"],
        "memos": [],
        "tags": [],
    }
    values.update(overrides)
    return Extraction.model_validate(values)


def test_report_counts_recall_unsupported_and_rejected():
    r = Result(
        "c1", "설명", ["아이디어 A", "아이디어 B"], ["할 일 A"], extraction=make_extraction()
    )
    r.gold_found = [True, False, True]
    r.supported = [True, False, True]
    r.duplicate = [False, False, True]
    r.extraction.memos.append(CitedLine(text="아직 정하지 않았다", sources=[]))
    r.memo_process = [True]
    r.saved = [("todo", "할 일 A (맥락)")]
    r.rejected = ["거절한 제안"]
    r.rejected_extracted = [True]
    failed = Result("c2", "설명", ["x"], [], error="RuntimeError: 시간 초과")
    text = report([r, failed], Settings(_env_file=None), 1.0, full=True)
    assert "재현율 2/3 (67%), 수락하지 않은 제안 추출 1/1 — 오류 있음" in text
    assert "아이디어 1/2 (50%), 할 일 1/1 (100%)" in text
    assert "근거 없는 아이디어·할 일(지어냄·거절한 제안): 1/3" in text
    assert "**근거 없음** [아이디어] 지어낸 것" in text
    assert "대화 중 저장한 노트와 중복된 추출 항목: 1/3" in text
    assert "O **중복** [할 일] 할 일 A" in text
    assert "대화 진행 기록 메모(쓸모없음): 1/1" in text
    assert "**진행 기록** 아직 정하지 않았다" in text
    assert "**추출됨** 거절한 제안" in text


def test_rejected_extraction_fails_even_with_good_recall():
    r = Result("c1", "설명", ["아이디어 A"], [], extraction=make_extraction(todos=[]))
    r.gold_found = [True]
    r.supported = [True, True]
    r.duplicate = [False, False]
    r.rejected = ["거절한 제안"]
    r.rejected_extracted = [True]
    assert "— 미달" in report([r], Settings(_env_file=None), 1.0, full=True)
    r.rejected_extracted = [False]
    assert "— 통과" in report([r], Settings(_env_file=None), 1.0, full=True)


def test_judge_schema_fixes_array_lengths():
    schema = judge_schema(3, 2, 1, rejected=2)
    assert schema["properties"]["gold_found"]["minItems"] == 3
    assert schema["properties"]["extracted_supported"]["maxItems"] == 2
    assert schema["properties"]["extracted_duplicate"]["maxItems"] == 2
    assert schema["properties"]["memo_process"]["minItems"] == 1
    assert schema["properties"]["rejected_extracted"]["minItems"] == 2
