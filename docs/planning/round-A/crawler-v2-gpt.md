# 크롤러 영역 기획 v2 — GPT 적대적 검토

> 대상: `docs/planning/round-A/crawler-v1-opus.md` 검증 + 크롤러 코드 직접 확인.  
> 원칙: v1을 덮어쓰지 않고, 사실관계·운영 구멍·UX 허점을 직설적으로 찍는다.

---

## 0. 본문 요약

v1의 방향은 맞다. “크롤러는 raw record 공장이고, 차단은 정상 상태이며, 관리자는 한 화면에서 복구해야 한다”는 큰 그림은 유지할 가치가 있다.

하지만 v1은 현재 코드를 실제보다 정돈된 상태로 본다. 특히 **공통 엔진 4종은 코드에 없다.** 지금은 `crawler.py`마다 직접 구현한 긴 수집 로직이 많고, `plugin.yaml`은 강한 스키마가 아니라 느슨한 메모장에 가깝다. 관리자 UI도 v1이 그린 라이브 모니터가 아니라 **실행/설정/활성 토글 중심의 기본 카드 UI**다.

직전 라운드 결과 반영도 절반이다. 롯데 240건, 코스트코 48건 및 Playwright 전환, 쿠팡 Akamai 차단은 적었지만, 홈플러스/코스트코 방식 설명은 코드와 어긋난다. v1은 기획서로는 쓸 수 있지만, 그대로 실행 계획으로 쓰면 “있는 기능”과 “만들 기능”이 섞여 개발 우선순위가 흐려진다.

---

## A. v1 사실관계 검증

### A-1. 마트별 행수/방식 매핑 검증

| 소스 | v1 주장 | 코드 확인 | 판정 |
|---|---|---|---|
| 롯데마트 | `~240`, `__INITIAL_STATE__` SSR + SPA card fallback, WAF 202 간헐 | `LottemartCrawler`는 HTTP `__INITIAL_STATE__` → 200건 미달 시 promotions scroll → 10건 미달 시 Playwright 검색 폴백. `plugin.yaml`은 `live_ready:false`, `status: blocked_by_source_waf_http_202` | **부분 일치.** 240건 안정이라는 직전 결과는 반영했지만, yaml은 여전히 WAF blocked/live disabled 쪽이다. “안정”과 “operator_capture 신뢰 경로”가 충돌한다. |
| 이마트 | `~274`, SSR + 카드 파싱 | `EmartCrawler`는 SSG `__NEXT_DATA__`/검색 페이지 기반 requests. `plugin.yaml`도 `public_search_next_data`, `script#__NEXT_DATA__` | **방식 표현 부정확.** SSR+카드라기보다 Next.js JSON 추출이다. |
| 홈플러스 | `~199`, SSR | `HomeplusCrawler` 주석과 구현은 mfront SPA, Playwright 우선, HTTP fallback. `plugin.yaml`도 `strategy: playwright`, `public_search_playwright_spa` | **틀림.** 홈플러스를 SSR로 적으면 복구 전략이 잘못 잡힌다. |
| 코스트코 | `48 → 300+`, requests 멀티패스, Playwright 백업 진행 | 현재 `CostcoCrawler`는 Playwright headless + OCC API XHR 인터셉트 + HTML fallback. `plugin.yaml`은 아직 version `0.4.0`, strategy `requests`, live_ready true, 37 URL 설명 | **상태가 엇갈림.** v1은 직전 라운드의 48/전환 진행은 반영했지만, 코드 본체는 이미 Playwright/OCC 중심으로 이동했고 yaml은 낡았다. |
| 코코달인 | 별도 플러그인, 코스트코와 분리 | `CocodalinCrawler`는 코코달인 API `bestLikeProducts` + 12개 `productList`, 독립 플러그인 | **일치.** |
| 쿠팡 | 0, Akamai 100% 차단, traceId 변조 무효, operator_capture만 가능 | `coupang/plugin.yaml`에 traceId 3종 모두 403, Playwright persistent/undetected도 403, `akamai_access_denied`, live_ready false | **일치.** |

### A-2. “공통 엔진 4종”은 실제 추상화가 아니다

v1은 `SsrInitialStateRunner`, `PaginatedCardRunner`, `SearchKeywordRunner`, `PlaywrightHeadfulRunner` 4종을 말한다. 코드에는 그 이름의 러너가 없다.

실제 존재하는 것은 다음이다.

