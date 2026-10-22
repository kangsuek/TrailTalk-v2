# 구현 계획서

[Spec.md](Spec.md) 12절의 마일스톤을 작업 단위로 풀어 진행 상태를 추적하는 문서다. 요구사항의 정본은 Spec.md, 클라이언트 규약의 정본은 [client-contract.md](client-contract.md)이다. 이 문서와 다르면 그쪽이 먼저이고 이 문서를 고친다.

## 1. 사용법과 갱신 규칙

- 작업 ID는 `M{마일스톤}-{NN}` 형식이다(예: `M0-03`). 한 번 붙인 ID는 바꾸지 않는다.
- 상태값은 `대기`, `진행 중`, `완료`, `막힘`, `취소` 다섯 가지다. 막힘과 취소에는 이유를 한 줄 적는다.
- 작업을 시작할 때 `진행 중`으로, 끝낼 때 `완료`로 바꾸고 같은 커밋에 넣는다. 진행 중인 작업은 한 번에 하나만 둔다.
- 마일스톤 하나는 "구현 → 검증 → 사용자 확인"을 마친 뒤 다음으로 넘어간다. 종료 체크리스트는 3절 끝에 있다.
- 지금 상세하게 쓰는 것은 M0뿐이다. M1~M6은 착수할 때 M0와 같은 형식(작업 표, 완료 기준 표)으로 상세화한다.
- 완료한 마일스톤은 작업 표를 한 줄 요약으로 접는다.

## 2. 진행 대시보드

| 마일스톤 | 내용 | 상태 | 작업(완료/전체) | 시작 | 종료 | 종료 커밋 |
|---|---|---|---|---|---|---|
| M0 | 기반 | 진행 중 | 10/16 | - | - | - |
| M1 | 글 대화 | 대기 | - | - | - | - |
| M2 | 일지 | 대기 | - | - | - | - |
| M3 | 음성 | 대기 | - | - | - | - |
| M4 | 신뢰성 | 대기 | - | - | - | - |
| M5 | 확장 기능 | 대기 | - | - | - | - |
| M6 | 보안·마무리 | 대기 | - | - | - | - |
| P2 | 내보내기·검색·브리핑·MCP | 대기 | - | - | - | - |

현재 작업: 묶음 B(M0-08 페르소나) 병합 승인 대기
다음 작업: M0-09

## 3. M0 기반

**목표**: 이후 모든 마일스톤이 올라설 서버·웹 뼈대와 검증 장치를 갖춘다. LLM·음성 호출은 없다.

**범위 밖**: 상태 머신 전이 표와 `sessionMachine`(M3), CSRF 검사(M6), `persona`·`user_profile` 외 테이블(필요한 마일스톤에서 리비전으로 추가), 음성·PWA 의존성(M3), CLI·음성·검색 설정 항목.

### 3.1 작업 표

| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M0-00 | `client-contract.md` 이식(v2 계약 변경 반영) | `docs/client-contract.md`(커밋 c310f96) | 완료 |
| M0-01 | 저장소 뼈대 | `server/`, `web/`, `shared/`, `README.md`, `server/.python-version`, `.env.example`(키 이름만), `.gitignore` 점검 | 완료 |
| M0-02 | 서버 환경 | `server/pyproject.toml`(uv). 의존성은 M0에 필요한 것만: fastapi, uvicorn, pydantic-settings, sqlalchemy[asyncio], aiosqlite, alembic, pyyaml / 개발: pytest, pytest-asyncio, ruff. ruff는 line-length 100·규칙 E,F,I,UP,B, pytest는 `asyncio_mode=auto`. 테스트가 0개면 pytest가 실패하므로 `create_app`·health 스모크 테스트 1개를 함께 둔다 | 완료 |
| M0-03 | 설정 | `app/config.py`: DB, 로그, 자동 마이그레이션, 페르소나 폴더·기본, 시간대, 웹 dist, 클라이언트 설정 경로(`CLIENT_DEFAULTS_PATH`), 검증 서버용 임시 경로 키(첨부·오디오·CLI 작업 폴더 디렉터리 설정 키 이름만 먼저 정하고 쓰는 기능은 해당 마일스톤: 첨부 `purge_orphans` 안전장치는 M5). 테스트는 `Settings(_env_file=None)`로 만든다 | 완료 |
| M0-04 | 오류·요청 ID·로깅 | `errors.py`(`AppError`와 핸들러 4종: `AppError`, HTTP 예외(`not_found`·`method_not_allowed`·그 밖은 HTTP 상태 이름 코드), 검증 오류(`validation_error`, `details`에 `loc`·`msg`·`type`), 미처리 예외(`internal_error`, 내부 정보 비노출). 응답 `{"error":{code,message,request_id,details}}`), `request_context.py`(X-Request-ID, 정규식 `[A-Za-z0-9._-]{1,64}` 전체 일치), 로깅 설정, 오류 형식 테스트. `csrf_rejected` 코드는 문서에만 두고 검사는 M6 | 완료 |
| M0-05 | DB와 Alembic | `db/{base,types,session,migrate}.py`(명명 규칙, `UTCDateTime`, `new_id()`, SQLite FK pragma, `get_db`), `migrations/`(비동기 env, `render_as_batch`, 마이그레이션 중 FK 끄고 `foreign_key_check`, ruff 후처리), 초기 리비전 `0001`: `persona`, `user_profile`만. 모델↔마이그레이션 일치 테스트와 열거 CHECK 일치 테스트(`user_profile.chat_model`)를 처음부터 둔다 | 완료 |
| M0-06 | 앱 팩토리와 health | `main.py`의 `create_app(settings)`. 순서: 로깅 → lifespan(자동 마이그레이션) → 요청 컨텍스트 → 오류 핸들러 → `/api` 라우터(health 먼저) → 정적 마운트(마지막). `GET /api/health`: 200 `{"status":"ok","db":"ok"}`, DB 불가 시 503 `db_unavailable` | 완료 |
| M0-07 | 클라이언트 설정값 | `shared/client-defaults.json`(client-contract 7절 기준: `turn.*`, `turn.ack_*`, `merge_min_speech_ms` 포함), 서버 검증 모듈 `app/client_config.py`, 시작 때 로드(M0-06 lifespan에 연결). `session.idle_timeout_minutes`의 `IDLE_TIMEOUT_S` 덮어쓰기(0 이하이면 시작 거부)도 검증한다. `offline_notice`·`attachments`는 이 파일 값이 아니므로 M0에서 검증하지 않는다. 잘못된 파일이면 서버가 시작하지 않는다 | 완료 |
| M0-08 | 페르소나 | `persona/{schema,loader,prompt,rules}.py`, `personas/jenny.yaml`(이름·성격·말투, `voice`, `examples`, `closing`, `search_notice`, `ack` 목록, `offline_notice`, `{호칭}`은 인사말 예시에만). 조립기는 호칭을 받지 않고 `greeting_request(nickname)`만 호칭을 인사말 요청에 붙인다. 다시 열기용 '이어서 하는 대화' 블록은 M2. 로더는 sha256 버전을 만들고 오류는 `persona_not_found` 404, `persona_invalid` 500. 조립기는 persona·situation·memory·role rules 블록으로 만들며 호칭을 넣지 않는다(Spec 5.7). `rules.py`에 "인사말 이후에는 사용자를 호칭으로 부르지 않는다"를 넣고 테스트한다. 인사말 요청에 호칭을 붙이는 앱 안내는 M1. 기억 블록은 빈 `MemoryContext` 자리만. 테스트: 스냅샷(`UPDATE_SNAPSHOTS=1`로 갱신), `server/app/**/*.py`에 캐릭터 이름 하드코딩 금지, YAML만 바꿔 이름·말투 반영 | 완료 |
| M0-09 | 웹 환경 | `web/`: Vite, React 19, TypeScript, vitest, oxlint. 빈 앱(하단 탭 3개 자리와 서버 연결 상태 표시), `/api` 프록시(대상 주소는 환경변수로 받아 격리 서버 포트와 겹치지 않게 한다), vitest 테스트 1개 이상, `typecheck`(앱 전체 `tsc --noEmit`) 스크립트, 시안 토큰(색·글꼴·크기) 상수 | 대기 |
| M0-10 | OpenAPI→TS 타입 생성 | `app/openapi.py`, `web/scripts/gen-api.mjs`(openapi-typescript), `npm run gen:api`와 `npm run gen:api -- --check`, 생성물 `web/src/api/schema.d.ts` 커밋 | 대기 |
| M0-11 | core 비의존 린트 | `web/src/core/`를 두 겹으로 강제한다. (1) oxlint 오버라이드: `src/core/**`에서 브라우저 전역(`window`, `document`, `navigator`, `localStorage`, `indexedDB`, `fetch` 등)과 `react`, `../platform` import 금지. (2) `tsconfig.core.json`(lib에서 DOM 제외)으로 `npm run typecheck:core`. 타이머·`TextDecoder`·`AbortController`처럼 DOM 밖에서도 필요한 전역은 허용 목록이나 주입 규칙을 정한다. 착수 첫 단계에서 oxlint `overrides`가 `src/core/**`에만 걸리는지 확인하고, 안 되면 대안을 정해 사용자에게 알린다. 위반 샘플 파일로 둘 다 실패함을 확인하는 테스트 | 대기 |
| M0-12 | 실행 스크립트 | `run.sh`(서버 8000 + 웹 5173), `stop.sh`(PID 파일로 이 저장소가 띄운 프로세스만 종료, 사용자 8000 서버와 구별). `--fake`·`--phone`은 해당 마일스톤에서 추가 | 대기 |
| M0-13 | E2E 스모크 | Playwright(Chromium). 임시 DB·임시 경로의 격리 서버(포트 8100)와 웹을 띄워, 앱이 뜨고 서버 연결 "연결됨"이 보이는지 확인. 스크린샷 비교(`toHaveScreenshot`) 틀을 빈 앱 화면 1~2장으로 만든다(핵심 화면 기준 이미지는 M2~M3). 기준 이미지는 CI와 같은 Linux 환경에서 만든다(맥에서 만들면 글꼴 렌더링이 달라 CI에서 실패하므로 CI 산출물을 받아 승인하거나 Docker로 만든다). CI에는 Playwright 브라우저 설치 단계가 이미 조건부로 들어 있다. 사용자의 실제 서버(8000)와 DB는 건드리지 않는다 | 대기 |
| M0-14 | 문서 정합 | `CLAUDE.md`(폴더 구조·명령·개발 규칙·`verify.sh` 사용), 이 문서의 대시보드, client-contract 7절과 설정값 파일의 일치 확인 | 대기 |
| M0-15 | 검증 자동화 | `scripts/verify.sh`(`--quick`), `.claude/settings.json`(deny·ask 규칙과 PreToolUse 훅 2개), `.claude/hooks/{guard-protected,gate-git}.py`, `.githooks/pre-push`, `.github/workflows/verify.yml`, CLAUDE.md 개발 규칙. 스크린샷 비교는 M0-13에서 틀만, 핵심 화면 기준 이미지는 M2~M3 | 완료 |

