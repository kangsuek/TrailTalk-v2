"""일지 정리(추출, Spec 5.5): 끝난 대화의 전문을 일지(제목·결론·알게 된 것·확인할 것·노트·태그)로
정리한다.

대화가 끝나면(끝내기 API, end_session 도구, 무발화 종료) ensure_extraction이 대화당 하나의
백그라운드 작업을 띄운다. 가벼운 모델을 CLI 단발 호출로 부르고(app/llm/claude_cli.run_oneshot),
결과를 Pydantic 스키마로 다시 검증한다. 실패하면 한 번 다시 시도하고, 그래도 실패하면 failed로
둔다. 실패해도 대화와 전문은 남고 retry로 다시 돌릴 수 있다.
아이디어·할 일·메모는 그 대화의 기존 노트와 겹치는 것(app/jobs/dedupe.py)을 거른 뒤 새것만 더한다.
다시 연 대화를 다시 끝내면 요약·태그·확인할 것은 전문 전체로 새로 쓰고, 기존 노트(별표·완료·고친
내용)는 두며, 사용자가 고친 제목은 바꾸지 않는다. 전문에는 앞서 정리에 성공한 마지막 턴
(extracted_until_seq) 뒤에 표시를 넣어 노트는 그 뒤에서만 뽑게 한다(사용자가 고친 노트는 글이 달라
문자열로는 겹침을 알 수 없으므로, 앞부분에서 같은 항목이 원래 글로 다시 뽑히지 않게). 정리한 적이
없는 대화는 표시하지 않는다(앞부분 노트가 빠지지 않게).
상태(conversation_session.extract_status, API journal_status)는 pending → done/failed다.

검색 출처 인용(sources·citations)은 검색 도구가 생기는 M5부터 채워진다. 그 전에는 turn.sources가
비어 있어 출처 번호를 모두 버린다(인용 없음).
"""

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import func, select

from app.db.models import (
    ConversationSession,
    ExtractStatus,
    Note,
    NoteKind,
    SessionMode,
    SessionStatus,
    Turn,
    TurnRole,
)
from app.jobs.dedupe import matches_saved, new_items
from app.llm.backend import LlmError
from app.llm.claude_cli import run_oneshot
from app.persona.loader import load_session_persona
from app.persona.rules import EXTRACT_INSTRUCTION, EXTRACT_SAVED_SECTION, EXTRACT_SOURCES_SECTION

logger = logging.getLogger("trailtalk.extract")

ATTEMPTS = 2  # 첫 시도 + 재시도 1회
TRANSCRIPT_LIMIT = 100_000  # 이보다 긴 전문은 앞부분을 잘라 뒷부분을 남긴다
MAX_SOURCES = 30  # 정리에 알려 주는 출처 수(대화 순서, URL 중복 없이)
_RERUNS = 5  # 정리하는 사이 새 요청·턴이 들어오면 다시 도는 최대 횟수
MAX_CONCURRENT = 2  # 동시에 도는 정리 CLI 수(앱 시작 때 여러 대화가 한꺼번에 몰려도)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
SourceIds = Annotated[list[Annotated[int, Field(ge=1, le=MAX_SOURCES)]], Field(max_length=10)]


class CitedLine(BaseModel):
    """요약 줄·메모 한 항목과 근거 출처 번호(<출처> 목록의 번호). 번호는 서버가 검증한다."""

    model_config = ConfigDict(extra="forbid")

    text: Line
    sources: SourceIds


class Extraction(BaseModel):
    """정리 결과 스키마. CLI --json-schema에도 이 스키마를 넘긴다."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    # 일지: 결론 1줄 → 알게 된 것 → 확인할 것(Spec 5.4). 사실 하나는 한 곳에만
    conclusion: CitedLine
    findings: Annotated[list[CitedLine], Field(max_length=5)]
    checks: Annotated[list[Line], Field(max_length=5)]
    ideas: Annotated[list[Line], Field(max_length=10)]
    todos: Annotated[list[Line], Field(max_length=10)]
    memos: Annotated[list[CitedLine], Field(max_length=10)]
    tags: Annotated[list[Tag], Field(max_length=5)]


def _one_line(text: str) -> str:
    return " ".join(text.split())


# 모델이 문장 끝에 직접 적은 출처 번호(번호는 sources로만 받는다). 문장 중간의 "[2024]"는 둔다
_CITE_MARK = re.compile(r"(?:\s*\[\d{1,2}\])+(?=[.!?。]?\s*$)")


def cited_text(text: str) -> str:
    """한 줄로 정리하고 문장 끝 출처 번호를 뗀다(다 지워지면 원문)."""
    one = _one_line(text)
    return _CITE_MARK.sub("", one).strip() or one


def _clean_tags(tags: Sequence[str]) -> list[str]:
    """화면이 앞에 #을 붙이므로 모델이 붙인 #은 뗀다. 빈 값·중복은 뺀다(순서 유지)."""
    cleaned = (_one_line(tag.lstrip("#＃ \t")) for tag in tags)
    return list(dict.fromkeys(tag for tag in cleaned if tag))


