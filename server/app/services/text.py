"""서비스 공용 문자열 도우미(다른 서비스를 import하지 않아 순환이 생기지 않는다)."""


def escape_like(text: str) -> str:
    """LIKE 패턴에서 %·_·\\를 글자 그대로 찾도록 이스케이프한다(escape="\\"와 함께 쓴다)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
