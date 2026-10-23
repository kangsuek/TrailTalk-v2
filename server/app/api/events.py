"""턴 SSE 이벤트(client-contract 2.4).

`POST /api/sessions/{id}/turns`는 text/event-stream으로 아래 이벤트를 보낸다. 첫 이벤트는
turn(turn_id)이고 마지막은 done 또는 error 하나다(음성 업로드의 transcript는 M3).
각 메시지는 `event: <type>` 줄과 `data: <JSON>` 줄로 이뤄지고 JSON에도 type이 들어 있다.
자체 도구의 이름은 `mcp__trailtalk__` 접두사를 떼어 보내고, 접두사가 있는 이름은 외부 MCP
도구(M5)다(2.5).
"""

from typing import Annotated, Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ToolPhase = Literal["start", "call", "end"]
SessionStatusValue = Literal["active", "paused", "ended"]


class _Event(BaseModel):
    # 기본값이 있는 필드도 항상 보내므로 스키마에서 required로 표시한다(생성 타입의 type 좁히기)
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class TurnEvent(_Event):
    """스트림의 첫 이벤트. turn_id는 이번 답변(assistant 턴)의 ID로 끼어들기(M4)에 쓴다."""

    type: Literal["turn"] = "turn"
    turn_id: str


class SentenceEvent(_Event):
    """캐릭터 답변의 한 문장. index는 턴 안에서 0부터 증가한다.

    audio·speech_text는 음성 세션(M3)에서만 값이 오고 글 대화에서는 항상 null이다."""

    type: Literal["sentence"] = "sentence"
    index: int
    text: str
    audio: str | None = None
    speech_text: str | None = None


class ToolResultSummary(_Event):
    """앱 도구(save_note 등) 결과. result는 도구가 돌려준 값(보통 문자열)."""

    kind: Literal["result"] = "result"
    result: Any


ToolSummary = Annotated[ToolResultSummary, Field(discriminator="kind")]


class VoiceNotice(BaseModel):
    """답변이 아닌 안내 음성(예: 검색 전 "잠깐 찾아볼게요", M3). audio는 MP3(base64) 또는 null."""

    text: str
    audio: str | None


class ToolEvent(_Event):
    """도구 사용. start(이름만) → call(입력 완성) → end(결과 요약) 순서로 온다."""

    type: Literal["tool"] = "tool"
    phase: ToolPhase
    tool_use_id: str
    name: str
    input: dict[str, Any] | None = None
    summary: ToolSummary | None = None  # end에서만. 결과 형식을 모르면 null
    is_error: bool = False
    notice: VoiceNotice | None = None  # 음성 세션(M3)의 검색 안내


class DoneEvent(_Event):
    """턴 끝. session_status가 paused/ended면 도구(pause_session/end_session)가 바꾼 것이다."""

    type: Literal["done"] = "done"
    turn_id: str  # turn 이벤트와 같은 ID(저장된 assistant 턴)
    text: str
    interrupted: bool = False
    session_status: SessionStatusValue = "active"
    superseded: bool = False  # 병합으로 대체된 턴(M4)


class ErrorEvent(_Event):
    """스트림 도중 오류. code는 공통 오류 형식(client-contract 9절)과 같은 값이다."""

    type: Literal["error"] = "error"
    code: str
    message: str


StreamEvent = Annotated[
    TurnEvent | SentenceEvent | ToolEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]
_STREAM_EVENT = TypeAdapter(StreamEvent)
AnyEvent = TurnEvent | SentenceEvent | ToolEvent | DoneEvent | ErrorEvent

_OWN_PREFIX = "mcp__trailtalk__"


def public_tool_name(cli_name: str) -> str:
    """CLI 도구 이름을 클라이언트용 이름으로 바꾼다. 자체 도구만 접두사를 뗀다."""
    return cli_name.removeprefix(_OWN_PREFIX)


def encode_sse(event: AnyEvent) -> bytes:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n".encode()


def parse_sse_data(data: str) -> AnyEvent:
    """data 줄의 JSON을 이벤트로 되돌린다(테스트·도구용)."""
    return _STREAM_EVENT.validate_json(data)


def sse_response_doc(description: str) -> dict[int | str, dict[str, Any]]:
    """라우트의 responses 인자: 200 응답을 text/event-stream(StreamEvent)으로 문서화한다."""
    return {
        200: {
            "description": description,
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/StreamEvent"}}
            },
        }
    }


def register_event_schemas(app: FastAPI) -> None:
    """OpenAPI components에 이벤트 스키마를 넣는다(웹 타입 생성용)."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original()
        defs = _STREAM_EVENT.json_schema(
            mode="serialization", ref_template="#/components/schemas/{model}"
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.update(defs.pop("$defs", {}))
        components["StreamEvent"] = defs
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
