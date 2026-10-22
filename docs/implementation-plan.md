# 구현 계획서

[Spec.md](Spec.md) 12절의 마일스톤을 작업 단위로 풀어 진행 상태를 추적하는 문서다. 요구사항의 정본은 Spec.md, 클라이언트 규약의 정본은 [client-contract.md](client-contract.md)이다. 이 문서와 다르면 그쪽이 먼저이고 이 문서를 고친다.

## 1. 사용법과 갱신 규칙

- 작업 ID는 `M{마일스톤}-{NN}` 형식이다(예: `M0-03`). 한 번 붙인 ID는 바꾸지 않는다.
- 상태값은 `대기`, `진행 중`, `완료`, `막힘`, `취소` 다섯 가지다. 막힘과 취소에는 이유를 한 줄 적는다.
- 작업을 시작할 때 `진행 중`으로, 끝낼 때 `완료`로 바꾸고 같은 커밋에 넣는다. 진행 중인 작업은 한 번에 하나만 둔다. 계획서가 묶은 작업 묶음은 하나로 보며, 묶음 안의 작업은 함께 `진행 중`일 수 있다.
- 마일스톤 하나는 "구현 → 검증 → 사용자 확인"을 마친 뒤 다음으로 넘어간다. 종료 체크리스트는 각 마일스톤 상세 절의 끝에 있다.
- 지금 상세하게 쓰는 것은 M0·M1이다. M2~M6은 착수할 때 같은 형식(작업 표, 완료 기준 표)으로 상세화한다.
- 완료한 마일스톤은 작업 표를 한 줄 요약으로 접는다.

## 2. 진행 대시보드

| 마일스톤 | 내용 | 상태 | 작업(완료/전체) | 시작 | 종료 | 종료 커밋 |
|---|---|---|---|---|---|---|
| M0 | 기반 | 완료 | 16/16 | 2026-10-22 | 2026-10-23 | 5d5c9f9 |
| M1 | 글 대화 | 진행 중 | 2/14 | 2026-10-23 | - | - |
| M2 | 일지 | 대기 | - | - | - | - |
| M3 | 음성 | 대기 | - | - | - | - |
| M4 | 신뢰성 | 대기 | - | - | - | - |
| M5 | 확장 기능 | 대기 | - | - | - | - |
| M6 | 보안·마무리 | 대기 | - | - | - | - |
| P2 | 내보내기·검색·브리핑·MCP | 대기 | - | - | - | - |

현재 작업: 묶음 A `m1-a-data-profile`(M1-03 프로필 API 진행 중)
다음 작업: 묶음 A 검증·리뷰 뒤 병합 승인 요청

## 3. M0 기반

**목표**: 이후 모든 마일스톤이 올라설 서버·웹 뼈대와 검증 장치를 갖춘다. LLM·음성 호출은 없다.

**범위 밖**: 상태 머신 전이 표와 `sessionMachine`(M3), CSRF 검사(M6), `persona`·`user_profile` 외 테이블(필요한 마일스톤에서 리비전으로 추가), 음성·PWA 의존성(M3), CLI·음성·검색 설정 항목.

### 3.1 작업 요약

M0-00~M0-15 16개 작업을 모두 완료했다(2026-10-23 종료, 종료 커밋 `5d5c9f9`). 문서 이식, 서버 뼈대(설정·오류·DB·health·클라이언트 설정값·페르소나), 웹 뼈대·타입 생성·core 비의존 린트, 실행 스크립트, Playwright E2E, 검증 자동화다. 작업별 산출물 상세는 `git log -- docs/implementation-plan.md`의 이전 판에 남아 있다. 디자인 시안 사본은 이미 저장소에 있다(커밋 fd642e8).

