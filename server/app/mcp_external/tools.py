# ruff: noqa: E501  (도구 설명은 모델이 읽는 한국어 문장이라 줄 길이를 맞추지 않는다)
"""외부 MCP 도구 13개 (docs/MCP/tools.md).

일지 6: save_journal, list_journals, get_journal, search_conversations, rename_journal, delete_journal
노트 5: save_note, search_notes, list_notes, update_note, delete_note
기억·프로필 2: get_memory, set_nickname

저장·조회·수정·삭제 규칙은 app/services에 있고 이 모듈은 입력 검증, 앱 출처 제한, 삭제 확인 값,
말로 읽기 좋은 결과 서식만 맡는다. 도구마다 `guard.wrap`이 속도 제한·하루 쓰기 상한·호출 기록
(이름·시각·성공·대상 id만)을 더한다.
"""

import hashlib
from datetime import date
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import func, select

from app.api.profile import Nickname
from app.db.models import AppKind, ConversationSession, Note, NoteKind, Turn
from app.db.types import utcnow
from app.errors import AppError
from app.mcp_external.app import ToolRuntime
from app.mcp_external.render import (
    DATA_NOTICE,
    clip,
    describe_now,
    journal_line,
    note_line,
    render_journal,
)
from app.persona.loader import load_persona
from app.services import app_journal
from app.services import journal as journal_service
from app.services import nickname as nickname_service
from app.services import notes as note_service
from app.services.journal import is_app_session
from app.services.lookup import resolve_prefix, short_id
from app.services.memory import load_app_memory
from app.services.profile import get_or_create_profile

NOTE_MAX = 500
ITEM = Annotated[str, Field(min_length=1, max_length=NOTE_MAX)]
ITEM_LIST = Annotated[list[ITEM], Field(max_length=20)]
READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True)
CONFIRM_MISSING = "확인 값이 없거나 만료됐습니다. 먼저 미리보기를 다시 요청하세요."
WEB_JOURNAL = "웹에서 만든 일지는 앱에서 수정·삭제할 수 없습니다. 웹 화면에서 하세요."
SEARCH_RESULT_MAX = 4_000
HIT_CHARS = 300
NEIGHBOR_CHARS = 150


def _parse_day(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"{label}은 2026-10-25 같은 YYYY-MM-DD 형식으로 쓰세요.") from None