# 전문에서 앞서 정리한 부분과 그 뒤를 나누는 표시(EXTRACT_INSTRUCTION 규칙이 같은 글을 쓴다)
RESUMED_MARK = "(— 여기서부터 다시 열어 이어 간 대화 —)"
_CLOSE_TAG = re.compile(r"<\s*/\s*(대화|저장한 노트|출처)\s*>")


def _escape_tags(text: str) -> str:
    """글 안에서 프롬프트의 구분 태그(<대화>, <저장한 노트>, <출처>)를 닫지 못하게 하고(공백을 넣은
    변형 포함), 다시 연 지점 표시를 흉내 내지 못하게 한다."""
    text = _CLOSE_TAG.sub(lambda m: f"[/{m.group(1)}]", text)
    return text.replace(RESUMED_MARK, RESUMED_MARK.strip("()"))


def build_transcript(
    turns: Sequence[Turn], assistant: str, extracted_until: int | None = None
) -> str:
    """extracted_until: 앞서 정리에 성공한 마지막 턴 seq. 그 뒤 첫 턴 앞에(없으면 맨 끝에)
    RESUMED_MARK를 넣는다(새 노트는 그 뒤에서만 뽑는다). None이면 표시하지 않는다."""
    lines = []
    marked = extracted_until is None
    for t in turns:
        if not marked and t.seq > extracted_until:
            lines.append(RESUMED_MARK)
            marked = True
        speaker = "사용자" if t.role is TurnRole.USER else assistant
        mark = " (말이 끊김)" if t.interrupted else ""
        lines.append(f"{speaker}: {_escape_tags(_one_line(t.text))}{mark}")
    if not marked:
        lines.append(RESUMED_MARK)  # 정리한 뒤로 새 말이 없다(새 노트 없음)
    kept: list[str] = []
    size = 0
    for line in reversed(lines):  # 너무 길면 뒷부분(최근 대화)을 줄 단위로 남긴다
        size += len(line) + 1
        if size > TRANSCRIPT_LIMIT:
            kept.append("(앞부분 생략)")
            break
        kept.append(line)
    return "\n".join(reversed(kept))


def collect_sources(turns: Sequence[Turn]) -> list[dict]:
    """대화에서 캐릭터가 본 출처를 대화 순서대로 모은다(URL 중복 없이, 최대 MAX_SOURCES개)."""
    found: dict[str, dict] = {}
    for turn in turns:
        for source in turn.sources or []:
            url = source.get("url") if isinstance(source, dict) else None
            if not isinstance(url, str) or url in found:
                continue
            if len(found) >= MAX_SOURCES:
                return list(found.values())
            title = source.get("title")
            found[url] = {"title": title if isinstance(title, str) else None, "url": url}
    return list(found.values())


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return host.removeprefix("www.") or url


class Cited(BaseModel):
    """검증한 인용: 요약 줄·메모(글과 근거 출처 URL)와 출처 제목(URL → 제목).

    번호가 아니라 URL로 저장한다. 번호는 조회할 때 실제로 남은 요약·메모 기준으로 매긴다
    (다시 정리·중복으로 걸러진 메모 때문에 번호가 어긋나거나 고아 인용이 생기지 않게).
    """

    summary: list[tuple[str, list[str]]]
    memos: list[tuple[str, list[str]]]
    titles: dict[str, str]


