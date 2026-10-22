# 클라이언트 규약

웹 앱(PWA)이 지키는 서버·클라이언트 규약의 정본이다. 요구사항과 동작 설명은 [Spec.md](Spec.md)가 기준이고, 이 문서는 그것을 필드·순서·오류 코드 수준으로 내린 것이다. v1 `client-contract.md`를 옮기면서 Spec.md에서 확정한 v2 변경을 반영했다(`[v2]` 표시).

웹 앱은 이 문서, 서버가 내는 OpenAPI 스키마, 상태 전이 표(`shared/fixtures/transitions.json`), 클라이언트 설정값(`shared/client-defaults.json`)을 기준으로 만든다.

## 0. 바꾸는 규칙

- 규약을 바꾸면 같은 커밋에서 이 문서, 서버 스키마(`npm run gen:api`로 웹 타입 갱신), 전이 표를 함께 고친다.
- 서버가 새 이벤트·필드를 먼저 더할 수 있으므로 클라이언트는 모르는 이벤트 `type`, 필드, `summary.kind`를 무시한다(앱이 멈추지 않게).
- 한도·기본값의 정본은 서버다. 클라이언트는 `GET /api/profile`의 `client`로 받아 쓴다.

### v2 변경 요약

| 변경 | 위치 |
|---|---|
| 변경성 요청에 `X-TrailTalk: 1` 헤더와 Origin 검사(CSRF 방어), 거절 코드 `csrf_rejected` | 1.5, 9 |
| SSE `sentence.speech_text`: 합성이 실패해 `audio`가 `null`일 때만 실린다 | 2.4 |
| 병합: `done.superseded`, 사용자 턴 `merged_from`, 앞 턴이 첫 문장을 내기 전 뒷말은 큐에 넣지 않고 바로 보낸다 | 2.8, 3.2, 6 |
| 지연 보고에 `ack_ms`, 서버 기록에 `tts_model`과 첫 문장 단계(`first_queued_ms`·`first_synth_ms`·`synth_wait_ms`), 요약에 맞장구·검색·합성 폴백 지표, 맞장구 설정(`client.turn`, 프로필 `ack_enabled`), 맞장구 소리(`persona.ack`) | 2.2, 2.15, 4.1, 6.4, 7 |
| 일지 목록은 날짜별 최신순만: `topics`, 정렬, 보기 전환 제거(키워드 검색 `q`는 P2). 진행 중(`active`) 대화도 목록에 나온다 | 3.1 |
| 일지 상세의 화자 이름은 현재 프로필이 아니라 그 세션의 페르소나(`persona_name`) | 3.2 |
| 호칭은 세션 첫 인사에서만 쓴다(변경을 알리는 답변에서만 새 호칭을 한 번 말해도 된다). 변경은 다음 세션의 첫 인사부터. 세션 준비(prepare)가 호칭을 더는 보지 않는다 | 2.1, 2.2, 4.1 |
| 종료는 화면의 "대화종료" 버튼(확인 창 포함). 큰 버튼 길게 누르기는 확인 없는 보조 수단 | 6.3 |
| 남은 토큰 막대는 헤더 오른쪽(시작 화면과 같은 위치), "새 버전 적용" 버튼은 설정 화면 | 1.3, 1.4 |
| 오프라인 안내 문구는 페르소나 YAML에서 나온다(`client.offline_notice`를 서버가 채운다) | 7, 8 |
| v1의 `barge_in_event` API(`POST /api/barge-in-events`)와 `window.__tt_metrics` 훅은 이식하지 않는다 | — |

## 1. API 공통

### 1.1 경로와 타입

- 모든 서버 API는 `/api` 아래에 둔다(예: `/api/health`, `/api/sessions`).
- `GET /api/health`: DB에 닿으면 200 `{"status":"ok","db":"ok"}`, 닿지 않으면 503 `db_unavailable`(9절 형식). CSRF 검사와 인증이 없다.
- 타입은 FastAPI OpenAPI 스키마에서 생성한다. 서버 `python -m app.openapi`, 웹 openapi-typescript(`npm run gen:api` → `web/src/api/schema.d.ts`).
- 턴 SSE는 POST 응답이라 `EventSource` 대신 스트림을 직접 읽는다. 파서는 `web/src/core/sse.ts`다. 줄 끝은 `\r\n`·`\r`·`\n`만 인정하고, 빈 줄로 끝나지 않은 마지막 메시지는 버린다.

### 1.2 폰 접속

서버는 집 Mac에서 돌고, 폰은 Tailscale Serve가 tailnet 안에만 여는 HTTPS 주소(`https://<Mac 기기 이름>.<tailnet>.ts.net/`)로 접속한다. 브라우저 마이크는 HTTPS(또는 localhost)에서만 열린다. 서버 API에는 로그인이 없으므로 공개 주소(Funnel)로 열지 않는다. 앱 도구 경로 `/internal/*`은 프록시를 거친 요청을 403으로 막는다.

### 1.3 Claude 남은 토큰

`GET /api/usage` → `{status, five_hour, seven_day, updated_at}`.

- 한도는 `{utilization, resets_at}`(쓴 비율 0~1, 초기화 시각) 또는 `null`이다. 서버는 CLI가 답변마다 알려 주는 구독 한도(`rate_limit_event`)의 마지막 값을 메모리에 두므로, 서버를 켠 뒤 첫 답변 전에는 모두 `null`이다.
- `status`는 `allowed`·`allowed_warning`·`rejected`다.
- 클라이언트는 두 한도 중 덜 남은 쪽을 "남은 %·N시간 뒤 초기화"로 보인다(초기화 시각이 지난 한도는 100%). 위치는 **헤더 오른쪽**이고 시작 화면과 대화 화면이 같다. 서버 연결 확인(`GET /api/health`)과 함께 30초마다, 화면이 다시 보일 때 다시 불러온다. 계산은 `web/src/core/usage.ts`다.
- 오프라인이면 "확인 불가"로 보인다.

### 1.4 PWA

서비스 워커는 앱 셸만 미리 저장하고, 음성 감지 자산(`/vad/<vad-web 버전>-<onnxruntime 버전>/`)은 처음 쓸 때 저장한다. `/api`·`/internal`은 다루지 않아 SSE와 업로드는 늘 네트워크로 간다. 새 버전은 자동으로 새로 고치지 않고 설정 화면의 "새 버전 적용" 버튼으로 바꾼다(대화 중 페이지가 다시 열리지 않게).

### 1.5 변경성 요청 보안 `[v2]`

POST·PUT·PATCH·DELETE 요청은 다음을 모두 지켜야 서버가 처리한다. 하나라도 어기면 403 `csrf_rejected`다.

1. 헤더 `X-TrailTalk: 1`을 보낸다. 교차 출처 요청에 CORS 사전 요청을 강제하는 주된 방어선이다. 오디오 업로드처럼 본문이 바이트인 요청도 보낸다.
2. `Origin`이 있으면 허용 목록(`ALLOWED_ORIGINS`: 서버 자신의 Tailscale 주소, `127.0.0.1:8000`, 개발 중에는 `localhost:5173`)에 있어야 한다. `Origin`이 없는 요청은 1번을 만족하면 받는다.
3. 본문이 있는 요청은 `Content-Type`이 `application/json`·`multipart/form-data`·`audio/*` 중 하나여야 한다. 서버가 지원하지 않는 오디오 형식이라도 `audio/*`면 이 검사는 통과하고 서버가 `audio_invalid`로 처리한다. 그 밖의 형식은 `csrf_rejected`다. 본문 없는 요청에는 적용하지 않는다.

면제: `/internal/*`(루프백만, 프록시 경유는 403). CORS는 열지 않는다. `GET` 요청과 `<img>`가 읽는 `GET /api/attachments/{id}`에는 헤더를 요구하지 않는다.

## 2. 세션과 턴

### 2.1 시작 준비

대화 화면이 "시작 전"이나 "끝남" 상태가 되면 `POST /api/sessions/prepare {mode}` → 204를 보낸다. 서버가 다음 대화의 CLI를 미리 띄워 인사말 대기를 약 1.4초 줄인다.

- 대화 탭이 보일 때만 보내고, 화면이 열려 있는 동안 4분마다 다시 보낸다. 결과를 기다리지 않고 실패는 무시한다.
- 같은 조건이면 여러 번 불러도 하나만 준비된다. 준비된 지 5분이 지나면 다음 요청 때 새 시각으로 다시 띄우고, 쓰지 않으면 닫힌다.
- 준비 뒤 프롬프트(관심사·페르소나 등)나 날짜·오전/오후가 바뀌면 시작할 때 새로 띄운다. `[v2]` 호칭은 프롬프트에 들어가지 않고 인사말을 만들 때만 붙으므로 호칭이 바뀌어도 다시 띄우지 않는다.

### 2.2 세션 시작

`POST /api/sessions {mode: "text"|"voice"}` → 201 `{session, greeting: {turn_id, text, audio}, persona: {id, name, ack: [{text, audio}]}}`.

- `greeting.audio`는 인사말 MP3(base64)로 음성 세션에서만 오고, 합성에 실패하면 `null`이어도 세션은 시작된다.
- 화면의 캐릭터 이름은 `persona.name`을 쓰고 코드에 넣지 않는다(NFR-08).
- `[v2]` `persona.ack`은 맞장구 소리 목록이다(페르소나 YAML의 짧은 문구와 그 MP3(base64), 음성 세션에서만 `audio`가 오고 합성 실패면 `null`). 클라이언트는 이 중 하나를 골라 맞장구로 재생한다(6.4). 맞장구를 끈 사용자도 목록은 받는다.
- `[v2]` **호칭은 이 인사말에서만 쓰인다.** 서버는 인사말을 만들 때만 프로필의 호칭을 넣고, 이후 답변·재개 인사말·마무리 멘트에는 쓰지 않는다. 예외로 사용자가 호칭 변경을 요청해 `set_nickname`이 불린 턴에서만, 변경을 알리는 답변에서 새 호칭을 한 번 말해도 된다.
- 음성 세션과 글 세션의 `mode`는 시작 방식이며, 텍스트 세션에서도 음성 턴을, 음성 세션에서도 글 턴을 보낼 수 있다.

