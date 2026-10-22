# TrailTalk v2

- 의도: [docs/Intent.md](docs/Intent.md)
- 명세: [docs/Spec.md](docs/Spec.md) — 마일스톤은 12절(M0~M6)
- 규약: [docs/client-contract.md](docs/client-contract.md) — API·SSE·상태 머신·오류 코드의 정본
- 화면 시안: [docs/design/README.md](docs/design/README.md) — 아티팩트 링크와 소스 사본(`docs/design/*.dc.html`). 시안을 고치면 같은 커밋에서 이 폴더도 맞춘다.
- v1 소스(참고용): `~/pythonProject/TrailTalk/`

위 문서는 자동으로 불러오지 않는다(`@` import 금지). 필요한 절만 `grep -n "^#"`으로 위치를 찾아 범위를 지정해 읽는다.

## 작업 규칙

- 자동 커밋/푸시 허용(2026-10-22 사용자 확정). 묻지 않고 커밋하고 푸시한다. 단, 매번 커밋·푸시 전에 독립 general-purpose 서브에이전트로 diff 리뷰를 하고 지적을 반영한다. 저장소는 `main` 브랜치로 초기화했다. 원격은 GitHub 계정 kangsuek의 저장소이며, 저장소 이름과 공개 여부가 정해져 원격이 설정된 뒤부터 푸시한다(그 전에는 커밋만 한다).
- 웹 앱(PWA)이므로 실제 동작 검증은 Playwright로 브라우저(Chromium)를 띄워 한다. 단위 테스트만으로 끝내지 않는다. 가짜 마이크는 `--use-fake-device-for-media-stream`과 wav 파일을 쓴다.
- 화면 캡처도 Playwright 브라우저로 한다. OS 좌표 자동화(osascript)는 쓰지 않는다.
- 검증용 서버를 띄울 때는 DB, 첨부, 오디오, CLI 작업 폴더를 모두 임시 경로로 바꾼다(서버 시작 때 `purge_orphans`가 DB에 없는 첨부를 지운다). 사용자의 실제 서버(포트 8000)와 DB는 건드리지 않는다. 실제 Claude CLI와 OpenAI 호출은 사용량과 과금이 있으니 필요할 때만 쓰고 알린다.
- 캐릭터 이름·성격·말투·보이스·안내 문구는 코드가 아닌 `server/personas/*.yaml`에만 둔다.
- 마일스톤 하나를 구현·검증하고 사용자 확인을 받은 뒤 다음으로 넘어간다.
