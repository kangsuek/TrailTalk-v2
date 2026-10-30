"""호칭 서비스: 호칭 규칙과 저장.

내부 MCP는 "이번 사용자 발화에 나온 호칭만" 받는 검사를 얹고(`utterance_supports`), 외부 앱
MCP는 서버가 발화를 알 수 없어 그 검사 없이 저장한다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.services.profile import get_or_create_profile

NICKNAME_MIN_CHARS = 2  # 님·씨를 뗀 호칭이 이보다 짧으면 거의 모든 발화에 들어 있어 근거가 못 된다


class NicknameRejected(AppError):
    def __init__(self) -> None:
        super().__init__(
            "validation_error",
            "호칭은 님·씨를 뺀 부분이 두 글자 이상이어야 바꿀 수 있습니다.",
            422,
        )


def nickname_core(nickname: str) -> str:
    """호칭에서 공백과 끝의 존칭(님·씨)을 뺀 부분. 사용자 발화와 맞춰 볼 때 쓴다."""
    compact = "".join(nickname.split())
    for suffix in ("님", "씨"):
        if len(compact) > len(suffix) and compact.endswith(suffix):
            return compact[: -len(suffix)]
    return compact


def check_nickname(nickname: str) -> str:
    """님·씨를 뺀 부분이 2글자 이상인지 본다. 통과하면 그 부분(core)을 돌려준다."""
    core = nickname_core(nickname)
    if len(core) < NICKNAME_MIN_CHARS:
        raise NicknameRejected()
    return core


def utterance_supports(core: str, utterance: str) -> bool:
    """사용자 발화(공백 무시)에 호칭 core가 들어 있는가."""
    return core in "".join(utterance.split())


async def set_nickname(db: AsyncSession, nickname: str) -> str:
    """호칭을 프로필에 저장한다(웹 글 대화와 하나를 공유). 글자 수·모양은 호출자가 `Nickname`
    형식으로 검증한 값이고, 여기서는 존칭을 뺀 부분 2글자 이상만 본다."""
    check_nickname(nickname)
    profile = await get_or_create_profile(db)
    profile.nickname = nickname
    await db.commit()
    return nickname