### 2.3 글 턴

`POST /api/sessions/{id}/turns {text}`(1~4000자) → 2.4의 SSE.

### 2.4 SSE 이벤트

턴 요청의 응답은 `text/event-stream`이다. 메시지마다 `event: <type>` 줄과 `data: <한 줄 JSON>` 줄, 빈 줄로 이뤄지고 JSON에도 `type`이 들어 있다. 스키마는 OpenAPI components(`StreamEvent`, 서버 `app/api/events.py`)가 기준이다.

| type | 필드 | 의미 |
|---|---|---|
| `transcript` | `text` | 음성 턴에서만 `turn` 바로 앞에 오는 첫 이벤트. 인식한 글(사용자 메시지로 저장된 글) |
| `turn` | `turn_id` | 스트림의 첫 이벤트(음성 턴은 `transcript` 다음). 이번 답변(assistant 턴)의 ID. 끼어들기에 쓴다 |
| `sentence` | `index`, `text`, `audio`, `speech_text` | 답변 한 문장. `index`는 턴 안에서 0부터. `audio`는 그 문장의 MP3(base64)로, 음성 세션에서만 오고 텍스트 세션이거나 합성 실패면 `null`이다. `text`는 화면에 보이는 원문(클라이언트는 이 글자를 보인다)이다. `[v2]` `speech_text`는 키가 항상 있고, `audio`가 있으면 `null`이다. `audio`가 `null`인 음성 문장에서만 값이 오며 기기 TTS가 읽을 글(마크다운·링크를 지우고 숫자를 읽기 쉽게 바꾼 것)이다. 텍스트 세션에서는 읽지 않는다 |
| `tool` | `phase`(`start`/`call`/`end`), `tool_use_id`, `name`, `input`, `summary`, `is_error`, `notice` | 도구 사용. `start`에는 이름만 온다(검색 중 표시용). `input`은 `call`에서만, `summary`·`is_error`는 `end`에서만 의미가 있고 나머지 단계에서는 `null`/`false`. `notice`(`{text, audio}`)는 음성 세션에서 캐릭터가 말없이 `web_search`·`web_fetch`를 시작할 때만 `start`에 실리는 안내 음성(턴마다 한 번)이다. 답변 문장이 아니라 `index`·`done.text`에 들어가지 않으며, 클라이언트는 문장처럼 재생 대기열에 넣는다 |
| `done` | `turn_id`, `text`, `interrupted`, `session_status`(`active`/`paused`/`ended`), `superseded` | 턴 끝. `turn_id`는 `turn` 이벤트와 같다. 전체 답변과 세션 상태. `[v2]` `superseded`가 `true`면 이 턴이 병합 때문에 대체된 것이고, 이때 `text`는 빈 문자열, `interrupted`는 `false`, `session_status`는 `active`다(2.8) |
| `error` | `code`, `message` | 스트림 도중 오류. 코드는 9절과 같다. 이 뒤에는 이벤트가 오지 않는다 |

모든 필드는 항상 실려 온다(스키마상 required). 시작 전 오류는 SSE가 아니라 9절의 JSON 오류로 온다.

**순서**: 한 턴은 `turn`으로 시작해(음성 턴은 그 앞에 `transcript`) `sentence`·`tool`이 섞여 오다가 `done` 또는 `error` 하나로 끝난다.

### 2.5 도구 이름

`name`은 다음 중 하나이거나, `[v2]` 외부 MCP 도구(M5)의 `mcp__<서버>__<도구>`다: `send_email`, `save_note`, `search_notes`, `search_conversations`(지난 대화 전체의 주고받은 말 찾기), `summarize_session`, `pause_session`, `end_session`, `set_nickname`, `set_model`, `web_search`, `web_fetch`.

`web_search`는 내장 웹 검색이거나 검색 API 도구 `search_USA`(해외·영어권)·`search_naver`(국내 뉴스)다. 서버가 이들을 같은 이름·같은 `web_search` 요약으로 보내므로 클라이언트는 구분하지 않는다. 음성 대화에서 `search_conversations`를 말없이 시작하면 `web_search`처럼 안내 음성 `notice`가 붙는다.

`[v2]` 외부 MCP 도구(M5)는 `name`에 접두사를 포함한 전체 이름이 온다(자체 도구는 서버가 `mcp__trailtalk__` 접두사를 떼고 위 목록의 이름으로 보내므로 접두사가 있는 이름은 외부 도구다). 화면은 서버 이름을 보이지 않고 "`<도구>` 사용 중"으로 보인다. 외부 도구의 `input`은 `null`이다. M5 스파이크 전까지 `end`의 `summary`는 `result` kind(결과 문자열, 서버가 2000자로 자름)이고, 스파이크에서 `web_search` 요약으로 바꾸기로 하면 이 문단을 고친다. 클라이언트는 모르는 이름도 이벤트를 버리지 않는다.

### 2.6 도구 결과 요약

`summary`는 `end`에서만 오며 `kind`로 종류를 구분한다(OpenAPI `WebSearchSummary`·`WebFetchSummary`·`ToolResultSummary`). 결과 형식을 알 수 없거나 모르는 `kind`는 `null`처럼 다루고 이벤트를 버리지 않는다. 화면의 출처 표시는 서버가 준 호스트 이름을 그대로 쓴다(클라이언트는 URL을 해석하지 않는다).

| `kind` | 필드 | 의미 |
|---|---|---|
| `web_search` | `query`, `links: [{title, url}]`(최대 10개), `sources: [호스트]` | 검색어와 결과 링크. `sources`는 링크의 호스트 이름(`www.` 뗌, 중복 없이 링크 순서로 최대 3개)이다. 비어 있으면 화면은 "검색 완료" |
| `web_fetch` | `code`, `bytes`, `url`, `host` | 읽은 페이지의 HTTP 상태·크기·주소와 출처 호스트. `code`가 400 이상이면 읽지 못한 것으로 본다 |
| `result` | `result` | 앱 도구(`save_note` 등)가 돌려준 값(보통 한 줄 문자열) |

### 2.7 음성 턴

`POST /api/sessions/{id}/turns/audio`. 본문은 말 한 번의 오디오 바이트 그대로(multipart 아님)이고 `Content-Type`은 녹음 형식(웹 `audio/webm`, 5절)이다 → 2.4의 SSE(`transcript` → `turn` → …).

- 서버는 SSE를 열기 전에 인식하므로 오디오·인식 오류와 말 없음은 JSON 오류다: `audio_invalid`(400, 너무 크면 413), `no_speech`(422), `stt_failed`·`stt_timeout`·`voice_unavailable`. 이 오류들은 사용자 메시지를 만들지 않는다(상태 머신에는 `turn_error {turnId: null}`).
- 인식 뒤 스트림을 열 때 다른 턴이 진행 중이거나 세션이 끝났으면 `transcript` 없이 `error`(`turn_in_progress`·`session_ended`)가 첫 이벤트로 온다(인식한 글은 저장되지 않는다). 단, 음성 턴이 병합 조건(2.8)이면 `turn_in_progress` 대신 앞 턴을 대체한다. 병합 여부를 알리는 표식은 요청에 없다. 서버는 상태만 보고 판단한다.

### 2.8 병합: 쉬며 이어 말한 뒷말 `[v2]`

쉬며 이어 말한 뒷말이 앞말과 따로 처리되면 앞말에만 답한다. 서버는 다음 조건에서 앞 턴을 대체해 합친 한 번의 답을 만든다.

**역할 분담**: 서버는 요청이 왔을 때의 상태(같은 세션의 앞 턴이 처리 중이고 **첫 답변 문장(`sentence`)이 아직 클라이언트에 나가지 않았음**)와 음성 턴 여부만 보고 병합한다. 길이·큐·글 턴 같은 나머지 조건은 모두 **클라이언트 책임**이며, 조건을 만족할 때만 뒷말을 큐에 넣지 않고 일반 음성 턴처럼 바로 보낸다(v1은 큐에 넣어 앞 답변이 끝난 뒤 보냈다). 요청에 병합 표식은 없다.