**작업 순서**: ID 순서가 기본이다. 선행 관계는 M0-05가 M0-03·04 뒤, M0-06이 M0-04·05 뒤, M0-07은 M0-06의 lifespan에 "시작 때 로드"를 연결하므로 M0-06 뒤, M0-08이 M0-03·05 뒤, M0-10이 M0-06(서버 스키마)과 M0-09(웹 폴더) 뒤, M0-11·12가 M0-09 뒤, M0-13이 전부 뒤다. M0-11은 실현 가능성을 먼저 확인하는 스파이크로 시작했다.

### 3.2 작업별 점검

- [x] **M0-01** 폴더와 `README.md`가 있다. `.env.example`에는 값 없이 키 이름만 있다. `.env`는 추적되지 않는다.
- [x] **M0-02** `uv sync`가 성공한다. `uv run ruff check`·`uv run pytest`가 빈 상태에서 통과한다.
- [x] **M0-03** 환경 변수·기본값 테스트가 있다. 테스트 설정이 실제 `.env`를 읽지 않는다.
- [x] **M0-04** 오류 응답 형식, 요청 ID 전파(유효·무효 값, 응답 `request_id` 일치), 404·405·검증 오류·500 변환 테스트가 있다.
- [x] **M0-05** 빈 DB에서 `upgrade head`가 성공하고 모델과 마이그레이션이 일치한다. 열거값과 CHECK가 일치한다.
- [x] **M0-06** 시작 때 자동 마이그레이션이 적용된다. health가 200과 503을 모두 테스트한다. 라우터가 정적 마운트보다 먼저다.
- [x] **M0-07** 정상 파일, 필드 누락, 범위 밖 값 테스트가 있다. 값이 client-contract 7절과 같다.
- [x] **M0-08** 스냅샷, 이름 하드코딩 금지, YAML 변경 반영, 파일 없음·형식 오류 테스트가 있다. 프롬프트에 호칭이 없다.
- [x] **M0-09** `npm run build`와 `npm run test`가 통과한다. `npm run dev`로 빈 앱이 뜬다. `/api` 프록시로 health를 호출한다. 시안 토큰이 `light`와 `dark` 두 벌이다.
- [x] **M0-10** 서버 스키마를 바꾸고 생성물을 갱신하지 않으면 `--check`가 실패한다.
- [x] **M0-11** `src/core`에 `window`나 `react` import를 넣으면 린트와 `typecheck:core`가 실패한다. 샘플은 정상 코드에 남지 않는다.
- [x] **M0-12** `run.sh` 실행 뒤 두 포트가 열리고 `stop.sh`가 이 저장소의 프로세스만 끝낸다.
- [x] **M0-13** 격리 서버와 웹으로 스모크가 통과한다. 사용한 DB·디렉터리가 임시 경로(`web/.e2e/data`, git 무시)이고 다음 E2E 실행 때 지워진다. 실제 `server/data`는 바뀌지 않는다.
- [x] **M0-14** 문서의 명령과 폴더 구조가 실제와 같다.
- [x] **M0-15** `verify.sh`가 통과·실패·건너뜀을 구분한다. 훅이 기존 테스트·보호 파일 수정에 확인을 요청하고, `git commit`·`push`·`merge` 전에 verify를 실행해 실패하면 막는다. force push는 거부, main push·의존성 변경은 확인을 요청한다. pre-push와 Actions가 같은 게이트를 쓴다.

### 3.3 완료 기준