- `engine/strategies/{requests_st,cloudscraper_st,selenium_st,undetected_st,playwright_st}.py`
- `engine/executor.py`의 strategy cascade
- `engine/playwright_helper.py`
- 각 마트별 `crawler.py` 내부의 자체 구현

즉, v1의 4 엔진은 **기획 단계**다. 지금 코드는 “yaml이 러너를 고르는 구조”가 아니라 “각 crawler.py가 자기 방식으로 requests/Playwright/파서를 직접 들고 있는 구조”다. 이걸 명확히 안 쓰면 v3 작성자가 이미 엔진이 있는 줄 알고 UI부터 얹는 실수를 한다.

### A-3. yaml schema 현황

`PluginLoader.validate_config()`가 강제하는 것은 사실상 이 정도다.

- 필수: `name`, `version`
- `version` semver
- `category`가 허용 목록인지
- `target.difficulty`가 1~5인지
- `dependencies`가 list인지

반면 v1이 기대하는 핵심 키는 강제되지 않는다.

- `entrypoints`
- `source_map`
- `parser_inputs`
- `output.minimum_rows`
- `output.field_coverage_thresholds`
- `live_readiness`
- `waf_strategy`
- `rate_limit_seconds`

게다가 현재 yaml도 일관되지 않다.

- `entrypoints`: 롯데/홈플러스는 list, 이마트는 module/class/paths dict
- `rate_limit_seconds`: 롯데/홈플러스는 숫자, 이마트는 dict
- 코스트코 `plugin.yaml`은 `version: 0.4.0`, `strategy: requests`, `live_ready: true`인데 `crawler.py`는 v0.5.0 Playwright/OCC 중심
- 코코달인 yaml은 `source_map`, `live_readiness`, `diagnostic_evidence_fields`가 거의 없다

결론: yaml은 운영 계약이 아니라 **느슨한 설명 파일**이다. v1의 “yaml만 바꾸면 복구”는 목표이지 현재 상태가 아니다.

### A-4. 라이브 자동화/품질 게이트 위치

확인된 위치는 다음이다.

- 품질: `pipeline/quality.py` — `CRITICAL_FIELD_THRESHOLDS`와 필드 커버리지/중복/invalid 계산
- bounded diagnostics: `pipeline/diagnostics.py` — fixture/raw input 기반 진단 계획과 drift readiness
- source run/AI handoff: `pipeline/source_runs.py`
- 일반 crawl pipeline: `pipeline/pipeline.py`
- 스케줄러: `scheduler/scheduler.py` — APScheduler, `max_instances=1`, `coalesce=True`
- 동시성: `concurrency.py`, `api/routes/crawlers.py` — 전역 `MAX_CONCURRENT_CRAWLS`, 같은 crawler 중복 실행 방지
- 도메인 rate limiter: `engine/rate_limiter.py`, 단 `engine/executor.py`에서만 호출된다. 마트 crawler.py가 직접 requests/Playwright를 쓰는 경로에는 일괄 적용되지 않는다.
- circuit breaker: `pipeline/circuit_breaker.py`, 현재 주요 사용처는 DB-admin ingestion 쪽이다. 크롤러 전략 전환 루프에는 연결되어 있지 않다.

v1이 “토대가 있다”고 한 건 맞지만, 토대와 실제 마트 크롤러 실행 경로가 붙어 있지 않은 부분이 많다.

### A-5. 현 관리자 UI 검증

`frontend/src/pages/Crawlers/Crawlers.jsx` 기준 현재 UI는 다음만 확실하다.

- 카테고리 필터
- 그룹 접기/펼치기
- 개별 실행
- 선택 벌크 실행
- 활성/비활성 토글
- 설정 모달: `target_url`, `delay`, `max_items`
- 실행 상태 SSE + 폴링 fallback
- 최근 5회 미니 타임라인

없는 것:

- WAF/Akamai/Cloudflare 차단 시그니처 라벨
- 필드 충실도 표시
- 전략 전환 버튼
- operator_capture 버튼/세션 전달 UI
- 신고 큐
- 셀렉터 편집 UI
- source_map/fixture 상태 표시
- 동시 실행 수/큐 상태 카드

v1 UI는 미래안이고, 현 UI와 거리가 크다.

---

## B. v1 말미 5포인트에 대한 강한 답

### 1. yaml schema 진화 정책 부재

약점 맞다. 더 세게 말하면, 지금 yaml은 schema라고 부르기 어렵다.