- **클라이언트가 바로 보내는 조건**(모두 만족): 앞 턴이 음성 턴이고 첫 문장이 아직 재생 대기열에 없다, 검색 안내(`tool.notice`)가 아직 나오지 않았다(나왔으면 병합이 진행 중인 검색을 버리므로 큐 규칙을 따른다), 오프라인 큐가 비어 있다, 뒷말이 음성 턴이고 실제 음성 길이가 `merge_min_speech_ms`(7절) 이상이다.
- **서버 동작**: 앞 턴 생성을 취소하고 앞 턴 스트림을 `done {turn_id: 앞 턴의 turn 이벤트 ID, text: "", interrupted: false, session_status: "active", superseded: true}`로 닫는다. CLI에는 "직전 말에 이어서 말함" 안내와 함께 앞말·뒷말을 합친 텍스트를 보내 **한 번만 답하게** 한다. 앞말에서 이미 호출된 도구(`save_note` 등)는 되돌리지 않으며, 중복 노트는 일지 추출의 중복 제거에 맡긴다. 취소된 앞 턴의 답변은 저장하지 않는다(첫 문장 전이라 기록이 없다).
- **경쟁 상태**: 클라이언트는 첫 문장이 아직 안 왔다고 보고 바로 보냈는데 서버는 이미 첫 문장을 내보낸 경우, 서버는 병합하지 않고 2.7대로 `transcript` 없이 `turn_in_progress`를 보낸다(인식한 글은 저장되지 않는다). 클라이언트는 이 오류를 받으면 그 말을 `queueUtterance`로 큐에 되돌린다(유실 방지).
- **기록**: 즉시 기록 원칙에 따라 사용자 턴은 행마다 남고 오디오도 각각 보관한다. 뒷말 행의 `merged_from`이 바로 앞 사용자 턴 ID를 가리킨다(일지 상세 `turns[]`에 실린다, 3.2). 뒷말이 또 병합 조건을 만족하면 다시 병합하며 `merged_from`이 이어지는 체인이 된다. 화면과 전문은 `merged_from`으로 이어진 모든 행을 한 말풍선으로 보인다.
- **클라이언트 동작**: 병합은 클라이언트가 뒷말을 바로 보낸 결정에서 시작하므로, 라이브 화면에서는 두 말풍선을 클라이언트가 직접 한 말풍선으로 합친다. `done.superseded`는 `turn_done`으로 머신에 보내지 않고 앞 `sendTurn`을 상태 변화 없이 끝낸다. 이 `done`은 뒷말의 `turn` 이벤트보다 먼저 도착할 수 있고, 그때 머신의 현재 턴 ID는 아직 앞 턴이므로 6.6의 "다른 ID는 무시" 규칙에 기대지 않는다.
- **맞장구**: 병합된 요청도 새 턴이므로 `ack_due`가 다시 걸리지만, 앞 턴에서 맞장구를 이미 재생했다면 다시 재생하지 않는다(턴 체인마다 한 번).
- **병합하지 않는 경우**: 위 조건 중 하나라도 어긋나는 모든 경우(첫 문장이 이미 나감, 글 입력 턴, 검색 안내 재생 뒤, 길이 미달, 오프라인 큐가 있음). 이때는 일반 끼어들기·큐 규칙(6절)을 따른다.
- **한계**: 뒷말이 서버에 닿는 시각이 앞 턴의 첫 문장보다 늦으면(쉬는 시간이 약 4초 이상이면) 대개 병합되지 않는다. 병합을 위해 첫 문장을 늦추는 대기 창은 두지 않는다.

### 2.9 종료

`POST /api/sessions/{id}/end` → `{session, closing, closing_audio, saved: {idea, todo, memo}, journal_status}`.

- 여러 번 불러도 같다. `closing_audio`는 마무리 멘트 MP3(base64)로 음성 세션에서만 오고 실패하면 `null`이다. 마무리 멘트에는 호칭을 쓰지 않는다.
- 서버는 세션을 끝내고 일지 정리(추출)를 띄운 뒤 **최대 45초** 기다려, 이 대화에서 저장한 노트 개수로 만든 마무리 멘트(`closing`, 캐릭터 말풍선)를 준다. `journal_status`가 `pending`이면 정리가 끝나지 않은 것이다(개수가 나중에 늘 수 있다). 기다리는 동안 클라이언트는 정리 중 안내와 "그만 기다리기"를 보인다.
- 끝내기 도구로 턴이 끝나 대화가 끝났을 때(`done`의 `session_status: ended`, 또는 `turn` 뒤 `session_ended` 오류)도 클라이언트는 이어서 이 API를 불러 마무리 멘트를 받는다.
- `saved`는 다시 연 뒤 생긴 노트만 센다.

### 2.10 쉬기·무발화·저장 보장

- 쉬기(`paused`) 상태에서 턴을 보내면 다시 `active`가 된다.
- 마지막 발화 뒤 30분 동안 말이 없으면(쉬는 중 포함) 서버가 세션을 끝내고 일지를 정리한다(클라이언트 타이머의 안전망). 그 뒤 턴 요청은 `session_ended`다. 무발화로 끝난 세션의 `ended_at`은 마지막 발화 시각이다.
- 서버는 사용자 메시지를 받자마자, 답변은 `sentence`를 보내기 전에 문장마다 저장한다. 그래서 턴 도중 연결이 끊기거나 오류가 나거나 서버가 죽어도 사용자 메시지와 클라이언트가 받은 문장은 모두 기록되고(보내려던 문장이 하나 더 남을 수 있다), 그 답변은 끊긴 답변(`interrupted`)으로 남는다. 첫 문장 전에 끊기면 사용자 메시지만 남는다.
- 쉬기·끝내기 도구가 불린 뒤 턴이 오류나 연결 끊김으로 끝나도 그 요청은 반영된다.
- 턴 요청이 `session_ended`·`session_not_found`로 실패하면(시작 전 JSON 오류든 SSE `error` 이벤트든) 클라이언트는 대화를 끝난 상태로 바꾼다. 끝내기 요청 뒤 턴이 오류로 끝나거나 턴 도중 다른 곳(끝내기 API·무발화 감시)이 세션을 끝내면 서버는 `error`를 `session_ended`("대화를 마쳤어요.")로 보낸다.
- `turn` 이벤트 전에 온 `error`는 서버가 사용자 메시지를 받지 못한 것이므로 클라이언트는 그 메시지를 목록에서 빼고 입력창으로 되돌린다.

### 2.11 다시 열기

`POST /api/sessions/{id}/reopen {mode}` → 200 `{session, greeting: {turn_id, text, audio}, persona, turns: [턴]}`.

- 끝난 대화를 같은 세션으로 다시 열어 이어서 대화한다(일지 상세의 "글로 이어서"·"음성으로 이어서"). 끝나지 않은 대화(대화 화면을 닫았거나 다른 기기에서 남은 대화)도 같은 요청으로 이어받는다: 서버는 지금 CLI를 닫고 끝난 대화처럼 새로 띄운다(실패하면 원래 진행 중 상태로 남는다). `mode`는 이번에 쓸 방식이며 처음과 달라도 된다.
- 서버는 저장된 전문을 새 프롬프트에 넣어 캐릭터를 다시 띄운다(일지 정리가 끝났고 전문이 길면 앞부분은 정리(제목·요약·확인할 것·노트)로 대신하고 최근 원문 약 4천 자만 넣는다). 직전 이야기를 짚는 **재개 인사말**(`greeting`, 음성이면 `audio`)을 전문 끝에 새 턴으로 남긴다. 재개 인사말에는 호칭을 쓰지 않는다. 재개 인사말 턴은 첫 인사말처럼 끼어들어도 잘리지 않는다.
- `turns`는 그 인사말까지 포함한 전체 전문(일지 상세의 `turns`와 같은 형식)이라 클라이언트는 이것으로 이전 말풍선을 채운다.
- 다시 연 동안 일지는 진행 중(`status: active`, `journal_status: null`)으로 보이고, 돌던 일지 정리는 멈춘다. 다시 끝내면 일지를 새로 정리한다: 요약·태그·확인할 것은 전문 전체로 새로 쓰고, 노트는 지우지 않으며(별표·완료·고친 내용 유지) 새 노트만 더하고, 고친 제목은 유지된다. 일지 날짜(`date`, `started_at`)는 처음 시작한 날 그대로다.
- 오류: 답변을 만드는 중이면 409 `turn_in_progress`, 없으면 404 `session_not_found`, 재개 인사말을 받지 못하면 시작 실패와 같은 오류이고 대화는 원래 상태로 남는다.
- 다른 대화가 진행 중일 때 다시 열면 서버는 막지 않으므로 **클라이언트가 막는다**(진행 중인 대화를 끝낸 뒤 이어서 할 수 있다고 안내). 일지 상세에서 이 화면이 지금 진행 중인 대화는 다시 열지 않고 대화 화면으로 돌아가며, 열려 있지 않은 진행 중 대화에는 이어서 버튼과 "대화 끝내기"(끝내기 API, 끝내야 지울 수 있다)를 보인다.

### 2.12 끼어들기

`POST /api/sessions/{id}/turns/{turn_id}/cancel {last_played}` → 204.

- `last_played`는 끝까지 들려준 마지막 문장 번호(`sentence.index`)이고 하나도 못 들려줬으면 -1이다.
- 서버는 그 턴이 진행 중이면 CLI를 인터럽트하고(남은 합성은 버린다) 턴이 끝나기를 최대 10초 기다린 뒤, 답변 기록을 `last_played`번 문장까지로 자르고 `interrupted`로 표시한다. 끝난 턴(다 받은 뒤 재생 중 끊기)도 같게 자른다. 다 들었으면(마지막 문장 번호 이상) 바꾸지 않는다. 여러 번 불러도 같다. 인사말(seq 0)은 문장 번호 없이 재생되므로 자르지 않는다.
- 자른 경우 다음 턴에 CLI에만 "직전 답변을 어디까지 들었는지" 안내를 붙인다(기록에는 남지 않는다).
- 오류: 없는 세션 404 `session_not_found`, 이 대화의 캐릭터 답변이 아니면 404 `turn_not_found`. 첫 문장 전에 연결이 끊겨 답변 기록이 아직 없는 턴도 `turn_not_found`일 수 있으며 클라이언트는 이 결과를 무시한다.
- 클라이언트는 cancel과 함께 턴 스트림도 끊는다(계속 읽으면 `done.text`는 자르기 전 전체 답변이다). 자르기와 다음 턴 안내는 턴 락 안에서 하므로 그 짧은 동안 새 턴이 `turn_in_progress`가 될 수 있다. 진행 중인 턴이 10초 안에 멈추지 않으면 자르지 않는다.

### 2.13 파일 첨부

