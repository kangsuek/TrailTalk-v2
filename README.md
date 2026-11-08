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
scripts/  검증 게이트(verify.sh)와 커밋 뒤 백그라운드 검증(verify-bg.sh)
docs/     문서
```

`.githooks/`(git 훅)와 `.claude/`(Claude Code 훅·설정)는 검증 게이트의 일부다(아래 "검증").

## 필요 도구

[uv](https://docs.astral.sh/uv/)(Python 3.12는 uv가 받는다), Node.js 24. 자체 음성 대화(현재 보류 중이지만 코드는 있다)에는 OpenAI 키(`OPENAI_API_KEY`)가 필요하다. ogg 등 변환이 필요한 오디오를 받으려면 ffmpeg도 있어야 한다(`brew install ffmpeg`, MacPorts는 `sudo port install ffmpeg`, 없어도 웹이 보내는 webm·wav는 동작한다). 설정은 `cp .env.example .env` 뒤 필요한 값만 채운다.

## 실행

```bash
./run.sh            # 서버(8000)와 웹(5173)을 띄우고 브라우저를 연다. DB는 server/data/trailtalk.db
./run.sh --tmp      # 임시 데이터(.run/tmp)로 실행(실제 DB를 건드리지 않는 확인용)
./run.sh --no-open  # 브라우저를 열지 않는다
./run.sh --fake     # 음성 인식·합성을 과금 없는 가짜로(OpenAI 키 없이 음성 화면 확인)
./run.sh --phone    # 폰 접속 안내(마이크는 HTTPS 필요): Tailscale 호스트를 허용하고 tailnet 전용 HTTPS(8443) 켜는 명령을 알려 준다(Tailscale 설정은 바꾸지 않음)
./run.sh --mcp      # 외부 MCP 서버(8400)를 명시해서 띄운다. .env 설정이 있으면 옵션 없이도 자동(--no-mcp로 끔, 아래 "Claude 앱 연결")
./stop.sh           # 다른 터미널에서 끄기(이 저장소의 run.sh만 종료). Ctrl+C로도 끌 수 있다
./stop.sh --mcp     # 외부 MCP 서버(자동 또는 --mcp로 띄운 것)만 끈다(서버와 웹은 계속 실행)
```

`HTTP_PROXY`·`HTTPS_PROXY`가 설정된 환경에서는 서버가 자기 도구 서버(`127.0.0.1`)를 부를 때 프록시가 가로채 막힐 수 있다. 실행 전에 `NO_PROXY=127.0.0.1`을 함께 설정한다.

포트는 `API_PORT`, `WEB_PORT`(외부 MCP는 `MCP_PORT`) 환경 변수로 바꾼다. 처음 실행하면 의존성을 설치한다(`uv sync`, `npm ci`).

### 폰에서 접속해 확인하기

폰의 마이크는 HTTPS 페이지에서만 열리므로 Tailscale의 tailnet 전용 HTTPS를 쓴다(공개 Funnel이 아니다).

1. 폰에도 Tailscale을 켜고 이 Mac과 같은 계정으로 로그인한다. Tailscale 관리 콘솔에서 MagicDNS와 HTTPS 인증서가 켜져 있어야 한다.
2. `./run.sh --phone`으로 실행한다. 개발 서버가 이 Mac의 tailnet 호스트 이름을 받도록 열리고, 아래 3·4번의 명령과 주소가 터미널에 나온다(Tailscale 설정은 바꾸지 않는다).
3. 다른 터미널에서 안내된 명령을 한 번 실행한다. 예: `tailscale serve --bg --https=8443 http://127.0.0.1:5173`(터미널에 나온 명령을 그대로 따른다. Tailscale 앱 번들만 있으면 명령 경로가 다르고, `WEB_PORT`를 바꿨다면 포트도 다르다). 이 Mac은 443을 외부 MCP의 Funnel이 이미 쓰고 있어 8443을 쓴다(8443 Serve와 443 Funnel이 함께 동작하는 것을 2026-11-08에 확인했다). 실행하기 전에 `tailscale serve status`로 8443이 이미 쓰이고 있는지 보고, 쓰이고 있으면 기존 설정을 덮어쓰지 않도록 `PHONE_HTTPS_PORT=10000 ./run.sh --phone`처럼 다른 포트를 고른다.
4. 폰 브라우저에서 `https://<이 Mac의 기기 이름>.<tailnet>.ts.net:8443`을 열고 마이크를 허용한다.
5. 끝나면 `tailscale serve --https=8443 off`로 끈다.

**폰에서 "사이트에 연결할 수 없습니다"가 나오면**: ① 443(포트 없는) 주소는 외부 MCP용 Funnel이라 브라우저로 열 주소가 아니다(404). 반드시 `:8443`을 붙인다. ② `run.sh`가 꺼져 있으면 Serve 뒤쪽이 비어 502가 난다. ③ Funnel이 켜져 있으면 이 호스트 이름이 공개 DNS에도 공개 IP로 등록되므로, 폰이 Tailscale DNS를 거치지 않고(Chrome "보안 DNS", Android "비공개 DNS"가 켜진 경우 등) 공개 IP로 풀면 8443에 닿지 못할 수 있다. 이때는 그 설정을 끄고 Tailscale 앱의 "Use Tailscale DNS settings"를 켠다. `https://<Tailscale IP>:8443`이 인증서 경고와 함께 열리면 경로는 정상이고 이름 해석 문제다. 이 Mac은 2026-11-08에 ①·②를 거쳐 폰에서 첨부와 대화가 정상 동작함을 확인했다(③은 가능성이며 어느 설정이 원인이었는지는 확인하지 않았다).

