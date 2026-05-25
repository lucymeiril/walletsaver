# 크롤러 영역 기획 v3 — Opus 살붙이기 (v2 반박/수용 + 빠뜨린 시나리오)

> Round-A / 3번 타자. 입력: v1(`crawler-v1-opus.md`), v2(`crawler-v2-gpt.md`).
> 범위: `packages/crawler-admin/` 만. v1·v2는 **수정하지 않는다.**
> 톤: 비개발자 가독, 직설. v2의 안전 타령·동적 차단 회피·운영자 떠넘기기는 깎아낸다. 진짜 약점만 수용.

---

## 0. 본문 요약 (한 화면)

v2는 “있는 기능 vs 만들 기능” 분리, capability 기반 yaml schema, 신고큐 가중치, circuit breaker 연결, 코스트코 lane 분리 — **이 다섯 개는 사실로 인정하고 v3가 흡수한다.**

대신 v2가 운영자 워크밴치(브라우저 캡처)를 “학습용 비상 경로”로 격하한 부분, ToS/IP 통보를 “협상 채널”로 떠넘긴 부분, headful을 “서버에서 안 뜬다”로 단정한 부분, 자동 전환을 retry budget으로 묶어 사실상 한 번만 시도하게 만든 부분 — **이 네 개는 안전 타령이라 배척한다.** 사용자 명시 요구는 “전용 브라우저로 검색·일부 긁기·영구 등록을 프론트에서” 하는 것이고, 운영자 워크밴치는 비상이 아니라 **본 사이트 구조 변경/캡차 대응의 1급 도구**다.

v3의 한 줄: **“capability yaml + 도메인별 circuit breaker + 운영자 워크밴치(1급) + 마트별 lane 분리. 안전·격하·규격 놀이는 다 거른다.”**

---

## 서문 — v2 응답 정책

### S-1. 수용 약점 (그대로 v3에 박는다)

1. **공통 엔진 4종은 코드에 없다.** 현재는 `engine/strategies/*`와 마트별 `crawler.py`가 각자 구현. v3는 “신규 작업”으로 명시한다.
2. **yaml schema가 느슨하다.** `PluginLoader.validate_config()`가 강제하는 건 name/version/category/difficulty/dependencies 뿐. 핵심 운영 키(`entrypoints`, `source_map`, `output.minimum_rows`, `field_coverage_thresholds`, `live_readiness`, `waf_strategy`)는 강제 안 됨. **capability 기반 스키마로 진화시킨다.**
3. **circuit breaker가 크롤러 전략 루프에 연결 안 됨.** `pipeline/circuit_breaker.py`는 존재하지만 DB ingestion 쪽만 씀. v3에서 strategy escalation에 정식 연결.
4. **홈플러스는 SSR이 아니라 SPA Playwright**다. v1 표 오류. **사실관계 정정**.
5. **이마트는 “SSR+카드”가 아니라 `__NEXT_DATA__` 추출.** v1 표 오류. 정정.
6. **코스트코 yaml(0.4.0, strategy:requests, live_ready:true)이 실제 코드(Playwright/OCC 중심)와 어긋남.** yaml 마이그레이션 필요.
7. **신고큐는 단순 리스트면 악용된다.** 그룹화/유니크 신고자/저신뢰 사용자 가중치 필요.
8. **코스트코 단일 사이클 10분+ 문제.** 전역 `MAX_CONCURRENT_CRAWLS=5`만으로 부족. **도메인/IP별 토큰버킷 + 카테고리 샤드 + cron 지터** 필요.
9. **차단 라벨은 비개발자 언어 2층 구조**가 맞다. “보안벽이 자동 요청으로 판단함” + 접힌 `AWS WAF 202`.
10. **30개+ 소스 시대에는 카드만으로 운영 안 됨.** 테이블 모드/문제만 보기/검색 추가.

### S-2. 배척 (안전 타령 / 동적 차단 회피 / 운영자 떠넘기기)

1. **operator_capture를 “학습용 비상 경로”로 격하 (v2 §E).**
   - 사용자 명시 입장: “전용 브라우저로 상품 검색·페이지 일부 긁기·영구 등록을 **프론트에서**”. 운영자 워크밴치는 **1급 시민**이다.
   - “비상 경로” 표현은 사실상 “쓰지 마라”로 굳고, UI에서 버튼이 안 보이는 결과로 흐른다. 거부.
   - 단, v2가 한 말 중 **“반복되는 차단은 다음 실행부터 코드/프로필/쿠키 jar로 흡수”**는 좋은 운영 룰이므로 채택. 워크밴치는 **자동화의 입력 장치이자 동시에 즉시 수확 도구**다 — 둘 다.

2. **ToS/IP 차단 통보 시 “throttle profile 전환 → 협상 채널” (v2 §C-1).**
   - “협상”은 사람 일이고, 코드 영역이 아니다. 크롤러 v3 산출물은 **증거 로그(요청 수/UA/시간대/경로)** 자동 보존까지만 한다. 협상 템플릿/감축 모드는 운영 매뉴얼이지 기획 산출물이 아님.