def _journal_state(convo: ConversationSession, notes: list[Note], turns: int) -> str:
    """삭제 확인 값에 묶는 대상의 현재 상태(바뀌면 미리보기를 다시 받아야 한다)."""
    parts = [convo.title or "", convo.summary or "", ",".join(convo.tags or []), str(turns)]
    parts += [f"{n.id}:{n.kind.value}:{n.content}:{n.starred}:{n.done}" for n in notes]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def _note_state(note: Note) -> str:
    raw = f"{note.content}:{note.starred}:{note.done}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def register_tools(mcp: MCPServer, runtime: ToolRuntime) -> None:
    guard, factory, tz, settings = (
        runtime.guard,
        runtime.session_factory,
        runtime.tz,
        runtime.settings,
    )
    assert guard.signer is not None
    signer = guard.signer

    def assistant_name(convo: ConversationSession) -> str:
        if is_app_session(convo):
            return settings.app_speaker_name
        try:
            pid = convo.persona_id or settings.default_persona
            return load_persona(settings.persona_dir, pid).persona.name
        except Exception:
            return "상대"

    # --- 일지 ------------------------------------------------------------------------------

    @mcp.tool(annotations=WRITE)
    @guard.wrap(write=True)
    async def save_journal(
        title: Annotated[str, Field(min_length=1, max_length=100)],
        summary: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None,
        ideas: ITEM_LIST | None = None,
        todos: ITEM_LIST | None = None,
        memos: ITEM_LIST | None = None,
        tags: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=30)]], Field(max_length=10)
        ]
        | None = None,
        transcript: Annotated[str, Field(max_length=20_000)] | None = None,
    ) -> str:
        """사용자가 '오늘은 여기까지'라고 하면 대화를 마치기 전에 반드시 부른다.

        오늘 대화의 일지를 저장한다. 새 일지는 summary가 필요하다(첫 줄은 결론). 같은 날 같은 제목으로
        다시 부르면 갱신한다. summary·tags·transcript는 넘긴 것만 통째로 바꾸고 생략하면 그대로 둔다.
        ideas·todos·memos는 기존 노트를 유지하고 없는 내용만 더한다(지우지 않는다).
        transcript에는 이번 대화에서 주고받은 말을 한 줄에 한 발화씩 "나: …", "Claude: …" 형식으로 넣는다.
        """
        async with factory() as db:
            result = await app_journal.save_app_journal(
                db,
                tz,
                utcnow(),
                title,
                summary=summary.strip() if summary else None,
                ideas=ideas,
                todos=todos,
                memos=memos,
                tags=tags,
                transcript=transcript,
                assistant_names=frozenset({settings.app_speaker_name}),
            )
        verb = "저장" if result.created else "갱신"
        changed = ", ".join(result.changed) or "없음"
        counts = result.counts
        return (
            f"일지 {verb} 완료(id {short_id(result.convo.id)}): 바뀐 항목 {changed}. "
            f"현재 아이디어 {counts.get(NoteKind.IDEA, 0)}개, 할 일 {counts.get(NoteKind.TODO, 0)}개, "
            f"메모 {counts.get(NoteKind.MEMO, 0)}개"
            + (f". 새 노트 {result.added_notes}건을 더했습니다" if result.added_notes else "")
        )

    @mcp.tool(annotations=READ)
    @guard.wrap()
    async def list_journals(
        keyword: Annotated[str, Field(max_length=100)] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> str:
        """저장된 일지(앱·웹 모두, 앱 메모 포함)를 최신순으로 본다.

        keyword는 제목·요약·태그·노트·대화 전문에서 찾는다(낱말 3개까지 모두 든 것). 날짜는 YYYY-MM-DD.
        """
        terms = journal_service.search_terms(keyword or "")
        start, end = _parse_day(from_date, "from_date"), _parse_day(to_date, "to_date")
        async with factory() as db:
            found = await journal_service.search_journals(
                db, tz, terms=terms, from_=start, to=end, limit=limit
            )
        if not found.rows:
            return "조건에 맞는 일지가 없습니다."
        head = f"일지 {found.total}건 중 {len(found.rows)}건(최신순). {DATA_NOTICE}"
        return "\n".join([head, *[journal_line(r.convo, r.counts, tz) for r in found.rows]])

    @mcp.tool(annotations=READ)
    @guard.wrap(target_arg="id")
    async def get_journal(
        id: str,
        format: Literal["text", "markdown"] = "text",
        include_transcript: bool = False,
    ) -> str:
        """일지 한 건: 요약, 아이디어·할 일·메모(★별표·✓완료), 태그. 전문은 요청할 때만 붙인다.

        id는 list_journals에 나온 8자다. 문서로 내보내 달라고 하면 format=markdown을 쓴다.
        """
        async with factory() as db:
            convo = await resolve_prefix(db, ConversationSession, id, "일지")
            parts = await journal_service.get_journal(db, convo.id)
        return render_journal(
            parts.convo,
            parts.notes,
            parts.turns,
            tz=tz,
            assistant_name=assistant_name(parts.convo),
            markdown=format == "markdown",
            include_transcript=include_transcript,
        )

    @mcp.tool(annotations=READ)
    @guard.wrap()
    async def search_conversations(
        keyword: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> str:
        """저장된 대화 전문에서 말을 찾는다(최신순 최대 8건, 앞뒤 말과 함께).

        조사를 뺀 핵심 낱말 1~2개로 찾는다. 못 찾으면 다른 낱말로 한 번 더 찾고, 그래도 없으면
        지어내지 말고 없다고 말한다.
        """
        terms = journal_service.search_terms(keyword)
        if not terms:
            raise ToolError("검색어가 비어 있습니다.")
        async with factory() as db:
            found = await journal_service.search_conversations(db, terms)
            if not found.hits:
                return f"'{keyword.strip()}'에 해당하는 대화가 없습니다."
            names = {}
            for hit in found.hits:
                convo = await db.get(ConversationSession, hit.turn.session_id)
                names[hit.turn.session_id] = assistant_name(convo) if convo else "상대"
        parts = [f"지난 대화 기록에서 찾은 말이다(최신순, >가 찾은 말). {DATA_NOTICE}"]
        size = len(parts[0])

        def line(turn: Turn, limit: int) -> str:
            who = "사용자" if turn.role.value == "user" else names[turn.session_id]
            return f"{who}: {clip(turn.text, limit)}"

        for hit in found.hits:
            turn = hit.turn
            label = f"'{' '.join(hit.title.split())}'" if hit.title else "제목 없는 대화"
            entry = [f"[{hit.started_at.astimezone(tz):%Y-%m-%d} {label}]"]
            before = found.neighbors.get((turn.session_id, turn.seq - 1))
            after = found.neighbors.get((turn.session_id, turn.seq + 1))
            if before is not None:
                entry.append(f"  {line(before, NEIGHBOR_CHARS)}")
            entry.append(f"> {line(turn, HIT_CHARS)}")
            if after is not None:
                entry.append(f"  {line(after, NEIGHBOR_CHARS)}")
            text = "\n".join(entry)
            if size + 1 + len(text) > SEARCH_RESULT_MAX:
                break
            parts.append(text)
            size += 1 + len(text)
        return "\n".join(parts)

    def _require_app_journal(convo: ConversationSession) -> None:
        if not is_app_session(convo):
            raise ToolError(WEB_JOURNAL)

    @mcp.tool(annotations=WRITE)
    @guard.wrap(write=True, target_arg="id")
    async def rename_journal(
        id: str, title: Annotated[str, Field(min_length=1, max_length=100)]
    ) -> str:
        """앱에서 저장한 일지의 제목을 바꾼다. 사용자가 분명히 요청했을 때만 부른다.

        같은 날 같은 제목의 앱 일지가 있으면 거부된다. 웹에서 만든 일지와 앱 메모는 바꿀 수 없다.
        """
        async with factory() as db:
            convo = await resolve_prefix(db, ConversationSession, id, "일지")
            _require_app_journal(convo)
            if convo.app_kind is AppKind.MEMO:
                raise ToolError("앱 메모는 제목을 바꿀 수 없습니다.")
            clean = " ".join(title.split())
            try:
                await journal_service.rename_journal(db, convo.id, clean, tz)
            except AppError as exc:
                raise ToolError(exc.message) from None
        return f"제목을 '{clean}'(으)로 바꿨습니다(id {short_id(convo.id)})."

    @mcp.tool(annotations=DELETE)
    @guard.wrap(write=True, target_arg="id")
    async def delete_journal(id: str, confirm_token: str | None = None) -> str:
        """앱에서 저장한 일지를 지운다. 되돌릴 수 없고 그 일지의 노트·전문도 함께 지워진다.

        2단계다. confirm_token 없이 부르면 지우지 않고 대상 요약과 확인 값을 돌려준다. 그러면 사용자에게
        지울지 물어보고, 분명한 동의가 있을 때만 그 확인 값을 넘겨 다시 부른다. 사용자의 요청 없이는
        부르지 않는다. 웹에서 만든 일지는 지울 수 없다.
        """
        async with factory() as db:
            convo = await resolve_prefix(db, ConversationSession, id, "일지")
            _require_app_journal(convo)
            notes = list((await db.scalars(select(Note).where(Note.session_id == convo.id))).all())
            turn_count = await db.scalar(
                select(func.count()).select_from(Turn).where(Turn.session_id == convo.id)
            )
            target = f"{convo.id}:{_journal_state(convo, notes, turn_count or 0)}"
            if confirm_token is None or not signer.valid(confirm_token, "delete_journal", target):
                if confirm_token is not None:
                    raise ToolError(CONFIRM_MISSING)
                token = signer.issue("delete_journal", target)
                day = f"{convo.started_at.astimezone(tz):%Y-%m-%d}"
                kind = "앱 메모" if convo.app_kind is AppKind.MEMO else "일지"
                return (
                    f"{kind} '{convo.title}'({day}, id {short_id(convo.id)})을(를) 지우면 "
                    f"노트 {len(notes)}개와 대화 전문도 함께 사라지고 되돌릴 수 없습니다. "
                    f"사용자에게 지울지 묻고, 분명히 동의하면 confirm_token으로 다시 부르세요. "
                    f"(확인 값: {token})"
                )
            title = convo.title
            await journal_service.delete_app_journal(db, convo)
        return f"일지 '{title}'을(를) 지웠습니다(노트 {len(notes)}개 포함)."

    # --- 노트 ------------------------------------------------------------------------------

    @mcp.tool(annotations=WRITE)
    @guard.wrap(write=True)
    async def save_note(
        kind: Literal["idea", "todo", "memo"],
        content: Annotated[str, Field(min_length=1, max_length=NOTE_MAX)],
    ) -> str:
        """아이디어(idea)·할 일(todo)·메모(memo)를 저장한다.

        사용자가 저장을 요청했거나 기억해 둘 만한 내용을 직접 말했을 때 쓴다. 일지 없이 저장하면
        그날의 앱 메모에 모인다.
        """
        text = content.strip()
        if not text:
            raise ToolError("저장할 내용이 비어 있습니다.")
        async with factory() as db:
            note, _ = await app_journal.save_app_note(db, tz, utcnow(), NoteKind(kind), text)
        return f"저장 완료({kind}, id {short_id(note.id)}): {text}"

    @mcp.tool(annotations=READ)
    @guard.wrap()
    async def search_notes(
        keyword: Annotated[str, Field(min_length=1, max_length=100)],
        days: Annotated[int, Field(ge=1, le=365)] = 30,
    ) -> str:
        """저장한 노트를 찾는다(최근 days일, 최대 10건, 낱말 3개까지 모두 든 노트)."""
        terms = journal_service.search_terms(keyword)
        if not terms:
            raise ToolError("검색어가 비어 있습니다.")
        since = note_service.since_days(utcnow(), days)
        async with factory() as db:
            rows = await note_service.search_notes(db, terms, since)
            sessions = {n.session_id: await db.get(ConversationSession, n.session_id) for n in rows}
        if not rows:
            return f"'{keyword.strip()}'에 해당하는 노트가 없습니다."
        lines = [note_line(n, sessions[n.session_id], tz) for n in rows]
        return "\n".join([f"저장한 노트 목록이다. {DATA_NOTICE}", *lines])

    @mcp.tool(annotations=READ)
    @guard.wrap()
    async def list_notes(
        kind: Literal["idea", "todo", "memo"] | None = None,
        status: Literal["open", "done", "all"] = "open",
        starred: bool | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> str:
        """노트 목록(별표가 먼저, 그다음 최신순). 각 줄에 출처(앱/웹)를 밝힌다.

        "저장된 아이디어 보여 줘"는 kind=idea로 부른다. 결과를 말로 읽을 때 개수가 많으면 요약한다.
        """
        query = select(Note, ConversationSession).join(
            ConversationSession, Note.session_id == ConversationSession.id
        )
        if kind:
            query = query.where(Note.kind == NoteKind(kind))
        if status != "all":
            query = query.where(Note.done.is_(status == "done"))
        if starred is not None:
            query = query.where(Note.starred.is_(starred))
        async with factory() as db:
            rows = (
                await db.execute(
                    query.order_by(Note.starred.desc(), Note.created_at.desc(), Note.id).limit(
                        limit
                    )
                )
            ).all()
        if not rows:
            return "조건에 맞는 노트가 없습니다."
        lines = [note_line(note, convo, tz) for note, convo in rows]
        return "\n".join([f"노트 {len(rows)}건(최대 {limit}건). {DATA_NOTICE}", *lines])

    @mcp.tool(annotations=WRITE)
    @guard.wrap(write=True, target_arg="id")
    async def update_note(
        id: str,
        content: Annotated[str, Field(min_length=1, max_length=NOTE_MAX)] | None = None,
        starred: bool | None = None,
        done: bool | None = None,
    ) -> str:
        """노트의 내용·별표·완료를 바꾼다(넘긴 항목만). 웹에서 만든 노트도 고칠 수 있다.

        사용자가 분명히 요청했을 때만 부른다. id는 list_notes에 나온 8자다. 아이디어를 done으로
        닫으면 다음 대화의 기억에서 빠진다.
        """
        changes: dict = {}
        if content is not None:
            text = content.strip()
            if not text:
                raise ToolError("내용이 비어 있습니다.")
            changes["content"] = text
        if starred is not None:
            changes["starred"] = starred
        if done is not None:
            changes["done"] = done
        if not changes:
            raise ToolError("바꿀 항목(content, starred, done)을 하나 이상 넘기세요.")
        async with factory() as db:
            note = await resolve_prefix(db, Note, id, "노트")
            note = await note_service.update_note(db, note.id, changes)
        return f"노트를 고쳤습니다: {note_line(note)}"

    @mcp.tool(annotations=DELETE)
    @guard.wrap(write=True, target_arg="id")
    async def delete_note(id: str, confirm_token: str | None = None) -> str:
        """노트를 지운다. 웹에서 만든 노트도 지울 수 있고 되돌릴 수 없다.

        2단계다. confirm_token 없이 부르면 지우지 않고 대상과 확인 값을 돌려준다. 사용자에게 지울지
        묻고 분명히 동의할 때만 그 확인 값을 넘겨 다시 부른다. 사용자의 요청 없이는 부르지 않는다.
        """
        async with factory() as db:
            note = await resolve_prefix(db, Note, id, "노트")
            target = f"{note.id}:{_note_state(note)}"
            if confirm_token is None:
                token = signer.issue("delete_note", target)
                return (
                    f"노트 [{note.kind.value}] '{clip(note.content, 80)}'(id {short_id(note.id)})을(를) "
                    f"지우면 되돌릴 수 없습니다. 사용자에게 지울지 묻고, 분명히 동의하면 "
                    f"confirm_token으로 다시 부르세요. (확인 값: {token})"
                )
            if not signer.valid(confirm_token, "delete_note", target):
                raise ToolError(CONFIRM_MISSING)
            gone = await note_service.delete_note(db, note.id)
        return f"노트를 지웠습니다: {clip(gone.content, 80)}"

    # --- 기억·프로필 --------------------------------------------------------------------------

    @mcp.tool(annotations=READ)
    @guard.wrap()
    async def get_memory() -> str:
        """대화를 시작할 때 맨 먼저 부른다.

        지금 시각, 호칭, 최근 일지(제목·요약), 아직 닫지 않은 아이디어와 할 일(최근 5개까지)을 돌려준다.
        시각은 돌려준 값을 그대로 쓰고 아침·저녁을 추측하지 않는다.
        """
        now = utcnow()
        async with factory() as db:
            profile = await get_or_create_profile(db)
            memory = await load_app_memory(db, settings, profile, now)
            name = profile.nickname
        lines = [describe_now(now, tz)]
        lines.append(f"호칭: {name}" if name else "호칭: 아직 정하지 않음")
        lines.append(DATA_NOTICE)
        if memory.recent_summaries:
            lines.append("최근 일지:")
            lines += [f"- {s}" for s in memory.recent_summaries]
        else:
            lines.append("최근 7일 일지가 없습니다. 첫 대화처럼 시작하세요.")
        if memory.open_ideas:
            lines.append("열린 아이디어:")
            lines += [f"- {s}" for s in memory.open_ideas]
        if memory.open_todos:
            lines.append("열린 할 일(최근 순):")
            lines += [f"- {s}" for s in memory.open_todos]
            lines.append("더 보려면 list_notes(kind=todo)를 쓴다.")
        return "\n".join(lines)

    @mcp.tool(annotations=WRITE)
    @guard.wrap(write=True)
    async def set_nickname(nickname: Nickname) -> str:
        """사용자가 앞으로 자기를 다르게 불러 달라고 분명히 말했을 때만 부른다.

        프로필에 저장하며 웹 글 대화와 같은 호칭을 쓴다. 다음 대화의 get_memory부터 반영되고, 이 대화
        안에서는 결과 문구대로 이어 간다.
        """
        async with factory() as db:
            await nickname_service.set_nickname(db, nickname)
        return (
            f"호칭을 '{nickname}'(으)로 바꿨습니다. 다음 대화부터 반영되며, 이 대화에서는 지금부터 "
            "그렇게 부르세요."
        )
