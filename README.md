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

## 검증

```bash
scripts/verify.sh           # 전체 게이트(서버, 웹이 생긴 뒤에는 웹·빌드·E2E 포함)
scripts/verify.sh --quick   # 타입·린트·단위 테스트
git config core.hooksPath .githooks   # 직접 푸시할 때도 전체 검증이 걸리게 한다(clone마다 한 번, `--no-verify`로 건너뛸 수 있음)
```

서버만 따로: `(cd server && uv run pytest && uv run ruff check . && uv run ruff format --check .)`.
웹(`web/`): `npm ci` 뒤 `npm run typecheck`, `typecheck:core`, `lint`, `test`, `build`, `gen:api -- --check`. 개발 서버는 `npm run dev`(`/api`를 `VITE_API_TARGET`, 기본 `http://127.0.0.1:8000`으로 넘긴다). 서버 API를 바꾸면 `npm run gen:api`로 `src/api/schema.d.ts`를 다시 만든다. GitHub에서는 push·PR마다 같은 검증이 돌아간다(`.github/workflows/verify.yml`).