3. **“headful은 서버에서 안 뜬다 → operator PC로 빼라” (v2 §C-7).**
   - 사실 일부분, 결론 과잉. Windows 운영기/전용 worker/Xvfb·VNC·container display 옵션 다 살아있다. **별도 Playwright headful worker pool**을 두면 끝난다. “관리자 PC로 빼라”는 운영자 떠넘기기.

4. **자동 전환의 “retry budget 1~2회/사이클” 상한 (v2 §B-2).**
   - circuit breaker로 무한루프 막는 건 맞지만, **사이클당 1~2회 상한**은 사실상 자동 복구를 죽인다. v3는 “**도메인별 backoff + escalation 시퀀스 정해진 만큼은 끝까지 간다**”로 갈음. 한 사이클에 requests→Playwright headless→Playwright headful(워크밴치 자산 활용)→다음 cron 으로 이월, 이게 표준. budget이 아니라 **escalation depth가 yaml에 박혀 있고 다 소진하면 cooldown** 이다.

5. **D-3 4개 금지(v1)를 “그것도 안전 타령”으로 깔 여지** — v2가 직접 깔진 않았지만 깔 만한 자리. **양보 안 함.** captcha 자동풀이/자격증명 도용/WAF 토큰 위조/robots 위반 강제진입은 합법/불법 경계라 코드 단에서 차단 유지.

### S-3. v2의 v3 질문 5개에 대한 답

1. **“현재 있는 기능 vs 신규 작업 표로 분리?”** → **그렇다.** 본 문서 §D-0 표가 그것.
2. **“yaml schema는 고정 4엔진 vs capability registry?”** → **capability registry.** v2 제안 수용. §D-1.
3. **“operator_capture를 학습/fixture 확보용 비상 경로로 격하?”** → **아니. 1급 시민으로 둔다.** 사용자가 직접 지시한 “전용 브라우저 워크밴치”가 이 자산을 정식 도구로 쓴다. 단 “반복 차단은 코드로 흡수”는 같이 한다. §D-3.
4. **“코스트코를 별도 lane으로 분리?”** → **그렇다.** 도메인별 토큰버킷 + long-running lane + 카테고리 샤드. §B-5, §D-4.
5. **“UI를 테이블 모드로 먼저?”** → **둘 다.** 상위 위험 5~10개는 카드(정보밀도), 나머지는 테이블(필터/검색/문제만 보기). §E.

---

## A. 사실관계 정정 (v1 오류만)

| v1 표기 | 실제 코드 | 정정 |
|---|---|---|
| 홈플러스 “SSR” | `HomeplusCrawler` mfront SPA, `strategy: playwright`, `public_search_playwright_spa` | **SPA Playwright 우선 + HTTP fallback** |
| 이마트 “SSR + 카드 파싱” | `EmartCrawler` Next.js `__NEXT_DATA__`/검색 페이지 requests | **Next.js JSON 추출 (requests)** |
| 코스트코 yaml v0.4.0 / strategy:requests / live_ready:true | 실제 코드는 Playwright + OCC API XHR 인터셉트 + HTML fallback | **yaml 자체가 stale.** 마이그레이션 필요 (D-1에서 처리) |
| 롯데마트 “240건 안정” + yaml `status: blocked_by_source_waf_http_202 / live_ready:false` 공존 | 동시 표기 충돌 | **yaml을 240건 실측에 맞게 `live_ready: true` + waf_strategy 블록**으로 갱신 (D-1) |

그 외 v1 사실관계는 유효. v2가 추가로 깐 “공통 엔진 4종은 실재 아님”은 오류 정정이 아니라 v1 자신이 “기획”이라고 명시한 부분이라 §B-1에서 진화 형태로 다룬다.

---

## B. v1 자기검증 5포인트 + v2 약점 통합 재답변

### B-1. yaml schema 진화 (4엔진 → capability registry)

v1은 “SsrInitialState/PaginatedCard/SearchKeyword/PlaywrightHeadful 4종”을 못박았다. v2가 정확히 깠다: GraphQL/cursor/infinite scroll/WebSocket/signed XHR/app API 혼합이면 4종으로 안 잡힌다. **수용한다.**

v3 yaml schema (필수 키 강제):

```yaml
name: lottemart
version: 1.0.0
category: mart

capabilities:
  transport:     [html, xhr]              # html | xhr | graphql | websocket | app_api
  render:        [none, playwright_headless]
  pagination:    [page_param]             # | cursor | infinite_scroll | load_more
  extraction:    [css, jsonpath]          # | graphql_edges | intercepted_response
  session:       [cookie_jar]             # | stateless | persistent_profile | operator_capture
  anti_blocker:  [ua_rotation, referer_chain, sleep, headful_fallback]

entrypoints:
  crawl_sale_listing: { module: ..., class: ... }
  fetch_single_product: { module: ..., class: ... }
  ingest_operator_capture: { module: ..., class: ... }

source_map:
  - id: weekly_sale
    url_template: "https://.../sale?page={page}"
    parser_inputs: [initial_state, embedded_json, card_html]
    selectors: { ... }

output:
  minimum_rows: 200
  field_coverage_thresholds: { name: 0.95, sale_price: 0.90, detail_url: 0.85 }
  required_fields: [name, sale_price, detail_url]

waf_strategy:
  detect: [http_202, akamai_403, x-awswaf-token]
  escalation:
    - { from: requests,             to: playwright_headless, after_failures: 2, cooldown_sec: 60 }
    - { from: playwright_headless,  to: playwright_headful,  after_failures: 2, cooldown_sec: 300 }
    - { from: playwright_headful,   to: operator_workbench,  after_failures: 2, cooldown_sec: 1800 }

rate_limit:
  per_domain_rps: 0.1     # 도메인별 token bucket
  page_sleep_sec: 10
  jitter_sec: [2, 8]

live_readiness:
  fixture_pass: true
  bounded_diagnostic_pass: true
  operator_approval: true
```

