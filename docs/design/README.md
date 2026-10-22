# 화면 시안

TrailTalk v2의 화면 시안(대화·일지·설정, 라이트·다크) 소스 사본이다. 정본은 아티팩트이고, 이 폴더는 구현할 때 마크업·스타일·문구를 저장소 안에서 참고하고 버전 이력에 남기기 위한 사본이다.

- 아티팩트(비공개, 소유자만 열람): https://claude.ai/artifact/UtHPgV1MqZRsLDEKyEZpaQ
- 화면 구성의 기준은 [Spec.md](../Spec.md) 8절이다. 시안과 다르면 Spec.md가 먼저이고 시안을 고친다.
- 마지막으로 맞춘 아티팩트 버전: `1792678056-d7a8` (2026-10-22, 라이트 호박색을 `#B26A00`→`#9C5C00`으로 어둡게 해 글자 대비 4.5:1 확보)

## 구성

캔버스(`canvas.json`)는 두 페이지로 나뉜다. 두 페이지의 보드 위치와 순서는 같다.

| 페이지 | 내용 |
|---|---|
| 페이지1 · 라이트 모드 | 대화 11장, 일지 8장, 설정 3장 |
| 페이지2 · 다크 모드 | 같은 22장의 다크 버전 |

모든 보드는 360 × 800이다. 하단 탭(대화·일지·설정)은 세 화면 영역 모두에 있다.

## 파일 ↔ 보드

| 보드 | 라이트 파일 | 다크 파일 |
|---|---|---|
| 대화 01 시작 (대기) | `Main.dc.html` | `DarkMain.dc.html` |
| 대화 02 듣기 | `Listening.dc.html` | `DarkListening.dc.html` |
| 대화 03 처리 중 · 맞장구 · 이어 말함 | `Processing.dc.html` | `DarkProcessing.dc.html` |
| 대화 04 말하기 · 노트 저장 | `Speaking.dc.html` | `DarkSpeaking.dc.html` |
| 대화 05 검색 중 | `Searching.dc.html` | `DarkSearching.dc.html` |
| 대화 06 쉬는 중 | `Paused.dc.html` | `DarkPaused.dc.html` |
| 대화 07 오프라인 보관 | `Offline.dc.html` | `DarkOffline.dc.html` |
| 대화 08 정리 · 끝남 | `Closing.dc.html` | `DarkClosing.dc.html` |
| 대화 09 글 대화 · 첨부 | `TextChat.dc.html` | `DarkTextChat.dc.html` |
| 대화 10 기초 (색·글자·상태) | `Foundations.dc.html` | `DarkFoundations.dc.html` |
| 대화 11 종료 확인 | `ConfirmEnd.dc.html` | `DarkConfirmEnd.dc.html` |
| 일지 01 목록 | `JList.dc.html` | `DJList.dc.html` |
| 일지 02 선택 · 삭제 확인 | `JSelect.dc.html` | `DJSelect.dc.html` |
| 일지 03 상세 · 요약 | `JDetail.dc.html` | `DJDetail.dc.html` |
| 일지 04 상세 · 노트 | `JNotes.dc.html` | `DJNotes.dc.html` |
| 일지 05 상세 · 전문 | `JTranscript.dc.html` | `DJTranscript.dc.html` |
| 일지 06 정리 중 | `JPending.dc.html` | `DJPending.dc.html` |
| 일지 07 정리 실패 | `JFailed.dc.html` | `DJFailed.dc.html` |
| 일지 08 제목 수정 | `JTitle.dc.html` | `DJTitle.dc.html` |
| 설정 01 내 정보 | `Settings1.dc.html` | `DarkSettings1.dc.html` |
| 설정 02 음성 · 대화 모델 | `Settings2.dc.html` | `DarkSettings2.dc.html` |
| 설정 03 보관 · 화면 · 앱 | `Settings3.dc.html` | `DarkSettings3.dc.html` |

## 디자인 요약

대화 화면 구조는 위에서부터 헤더(제니 이름·상태, 오른쪽에 남은 토큰 막대), 말풍선 영역, 아래 조작 영역(맨 위에 "음성으로/글로" 선택 버튼, 그 아래 큰 버튼과 일시 중단·대화종료 보조 버튼), 하단 탭이다. 글 대화(대화 09)는 조작 영역 대신 여러 줄 입력창과 대화종료 버튼이 있다.

| 항목 | 라이트 | 다크 |
|---|---|---|
| 바탕 / 카드 | `#F3F0E8` / 흰색(소스에서는 `#fff`) | `#0D1612` / `#17241D` |
| 글자 / 보조 글자 | `#16241D` / `#4A5A52` | `#EDEAE0` / `#A9B7AE` |
| 주색(듣기·내 말풍선·주 버튼) | `#1D5B43` | 버튼 `#4FB58D`, 내 말풍선 `#2B7A5A` |
| 처리 중·검색 | 호박 `#9C5C00` (바탕 위 4.67:1, 카드 위 5.32:1) | `#E3A23B` |
| 오프라인·삭제 | 벽돌 `#8A2615` | 노을 `#E8806B` |
| 글꼴 | Noto Sans KR 400/500/700. 제목 20~24px, 본문·말풍선 16px, 버튼·카드 문구 15px, 보조 13px, 가장 작게 11~12px | 같음 |
| 크기 | 큰 버튼 80px, 보조 버튼 48px(터치 영역 44px 이상), 선택 버튼 높이 44px, 헤더 60px, 하단 탭 64px | 같음 |

상태는 색만으로 구분하지 않고 아이콘·모양·문구를 함께 쓴다(대화 10 기초 화면에 7가지 상태가 정리돼 있다).

## 형식과 주의

- 소스는 아티팩트 전용 형식(`.dc.html`, Design Component)이다. `<script src="./support.js">`는 아티팩트가 제공하는 파일이라 저장소에는 없고, 이 파일을 브라우저에서 바로 열면 화면이 나오지 않을 수 있다. 마크업·스타일·문구를 읽어서 쓰는 용도다.
- 시안의 보이스 이름(nova 등), 일지 제목, 날짜, 이메일(`daniel@example.com`)은 예시이다. 실제 값은 서버가 준다.
- 렌더링은 아티팩트에서 확인한다. 이 폴더의 파일은 렌더링을 검증하지 않았다.

## 고치는 방법

1. 아티팩트가 정본이므로 먼저 아티팩트를 고친다.
2. 같은 커밋에서 이 폴더를 다시 맞춘다(아티팩트의 `project/` 파일을 받아 덮어쓰고, 위 "마지막으로 맞춘 버전"을 갱신).
3. 화면 구성이 바뀌면 Spec.md 8절과 [client-contract.md](../client-contract.md)도 함께 확인한다.