새 사이트가 GraphQL, cursor pagination, infinite scroll, WebSocket, signed XHR, 앱 API 혼합이면 v1의 4 엔진으로 안 잡힌다. 해결은 “4 엔진 고정”이 아니라 **capability 기반 schema**다.

필요한 구조:

```yaml
capabilities:
  transport: [html, xhr, graphql, websocket, app_api]
  render: [none, playwright_headless, playwright_headful]
  pagination: [page_param, cursor, infinite_scroll, load_more_button]
  extraction: [css, jsonpath, graphql_edges, intercepted_response]
  session: [stateless, cookie_jar, persistent_profile, operator_capture]
```

엔진은 4개 고정이 아니라 capability 조합을 실행하는 runner registry여야 한다. 그래야 새 사이트가 나와도 “엔진 5번 만들지 말자” 같은 규격 놀이에 갇히지 않는다.

### 2. 자동 전략 전환 무한루프 위험

v1의 자동 전환은 그대로 구현하면 IP 태우는 버튼이다.

적절한 모델:

- key: `source_id + domain + egress_ip + blocker_signature`
- 상태: `closed → open → half_open`
- threshold: 같은 blocker 2~3회면 open
- cooldown: Akamai/WAF는 짧게 30초가 아니라 30분~수시간 단위
- retry budget: 한 실행 사이클당 전략 전환 최대 1~2회
- escalation order: requests 실패 → Playwright 1회 → persistent profile/쿠키 jar → 다음 cron으로 이월 → operator_capture 알림
- 절대 금지할 것: 같은 run에서 requests→Playwright→UA→다시 requests→다시 Playwright 반복

코드에 `CircuitBreaker`는 있지만 crawler strategy loop와 연결되어 있지 않다. v3는 이 연결을 설계해야 한다.

### 3. 신고 큐 악용 가중치

v1의 신고 큐는 악용에 취약하다. “많이 신고된 상품 우선”만 있으면 장난/경쟁사/봇이 운영 우선순위를 망가뜨린다.

필요한 가중치:

- 같은 사용자 동일 URL 반복 신고 dedup
- 같은 상품/같은 source_url 그룹화
- 최근 가입/익명/저신뢰 사용자는 낮은 가중치
- 실제 크롤러 품질 저하와 일치하면 가중치 상승
- 신고 폭주가 특정 source에 몰리면 “사용자 불만”과 “공격성 노이즈”를 분리 표시
- 큐는 개별 신고 리스트가 아니라 “상품/URL 그룹” 단위로 운영

관리자는 신고 100개를 보면 안 된다. “쿠팡 생수 URL 1개에 신고 37건, 유니크 사용자 9명, 최근 크롤 실패 Akamai 403”처럼 봐야 한다.

### 4. operator_capture UX

v1의 operator_capture는 UX가 헐겁다. “브라우저에서 풀고 와주세요”로 끝나면 운영자는 안 쓴다.

필요한 흐름:

1. 관리자 카드에서 “브라우저 캡처로 복구” 클릭
2. 서버가 `OperatorBrowserSessionManager.open(url)`으로 세션 생성
3. 프론트는 스크린샷/라이브 뷰 + URL + 상태를 보여줌
4. 운영자가 화면에서 로그인/캡차/지역 선택/성인 확인 등 필요한 조작을 직접 함
5. “현재 DOM 캡처” 클릭
6. 서버가 HTML/JSON/HAR 일부와 쿠키 jar 메타를 `OperatorWorkbenchStore.save_capture()`로 저장
7. `ingest_operator_capture` entrypoint가 해당 artifact를 재파싱
8. 성공하면 fixture로 고정하고 다음 자동화 전략에 반영

핵심은 “매번 사람이 풀기”가 아니다. 사람 개입은 **새 blocker를 학습하기 위한 마지막 수단**이어야 한다. 반복되는 차단은 코드/프로필/쿠키 jar/인터셉트 전략으로 흡수해야 한다.

### 5. 코스트코 10분+ 사이클 동시성

v1의 우려는 맞다. 더 큰 문제는 현재 코스트코가 15개 카테고리마다 10초 sleep이면 기본으로 2분 30초 이상이고, 페이지/검색/Playwright 로딩까지 붙으면 10분을 넘는다. 같은 IP에서 롯데/홈플러스/쿠팡까지 돌면 차단 확률도 같이 오른다.

필요한 정책:

