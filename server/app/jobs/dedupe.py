"""노트 중복 제거(Spec 5.5): 일지 정리 결과에서 이미 저장된 노트와 같은 항목을 거른다.

보수적으로 한다. 정규화(NFKC, 소문자, 공백·문장부호 제거)한 글이 똑같을 때만 같은 항목으로 본다.
표현만 다른 중복은 추출 지시(저장한 노트 목록을 알려 준다, app/jobs/extract.py)에 맡기고 문자열
유사도·포함 관계로는 지우지 않는다(v1에서 "치과 3시"와 "치과 5시"가 같은 항목으로 지워졌다).
예외로 대화 중 저장한 노트 끝의 괄호 설명만 뺀 글과 똑같은 후보는 같은 항목으로 본다(matches_saved).
"""

import re
import unicodedata
from collections.abc import Iterable

_DROP = re.compile(r"[\W_]+")
_NUMBER = re.compile(r"\d+")
# 부정 표현("않", "못하", 띄어 쓴 "안"). 있고 없음이 다르면 반대 뜻이다
_NEGATION = re.compile(r"않|못\s?하|(?:^|\s)안\s")
# 괄호 안 설명. save_note가 노트 끝에 맥락으로 붙인다("… 확인하기 (… 첫 단계)")
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def normalize(text: str) -> str:
    return _DROP.sub("", unicodedata.normalize("NFKC", text).lower())


def is_duplicate(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def new_items(existing: Iterable[str], candidates: Iterable[str]) -> list[str]:
    """candidates 중 existing과도, 앞서 고른 것과도 겹치지 않는 항목(순서 유지)."""
    seen = {normalize(item) for item in existing}
    kept: list[str] = []
    for item in candidates:
        key = normalize(item)
        if not key or key in seen:
            continue
        kept.append(item)
        seen.add(key)
    return kept


def matches_saved(saved: str, candidate: str) -> bool:
    """대화 중 save_note로 저장한 노트와 같은 종류의 추출 후보가 같은 항목인지.

    is_duplicate에 더해, 저장 노트의 괄호 설명(맥락)을 뺀 글이 후보와 똑같은지 본다("X (첫 단계)"와
    "X"). 오판하면 사용자 항목이 사라지므로 후보에 괄호가 없고, 숫자·부정 여부가 원문 그대로 같고,
    뺀 글이 정규화해서 똑같을 때만 같다고 본다. 이때 지워지는 후보는 저장 노트보다 정보가 적다.
    """
    if is_duplicate(saved, candidate):
        return True
    stripped = _BRACKETS.sub(" ", saved)
    if stripped == saved or _BRACKETS.search(candidate) or not normalize(stripped):
        return False
    if _NUMBER.findall(normalize(saved)) != _NUMBER.findall(normalize(candidate)):
        return False
    if bool(_NEGATION.search(f" {saved} ")) != bool(_NEGATION.search(f" {candidate} ")):
        return False
    return normalize(stripped) == normalize(candidate)