**마이그레이션 정책:**
- `PluginLoader.validate_config()` 강제 키를 위 schema로 확장.
- 기존 yaml(롯데/이마트/홈플/코스트코/코코달인 + 핫딜 9종 + 쇼핑 8종) 1:1 마이그레이션 PR 한 번에. **타입 일관성**(rate_limit_seconds: dict vs 숫자, entrypoints: list vs dict) v2 지적 그대로 수용.
- schema 버전 키 `schema_version: 2`. loader가 1이면 자동 컴파일 + 경고.

### B-2. circuit_breaker 트리거/완화 룰

v1은 “자동 전환 토글”만 말하고 `pipeline/circuit_breaker.py` 연결 빠뜨림. v2 지적 그대로 수용.

**키:** `(source_id, domain, egress_ip, blocker_signature)` 4-튜플.
**상태:** `closed → open → half_open → closed`.
**트리거:**
- 같은 blocker(WAF 202 / Akamai 403 / bot manager / timeout / parser empty) 연속 2회 → `open`.
- 필드 충실도 핵심필드(name/sale_price/detail_url) <80% 2회 연속 → `open`.

**완화 (cooldown):**
- WAF/Akamai: 30분~수시간 (yaml `cooldown_sec`).
- Parser empty: 다음 cron까지.
- bot manager: 1시간.

**half_open:** 1회 시도 → 성공 시 closed, 실패 시 다시 open(지수 백오프).

**escalation depth (사이클당 상한 아님):**
- yaml `waf_strategy.escalation` 시퀀스를 끝까지 시도 가능. 단 각 단계마다 cooldown.
- v2가 말한 “retry budget 1~2회” 상한은 거부. 대신 **단계 사이 cooldown으로 IP 보호**.
- “requests→PW→UA→requests→PW→UA” 같은 핑퐁은 escalation 시퀀스로 원천 차단 (한 방향).

### B-3. 신고큐 악용 방지

v1의 “신고 100건 = 우선순위 1위”는 v2 지적대로 장난/경쟁사 폭탄에 무방비. 수용.

**그룹 키:** `source + canonical(detail_url)` (URL normalize: 쿼리 정렬, tracking 파라미터 제거).

**가중치 공식 (느슨, AI 영역 아님):**
- 유니크 신고자 수 (가입 7일 미만 0.3, 1개월 미만 0.7, 그 외 1.0)
- 같은 사용자 같은 URL 24시간 dedup
- 최근 크롤 실패/필드 결측과 일치 시 +1.0
- 핫딜러(`packages/web-frontend` 기준 heavy user) 가중 1.5
- 동일 IP 대량 신고 → 자동 0.1로 강제

**관리자 화면 표시:** “쿠팡 생수 URL 1건 / 신고 37 / 유니크 9 / 최근 크롤 Akamai 403” 식 그룹 한 줄. v2 D-4 컬럼 그대로 채택.

**액션:** 재크롤 / 영구 등록(`fetch_single_product` cron 박기) / 무시 / 병합 / source 단위 차단.

### B-4. operator_capture(워크밴치) UX — **1급 시민으로**

v1은 “브라우저로 풀고 와주세요”로 끝났다. v2는 거꾸로 “비상 경로로 격하”했다. **둘 다 틀렸다.**

v3 입장: **운영자 워크밴치는 (a) 본 사이트 구조 변경/캡차 대응의 정식 도구이자 (b) 사용자가 직접 지시한 “전용 브라우저로 상품 검색·일부 긁기·영구 등록” 프론트 기능의 기반.** 1급.

**구체 흐름 (v2 §B-4 흐름 기본 채택 + 1급 시민화):**

1. 관리자 카드/테이블에서 “워크밴치 열기” (항상 표시, 비상 표현 X).
2. 백엔드 `OperatorBrowserSessionManager.open(url, source_id)` — Playwright headful + persistent profile(`crawlers/{source}/profile/`).
3. 프론트가 **라이브 뷰**(스크린샷 스트리밍 또는 VNC iframe) + 상태 패널(쿠키/URL/네트워크).
4. 운영자가 한 화면에서: 로그인 1회 / 캡차 / 지역 선택 / 검색 / 카드 클릭.
5. **세 가지 출력 동시에:**
   - **a) 즉시 수확** — 운영자가 본 페이지의 상품 카드를 골라 “영구 등록” (사용자 직접 지시 사항). `fetch_single_product` cron에 등록.
   - **b) 세션 자산화** — 쿠키 jar / persistent profile / HAR 일부를 다음 자동 사이클이 재사용 (아카라이브 로그인 후순위 시나리오 핵심).
   - **c) fixture 화석화** — HTML/JSON 스냅샷을 `crawlers/{source}/fixtures/`에 저장. selector drift 탐지 기준이 됨.