- source별 job lock: 이미 scheduler `max_instances=1`은 같은 job 중복만 막는다.
- domain/IP별 token bucket: `costco.co.kr`와 같은 egress IP 단위로 제한
- long-running crawler queue: 코스트코 같은 장기 작업은 별도 low-priority lane
- cron jitter: 07:00에 마트 3개가 동시에 출발하면 안 된다
- category shard: 코스트코 15개 카테고리를 한 번에 다 돌리지 말고 shard별로 분할
- 관리자 UI에 “현재 실행 중 3/5, 코스트코 대기 12분 예상” 표시

현재 `MAX_CONCURRENT_CRAWLS=5`만으로는 부족하다. 전역 5개 제한은 같은 IP/같은 도메인 압박을 모른다.

---

## C. v1이 못 챙긴 시나리오

### C-1. 마트가 ToS 변경/IP 차단 통보를 보낸 경우

이건 “크롤러 중단”으로 도망갈 문제가 아니다. 운영 대응 채널이 필요하다.

- source별 연락/고지 로그: 언제 어떤 IP/도메인/경로가 문제 됐는지 기록
- 트래픽 증빙: 요청 수, user-agent, 시간대, robots-sensitive 경로 접근 여부
- throttle profile 전환: full crawl → reduced crawl → fixture-only → partner/API 협상
- 협상 채널: 제휴/API/상품 피드 요청 템플릿

즉, 코드가 할 일은 “막자”가 아니라 **운영자가 설명하고 조정할 수 있게 증거를 남기는 것**이다.

### C-2. 같은 상품이 여러 소스에 동시에 나오는 경우 dedup 책임

크롤러 책임은 source 내부 dedup까지만이다.

- 같은 소스 내부 중복: crawler/pipeline이 `source_record_key`, URL, name+price로 제거
- 다른 소스 간 동일 상품: DB/AI 책임
- 크롤러가 해야 할 것: dedup에 필요한 원본 키를 풍부하게 넘기기
  - `source_id`
  - `source_record_key`
  - `detail_url`
  - `canonical_url` 가능하면
  - `image_url`
  - `brand`, `unit`, `package_quantity`
  - `raw_title`

`pipeline/dedup.py`는 핫딜 중심이다. 마트 가격 비교용 cross-source product matching은 별도 책임으로 남겨야 한다.

### C-3. cron이 저녁 핫딜 시간대와 겹칠 때

저녁 핫딜 시간대에 무거운 마트 full crawl이 돌면 운영 UI/API/DB ingest가 같이 부담을 받는다.

필요한 정책:

- full crawl은 새벽/오전 low traffic
- 저녁에는 delta crawl / single product refresh / 신고 큐 처리 위주
- hotdeal crawler와 mart crawler lane 분리
- DB ingest queue backpressure가 높으면 무거운 크롤러 자동 지연
- UI에 “사용자 피크 보호 모드” 표시

### C-4. 새 사이트 추가 시 fixture 캡처/스키마 검증 자동화

v1의 “새 소스 추가 마법사”는 좋은데, 검증 단계가 더 구체적이어야 한다.

필수 자동화:

1. URL 1개 입력
2. requests/Playwright/인터셉트 중 어떤 원천 후보가 나오는지 자동 탐지
3. HTML/JSON fixture 저장
4. selector/jsonpath 후보별 raw row count 표시
5. required fields coverage 계산
6. `plugin.yaml` generated draft
7. `crawler.py` thin adapter 생성
8. fixture test 자동 생성
9. bounded live diagnostic 1회
10. live_ready 체크리스트

새 사이트 추가가 “yaml 빈칸 채우기”면 비개발자는 못 한다.

### C-5. 이미지/저작권 처리

크롤러는 이미지 파일을 함부로 복제 저장하면 안 된다. 하지만 제품 비교 UX에는 이미지가 필요하다.

실용 정책:

- 기본은 `image_url` 원본 링크 저장
- 썸네일 캐시는 별도 이미지 프록시/캐시 계층에서 TTL 짧게
- 출처/source 표기
- 이미지가 hotlink 차단이면 placeholder 또는 운영자 승인 캐시
- 크롤러 raw record에는 이미지 저작권 판단을 하지 말고 `image_origin`, `image_url`, `captured_at` 메타를 남긴다

### C-6. 라이브 모니터 동시 동작 수 제한

현 UI는 선택 실행 수를 backend `MAX_CONCURRENT_CRAWLS`로 제한하지만, 화면에는 운영자가 현재 몇 개가 도는지 잘 안 보인다.

필요한 표시:

