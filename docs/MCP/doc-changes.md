# 기존 문서 반영 기록

2026-10-30에 MA-00b로 Intent·Spec·구현 계획서·클라이언트 계약에 옮긴 변경 목록이다. 반영은 끝났고 이 문서는 어떤 절을 고쳤는지의 기록이다(절 번호는 당시 기준). 화면 시안(`docs/design/`, 아티팩트)은 사용자 지시로 범위에서 제외했다.

## 1. Intent (`docs/Intent.md`)

- "주 장면" 문장을 "음성 대화는 Claude 앱(MCP 연계)이 맡고 TrailTalk는 그 일지·노트를 저장하고 보여 준다. 자체 음성 처리(STT/TTS)는 보류한다. 글 대화는 유지한다"로 바꾸고, 글 대화가 TrailTalk가 직접 하는 유일한 대화 수단이 됨을 적었다.
- 기능 표의 음성 대화와 설정(보이스·말 속도·음성 원본 보관)에 "보류"를, 응답 지연 서술에 "보류 중" 각주를 달았다.

## 2. Spec (`docs/Spec.md`)

| 절 | 변경 |
|---|---|
| 3 NFR-06, 9 개인정보 | 예외에 "앱 연계: 일지·노트 내용이 사용자의 Claude 계정(Anthropic)으로 전달된다" 추가 |
| 3.1 요구사항 | FR-19를 Claude 앱 MCP 서버로 바꾸고 P1로 올림, 음성 관련 FR에 "보류" 표시, FR-26(앱 일지·노트를 웹에서 보고 고침) 추가 |
| 4 아키텍처, 5.6 도구 | 외부 MCP 앱(별도 ASGI 앱·포트)·공유 `services/` 계층 추가, 내부(`/internal/mcp`)와 외부(`/mcp`) 도구 서버 구분 |
| 6 데이터 모델, 7 서버 API | `SessionMode.claude_app`·앱 구분 열·OAuth 테이블, 일지 목록·상세의 출처 필드, 앱 세션 다시 열기 거절 |
| 9 보안 | 공개 Funnel은 MCP·OAuth 전용 포트에만 쓰고 `/api`·웹·`/internal`은 공개하지 않음. OAuth·토큰 해시·로그인 시도 제한, 쓰기·삭제 도구 인젝션 방어(서버 강제 2단계 확인) |
| 12 마일스톤, 13 결정 | M3-16~19·M4 음성 항목 보류, MA 행 추가, 결정 D9 |

## 3. 클라이언트 계약 (`docs/client-contract.md`)

| 절 | 변경 |
|---|---|
| 1.2 폰 접속 | MCP 전용 포트만 Funnel로 열고 `/api`는 열지 않음, 폰 접속 주소·포트 서술 |
| 1.5 변경성 요청 보안 | 외부 MCP 앱은 `Authorization: Bearer`로만 인증해 이 규칙의 대상이 아니고 로그인 폼은 자체 CSRF 방어를 둠 |
| 2.11 다시 열기 | 앱 세션은 409로 거절 |
| 3.1 목록, 3.2 상세 | 앱 일지·앱 메모는 턴 수와 무관하게 나오고 출처 필드(`source`)가 붙음. 앱 세션은 retry 무동작, 같은 날 같은 제목 거부(409), `persona_name`은 설정값, `checks=[]` |
| 3.3 노트 | 노트 삭제는 앱 MCP만 제공하고 앱이 웹 노트도 고칠 수 있음(마지막 쓴 것이 남음) |

서버 API가 바뀌어 `npm run gen:api`로 `src/api/schema.d.ts`를 갱신했다.

## 4. 구현 계획서 (`docs/implementation-plan.md`)

대시보드 갱신, M3 묶음 D(M3-16~19)와 M4 음성 항목 "보류" 표시, 새 마일스톤 MA 안내(상세는 [implementation-plan.md](implementation-plan.md)), 요구사항 추적표의 FR-19 갱신, 이월·결정에 이 결정과 근거(외부 노출은 MCP 전용 포트, `spike.db` 미이관, 시안 미수정)와 "출처 표시 UI는 시안이 없다"는 열린 항목을 기록했다.

## 5. CLAUDE.md·README

CLAUDE.md "구조와 명령"에 MCP 서버 실행·종료와 `docs/MCP/` 링크를, `.env.example`에 키 이름만, README에 앱 연결 절차(커넥터 URL, 로그인)를 더했다.

## 6. 결정 (2026-10-30)

외부 MCP는 별도 ASGI 앱·포트, 앱 메모는 전용 열 `app_kind`, `transcript`는 `Turn`으로 저장, 삭제 도구는 서버가 강제하는 확인 값(`confirm_token`), 앱이 고칠 수 있는 범위는 노트는 출처 무관(웹 노트 포함)·일지는 앱 출처만, `get_memory`는 열린 할 일을 최근 5개까지 포함(관심사 제외), 도구는 13개(`set_nickname` 추가), 출처 표시 UI는 시안 수정 뒤 구현한다. Funnel 443은 MCP 전용이고 PWA Serve는 8443이다(공존은 MA-12 전에 확인, design.md 1.1).