디자인 시안 사본은 이미 저장소에 있다(커밋 fd642e8).

**작업 순서**: ID 순서가 기본이다. 선행 관계는 M0-05가 M0-03·04 뒤, M0-06이 M0-04·05 뒤, M0-07은 M0-06의 lifespan에 "시작 때 로드"를 연결하므로 M0-06 뒤, M0-08이 M0-03·05 뒤, M0-10이 M0-06(서버 스키마)과 M0-09(웹 폴더) 뒤, M0-11·12가 M0-09 뒤, M0-13이 전부 뒤다. M0-11은 실현 가능성을 먼저 확인하는 스파이크로 시작한다(해당 행 참고).

### 3.2 작업별 점검

- [x] **M0-01** 폴더와 `README.md`가 있다. `.env.example`에는 값 없이 키 이름만 있다. `.env`는 추적되지 않는다.
- [x] **M0-02** `uv sync`가 성공한다. `uv run ruff check`·`uv run pytest`가 빈 상태에서 통과한다.
- [x] **M0-03** 환경 변수·기본값 테스트가 있다. 테스트 설정이 실제 `.env`를 읽지 않는다.
- [x] **M0-04** 오류 응답 형식, 요청 ID 전파(유효·무효 값, 응답 `request_id` 일치), 404·405·검증 오류·500 변환 테스트가 있다.
- [x] **M0-05** 빈 DB에서 `upgrade head`가 성공하고 모델과 마이그레이션이 일치한다. 열거값과 CHECK가 일치한다.
- [x] **M0-06** 시작 때 자동 마이그레이션이 적용된다. health가 200과 503을 모두 테스트한다. 라우터가 정적 마운트보다 먼저다.
- [x] **M0-07** 정상 파일, 필드 누락, 범위 밖 값 테스트가 있다. 값이 client-contract 7절과 같다.
- [x] **M0-08** 스냅샷, 이름 하드코딩 금지, YAML 변경 반영, 파일 없음·형식 오류 테스트가 있다. 프롬프트에 호칭이 없다.
- [ ] **M0-09** `npm run build`와 `npm run test`가 통과한다. `npm run dev`로 빈 앱이 뜬다. `/api` 프록시로 health를 호출한다. 시안 토큰이 `light`와 `dark` 두 벌이다.
- [ ] **M0-10** 서버 스키마를 바꾸고 생성물을 갱신하지 않으면 `--check`가 실패한다.
- [ ] **M0-11** `src/core`에 `window`나 `react` import를 넣으면 린트와 `typecheck:core`가 실패한다. 샘플은 정상 코드에 남지 않는다.
- [ ] **M0-12** `run.sh` 실행 뒤 두 포트가 열리고 `stop.sh`가 이 저장소의 프로세스만 끝낸다.
- [ ] **M0-13** 격리 서버와 웹으로 스모크가 통과한다. 사용한 DB·디렉터리가 임시 경로이고 종료 때 지워진다.
- [ ] **M0-14** 문서의 명령과 폴더 구조가 실제와 같다.
- [x] **M0-15** `verify.sh`가 통과·실패·건너뜀을 구분한다. 훅이 기존 테스트·보호 파일 수정에 확인을 요청하고, `git commit`·`push`·`merge` 전에 verify를 실행해 실패하면 막는다. force push는 거부, main push·의존성 변경은 확인을 요청한다. pre-push와 Actions가 같은 게이트를 쓴다.