| 기준 | 목표 | 측정값 | 결과 |
|---|---|---|---|
| 서버 테스트 | `uv run pytest` 통과 | 98개 통과 | 통과 |
| 서버 린트 | `uv run ruff check`, `uv run ruff format --check` 통과 | 오류 0 | 통과 |
| 웹 | `npm run typecheck`, `npm run typecheck:core`, `npm run lint`, `npm run test`, `npm run build` 통과 | 웹 테스트 24개 통과, 빌드 성공 | 통과 |
| 타입 생성 | `npm run gen:api -- --check` 통과 | 서버 스키마와 일치 | 통과 |
| health | `GET /api/health` 200, DB 불가 시 503 | pytest(실제 엔진 실패 경로)와 격리 서버 curl로 확인 | 통과 |
| 마이그레이션 | 모델↔마이그레이션 일치, 열거 CHECK 일치, 시작 때 head 자동 적용 | 마이그레이션 테스트 통과 | 통과 |
| 페르소나 | 스냅샷·이름 하드코딩 금지 통과, YAML만 바꿔 이름·말투 반영(NFR-08) | 스냅샷 3개, 이름 하드코딩 방지, YAML 변경 반영 테스트 통과 | 통과 |
| core 린트 | 위반 샘플이 린트와 tsc에서 실패 | 위반 샘플 12종 실패·정상 코드 통과(`tests/core-isolation.test.ts`) | 통과 |
| 클라이언트 설정값 | 잘못된 파일이면 서버가 시작하지 않음 | 잘못된 값 12종·누락 파일 테스트 통과 | 통과 |
| E2E | Playwright 스모크 통과, 임시 경로 격리 확인 | Playwright 7개 통과(스모크 5, 시각 2), 격리 서버가 `web/.e2e/data` 아래에 DB 생성 | 통과 |
| 게이트 | `scripts/verify.sh` 통과, 실패 시 단계명과 함께 종료 코드 1, 훅·pre-push·Actions가 같은 스크립트를 실행 | 전체 통과, 실패 시험으로 확인, Actions 성공 | 통과 |

### 3.4 M0 종료 체크리스트

M0에는 LLM·음성 호출이 없으므로 실제 CLI 점검과 구독 사용량 확인은 해당 없음이다.

- [x] 단위 테스트와 Playwright 실구동 통과, 완료 기준 표 채움
- [x] `CLAUDE.md`와 client-contract가 코드와 일치
- [x] 독립 서브에이전트가 diff를 리뷰하고 지적을 반영
- [x] 커밋·푸시
- [x] 사용자 확인
- [x] 대시보드·추적표 갱신, 작업 표를 한 줄 요약으로 접음

## 4. M1 글 대화

**목표**: 글로 대화하고 모든 턴이 DB에 즉시 기록된다. Claude CLI 세션 매니저, SSE 턴, 도구, 무발화 종료, 최소 웹 대화 화면, 톤 평가까지 갖춘다. 설계 결정은 승인된 M1 계획(2026-10-23)을 따르고, v1(`~/pythonProject/TrailTalk/server/`)의 검증된 구현에서 음성·끼어들기·지연 계측·첨부·검색·메일을 걷어 내고 옮긴다.

**범위 밖**: 일지 추출·재시도·목록·상세·삭제·다시 열기(M2), 마크다운 렌더링·시작 화면 카드(M2), 음성·끼어들기·`prepare`(M3~M4), 웹 검색·첨부·이메일·사용량 막대·설정 화면(M5), CSRF(M6). `POST /sessions/{id}/end`의 `journal_status`는 M2 전까지 `null`이다(client-contract 2.9에는 M1-10에서 반영한다).

### 4.1 작업 표