def build_citations(result: Extraction, sources: Sequence[dict]) -> Cited:
    """출처 번호를 <출처> 목록에 있는 것만 남기고 URL로 바꾼다(모델이 URL을 지어내지 못하게)."""
    titles: dict[str, str] = {}

    def urls(ids: Sequence[int]) -> list[str]:
        out: list[str] = []
        for i in ids:
            if not 1 <= i <= len(sources):
                continue  # 목록에 없는 번호는 버린다
            src = sources[i - 1]
            titles.setdefault(src["url"], _one_line(src.get("title") or "") or _host(src["url"]))
            if src["url"] not in out:
                out.append(src["url"])
        return out

    def lines(items: Sequence[CitedLine]) -> list[tuple[str, list[str]]]:
        return [(cited_text(item.text), urls(item.sources)) for item in items]

    # 요약 줄 = 결론(첫 줄) + 알게 된 것
    summary = lines([result.conclusion, *result.findings])
    return Cited(summary=summary, memos=lines(result.memos), titles=titles)


def merge_titles(stored: list | None, new: dict[str, str]) -> list[dict]:
    """출처 제목을 합친다(URL → 제목). 다시 정리해도 앞 회차 메모가 가리키는 출처는 남긴다."""
    titles = {c["url"]: c["title"] for c in stored or [] if isinstance(c, dict)}
    for url, title in new.items():
        titles.setdefault(url, title)
    return [{"title": t, "url": u} for u, t in titles.items()]


def number_citations(
    summary_urls: Sequence[Sequence[str]], memo_urls: Sequence[Sequence[str]], titles: dict
) -> tuple[list[list[int]], list[list[int]], list[dict]]:
    """남아 있는 요약 줄 → 메모 순서로 처음 인용된 차례대로 1부터 번호를 매긴다(일지 상세 API).
    실제로 쓰인 출처만 인용 목록에 들어간다. (요약 줄 번호, 메모 번호, [{n, title, url}])"""
    numbers: dict[str, int] = {}
    citations: list[dict] = []

    def ids(urls: Sequence[str]) -> list[int]:
        out: list[int] = []
        for url in urls:
            if not isinstance(url, str):
                continue
            if url not in numbers:
                numbers[url] = len(numbers) + 1
                citations.append(
                    {"n": numbers[url], "title": titles.get(url) or _host(url), "url": url}
                )
            if numbers[url] not in out:
                out.append(numbers[url])
        return out

    summary = [ids(urls) for urls in summary_urls]
    memos = [ids(urls) for urls in memo_urls]
    return summary, memos, citations


SAVED_LABELS = {NoteKind.IDEA: "아이디어", NoteKind.TODO: "할 일", NoteKind.MEMO: "메모"}


def build_prompt(
    turns: Sequence[Turn],
    assistant: str,
    saved: Sequence[tuple[NoteKind, str]] = (),
    sources: Sequence[dict] = (),
    extracted_until: int | None = None,
) -> str:
    """saved: 이 대화에 이미 저장된 노트(종류, 내용). 같은 항목을 다시 뽑지 않게 알려 준다. 종류를
    붙여 다른 종류의 항목까지 빼지 않게 한다. 노트는 모델이 만든 글이라(웹 내용이 섞일 수 있다)
    태그로 감싸 지시로 따르지 않게 한다."""
    lines = [
        f"- [{SAVED_LABELS[NoteKind(kind)]}] {_escape_tags(_one_line(content))}"
        for kind, content in saved
        if content.strip()
    ]
    saved_section = EXTRACT_SAVED_SECTION.format(items="\n".join(lines)) if lines else ""
    source_lines = []
    for n, src in enumerate(sources, start=1):
        title = _escape_tags(_one_line(src.get("title") or "(제목 없음)"))
        source_lines.append(f"[{n}] {title} — {_escape_tags(src['url'])}")
    source_section = (
        EXTRACT_SOURCES_SECTION.format(items="\n".join(source_lines)) if source_lines else ""
    )
    return EXTRACT_INSTRUCTION.format(
        assistant=assistant,
        sources=source_section,
        saved=saved_section,
        transcript=build_transcript(turns, assistant, extracted_until),
    )


def assistant_name(app: FastAPI, persona_id: str | None) -> str:
    """전문의 화자 이름은 그 대화가 시작한 페르소나를 따른다(파일이 사라졌으면 기본 페르소나)."""
    settings = app.state.settings
    loaded = load_session_persona(settings.persona_dir, persona_id, settings.default_persona)
    return loaded.persona.name


async def _call(app: FastAPI, prompt: str) -> Extraction:
    settings = app.state.settings
    async with app.state.extract_slots:
        raw = await _run(settings, prompt)
    return Extraction.model_validate(raw)


