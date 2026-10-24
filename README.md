# TrailTalk v2

등산·산책 중 이어폰만으로 캐릭터 '제니'와 대화하며 브레인스토밍하고, 대화를 자동으로 일지로 정리하는 앱의 v2.

- 의도: [docs/Intent.md](docs/Intent.md)
- 명세: [docs/Spec.md](docs/Spec.md)
- 규약: [docs/client-contract.md](docs/client-contract.md)
- 구현 계획(진행 상황은 대시보드): [docs/implementation-plan.md](docs/implementation-plan.md)
- 화면 시안: [docs/design/README.md](docs/design/README.md)

## 구조

```
server/   FastAPI 서버 (Python 3.12, uv)
web/      React PWA (Vite, TypeScript)
shared/   서버와 웹이 함께 읽는 값 (client-defaults.json)
docs/     문서
```

## 필요 도구

[uv](https://docs.astral.sh/uv/)(Python 3.12는 uv가 받는다), Node.js 24. 설정은 `cp .env.example .env` 뒤 필요한 값만 채운다.

## 실행

```bash
./run.sh            # 서버(8000)와 웹(5173)을 띄우고 브라우저를 연다. DB는 server/data/trailtalk.db
./run.sh --tmp      # 임시 데이터(.run/tmp)로 실행(실제 DB를 건드리지 않는 확인용)
./run.sh --no-open  # 브라우저를 열지 않는다
./stop.sh           # 다른 터미널에서 끄기(이 저장소의 run.sh만 종료). Ctrl+C로도 끌 수 있다
```

포트는 `API_PORT`, `WEB_PORT` 환경 변수로 바꾼다. 처음 실행하면 의존성을 설치한다(`uv sync`, `npm ci`).

## 검증

```bash
scripts/verify.sh           # 전체 게이트(서버, 웹이 생긴 뒤에는 웹·빌드·E2E 포함)
scripts/verify.sh --quick   # 타입·린트·단위 테스트
git config core.hooksPath .githooks   # 직접 푸시할 때도 전체 검증이 걸리게 한다(clone마다 한 번, `--no-verify`로 건너뛸 수 있음)
```

서버만 따로: `(cd server && uv run pytest && uv run ruff check . && uv run ruff format --check .)`.
페르소나 톤 평가(실제 Claude CLI를 써서 구독 사용량이 든다): `(cd server && RUN_REAL_CLI=1 uv run python -m tests.persona_eval.run_eval)`. 리포트는 `docs/eval/`에 남는다.
웹(`web/`): `npm ci` 뒤 `npm run typecheck`, `typecheck:core`, `lint`, `test`, `build`, `gen:api -- --check`, `e2e`(Playwright. 처음에는 `npx playwright install chromium`. 임시 폴더 `web/.e2e/`의 격리 서버 8100과 웹 5174를 자동으로 띄운다. 스크린샷 기준 이미지는 OS별(`e2e/__screenshots__/<OS>/`)이라 기준이 없는 OS에서는 시각 비교를 건너뛴다. 갱신은 `npm run e2e:update`로 하고 눈으로 확인한 뒤 커밋). 개발 서버는 `npm run dev`(`/api`를 `VITE_API_TARGET`, 기본 `http://127.0.0.1:8000`으로 넘긴다). 서버 API를 바꾸면 `npm run gen:api`로 `src/api/schema.d.ts`를 다시 만든다. GitHub에서는 push·PR마다 같은 검증이 돌아간다(`.github/workflows/verify.yml`).