| ID | 묶음 | 작업 | 산출물 | 상태 |
|---|---|---|---|---|
| M1-01 | A | 모델·리비전 0002 | `db/models.py`에 `conversation_session`·`turn`·`note`(열거 CHECK), `migrations/versions/0002_*.py`, `test_migrations.py`의 `TABLES`·열거 CHECK 시험 갱신, `test_conversation_models.py` | 완료 |
| M1-02 | A | 설정 키 | `config.py`: `claude_cli_path`, `claude_code_oauth_token`, `cli_turn_timeout_s`, `llm_chat_model`, `internal_base_url`, `cli_env_passthrough`. 테스트는 `Settings(_env_file=None)` | 완료 |
| M1-03 | A | 프로필 API | `GET/PUT /api/profile`(client-contract 4.1 규칙, `default_chat_model`), 오류 코드·문서 9절 갱신 | 대기 |
| M1-04 | B | LLM 계층 이식 | `app/llm/{backend,events,parser,claude_cli,manager}.py`, `LlmError` 계열(`llm_error`·`llm_process_exited`·`llm_timeout`). `build_command`의 `--allowedTools`는 서버 목록에서 만든다(M1은 자체 서버만) | 대기 |
| M1-05 | B | 가짜 CLI·녹화·시험 | `tests/fakes/`, `tests/fixtures/claude_cli/`(v1 복사, 경로 치환 확인), `fake_cli` 픽스처, `test_llm_cli.py`: 다중 턴, 크래시 후 `--resume`, 모델 변경 재기동, 시간 초과, 환경 격리, 토큰 비로깅 | 대기 |
| M1-06 | C | 대화 서비스 | `services/runtime.py`, `services/conversation.py`(시작·턴·종료), `jobs/idle.py`(30분 무발화 종료), `llm/sentences.py`(문장 분리) | 대기 |
| M1-07 | C | 세션 API와 SSE | `api/events.py`, `api/sessions.py`(`POST /sessions`·`/sessions/{id}/turns`·`/sessions/{id}/end`), 라우터 등록 | 대기 |
| M1-08 | C | 도구 서버(MCP) | `mcp/server.py`: `save_note`·`search_notes`·`search_conversations`·`summarize_session`·`pause_session`·`end_session`·`set_nickname`·`set_model`, 인증 미들웨어, `mount_mcp`. `mcp_client_config`는 외부 서버 목록(M1은 빈 목록)을 받는 형태. 의존성 `mcp` 추가(사용자 확인) | 대기 |
| M1-09 | C | 프롬프트·기억 | `MemoryContext` 채우기(열린 아이디어·할 일·관심사), `rules.py` 도구 절을 실제 도구 목록에 맞춤, 스냅샷 갱신·차이 검토 | 대기 |
| M1-10 | C | 계약·타입 | `npm run gen:api`로 `schema.d.ts` 재생성, client-contract 반영(2.9에 `journal_status`는 M2 전까지 `null` 명시) | 대기 |
| M1-11 | D | 웹 대화 화면 | `core/sse.ts`, `api/conversation.ts`, `screens/` 대화 화면(시작 버튼·말풍선·입력창·도구 알림·대화종료·`session_ended` 처리) | 대기 |
| M1-12 | D | E2E | 가짜 CLI를 `CLAUDE_CLI_PATH`로 쓰는 격리 서버(8100)로 대화·즉시 기록(DB 확인)·새로고침 후 이어짐·오류 | 대기 |
| M1-13 | D | 톤 평가 | `server/tests/persona_eval/`(v1 이식, 글 대화 맥락 질문 20개, `RUN_REAL_CLI=1`), 실제 CLI 1회 실행과 `docs/eval/` 리포트 | 대기 |
| M1-14 | D | 문서 정합·종료 | 이 문서 갱신, client-contract·CLAUDE.md 점검, 종료 체크리스트 | 대기 |

묶음은 브랜치 하나씩이다: A `m1-a-data-profile`(M1-01~03), B `m1-b-llm`(M1-04~05), C `m1-c-turns-tools`(M1-06~10), D `m1-d-web-eval`(M1-11~14). 순서는 A → B → C → D이고 묶음마다 승인을 받는다.

### 4.2 작업별 점검