- 현재 실행 중: `active_count()/MAX_CONCURRENT_CRAWLS`
- 대기 중 작업 수
- 도메인별 rate limit 상태
- 다음 실행 예정 작업
- 장기 실행 작업 예상 종료

버튼을 누른 뒤 “왜 안 끝나지?”가 아니라 누르기 전부터 알아야 한다.

### C-7. Playwright headful 운영 서버 문제

headful은 운영 서버에서 그냥 뜨지 않는다. X server/Windows desktop session/GPU/no-sandbox 문제가 있다.

정리:

- 서버 자동화 기본값은 headless
- operator_capture/headful은 관리자 PC 또는 브라우저 세션 전용 worker에서 돌리는 게 맞다
- Linux 서버에서 headful을 쓰려면 Xvfb/컨테이너 display/권한/GPU 옵션이 필요하다
- 현재 코드에는 `headless=False` 세션 매니저는 있지만, 배포 환경별 실행 계획은 없다
- 코스트코 본 crawler는 현재 `headless=True`다. v1의 “headful 전환”과 실제 운영 실행 조건을 분리해야 한다

---

## D. UI/UX 검토

### D-1. 한 클릭 액션 7종은 그대로 나열하면 헷갈린다

v1의 7개 액션은 기능으로는 필요하지만, 카드에 같은 무게로 놓으면 관리자에게 안 직관적이다.

권장 그룹:

**기본 조작**
- 실행
- 부분 실행
- 중지/대기열 취소

**복구 조작**
- 전략 전환 재시도
- 셀렉터 편집
- 브라우저 캡처 복구

**운영 큐**
- 신고 큐
- 상품 영구 등록

**설정**
- 스케줄/딜레이/최대건수
- yaml 고급 편집

카드에는 2~3개만 바로 보이고, 나머지는 “복구” 드롭다운으로 묶는 게 낫다.

### D-2. 차단 시그니처 라벨은 비개발자 언어가 필요하다

`AWS WAF 202`, `Akamai 403`, `x-awswaf-token`만 보여주면 비개발자는 모른다.

표현은 이렇게 가야 한다.

- “사이트 보안벽이 자동 요청으로 판단함”
- “브라우저 렌더링 필요”
- “쿠키 세션 필요”
- “잠시 쉬었다가 재시도 필요”
- 세부 코드: `AWS WAF 202`는 접힌 상세에 표시

즉, 라벨은 “사람말 + 개발 코드” 2층 구조가 맞다.

### D-3. 마트가 10개 넘으면 카드 UI는 무너진다

현재는 grid + 그룹 접기다. 10개까지는 버티지만, 30개 이상 플러그인 시대에는 카드만으로 운영이 안 된다.

필요한 화면 모드:

- 요약 테이블 모드: source, 상태, 마지막 성공, 행수, 품질, blocker, 다음 실행
- 문제만 보기: 빨강/노랑만 필터
- source group별 접기
- 검색
- “오늘 실패한 것만”
- “live_ready=false만”

라이브 모니터 카드는 상위 위험 소스 5개만 보여주고, 전체는 테이블이 맞다.

### D-4. 신고 큐는 우선순위/그룹화/dedup 없으면 폭주한다

신고 큐는 단순 리스트가 아니다. 운영 큐다.

필수 컬럼:

- 그룹 키: source + normalized URL/product key
- 신고 수 / 유니크 사용자 수
- 최근 신고 시각
- 최근 크롤 상태
- 관련 blocker
- 자동 재크롤 가능 여부
- 담당 액션: 재크롤, 영구 등록, 무시, 병합, 차단

신고가 많다는 이유만으로 자동 크롤하면 장난 신고가 crawler 비용을 태운다.

---

## E. operator_capture에 대한 입장

사용자 지적이 맞다. **operator_capture가 기본 복구 전략이 되면 회피 코드다.**

운영자가 매번 귀찮게 개입하는 구조는 실패다. 크롤러의 목표는 코드 단에서 뚫는 것이다. UA/쿠키 jar/persistent profile/Playwright/OCC 인터셉트/스크롤/딜레이/세션 재사용으로 자동화가 해결해야 한다.

다만 operator_capture를 완전히 버리면 안 된다. 이유는 하나다. 새 blocker가 생겼을 때 자동화가 학습할 진본 HTML/JSON/쿠키 흐름을 얻어야 한다. 그래서 operator_capture의 올바른 위치는 이것이다.

