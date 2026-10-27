"""다시 연 대화의 프롬프트(M2-08): '이어서 하는 대화' 블록 스냅샷. 새 대화의 프롬프트(test_prompt.py
스냅샷)는 바뀌지 않는다."""

from app.persona.prompt import (
    RECENT_LIMIT,
    PastNote,
    PastSummary,
    PastTurn,
    build_system_prompt,
    previous_block,
)
from tests.test_prompt import MEMORY, NOW, TZ, check_snapshot, persona  # noqa: F401

PREVIOUS = [
    PastTurn("assistant", "안녕하세요! 오늘은 어떤 이야기를 해 볼까요?"),
    PastTurn("user", "등산로 쓰레기통 지도 앱을 생각해 봤어"),
    PastTurn("assistant", "오, 재밌겠어요! 어디에 먼저 표시하면 좋을까요?", interrupted=True),
]
SUMMARY = PastSummary(
    title="등산로 쓰레기통 지도",
    summary=["쓰레기통 지도 앱을 만들어 보기로 했다.", "입구와 정상에 먼저 표시하면 쓸모가 크다."],
    checks=["공개 데이터가 있는지"],
    notes=[
        PastNote("아이디어", "등산로 쓰레기통 지도"),
        PastNote("할 일", "북한산 입구 사진 찍기", done=True),
    ],
)


def test_snapshot_text_reopened(persona):  # noqa: F811
    check_snapshot(
        "prompt_jenny_text_reopened",
        build_system_prompt(
            persona, mode="text", now=NOW, timezone=TZ, memory=MEMORY, previous=PREVIOUS
        ),
    )


def test_snapshot_text_reopened_long_with_summary(persona):  # noqa: F811
    long = PREVIOUS + [
        PastTurn("user" if i % 2 == 0 else "assistant", f"이야기 {i} " + "가" * 300)
        for i in range(20)
    ]
    check_snapshot(
        "prompt_jenny_text_reopened_summary",
        build_system_prompt(
            persona,
            mode="text",
            now=NOW,
            timezone=TZ,
            memory=MEMORY,
            previous=long,
            previous_summary=SUMMARY,
        ),
    )


def test_short_transcript_ignores_summary(persona):  # noqa: F811
    assert previous_block(persona, PREVIOUS, SUMMARY) == previous_block(persona, PREVIOUS)


def test_recent_text_is_bounded(persona):  # noqa: F811
    long = [PastTurn("user", "가" * 500) for _ in range(30)]
    block = previous_block(persona, long, SUMMARY)
    recent = block[block.index("<대화>") : block.index("</대화>")]
    assert len(recent) <= RECENT_LIMIT + 600  # 한도 + 표시 줄·마지막 한 줄 여유
    assert "<정리>" in block


def test_new_session_prompt_has_no_previous_block(persona):  # noqa: F811
    prompt = build_system_prompt(persona, mode="text", now=NOW, timezone=TZ, memory=MEMORY)
    assert "# 이어서 하는 대화" not in prompt