- [x] **M1-01** 빈 DB에서 `upgrade head`가 성공하고 모델과 마이그레이션이 일치한다. 열거 CHECK가 모델과 같다.
- [x] **M1-02** 새 설정 키 기본값·환경 변수 시험이 있고 실제 `.env`를 읽지 않는다.
- [ ] **M1-03** 필드별 범위·오류(422)·기본값 생성·`client` 읽기 전용 시험이 있다.
- [ ] **M1-04** 파서가 녹화 이벤트를 모두 해석하고 `is_error`·중단을 구분한다.
- [ ] **M1-05** 가짜 CLI로 위 시험이 모두 통과하고 시간 민감 시험은 3번 연속 통과한다. 외부 서버 목록이 비면 CLI 인자·mcp 설정이 v1과 같다는 시험과 토큰·`headers` 값이 인자·로그에 없다는 시험이 있다.
- [ ] **M1-06** 사용자 턴이 먼저, 답변은 문장마다 커밋되고 서버를 중간에 죽여도 받은 문장이 남는다. 무발화 30분(시험은 짧게 덮어씀)에 세션이 끝난다. 서버 kill·무발화 시험은 3번 연속 통과한다.
- [ ] **M1-07** SSE 순서(`turn` → `sentence`·`tool` → `done`|`error`)와 오류 코드(`session_not_found`·`session_ended`·`turn_in_progress`)를 시험한다.
- [ ] **M1-08** `/internal/mcp/` JSON-RPC 직접 호출 시험이 있다. 프록시 헤더는 403, 토큰 없음·틀림은 401이다. 프록시 환경 대비 `NO_PROXY=127.0.0.1`이 실행 문서에 있다. `set_nickname`·`set_model`은 사용자 발화 근거가 없으면 거절한다.
- [ ] **M1-09** 프롬프트 스냅샷 갱신 차이를 검토했고 호칭이 프롬프트에 없다.
- [ ] **M1-10** `gen:api -- --check`가 통과한다. client-contract가 코드와 같다.
- [ ] **M1-11** 브라우저에서 글을 보내면 답변이 문장 단위로 나오고 도구 알림과 대화종료가 동작한다. `src/core` 비의존 규칙을 지킨다.
- [ ] **M1-12** E2E가 대화·즉시 기록(DB 확인)·새로고침 후 이어짐·오류 표시를 확인하고, 임시 경로 격리 서버로 통과하며 사용자 8000 서버와 DB는 바뀌지 않는다.
- [ ] **M1-13** 톤 평가가 18/20 이상이고 인사말 이후 호칭이 0개다(말투 예시의 `(호칭)`을 글자 그대로 말하지 않는지 포함). 실제 CLI 사용량을 알렸다.
- [ ] **M1-14** 문서의 명령·구조가 실제와 같다.

### 4.3 완료 기준

| 기준 | 목표 | 측정값 | 결과 |
|---|---|---|---|
| 서버 테스트·린트 | `uv run pytest`, `ruff check`, `ruff format --check` 통과 | - | - |
| 웹 | typecheck 두 종류, lint, test, build 통과 | - | - |
| 타입 생성 | `npm run gen:api -- --check` 통과 | - | - |
| 즉시 기록 | 글 대화의 사용자 턴·답변 문장이 오가는 즉시 DB에 있음 | - | - |
| E2E | Playwright 통과, 임시 경로 격리 확인 | - | - |
| 톤 평가 | 20개 중 18개 이상, 인사말 이후 호칭 0개 | - | - |
| 게이트 | `scripts/verify.sh` 전체 통과 | - | - |

### 4.4 M1 종료 체크리스트

- [ ] 단위 테스트와 Playwright 실구동 통과, 완료 기준 표 채움
- [ ] 톤 평가 실제 CLI 점검(구독 사용량 확인 포함)
- [ ] `CLAUDE.md`와 client-contract가 코드와 일치
- [ ] 묶음마다 독립 서브에이전트가 diff를 리뷰하고 지적을 반영
- [ ] 커밋·푸시
- [ ] 사용자 확인
- [ ] 대시보드·추적표 갱신, 작업 표를 한 줄 요약으로 접음

## 5. M2~M6 요약

착수할 때 3·4절 형식으로 상세화한다. 내용과 완료 기준은 Spec.md 12절을 따른다.