6. `ingest_operator_capture` entrypoint가 (b)+(c)를 재파싱해서 정합성 검증.

**자동화와의 관계 (v2가 한 말 중 살릴 부분):** 같은 차단이 워크밴치로 한 번 풀리면, 다음 cron부터는 **persistent profile + 쿠키 jar 재사용**으로 자동화 경로에서 통과시킨다. 워크밴치를 매일 누르게 만드는 건 실패. 하지만 “비상 경로니까 평소엔 숨겨라”도 실패. **항상 보이게 두고, 누를 일이 점점 줄어드는 것**이 v3의 목표.

### B-5. 코스트코 동시성

v1은 우려만, v2가 숫자로 깠다(15카테고리 × 10s + Playwright + 페이지/검색 = 10분+). 수용.

**v3 정책:**

- **scheduler `max_instances=1`** (현재 그대로 유지, 동일 job 중복 방지).
- **도메인별 token bucket** `engine/rate_limiter.py`를 마트 crawler.py 직접 요청 경로에도 통과시키게 리팩토링 (v2 §A-4 지적). `costco.co.kr` per_domain_rps=0.1.
- **long-running lane**: 전역 `MAX_CONCURRENT_CRAWLS=5` 외에 별도 `LONG_RUNNING_LANE=1` (코스트코/홈플 Playwright SPA 큰 작업 전용). 짧은 핫딜 9종은 본 lane을 안 막는다.
- **카테고리 샤드**: 코스트코 15 카테고리를 5×3 샤드로 분할. cron 시간에 샤드별 차등 발행. 한 샤드 = 약 3~5분.
- **cron jitter**: 07:00 동시 출발 금지. yaml `rate_limit.jitter_sec`로 0~600s 분산.
- **UI 표시**: “현재 실행 3/5, long-running 1/1, 코스트코 샤드 2/5 진행, 예상 종료 +7분.”

---

## C. 빠뜨린 시나리오 보강

### C-1. Akamai/Cloudflare 막힘 시 진짜 대응 (회피 코드 아님)

v2가 “ToS 통보 시 협상 채널”로 떠넘긴 자리. 코드 영역만 분리:

1. **시그니처 감지** — `pipeline/blocker_signatures.py`(신규). HTTP status × 헤더(`server: AkamaiGHost`, `x-awswaf-token`, `cf-mitigated`) × HTML 패턴(`Pardon Our Interruption`, Cloudflare challenge) 매칭.
2. **escalation 시퀀스 (yaml에 박힘)**: requests → Playwright headless → Playwright headful + persistent profile → 워크밴치 알림.
3. **persistent profile 재사용** — 워크밴치에서 한 번 통과한 쿠키/스토리지를 다음 자동 사이클이 가져다 씀.
4. **egress IP 풀** (선택) — 운영기 외에 백업 egress 1~2개. 같은 도메인이 한 IP만 학습 못 하게.
5. **증거 보존** — 매 차단 시 요청/응답 헤더 + HTML 첫 4KB + 스크린샷(Playwright 단계) 저장. `crawlers/{source}/blocker_evidence/`.

**금지 명시 (v1 D-3 유지):** captcha 자동풀이 / 자격증명 도용 / WAF 토큰 위조 / robots 위반 강제진입.

### C-2. 마트 사이트 구조 변경 자동 감지

v2 §F-1, §F-2 채택.

- 각 selector / jsonpath / URL template에 **drift 점수** (최근 7일 hit rate, row count 추이).
- “롯데 `productEntities` path 100→0, card selector 50→0” 같은 **경로 단위 알람**.
- fixture vs live DOM **구조 diff**(태그 트리 hash).
- 트리거 시 카드 빨강 + 셀렉터 편집 UI 바로가기.

### C-3. 일부 상품만 재크롤 / 신규 상품 영구 등록 (사용자 직접 지시)

사용자 요구: “전용 브라우저로 검색→일부 긁기→영구 등록”.

- **부분 재크롤**: 카드의 “부분 재크롤” → 카테고리/검색 키워드 선택 모달 → 해당 source_map 항목만 실행.
- **영구 등록**: 워크밴치 또는 신고큐에서 URL 1개 → `fetch_single_product` cron 등록 → yaml `tracked_urls`에 추가 → 매일 갱신.
- **목록 출처는 워크밴치에서 직접**: 운영자가 검색 후 골라 “이 5개 등록”. tracked_urls에 5건 박힘.
- **해제**: 동일 UI에서 토글로 cron 제거.

### C-4. 쿠팡 같은 동적 상품 — 추적 품목 선택 정책

