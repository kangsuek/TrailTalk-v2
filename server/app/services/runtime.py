"""대화 세션의 메모리 상태(서버 프로세스 안에서만 유효).

MCP 도구 인증 토큰, 현재 처리 중인 사용자 턴, 도구가 요청한 세션 상태 변경을 담는다.
DB에 남길 필요가 없는 값만 둔다. 서버가 재시작되면 세션을 다시 열 때 새로 만든다.

턴 처리(app/services/conversation.py)가 지킬 순서:
- 사용자 턴을 커밋한 뒤 current_user_turn_id를 설정하고 send()를 시작한다(note.turn_id 외래 키).
  턴 시작 때 requested_status를 비우고, 턴이 끝나면 pop_requested_status()로 읽어 반영한 뒤
  current_user_turn_id를 None으로 되돌린다.
- 세션을 끝낼 때는 CLI를 먼저 닫고(llm.close) 런타임을 discard한다. 살아 있는 CLI는 처음 받은
  토큰을 계속 쓰므로, 토큰을 바꾸려면 CLI를 닫은 뒤 새로 ensure해야 한다.
끼어들기(M4) 상태는 그때 더한다.
"""

import asyncio
import secrets
from dataclasses import dataclass, field

from app.db.models import SessionStatus


@dataclass
class ConversationRuntime:
    session_id: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    current_user_turn_id: str | None = None  # save_note가 노트를 이 턴에 연결한다
    requested_status: SessionStatus | None = None  # pause_session/end_session이 남긴 요청
    # 한 대화에서 턴은 하나씩만 처리한다(사용자 턴 seq 계산과 CLI 입력 순서)
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def pop_requested_status(self) -> SessionStatus | None:
        status, self.requested_status = self.requested_status, None
        return status


class RuntimeRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ConversationRuntime] = {}

    def ensure(self, session_id: str) -> ConversationRuntime:
        runtime = self._items.get(session_id)
        if runtime is None:
            runtime = self._items[session_id] = ConversationRuntime(session_id)
        return runtime

    def get(self, session_id: str) -> ConversationRuntime | None:
        return self._items.get(session_id)

    def discard(self, session_id: str) -> None:
        self._items.pop(session_id, None)

    def authenticate(self, session_id: str | None, token: str | None) -> ConversationRuntime | None:
        runtime = self._items.get(session_id or "")
        # bytes로 비교한다(str끼리는 ASCII가 아닌 값이 오면 compare_digest가 예외를 낸다)
        if (
            runtime is None
            or not token
            or not secrets.compare_digest(runtime.token.encode(), token.encode())
        ):
            return None
        return runtime
