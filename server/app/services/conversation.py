"""대화 세션과 턴 처리(Spec 5.8, client-contract 2절).

- 세션 시작: 프롬프트를 조립해 CLI를 열고, 숨은 첫 메시지로 받은 인사말을
  assistant 턴(seq 0, greeting)으로 저장한다.
- 턴: 사용자 턴을 먼저 저장하고 CLI 이벤트를 SSE 이벤트(app/api/events.py)로 바꿔 보낸다.
  답변은 문장을 보내기 전에 문장마다 커밋한다. 끝나지 못한 답변(연결 끊김·오류·서버 강제 종료)은
  보낸 문장까지 interrupted로 남는다.
- 종료: CLI를 닫고 대화 런타임(MCP 토큰)을 버린 뒤 CLI 대화 기록 파일을 지운다. 일지 정리(추출)와
  다시 열기는 M2에서 더한다.

프롬프트는 세션을 처음 열 때 만들어 세션 행(system_prompt)에 고정한다. CLI가 죽어 --resume으로
다시 띄울 때도 같은 값을 쓴다. 호칭은 프롬프트에 넣지 않고 인사말 요청에만 붙인다(Spec 5.7).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime

import anyio
from fastapi import FastAPI
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import (
    DoneEvent,
    ErrorEvent,
    SentenceEvent,
    ToolEvent,
    TurnEvent,
    encode_sse,
    public_tool_name,
)
from app.db.models import (
    ConversationSession,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.db.types import new_id, utcnow
from app.errors import AppError
from app.llm.backend import LlmError, LlmSession
from app.llm.claude_cli import delete_cli_session_file
from app.llm.events import (
    TextDelta,
    ToolCalled,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnStarted,
)
from app.llm.sentences import SentenceSplitter
from app.mcp.server import mcp_client_config
from app.persona.loader import LoadedPersona
from app.persona.memory import load_memory
from app.persona.prompt import build_system_prompt, current_time_note, greeting_request
from app.services.profile import profile_chat_model, profile_with_persona
from app.services.runtime import ConversationRuntime

logger = logging.getLogger("trailtalk.conversation")


class SessionNotFound(AppError):
    def __init__(self) -> None:
        super().__init__("session_not_found", "대화 세션을 찾을 수 없습니다.", 404)


class SessionEnded(AppError):
    def __init__(self) -> None:
        super().__init__("session_ended", "이미 끝난 대화입니다.", 409)


class TurnBusy(AppError):
    def __init__(self) -> None:
        super().__init__("turn_in_progress", "이전 답변이 아직 끝나지 않았습니다.", 409)


_END_WAIT_S = 10.0  # 끝내기: 진행 중인 턴이 정리되길 기다리는 시간

_LLM_PUBLIC_MESSAGES = {
    "llm_process_exited": "답변 도중 연결이 끊겼어요. 다시 말해 주세요.",
    "llm_timeout": "답변이 너무 오래 걸려 멈췄어요. 다시 말해 주세요.",
}


def public_error(exc: AppError) -> AppError:
    """클라이언트에 보낼 오류. LLM·서버 오류의 상세(CLI stderr, 경로 등)는 로그에만 남긴다."""
    if isinstance(exc, LlmError):
        message = _LLM_PUBLIC_MESSAGES.get(exc.code, "답변을 만들지 못했습니다.")
        return LlmError(exc.code, message, exc.status_code)
    if exc.status_code >= 500:
        return AppError(exc.code, "서버 내부 오류가 발생했습니다.", exc.status_code)
    return exc


def start_error(exc: AppError) -> AppError:
    """세션 시작 실패를 클라이언트에 보낼 오류로 바꾼다(내부 정보 없이 시작용 문구)."""
    if isinstance(exc, LlmError) or exc.status_code >= 500:
        logger.warning("세션 시작 실패(code=%s): %s", exc.code, exc.message)
        return LlmError(
            exc.code, "대화를 시작하지 못했어요. 잠시 뒤 다시 해 주세요.", exc.status_code
        )
    return exc


async def _set_status(
    db: AsyncSession,
    session_id: str,
    status: SessionStatus,
    ended_at: datetime | None = None,
    idle_cutoff: datetime | None = None,
) -> int:
    """상태를 바꾸고 바뀐 행 수를 돌려준다. 이미 끝난 세션은 건드리지 않는다(종료 요청과 턴이
    겹쳐도 ended를 지킨다).

    ended_at: 끝난 시각(기본은 지금). 무발화 종료는 마지막 활동 시각을 넘긴다.
    idle_cutoff: 무발화 종료용. cutoff 이후에 쓴 턴이 있으면(감시가 대상을 고른 뒤 말을 걸었다)
    같은 문장 안에서 건너뛴다. 확인과 쓰기 사이에 끼어드는 경쟁이 없다."""
    values: dict = {"status": status}
    if status is SessionStatus.ENDED:
        values["ended_at"] = ended_at or utcnow()
    query = update(ConversationSession).where(
        ConversationSession.id == session_id,
        ConversationSession.status != SessionStatus.ENDED,
    )
    if idle_cutoff is not None:
        spoke_after = (
            select(Turn.id)
            .where(Turn.session_id == ConversationSession.id, Turn.created_at >= idle_cutoff)
            .correlate(ConversationSession)
            .exists()
        )
        query = query.where(~spoke_after)
    result = await db.execute(query.values(**values).execution_options(synchronize_session=False))
    return result.rowcount


async def get_session(db: AsyncSession, session_id: str) -> ConversationSession:
    convo = await db.get(ConversationSession, session_id)
    if convo is None:
        raise SessionNotFound()
    return convo


async def _profile(app: FastAPI, db: AsyncSession):
    profile, loaded = await profile_with_persona(db, app.state.settings)
    # 프로필·페르소나 행을 만들거나 고쳤으면 바로 커밋한다. 턴 내내 쓰기 잠금을 쥐면
    # 같은 시간에 MCP save_note 같은 다른 쓰기가 SQLite 잠금 대기 끝에 실패한다
    await db.commit()
    return profile, loaded


async def _get_cli(
    app: FastAPI, session_id: str, prompt: str, model: str, resume_id: str | None = None
) -> LlmSession:
    """model: 대화 모델(프로필). 살아 있는 CLI와 다르면 매니저가 --resume으로 다시 띄운다."""
    settings = app.state.settings
    runtime = app.state.runtimes.ensure(session_id)
    return await app.state.llm.get(
        session_id,
        system_prompt=prompt,
        model=model,
        resume_id=resume_id,
        mcp_config=mcp_client_config(settings.internal_base_url, runtime),
    )


async def open_llm(
    app: FastAPI, db: AsyncSession, convo: ConversationSession
) -> tuple[LlmSession, LoadedPersona]:
    """대화의 CLI 세션과 프롬프트에 쓴 페르소나.

    CLI가 살아 있으면 재사용하고 없으면 --resume. 대화 모델은 부를 때마다 프로필에서 읽으므로
    대화 중에 바꿔도 다음 답변부터 쓴다(모델이 바뀌면 CLI를 같은 맥락으로 다시 띄운다).

    프롬프트는 세션을 처음 열 때 만들어 세션 행에 고정한다. 그 뒤 프로필을 바꿔도 CLI를 다시 띄울
    때(유휴 정리·크래시·서버 재시작 후 --resume) 같은 프롬프트를 쓴다.
    """
    profile, loaded = await _profile(app, db)
    settings = app.state.settings
    if convo.system_prompt is None:
        memory = await load_memory(db, settings, profile, convo.started_at)
        await db.commit()  # 읽기만 했으니 트랜잭션을 닫는다
        convo.system_prompt = build_system_prompt(
            loaded.persona,
            mode=convo.mode.value,
            now=convo.started_at,
            timezone=settings.timezone,
            memory=memory,
        )
        await db.commit()  # 이 턴이 오류로 끝나도 고정한 프롬프트는 남긴다
    model = profile_chat_model(profile, settings)
    session = await _get_cli(app, convo.id, convo.system_prompt, model, convo.cli_session_id)
    return session, loaded


async def teardown(app: FastAPI, session_id: str, cli_session_id: str | None) -> None:
    """CLI를 닫은 뒤 런타임을 버린다(순서 주의: services/runtime.py). 기록 파일도 지운다."""
    await app.state.llm.close(session_id)
    app.state.runtimes.discard(session_id)
    if await asyncio.to_thread(delete_cli_session_file, cli_session_id):
        logger.info("CLI 대화 기록 삭제(session=%s)", session_id)


async def start_session(
    app: FastAPI, db: AsyncSession, mode: SessionMode
) -> tuple[ConversationSession, Turn, LoadedPersona]:
    profile, loaded = await _profile(app, db)
    nickname = profile.nickname  # 아래 커밋들로 만료되기 전에 꺼내 둔다
    convo = ConversationSession(mode=mode, persona_id=loaded.persona.id)
    db.add(convo)
    await db.commit()
    session_id = convo.id
    runtime = app.state.runtimes.ensure(session_id)
    cli_session_id = None
    seen: list[str] = []  # 인사말이 실패해도 띄운 CLI의 기록 파일을 지우도록 ID를 남긴다
    try:
        async with runtime.turn_lock:
            session, loaded = await open_llm(app, db, convo)
            text, cli_session_id = await _receive_greeting(
                session,
                current_time_note(utcnow(), app.state.settings.timezone)
                + greeting_request(nickname),
                session_id,
                seen,
            )
            greeting = Turn(
                session_id=convo.id, seq=0, role=TurnRole.ASSISTANT, text=text, greeting=True
            )
            db.add(greeting)
            convo.cli_session_id = cli_session_id
            await db.commit()
    except BaseException as exc:
        # 인사말도 없는 빈 세션은 남기지 않는다. 요청 취소·서버 종료 중에도 정리하도록
        # 취소에서 보호한다
        try:
            with anyio.CancelScope(shield=True):
                await _discard_new_session(app, db, session_id, cli_session_id or _last(seen))
        except Exception:
            logger.exception("시작 실패 정리 중 예외(session=%s)", session_id)
        if isinstance(exc, AppError):
            raise start_error(exc) from exc
        raise
    return convo, greeting, loaded


def _last(items: list[str]) -> str | None:
    return items[-1] if items else None


async def _receive_greeting(
    session: LlmSession, instruction: str, session_id: str, seen: list[str]
) -> tuple[str, str | None]:
    """숨은 안내를 보내 인사말을 받는다. (인사말, CLI 세션 ID)
    seen: 받은 CLI 세션 ID를 바로 적는다(실패해도 호출한 쪽이 기록 파일을 지울 수 있게)."""
    cli_session_id = None
    parts: list[str] = []
    finished = None
    async with aclosing(session.send(instruction)) as stream:
        async for event in stream:
            if isinstance(event, TurnStarted) and event.cli_session_id:
                cli_session_id = event.cli_session_id
                seen.append(cli_session_id)
            elif isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, TurnFinished):
                finished = event
    if finished is None or finished.is_error:
        detail = finished.error_message if finished else "응답 없음"
        logger.warning("인사말 실패(session=%s): %s", session_id, detail)
        raise LlmError("llm_error", "인사말을 받지 못했습니다.")
    return "".join(parts).strip() or finished.text, cli_session_id


async def _discard_new_session(
    app: FastAPI, db: AsyncSession, session_id: str, cli_session_id: str | None
) -> None:
    await db.rollback()
    try:
        await teardown(app, session_id, cli_session_id)
    except Exception:  # 정리가 실패해도 빈 세션은 지운다(남으면 active로 떠돈다)
        logger.exception("시작 실패 세션의 CLI 정리 실패(session=%s)", session_id)
    await db.execute(delete(ConversationSession).where(ConversationSession.id == session_id))
    await db.commit()


async def end_session(
    app: FastAPI,
    db: AsyncSession,
    convo: ConversationSession,
    ended_at: datetime | None = None,
    idle_cutoff: datetime | None = None,
) -> bool:
    """세션을 끝낸다. 이미 끝났으면 정리만 다시 한다(멱등). ended_at: 끝난 시각(기본은 지금).

    idle_cutoff: 무발화 종료에서만 준다. 그 뒤에 말을 건 세션이면 끝내지 않고 False를 돌려준다
    (CLI도 닫지 않는다). 그 밖에는 True.

    정리(CLI 닫기)는 턴 잠금을 쥐고 한다. 일지 정리(추출)와 다시 열기는 M2에서 더한다.
    """
    changed = await _set_status(db, convo.id, SessionStatus.ENDED, ended_at, idle_cutoff)
    await db.commit()
    if idle_cutoff is not None and changed == 0:
        await db.refresh(convo)
        if convo.status is not SessionStatus.ENDED:
            return False  # 그사이 말을 걸었다
    runtime = app.state.runtimes.ensure(convo.id)
    await app.state.llm.close(convo.id)  # 진행 중인 턴이 있으면 여기서 끊긴다
    locked = False
    try:
        # 턴 스트림이 정리를 마칠 때까지 기다린다(CLI를 닫았으니 보통 바로 끝난다)
        async with asyncio.timeout(_END_WAIT_S):
            await runtime.turn_lock.acquire()
        locked = True
    except TimeoutError:
        logger.warning("종료 중 턴 정리 대기 시간 초과(session=%s)", convo.id)
    try:
        await db.refresh(convo)  # 턴 중에 바뀐 cli_session_id·상태를 다시 읽는다
        if convo.status is not SessionStatus.ENDED:
            return True
        await teardown(app, convo.id, convo.cli_session_id)
    finally:
        if locked:
            runtime.turn_lock.release()
    return True


def check_turn_allowed(app: FastAPI, convo: ConversationSession) -> None:
    """SSE를 열기 전 검사. 실패는 JSON 오류로 나간다."""
    if convo.status is SessionStatus.ENDED:
        raise SessionEnded()
    runtime = app.state.runtimes.get(convo.id)
    if runtime is not None and runtime.turn_lock.locked():
        raise TurnBusy()


def _error(exc: AppError) -> bytes:
    exc = public_error(exc)
    return encode_sse(ErrorEvent(code=exc.code, message=exc.message))


async def _next_seq(db: AsyncSession, session_id: str) -> int:
    last_seq = await db.scalar(select(func.max(Turn.seq)).where(Turn.session_id == session_id))
    return (last_seq if last_seq is not None else -1) + 1


async def stream_turn(app: FastAPI, session_id: str, text: str) -> AsyncIterator[bytes]:
    """사용자 메시지 한 턴을 처리하며 SSE 바이트를 낸다.

    클라이언트가 끊기면 이 제너레이터가 닫히고 aclosing이 CLI 턴을 멈춘다. 이때 사용자 턴과
    보낸 문장까지의 답변(interrupted)이 남는다.
    """
    runtime = app.state.runtimes.ensure(session_id)
    if runtime.turn_lock.locked():  # 검사와 획득 사이에 await가 없어 경합하지 않는다
        yield _error(TurnBusy())
        return
    async with runtime.turn_lock:
        db = app.state.session_factory()
        try:
            # 안쪽 제너레이터도 바로 닫아야 락을 풀기 전에 CLI 턴 정리(인터럽트)가 끝난다
            turn = _run_turn(app, db, runtime, session_id, text)
            async with aclosing(turn) as chunks:
                async for chunk in chunks:
                    yield chunk
        finally:
            # 연결이 끊겨 취소된 중에도 커넥션을 온전히 돌려준다(닫기가 다시 취소되면 망가진
            # 커넥션이 풀에 남아 다음 요청이 실패한다)
            with anyio.CancelScope(shield=True):
                await db.close()


async def _run_turn(
    app: FastAPI,
    db: AsyncSession,
    runtime: ConversationRuntime,
    session_id: str,
    text: str,
) -> AsyncIterator[bytes]:
    """턴 락을 잡은 상태에서 한 턴을 처리한다.

    짧은 DB 작업 구간은 취소(연결 끊김)에서 보호한다. 쿼리 도중 취소되면 SQLAlchemy가
    커넥션을 폐기하다 그것마저 취소되어, 죽은 커넥션이 풀에 남는다.
    """
    try:
        with anyio.CancelScope(shield=True):
            convo = await db.get(ConversationSession, session_id)
            if convo is not None and convo.status is not SessionStatus.ENDED:
                seq = await _next_seq(db, session_id)
                user_turn = Turn(session_id=session_id, seq=seq, role=TurnRole.USER, text=text)
                db.add(user_turn)
                await _set_status(db, session_id, SessionStatus.ACTIVE)  # 쉬기 중이면 이어 감
                await db.commit()
    except Exception:
        logger.exception("사용자 턴 저장 실패(session=%s)", session_id)
        yield _error(AppError("internal_error", "서버 내부 오류가 발생했습니다.", 500))
        return
    if convo is None or convo.status is SessionStatus.ENDED:
        app.state.runtimes.discard(session_id)  # 위에서 새로 만든 런타임(토큰)을 남기지 않는다
        yield _error(SessionNotFound() if convo is None else SessionEnded())
        return
    user_turn_id = user_turn.id  # 아래 커밋·롤백 뒤에도 쓰도록 미리 꺼내 둔다

    assistant_id = new_id()
    yield encode_sse(TurnEvent(turn_id=assistant_id))
    runtime.requested_status = None
    runtime.current_user_turn_id = user_turn_id
    try:
        with anyio.CancelScope(shield=True):
            await db.refresh(convo)  # 그사이 종료 API가 끝냈으면 CLI를 다시 띄우지 않는다
            if convo.status is SessionStatus.ENDED:
                raise SessionEnded()
            session, _ = await open_llm(app, db, convo)
        splitter = SentenceSplitter()
        index = 0
        parts: list[str] = []
        sent: list[str] = []  # 클라이언트에 보낸 문장(부분 답변으로 저장)
        reply_saved = False
        tool_names: dict[str, str] = {}
        finished: TurnFinished | None = None

        async def sentence_chunk(item: str) -> bytes:
            """먼저 커밋하고 보낸다. 클라이언트가 받은 문장은 서버가 죽어도 남는다(보내기 직전에
            끊기면 못 받은 문장이 하나 더 남을 수 있다). 끝나기 전에는 interrupted로 둔다."""
            nonlocal index, reply_saved
            sent.append(item)
            with anyio.CancelScope(shield=True):
                await _save_reply(
                    db, assistant_id, session_id, seq + 1, " ".join(sent), True, reply_saved
                )
                await db.commit()
            reply_saved = True
            chunk = encode_sse(SentenceEvent(index=index, text=item))
            index += 1
            return chunk

        # 지금 시각을 CLI에만 알린다(기록에는 남기지 않는다)
        cli_input = current_time_note(utcnow(), app.state.settings.timezone) + text
        # CLI 오류(크래시·시간 초과)로 끝나도 받은 글은 아래에서 마저 보내고 저장한 뒤 다시 던진다
        stream_error: LlmError | None = None
        try:
            async with aclosing(session.send(cli_input)) as stream:
                async for event in stream:
                    if isinstance(event, TurnStarted):
                        if event.cli_session_id and event.cli_session_id != convo.cli_session_id:
                            convo.cli_session_id = event.cli_session_id
                            with anyio.CancelScope(shield=True):
                                await db.commit()
                    elif isinstance(event, TextDelta):
                        parts.append(event.text)
                        for item in splitter.feed(event.text):
                            yield await sentence_chunk(item)
                    elif isinstance(event, ToolStarted):
                        # 도구 앞의 말("잠깐 찾아볼게요")은 바로 문장으로 보낸다
                        for item in splitter.flush():
                            yield await sentence_chunk(item)
                        if parts and not parts[-1][-1:].isspace():
                            parts.append("\n\n")
                        name = public_tool_name(event.name)
                        tool_names[event.tool_use_id] = name
                        yield encode_sse(
                            ToolEvent(phase="start", tool_use_id=event.tool_use_id, name=name)
                        )
                    elif isinstance(event, ToolCalled):
                        name = tool_names.setdefault(
                            event.tool_use_id, public_tool_name(event.name)
                        )
                        yield encode_sse(
                            ToolEvent(
                                phase="call",
                                tool_use_id=event.tool_use_id,
                                name=name,
                                input=event.input,
                            )
                        )
                    elif isinstance(event, ToolFinished):
                        yield encode_sse(
                            ToolEvent(
                                phase="end",
                                tool_use_id=event.tool_use_id,
                                name=tool_names.get(event.tool_use_id, "unknown"),
                                summary=event.summary,
                                is_error=event.is_error,
                            )
                        )
                    elif isinstance(event, TurnFinished):
                        finished = event
        except LlmError as exc:
            stream_error = exc
        for item in splitter.flush():
            yield await sentence_chunk(item)
        if stream_error is not None:
            raise stream_error  # 아래 except AppError가 상태 요청 반영·오류 이벤트를 맡는다

        if finished is None or (finished.is_error and not finished.interrupted):
            detail = finished.error_message if finished else "응답 없음"
            logger.warning("턴 실패(session=%s): %s", session_id, detail)
            error = LlmError("llm_error", "답변을 만들지 못했습니다.")
            yield _error(await _settle_after_error(app, db, runtime, session_id, error))
            return  # 보낸 문장은 끊긴 답변으로 남는다
        reply = "".join(parts).strip() or finished.text
        with anyio.CancelScope(shield=True):
            await _save_reply(
                db, assistant_id, session_id, seq + 1, reply, finished.interrupted, reply_saved
            )
            requested = runtime.pop_requested_status()
            if requested is not None:
                await _set_status(db, session_id, requested)
            await db.commit()
            await db.refresh(convo)  # 같은 시간에 종료 API가 바꿨을 수 있다
            if requested is SessionStatus.ENDED:
                await teardown(app, session_id, convo.cli_session_id)
        yield encode_sse(
            DoneEvent(
                turn_id=assistant_id,
                text=reply,
                interrupted=finished.interrupted,
                session_status=convo.status.value,
            )
        )
    except AppError as exc:
        logger.warning("턴 오류(session=%s, code=%s): %s", session_id, exc.code, exc.message)
        yield _error(await _settle_after_error(app, db, runtime, session_id, exc))
    except Exception:
        logger.exception("턴 처리 중 예외(session=%s)", session_id)
        error = AppError("internal_error", "서버 내부 오류가 발생했습니다.", 500)
        yield _error(await _settle_after_error(app, db, runtime, session_id, error))
    finally:
        runtime.current_user_turn_id = None
        # 도구가 쉬기·끝내기를 요청한 뒤 턴이 오류나 연결 끊김으로 끝났어도 요청은 반영한다
        # (정상 종료면 위에서 이미 꺼냈다). 끊김으로 취소된 중에도 끝까지 처리한다
        leftover = runtime.pop_requested_status()
        if leftover is not None:
            with anyio.CancelScope(shield=True):
                await _apply_leftover_status(app, db, session_id, leftover)


async def _save_reply(
    db: AsyncSession,
    turn_id: str,
    session_id: str,
    seq: int,
    text: str,
    interrupted: bool,
    exists: bool,
) -> None:
    """assistant 턴을 만들거나 고친다(커밋은 부르는 쪽). 문장마다 불리므로 한 줄 쿼리로 끝낸다."""
    if exists:
        statement = (
            update(Turn)
            .where(Turn.id == turn_id)
            .values(text=text, interrupted=interrupted)
            .execution_options(synchronize_session=False)
        )
    else:
        statement = insert(Turn).values(
            id=turn_id,
            session_id=session_id,
            seq=seq,
            role=TurnRole.ASSISTANT,
            text=text,
            interrupted=interrupted,
        )
    await db.execute(statement)


async def _settle_after_error(
    app: FastAPI,
    db: AsyncSession,
    runtime: ConversationRuntime,
    session_id: str,
    error: AppError,
) -> AppError:
    """턴이 오류로 끝났을 때 도구가 남긴 쉬기·끝내기 요청을 반영하고 보낼 오류를 고른다.

    끝내기 요청이었거나 그사이 다른 곳(끝내기 API·무발화 감시)이 세션을 끝냈으면 세션이 끝났음을
    알려 클라이언트가 끝난 화면으로 가게 한다(CLI가 닫혀 난 오류를 "다시 말해 주세요"로
    보내지 않게).
    """
    leftover = runtime.pop_requested_status()
    with anyio.CancelScope(shield=True):
        if leftover is not None:
            await _apply_leftover_status(app, db, session_id, leftover)
        ended = leftover is SessionStatus.ENDED or await _is_ended(db, session_id)
    if ended:
        return AppError("session_ended", "대화를 마쳤어요.", 409)
    return error


async def _is_ended(db: AsyncSession, session_id: str) -> bool:
    """세션이 끝났는지 DB에서 다시 읽는다. rollback으로 세션의 객체(convo)를 만료시키므로
    이 뒤에서 그 속성을 읽지 않는다."""
    try:
        await db.rollback()
        status = await db.scalar(
            select(ConversationSession.status).where(ConversationSession.id == session_id)
        )
        await db.commit()
    except Exception:
        logger.exception("세션 상태 확인 실패(session=%s)", session_id)
        return False
    return status is SessionStatus.ENDED


async def _apply_leftover_status(
    app: FastAPI, db: AsyncSession, session_id: str, status: SessionStatus
) -> None:
    try:
        await db.rollback()
        await _set_status(db, session_id, status)
        await db.commit()
        if status is SessionStatus.ENDED:
            convo = await db.get(ConversationSession, session_id)
            await teardown(app, session_id, convo.cli_session_id if convo else None)
        logger.info("턴이 끝나지 않았지만 상태 요청 반영(session=%s, %s)", session_id, status)
    except Exception:
        logger.exception("상태 요청 반영 실패(session=%s)", session_id)
