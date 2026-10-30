# TrailTalk v2

- 의도: [docs/Intent.md](docs/Intent.md)
- 명세: [docs/Spec.md](docs/Spec.md) — 마일스톤은 12절(M0~M6)
- 규약: [docs/client-contract.md](docs/client-contract.md) — API·SSE·상태 머신·오류 코드의 정본
- 구현 계획: [docs/implementation-plan.md](docs/implementation-plan.md) — 작업 ID·상태·완료 기준. 작업을 시작·끝낼 때 상태를 갱신해 같은 커밋에 넣는다.
- 화면 시안: [docs/design/README.md](docs/design/README.md) — 아티팩트 링크와 소스 사본(`docs/design/*.dc.html`). 시안을 고치면 같은 커밋에서 이 폴더도 맞춘다.
- Claude 앱 MCP 연계(2026-10-30 결정): [docs/MCP/README.md](docs/MCP/README.md) — 결정·도구 명세·구현 계획서(MA 작업의 진행 상태 정본, 작업을 시작·끝낼 때 같은 커밋에서 갱신)
- v1 소스(참고용): `~/pythonProject/TrailTalk/`

위 문서는 자동으로 불러오지 않는다(`@` import 금지). 필요한 절만 `grep -n "^#"`으로 위치를 찾아 범위를 지정해 읽는다.

## 구조와 명령

```
server/   FastAPI 서버(Python 3.12, uv). app/ 코드, migrations/ Alembic, personas/ 캐릭터 YAML, tests/
web/      React PWA(Vite, TypeScript). src/core 순수 로직, src/api 서버 호출·생성 타입, src/screens·src/components 화면, e2e/ Playwright
shared/   서버와 웹이 함께 읽는 값(client-defaults.json)
scripts/  verify.sh 검증 게이트(.githooks/pre-push, .claude/hooks, .github/workflows가 같은 스크립트를 쓴다)
```

- 실행·종료: `./run.sh`(`--tmp` 임시 데이터), `./stop.sh`. Claude 앱 연계 외부 MCP 서버는 `./run.sh --mcp`(`.env`에 `MCP_PUBLIC_URL`·`MCP_OWNER_PASSWORD`가 있어야 한다, 포트 8400), 토큰 전체 폐기는 `./run.sh --mcp-revoke-all`
- 검증: `scripts/verify.sh [--quick]`. 문서(`docs/`, `CLAUDE.md`, `README.md`)를 뺀 작업 트리가 같으면 통과한 단계(quick, full)를 `.git/verify-cache/` 기록으로 건너뛴다(commit에서 통과한 코드의 push는 build·E2E만 돈다). 서버·웹 검사는 병렬이고 서버 pytest는 xdist 6 워커다(`VERIFY_PYTEST_WORKERS`로 조정, CPU 수만큼 늘리면 시간에 민감한 테스트가 흔들린다). `VERIFY_NO_CACHE=1`로 기록을 끄고 `VERIFY_SERIAL=1`로 순차 실행한다.
- 서버 API를 바꾸면 `cd web && npm run gen:api`로 `src/api/schema.d.ts`를 다시 만들어 함께 커밋한다.
- 프롬프트를 바꾸면 `cd server && UPDATE_SNAPSHOTS=1 uv run pytest tests/test_prompt.py`로 스냅샷을 갱신하고 차이를 검토한다.
- 화면을 바꿔 스크린샷 기준이 달라지면 `cd web && npm run e2e:update`로 갱신하고 이미지를 눈으로 확인한 뒤 커밋한다.
- 프롬프트·페르소나를 바꾸면 톤 평가를 다시 돌린다: `cd server && RUN_REAL_CLI=1 uv run python -m tests.persona_eval.run_eval`(실제 Claude CLI 사용량이 나가므로 알리고 쓴다). 리포트는 `docs/eval/`에 남고 기준은 20개 중 18개 이상·인사말 이후 호칭 0개다.
- 모델을 바꾸면 Alembic 리비전을 같은 커밋에 넣는다(`cd server && uv run alembic revision --autogenerate -m "..."`).

## 작업 규칙

