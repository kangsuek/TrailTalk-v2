"""스트리밍 텍스트를 문장 단위로 나눈다(글 대화의 sentence 이벤트, M3부터 문장 단위 TTS).

경계는 다음 글자를 봐야 확정되므로(예: "1.5", "...", "?!") 버퍼 끝에서는 판단을 미룬다.
그래서 한 글자씩 넣어도 한꺼번에 넣어도 결과가 같다. 남은 글자는 flush()로 꺼낸다.
"""

import re
import unicodedata

_TERMINALS = ".!?…~"
_CLOSERS = "\"'”’)」』]>"
_QUOTES = "\"'”’」』"
# 닫는 따옴표 뒤에 띄어 쓴 인용 조사가 오면 문장이 이어진다("좋아요." 라고 했어요)
_QUOTE_PARTICLES = (
    "라고",
    "라는",
    "라며",
    "하고",
    "하며",
    "하는",
    "하면서",
    "이라고",
    "이라는",
    "이라며",
)
# 문장 끝으로도 흔히 쓰는 단어(no, etc, st 등)는 넣지 않는다
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "vs", "e.g", "i.e"}
_SYMBOL_CATEGORIES = {"So", "Sk", "Cf", "Mn", "Me", "Cn"}  # 이모지·결합 문자(수학·통화 기호 제외)
_MARKUP = "*_"  # 마크다운 굵게·기울임(예: "**좋아요!** 다음")
_MIN_SENTENCE_CHARS = 3  # 이보다 짧은 조각(예: "오!")은 다음 문장과 합친다
_WORD_BEFORE = re.compile(r"([A-Za-z.]+)$")
_LIST_NUMBER = re.compile(r"(?:^|\n)\s*\d{1,3}$")


def _is_symbol_token(token: str) -> bool:
    """이모지·기호로만 된 토큰(예: "😊", "🚶‍♀️"). 앞 문장 끝에 붙인다."""
    return bool(token) and all(_is_symbol_char(c) or c in _TERMINALS for c in token)


def _is_symbol_char(char: str) -> bool:
    return unicodedata.category(char) in _SYMBOL_CATEGORIES


def _core_length(sentence: str) -> int:
    """문장부호·공백을 뺀 글자 수."""
    return len(re.sub(rf"[\s{re.escape(_TERMINALS + _CLOSERS)}]", "", sentence))


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""
        self._pending = ""  # 너무 짧아 다음 문장 앞에 붙일 조각
        self._scan_from = 0  # 이미 경계가 없다고 확인한 앞부분은 다시 훑지 않는다

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        sentences: list[str] = []
        while (cut := self._find_boundary()) is not None:
            end, next_start = cut
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[next_start:]
            self._scan_from = 0
            sentences.extend(self._emit(sentence))
        return sentences

    def flush(self) -> list[str]:
        rest = (
            (self._pending + " " + self._buffer).strip() if self._pending else self._buffer.strip()
        )
        self._buffer = ""
        self._pending = ""
        self._scan_from = 0
        return [rest] if rest else []

    def _emit(self, sentence: str) -> list[str]:
        if not sentence:
            return []
        if self._pending:
            sentence = f"{self._pending} {sentence}"
            self._pending = ""
        if _core_length(sentence) < _MIN_SENTENCE_CHARS:
            self._pending = sentence
            return []
        return [sentence]

    def _find_boundary(self) -> tuple[int, int] | None:
        """(문장 끝 위치, 다음 문장 시작 위치). 아직 판단할 수 없으면 None."""
        text = self._buffer
        i = self._scan_from
        while i < len(text):
            char = text[i]
            if char == "\n":
                return i, i + 1
            if char not in _TERMINALS or self._is_range_tilde(text, i):
                i += 1
                continue
            j = i
            while j < len(text) and text[j] in _TERMINALS:
                j += 1
            # 닫는 따옴표·괄호, 바로 붙은 이모지, 마크다운 기호는 앞 문장에 붙인다
            while j < len(text) and (
                text[j] in _CLOSERS or text[j] in _MARKUP or _is_symbol_char(text[j])
            ):
                j += 1
            if j >= len(text):
                self._scan_from = i
                return None  # 다음 글자를 봐야 안다
            if not text[j].isspace():
                i = j  # "1.5", "v2.1", "docs.astral.sh" 등: 경계 아님
                continue
            if any(c in _QUOTES for c in text[i:j]):
                continues = self._quote_continues(text, j)
                if continues is None:
                    self._scan_from = i
                    return None  # 조사인지 아직 모른다
                if continues:
                    i = j
                    continue
            if self._is_exception(text, i, j):
                i = j
                continue
            cut = self._attach_trailing_symbols(text, j)
            if cut is None:
                self._scan_from = i
            return cut
        self._scan_from = len(text)
        return None

    @staticmethod
    def _quote_continues(text: str, space: int) -> bool | None:
        """닫는 따옴표 뒤 공백 다음이 인용 조사면 True. 글자가 모자라 판단할 수 없으면 None."""
        start = space
        while start < len(text) and text[start] in " \t\u00a0":
            start += 1
        rest = text[start:]
        if any(rest.startswith(p) for p in _QUOTE_PARTICLES):
            return True
        if any(p.startswith(rest) for p in _QUOTE_PARTICLES):
            return None
        return False

    @staticmethod
    def _attach_trailing_symbols(text: str, space: int) -> tuple[int, int] | None:
        """문장부호 뒤 공백 다음의 이모지 토큰은 앞 문장에 붙인다("좋아요! 😊 다음")."""
        start = space
        while start < len(text) and text[start] in " \t\u00a0":
            start += 1
        if start >= len(text):
            return None  # 공백 뒤가 이모지인지 아직 모른다
        end = start
        while end < len(text) and not text[end].isspace():
            end += 1
        token = text[start:end]
        if not token or not _is_symbol_token(token):
            return space, space + 1
        if end >= len(text):
            return None  # 토큰이 끝났는지 아직 모른다
        return end, end + 1

    @staticmethod
    def _is_range_tilde(text: str, index: int) -> bool:
        """띄어 쓴 범위 표기("3시 ~ 5시")의 ~는 문장 끝이 아니다."""
        return text[index] == "~" and index > 0 and text[index - 1].isspace()

    @staticmethod
    def _is_exception(text: str, start: int, end: int) -> bool:
        run = text[start:end].rstrip(_CLOSERS)
        if run != ".":
            return False
        before = text[:start]
        if _LIST_NUMBER.search(before):  # "1. 항목" 같은 번호 목록
            return True
        word = _WORD_BEFORE.search(before)
        return bool(word and word.group(1).lower() in _ABBREVIATIONS)
