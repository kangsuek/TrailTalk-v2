"""대화 세션 API(client-contract 2절): 시작(인사말), 글·음성 턴(SSE), 종료(마무리 멘트), 다시 열기.

음성 세션이면 인사말·마무리 멘트·재개 인사말과 답변 문장에 소리(MP3 base64)를 싣는다(M3).
미리 띄우기는 M4에서 더한다.
"""

import time
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.events import sse_response_doc
from app.api.journal import TurnOut
from app.db.models import ConversationSession, SessionMode
from app.db.session import DbSession
from app.errors import AppError
from app.jobs import extract
from app.persona.loader import LoadedPersona, load_session_persona
from app.services import closing, conversation
from app.services.voice import VoiceTurn, speak
from app.voice.audio import prepare_for_stt

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

    journal_status는 일지 정리 상태다. pending이면 기다리는 시간 안에 정리가 끝나지 않은 것이다
    (개수가 나중에 늘 수 있다). null은 정리 기록이 없는 것이다."""

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


class SessionReopen(BaseModel):
    mode: Literal["text", "voice"] = "text"  # 이번에 쓸 방식(처음과 달라도 된다)


class SessionReopened(BaseModel):
    """다시 열기 응답. greeting은 전문 끝에 새로 남긴 재개 인사말(호칭 없음), turns는 그 인사말까지
    포함한 전체 전문(일지 상세의 turns와 같은 형식)이다."""

    session: SessionOut
    greeting: GreetingOut
    persona: PersonaOut
    turns: list[TurnOut]


class TurnCreate(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


def _persona_out(loaded: LoadedPersona) -> PersonaOut:
    return PersonaOut(
        id=loaded.persona.id,
        name=loaded.persona.name,
        ack=[AckOut(text=text, audio=None) for text in loaded.persona.ack],
    )


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request, db: DbSession) -> SessionStarted:
    mode = SessionMode(body.mode)
    convo, greeting, loaded = await conversation.start_session(request.app, db, mode)
    audio = None
    if mode is SessionMode.VOICE:
        style = await conversation.session_voice_style(request.app, db, loaded.persona)
        audio = await speak(request.app, greeting.text, style)
    return SessionStarted(
        session=SessionOut.of(convo),
        greeting=GreetingOut(turn_id=greeting.id, text=greeting.text, audio=audio),
        persona=_persona_out(loaded),
    )


@router.post("/sessions/{session_id}/reopen")
async def reopen_session(
    session_id: str, request: Request, db: DbSession, body: SessionReopen | None = None
) -> SessionReopened:
    """끝난 대화(또는 열려 있지 않은 진행 중 대화)를 같은 세션으로 다시 열어 이어서 대화한다.
    답변 중이면 409 turn_in_progress, 재개 인사말을 받지 못하면 시작 실패와 같은 오류이고 대화는
    원래 상태로 남는다."""
    mode = SessionMode((body or SessionReopen()).mode)
    convo, greeting, turns, loaded = await conversation.reopen_session(
        request.app, db, session_id, mode
    )
    audio = None
    if mode is SessionMode.VOICE:
        style = await conversation.session_voice_style(request.app, db, loaded.persona)
        audio = await speak(request.app, greeting.text, style)
    return SessionReopened(
        session=SessionOut.of(convo),
        greeting=GreetingOut(turn_id=greeting.id, text=greeting.text, audio=audio),
        persona=_persona_out(loaded),
        turns=[TurnOut.of(t) for t in turns],
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


async def _read_upload(request: Request, max_bytes: int) -> bytes:
    """업로드 본문을 한도 안에서만 읽는다. Content-Length가 한도를 넘으면 읽지 않고 413, 헤더가
    없거나 거짓이면 읽는 도중 한도를 넘는 순간 끊는다."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise AppError("audio_invalid", "오디오가 너무 큽니다.", 413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise AppError("audio_invalid", "오디오가 너무 큽니다.", 413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/sessions/{session_id}/turns/audio",
    response_class=StreamingResponse,
    responses=sse_response_doc(
        "음성 턴 이벤트 스트림(transcript → turn → sentence·tool → done 또는 error)"
    ),
)
async def create_audio_turn(session_id: str, request: Request, db: DbSession) -> StreamingResponse:
    """말 한 번의 오디오 바이트(multipart 아님)를 인식해 턴을 시작한다. SSE를 열기 전에 인식하므로
    오디오·인식 오류와 말 없음은 JSON 오류이고 사용자 메시지를 만들지 않는다."""
    started = time.monotonic()
    app = request.app
    settings = app.state.settings
    convo = await conversation.get_session(db, session_id)
    conversation.check_turn_allowed(app, convo)
    data = await _read_upload(request, settings.stt_max_bytes)
    uploaded = time.monotonic()
    audio = await prepare_for_stt(
        data,
        request.headers.get("content-type"),
        max_bytes=settings.stt_max_bytes,
        ffmpeg_path=settings.ffmpeg_path,
        timeout_s=settings.ffmpeg_timeout_s,
    )
    text = (await app.state.stt.transcribe(audio)).strip()
    if not text:
        raise AppError("no_speech", "말소리가 들리지 않았어요.", 422)
    recognized = time.monotonic()
    await db.close()  # 스트림은 자기 세션을 따로 연다(글 턴과 같다)
    voice = VoiceTurn(
        started=started,
        transcript=text,
        upload_ms=round((uploaded - started) * 1000),
        stt_ms=round((recognized - uploaded) * 1000),
        audio_bytes=len(data),
    )
    return EventStreamResponse(
        conversation.stream_turn(app, session_id, text, voice),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, request: Request, db: DbSession) -> SessionClosed:
    """세션을 끝내고 일지 정리를 띄워 최대 extract_wait_s 기다린 뒤 마무리 멘트를 준다(멱등).
    마무리 멘트의 저장 개수는 정리로 더해진 노트까지 센다."""
    app = request.app
    settings = app.state.settings
    convo = await conversation.get_session(db, session_id)
    await conversation.end_session(app, db, convo)
    await db.commit()
    await extract.wait_extraction(app, session_id, settings.extract_wait_s)
    # 기다리는 사이 지워졌으면 404. get은 지운 것을 모르는 메모리 속 객체를 돌려주므로
    # DB에서 다시 읽는다
    convo = await conversation.reload_session(db, session_id)
    counts = await closing.count_notes(db, session_id, since=convo.reopened_at)
    journal_status = convo.extract_status.value if convo.extract_status else None
    if journal_status is None and session_id in app.state.extractions:
        journal_status = "pending"  # 정리 작업이 막 떠서 아직 상태를 쓰지 않았다
    # 마무리 멘트는 그 대화가 시작한 페르소나를 따른다(대화 중에 프로필을 바꿔도)
    loaded = load_session_persona(settings.persona_dir, convo.persona_id, settings.default_persona)
    closing_text = closing.closing_message(loaded.persona, counts)
    closing_audio = None
    if convo.mode is SessionMode.VOICE:
        style = await conversation.session_voice_style(app, db, loaded.persona)
        closing_audio = await speak(app, closing_text, style)
    return SessionClosed(
        session=SessionOut.of(convo),
        closing=closing_text,
        closing_audio=closing_audio,
        saved=SavedCounts(**{kind.value: count for kind, count in counts.items()}),
        journal_status=journal_status,
    )