`POST /api/sessions/{id}/turns/files`, `multipart/form-data`(`text` 1~4000자 필수, `files` 1~3개) → 2.4의 SSE.

- 글 대화(`mode=text`)에서만 받고 음성 세션은 400 `attachment_invalid`다.
- 이미지(png·jpg·webp·gif), 텍스트(txt·md·csv·json), PDF만 된다. 서버는 이미지를 열어 EXIF 회전을 적용한 뒤 긴 변 1024px 이하 PNG(알파)·JPEG로 다시 인코딩하고 EXIF를 제거한다(GIF는 첫 프레임, 320px 썸네일을 함께 저장). 텍스트는 UTF-8(BOM 허용), 실패하면 CP949로 읽어 UTF-8로 저장하고 NUL이 있으면 거절한다. PDF는 재인코딩하지 않고 원본을 저장·전달하며(`%PDF-` 시그니처 확인, 암호화·손상은 거절) 메시지당 1개다.
- 한도: 이미지 원본 5MB(넘으면 413 `attachment_too_large`), 텍스트 파일당 200KB(413), PDF 5MB(413). 쪽수·글자 수 한도는 넘으면 400 `attachment_invalid`이며 자르지 않고 거절한다: PDF 파일당 10쪽, 메시지의 텍스트 합계 1만 자, 세션 누적 이미지 10장·텍스트 3만 자·PDF 20쪽. 한도의 정본은 서버이고 `GET /api/profile`의 `client.attachments`(`max_files`, `image_upload_max_bytes`, `image_max_px`, `text_max_bytes`, `text_max_chars`, `session_max_images`, `session_max_text_chars`, `max_pdfs`, `pdf_max_bytes`, `pdf_max_pages`, `session_max_pdf_pages`, `image_extensions`, `text_extensions`, `pdf_extensions`)로 내려오며, 웹은 보내기 전 안내에만 쓴다(서버가 다시 검증한다).
- 글은 필수이고 기본 문구를 넣지 않으므로 첨부만 있고 글이 없으면 보내지 못하게 하고 힌트를 보인다. 첨부 오류(`attachment_*`)는 SSE 전에 JSON으로 오며 사용자 메시지를 만들지 않으므로 클라이언트는 쓴 글과 첨부 목록을 입력창에 되돌린다.
- `turn.text`에는 사용자가 쓴 글만 저장되고 첨부는 `attachment` 행(턴에 CASCADE)과 `attachments_dir/{session_id}/` 파일(폴더 0700·파일 0600)로 남는다. CLI에는 `[이미지 블록…, document(PDF) 블록…, 텍스트 블록]`으로 전달하고 텍스트 파일은 `<attachment name="…">…</attachment>` 래퍼로 사용자 글 앞에 붙인다.
- 일지 상세·다시 열기의 `turns[].attachments`는 `[{id, name, mime, size, thumb}]`이고(`thumb`는 썸네일이 있는 이미지), 파일은 `GET /api/attachments/{id}`(`?thumb=1`은 320px 썸네일)로 받는다. 이미지는 `inline`, 텍스트는 `text/plain; charset=utf-8`, PDF는 `application/pdf` 첨부(`attachment`)이며 항상 `X-Content-Type-Options: nosniff`다. 로그인이 없는 앱이라 보호는 ID(UUID) 추측 불가성과 네트워크 경계(Tailscale)뿐이다(`<img>`가 헤더를 못 붙이므로 토큰은 쓰지 않는다).
- 대화를 지우면 행과 폴더가 함께 지워지고, DB에 없는 파일은 1시간 뒤 정리된다. 다시 열면 CLI 프로세스가 새로 떠서 이미지·PDF는 이름만 남고(`[첨부: 이름]`, 캐릭터는 내용을 모른다고 말한다) 텍스트는 최신순 1만 자까지 다시 들어간다. 일지 정리에는 이름만 넘긴다.

### 2.14 기록만 남기기

`POST /api/sessions/{id}/turns/audio/record`, 본문은 음성 턴과 같은 오디오 바이트 → 201 `{text}`.

인식한 말을 사용자 턴으로만 저장하고 캐릭터는 대답하지 않는다. 대답할 수 없는 보관한 말(서버가 대화를 끝냄, 새로 고쳐 대화가 사라짐)의 유실을 막는 데 쓴다. 끝난 대화도 받으며 그때는 일지를 다시 정리한다(새 말에서 나온 노트만 더해진다). 진행 중인 턴이 있으면 409 `turn_in_progress`, 말이 없으면 422 `no_speech`, 없는 세션은 404 `session_not_found`.

### 2.15 지연 측정

서버는 음성 턴마다 요청 처리를 시작한 때를 기준으로 단계 시간(ms)을 남긴다: `upload_ms`(세션 확인과 본문 다 받기까지), `stt_ms`(형식 변환과 인식), `first_token_ms`(CLI 첫 글자), `first_queued_ms`·`first_synth_ms`·`synth_wait_ms`(첫 문장 합성 구간), `first_sentence_ms`(첫 문장을 소리와 함께 보냄), `done_ms`(턴 끝), `audio_bytes`. `[v2]` 문장마다 쓴 합성 모델(`tts_model`)과 폴백 발동 여부도 남긴다.

클라이언트는 한 번만 보고한다: `POST /api/sessions/{id}/turns/{turn_id}/latency {speech_to_request_ms, request_to_playback_ms, first_sound_notice, ack_ms}` → 204.

| 필드 | 뜻 |
|---|---|
| `speech_to_request_ms` | 말이 실제로 끝난 때(VAD 종료 감지 − 무음 대기 `end_of_speech_silence_ms`)부터 요청을 시작한 때까지 |
| `request_to_playback_ms` | 요청 시작부터 그 턴의 **첫 답변 소리**가 재생되기 시작한 때까지(검색 안내 음성 포함, 맞장구는 제외) |
| `first_sound_notice` | 첫 답변 소리가 검색 안내 음성이었는지 |
| `ack_ms` | `[v2]` 맞장구가 재생되기 시작한 시각(요청 시작 대비). 맞장구가 없었으면 생략 |

- 0~600000 범위. 기다리지 않고 실패는 무시한다. 끊은 턴·소리 없이 끝난 턴은 보내지 않고, 마무리 멘트 소리는 재지 않는다. 다시 보내면 덮어쓰고, 측정 행이 없으면 404 `turn_not_found`다.
- 맞장구는 `turn` 이벤트(인식 약 1초 뒤)보다 먼저 나갈 수 있어 보고할 턴 ID가 아직 없으므로, 클라이언트는 `ack_ms`를 보관했다가 `turn` 수신 때 해당 턴의 보고에 싣는다.
- `GET /api/latency?limit=100`(1~500) → `{turns: [..., first_sound_notice, total_ms], summary: {count, total_ms: {median, p90}, total_ms_reply: {median, p90}, stages: {단계: 중앙값}}}`(최근 음성 턴부터). `total_ms`는 두 보고값의 합(말 끝 → 첫 답변 소리), `total_ms_reply`는 첫 소리가 답변 문장인 턴만의 값이다(검색 턴은 안내 음성이 답변 지연을 가린다).
- `[v2]` 요약에 필드를 더한다: `summary.ack_ms`(`{median, p90}`, 맞장구가 나간 턴의 값), `summary.search`(`{count, total_ms: {median, p90}, total_ms_reply: {median, p90}}`, 검색 턴만 따로 센 값이며 위 `total_ms`는 검색 제외), `summary.tts`(`{models: {<모델 이름>: 문장 수}, fallback_ratio}`, 기본 모델에서 대체 모델·기기 TTS로 넘어간 문장의 비율).

## 3. 일지와 노트

### 3.1 목록

`GET /api/journal?from=YYYY-MM-DD&to=YYYY-MM-DD` → 일지 목록(최신순). 날짜는 서버 시간대의 현지 날짜이고 둘 다 포함하며, 생략하면 최근 30일이다(한 번에 366일까지, 2000-01-01~9998-12-31 밖이거나 범위가 틀리면 422 `invalid_range`).

- 사용자가 한마디도 하지 않은 대화는 빠진다. 진행 중인 대화(`status: active`)는 나온다.
- `[v2]` 보기 전환(날짜별/아이디어별)과 정렬은 없다. 키워드 검색(`q`)은 P2(FR-15)에서 추가하며, 그때 이 절에 더한다. 클라이언트는 `date`로 날짜별로 묶어 최신순으로만 보인다(시간대 계산을 하지 않는다). `topics`는 없다.
- 항목: `{id, date, started_at, ended_at, status, title, summary: [줄], tags, journal_status, counts: {idea, todo, memo}}`.
- `journal_status`는 `pending`(정리 중)·`done`·`failed`(정리 실패)·`null`(정리 기록 없음: 아직 끝나지 않은 대화, 또는 정리가 생기기 전에 끝난 대화)이다.
- 진행 중 항목은 "대화 중" 알약으로 보이고 누르면 대화 화면으로 돌아간다. 진행 중인 대화는 지울 수 없다.

### 3.2 상세와 정리

`GET /api/journal/{id}` → `{session: 위 항목, summary_cites, citations, checks, persona_name, notes: [{id, kind, content, starred, done, created_at, cites}], turns: [{id, seq, role, text, interrupted, merged_from, created_at, attachments: [{id, name, mime, size, thumb}]}]}`. 없으면 404 `session_not_found`(목록에서 빠지는 대화도 ID로는 조회된다).