쿠팡은 Akamai 100% 차단이라 자동 카탈로그 수집 불가(`coupang/plugin.yaml` 검증). 그렇다고 “안 함”이 답은 아님.

- **tracked_urls 모델만 운영**: 워크밴치에서 운영자가 관심 상품을 찾아 등록 → 등록된 URL만 주기적으로 `fetch_single_product`.
- **카탈로그 자동 수집 X, 가격 추적 O.** 이게 합법/현실 양립의 유일 해.
- 사용자/핫딜러 신고에서 들어온 쿠팡 URL도 동일 경로.

### C-5. 코코달인/오피넷/algumon 별도 어댑터

- **코코달인**: 마트형(`marts/cocodalin`)과 핫딜형(`hotdeals/cocodal`) 둘 다 존재. v1이 짚었지만 진화 누락. v3에서는 **둘이 capability schema는 같고 source_map만 다른** 형태로 정렬.
- **오피넷**: 공공 API. capability `transport: [xhr]`, `session: stateless`. 차단 escalation 불필요(yaml에 `waf_strategy: disabled`). 그러나 schema 진화에선 같은 모양.
- **algumon**: requests + 30분 주기. capability `transport: [html]`, render none. 안정.

요지: **마트와 어댑터를 같은 schema 안에 두되, capability 조합으로 자연 분기.** 별도 코드 경로 만들 필요 없음.

### C-6. 아카라이브 로그인 대응 (후순위) — 운영자 1회 + 세션 재사용

- **운영자 워크밴치에서 1회 로그인** → persistent profile 저장 (`crawlers/hotdeals/arca/profile/`).
- 자동 사이클은 이 profile을 마운트해서 진입.
- 세션 만료/재로그인 필요 시그니처 감지 → 워크밴치로 알림.
- 자격증명을 코드에 박지 않는다. profile 디렉토리만 운영.
- **자동 로그인 폼 입력 시도 금지** — 자격증명 도용 회피, robots/ToS 회피. 사람이 한 번 누른다.

### C-7. 카테고리/검색 URL 변경

- yaml `source_map[].url_template`이 진실의 원본.
- live drift: 200 OK인데 row 0 → URL 변경 의심 → 셀렉터 편집 UI에서 URL도 같이 수정.
- 검색 키워드 리스트(`search_keywords`)도 yaml 폼에서 편집.
- 변경 시 git diff 미리보기 + “테스트 실행 1회” 후 디스크 반영.

### C-8. 가격 표시 변경 (g / 100g / 1L) — DB 단위 정규화 연결

크롤러는 **정규화하지 않는다.** raw 그대로 + 메타만 전달.

- 산출 필드: `sale_price` (정수, KRW), `unit_text` (원문 “1.5L”, “100g당”), `unit_quantity` (정규화 시도 없이 raw), `package_quantity` (있으면).
- DB-admin/AI-admin 영역이 정규화 책임. 크롤러는 raw 보존만.
- yaml `output.required_fields`에 `unit_text` 권장(필수 아님).

### C-9. 크롤 빈도 / 리트라이 / 지연 정책

- **빈도** (cron, yaml `schedule`):
  - 마트 4사: 일 1회 새벽 04:00~07:00 (jitter 분산).
  - 코코달인: 일 2회.
  - 핫딜 (algumon/ppomppu/fmkorea/clien/quasarzone): 30~60분.
  - 아카라이브: 1시간.
  - 오피넷: 1시간.
  - tracked_urls(`fetch_single_product`): 6시간.
- **리트라이**: yaml escalation 시퀀스 그대로. 단계 사이 cooldown.
- **지연**: per_domain_rps 0.1~0.5, page_sleep 5~10s, jitter ±20%.
- **저녁 핫딜 시간대 보호** (v2 §C-3 채택): 18:00~23:00에는 무거운 마트 full crawl 금지. delta/tracked_urls/신고큐 처리만.

### C-10. 라이브 모니터 / 데이터 품질 게이트 (누락 검출)

v1 F절 토대 유지 + v2 §F-1/§F-2 추가.

- volume gate / field coverage gate / 현실성 gate (v1).
- selector drift gate / URL drift gate (v2).
- **누락 의심 자동 진단**: 샘플링 검색 URL 비교 — 같은 키워드(우유/계란/라면 같은 단골 키워드 10개)를 별도 search probe로 돌려, 메인 크롤 결과와 교차 검증. 메인 0건인데 probe에서 다수 검출 → “누락 의심” 카드 빨강.

---

## D. 엔진/플러그인 보강

### D-0. 있는 것 vs 만들 것 (v2 §H-1 응답)