| M | 핵심 | 완료 기준(요약) |
|---|---|---|
| M2 | 종료·추출·재시도·제목 수정·삭제, 일지 화면, 이어서 하기, 시작 화면, 마크다운 렌더링, 화면 스크린샷 기준 이미지(대화 시작·일지·설정, 라이트·다크) | 글 대화 3개의 일지가 맞게 추출, 수락하지 않은 제안 미추출 |
| M3 | VAD·녹음·STT·문장 TTS·재생, 상태 머신, 지연 계측 | PC·폰 음성 대화, TTS 100문장 무손실, 지연 30턴 측정 |
| M4 | 끼어들기, 오프라인 큐, 발화 병합(D2), 맞장구·첫 문장 분할, 쉬기·무발화 종료 | 비행기 모드 유실 0, 병합 15회, 60턴 지연 판정 |
| M5 | 검색·출처, 첨부, 설정 화면, 이메일, 사용량 막대, WebFetch 차단(D7), 외부 MCP 연결(FR-25: 예시 설정 파일·`.gitignore`·허용 도구 차단 확인 포함) | 도구·첨부·설정 E2E, 폰 첨부 확인, 검색 턴 지연 판정, 허용 밖 도구 호출 안 됨(가짜 외부 MCP E2E) |
| M6 | CSRF(D3), 안전장치, PWA, iOS Safari, 실제 산책 1회 | 보안 테스트 통과, 산책 측정 기록 |

## 6. 요구사항 추적표

M0에서 직접 만족하는 요구사항은 NFR-08(설정 분리)뿐이고, 나머지는 해당 마일스톤에서 구현한다. 완료한 항목은 마일스톤 종료 때 지운다.

| 요구사항 | 마일스톤 | | 요구사항 | 마일스톤 |
|---|---|---|---|---|
| FR-01 세션 시작·인사 | M1 | | FR-15 화면 검색 P2, 제니 검색 도구 | M1~M2 |
| FR-02 VAD 자동 전송 | M3, 병합 M4 | | FR-16 Markdown 내보내기 | P2 |
| FR-03 끼어들기 | M4 | | FR-17 설정 | M5 |
| FR-04 음성 명령(도구) | M1, 쉬기·종료 클라이언트 M4 | | FR-18 주간 브리핑 | P2 |
| FR-05 Wake Lock | M3 | | FR-19 일지 조회 MCP | P2 |
| FR-06 STT·문장 TTS | M3 | | FR-20 웹 검색·출처 | M5 |
| FR-07 페르소나 적용 | M0 로더, M1 | | FR-21 이메일 | M5 |
| FR-08 글 대화 | M1 | | FR-22 첨부 | M5 |
| FR-09 브레인스토밍 | M1 | | FR-23 시작 화면 카드·상태·막대 | 최소 연결 표시 M0, 화면 M2, 막대 M5 |
| FR-10 정리 요약 | M1 | | FR-24 마크다운 렌더링 | M2 |
| FR-11 기억 | M1~M2 | | NFR-01 응답 속도 | M3 계측, M4 판정, M5 검색 턴, M6 산책 |
| FR-12 즉시 기록·음성 보관 | M1, 보관 설정은 M5(FR-17) | | NFR-02 핸즈프리 | M4 |
| FR-13 자동 추출 | M2 | | NFR-03/05 인식률·배터리 | M6 |
| FR-14 일지 목록·관리 | M2 | | NFR-04 통신 불안정 | M4 |
| NFR-06 개인정보 | M1~M6 | | NFR-07 페르소나 일관성 | M1 |
| NFR-08 설정 분리 | **M0** | | NFR-09 음성 신뢰성 | M3 |
| NFR-10 보안 | M6 | | FR-25 외부 MCP | M5 |

## 7. 이월·결정