- `turns`는 전문이고 `interrupted`는 끝까지 말하지 못한 답변이다. `[v2]` `merged_from`은 병합된 뒷말의 앞말 턴 ID이며, 두 행을 한 말풍선으로 보인다(없으면 `null`).
- **인용**: 검색으로 알게 된 요약 줄·메모에는 근거 출처 번호가 붙는다. `summary_cites[i]`는 `session.summary[i]`의 번호(같은 길이, 없으면 빈 목록), 노트의 `cites`는 그 메모의 번호, `citations`는 `[{n, title, url}]`이다. 클라이언트는 문장 끝에 `[1][2]`를, 맨 아래 "인용:" 아래에 `[n] 제목 URL`(제목은 링크, http(s)만)을 그린다. 번호는 서버가 대화 중 캐릭터가 본 검색 결과에 맞춰 검증하고 1부터 다시 매긴 것이다. 검색하지 않은 대화·예전 일지는 빈 목록이다.
- **표시 형식**: `checks`가 null이 아니면 새 형식이다. `session.summary` 첫 줄은 결론(굵게), 나머지 줄은 "알게 된 것", `checks`는 "확인할 것"으로 그리고, 태그는 인용 뒤 맨 아래에 둔다. `checks`가 null이면 예전 형식(요약 줄 목록)이며, 끝난 대화면 다시 정리해 새 형식으로 바꿀 수 있다(다시 정리해도 노트는 새로 넣지 않는다).
- 전문의 캐릭터 화자 이름은 `persona_name`(그 세션의 페르소나 이름)을 쓴다(코드에 두지 않는다).
- **정리 상태 갱신**: `journal_status`가 `pending`인 동안 목록·상세를 3초마다(최대 약 2분) 다시 불러와 정리가 끝난 것을 보여 준다.

| 요청 | 결과 |
|---|---|
| `POST /api/journal/{id}/retry` | 202 일지 항목. 정리에 실패했거나(`failed`) 정리 기록이 없는(`null`) 끝난 대화, 또는 예전 형식(`done`인데 `checks`가 null)을 다시 정리한다. 정리 중·완료면 아무것도 하지 않고 그대로 준다. 끝나지 않은 대화는 409 `session_not_ended` |
| `PATCH /api/journal/{id} {title}` | 바뀐 일지 항목. 줄바꿈·연속 공백은 한 칸으로 줄인 뒤 1~200자. 없으면 404 `session_not_found`. 고친 제목은 다시 정리해도 바뀌지 않는다 |
| `DELETE /api/journal/{id}` | 204. 대화와 노트·전문·지연 기록·보관한 녹음을 모두 지운다. 진행 중(`active`)이면 409 `session_active`(끝낸 뒤 지운다), 답변을 만드는 중이면 409 `turn_in_progress`, 쉬는 중(`paused`)이면 CLI를 정리하고 지운다. 정리 중이던 일지 정리는 멈춘다 |

P2(미구현): `GET /api/journal/{id}/export.md`는 일지를 Markdown으로 내보낸다(FR-16). 만들 때 이 표에 추가한다.

여러 개를 한 번에 지울 때는 일괄 API 없이 고른 항목마다 `DELETE`를 차례로(동시에 보내지 않고) 부르고, 404는 이미 지워진 것으로 보며, 실패한 항목만 선택된 채 남긴다.

### 3.3 노트

`PATCH /api/notes/{id} {starred?, done?, content?}` → 바뀐 노트. 아이디어의 `done`은 다 했거나 접은 아이디어를 닫는 데 쓴다(다음 대화의 기억에서 빠진다). 보낸 필드만 바꾸며 `content`는 앞뒤 공백을 뺀 1~500자이고 여러 줄도 된다. 없으면 404 `note_not_found`.

### 3.4 시작 화면 "지난 아이디어 이어 가기"

`GET /api/notes/open-ideas?limit=5` → `[{id, content, starred, session_id, created_at, counts: {idea, todo, memo}}]`.

- 완료하지 않은 아이디어를 대화당 하나씩(그 대화의 가장 최근 아이디어) 만든 날짜의 역순으로 `limit`개(1~20, 기본 5) 준다. 항목마다 `counts`로 그 대화(`session_id`)에 저장된 종류별 노트 수를 붙인다(일지 목록 `counts`와 같은 기준이라 완료한 것도 센다). 없으면 빈 목록.
- 클라이언트는 카드에 만든 날짜·내용과 "아이디어 N · 할 일 M · 메모 K"(0인 종류는 뺀다)를 보인다. 대화 전 시작 화면이 보일 때마다 다시 불러오고(끝난 대화 화면에는 두지 않는다), 빈 목록이거나 못 불러오면 목록을 숨긴다. 카드를 누르면 그 `session_id`의 일지 상세를 연다(거기서 이어서 하기).

## 4. 프로필과 보이스

### 4.1 프로필

`GET /api/profile` → `{nickname, email, mail_ready, interests, persona_id, voice, speaking_rate, ack_enabled, keep_audio, chat_model, default_chat_model, client}`(처음 조회하면 기본값으로 만든다). `client`는 7절의 클라이언트 설정값이고 읽기 전용이다(`PUT`에 보내면 422).

`PUT /api/profile`은 보낸 필드만 바꾼다.

| 필드 | 규칙 |
|---|---|
| `nickname` | 앞뒤 공백을 뺀 1~20자 한 줄. `null`이면 기본 호칭으로 돌아간다. `[v2]` 호칭은 **세션 시작 인사말에서만** 쓰이며, 바꾸면 다음 세션의 첫 인사부터 적용된다(2.2) |
| `email` | 대화를 보낼 본인 주소(앞뒤 공백을 뺀 이메일 모양 254자 이내, 틀리면 422). `null`이면 설정 안 함 |
| `mail_ready` | 서버에 메일 보내기(SMTP) 설정이 있는지(읽기 전용) |
| `interests` | 최대 10개, 각 1~30자, 중복은 제거한다. 다음 대화의 프롬프트부터 쓴다 |
| `voice`, `speaking_rate` | `voice`는 `GET /api/voices`의 `voices` 안의 이름만(틀리면 422), `speaking_rate`는 0.75~1.5. 둘 다 `null`이면 캐릭터(페르소나 YAML) 기본값. 바꾼 값은 다음 답변(인사말·문장·마무리 멘트)부터 쓴다. 말 속도를 정하면 서버가 음성 말투 지시에도 빠르기를 붙인다 |
| `ack_enabled` `[v2]` | 기본 `true`. 끄면 클라이언트가 맞장구를 재생하지 않는다(6.4) |
| `keep_audio` | 기본 `false`. 켜면 이후 음성 턴의 녹음(인식에 넘긴 파일: 인식이 바로 받는 형식 webm·wav·mp3·m4a는 올린 그대로, 그 밖은 서버가 바꾼 webm/opus)을 사용자 턴에 붙여 보관하고 30일(`AUDIO_RETENTION_DAYS`)이 지나면 지운다. 끄면 이후 녹음은 저장하지 않고, 이미 저장한 녹음은 같은 기간 뒤 지운다. 녹음은 본인만 읽을 수 있는 권한으로 저장하며, 저장에 실패해도 턴은 그대로 진행한다(경로를 남기지 못하면 파일도 지운다) |
| `chat_model` | `haiku`·`sonnet`·`opus` 중 하나(그 밖은 422). `null`이면 서버 기본값(`default_chat_model`, 서버 설정 `LLM_CHAT_MODEL`). 진행 중인 대화에도 다음 답변부터 쓴다(서버가 답변 사이에 같은 대화 맥락으로 CLI를 새 모델로 다시 띄우므로 바꾼 직후 첫 답변은 늦을 수 있다). 일지 정리 모델은 따로이며 바뀌지 않는다 |
| `persona_id` | 없는 페르소나는 404 `persona_not_found` |

진행 중인 세션의 프롬프트는 시작 때 고정돼(`conversation_session.system_prompt`) CLI를 다시 띄우거나 서버를 재시작해도 그대로다. 대화 중 사용자가 호칭을 바꿔 달라고 하면 캐릭터가 `set_nickname` 도구로 같은 `nickname`을 바꾸고(이번 사용자 발화에 나온 호칭만 받는다, 새 호칭은 다음 세션 첫 인사부터 쓰이고 그 변경을 알리는 답변에서만 한 번 말해도 된다), 모델을 바꿔 달라고 하면 `set_model` 도구로 같은 `chat_model`을 바꾼다(이번 사용자 발화에 "모델"이나 모델 이름이 있을 때만 받는다).

### 4.2 보이스

- `GET /api/voices` → `{voices, default_voice, default_rate, min_rate, max_rate}`.
- `GET /api/voices/{voice}/sample?rate=` → 고정 문장의 미리 듣기 MP3(보이스·속도별로 한 번만 합성). 합성할 수 없으면 503 `voice_unavailable`.

## 5. 오디오 형식

- 업로드: 말 한 번을 하나의 오디오로 보낸다. 권장은 16kHz 모노 Opus(웹 `audio/webm;codecs=opus`). 웹은 VAD가 준 16kHz 발화 오디오를 WebCodecs `AudioEncoder`로 24kbps Opus로 인코딩해 webm에 담고(mediabunny, `web/src/platform/encodeAudio.ts`), 브라우저가 Opus 인코딩을 못 하면 16bit PCM WAV(`audio/wav`, 약 10배 큼)로 보낸다. 서버는 webm·wav·mp3·m4a(mp4)는 그대로 인식에 넘기고, 그 밖의 형식(ogg 등)은 16kHz 모노 webm/opus로 바꾼다. 최대 10MB, 변환은 앞 120초까지.
- 응답: 문장별 MP3(base64, `sentence.audio`), 인사말·마무리 멘트도 MP3(base64)다.
- `[v2]` 합성 실패 시 서버는 재시도·대체 모델을 거쳐 최종 실패하면 `audio: null`과 `speech_text`를 보내고, 클라이언트는 기기 TTS(`speechSynthesis`, ko-KR)로 읽는다. 첫 문장은 요청 시작 후 12초가 지나도 소리가 없으면 글을 먼저 보낸다(Spec 5.2).