| 항목 | 있음 | 만들 것 (v3) |
|---|---|---|
| `engine/strategies/*` (requests/cloudscraper/selenium/undetected/playwright) | ✅ | capability registry로 매핑 |
| `engine/executor.py` strategy cascade | ✅ | yaml escalation 시퀀스 입력으로 받게 변경 |
| `engine/rate_limiter.py` 도메인 토큰버킷 | ✅ (executor 경유만) | 마트 crawler.py 직접 호출 경로에도 강제 |
| `pipeline/circuit_breaker.py` | ✅ (DB ingest용) | 크롤러 strategy loop에 연결 |
| `pipeline/quality.py` CRITICAL_FIELD_THRESHOLDS | ✅ | UI 카드 시각화 |
| `pipeline/diagnostics.py` bounded | ✅ | 새 소스 위저드와 결합 |
| `scheduler/scheduler.py` APScheduler | ✅ | long-running lane 추가 |
| `concurrency.py` `MAX_CONCURRENT_CRAWLS` | ✅ | + `LONG_RUNNING_LANE` |
| `OperatorBrowserSessionManager`/`OperatorWorkbenchStore` | ✅ (이전 라운드 자산) | 1급 UI로 승격, 영구등록 연결 |
| capability yaml schema | ❌ | **신규** |
| selector drift 점수 | ❌ | **신규** (`pipeline/drift.py`) |
| blocker signature catalog | ❌ | **신규** (`pipeline/blocker_signatures.py`) |
| 신고큐 백엔드 | ❌ | **신규** (`api/routes/reports.py` + `pipeline/report_queue.py`) |
| 라이브 뷰(스크린샷 스트림/VNC) | ❌ | **신규** (워크밴치) |
| selector 편집 UI | ❌ | **신규** |

### D-1. yaml schema 진화 + 마이그레이션

§B-1 schema 그대로. 마이그레이션:

1. `schema_version: 2` 도입, loader가 1을 자동 컴파일.
2. PR 한 번에 25개 plugin.yaml 일괄 변환 (수기 + 스크립트 보조).
3. 검증: `PluginLoader.validate_config()` 확장 + fixture 회귀.
4. **롯데 yaml** `live_ready: true` 로 갱신(실측 240건 안정 반영) + `waf_strategy` 채움.
5. **코스트코 yaml** v0.5.0 + strategy Playwright/OCC 반영 + 카테고리 샤드 정의.

### D-2. circuit_breaker 트리거/완화 룰

§B-2 그대로. `pipeline/circuit_breaker.py`에 `crawler_strategy` 도메인 추가. UI에 상태 표시(open/cooldown 잔여 시간).

### D-3. 운영자 헤드풀 워크밴치 (rd2-cocodalin/operator-capture 자산 활용)

- **자리매김**: 회피가 아니라 **본 사이트 구조 변경/캡차 대응 + 영구 등록 도구**. 1급.
- **재사용**: 이전 라운드 자산(`OperatorBrowserSessionManager`, `OperatorWorkbenchStore`, persistent profile 디렉토리) 그대로. 신규 작업은 라이브 뷰 프론트 + 영구 등록 API.
- **삭제 대상**: 과거 `operator_workbench.py`가 박았던 `captcha=False, stealth=False` 같은 작업마비 분기는 v1에서 추방 선언, v3도 유지 (재발 금지).

### D-4. Playwright 풀 (코스트코/롯데 SPA fallback / 홈플)

- **headless worker pool**: scheduler 옆에 5개 워커. yaml `render: playwright_headless` 만나면 이쪽.
- **headful worker pool**: 별도 1~2개. Windows 운영기 desktop session 또는 Xvfb 기반. yaml `render: playwright_headful` 또는 escalation 단계로 진입.
- **profile 마운트**: 각 소스 폴더의 `profile/` 디렉토리를 워커가 `--user-data-dir`로 사용.
- **자원**: 한 워커당 메모리 ~1.5GB 가정 + CPU 1코어. 운영기 사양 따라 조정.
- **격리**: 마트 풀과 핫딜 풀 분리 가능(yaml `worker_pool: marts|hotdeals|workbench`).

---

## E. 관리자 UI/UX 보강

### E-1. 사용자 직접 지시: “전용 브라우저로 검색·일부 긁기·영구 등록”을 프론트에서

- 워크밴치 패널이 **크롤러 페이지 1급 탭**. 카드 한 구석이 아니라.
- 흐름: 소스 선택 → 시작 → 라이브 뷰 → 운영자가 검색/탐색 → 상품 카드에 “등록” 체크 → “영구 등록 5건” → 완료.
- 등록된 URL은 카드 “tracked_urls: 23개” 표시. 클릭 시 목록/주기/마지막 갱신.

### E-2. 누락/실패 카드 1-click 재시도

- 빨강/노랑 카드의 “즉시 재시도” / “전략 전환 재시도” / “부분 재크롤” / “워크밴치 열기” 4개 액션 항상.
- 신고큐 N건이 있으면 카드 상단 배지 + 1-click “일괄 재크롤”.

### E-3. yaml 직접 편집 UI (도움말/검증)

- 핵심 섹션(`source_map`, `selectors`, `url_template`, `search_keywords`, `parser_inputs`, `output.minimum_rows`, `output.field_coverage_thresholds`, `waf_strategy`)을 폼 + 코드 에디터 두 모드.
- 각 필드 옆에 한 줄 도움말 (“이 셀렉터는 카테고리 페이지의 상품 카드 묶음을 가리킨다”).
- 저장 시: schema validate → git diff 미리보기 → **테스트 실행 1회**(bounded diagnostic) → 통과 시 디스크 반영 + hot reload.
- 통과 실패: 디스크 반영 안 함. 화면에 실패 사유.

