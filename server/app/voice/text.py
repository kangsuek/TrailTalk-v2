"""읽을 글 다듬기와 보이스 상수(Spec 5.2). 화면에 보이는 문장은 그대로 두고 음성에만 쓴다."""

import re
import unicodedata

_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()\s]|\([^()\s]*\))*\)")
# URL 글자(괄호 제외)로 이어지고 문장부호로 끝나지 않는다("example.com에서", "(www.a.com)")
_URL = re.compile(r"(?:https?://|www\.)[A-Za-z0-9_\-.~:/?#@!$&'*+,;=%]*[A-Za-z0-9_/#=&%-]")
# 숫자 사이의 *(곱하기, 3*4)는 남긴다
_MD_MARKS = re.compile(r"(?<!\d)\*+|\*+(?!\d)|__+|`+|^#{1,6}\s*|^>\s*", re.MULTILINE)
# 줄 첫머리 목록 기호("- 사과", "• 둘째"). 띄어 쓰지 않은 음수(-3도)는 남긴다
_LIST_BULLET = re.compile(r"^[ \t]*[-•+*][ \t]+", re.MULTILINE)
_SPACES = re.compile(r"[ \t\u00a0]{2,}")
# 범위 표기 "3시 ~ 5시"의 ~ 앞 공백은 남긴다
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,!?…])")
_EMPTY_PARENS = re.compile(r"\(\s*\)")


def speech_text(sentence: str) -> str:
    """읽을 문장만 남긴다: 마크다운 표시·링크 주소·URL·이모지를 지운다.

    화면에 보이는 문장(sentence 이벤트의 text)은 그대로 두고 음성에만 쓴다."""
    text = _MD_LINK.sub(r"\1", sentence)
    text = _URL.sub("", text)
    text = _LIST_BULLET.sub("", text)
    text = _MD_MARKS.sub("", text)
    text = "".join(c for c in text if not _is_symbol(c))
    text = _EMPTY_PARENS.sub("", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACES.sub(" ", text).strip()


_UNIT_SYMBOLS = "°℃℉"


def _is_symbol(char: str) -> bool:
    """이모지·기호·이모지 이체 선택자(U+FE0F 등). 단위 기호(℃, °, ㎞ 등)는 남긴다."""
    if char in _UNIT_SYMBOLS or "\u3300" <= char <= "\u33ff":  # CJK 호환 단위(㎞, ㎏)
        return False
    return "\ufe00" <= char <= "\ufe0f" or unicodedata.category(char) in {"So", "Cf", "Sk", "Cn"}


def has_speech(text: str) -> bool:
    """글자나 숫자가 하나라도 있어야 읽을 것이 있다(문장부호만 남은 경우 제외)."""
    return any(c.isalnum() for c in text)


# 설정 화면에서 고를 수 있는 OpenAI TTS 보이스(gpt-4o-mini-tts가 받는 이름).
# 캐릭터가 아닌 제공자 정보라 코드에 둔다
OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)
# 설정 화면의 말 속도 범위(OpenAI speed는 0.25~4.0이지만 걸으며 듣기에 알맞은 범위로 묶는다)
SPEAKING_RATE_MIN = 0.75
SPEAKING_RATE_MAX = 1.5