- 브랜치와 병합(2026-10-22 사용자 확정): 코드 작업은 작업(`M0-03` 같은 ID) 하나당, 또는 계획서가 묶은 작업 묶음 하나당 브랜치 하나(`m0-a-server-base` 형식)에서 한다. 브랜치 안에서는 묻지 않고 커밋하고, 원격 브랜치에 푸시해 백업한다. 브랜치 커밋마다 리뷰하지 않고 병합 승인을 요청하기 전에 한 번 리뷰한다. `main`에는 사용자 승인 뒤에만 병합(`--no-ff`)·푸시한다. 승인을 요청하기 전에 다음 세 가지를 모두 통과시키고 결과를 보고한다: 검증 명령 전부, Playwright 실구동 검증, 독립 general-purpose 서브에이전트 diff 리뷰(지적 반영). 문서만 바꾸는 변경(`docs/` 아래 전부(시안 `docs/design/*.dc.html` 포함), `CLAUDE.md`, `README.md`)은 예외로, 사용자 승인 없이 `main`에 바로 커밋·푸시하되, 커밋·푸시 전에 독립 general-purpose 서브에이전트로 diff 리뷰를 반드시 거치고 지적을 반영한다. 리뷰 뒤에 의미가 바뀌는 수정(규칙·계약·보안·설계 서술)을 더 했다면 커밋 전에 그 부분을 다시 리뷰한다. 오타·표현·서식만 고친 경우는 재리뷰하지 않고 보고에 밝히되, 의미 변경인지 애매하면 재리뷰한다. 설정·데이터 파일(`server/personas/*.yaml`, `shared/client-defaults.json` 등)과 코드가 섞인 변경은 코드 규칙을 따른다. 마일스톤 종료 확인은 그 마일스톤 마지막 작업의 `main` 병합 승인과 겸한다.
- 원격은 GitHub 계정 kangsuek의 `TrailTalk-v2`이고 기본 브랜치는 `main`이다.
- 웹 앱(PWA)이므로 실제 동작 검증은 Playwright로 브라우저(Chromium)를 띄워 한다. 단위 테스트만으로 끝내지 않는다. 가짜 마이크는 `--use-fake-device-for-media-stream`과 wav 파일을 쓴다.
- 화면 캡처도 Playwright 브라우저로 한다. OS 좌표 자동화(osascript)는 쓰지 않는다.
- 검증용 서버를 띄울 때는 DB, 첨부, 오디오, CLI 작업 폴더를 모두 임시 경로로 바꾼다(서버 시작 때 `purge_orphans`가 DB에 없는 첨부를 지운다). 사용자의 실제 서버(포트 8000)와 DB는 건드리지 않는다. 실제 Claude CLI와 OpenAI 호출은 사용량과 과금이 있으니 필요할 때만 쓰고 알린다.
- 캐릭터 이름·성격·말투·보이스·안내 문구는 코드가 아닌 `server/personas/*.yaml`에만 둔다.
- 마일스톤 하나를 구현·검증하고 사용자 확인을 받은 뒤 다음으로 넘어간다.
- 화면 디자인(2026-10-24 사용자 확정): 화면이 있는 작업은 [docs/design/README.md](docs/design/README.md)의 보드 표에서 그 작업에 해당하는 시안을 찾아 같은 작업에서 디자인까지 적용한다. 시안의 기능이 뒤 마일스톤 몫(토큰 막대 M5, 첨부 M5, 음성 선택 M3 등)이면 만들지 않고 구현 계획서의 해당 마일스톤 작업에 "시안 적용"을 적는다. 검증은 Playwright 스크린샷을 시안(`docs/design/*.dc.html`)과 눈으로 대조하고, 시안과 다르게 한 부분은 보고에 밝힌다.

## 개발 규칙

- 코드 수정 전에 Spec.md·client-contract.md의 해당 절과 영향받는 기존 기능·테스트를 먼저 확인한다.
- 기존 테스트를 삭제·skip하거나 기대값·허용 오차를 완화하려면 사용자 승인을 받는다(훅이 기존 테스트·보호 파일 수정 때 확인을 요청한다). 계약이 바뀌어 고쳐야 하면 문서 변경과 함께 하고 이유를 커밋 메시지에 적는다. 새 테스트 추가는 자유다.
- 작업 범위는 `docs/implementation-plan.md`의 진행 중인 마일스톤 작업 표에서 지금 하는 작업(또는 작업 묶음)의 산출물이다. 범위 밖 파일을 고쳐야 하면 멈추고 보고한다.
- 버그를 고칠 때는 실패하는 회귀 테스트를 먼저 추가하고 고친다. 커밋은 한 목적씩 작게 나눈다.
- force push는 `.claude/settings.json`이 거부(deny)하고, `main` push·`git merge`·`reset --hard`·의존성 추가·업그레이드는 확인(ask)을 요청한다. 문서만 바꾸는 직접 `main` 푸시도 이 확인이 뜨며, 이는 위 예외 규칙에 따라 승인하는 자리다(코드 변경은 사용자 승인 없이 승인하지 않는다). 규칙을 우회하지 않는다. 훅은 Edit·Write·MultiEdit만 가로채고 `sed -i` 같은 Bash 수정은 막지 못하므로, 테스트·보호 파일은 도구로 고친다. 게이트 자체(`.claude/`, `scripts/verify.sh`, `.githooks/`, 워크플로)도 보호 파일이다.
- 변경 후 `scripts/verify.sh`를 실행한다(`--quick`은 타입·린트·단위 테스트, 인자 없이는 빌드·E2E까지). `git commit` 전에는 `--quick`, `git push`·`git merge` 전에는 전체가 훅(`.claude/hooks/gate-git.py`)과 `.githooks/pre-push`로 자동 실행되고 실패하면 막힌다. 개별 명령은 다음과 같다(해당 폴더와 스크립트가 생긴 뒤부터). 서버(`server/`): `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`. 웹(`web/`): `npm run typecheck`, `npm run typecheck:core`, `npm run lint`, `npm run test`, `npm run build`, `npm run gen:api -- --check`, `npm run e2e`(Playwright, 전체 모드).
- 테스트나 검증이 실패하면 구현을 멈추고 원인과 영향 범위를 보고한 뒤 지시를 기다린다.
- `main` 병합 승인을 요청할 때 변경 요약(`git diff --stat`과 핵심 변경), 검증 결과, 서브에이전트 리뷰 결과를 함께 보고한다. 문서만 바꾼 직접 커밋도 커밋 뒤에 변경 요약과 서브에이전트 리뷰 결과(지적과 반영 내용, 재리뷰하지 않은 오타·표현·서식 수정이 있으면 그 내용)를 보고한다.