async def _run(settings, prompt: str) -> dict:
    return await run_oneshot(
        settings,
        prompt,
        model=settings.llm_extract_model,
        json_schema=Extraction.model_json_schema(),
        timeout_s=settings.extract_timeout_s,
    )


def init_state(app: FastAPI) -> None:
    """정리 작업 상태를 app.state에 둔다(create_app에서 부른다)."""
    app.state.extractions = {}  # 대화 ID → 돌고 있는 정리 작업
    app.state.extract_writes = set()  # 취소에서 보호한 결과 쓰기
    app.state.extract_closed = False  # 앱이 끝나는 중이면 새 정리를 띄우지 않는다
    app.state.reformat_requests = set()  # 예전 형식 일지를 다시 정리해 달라는 요청(retry)
    app.state.extract_slots = asyncio.Semaphore(MAX_CONCURRENT)


async def _shielded(app: FastAPI, coro) -> None:
    """DB 쓰기를 취소에서 보호한다. 정리 작업은 asyncio 태스크라 앱 종료 때 asyncio 취소를 받는데,
    anyio CancelScope(shield)는 이를 막지 못한다. 그래서 쓰기를 별도 태스크로 돌려 끝까지 마치게
    하고, cancel_all이 남은 쓰기를 기다린다(커밋 도중 끊겨 죽은 커넥션이 풀에 남지 않게)."""
    writes: set[asyncio.Task] = app.state.extract_writes
    task = asyncio.create_task(coro)
    writes.add(task)
    task.add_done_callback(writes.discard)
    await asyncio.shield(task)


async def _set_status(app: FastAPI, session_id: str, status: ExtractStatus) -> None:
    async def write() -> None:
        async with app.state.session_factory() as db:
            convo = await db.get(ConversationSession, session_id)
            if convo is not None:
                convo.extract_status = status
                await db.commit()

    await _shielded(app, write())


