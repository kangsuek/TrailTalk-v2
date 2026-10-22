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

## 검증 명령

```bash
(cd server && uv run pytest && uv run ruff check . && uv run ruff format --check .)
```

웹 명령(`web/`)은 M0-09 이후에 추가한다.
