"""톤 평가의 기계적 검사(코드로 판정할 수 있는 항목). 말투·친근함 같은 판단은 채점 모델이 한다.

페르소나 YAML의 말투 규칙(쓰지 않는 것: 이모지·번호 목록·보고서체·반말)과 앱 규칙을 기준으로 한다:
문장 수 상한, 이모지·마크다운·목록 금지, 개인정보·실행 환경 비노출, 첫인사 뒤 호칭 금지.
질문이 하나뿐인지는 수사적 표현("좋은데요?!")과 구분해야 해서 채점 모델이 본다.
"""

import re
from dataclasses import dataclass

from app.llm.sentences import SentenceSplitter

# 그림 문자·딩뱃·화살표·기술 기호·도형·‼·변형 선택자(음성에서 읽을 수 없는 기호).
# 소스에 보이지 않는 문자가 없게 re 이스케이프로 쓴다
_EMOJI = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF"
    r"\u25A0-\u25FF\u203C\u2049\uFE0F\u200D]"
)
_MARKDOWN = re.compile(r"\*\*|__|`|\[[^\]]+\]\(|^\s*#|^\s*[-*•]\s|^\s*\d+[.)]\s", re.MULTILINE)
_PRIVATE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+|/Users/|/home/|/private/|/tmp/|cli-sessions|claude_code",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def count_sentences(text: str) -> int:
    """화면에 sentence 이벤트로 나뉘어 나갈 문장 수(서버 문장 분할기 기준)."""
    splitter = SentenceSplitter()
    return len(splitter.feed(text)) + len(splitter.flush())


def code_checks(answer: str, *, max_sentences: int, nickname: str | None = None) -> list[Check]:
    """nickname이 있으면 첫인사 이후 답변에 호칭이 없어야 한다(호칭 규칙)."""
    answer = answer.strip()
    sentences = count_sentences(answer)
    emojis = _EMOJI.findall(answer)
    markdown = _MARKDOWN.findall(answer)
    private = _PRIVATE.findall(answer)
    return [
        Check("답변 있음", bool(answer)),
        Check("문장 수", 0 < sentences <= max_sentences, f"{sentences}문장(상한 {max_sentences})"),
        Check("이모지 없음", not emojis, "".join(emojis)),
        Check("마크다운·목록 없음", not markdown, ", ".join(repr(m) for m in markdown)),
        Check("개인정보·환경 비노출", not private, ", ".join(private)),
        *([Check("호칭 없음", nickname not in answer, f"'{nickname}' 포함")] if nickname else []),
    ]
