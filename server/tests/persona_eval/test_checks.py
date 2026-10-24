"""톤 평가 기계적 검사와 질문 세트(실제 CLI 없이 돈다)."""

from pathlib import Path

import pytest
import yaml

from tests.persona_eval.checks import code_checks, count_sentences

QUESTIONS = Path(__file__).with_name("questions.yaml")


def failed(answer: str, max_sentences: int = 4) -> set[str]:
    return {c.name for c in code_checks(answer, max_sentences=max_sentences) if not c.passed}


def test_good_answer_passes():
    answer = "민수, 좋은 아침이에요! 바람 완전 시원하죠? 오늘은 무슨 생각 하면서 걸을까요"
    assert failed(answer) == set()


@pytest.mark.parametrize(
    ("answer", "name"),
    [
        ("", "답변 있음"),
        ("하나요. 둘이요. 셋이요. 넷이에요. 다섯이에요.", "문장 수"),
        ("좋아요 😊 같이 걸어요.", "이모지 없음"),
        ("좋아요! ✨ 같이 걸어요.", "이모지 없음"),
        ("벌써 ⏰ 아홉 시예요.", "이모지 없음"),
        ("오른쪽 → 왼쪽으로 가요.", "이모지 없음"),
        ("정말요‼ 대박이에요.", "이모지 없음"),
        ("**좋아요** 같이 걸어요.", "마크다운·목록 없음"),
        ("준비물이에요.\n1. 물\n2. 모자", "마크다운·목록 없음"),
        ("준비물이에요.\n- 물\n- 모자", "마크다운·목록 없음"),
        ("메일은 me@example.com 이에요.", "개인정보·환경 비노출"),
        ("작업 폴더는 /Users/me/cli-sessions 예요.", "개인정보·환경 비노출"),
    ],
)
def test_each_rule_catches_violation(answer, name):
    assert name in failed(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "물은 1.5리터 정도면 충분하대요. 조금씩 자주 마셔요.",
        "오늘 #등산 기록 남겨 볼까요?",
        "가을 산책 완전 좋잖아요~ 천천히 걸어요.",
    ],
)
def test_ordinary_korean_text_is_not_flagged(answer):
    assert failed(answer) == set()


def test_rhetorical_question_marks_are_left_to_the_judge():
    assert failed("그거 완전 좋은데요?! 누가 제일 먼저 쓸까요?") == set()


def test_sentence_count_uses_server_splitter():
    assert count_sentences("오! 좋아요. 그럼 가 볼까요?") == 2  # 짧은 감탄사는 다음 문장과 합친다


def test_question_set_shape():
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    assert len(questions) == 20
    assert len({q["id"] for q in questions}) == 20
    assert all(q["text"].strip() and q["category"] for q in questions)


def test_nickname_check_flags_calling_the_user_by_name():
    ok = code_checks("오, 그거 좋은데요?!", max_sentences=5, nickname="민수")
    assert all(c.passed for c in ok)
    bad = code_checks("민수님, 그거 좋은데요?!", max_sentences=5, nickname="민수")
    assert {c.name for c in bad if not c.passed} == {"호칭 없음"}
    # 호칭을 주지 않으면 검사하지 않는다
    assert "호칭 없음" not in {c.name for c in code_checks("민수님!", max_sentences=5)}
