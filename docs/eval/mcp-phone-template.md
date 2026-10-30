# Claude 앱 MCP 폰 실측 보고서 (양식)

실행 날짜 · 기기 · 앱 버전 · 네트워크(셀룰러/Wi-Fi)를 적고, 아래 표의 통과/실패를 채운다. 실패는 원인과 조치(재시도·설명 수정·보류)를 정한다. 사전 조건은 [implementation-plan.md](../MCP/implementation-plan.md) MA-12와 [account-instructions.md](../MCP/account-instructions.md)(앱 입력란과 일치)다.

| # | 시나리오(음성) | 기대 | 결과(통과/실패) | 메모·원인·조치 |
|---|---|---|---|---|
| 1 | 커넥터 추가(URL = 공개 주소 + /mcp)와 OAuth 로그인(소유자 비밀번호) | 연결 성공, 도구 13개 보임 | | |
| 2 | "제니야" → 첫 호출 | get_memory가 불려 호칭·지난 일지·열린 아이디어 | | 첫 호출 지연 로딩 실패 시 재시도로 성공하는지 |
| 3 | "저장된 아이디어를 목록으로 보여 줘" | list_notes(kind=idea)를 말로 읽음 | | |
| 4 | "이거 저장해줘" | save_note 후 복창 | | 앱 메모 세션에 모임 |
| 5 | "아까 말한 ○○ 별표 해 줘" | list_notes → update_note(starred) | | 웹에서 ★ 확인 |
| 6 | "지난주에 ○○ 얘기했었지?" | search_conversations 또는 list_journals | | |
| 7 | "오늘은 여기까지" | save_journal 후 마무리 말 | | 웹 일지 목록에 보임 |
| 8 | "그 일지 지워 줘" | 미리보기 → 사용자 확인 → 확정, 앱 출처만 | | 웹 일지는 거절 |
| 9 | "앞으로 ○○라고 불러줘" | set_nickname, 다음 대화 get_memory에 반영 | | |
| 10 | 서버를 끄고 호출 | 커넥터 502/연결 오류 안내 | | |

판정(MS-01~03)은 사용자가 확인한다.