- **상시 운영 경로 아님**
- **반복 수동 작업 아님**
- **차단 원인 분석과 fixture 확보를 위한 마지막 복구 도구**
- **한 번 캡처한 뒤 다음 실행부터 코드/프로필/인터셉트 전략으로 흡수해야 하는 입력 장치**

v1은 operator_capture를 너무 쉽게 “신뢰 경로”로 둔다. 이 표현은 위험하다. 신뢰 경로가 아니라 **학습용 비상 경로**라고 불러야 한다.

---

## F. 추가 제안

### F-1. 크롤러 회귀 자동화

사이트 구조가 바뀌면 “0건”만 알면 늦다. 어디서 깨졌는지 자동으로 알려야 한다.

- fixture별 raw candidate count
- parsed count
- valid count
- required field coverage
- selector hit count
- JSON path hit count
- 이전 fixture와 DOM 구조 diff

알림은 “롯데 실패”가 아니라 “롯데 `productEntities` path 100→0, card selector 50→0”처럼 나와야 한다.

### F-2. 셀렉터/URL 안정성 모니터링

각 selector와 URL template에 drift 점수를 붙인다.

- 최근 7일 hit rate
- 평균 row count
- 실패 전조: hit count가 240→180→90으로 하락
- redirect/final_url 변화
- HTTP status 변화
- HTML bytes 급감

이걸 보면 완전히 터지기 전에 고친다.

### F-3. 크롤러 메트릭 대시보드

필수 메트릭:

- source별 성공률
- 평균/최대 실행 시간
- 수집 건수 추이
- field coverage 추이
- blocker rate
- retry count
- strategy별 성공률
- egress IP별 차단률
- DB ingest 대기 시간

현재 UI의 successRate/totalRuns만으로는 운영 판단이 약하다.

### F-4. 우회 전략 AB test

“어떤 UA가 덜 막히는지”는 감으로 고르면 안 된다.

- UA pool별 성공률
- headless/headful 성공률
- persistent profile 사용 여부
- sleep 구간별 blocker rate
- referer chain 여부
- viewport 조합

단, AB test는 무한 시도가 아니라 retry budget/circuit breaker 안에서 돌아야 한다.

### F-5. 새 소스 추가 onboarding 위저드

비개발자 관리자 기준 위저드가 필요하다.

1. 사이트 URL 입력
2. 크롤 목적 선택: 할인 목록/카탈로그/단일상품
3. 자동 probe 실행
4. 원천 후보 표시: HTML 카드, embedded JSON, XHR, GraphQL
5. 필드 매핑 선택
6. 미리보기 10건
7. fixture 저장
8. yaml 생성
9. bounded diagnostic
10. live_ready 신청

이게 있어야 “새 사이트 추가”가 개발자 작업에서 운영자 작업으로 내려온다.

---

## G. v1 약점 5개

1. **있는 것과 만들 것을 섞었다.** 공통 엔진 4종, 차단 라벨 UI, 전략 전환 UI는 현재 코드에 없다.
2. **yaml schema를 과신했다.** 실제 검증은 name/version/category 정도이고, 핵심 운영 키는 강제되지 않는다.
3. **홈플러스/코스트코 방식 설명이 코드와 어긋난다.** 홈플러스는 SPA Playwright이고, 코스트코는 이미 Playwright/OCC 중심 코드다.
4. **operator_capture를 너무 쉽게 신뢰 경로로 둔다.** 사용자가 원한 건 반복 수동 개입이 아니라 코드 단 자동 복구다.
5. **동시성/차단/스케줄을 한 덩어리로 못 묶었다.** circuit breaker, rate limiter, scheduler, UI active count가 흩어져 있고 마트 crawler 직접 요청 경로에 일괄 적용되지 않는다.

---

## H. v3 작성자에게 질문

1. v3는 “현재 있는 기능”과 “새로 만들 기능”을 표로 분리할 것인가? 특히 공통 엔진 4종은 신규 작업으로 명시할 것인가?
2. yaml schema는 고정 4엔진 방식으로 갈 것인가, capability 기반 runner registry로 갈 것인가?
3. operator_capture를 반복 운영 경로가 아니라 학습/fixture 확보용 비상 경로로 격하할 것인가?
4. 코스트코 같은 장기 Playwright crawler를 별도 queue/lane으로 분리할 것인가, 전역 `MAX_CONCURRENT_CRAWLS`만 유지할 것인가?
5. 관리자 UI는 카드 확장으로 갈 것인가, 10개+ 소스 운영을 위해 테이블/필터/문제만 보기 모드를 먼저 만들 것인가?