### 3.3 완료 기준

| 기준 | 목표 | 측정값 | 결과 |
|---|---|---|---|
| 서버 테스트 | `uv run pytest` 통과 | - | - |
| 서버 린트 | `uv run ruff check`, `uv run ruff format --check` 통과 | - | - |
| 웹 | `npm run typecheck`, `npm run typecheck:core`, `npm run lint`, `npm run test`, `npm run build` 통과 | - | - |
| 타입 생성 | `npm run gen:api -- --check` 통과 | - | - |
| health | `GET /api/health` 200, DB 불가 시 503 | - | - |
| 마이그레이션 | 모델↔마이그레이션 일치, 열거 CHECK 일치, 시작 때 head 자동 적용 | - | - |
| 페르소나 | 스냅샷·이름 하드코딩 금지 통과, YAML만 바꿔 이름·말투 반영(NFR-08) | - | - |
| core 린트 | 위반 샘플이 린트와 tsc에서 실패 | - | - |
| 클라이언트 설정값 | 잘못된 파일이면 서버가 시작하지 않음 | - | - |
| E2E | Playwright 스모크 통과, 임시 경로 격리 확인 | - | - |
| 게이트 | `scripts/verify.sh` 통과, 실패 시 단계명과 함께 종료 코드 1, 훅·pre-push·Actions가 같은 스크립트를 실행 | - | - |

### 3.4 M0 종료 체크리스트

M0에는 LLM·음성 호출이 없으므로 실제 CLI 점검과 구독 사용량 확인은 해당 없음이다.

