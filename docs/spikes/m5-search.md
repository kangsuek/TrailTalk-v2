# M5-02 검색 공급자·외부 MCP 후보 스파이크 (2026-11-02)

네이버 검색 API는 실제 키로 `docs/spikes/m5-search/naver_spike.py`를 실행했고(7회, 키는 환경 변수로만 넘겨 파일·로그에 없다), HasData는 Claude 커넥터의 도구 호출로 한국어·영어 검색을 확인했다. `search_USA`(Tavily)는 2026-11-02에 제거해 확인하지 않았다.

## 결론

| 항목 | 결론 |
|---|---|
| `search_naver`(뉴스) | v1 결과 그대로 쓴다. 응답 0.09~0.11초, 필드 `title`·`description`·`originallink`·`link`·`pubDate`. v1의 정렬·거름 전략(기간 있으면 `date` 50건 거르기, 없으면 `sim`)을 이식한다 |
| `search_naver_blog`(블로그) | 새로 만든다. 응답 0.16~0.37초(5회 중앙값 0.20초), 필드 `title`·`description`·`bloggername`·`bloggerlink`·`link`·`postdate`(YYYYMMDD). 호스트는 전부 `blog.naver.com`이라 출처 표시는 호스트 대신 `bloggername`을 쓴다. **날짜 필터는 없고** `sort=date`가 최신순이다. 영어 질의도 결과가 있다 |
| 해외·그 밖의 검색 | **내장 `WebSearch`를 기본으로 한다.** 출처 URL을 `tool_use_result`에서 뽑을 수 있어 `turn.sources`·인용(M5-10)이 된다 |
| HasData | **잠정 채택(보조)**. 구글 검색 품질이 좋고 `tbs`로 기간 필터(`qdr:h/d/w/m/y`)를 줄 수 있다. 외부 MCP 서버 이름은 `hasdata`, 허용 도구는 `hasdata_google_serp_serp_light_getSearchResults`(검색)와 `hasdata_web_scraping_web_scraping_scrapeWebPage`(상세 내용, 아래)로 시작한다(전체 이름 각 61자로 64자 이하). **도구 이름은 Claude 커넥터가 보여 준 이름이며 원격 서버 `tools/list`의 이름과 같은지는 아직 확인하지 못했다(M5-15 ⑥에서 확인하고 다르면 허용 목록을 고친다).** URL은 `?apis=google_serp_serp_light`로 도구를 제한한다. 이름 변경(`google_search`)은 하지 않는다(원격 서버 도구 이름을 바꿀 수 없고 불필요) |
| 외부 도구의 출처 인용 | 외부 MCP 결과는 `turn.sources`에 넣지 않는다(서버마다 결과 구조가 달라 URL을 해석하지 않는 M5-13 규칙 유지). 화면은 M5-13대로 "`<도구>` 사용 중"과 결과를 글자 그대로 보인다 |

## 네이버 ([로그](m5-search/logs/naver.json))

| 종류 | 질의 | 정렬 | 지연(초) | `total` |
|---|---|---|---|---|
| 뉴스 | 코스피 마감 시황 | date | 0.11 | 136,616 |
| 뉴스 | 삼성전자 실적 | sim | 0.09 | 785,903 |
| 블로그 | 제주도 맛집 후기 | sim | 0.37 | 4,282,522 |
| 블로그 | 제주도 맛집 후기 | date | 0.28 | 3,341,834 |
| 블로그 | 아이폰 17 사용 후기 | sim | 0.19 | 177,901 |
| 블로그 | 서울 한강공원 피크닉 경험담 | date(30건) | 0.20 | 40,590 |
| 블로그 | Nvidia earnings | sim | 0.16 | 10,691 |

- 블로그 결과 샘플은 후기·경험담이 잘 나온다. 다만 업체 홍보성 글("내돈내산" 표기, 해시태그 나열)이 섞이므로 `search_naver_blog` 규칙에는 "후기·경험담 참고용이며 사실 확인에는 쓰지 않는다"를 넣는다(광고성 걸러내기는 하지 않는다).
- 블로그에는 기간 필터가 없어 `recency`가 필요하면 `date`로 받아 `postdate`로 거른다(뉴스와 같은 방식). 일 한도(검색 API 25,000회)에 비해 호출량은 작다.
- 도구 인자 안: `query`, `sort`(`sim`·`date`), 블로그는 `recency`(day·week·month)를 선택으로 둔다.