## 6. 세션 상태 머신

음성 대화는 아래 상태를 오가는 하나의 루프다. 상태 머신은 이벤트를 받아 다음 상태와 **명령**을 돌려주는 순수 함수이고(웹 `web/src/core/sessionMachine.ts`), 마이크·재생·서버 호출·타이머는 화면·플랫폼 계층이 명령을 받아 실행한다. 전이 표 `shared/fixtures/transitions.json`을 웹 테스트(Vitest)가 읽는다. 각 사례는 대기에서 시작해 단계마다 이벤트를 넣고 상태 이름·명령 목록(순서 포함)·지정한 context 값을 확인한다. v1 사례(33개)를 이식하고 `[v2]` 사례를 더한다: 종료 확인(열기·확인·취소, 열린 동안 서버가 끝냄), 맞장구(타이머 → 재생, 첫 문장이 먼저 와서 건너뜀, 겹침, 사용자 발화로 중단), 병합(뒷말 즉시 전송, 앞 턴 `done.superseded`가 뒷말 `turn`보다 먼저 도착, 병합 조건 불충족 각 경우, `turn_in_progress`로 큐에 되돌림).

### 6.1 상태·이벤트·명령

- **상태**(코드 이름): 대기 `idle`, 듣기 `listening`, 처리 중 `processing`, 말하기 `speaking`, 쉬기 `paused`, 오프라인 보관 `offline`, 정리 `closing`.
- **이벤트**: 버튼 `tap`·`long_press`·`pause`(일시 중단), `end_request`·`end_confirm`·`end_cancel`(`[v2]` 대화종료 버튼과 확인 창), 시작 `session_started`(인사말 재생 시작)·`start_failed`, 발화 감지 `speech_start`·`speech_end`, 턴 스트림 `turn`·`sentence`·`turn_done`·`turn_error`·`note_saved`, 재생 `sentence_played`·`playback_idle`, 오프라인 `send_failed`·`offline_notice_done`·`online`·`queue_sent`·`queue_send_failed`, 맞장구 `ack_due {turnId}`·`ack_started {turnId}`·`ack_done {turnId}`(`[v2]`), 그 밖 `idle_timeout`·`session_closed`·`end_failed`.
- **명령**: `startSession`, `sendTurn`, `cancelTurn`(턴 ID와 마지막으로 다 들려준 문장 번호), `endSession`, `micOn`·`micOff`, `setVadMode`(재생 중 `playback`으로 임계값 상향), `stopPlayback`, `queueUtterance`, `speakOfflineNotice`, `sendQueued`, `playSound`(`listen`·`saved`·`offline`), `startAckTimer {turnId}`·`playAck {turnId}`·`stopAck`(`[v2]` 맞장구), `showEndConfirm`·`hideEndConfirm`(`[v2]` 종료 확인 창), `notifyError`, `startIdleTimer`·`clearIdleTimer`.

### 6.2 규칙 요약

- **한 번 누르기(큰 버튼)**: 대기에서는 시작, 말하기·처리 중에는 끼어들기(재생을 멈추고 취소 뒤 듣기. 처리 중에도 검색 안내 음성이 나오고 있을 수 있다), 쉬기에서는 다시 듣기.
- **일시 중단**(`pause`, 보조 버튼): 듣기에서만 받아 쉬기로 간다. 마이크를 끄고(`micOff`) 무발화 타이머를 다시 시작하며, 말하던 중이면 그 말은 버린다. 서버 호출은 없다(서버 세션은 진행 중이고 무발화 감시가 같은 30분 기준으로 정리한다). 다시 듣기는 쉬기의 `tap`이다. 다른 상태에서는 무시한다.
- 답변 문장을 다 들려주고 턴이 끝나면 `done`의 `session_status`에 따라 듣기·쉬기·정리로 간다.
- 듣기·쉬기에서 30분(`idle_timeout_minutes`) 동안 말이 없으면 정리로 간다. 서버 안전망과 같은 기준이다.
- 표에 없는 조합과 모르는 이벤트는 무시한다.

### 6.3 종료 `[v2]`

- **대화종료 버튼**: 대기·정리를 뺀 모든 상태에서 보이는 보조 버튼(글 대화는 입력창 아래 버튼)이다. context에 `endConfirmOpen`을 둔다.
  - `end_request`: `endConfirmOpen`을 `true`로 하고 `showEndConfirm`을 낸다. 상태는 그대로다(진행 중인 재생·듣기는 그대로 둔다). 이미 열려 있으면 무시한다.
  - `end_confirm`: `endConfirmOpen`이 `true`일 때만 받는다(아니면 무시). `hideEndConfirm`, 진행 중인 턴이 있으면 `cancelTurn`, 재생 중지, `endSession`을 내고 정리로 간다.
  - `end_cancel`: `endConfirmOpen`이 `true`일 때만 `hideEndConfirm`을 내고 `false`로 한다.
  - 확인 창이 열린 동안 `session_closed`·`idle_timeout`·서버가 끝낸 세션 등으로 정리나 대기로 가면 `hideEndConfirm`도 함께 낸다.
  - 확인 창 문구는 화면이 정한다(시안: "대화를 끝낼까요?", 버튼 "끝내고 정리하기"/"계속 대화하기").
- **큰 버튼 길게 누르기**(`long_press`): 확인 창 없이 같은 종료를 한다(보조 수단). 정리 중이면 끝내기 응답을 기다리지 않고 대기로 간다("그만 기다리기"도 같다).
- 마이크를 쓸 수 없으면(`mic_denied` 등) 플랫폼이 `long_press`로 대화를 마치고(일지 정리), 정리가 끝난 뒤 이유를 보인다. 대기·정리 중에 늦게 온 마이크 오류는 무시한다. 턴 도중 세션이 서버에서 끝났을 때(`session_ended`)의 문구도 정리가 끝난 뒤 보인다.

### 6.4 맞장구 `[v2]`

- 상태는 바꾸지 않는 부가 동작이다(`processing` 중에만 일어난다). 턴 요청을 보내는 `sendTurn`과 함께 머신이 `startAckTimer {turnId}`를 내고(건너뛰는 경우가 아니면), 플랫폼이 `ack_delay_ms` 뒤에 `ack_due {turnId}`를 보낸다. 머신은 그 턴이 아직 현재 턴이고 첫 답변 문장이 재생 대기열에 없을 때만 `playAck {turnId}`를 내고, 플랫폼이 재생을 시작하면 `ack_started {turnId}`, 끝나면 `ack_done {turnId}`를 보낸다. 턴 ID가 다른 `ack_*`는 무시한다.
- 건너뛰는 경우: 말이 `ack_min_speech_ms` 미만이거나 글 입력 턴이거나 프로필 `ack_enabled`가 `false`인 경우. 검색 턴은 맞장구 뒤에 검색 안내 음성이 평소처럼 이어진다. 소리는 세션 시작 응답의 `persona.ack`에서 고른다.
- 첫 문장이 맞장구 재생 시작 후 `ack_overlap_max_ms` 안에 오면 맞장구를 페이드아웃(`stopAck`)하고 답을 재생한다. 그보다 늦으면 맞장구가 끝난 뒤 이어서 재생한다. 사용자가 다시 말하면 `stopAck`으로 즉시 멈춘다.
- 맞장구가 나가는 동안은 재생 중 VAD 임계값(`setVadMode playback`)을 적용한다.
- 맞장구는 지연 측정의 "첫 답변 소리"에서 제외하고 `ack_ms`로 따로 보고한다(2.15).

### 6.5 오프라인 큐와 이어 말하기

- **오프라인 큐**: 새 말을 보내다 서버에 닿지 않으면(`send_failed`) 큐에 넣고 오프라인 안내 뒤 듣는다(`connected=false`). 연결되면(`online`) 큐의 말을 가장 오래된 것부터 보통 턴으로 보내(`sendQueued`) 캐릭터가 차례로 대답한다. 턴을 다 들려주고 끝났을 때·오프라인 안내가 끝났을 때·쉬기에서 다시 들을 때·오류 뒤에도 연결돼 있고 큐가 있으면 듣기 대신 큐부터 보낸다(끼어들기는 사용자가 말하려는 것이므로 바로 듣는다). 큐가 남아 있는 동안 한 새 말은 큐 뒤에 넣어 순서를 지킨다. 큐의 말을 서버가 받으면 `queue_sent {remaining}`, 보내다 서버에 닿지 않으면 `queue_send_failed`(안내 없이 듣기, 말은 큐에 그대로)다. 상태에는 `connected`가 있다.
- **처리 중 들어온 발화**: 처리 중(답변을 기다리는 중, 보관한 말을 보내는 중 모두)에 들어온 발화(`speech_end`)도 버리지 않고 큐 뒤에 넣어(`queueUtterance`) 턴이 끝나면 연결돼 있는 한 차례로 보낸다. 끼어든 뒤 큐가 남아 있으면 다음 턴이 끝날 때(또는 다음 말) 이어서 보낸다. `[v2]` 단, 2.8의 병합 조건(앞 턴이 음성 턴이고 첫 문장·검색 안내가 아직 없음, 큐가 비어 있음, 뒷말이 음성 턴이고 길이 조건 충족)이면 큐에 넣지 않고 바로 `sendTurn`한다. 그렇게 보낸 말이 `turn_in_progress`로 거절되면 `queueUtterance`로 큐에 되돌린다. `done.superseded`가 앞 `sendTurn`을 상태 변화 없이 끝내는 규칙과 그 도착 순서는 2.8에 있다.
- **이어 말하기**: 상태에는 `userSpeaking`(마이크가 켜진 상태에서 `speech_start` 뒤 `speech_end` 전)이 있다. 처리 중에 말을 시작해 아직 끝나지 않았는데 첫 답변 문장이 오면 끼어들기로 처리한다(재생을 멈추고 들려준 문장 없이 취소한 뒤 듣기). 반쪽 말에 답하지 않고 이어 하는 말을 다음 턴으로 보낸다. 말하기 중에 끝난 말도 버리지 않고 큐 뒤에 넣는다.
- 화면은 끊겼으면 보관한 말 수를, 연결돼 있으면 "이어서 한 말 N개"(답변 중이면 "답변 뒤에", 아니면 "다음 차례에" 보냄)를 보인다.
- 큐 순번은 말이 끝난 때 정하므로 보내던 말이 실패해 나중에 큐에 들어가도 그사이 넣은 뒷말보다 앞에 선다.