async def run_extraction(app: FastAPI, session_id: str) -> Extraction | None:
    """대화 하나를 정리한다. 이미 done/failed이거나 끝나지 않은 대화면 아무것도 하지 않는다.
    결과(실패·건너뜀이면 None)."""
    async with app.state.session_factory() as db:
        convo = await db.get(ConversationSession, session_id)
        if convo is None or convo.extract_status in (ExtractStatus.DONE, ExtractStatus.FAILED):
            return None
        if convo.mode is SessionMode.CLAUDE_APP:
            return None  # 앱 일지·앱 메모는 앱이 정리한 것을 저장한 것이라 다시 정리하지 않는다
        if convo.status is not SessionStatus.ENDED:
            return None  # 다시 연 대화는 다시 끝낼 때 정리한다
        convo.extract_status = ExtractStatus.PENDING
        rows = await db.execute(
            select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq)
        )
        turns = list(rows.scalars())
        notes = await db.execute(
            select(Note.kind, Note.content)
            .where(Note.session_id == session_id)
            .order_by(Note.created_at)
        )
        saved = [(kind, content) for kind, content in notes]
        assistant = assistant_name(app, convo.persona_id)
        extracted_until = convo.extracted_until_seq
        # 예전 형식 일지를 새 형식으로 '다시 정리'해 달라는 요청이면 노트는 이미 뽑았으므로
        # 다시 넣지 않는다(고친 노트가 되살아나거나 중복이 생기지 않게). 요청으로 시작한 이번만
        # 해당한다(늦게 온 턴 때문에 다시 도는 정리는 새 말의 노트를 뽑아야 한다). 앞서 정리한 뒤로
        # 이어 간 말이 있으면(다시 열어 이어 간 뒤 정리가 실패한 일지) 그 말의 노트를 뽑아야 하므로
        # 다시 정리로 보지 않는다
        requests: set[str] = app.state.reformat_requests
        # 정리 경계가 생기기 전에 정리한 일지(extracted_until NULL)는 다시 연 적이 있으면 이어 간
        # 말이 있는 것으로 본다(다시 열면 재개 인사말 턴이 생긴다)
        if extracted_until is None:
            said_after = convo.reopened_at is not None
        else:
            said_after = any(t.seq > extracted_until for t in turns)
        reformat = (
            session_id in requests
            and convo.checks is None
            and bool(convo.summary)
            and not said_after
        )
        requests.discard(session_id)
        await db.commit()
    if not any(t.role is TurnRole.USER for t in turns):
        # 인사만 하고 끝난 대화는 정리할 것이 없다(사용량을 쓰지 않는다)
        await _set_status(app, session_id, ExtractStatus.DONE)
        return None

    sources = collect_sources(turns)
    prompt = build_prompt(turns, assistant, saved, sources, extracted_until)
    result: Extraction | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            result = await _call(app, prompt)
            break
        except (LlmError, ValidationError) as exc:
            # 대화에서 나온 내용(모델 출력)은 로그에 남기지 않는다
            reason = (
                f"스키마 오류 {exc.error_count()}건"
                if isinstance(exc, ValidationError)
                else exc.code
            )
            logger.warning(
                "일지 정리 실패(session=%s, %d/%d): %s", session_id, attempt, ATTEMPTS, reason
            )
    if result is None:
        await _set_status(app, session_id, ExtractStatus.FAILED)
        return None
    cited = build_citations(result, sources)

    async def save() -> None:
        async with app.state.session_factory() as db:
            convo = await db.get(ConversationSession, session_id)
            if convo is None or convo.status is not SessionStatus.ENDED:
                return  # 정리하는 사이 지워졌거나 다시 열렸다(다시 끝낼 때 새로 정리한다)
            if not convo.title_edited:  # 사용자가 고친 제목은 두고 간다
                convo.title = _one_line(result.title)
            # 요약은 줄 목록으로 저장하므로 항목 안의 줄바꿈은 한 칸으로 줄인다
            convo.summary = "\n".join(text for text, _ in cited.summary if text)
            summary_urls = [urls for text, urls in cited.summary if text]
            convo.summary_cites = summary_urls if any(summary_urls) else None
            convo.citations = merge_titles(convo.citations, cited.titles) or None
            convo.checks = [line for line in map(_one_line, result.checks) if line]
            convo.tags = _clean_tags(result.tags)
            # 이 대화의 기존 노트(대화 중 저장한 것, 다시 열기 전에 정리한 것)와 겹치지 않는
            # 항목만 더한다. 같은 종류의 노트와는 괄호 설명을 뺀 글로도 비교한다(matches_saved)
            rows = await db.execute(
                select(Note.kind, Note.content).where(Note.session_id == session_id)
            )
            saved_notes = [(kind, content) for kind, content in rows]
            memo_cites: dict[str, list[str]] = {}
            for text, urls in cited.memos:
                memo_cites.setdefault(text, urls)  # 같은 글이 또 오면 남는 쪽(앞)의 출처를 쓴다
            existing = [content for _, content in saved_notes]
            for kind, items in (
                (NoteKind.IDEA, [] if reformat else result.ideas),
                (NoteKind.TODO, [] if reformat else result.todos),
                (NoteKind.MEMO, [] if reformat else [text for text, _ in cited.memos]),
            ):
                same_kind = [content for k, content in saved_notes if k is kind]
                fresh = [i for i in items if not any(matches_saved(s, i) for s in same_kind)]
                for content in new_items(existing, fresh):
                    urls = memo_cites.get(content) if kind is NoteKind.MEMO else None
                    db.add(
                        Note(session_id=session_id, kind=kind, content=content, cites=urls or None)
                    )
                    existing.append(content)
            # 정리하는 사이 새 턴(M4 오프라인 큐의 기록 등)이 들어왔으면 끝내지 않고 한 번 더
            # 돈다(_guarded가 pending을 보고 다시 부른다)
            now_turns = await db.scalar(
                select(func.count()).select_from(Turn).where(Turn.session_id == session_id)
            )
            done = now_turns == len(turns)
            convo.extract_status = ExtractStatus.DONE if done else ExtractStatus.PENDING
            if turns:
                convo.extracted_until_seq = turns[-1].seq
            await db.commit()

    await _shielded(app, save())
    logger.info("일지 정리 완료(session=%s)", session_id)
    return result


async def _status(app: FastAPI, session_id: str) -> ExtractStatus | None:
    """끝난 대화의 정리 상태. 끝나지 않은 대화는 None(정리할 차례가 아니다)."""
    async with app.state.session_factory() as db:
        row = (
            await db.execute(
                select(ConversationSession.status, ConversationSession.extract_status).where(
                    ConversationSession.id == session_id
                )
            )
        ).first()
    if row is None or row.status is not SessionStatus.ENDED:
        return None
    return row.extract_status