Tailscale이 없거나 로그인되어 있지 않거나 MagicDNS·HTTPS 인증서가 꺼져 있으면 `./run.sh --phone`이 이유를 알려 주고 멈춘다. 접속 주소 규약은 [client-contract.md](docs/client-contract.md) 1.2에 있다.

## Claude 앱 연결

음성 대화는 Claude 앱이 맡고, TrailTalk는 앱이 저장한 일지·노트를 웹 일지 화면에 보여 준다([docs/MCP/README.md](docs/MCP/README.md)).

1. `.env`에 `MCP_PUBLIC_URL`(Funnel로 공개할 `https://<기기 이름>.<tailnet>.ts.net`, 끝 슬래시·경로 없이)과 `MCP_OWNER_PASSWORD`(16자 이상)를 적는다(`.env.example` 참고, 값은 저장소에 두지 않는다).
2. `./run.sh`로 서버를 띄운다(`.env` 설정이 있으면 MCP 서버도 자동으로 뜬다). Tailscale Funnel(443)은 MCP 포트(8400)만 가리켜야 한다. `/api`·웹은 공개하지 않는다.
3. Claude 앱의 커넥터에 `MCP_PUBLIC_URL` + `/mcp`를 추가하고 소유자 비밀번호로 승인한다. 계정 지침은 [docs/MCP/account-instructions.md](docs/MCP/account-instructions.md)를 붙여 넣는다.
4. 연결을 모두 끊으려면 `./run.sh --mcp-revoke-all`(소유자 비밀번호를 바꾼 뒤에도 실행한다).

## 검증

```bash
scripts/verify.sh           # 전체 게이트(서버, 웹이 생긴 뒤에는 웹·빌드·E2E 포함)
scripts/verify.sh --quick   # 타입·린트·단위 테스트
git config core.hooksPath .githooks   # git 훅을 켠다(clone마다 한 번): 커밋·병합 뒤 전체 검증을 백그라운드로 시작하고, push 때 올라가는 커밋의 통과 기록을 확인한다
scripts/verify-bg.sh status           # 백그라운드 검증 상태(통과·진행 중·실패). 실패했으면 고친 뒤 새로 커밋하거나 `scripts/verify-bg.sh retry`
```

push 게이트는 `.githooks/pre-push`이고, Claude Code의 `.claude/hooks/gate-git.py`는 그 훅이 꺼져 있거나 `git push --no-verify` 같은 단순한 우회일 때 push를 막는 보조 장치다(서브셸·alias·다른 저장소 등은 못 막는다). GitHub Actions CI는 없다. 훅은 이 기기의 git 설정이라 훅을 켜지 않은 기기·`--no-verify`·GitHub 웹 편집은 검증을 거치지 않으니, 의심되면 새 폴더에 clone해 `VERIFY_NO_CACHE=1 scripts/verify.sh`를 돌린다. E2E 포트는 `E2E_API_PORT`·`E2E_WEB_PORT`·`E2E_MCP_PORT`(기본 8100·5174·8401, 백그라운드 검증은 8110·5184·8411)로 바꾼다.

서버만 따로: `(cd server && uv run pytest && uv run ruff check . && uv run ruff format --check .)`.
페르소나 톤 평가(실제 Claude CLI를 써서 구독 사용량이 든다): `(cd server && RUN_REAL_CLI=1 uv run python -m tests.persona_eval.run_eval)`. 리포트는 `docs/eval/`에 남는다.
일지 정리 평가(같은 사용량 주의): 추출 품질 `(cd server && RUN_REAL_CLI=1 uv run python -m tests.extract_eval.run_eval)`, 실제 글 대화 3개(다시 열기 포함) `(cd server && RUN_REAL_CLI=1 uv run python -m tests.journal_eval.run_journal)`. 둘 다 임시 데이터 격리 서버를 쓰고 리포트를 `docs/eval/`에 남긴다.
웹(`web/`): `npm ci` 뒤 `npm run typecheck`, `typecheck:core`, `lint`, `test`, `build`, `gen:api -- --check`(서버 API를 바꾸면 `npm run gen:api`로 `src/api/schema.d.ts`를 갱신), `e2e`(Playwright. 처음에는 `npx playwright install chromium`. 임시 폴더 `web/.e2e/`의 격리 서버 8100과 웹 5174를 자동으로 띄운다. 스크린샷 기준 이미지는 OS별(`e2e/__screenshots__/<OS>/`)이라 기준이 없는 OS에서는 시각 비교를 건너뛴다. 갱신은 `npm run e2e:update`로 하고 눈으로 확인한 뒤 커밋). 개발 서버는 `npm run dev`(`/api`를 `VITE_API_TARGET`, 기본 `http://127.0.0.1:8000`으로 넘긴다).
