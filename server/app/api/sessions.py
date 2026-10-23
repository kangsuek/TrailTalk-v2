"""대화 세션 API(client-contract 2절): 시작(인사말), 글 턴(SSE), 종료(마무리 멘트).

음성 턴·다시 열기·미리 띄우기는 해당 마일스톤(M2~M4)에서 더한다.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.events import sse_response_doc
from app.db.models import ConversationSession, SessionMode
from app.db.session import DbSession
from app.services import closing, conversation
from app.services.profile import profile_with_persona

router = APIRouter(tags=["sessions"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class EventStreamResponse(StreamingResponse):
    """연결이 끊겨도 본문 제너레이터를 바로 닫는다.

    Starlette는 끊긴 스트림의 제너레이터를 닫지 않고 GC에 맡긴다. 그동안 턴 락과 CLI 턴이
    풀리지 않으므로 여기서 직접 닫는다(제너레이터의 finally·aclosing이 CLI 턴을 멈춘다).
    """

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.body_iterator.aclose()  # type: ignore[union-attr]


class SessionOut(BaseModel):
    id: str
    mode: Literal["text", "voice"]
    status: Literal["active", "paused", "ended"]
    started_at: datetime
    ended_at: datetime | None

    @classmethod
    def of(cls, convo: ConversationSession) -> "SessionOut":
        return cls(
            id=convo.id,
            mode=convo.mode.value,
            status=convo.status.value,
            started_at=convo.started_at,
            ended_at=convo.ended_at,
        )


class SavedCounts(BaseModel):
    idea: int
    todo: int
    memo: int


class SessionClosed(BaseModel):
    """끝내기 응답. closing은 캐릭터가 하는 마무리 멘트, saved는 이 대화에서 저장한 노트 개수다.

    journal_status는 일지 정리(M2) 전까지 항상 null이다."""

    session: SessionOut
    closing: str
    closing_audio: str | None  # 마무리 멘트 MP3(base64). 음성 세션(M3)에서만
    saved: SavedCounts
    journal_status: Literal["pending", "done", "failed"] | None


class SessionCreate(BaseModel):
    mode: Literal["text", "voice"] = "text"


class GreetingOut(BaseModel):
    turn_id: str
    text: str
    audio: str | None  # 인사말 MP3(base64). 음성 세션(M3)에서만


class AckOut(BaseModel):
    text: str
    audio: str | None  # 맞장구 MP3(base64). 음성 세션(M3)에서만


class PersonaOut(BaseModel):
    """화면에 보일 캐릭터 정보. 클라이언트는 캐릭터 이름을 코드에 두지 않고 이 값을 쓴다(NFR-08)."""

    id: str
    name: str
    ack: list[AckOut]


class SessionStarted(BaseModel):
    session: SessionOut
    greeting: GreetingOut
    persona: PersonaOut


class TurnCreate(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request, db: DbSession) -> SessionStarted:
    convo, greeting, loaded = await conversation.start_session(
        request.app, db, SessionMode(body.mode)
    )
    return SessionStarted(
        session=SessionOut.of(convo),
        greeting=GreetingOut(turn_id=greeting.id, text=greeting.text, audio=None),
        persona=PersonaOut(
            id=loaded.persona.id,
            name=loaded.persona.name,
            ack=[AckOut(text=text, audio=None) for text in loaded.persona.ack],
        ),
    )


@router.post(
    "/sessions/{session_id}/turns",
    response_class=StreamingResponse,
    responses=sse_response_doc("턴 이벤트 스트림(turn → sentence·tool → done 또는 error)"),
)
async def create_turn(
    session_id: str, body: TurnCreate, request: Request, db: DbSession
) -> StreamingResponse:
    convo = await conversation.get_session(db, session_id)
    conversation.check_turn_allowed(request.app, convo)
    # 요청 세션의 커넥션을 스트림 내내 쥐지 않는다. 끊김으로 취소된 채 닫히면 망가진 커넥션이
    # 풀로 돌아간다. 스트림은 자기 세션을 따로 연다
    await db.close()
    return EventStreamResponse(
        conversation.stream_turn(request.app, session_id, body.text.strip()),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, request: Request, db: DbSession) -> SessionClosed:
    """세션을 끝내고 마무리 멘트를 준다(멱등). 일지 정리(추출)는 M2에서 더한다."""
    app = request.app
    convo = await conversation.get_session(db, session_id)
    await conversation.end_session(app, db, convo)
    await db.commit()
    await db.refresh(convo)
    counts = await closing.count_notes(db, session_id, since=convo.reopened_at)
    _, loaded = await profile_with_persona(db, app.state.settings)
    await db.commit()
    return SessionClosed(
        session=SessionOut.of(convo),
        closing=closing.closing_message(loaded.persona, counts),
        closing_audio=None,
        saved=SavedCounts(**{kind.value: count for kind, count in counts.items()}),
        journal_status=None,
    )
