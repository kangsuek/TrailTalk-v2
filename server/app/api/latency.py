"""음성 턴 지연 보고와 요약(client-contract 2.15, Spec 5.1)."""

import math
import statistics
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import TurnLatency, TurnTts
from app.db.session import DbSession
from app.errors import AppError

router = APIRouter(tags=["latency"])

_MAX_MS = 600_000
_STAGES = (
    "upload_ms",
    "stt_ms",
    "first_token_ms",
    "first_queued_ms",
    "first_synth_ms",
    "synth_wait_ms",
    "first_sentence_ms",
    "done_ms",
)


class LatencyReport(BaseModel):
    """클라이언트가 턴마다 한 번 보고하는 값(0~600000ms)."""

    speech_to_request_ms: Annotated[int, Field(ge=0, le=_MAX_MS)]
    request_to_playback_ms: Annotated[int, Field(ge=0, le=_MAX_MS)]
    first_sound_notice: bool = False
    ack_ms: Annotated[int, Field(ge=0, le=_MAX_MS)] | None = None  # 맞장구(M4). 없으면 생략


class LatencyTurn(BaseModel):
    turn_id: str
    upload_ms: int | None
    stt_ms: int | None
    first_token_ms: int | None
    first_queued_ms: int | None
    first_synth_ms: int | None
    synth_wait_ms: int | None
    first_sentence_ms: int | None
    done_ms: int | None
    audio_bytes: int | None
    cli_age_ms: int | None
    reply_chars: int | None
    searched: bool
    speech_to_request_ms: int | None
    request_to_playback_ms: int | None
    first_sound_notice: bool | None
    ack_ms: int | None
    total_ms: int | None  # 말 끝 → 첫 답변 소리(두 보고값의 합). 보고 전이면 null


class Stat(BaseModel):
    median: int
    p90: int


class TotalStats(BaseModel):
    count: int
    total_ms: Stat | None
    total_ms_reply: Stat | None  # 첫 소리가 답변 문장인 턴만(검색 안내 음성이 가리지 않게)


class TtsStats(BaseModel):
    models: dict[str, int]  # 모델 이름 → 문장 수(기기 TTS로 넘어간 문장은 "device")
    fallback_ratio: float  # 기본 모델에서 대체 모델·기기 TTS로 넘어간 문장의 비율


class LatencySummary(BaseModel):
    count: int
    total_ms: Stat | None
    total_ms_reply: Stat | None
    stages: dict[str, int]  # 서버 단계별 중앙값(ms)
    ack_ms: Stat | None
    search: TotalStats
    tts: TtsStats


class LatencyOut(BaseModel):
    turns: list[LatencyTurn]
    summary: LatencySummary


def _stat(values: list[int]) -> Stat | None:
    if not values:
        return None
    ordered = sorted(values)
    p90 = ordered[math.ceil(0.9 * len(ordered)) - 1]
    return Stat(median=round(statistics.median(ordered)), p90=p90)


def _total(row: TurnLatency) -> int | None:
    if row.speech_to_request_ms is None or row.request_to_playback_ms is None:
        return None
    return row.speech_to_request_ms + row.request_to_playback_ms


@router.post("/sessions/{session_id}/turns/{turn_id}/latency", status_code=204)
async def report_latency(
    session_id: str, turn_id: str, body: LatencyReport, db: DbSession
) -> Response:
    row = await db.get(TurnLatency, turn_id)
    if row is None or row.session_id != session_id:
        raise AppError("turn_not_found", "지연을 기록한 턴이 없습니다.", 404)
    row.speech_to_request_ms = body.speech_to_request_ms
    row.request_to_playback_ms = body.request_to_playback_ms
    row.first_sound_notice = body.first_sound_notice
    row.ack_ms = body.ack_ms
    await db.commit()
    return Response(status_code=204)


@router.get("/latency")
async def get_latency(
    db: DbSession, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> LatencyOut:
    rows = list(
        await db.scalars(select(TurnLatency).order_by(TurnLatency.created_at.desc()).limit(limit))
    )
    plain = [row for row in rows if not row.searched]
    searched = [row for row in rows if row.searched]

    def totals(items: list[TurnLatency]) -> tuple[Stat | None, Stat | None]:
        reported = [(row, _total(row)) for row in items]
        every = [t for _, t in reported if t is not None]
        reply = [t for row, t in reported if t is not None and not row.first_sound_notice]
        return _stat(every), _stat(reply)

    total, reply = totals(plain)
    search_total, search_reply = totals(searched)
    stages = {}
    for name in _STAGES:
        stat = _stat([v for row in plain if (v := getattr(row, name)) is not None])
        if stat is not None:
            stages[name] = stat.median
    ack = _stat([row.ack_ms for row in plain if row.ack_ms is not None])

    turn_ids = [row.turn_id for row in rows]
    tts_rows = (
        list(await db.scalars(select(TurnTts).where(TurnTts.turn_id.in_(turn_ids))))
        if turn_ids
        else []
    )
    models: dict[str, int] = {}
    fallbacks = counted = 0
    for item in tts_rows:
        if item.model is None and not item.fallback:
            continue  # 읽을 글자가 없어 소리를 만들지 않은 문장
        counted += 1
        fallbacks += item.fallback
        key = item.model or "device"
        models[key] = models.get(key, 0) + 1

    return LatencyOut(
        turns=[
            LatencyTurn(
                **{
                    name: getattr(row, name)
                    for name in (
                        "turn_id",
                        *_STAGES,
                        "audio_bytes",
                        "cli_age_ms",
                        "reply_chars",
                        "searched",
                        "speech_to_request_ms",
                        "request_to_playback_ms",
                        "first_sound_notice",
                        "ack_ms",
                    )
                },
                total_ms=_total(row),
            )
            for row in rows
        ],
        summary=LatencySummary(
            count=len(plain),
            total_ms=total,
            total_ms_reply=reply,
            stages=stages,
            ack_ms=ack,
            search=TotalStats(
                count=len(searched), total_ms=search_total, total_ms_reply=search_reply
            ),
            tts=TtsStats(models=models, fallback_ratio=(fallbacks / counted) if counted else 0.0),
        ),
    )