- D6 (주간 브리핑 관심사): P2로 미룸.
- FR-21 이메일은 우선순위 P2지만 Spec 12절에 따라 M5에 둔다.
- FR-25 외부 MCP는 우선순위 P2지만 Spec 12절에 따라 M5에 둔다.
- `GET /api/health` 응답 본문(`status`·`db`)은 이 계획서가 정한 값이다. M0-06에서 client-contract에 한 줄 반영한다.
- 정적 마운트(`StaticFiles(html=True)`)는 클라이언트 라우트 새로고침에 `index.html` 폴백을 주지 않는다. 화면 라우팅을 정하는 M2에서 처리한다.
- 프로필의 `default_chat_model`(`LLM_CHAT_MODEL` 설정)은 프로필 API를 만드는 M1에서 추가한다.
- 페르소나 역할 규칙(`rules.py`)은 v1에서 검증한 전문을 옮겼다. 검색·메일·모델 변경 같은 도구 절은 도구 서버가 생기는 M1(검색 규칙은 M5)에서 실제 도구 목록에 맞춰 다듬고, 그때 프롬프트 스냅샷을 다시 만든다.
- 시스템 프롬프트의 말투 예시는 `{호칭}`을 `(호칭)`으로 보여 준다. 모델이 이를 글자 그대로 말하는지는 M1 톤 평가에서 확인한다.
- `src/core`는 ES2023 내장만 쓴다(`tsconfig.core.json`은 DOM·Node 타입을 뺀다). 타이머·`TextDecoder`·`AbortController` 같은 전역이 필요하면 `Clock` 같은 인터페이스로 주입받는다. oxlint는 `src/core/**`에서만 브라우저 전역·`react`·`platform`·`screens` import를 막는다(`tests/core-isolation.test.ts`가 위반 샘플로 확인).
- 웹 글꼴(Noto Sans KR)은 M0에서 불러오지 않고 시스템 글꼴로 대체한다. 오프라인 PWA에 맞는 방식(자체 호스팅)은 M6에서 정한다.
- D7 (WebFetch 사설망 차단): M5 초반에 CLI 권한 규칙으로 가능한지 확인하고, 안 되면 자체 MCP `web_fetch`로 간다.
- 화면 시안은 렌더링을 검증하지 않았다. M2·M3에서 화면을 구현할 때 아티팩트와 대조하며 어긋남을 기록한다.
- 제안값으로 정한 사항: 초기 리비전은 `persona`·`user_profile`만 둔다. core 비의존은 oxlint와 DOM 제외 tsconfig 두 겹이다. 상태 머신 전이 표는 M3에서 옮긴다. CSRF 검사는 M6이다.
- M0에서 넘어온 약속: Linux CI 시각 비교 기준 이미지는 화면이 생기는 M2~M3에서 CI 산출물을 받아 승인해 더한다(그 전에는 Linux CI가 시각 비교를 건너뛰고 스모크 5개만 돈다). 첨부 `purge_orphans` 안전장치는 M5. `run.sh`의 `--fake`·`--phone`은 필요한 마일스톤(M3~M4)에서 추가한다.
- D8 (외부 MCP 등록): 서버 설정 파일 직접 등록 + 도구 허용 목록, M5(2026-10-23 확정).
- 외부 MCP 구현 메모: v1 `mcp_client_config`는 http 형식만 만들므로 stdio 항목(`command`·`args`·`env`)과 외부 서버 목록은 M5에서 새로 만든다. M5 첫 작업은 `.gitignore`(`server/mcp-servers.yaml`)와 `mcp-servers.example.yaml`이다.
- D8 후속(M5 초반 스파이크, D7과 같은 시점): 범위는 D7, 검색 후보, 허용 밖 도구 차단, 도구 정의 지연, 이름 길이 한도다. 허용 밖 도구 차단 방식(CLI 거부·`--disallowedTools`·서버 중계)이 정해지면 Spec 5.6을 고친다. 후보 HasData(원격 HTTP `https://mcp.hasdata.com/mcp`, `x-api-key` 헤더, `?apis=`로 도구 제한)를 API 키로 `tools/list`·샘플 호출해 도구 이름·인자·결과 형식·한국어 품질·지연·무료 동시 요청 1개 제한을 확인하고, `web_search` 표시 매핑과 `google_search` 이름 변경 여부를 정한다. Spec·계약에는 이 스파이크 뒤에 반영한다.