### 6.6 플랫폼이 지킬 것

- 인사말은 SSE가 아니라 시작 응답으로 온다. 재생을 시작하며 `session_started {turnId}`(인사말 턴 ID)를 보내고, 재생할 소리가 없으면 바로 `playback_idle`을 보낸다.
- `sentence`·`turn_done`에는 턴 ID를 싣는다. 머신은 지금 턴과 다른 ID의 이벤트(취소한 턴의 늦은 이벤트)를 무시한다. `turn_error`는 턴 시작 전 오류면 `turnId: null`이다.
- `sentence` 이벤트는 그 문장 소리를 재생 대기열에 넣은 뒤에 머신에 보낸다. `playback_idle`은 보내는 순간 대기열이 비어 있을 때만 보낸다(`done`보다 먼저 와도 된다).
- 모든 요청(`startSession`·`sendTurn`·`endSession`)은 성공 이벤트나 실패 이벤트(`start_failed`·`turn_error`·`send_failed`·`end_failed`) 중 하나로 반드시 끝낸다. 시간 초과도 실패로 보낸다.
- 이어 재생(`AudioOutput`, `web/src/platform/audioOutput.ts`)은 넣은 순서대로 하나씩 재생하고(디코드는 넣는 즉시 병렬), 답변 문장이 끝날 때마다 `sentence_played {index}`, 대기열이 비면 `playback_idle`을 보낸다. 인사말·검색 안내(`tool.notice`)·마무리 멘트·맞장구는 문장 번호 없이 넣는다(`sentence_played` 없음). 소리가 없는 문장(`audio: null`)은 기기 TTS(`speech_text`)로 읽고, 읽기에 실패하거나 디코드·재생에 실패한 소리는 길이 0으로 보고 순서대로 넘어간다. `stopPlayback`은 즉시 멈추고 대기열을 비우며 이벤트를 보내지 않는다. 브라우저 자동 재생 제한 때문에 시작 버튼을 누를 때 오디오를 연다(`unlock`). 소리가 나지 않는 상황에서도 대기열은 멈추지 않는다(다시 켜기를 0.5초만 기다리고, 끝 알림이 오지 않으면 소리 길이 + 2초 뒤 넘어간다). 소리 없는 문장은 넣자마자 `sentence_played`가 나갈 수 있으므로, 플랫폼은 대기열에 넣은 직후 같은 동기 흐름에서 머신에 `sentence`를 보낸다(사이에 `await`을 두지 않는다).
- 마이크 입력(`AudioInput`, `web/src/platform/audioInput.ts`)은 `micOn`→`start`, `micOff`→`stop`(트랙을 멈춰 마이크 표시가 꺼진다), `setVadMode`→`setMode`로 받는다. `speech_start`는 말소리가 `min_speech_ms` 동안 이어진 뒤에 보낸다(재생 중 짧은 소음 한 번으로 끼어들기가 되지 않게). 그보다 짧은 소리는 이벤트 없이 버린다. `stop` 뒤에는 이벤트를 보내지 않는다. `mic_denied`·`mic_unavailable`·`vad_failed`는 6.3의 종료 규칙으로 처리한다.
- 명령 실행(`web/src/screens/voiceController.ts`): `startSession`은 `POST /api/sessions {mode: "voice"}` 뒤 인사말 소리를 대기열에 넣고 `session_started`를 보낸다. `sendTurn`은 음성 턴을 올리고 SSE를 머신 이벤트로 바꾼다(`transcript`는 사용자 말풍선, `sentence`는 소리를 넣은 뒤 `sentence`, `tool.notice`는 번호 없이 대기열에(소리가 있으면 마이크를 재생 중 임계값으로 바꿔 안내 음성을 이어 말하기로 잡지 않는다), `save_note` 성공은 `note_saved`). `cancelTurn`은 받는 중인 턴 요청 연결을 끊고(늦은 이벤트를 버린다) 끼어들기 API에 `lastPlayed`를 보낸다(기다리지 않고 실패는 무시: 연결이 끊기면 서버가 보낸 문장까지는 끊긴 답변으로 남긴다). 말풍선도 들려준 문장까지만 남긴다(대화 리듀서 `interrupt`). 인사말은 자르지 않는다. 끝내기 응답 뒤 마무리 소리(`closing_audio`)를 넣고 `session_closed`를 보낸다.
- 대화 중에는 Screen Wake Lock으로 화면을 켜 두고, Media Session의 재생/일시정지(이어폰 버튼)를 `tap`으로 받는다. 음성 모듈(vad-web·onnxruntime·mediabunny)은 첫 화면 로딩에서 빼고 화면이 열린 뒤 따로 불러오며, 다 불러오기 전에는 "음성으로"를 막는다(오디오는 버튼을 누른 동작 안에서 열어야 한다). 불러오지 못하면 글로 대화하도록 안내한다. 시작 화면과 대화 화면의 "음성으로/글로" 선택 버튼은 같은 위치·모양이고, 고른 방식을 기억해 `prepare`도 그 방식으로 보낸다.
- **음성 대화 중 글 입력**: 글은 말 한 번처럼 `speech_end`로 머신에 넣고, `sendTurn`에서 `POST /api/sessions/{id}/turns {text}`로 보낸다(서버가 음성 대화면 답변 음성도 만든다). 듣기에서만 받는다. 말하기면 `tap`(끼어들기), 쉬기면 `tap`(다시 듣기)을 먼저 보내고 듣기가 되면 보낸다. 끼어든 직후에는 `cancelTurn` 요청이 끝난 뒤 보내고, 그래도 `turn_in_progress`(서버가 이전 답변을 정리 중)면 0.5초 뒤 최대 3번 다시 보낸다. 처리 중·오프라인·정리 중이거나 큐에 말이 남아 있으면 받지 않는다(화면은 입력을 남기고 보내기만 잠근다). 인식 결과 이벤트가 없으므로 내 말풍선은 보낼 때 바로 그린다. 턴 시작 전에 실패해도 큐(녹음 전용)에 넣지 않는다. 대화가 이어지면 말풍선을 빼고 글을 입력창에 돌려주고, 대화가 끝났으면 말풍선만 빼고 글은 버린다. 지연 측정은 하지 않는다. `[v2]` 글 입력은 병합 대상이 아니다.
- **오프라인 큐 저장소**(`LocalQueue`, `web/src/platform/localQueue.ts`)는 녹음을 대화 ID와 함께 IndexedDB에 보관한다(새로 고쳐도 남는다, IndexedDB를 못 쓰면 메모리로 대신해 새로 고치면 사라진다). 서버에 닿지 않은 실패는 턴 시작 전의 `network_error`·`stream_closed`이고, 그 밖의 오류는 `turn_error`다. `queueUtterance`는 녹음을 큐에 넣고, `sendQueued`는 이 대화의 가장 오래된 말을 보내 `turn`을 받으면 큐에서 지운 뒤 `queue_sent`를 보낸다. 턴이 시작되기 전에 30초가 지나면 서버에 닿지 않은 것으로 본다. 큐의 말이 말소리가 없으면(`no_speech` 등) 버리고, 서버 일시 오류면 남겨 두고 `queue_send_failed`로 나중에 다시 보낸다(5번 실패하면 대답을 포기하고 기록만 남겨 뒤의 말을 막지 않는다). 서버가 말을 저장한 직후 `turn` 전에 끊기면 다시 보내 한 번 더 기록될 수 있다(최소 한 번 전달). 서버가 대화를 끝냈으면(`session_ended`) 그 말은 대답 없이 기록만 남긴다(2.14). 끝내기로 보내던 말이 끊기면 보관해 기록만 남긴다. 대화가 끝나 대기로 돌아가면(끊긴 채 끝냄 포함) 이 대화에 남은 말과 이전 대화(새로 고치기 전)의 남은 말도 기록만 남긴다(연결이 없으면 다음 연결 때). `speakOfflineNotice`는 기기 TTS(`speechSynthesis`, ko-KR)로 `client.offline_notice`를 읽고 끝나면 `offline_notice_done`을 보낸다(없거나 6초를 넘으면 바로). 연결 복구는 브라우저 `online` 이벤트와, 끊긴 동안 30초마다 `GET /api/health`로 서버에 닿는지 확인하는 것으로 알아챈다. 보관한 녹음은 30일이 지나면 보내지 않고 지우고, 기록만 남기기에 5번 실패한 말도 지운다(NFR-04의 예외). 대답을 포기한 말은 "기록만" 표시로 보통 전송에서 빠진다. 저장소에 넣지 못하면 그 말은 메모리에 두고, 읽기·지우기는 두 곳을 모두 본다. 화면에는 보관한 말 수를 보인다.

