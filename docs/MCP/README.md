# Claude 앱 MCP 연계

작성일: 2026-10-30. 상태: **제안(미구현)**. 이 폴더의 문서는 기존 문서(Intent·Spec·구현 계획서·클라이언트 계약)를 고치지 않는다. 반영안은 [doc-changes.md](doc-changes.md)에 모았고, 기존 문서에 옮기는 일(MA-00b)은 사용자 지시 뒤에 한다. 이 폴더 자체는 문서만 바꾸는 변경이라 서브에이전트 diff 리뷰 뒤 `main`에 바로 커밋한다(CLAUDE.md, 2026-10-30 사용자 확인).

## 한 줄 요약

음성 대화는 Claude 앱이 맡고, TrailTalk 서버는 외부 MCP 서버(`/mcp`, OAuth 보호)로 일지·노트를 저장·조회·검색·수정·삭제하는 도구 13개를 제공한다. 앱에서 저장한 내용은 기존 웹 일지 화면에 그대로 보이고 고칠 수 있다. 자체 음성 처리(STT/TTS)는 지우지 않고 **보류**한다.

## 결정 (2026-10-30 사용자 확정)

| # | 결정 |
|---|---|
| 1 | 음성 대화는 Claude 앱이 맡고 v2는 MCP로 연계한다 |
| 2 | 자체 음성 개발은 완전 제거가 아니라 **보류**한다. 이미 `main`에 병합된 M3-01~15 코드는 그대로 두고, M3-16~19와 M4의 음성 항목을 보류로 표시한다 |
| 3 | `trailTalk-MCP`의 `spike.db`에 쌓인 일지는 v2로 **옮기지 않는다** |
| 4 | 외부 MCP 도구는 13개: `save_journal`, `list_journals`, `get_journal`, `search_conversations`, `delete_journal`, `rename_journal`, `save_note`, `search_notes`, `list_notes`, `update_note`, `delete_note`, `get_memory`, `set_nickname`(호칭 변경, 2026-10-30 추가) |
| 5 | `get_memory`는 호칭·최근 일지(제목·요약)·아직 닫지 않은 아이디어·**아직 닫지 않은 할 일(최근 5개까지)**을 돌려준다(할 일 포함은 2026-10-30 확정). 관심사는 넣지 않는다 |
| 6 | 일지 없이 저장하는 노트는 날짜별 "앱 메모" 세션 하나에 모은다 |
| 7 | 외부 MCP(`/mcp`)는 내부용(`/internal/mcp`)과 분리하고, 로직은 `services/` 한 곳에 두고 두 쪽이 공유한다 |
| 8 | 화면 시안은 이번 작업에서 **수정하지 않는다**(2026-10-30 사용자 지시) |
| 9 | **노트(아이디어·할 일·메모)는 출처와 무관하게** 앱 음성으로 별표·완료·내용 수정·삭제할 수 있다(웹에서 만든 아이디어 포함, 2026-10-30 확정). **일지(제목 수정·삭제)는 앱 출처만** 다룬다. 조회·검색은 모두 한다. 할 일·메모까지 노트 전체에 같은 규칙을 적용한다(사용자 확정) |
| 10 | 일지·노트(아이디어 포함) 삭제는 모두 음성으로 할 수 있고 **서버가 강제하는 2단계 확인**을 거친다: `confirm_token` 없이 부르면 지우지 않고 대상 요약과 확인 값을 돌려주며, 사용자 확인 뒤 그 값을 넘겨야 지운다(`delete_journal`·`delete_note`). 사용자가 실제로 확인했는지는 서버가 보장하지 못한다 |
| 11 | 앱 일지 출처 표시 UI(와 이어서 하기 숨김 화면)는 **시안을 수정한 뒤** 구현한다. 시안 수정은 사용자의 별도 지시가 있을 때 한다. 서버 쪽(출처 필드·이어서 하기 거절)은 시안과 무관하게 먼저 구현할 수 있다 |
| 12 | 외부 MCP는 **별도 ASGI 앱·별도 포트**로 둔다 |
| 13 | 앱 메모 세션은 전용 열(`app_kind`)로 구분한다 |
| 14 | 앱이 넘긴 `transcript`는 `Turn`으로 풀어 저장한다 |
| 15 | `save_journal` 갱신은 기존 노트를 유지하고 없는 내용만 더한다. 삭제는 `delete_note`뿐 |
| 16 | 앱 세션은 `checks=[]`, 앱 세션 전문 화자 이름은 "Claude", 앱 일지·앱 메모 중복은 날짜 키 `app_day`로 막는다(제안, MA-04·10에서 확정) |

## 범위 밖

- 화면 시안(`docs/design/`, 아티팩트) 수정
- Intent·Spec·구현 계획서·client-contract 직접 수정(반영안만 제시)
- `spike.db` 이관
- 코드 구현

## 문서 안내

| 문서 | 내용 |
|---|---|
| [Intent.md](Intent.md) | 연계의 의도: 목표, 장면, 원칙, 성공 기준, 보류 |
| [Spec.md](Spec.md) | 연계의 명세: 요구사항, 아키텍처, 동작 규칙, 데이터·API 변경, 보안, 테스트, 결정 |
| [design.md](design.md) | 구조, 인증, 데이터 매핑, 보안, 코드 배치, 검증, 마일스톤 제안 |
| [tools.md](tools.md) | 도구 13개의 입력·출력·규칙 |
| [doc-changes.md](doc-changes.md) | Intent·Spec·계획서·계약에 반영할 변경안(시안 제외) |
| [implementation-plan.md](implementation-plan.md) | 구현 계획: 묶음·작업 ID·상태·완료 기준·진행 대시보드 |

## 참고 자료

- 시험용 구현(참고, 수정 금지): `~/pythonProject/trailTalk-MCP/` — Claude 앱(웹·폰 음성)에서 쓴 OAuth 보호 MCP 서버. 도구 12개의 원형(`set_nickname`은 v2 내부 MCP 것을 서비스로 옮겨 재사용)과 `oauth.py`·`login.py`가 있다. 일지는 `Journal` 테이블 한 장이다.
- v2 내부 MCP: `server/app/mcp/server.py`(`/internal/mcp`, Claude CLI 전용, 루프백만 허용, 프록시 경유 거부).
- v2 데이터: `server/app/db/models.py`의 `ConversationSession`·`Turn`·`Note`, 기억 조립 `server/app/persona/memory.py`.

## 사실과 추정의 구분

이 문서의 앱 쪽 동작(Claude 앱 음성 모드의 도구 호출 안정성, 첫 호출 지연 로딩, 커넥터 접속 조건)은 `trailTalk-MCP` CLAUDE.md의 기록과 일반적인 MCP 동작에 근거한 것이며, v2에서 구현·실측한 것이 아니다. 구현 뒤 폰에서 확인할 항목은 [design.md](design.md) 7절에 있다.