### E-4. 라이브 카운트 추이 알림 임계치

- yaml `output.minimum_rows` 미달 즉시 토스트 + 카드 빨강.
- 이전 7일 평균 대비 -30% 하락도 자동 알람(점진 drift).
- 핵심 필드 결측 임계 초과 알람.
- 임계는 yaml 단위. 전역 default 없음(소스별 특성이 너무 다름).

### E-5. 30개+ 소스 운영 (v2 §D-3 채택)

- 카드 모드(상위 위험 5~10) + 테이블 모드(전체) 토글.
- 필터: 카테고리 / 상태(빨강/노랑/초록) / live_ready / 최근 실패.
- 검색: 소스명/도메인.
- “오늘 실패만”, “live_ready=false만” 프리셋.

---

## F. 데이터 품질 게이트

### F-1. 마트별 최소 카운트 (yaml 박힘)

- 롯데마트 ≥ 240 (실측 기반)
- 이마트 ≥ 270
- 홈플러스 ≥ 195
- 코스트코 ≥ 300 (목표, Playwright/OCC 완료 후)
- 코코달인(마트) 최소치는 코드 안정화 후 결정 — 임시 ≥ 50
- 핫딜류 ≥ 30 (소스별 차등)
- 미달 → 카드 노랑 → 연속 2회 → 빨강 + circuit breaker 후보

### F-2. 누락 의심 자동 진단 (샘플링 검색 URL 비교)

- 단골 키워드 10개(우유, 계란, 라면, 즉석밥, 휴지, 세제, 콜라, 김치, 식용유, 만두)로 별도 search probe.
- 메인 크롤 결과에 해당 키워드 매칭 0~소수인데 probe에서 충분히 나오면 → “누락 의심”.
- 진단 결과는 카드에 “probe vs main: 우유 12 / 0” 표시.
- 임계 초과 시 selector drift 알람 트리거.

---

## G. 모듈/경계 보강

### G-1. ai-admin / db-admin / web과의 API 경계

| 영역 | 크롤러가 제공 | 크롤러가 받음 | 금지 |
|---|---|---|---|
| ai-admin | raw record stream, blocker evidence, selector drift signal | yaml selector patch suggestion (review 후 적용) | AI가 크롤러 직접 import / DB 직접 쓰기 |
| db-admin | `CrawlResult` (DiscountItem + 소스 메타) | tracked_urls 변경 통지 | DB에서 크롤러 내부 모듈 import |
| web-frontend | source 상태 read-only API, 신고 큐 POST | 사용자 신고 payload | 프론트가 크롤러 yaml 직접 쓰기 (관리자 UI 경유만) |

### G-2. crawler raw → ai_ingestion 페이로드 schema 안정성

```json
{
  "schema_version": 2,
  "source_id": "lottemart",
  "collection_path": "marts/lottemart/weekly_sale",
  "crawl_intent": "sale_listing",
  "source_record_key": "lottemart:weekly_sale:1234567",
  "captured_at": "2026-05-12T04:13:22+09:00",
  "raw_html_ref": "s3://.../...html.gz",
  "item": {
    "name": "...", "sale_price": 1990, "regular_price": 2490,
    "detail_url": "...", "image_url": "...",
    "unit_text": "1.5L", "brand": "...", "category_hint": "음료",
    "period_text": "5/10~5/16"
  },
  "diagnostics": { "blocker": null, "selectors_hit": {...} }
}
```

- `schema_version` 명시. AI/DB는 버전 다르면 거부.
- `source_record_key` 안정성 보장 (URL 정규화 + ID 추출).
- `raw_html_ref`로 사후 재파싱 가능.

---

## H. 로드맵 P0/P1/P2 재정렬

### P0 — 라이브 직전 (지금 ~ 2주)

- 롯데 yaml `live_ready: true` + waf_strategy 정합화 (실측 240 반영)
- 코스트코 yaml v0.5.0 마이그레이션 (Playwright/OCC 반영)
- circuit breaker ↔ crawler strategy loop 연결
- 도메인별 rate limiter를 마트 crawler.py 직접 경로에도 적용
- volume / field coverage gate UI 표시 (행 수만 → 충실도+행 수)
- WAF/Akamai 시그니처 카탈로그(`blocker_signatures.py`) 1차 + 라벨 2층 구조

### P1 — 운영 편의 (2주 ~ 6주)

- capability yaml schema v2 + 25개 yaml 일괄 마이그레이션
- 운영자 워크밴치 라이브 뷰 + 영구 등록 + tracked_urls 모델
- 셀렉터/URL 편집 UI (yaml 폼 + diff + 1회 테스트)
- 신고큐 백엔드 + 그룹화 UI + 가중치
- long-running lane + 코스트코 카테고리 샤드
- 테이블 모드 / 문제만 보기 / 검색
- selector drift 점수 + 누락 의심 자동 진단

### P2 — 확장 (6주 +)