async def _guarded(app: FastAPI, session_id: str) -> Extraction | None:
    try:
        result = await run_extraction(app, session_id)
        # 이 작업이 도는 사이에 다시 정리 요청(retry)이나 새 턴이 pending으로 바꿨으면 다시 돈다(그
        # 요청의 ensure_extraction은 돌던 이 작업을 받아 새로 띄우지 않았다). 상한을 둔다(남으면
        # 다음 요청이나 앱 시작 때 정리)
        for _ in range(_RERUNS):
            if await _status(app, session_id) is not ExtractStatus.PENDING:
                break
            result = await run_extraction(app, session_id)
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("일지 정리 작업 예외(session=%s)", session_id)
        await _set_status(app, session_id, ExtractStatus.FAILED)
        return None


def ensure_extraction(app: FastAPI, session_id: str) -> asyncio.Task | None:
    """대화의 정리 작업을 띄운다. 이미 돌고 있으면 그 작업을 돌려준다(대화당 하나).

    앱이 끝나는 중이면 띄우지 않는다(pending으로 남아 다음 시작 때 정리된다).
    """
    if app.state.extract_closed:
        return None
    tasks: dict[str, asyncio.Task] = app.state.extractions
    task = tasks.get(session_id)
    if task is None or task.done():  # 끝난(잊기 직전의) 작업은 새 요청을 받을 수 없다
        task = asyncio.create_task(_guarded(app, session_id), name=f"extract-{session_id}")
        tasks[session_id] = task

        def forget(done: asyncio.Task) -> None:
            if tasks.get(session_id) is done:
                tasks.pop(session_id)

        task.add_done_callback(forget)
    return task


async def wait_extraction(app: FastAPI, session_id: str, timeout_s: float) -> None:
    """진행 중인 정리가 끝나길 최대 timeout_s 기다린다. 시간이 지나도 정리는 멈추지 않는다."""
    task = app.state.extractions.get(session_id)
    if task is None:
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout_s)
    except TimeoutError:
        logger.info("일지 정리가 아직 끝나지 않아 먼저 응답(session=%s)", session_id)
    except asyncio.CancelledError:
        # 지우기·다시 열기가 정리를 멈췄다. 기다리던 쪽(끝내기 응답)까지 깨뜨리지 않는다
        if not task.cancelled():
            raise  # 기다리던 쪽 자신이 취소됐다
    except Exception:  # 정리 실패가 끝내기 응답까지 실패로 만들지 않는다(대화는 이미 끝났다)
        logger.exception("일지 정리 대기 중 예외(session=%s)", session_id)


async def cancel_extraction(app: FastAPI, session_id: str, timeout_s: float) -> None:
    """돌고 있는 정리를 멈추고(CLI는 kill), 이미 시작한 결과 쓰기가 끝나길 최대 timeout_s 기다린다.

    쓰기는 취소에서 보호된 별도 태스크(_shielded)라 정리 태스크를 취소해도 끝까지 돈다. 대화를
    지우기 전에 불러 지운 뒤에 쓰기가 커밋되지 않게 한다. 부른 쪽의 취소는 그대로 전파된다.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    task = app.state.extractions.get(session_id)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=timeout_s)
    writes = set(app.state.extract_writes)
    remaining = deadline - loop.time()
    if writes and remaining > 0:
        await asyncio.wait(writes, timeout=remaining)


async def resume_pending(app: FastAPI) -> list[str]:
    """앱 시작 때 정리 도중에 서버가 꺼진(pending으로 남은) 끝난 대화를 다시 정리한다. 띄운 대화
    ID 목록. 정리 기록이 없는(null) 대화는 정리가 생기기 전에 끝난 것이라 자동으로 돌리지 않는다
    (한꺼번에 사용량이 나가지 않게, 사용자가 retry로 고른다. client-contract 3.2)."""
    async with app.state.session_factory() as db:
        rows = await db.execute(
            select(ConversationSession.id).where(
                ConversationSession.status == SessionStatus.ENDED,
                ConversationSession.extract_status == ExtractStatus.PENDING,
            )
        )
        ids = list(rows.scalars())
    for session_id in ids:
        ensure_extraction(app, session_id)
    return ids


async def cancel_all(app: FastAPI) -> None:
    """앱 종료 때 남은 정리를 멈추고 새 정리를 받지 않는다. 진행 중인 DB 쓰기는 끝까지 기다린다.

    pending으로 남은 대화는 다음 시작 때 다시 정리한다(resume_pending).
    """
    app.state.extract_closed = True
    tasks = list(app.state.extractions.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks)
    writes = list(app.state.extract_writes)
    if writes:
        await asyncio.wait(writes)