## 7. 클라이언트 설정값

클라이언트는 `GET /api/profile`의 `client`를 받아 쓴다. 받기 전(또는 받지 못했을 때)에는 같은 형식의 `shared/client-defaults.json`을 대체값으로 쓴다. 서버는 시작할 때 이 파일을 읽어 검증하며(서버 `app/client_config.py`), 틀리면 서버가 시작하지 않는다. 다만 `session.idle_timeout_minutes`는 서버의 무발화 종료 기준(`IDLE_TIMEOUT_S`)으로 덮어써 서버 안전망과 늘 같다(0 이하면 서버가 시작하지 않는다). 서버만 따로 배포할 때는 `shared/`를 함께 두거나 `CLIENT_DEFAULTS_PATH`로 파일 위치를 준다. 화면 문구의 "30분"은 이 값에서 읽는다.

| 필드 | 기본값 | 의미 |
|---|---|---|
| `vad.speech_threshold` | 0.5 | Silero VAD 음성 확률이 이 값 이상이면 말 시작으로 본다(평상시) |
| `vad.silence_threshold` | 0.25 | 이 값 아래면 무음으로 본다. `speech_threshold`보다 작다 |
| `vad.playback_speech_threshold` | 0.8 | 캐릭터 음성(맞장구 포함) 재생 중의 말 시작 기준. 목소리를 사용자 발화로 잘못 듣지 않게 올린다. 평상시 값 이상 |
| `vad.playback_silence_threshold` | 0.65 | 재생 중 무음 기준. 평상시 값 이상, 재생 중 말 시작 기준보다 작다 |
| `vad.end_of_speech_silence_ms` | 1800 | 무음이 이만큼 이어지면 발화 끝(`speech_end`). `[v2]` 고정값이며 줄이는 것은 현장 데이터 뒤에 다시 검토한다 |
| `vad.min_speech_ms` | 300 | 이보다 짧은 소리는 발화로 보지 않고 버린다 |
| `session.idle_timeout_minutes` | 30 | 듣기·쉬기에서 이 시간 동안 말이 없으면 정리로 간다. 소수일 수 있다 |
| `audio.upload` | `{codec: "opus", sample_rate_hz: 16000, channels: 1}` | 발화 업로드 형식(5절) |
| `audio.response` | `{codec: "mp3"}` | 답변 문장 오디오 형식(5절) |
| `turn.ack_delay_ms` `[v2]` | 300 | 요청을 보낸 뒤 이 시간 안에 첫 문장이 오지 않으면 맞장구를 재생한다 |
| `turn.ack_min_speech_ms` `[v2]` | 1000 | 이보다 짧은 말에는 맞장구를 하지 않는다 |
| `turn.ack_overlap_max_ms` `[v2]` | 300 | 첫 문장이 맞장구 재생 시작 후 이 시간 안에 오면 맞장구를 페이드아웃한다 |
| `turn.merge_min_speech_ms` `[v2]` | 600 | 뒷말의 실제 음성 길이가 이보다 짧으면 병합하지 않는다(잡음 보호) |
| `offline_notice` | 페르소나 YAML의 안내 문구 | 오프라인 보관 때 기기 TTS로 읽는 안내(`[v2]` 서버가 페르소나 설정에서 채운다. 대체값은 "네트워크 연결이 불안하여 메모만 해둘게요.") |
| `attachments` | 서버 설정(파일에 없음) | 파일 첨부 한도(2.13) |

VAD 수치는 시작값이며 실제 산책 측정에서 조정한다. 웹은 `@ricky0123/vad-web`(Silero `v5` 모델)에 `speech/silence_threshold` → `positive/negativeSpeechThreshold`, `end_of_speech_silence_ms` → `redemptionMs`, `min_speech_ms` → `minSpeechMs`로 넘기고, 재생 중(`setVadMode playback`)에는 `playback_*` 값으로 바꾼다. 감지 전 소리 300ms를 발화 앞에 붙인다(웹 상수 `PRE_SPEECH_PAD_MS`). 모델·worklet·onnxruntime wasm은 CDN이 아니라 앱이 `/vad/<vad-web 버전>-<onnxruntime 버전>/`에서 서빙한다(약 16MB, wasm이 대부분. 파일 이름에 해시가 없어 버전 폴더로 캐시를 나눈다, `web/vadAssets.ts`).

## 8. 알림음과 안내 문구

`shared/sounds/`의 효과음을 쓴다: `listen.mp3`(듣기 시작, 올라가는 두 음 0.24초), `saved.mp3`(노트 저장, 맑은 두 음 0.29초), `offline.mp3`(오프라인 전환, 내려가는 두 음 0.36초). 상태 머신의 `playSound {name}`이 이 파일 이름과 같다. `[v2]` 맞장구 소리와 검색 안내(`search_notice`)의 문구·음성은 캐릭터 설정(`personas/*.yaml`)에서 온다. 오프라인 안내 문구는 7절의 `offline_notice`다.

## 9. 오류 응답

모든 API 오류는 HTTP 상태 코드와 함께 아래 형식으로 내려간다(서버 `app/errors.py`).

```json
{"error": {"code": "not_found", "message": "사람이 읽는 설명", "request_id": "b994ba61…", "details": {}}}
```

- `code`: 클라이언트가 분기에 쓰는 고정 문자열. `message`는 표시용이며 바뀔 수 있다.
- `details`: 선택. `validation_error`이면 필드 오류 목록(`loc`, `msg`, `type`).
- `request_id`: 응답 헤더 `X-Request-ID`와 같다. 클라이언트는 `X-Request-ID` 헤더(영문·숫자·`._-`, 64자 이내)를 보낼 수 있고, 없거나 형식이 맞지 않으면 서버가 새로 만든다. 서버는 모든 응답 헤더에 `X-Request-ID`를 넣는다.

| 상태 | `code` | 의미 |
|---|---|---|
| 404 | `not_found` | 없는 경로·리소스 |
| 405 | `method_not_allowed` | 지원하지 않는 메서드 |
| 422 | `validation_error` | 요청 형식 오류 |
| 500 | `internal_error` | 서버 내부 오류(내부 정보는 응답에 넣지 않음) |
| 503 | `db_unavailable` | 데이터베이스 연결 불가 |
| 403 | `csrf_rejected` `[v2]` | 변경성 요청의 `X-TrailTalk` 헤더·`Origin`·`Content-Type` 검사 실패(1.5) |
| 404 | `session_not_found` | 없는 대화 세션 |
| 409 | `session_ended` | 이미 끝난 세션에 턴 요청 |
| 409 | `turn_in_progress` | 같은 세션의 이전 답변이 아직 진행 중(`[v2]` 병합 조건이면 대체되어 이 오류가 나지 않는다) |
| 404 | `turn_not_found` | 끼어들기·지연 보고 대상이 이 대화의 캐릭터 답변이 아님 |
| 500 | `persona_invalid` | 서버의 페르소나 YAML 오류(프로필 요청에서 올 수 있다. 세션 시작에서는 일반 문구로 바뀐다) |
| 401·403·409·429 등 | `unauthorized`·`forbidden`·`conflict`·`too_many_requests`, 그 밖은 HTTP 상태 이름 | 일반 HTTP 오류 |
| 404 | `persona_not_found` | 없는 페르소나(`PUT /api/profile`) |
| 404 | `note_not_found` | 없는 노트 |
| 422 | `invalid_range` | 일지 목록의 날짜 범위가 틀림 |
| 409 | `session_not_ended` | 끝나지 않은 대화를 다시 정리하려 함 |
| 409 | `session_active` | 진행 중인 대화를 지우려 함 |
| 502 | `llm_error` | 인사말·답변을 만들지 못함(SSE에서는 `error` 이벤트) |
| 502 | `llm_process_exited` | Claude CLI 프로세스가 끝남. 다음 요청에서 맥락을 이어 다시 띄운다 |
| 504 | `llm_timeout` | 답변 시간 초과 |
| 422 | `no_speech` | 음성 턴에서 인식 결과에 말이 없음. 사용자 메시지는 만들지 않는다 |
| 400 | `attachment_invalid` | 파일 첨부가 형식·개수·내용·한도에 맞지 않거나 음성 세션(첨부 턴). 메시지를 그대로 보인다 |
| 413 | `attachment_too_large` | 첨부 파일이 너무 큼(이미지·PDF 5MB, 텍스트 200KB) |
| 404 | `attachment_not_found` | `GET /api/attachments/{id}`의 첨부가 없음 |
| 400·413 | `audio_invalid` | 업로드 오디오가 비었거나, 너무 크거나(413), 읽을 수 없음 |
| 503 | `voice_unavailable` | 음성 서비스를 쓸 수 없음(서버 키 없음·인증 실패·크레딧 소진·ffmpeg 없음). 다시 시도해도 풀리지 않는다 |
| 502 | `stt_failed`·`tts_failed` | 음성 인식·합성 실패(일시 오류 포함) |
| 504 | `stt_timeout`·`tts_timeout` | 음성 인식·합성 시간 초과 |

**클라이언트 측 코드**(서버가 보내지 않고 클라이언트가 만든다, 웹 `src/api/http.ts`·`src/api/conversation.ts`): `network_error`(서버에 연결할 수 없음, 또는 JSON 본문 없는 502·503·504: 개발 프록시·터널이 서버 중단 때 주는 응답), `http_error`(오류 응답이 공통 형식이 아님), `stream_closed`(턴 스트림이 `done`·`error` 없이 끊김), `bad_event`(SSE `data`가 JSON이 아니거나, JSON이어도 객체가 아니거나 `type`이 문자열이 아님).

기능별 코드는 해당 API를 만들 때 이 표에 추가한다.