- [ ] 단위 테스트와 Playwright 실구동 통과, 완료 기준 표 채움
- [ ] `CLAUDE.md`와 client-contract가 코드와 일치
- [ ] 독립 서브에이전트가 diff를 리뷰하고 지적을 반영
- [ ] 커밋·푸시
- [ ] 사용자 확인
- [ ] 대시보드·추적표 갱신, 작업 표를 한 줄 요약으로 접음

## 4. M1~M6 요약

착수할 때 3절 형식으로 상세화한다. 내용과 완료 기준은 Spec.md 12절을 따른다.

| M | 핵심 | 완료 기준(요약) |
|---|---|---|
| M1 | Claude CLI 세션 매니저, SSE 턴, 즉시 기록, 도구, 서버 무발화 종료, 프롬프트 스냅샷 추가·갱신 | 글 대화가 DB에 즉시 기록, 톤 평가 18/20 |
| M2 | 종료·추출·재시도·제목 수정·삭제, 일지 화면, 이어서 하기, 시작 화면, 마크다운 렌더링, 화면 스크린샷 기준 이미지(대화 시작·일지·설정, 라이트·다크) | 글 대화 3개의 일지가 맞게 추출, 수락하지 않은 제안 미추출 |
| M3 | VAD·녹음·STT·문장 TTS·재생, 상태 머신, 지연 계측 | PC·폰 음성 대화, TTS 100문장 무손실, 지연 30턴 측정 |
| M4 | 끼어들기, 오프라인 큐, 발화 병합(D2), 맞장구·첫 문장 분할, 쉬기·무발화 종료 | 비행기 모드 유실 0, 병합 15회, 60턴 지연 판정 |
| M5 | 검색·출처, 첨부, 설정 화면, 이메일, 사용량 막대, WebFetch 차단(D7) | 도구·첨부·설정 E2E, 폰 첨부 확인, 검색 턴 지연 판정 |
| M6 | CSRF(D3), 안전장치, PWA, iOS Safari, 실제 산책 1회 | 보안 테스트 통과, 산책 측정 기록 |

## 5. 요구사항 추적표

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
| NFR-10 보안 | M6 | | | |

## 6. 이월·결정

- D6 (주간 브리핑 관심사): P2로 미룸.
- FR-21 이메일은 우선순위 P2지만 Spec 12절에 따라 M5에 둔다.
- `GET /api/health` 응답 본문(`status`·`db`)은 이 계획서가 정한 값이다. M0-06에서 client-contract에 한 줄 반영한다.
- 정적 마운트(`StaticFiles(html=True)`)는 클라이언트 라우트 새로고침에 `index.html` 폴백을 주지 않는다. 화면 라우팅을 정하는 M2에서 처리한다.
- 프로필의 `default_chat_model`(`LLM_CHAT_MODEL` 설정)은 프로필 API를 만드는 M1에서 추가한다.
- 페르소나 역할 규칙(`rules.py`)은 v1에서 검증한 전문을 옮겼다. 검색·메일·모델 변경 같은 도구 절은 도구 서버가 생기는 M1(검색 규칙은 M5)에서 실제 도구 목록에 맞춰 다듬고, 그때 프롬프트 스냅샷을 다시 만든다.
- 시스템 프롬프트의 말투 예시는 `{호칭}`을 `(호칭)`으로 보여 준다. 모델이 이를 글자 그대로 말하는지는 M1 톤 평가에서 확인한다.
- D7 (WebFetch 사설망 차단): M5 초반에 CLI 권한 규칙으로 가능한지 확인하고, 안 되면 자체 MCP `web_fetch`로 간다.
- 화면 시안은 렌더링을 검증하지 않았다. M2·M3에서 화면을 구현할 때 아티팩트와 대조하며 어긋남을 기록한다.
- 제안값으로 정한 사항: 초기 리비전은 `persona`·`user_profile`만 둔다. core 비의존은 oxlint와 DOM 제외 tsconfig 두 겹이다. 상태 머신 전이 표는 M3에서 옮긴다. CSRF 검사는 M6이다.