- Playwright headful worker pool 정식화 (Windows desktop or Xvfb)
- 새 소스 onboarding 위저드 (v2 §C-4 10단계)
- 커뮤니티 플러그인 격리 실행기 (인터페이스는 P1, 실행은 P2)
- AI 셀렉터 patch 제안 입력 채널 (ai-admin 영역, 크롤러는 schema만)
- egress IP 풀 도입 (선택)

---

## I. 안전 타령 / 동적 차단 / 운영자 떠넘기기 배척 선언

- v2가 “operator_capture를 학습용 비상 경로로 격하”한 것은 **배척**. 사용자 명시 요구가 워크밴치를 프론트 정식 도구로 두는 것이라 양보 불가.
- v2 §C-1 “ToS 통보 시 throttle 전환 → 협상 채널”은 **배척**. 코드 영역 아님. 증거 로그까지가 v3 산출. 협상은 운영 매뉴얼로 분리.
- v2 §C-7 “headful은 서버에서 안 뜬다 → operator PC” **배척**. headful worker pool로 해결.
- v2 §B-2 “자동 전환 retry budget 1~2회/사이클” **배척**. escalation depth + 단계별 cooldown으로 갈음. 자동 복구를 함부로 죽이지 않는다.
- v2 §F-4 “AB test도 budget 안에서만” — 좋은 원칙이지만 “안에서만”을 절대화하는 건 **부분 배척**. circuit breaker 안에서면 충분.
- yaml schema 고정 / retry 횟수 강제 / depth 강제 같은 **동적 대응 차단 규격**도 배척. yaml에 박힌 escalation 시퀀스를 끝까지 시도 가능해야 한다.
- “안전”이라는 이름으로 기능 자체를 못 돌게 만드는 분기는 v1 D-3에서 추방 선언, v3도 유지. `requires_operator_capture=True` 같은 진입 차단 패턴 재발 금지.

**유지하는 선:** captcha 자동풀이 / 자격증명 도용 / WAF 토큰 위조 / robots 명시 위반 강제진입 4종. 이건 합법/불법 경계라 양보 안 함.

---

## 자기검증

### v2에 굽힌 흔적 점검

- **굽힘?** circuit breaker / 신고큐 가중치 / 코스트코 lane / capability schema / yaml 강제 키 / 비개발자 라벨 / 테이블 모드 — **이건 굽힌 게 아니라 사실이라 수용**. 안전 타령 아님.
- **굽힘 아님?** operator_capture 격하 거부 / “retry budget 1~2회” 거부 / “headful → operator PC” 거부 / “ToS 협상 채널” 거부 — **명시적으로 배척**.
- 결론: 안전 타령에 굽힌 자리는 없다고 자평.

### 동적 대응 차단 흔적 점검

- yaml에 박은 escalation 시퀀스는 “횟수 강제”가 아니라 “경로 명시”. depth는 yaml에서 조절 가능.
- cooldown은 IP 보호 목적이지 자동화 마비 목적이 아님.
- circuit breaker open 상태도 cooldown 후 half_open으로 자동 복귀.
- 워크밴치도 1급으로 노출, 숨김/격하 없음.

### v4가 깔 만한 3-5포인트

1. **capability yaml schema v2 마이그레이션 비용**. 25개 plugin.yaml 일괄 변환은 PR 하나로 안 끝난다. schema_version 1↔2 공존 기간 동안의 loader 자동 컴파일 코드 품질, 그리고 회귀 테스트 부담을 본 문서가 가볍게 봤다.
2. **headful worker pool의 실제 자원 비용**. v3가 “Windows desktop or Xvfb 1~2개”라고 적었지만, 운영기 RAM/CPU와 동시 워크밴치 세션 수의 상한, 그리고 라이브 뷰 스트리밍(스크린샷/VNC) 대역폭은 미계산. v4가 SLO/자원 산정으로 깔 만함.
3. **persistent profile + 쿠키 jar 재사용의 만료/재학습 루프**. “워크밴치로 한 번 풀면 다음 cron이 흡수”는 듣기 좋지만, 세션 만료/디바이스 핑거프린팅 갱신 주기/profile 손상 복구 절차가 미설계. v4가 “결국 사람이 매주 한 번 누르게 된다”로 깔 수 있음.
4. **selector drift 점수의 false positive**. 시즌 카테고리 비활성/품절 폭증으로 row count가 자연 하락하면 drift 알람이 양치기 소년이 된다. 정상 변동과 구조 변경을 구분하는 baseline 모델이 본 문서엔 없다.
5. **tracked_urls의 누적 폭증과 만료 정책**. 운영자가 워크밴치로 영구 등록을 100건/주 찍으면 1년이면 5천 건. fetch_single_product cron이 6시간 주기면 일 2만 요청. 만료/우선순위/노이즈 정리 규칙 부재.
6. **신고큐 가중치의 캘리브레이션**. “핫딜러 ×1.5”, “신규 사용자 ×0.3” 같은 계수가 어디서 왔는지 근거 없음. 운영 데이터로 보정 안 하면 자의적.

---

*작성: Opus 4.7 — 살붙이기 라운드. 다음(v4)은 GPT 반론, 그 다음(v5)이 Opus 최종.*
