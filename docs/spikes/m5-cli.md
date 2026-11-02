# M5-01 CLI 도구 권한 스파이크 (2026-11-02)

실제 Claude CLI(haiku, 비대화형 `-p`, `--restricted --strict-mcp-config --setting-sources ""`)로 확인했다. 재현: `cd server && uv run python ../docs/spikes/m5-cli/run_spike.py <allow|fetch|names|latency|events>`. 근거 로그는 [m5-cli/logs/](m5-cli/logs/)(경로·토큰은 가림). 호출은 로그 기준 22회(allow 2, fetch 9, latency 9, events 2)이고, 첫 `allow` 실행은 스크립트 파싱 오류로 결과를 저장하지 못해 그 호출분(최대 2회)이 더 쓰였다. 사례당 표본이 1~3회라 모델 행동의 비결정성은 반영하지 못한다.

## 결론 요약

| 항목 | 결론 | 계획서 반영 |
|---|---|---|
| ① 허용 밖 MCP 도구 | `--allowedTools`만으로 막힌다. 모델이 허용 밖 도구를 불러도 CLI가 권한 오류로 거부하고 서버에 닿지 않는다. `--disallowedTools`를 더하면 도구가 목록에서 빠진다 | M5-13·14는 서버 중계 없이 CLI 규칙으로 간다(8절 위험 문단의 큰 경우는 아니다). 외부 서버 도구마다 `--allowedTools`에 전체 이름을 적고 `--disallowedTools`를 함께 쓴다 |
| ② 내장 `WebFetch` | CLI 규칙만으로는 사설 대역을 막지 못한다 | **M5-11은 ② 경로**: 내장 `WebFetch`를 끄고 서버가 검사하는 내부 MCP `web_fetch`를 만든다 |
| ③ 이름 64자 | `mcp__<서버>__<도구>` 합계가 64자를 넘으면 안 된다. 서버 이름 32자·도구 이름 40자면 79자다 | M5-12 검증에서 전체 이름 64자 이하를 요구한다(Spec 5.6 그대로) |
| ④ 도구 정의 많을 때 | 도구 60개(+기본 2)에서도 첫 토큰 지연 증가는 작다(0개 2.0~2.1초, 20개 2.1~2.4초, 60개 2.0~2.9초, 표본 3회씩). 도구 정의 토큰은 늘어난다 | 도구가 몇십 개 수준이면 `ENABLE_TOOL_SEARCH=false`를 유지해도 된다 |
| ⑤ 이벤트 형식 | 아래 표 | M5-09·11의 요약 추출 방법으로 쓴다 |

## ① 허용 밖 도구 (`logs/allow.json`)

가짜 stdio 서버에 `allowed_ping`·`denied_ping`을 두고 둘 다 부르게 했다. 서버가 받은 호출 기록은 두 경우 모두 `allowed_ping` 하나였다.

- `--allowedTools mcp__fake__allowed_ping`만: 모델이 `denied_ping`을 호출했고 결과는 `Claude requested permissions to use mcp__fake__denied_ping, but you haven't granted it yet.`(`is_error: true`). 서버 호출 기록에는 없다.
- `--disallowedTools mcp__fake__denied_ping`을 더하면: 모델이 `denied_ping`을 부르지 못한다(목록에 없다고 답한다).

한계: 모델이 허용 밖 도구를 부르려 할 때 거부되는 것까지 확인했고, 비대화형이라 권한 질문으로 멈추지 않는다. `mcp__<서버>__*` 와일드카드 허용이 외부 서버에서 어떻게 동작하는지는 시험하지 않았다(Spec 5.6이 외부 서버의 `*` 허용을 거부하므로 필요 없다). ③ 이름 길이는 CLI 호출 없이 계산만 했고 64자 한도 자체는 모델 API의 외부 규칙이다.

## ② 내장 `WebFetch` (`logs/fetch.json`)

로컬 HTTP 서버를 띄워 적중 여부를 보고, 규칙 3종 × 주소 3종(`localhost`, `127.0.0.1`, `169.254.169.254`)을 시험했다. 로컬 서버 적중은 전부 0이었지만 그것이 CLI의 보호는 아니다.

| 주소 | 관찰 |
|---|---|
| `localhost` | 규칙과 무관하게 CLI 내장이 `WebFetch cannot fetch localhost or other hostnames without a dot`로 거부(점 없는 호스트 이름) |
| `127.0.0.1` | http를 https로 올려 요청해 TLS 오류(`WRONG_VERSION_NUMBER`)가 났을 뿐이다. 로컬에 TLS 서버가 있었다면 닿았을 것이다. `WebFetch(domain:127.0.0.1)` 거부 규칙을 쓰면 `denied access to domain:127.0.0.1` |
| `169.254.169.254` | 내장 보호 없이 **실제로 443 연결을 시도**했다(`connect ECONNREFUSED 169.254.169.254:443`). 도메인 허용 규칙만 둔 경우에는 모델이 스스로 거부했을 뿐이다 |

판단: 도메인 규칙은 글자 그대로 같은 호스트만 막는다(시험한 것은 `localhost`·`127.0.0.1` 거부 규칙). `10.x`·`192.168.x`·링크로컬 같은 **대역**, 사설 IP로 해석되는 도메인, 리다이렉트, DNS 재바인딩은 규칙 문법에 대역 표기가 없어 규칙으로 막을 수 없다고 **추론**했고, 직접 시험하지는 않았다(근거는 메타데이터 주소에 실제 연결을 시도했다는 위 관찰). 이 추론이 틀려도 서버 `web_fetch`는 어차피 대역·재바인딩을 직접 검사하므로 ② 경로 결정은 바뀌지 않는다. 그래서 내장 `WebFetch`를 끄고(`--tools`에서 제외) 서버가 직접 검사하는 `web_fetch`를 만든다(M5-11 ② 경로). 이 경우 M5-09의 `--tools`는 `WebSearch`만 켠다.

## ④ 지연 (`logs/latency.json`)

가짜 서버에 더미 도구를 0·20·60개 두고(기본 2개 별도) 각 3회 측정했다. 같은 프롬프트라 캐시가 섞인다.

| 더미 도구 | 첫 토큰(초) | 첫 실행 `cache_creation` | 이후 `cache_read` |
|---|---|---|---|
| 0 | 2.00~2.06 | 639 | 약 2.8~3.1k |
| 20 | 2.11~2.43 | 5,269 | 약 4.9k |
| 60 | 1.99~2.93 | 8,869 | 약 8.5k |

도구 정의는 개당 약 90 토큰(20→60개 구간)이고 캐시되면 지연 영향이 작다. 첫 실행(캐시 없음)에서만 60개일 때 2.9초로 조금 늘었다.

## ⑤ 이벤트 형식 (`logs/events.json`)

| 도구 | `tool_use.input` | 결과에서 뽑을 값 |
|---|---|---|
| `WebSearch` | `{query, mode}` | `user` 이벤트의 `tool_use_result`: `{query, results:[{tool_use_id, content:[{title, url}…]}…]}`. `tool_result.content` 문자열은 `Links: [{"title","url"}…]` 앞부분 JSON을 포함한다 |
| `WebFetch` | `{url, prompt}` | `tool_use_result`: `{bytes, code, codeText, result, durationMs, url}` |

서버가 `web_search` 요약(`query`·`links` 최대 10·`sources` 호스트 최대 3)을 만들 때는 `tool_use_result.results[].content[]`의 `url`을 쓴다(문자열 파싱보다 안정적이다). 이벤트에 `rate_limit_event`도 나온다(M5-03에서 쓴다).