## HasData (커넥터 경유 샘플 2회, 순차 호출)

- 한국어 `파이썬 3.14 출시일`(`gl=kr`, `hl=ko`): 10건 모두 한국어 결과(GeekNews, 공식 문서, 티스토리, velog 등), 제목·요약·날짜 정확. 영어 `Nvidia earnings`(`gl=us`, `tbs=qdr:w`): 최근 1주 결과 8건, 상대 날짜("12 hours ago") 포함.
- 응답에는 `organicResults`뿐 아니라 `relatedSearches`·`filters`·`inlineImages`·`pagination`이 같이 와서 한 번에 약 7~9KB다. 모델에는 전부 가고, 화면 표시용 결과 2000자 절단(M5-13)은 앞쪽 `organicResults` 일부만 보인다.
- 인자: `q`(필수), `gl`, `hl`, `num`(10 이상), `tbs`, `lr`, `location`. 첫 호출 `requestMetadata.status: ok`.
- **확인하지 못한 것**: 실제 원격 MCP 엔드포인트(`https://mcp.hasdata.com/mcp`, `x-api-key`)의 `tools/list`와 지연, 무료 동시 요청 1개 제한의 실제 오류 형태. HasData 키가 서버 `.env`에만 있어 이 스파이크에서 쓰지 않았다. M5-15 ⑥(실제 점검)에서 서버 경로로 확인한다.

## HasData 웹 스크래핑 (검색 결과의 상세 내용, 사용자 요청 확인)

`hasdata_web_scraping_web_scraping_scrapeWebPage`로 위 한국어 검색 1위 결과(`https://news.hada.io/topic?id=23514`)를 `outputFormat: ["markdown"]`, `removeBase64Images: true`로 가져왔다. **가능하다.**

- `status: 200`, 본문이 마크다운으로 온다: 제목, 발행일, 작성자, 본문 요약(주요 기능·변경 사항 목록), 댓글 5개까지 정확히 담겼다. 한국어 깨짐 없음.
- 단 상단 메뉴·하단 링크·언어 목록 같은 **페이지 공통 부분이 함께 와서** 본문 외 군더더기가 크다(약 5KB 중 본문은 절반 정도). `includeOnlyTags`·`excludeTags`(CSS 선택자)로 줄일 수 있으나 사이트마다 선택자가 달라 일반화하기 어렵다. 모델은 군더더기를 건너뛰고 읽을 수 있다.
- 이 도구는 **임의 URL을 HasData 서버가 대신 가져온다.** 우리 서버나 CLI가 사설 대역에 연결하는 것은 아니므로 D7(사설망 차단)의 위험은 없다. 대신 URL 입력이 곧 외부로 나가는 정보이므로 NFR-06 예외(외부 서비스형 서버, 도구 인자로 발화 일부가 서버 밖으로 나갈 수 있음)에 해당하고, `mcp-servers.example.yaml` 주석에 밝힌다(M5-12). 이 도구는 `web_fetch`(M5-11, 서버가 직접 가져옴)와 역할이 겹친다. 기본은 `web_fetch`, JS가 필요한 페이지나 차단된 사이트처럼 직접 가져오지 못할 때 이 도구를 허용 목록으로 두는 보조 수단으로 쓴다.
- `jsRendering`·`proxyType`·`aiExtractRules` 등은 과금이 더 드는 옵션이라 확인하지 않았다. 기본 호출(프록시 기본)만 확인했다.

## 계획서 반영

- M5-09: 내부 MCP는 `search_naver`·`search_naver_blog` 둘, 해외·일반은 `--tools WebSearch`(내장)로 한다. 규칙(`WEB_SEARCH_RULES`)은 "국내 뉴스 → `search_naver`, 국내 후기·경험담 → `search_naver_blog`, 그 밖 → `WebSearch`, 구글 기간 필터가 필요하면 HasData"로 다시 쓴다.
- M5-12·15: `mcp-servers.example.yaml`의 예시와 실제 연동은 `hasdata`(http, `x-api-key` 헤더를 `${MCP_HASDATA_API_KEY}`로 치환, 허용 도구는 검색·스크래핑 두 개)로 한다.

## 비밀 정보 주의

네이버 Client Secret이 대화에 노출되었으므로 `.env`에만 두고 필요하면 네이버 개발자센터에서 재발급한다. 이 저장소의 어떤 파일에도 키 값을 쓰지 않았다(`grep`으로 확인).
