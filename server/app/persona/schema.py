"""캐릭터 YAML(server/personas/*.yaml) 스키마. 키 오타는 바로 오류로 잡는다(NFR-08)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# 캐시된 객체를 여러 곳이 공유하므로 목록도 바꿀 수 없는 tuple로 둔다
TextList = Annotated[tuple[Text, ...], Field(min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpeechStyle(_Strict):
    # YAML 키는 register(BaseModel 속성과 이름이 겹쳐 내부 이름만 바꾼다)
    register_: Text = Field(alias="register")
    use: TextList
    avoid: TextList
    max_sentences_voice: Annotated[StrictInt, Field(ge=1, le=10)]


class VoiceStyle(_Strict):
    """TTS 보이스(결정 D3: OpenAI TTS). 피치 조절은 OpenAI TTS에 없어 instructions로 대신한다."""

    tts_voice: Text  # OpenAI 보이스 이름(예: coral)
    speaking_rate: Annotated[float, Field(ge=0.25, le=4.0)]  # OpenAI speed
    instructions: Text  # 말투·톤·빠르기 지시(gpt-4o-mini-tts)
    # 아무 말 없이 웹 검색을 시작할 때 서버가 대신 들려주는 안내(음성 세션)
    search_notice: Text


SAVED_PLACEHOLDER = "{저장}"


class Closing(_Strict):
    """세션을 닫을 때 하는 마무리 멘트(설계서 4.4).

    {저장}에는 앱이 "아이디어 3개, 할 일 1개"를 넣는다."""

    saved: Text  # 저장한 것이 있을 때
    nothing: Text  # 저장한 것이 없을 때

    @model_validator(mode="after")
    def _placeholder(self) -> "Closing":
        if SAVED_PLACEHOLDER not in self.saved:
            raise ValueError(f"closing.saved에는 {SAVED_PLACEHOLDER}가 있어야 합니다")
        if SAVED_PLACEHOLDER in self.nothing:
            raise ValueError(f"closing.nothing에는 {SAVED_PLACEHOLDER}를 쓸 수 없습니다")
        return self


class Persona(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,64}$")]
    name: Text
    role: Text
    personality: TextList
    speech_style: SpeechStyle
    brainstorm_style: TextList
    examples: TextList
    closing: Closing
    voice: VoiceStyle
    # 답이 늦을 때 먼저 들려주는 짧은 맞장구 문구(규약 6.4). 음성 세션에서 합성해 내려간다
    ack: TextList
    # 오프라인 보관 때 기기 TTS로 읽는 안내(규약 7절)
    offline_notice: Text

    @model_validator(mode="after")
    def _placeholder_only_in_examples(self) -> "Persona":
        """{호칭}은 인사말 예시(examples)에서만 쓸 수 있으므로 다른 필드에 쓰면 오류로 알린다."""
        data = self.model_dump(exclude={"examples"})
        if "{호칭}" in str(data):
            raise ValueError("{호칭}은 examples에서만 쓸 수 있습니다")
        return self
