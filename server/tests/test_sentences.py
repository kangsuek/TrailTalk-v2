import pytest

from app.llm.sentences import SentenceSplitter


def split_all(text: str) -> list[str]:
    splitter = SentenceSplitter()
    return splitter.feed(text) + splitter.flush()


def split_by_char(text: str) -> list[str]:
    splitter = SentenceSplitter()
    out = []
    for char in text:
        out += splitter.feed(char)
    return out + splitter.flush()


CASES = [
    ("안녕하세요! 오늘 산책 어떠세요? 좋아요.", ["안녕하세요!", "오늘 산책 어떠세요?", "좋아요."]),
    ("정말요?! 대박이네요... 그럼 해 봐요.", ["정말요?!", "대박이네요...", "그럼 해 봐요."]),
    ("가격은 1.5배예요. 버전은 v2.1이고요.", ["가격은 1.5배예요.", "버전은 v2.1이고요."]),
    ("docs.astral.sh 문서를 봤어요. 좋더라고요.", ["docs.astral.sh 문서를 봤어요.", "좋더라고요."]),
    ('그가 "좋다!"라고 말했어요. 끝이에요.', ['그가 "좋다!"라고 말했어요.', "끝이에요."]),
    ('"정말 좋아요!" 그녀가 웃었어요.', ['"정말 좋아요!"', "그녀가 웃었어요."]),
    ('"좋아요." 라고 했어요. 다음이에요.', ['"좋아요." 라고 했어요.', "다음이에요."]),
    ("“완전 대박!” 이라고 외쳤대요. 웃기죠?", ["“완전 대박!” 이라고 외쳤대요.", "웃기죠?"]),
    ('"가자!" 하고 출발했어요.', ['"가자!" 하고 출발했어요.']),
    ('"정말요?" 하늘을 봤어요.', ['"정말요?"', "하늘을 봤어요."]),
    ('끝에 "좋아요."', ['끝에 "좋아요."']),
    ("(정말 좋아요.) 다음이에요.", ["(정말 좋아요.)", "다음이에요."]),
    ("첫 줄이에요\n둘째 줄이에요", ["첫 줄이에요", "둘째 줄이에요"]),
    ("1. 사과 고르기\n2. 씻기", ["1. 사과 고르기", "2. 씻기"]),
    ("Dr. Kim이 왔어요. 반가워요.", ["Dr. Kim이 왔어요.", "반가워요."]),
    ("오! 그거 완전 좋은데요. 해 봐요.", ["오! 그거 완전 좋은데요.", "해 봐요."]),
    ("좋아요~ 다음 얘기 해요.", ["좋아요~", "다음 얘기 해요."]),
    ("메일은 a.b@example.com 이에요. 확인해요.", ["메일은 a.b@example.com 이에요.", "확인해요."]),
    ("끝나지 않은 문장", ["끝나지 않은 문장"]),
    ("반가워요! 😊 오늘 어때요?", ["반가워요! 😊", "오늘 어때요?"]),
    ("좋아요!😊 다음 얘기예요.", ["좋아요!😊", "다음 얘기예요."]),
    ("**좋아요!** 다음 얘기예요.", ["**좋아요!**", "다음 얘기예요."]),
    ("오후 3시 ~ 5시에 만나요. 좋아요.", ["오후 3시 ~ 5시에 만나요.", "좋아요."]),
    ("10~20개면 돼요. 다음이요.", ["10~20개면 돼요.", "다음이요."]),
    ("제 대답은 No. 다른 걸 해요.", ["제 대답은 No.", "다른 걸 해요."]),
    ("좋아요! → 다음 단계예요.", ["좋아요!", "→ 다음 단계예요."]),
    ("좋아요!\u00a0😊 다음이에요.", ["좋아요!\u00a0😊", "다음이에요."]),
    (
        "저장했어요! 📝 다음 할 일도 말해 줘요. 🚶\u200d♀️",
        ["저장했어요! 📝", "다음 할 일도 말해 줘요. 🚶\u200d♀️"],
    ),
    ("", []),
    ("   ", []),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_split(text, expected):
    assert split_all(text) == expected


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_streaming_invariance(text, expected):
    """한 글자씩 넣어도 결과가 같다."""
    assert split_by_char(text) == expected


def test_emits_as_soon_as_boundary_is_known():
    splitter = SentenceSplitter()
    assert splitter.feed("안녕하세요.") == []  # 다음 글자를 봐야 안다
    assert splitter.feed(" 오") == ["안녕하세요."]
    assert splitter.feed("늘 어때요?") == []
    assert splitter.flush() == ["오늘 어때요?"]


def test_short_fragment_at_end_is_kept():
    splitter = SentenceSplitter()
    assert splitter.feed("좋은 생각이에요. 오! ") == ["좋은 생각이에요."]
    assert splitter.flush() == ["오!"]


def test_flush_resets_state():
    splitter = SentenceSplitter()
    splitter.feed("하나. 둘")
    splitter.flush()
    assert splitter.feed("다음 문장이에요. 그") == ["다음 문장이에요."]


def test_long_input_without_boundary_is_fast():
    import time

    splitter = SentenceSplitter()
    started = time.perf_counter()
    for _ in range(20000):
        splitter.feed("가")
    assert splitter.flush() == ["가" * 20000]
    assert time.perf_counter() - started < 2.0
