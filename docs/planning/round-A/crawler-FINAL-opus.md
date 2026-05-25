# 크롤러 영역 기획 v5 — Opus 최종본 (단일 완성 기획서)

> Round-A 마지막 타자. 입력: v1(`crawler-v1-opus.md`), v2(`crawler-v2-gpt.md`), v3(`crawler-v3-opus.md`), v4(`crawler-v4-gpt.md`).
> 범위: `packages/crawler-admin/` 만. DB/AI/웹은 **경계만**.
> 이 문서가 크롤러 영역의 **단일 진실 원본**이다. v1~v4는 보존(참조용), 본 문서가 우선한다.
> 톤: 한국어 비개발자 가독, 직설. 회피 어휘 금지.

---

## 서문 — v1~v4 통합 정책

### S-1. 한 줄 요약

> **"capability yaml 5엔진 + 도메인별 circuit breaker + 운영자 워크밴치(1급) + 마트별 lane 분리 + 운영 수명주기(profile/tracked_url/evidence/contract) 완비. 라이브 실측 기준: 코스트코 995×3, 롯데마트 240×3. 안전 타령·운영자 떠넘기기·동적 차단 회피는 전부 거른다."**

### S-2. v1~v4에서 수용한 약점 (요약)

v2 적시:
- 공통 엔진은 코드에 없다(기획 단계) → v5 신규
- yaml schema가 느슨하다(name/version/category만 강제) → capability schema v2로 진화
- `pipeline/circuit_breaker.py`가 크롤러 strategy loop에 연결 안 됨 → 연결
- 홈플러스 SSR 표기 오류 → SPA Playwright로 정정
- 이마트 "SSR+카드" 표기 오류 → `__NEXT_DATA__` JSON 추출로 정정
- 코스트코 yaml(0.4.0 stale)과 코드 어긋남 → 0.6.0 OCC REST 정합화
- 신고큐는 단순 리스트면 악용된다 → 그룹/가중치
- 코스트코 10분+ 사이클 → long-running lane + 카테고리 샤드 + cron jitter
- 차단 라벨은 비개발자 언어 2층 → "보안벽이 자동 요청으로 판단함" + 접힌 `AWS WAF 202`
- 30개+ 소스 시대는 카드만으로 운영 불가 → 카드+테이블 토글

v4 적시 (수명주기):
- 워크밴치 산출물 등급 미분리 → 4등급(즉시수확/영구등록/세션자산/fixture) 분리
- retry depth/cooldown만으론 부족 → attempt_cost 런타임 상태 모델
- headful pool "1~2개면 끝"은 숫자 부재 → interactive/automated 분리 + 자원 SLO
- ToS 증거 "로그까지"는 얇다 → **evidence ledger** 구조화
- yaml 마이그레이션 일괄 PR은 깨진다 → read-compat / write-policy / test-matrix 3단계
- tracked_urls는 썩는다 → subscription lifecycle (tier/stale/review queue/canonical merge)
- profile은 만료된다 → profile refresh queue + state probe
- drift는 한 점수가 아니라 4종(parser_drift / volume_anomaly / session_loss / business_change) 분리
- 도메인 토큰버킷 값은 metric으로 조정
- PC/모바일 surface 동등 처리
- 가격/상품명 변경 → price_text_raw, confidence, previous_title 보존
- 광고/스폰서/카테고리 위장 → is_sponsored, rank_position, source_category_path 메타
- crawler-admin↔db-admin contract → `packages/shared/core/contracts`에 schema 버전 + compat test
- 우리 배포가 사이트 변화처럼 장애를 만든다 → plugin.yaml/crawler.py sha + canary + rollback

### S-3. v4를 **배척한** 자리 (안전/운영자 떠넘김/동적 회피)

v4는 v2보다 균형이 좋지만, 다음 표현/방향은 v5에서 잘라낸다.

| v4 표현/방향 | v5 판정 | 이유 |
|---|---|---|
| "profile refresh queue를 cron으로 미리 띄운다" — 단, **사람이 매주 누른다**는 전제로 흐를 위험 | **부분 배척** | refresh queue 자체는 채택. 단 "사람이 매주 누르는 것"을 정상 상태로 두지 않는다. profile lifecycle의 목표는 **사람 개입 빈도 감소**(주 1회→월 1회→분기 1회). 자동 보강 항목 §4-D 참조 |
| "automated headful이 interactive를 밀어내면 1급 시민 무너진다 → automated 우선순위 낮춤" | **수용+보강** | interactive 우선은 맞다. 단 automated headful을 "1개로 묶어 대기열"에 놓는 식으로 자동화 자체를 죽이지 않는다. 워크 풀 수치 §3-C에 명시 |
| "긴급 selector 수정은 UI patch + bounded diagnostic, 구조 변경은 직접 git PR" | **수용** | 단 "운영자가 yaml 직접 못 만지게 잠그자"로 흐르지 않게, **selector/url_template/search_keywords/output threshold/waf escalation**은 UI에서 직접 편집 가능 유지 |
| "워크밴치 영구 등록도 검토 큐에 넣고 14일 invalid면 stale" | **수용+조정** | 검토 큐는 채택. 단 "운영자가 등록한 건 자동 stale 안 함, 검토 큐 표시까지만"이 v5 기본. 자동 삭제 금지 |
| (v4가 직접 안 깠지만 깔 자리) D-3 4개 금지(captcha 자동풀이/자격증명 도용/WAF 토큰 위조/robots 위반 강제진입) | **유지** | 합법/불법 경계. 양보 없음 |
| v2 잔재: operator workbench "비상 경로 격하" / "headful은 운영자 PC로 빼라" / "retry 1~2회 상한" | **재확인 배척** | v3에서 이미 배척, v5도 같음 |
| "대외 협상 채널/throttle profile 감축 모드" | **배척** | 코드 영역 아님. v5 산출은 **evidence ledger**까지. 협상 템플릿은 운영 매뉴얼로 분리 |

### S-4. v4의 v5 결단 질문 5개 — 직답

| # | v4 질문 | v5 결단 |
|---|---|---|
| 1 | 워크밴치 산출물 4등급을 schema로 분리할 것인가? | **YES.** `WorkbenchCapture` (1개 세션) → 4종 자식 객체(`InstantHarvest`, `TrackedUrlEntry`, `SessionAsset`, `Fixture`). 각자 lifecycle/TTL/검토상태 별도. §5-C |
| 2 | retry를 attempt_cost 모델로 갈 것인가? | **YES.** yaml `waf_strategy.escalation`은 경로 명시, 실행 시점에 `attempt_cost = domain_pressure + worker_pressure + profile_age + blocker_severity + shard_scope`로 게이트. depth는 yaml(상한), cost는 런타임(가변). §4-A |
| 3 | tracked_urls를 subscription lifecycle로? | **YES, P1.** `status` 6종(active/stale/redirected/discontinued/duplicate_candidate/review_required) + `refresh_tier` 5종(1h/6h/daily/weekly/paused) + 검토 큐. §5-D |
| 4 | PC web과 mobile web을 동등 surface로? | **YES.** `source_map[].surface: pc_web \| mobile_web \| mobile_app_api`. fallback이 아닌 동등. 단 `surface` 메타는 raw payload에 박아 DB가 구분 가능. §3-B |
| 5 | crawler↔db contract를 어디서? | **`packages/shared/core/contracts`에 고정.** `crawler_to_db_v2.py` (TypedDict + JSON Schema) + `tests/contracts/test_crawler_db_compat.py` (회귀). major bump는 양쪽 PR 동시. minor는 호환. §8-B |

---

## 1. 프로젝트 맥락 + 크롤러 책임

### 1-1. 프로젝트 한 줄

WalletSavior는 마트/쇼핑몰/핫딜/공공 가격 정보를 모아 비교·추적하는 캡스톤 프로젝트. 크롤러는 **raw record를 안정적으로 토해내는 공장**이다.

### 1-2. 크롤러의 책임 / 비책임

| 책임 (한다) | 비책임 (안 한다) |
|---|---|
| raw record 산출 (name, sale_price, regular_price, detail_url, image_url, unit_text, brand, period_text, ...) | 카테고리 분류 / 동일상품 매칭 / cross-source dedup |
| 소스 메타데이터 (source_id, collection_path, crawl_intent, source_record_key, captured_at, raw_html_ref, surface, region_context) | 가격 단위 정규화 (`1.9천원` 해석은 보존만, 변환은 AI/DB) |
| 차단 감지 / 전략 전환 / 워크밴치 호출 / fixture 캐시 | DB 직접 쓰기 / AI 호출 |
| 신고 큐 수신 + 그룹화 | 신고 진위 판정 |
| evidence ledger | 대외 협상 |
| selector drift 분류 | drift 자동 보수 (제안만, 승인 운영자) |

### 1-3. 사용자 헌법 (재확인)

1. **소스 바뀌어도 yaml만으로 복구 가능.**
2. **차단은 정상 상태.** 감지→알림→전략 전환이 1급 시민.
3. **합법 위장 기본 장착, 공격 금지.** "안전 타령"으로 기능 막는 분기는 추방.
4. **운영자 워크밴치는 1급 시민.** 비상이 아니라 정식 도구.
5. **크롤러는 raw + 소스 메타까지.** 추론/매칭/정규화는 AI/DB 영역.

---

## 2. 사이트별 실측 + 전략 (완성판)

### 2-1. 마트 4사 + 코코달인

| 소스 | 방식 | 라이브 실측 | 엔진 | 엣지/리스크 |
|---|---|---|---|---|
| **이마트** | Next.js `__NEXT_DATA__` SSR + 페이지네이션 | 라이브 N건 안정 (요청별 변동) | `SsrInitialState` + `PaginatedCard` | 검색 페이지 별도 경로, 행사 종료 시 row 자연 감소 (drift false positive 주의) |
| **롯데마트** | SPA Angular, Playwright scroll + XHR 인터셉트 | **240 × 3 라이브 검증 완료** | `PlaywrightHeadful` (XHR intercept) | AWS WAF 202 간헐, persistent profile + 쿠키 jar 재사용 필수 |
| **홈플러스** | SPA mfront, Playwright 우선 + HTTP fallback | 임계 근접(≥195 목표) | `PlaywrightHeadful` + `SsrInitialState` (fallback) | mobile-first 구조. v5에서 `surface: mobile_web` 정식 채택 |
| **코스트코** | SAP Hybris/Akamai → **OCC REST API 직접 호출** | **995 × 3 라이브 검증 완료 (v0.6.0)** | **`OccRestApi`** (신규 5번째 엔진) | Playwright/SSR 우회 **불필요**. OCC endpoint 안정. yaml stale(0.4.0) 즉시 0.6.0 마이그레이션 |
| **코코달인 (마트형)** | `bestLikeProducts` API + 카테고리 `productList` | 안정 | `SearchKeyword` + `PaginatedCard` (REST 변형) | **코스트코 보조용** (코스트코가 놓친 가격대/품목 보강). 코스트코와 결합도 0 |

### 2-2. 핫딜 / 보조 / 보류

| 소스 | 방식 | 상태 | 비고 |
|---|---|---|---|
| algumon | requests 30분 주기 | 안정 | 가벼움 |
| ppomppu / fmkorea / clien / quasarzone | requests | 안정 | 핫딜 카테고리 |
| 코코달인 (핫딜형) | API | 안정 | 마트형과 별도 source |
| 아카라이브 | 로그인 필요, requests + cookie | **후순위 (운영자 1회 로그인 + persistent profile)** | profile refresh cadence yaml에 박음 |
| 오피넷 | 공공 API | 안정 | `waf_strategy: disabled` |
| **쿠팡** | Akamai 100% 차단 | **보류** (밴 빈번) | **tracked_urls 모델만** — 운영자가 워크밴치에서 관심 상품 등록 → `fetch_single_product` 주기 갱신. 카탈로그 자동 수집 안 함 |

### 2-3. 실측 카운트 기준 (yaml `output.minimum_rows`)

| 소스 | 임계 | 근거 |
|---|---|---|
| 이마트 | ≥ 270 | 직전 라운드 ~274 실측 |
| 롯데마트 | ≥ 240 | **3회 연속 라이브 240 검증** |
| 홈플러스 | ≥ 195 | 임계 근접, 미달 시 즉시 알람 |
| 코스트코 | ≥ 900 | **3회 연속 995 검증, 안전마진 95** |
| 코코달인(마트) | ≥ 50 | 임시. 안정화 후 상향 |
| 핫딜류 | ≥ 30 (소스별) | 차등 |

---

## 3. 공통 엔진 5종 + capability yaml schema (완성판)

### 3-A. 공통 엔진 5종 (4종 → 5종으로 확장)

v1의 4엔진 + 코스트코 실측으로 검증된 5번째.

| 엔진 | 용도 | capability 매핑 | 대표 소스 |
|---|---|---|---|
| **SsrInitialStateRunner** | `__INITIAL_STATE__` / `__NEXT_DATA__` JSON 추출 | `transport: html`, `extraction: jsonpath`, `render: none` | 이마트, 일부 SSR |
| **PaginatedCardRunner** | 페이지 파라미터 + CSS card | `transport: html`, `pagination: page_param`, `extraction: css` | 이마트 검색, 핫딜류 |
| **SearchKeywordRunner** | 키워드 리스트로 search URL 순회 | `pagination: page_param`, 키워드 입력 | 코코달인 일부, 단골 probe |
| **PlaywrightHeadfulRunner** | SPA / XHR 인터셉트 / 마우스 시뮬 | `render: playwright_headful`, `extraction: intercepted_response` | 롯데마트, 홈플러스 |
| **OccRestApiRunner (NEW)** | SAP Hybris OCC REST 직접 호출 (cookie/CSRF 토큰만 워크밴치로 1회) | `transport: xhr`, `extraction: jsonpath`, `session: cookie_jar` | **코스트코 (995×3 검증)** |

`engine/strategies/*` (requests/cloudscraper/selenium/undetected/playwright)는 **하위 transport 어댑터**로 유지. 5엔진은 **상위 워크플로**.

### 3-B. capability yaml schema v2

```yaml
name: lottemart
version: 1.0.0
schema_version: 2
category: mart

capabilities:
  transport:     [html, xhr]              # html | xhr | graphql | websocket | app_api
  render:        [playwright_headful]     # none | playwright_headless | playwright_headful
  pagination:    [page_param]             # | cursor | infinite_scroll | load_more
  extraction:    [css, jsonpath, intercepted_response]
  session:       [cookie_jar, persistent_profile]  # | stateless | operator_capture
  anti_blocker:  [ua_rotation, referer_chain, sleep, headful_fallback]

entrypoints:
  crawl_sale_listing: { module: ..., class: ... }
  fetch_single_product: { module: ..., class: ... }
  ingest_operator_capture: { module: ..., class: ... }

source_map:
  - id: weekly_sale_pc
    surface: pc_web            # pc_web | mobile_web | mobile_app_api  (v5 신규)
    url_template: "https://.../sale?page={page}"
    parser_inputs: [initial_state, embedded_json, card_html]
    selectors: { ... }
  - id: weekly_sale_mobile
    surface: mobile_web
    url_template: "https://m.../sale?page={page}"
    selectors: { ... }

output:
  minimum_rows: 240
  field_coverage_thresholds: { name: 0.95, sale_price: 0.90, detail_url: 0.85 }
  required_fields: [name, sale_price, detail_url]
  optional_recommended: [unit_text, image_url, brand, period_text]

waf_strategy:
  detect: [http_202, akamai_403, x-awswaf-token, cf-mitigated]
  escalation:
    - { from: requests,             to: playwright_headless, after_failures: 2, cooldown_sec: 60 }
    - { from: playwright_headless,  to: playwright_headful,  after_failures: 2, cooldown_sec: 300 }
    - { from: playwright_headful,   to: operator_workbench,  after_failures: 2, cooldown_sec: 1800 }

rate_limit:
  per_domain_rps: 0.1
  page_sleep_sec: 10
  jitter_sec: [2, 8]

profile_state:
  profile_id: lottemart-main
  cookie_expires_min: 1440
  login_state_probe: { type: selector, value: ".user-name" }
  region_state_probe: { type: cookie, value: "branch_id" }
  refresh_cadence_days: 14

live_readiness:
  fixture_pass: true
  bounded_diagnostic_pass: true
  operator_approval: true
```

### 3-C. schema 진화 + 마이그레이션 (v4 §C-1 수용)

**3단계 마이그레이션** (일괄 PR 금지):

1. **read compatibility** — `PluginLoader`가 schema_version 1과 2를 둘 다 읽고 내부 `NormalizedConfig`로 컴파일. v1 파일은 UI에서 자동 저장 안 함.
2. **write policy** — UI는 v2만 저장. v1 파일은 명시적 "변환" 큐로 진입. 변환 실패와 crawler 실패 카드 분리 표시.
3. **test matrix** — 6단계 상태 카드 표시:
   - `config_schema_valid` / `config_compiled` / `entrypoint_import_ok` / `fixture_parse_ok` / `bounded_live_ok` / `ui_editable`

대상 25개 yaml (마트 5 + 핫딜 9 + 쇼핑 8 + 공공 3)을 6주 분산 변환.

### 3-D. IP 풀 / UA 정책 — **자체 운영, 외부 떠넘김 X** (v4 §E-1, §E-2 수용)

| 항목 | v5 정책 |
|---|---|
| egress IP | 운영기 본 IP + 백업 egress 1~2개. **외부 프록시 풀은 쿠팡/쇼핑몰 실험 lane 한정.** 모든 로그·circuit·rate limit 키에 `egress_ip_id` 포함 |
| UA pool | family/version pin + **profile sticky** (per-request random 금지). cookie jar는 만든 UA와 fingerprint 일관 유지 |
| 모바일 UA | 모바일 surface 명시 시만 사용 (DOM/API가 다름) |
| sec-ch-ua / Accept-Language | family와 일관 |
| 회전 정책 | `per_profile_sticky` 기본, `per_session_rotate` 옵션 |

```yaml
ua_profile:
  family: chrome_windows
  version_pin: 131
  mobile: false
  rotate_policy: per_profile_sticky
  compatible_headers: chrome_desktop_ko
```

---

## 4. 회복력 / 동적 대응

### 4-A. circuit breaker (트리거 / 완화 / cooldown) — attempt_cost 게이트 포함

**키:** `(source_id, domain, egress_ip, blocker_signature)` 4-튜플.

**상태:** `closed → open → half_open → closed`.

**트리거:**
- 같은 blocker 연속 2회 → `open`
- 핵심필드 결측 <80% 2회 연속 → `open`

**완화 (cooldown, yaml `cooldown_sec`):**
- WAF / Akamai: 30분~수시간
- Parser empty: 다음 cron까지
- Bot manager: 1시간

**half_open:** 1회 시도 → 성공 시 closed, 실패 시 다시 open (지수 백오프).

**escalation depth (yaml 상한)** vs **attempt_cost (런타임 게이트)** — v4 §B-2 수용:

```
attempt_cost = domain_pressure + worker_pressure + profile_age + blocker_severity + shard_scope
next_step    = escalation[depth_idx]  IF  attempt_cost <= source_max_cost
               ELSE defer_to_next_window
```

- **depth는 yaml** — 경로 명시 (requests → headless → headful → workbench)
- **cost는 런타임** — 같은 IP가 이미 압박 받고 있으면, 같은 cycle에 headful까지 안 간다(다음 cron으로 이월)
- **무한 핑퐁 차단** — 한 방향만 가능

"retry budget 1~2회 상한"은 **거부**. 자동 복구를 함부로 죽이지 않는다.

### 4-B. drift 감지 (false positive 완화) — v4 §C-4 수용

drift를 **한 점수가 아닌 4분류**로 분리:

| 라벨 | 신호 | 대응 |
|---|---|---|
| `parser_drift` | selector hit ↓ + HTML 구조 hash 변화 + fixture도 실패 | 셀렉터 편집 UI 즉시 |
| `source_volume_anomaly` | row count만 ↓, selector hit 유지 | 비즈니스 변동(시즌 종료/품절) — 알람 약함, 7일 baseline 비교 |
| `session_state_loss` | 로그인/지역/회원가 probe 실패 | profile refresh queue |
| `catalog_business_change` | 신규 카테고리 등장 / 가격 표시 변경 / 상품명 일괄 변경 | 운영자 검토, 코드 수정 가능성 |

baseline: 전년/전월/요일 평균. 단골 probe 키워드(우유/계란/라면 등 10종)는 baseline 있는 경우만 비교.

### 4-C. retry / escalation depth

yaml `waf_strategy.escalation` 시퀀스를 끝까지 시도 가능. 단:
- 각 단계마다 cooldown
- attempt_cost 게이트가 cycle 이월 결정
- 같은 source가 한 cycle 안에서 같은 strategy를 두 번 시도 금지

### 4-D. 운영자 워크밴치 = 1급 시민 유지 + 자동화로 갈음 못 가는 case 명시

**워크밴치가 정식으로 필요한 case (자동화로 갈음 불가):**

1. **신규 사이트 첫 진입** — 캡차/지역 선택/성인 인증/회원 등록 등 사람만 처리 가능한 1회성 의식
2. **로그인 필요 사이트 초기 부트스트랩** (아카라이브, 향후 회원 전용 가격 마트)
3. **구조 변경 후 새 selector 직관 확보** — fixture만으론 안 보이는 흐름
4. **사용자 요구 "전용 브라우저로 상품 검색 → 영구 등록"** — 사용자 직접 지시
5. **신고 큐에서 검증 필요한 URL의 진본 확인**

**자동화로 흡수해야 하는 case (워크밴치 매번 누르기 금지):**

- 반복 차단 → persistent profile + cookie jar 재사용 (다음 cron이 흡수)
- 동일 selector drift → drift 점수 기반 자동 셀렉터 후보 제안
- 세션 만료 → profile refresh queue가 미리 알림 (사람 개입 빈도 ↓: 주→월→분기)

**금지선 (v1 D-3 유지):**
- ❌ captcha 자동풀이 (서비스/AI 모두)
- ❌ 자격증명 도용 / 인증 우회
- ❌ WAF 토큰 위조 / 액세스 컨트롤 우회
- ❌ robots.txt 명시 위배 영역 강제 진입

---

## 5. 운영자 헤드풀 워크밴치 (완성판)

### 5-A. 자리매김

워크밴치는 **회피가 아니라 본 사이트 구조 변경 / 캡차 대응 / 영구 등록 / 신규 부트스트랩의 정식 도구**. 크롤러 페이지의 **1급 탭**(카드 한 구석 X).

### 5-B. 흐름

1. 관리자가 "워크밴치 열기" (소스 카드/테이블에서 항상 표시)
2. 백엔드 `OperatorBrowserSessionManager.open(url, source_id)` → Playwright headful + persistent profile (`crawlers/{source}/profile/`)
3. 프론트는 **라이브 뷰** (스크린샷 폴링 또는 VNC iframe) + 상태 패널 (쿠키 / URL / 네트워크 / 로그인 상태)
4. 운영자 조작: 로그인 1회 / 캡차 / 지역 선택 / 검색 / 카드 클릭
5. 출력: 4등급 (§5-C)

### 5-C. 워크밴치 산출물 4등급 (v4 §B-1 수용)

한 `WorkbenchCapture` 세션 → 4종 자식 객체, 각자 lifecycle.

| 등급 | 객체 | 용도 | TTL/검토 |
|---|---|---|---|
| **즉시 수확** | `InstantHarvest` | 지금 화면의 상품 카드를 raw item 후보로 즉시 뽑음 | 24시간, AI/DB 검증 후 통상 raw record로 승격 |
| **영구 등록** | `TrackedUrlEntry` | URL을 tracked_urls에 등록, 주기 갱신 대상 | subscription lifecycle (§5-D) |
| **세션 자산** | `SessionAsset` | 쿠키 jar / persistent profile / HAR 일부를 다음 cron에 재사용 | profile refresh cadence (§4-D) |
| **fixture 화석화** | `Fixture` | HTML/JSON 스냅샷, drift baseline + 회귀 테스트 | 사이트 구조 변경 시 갱신 |

`ingest_operator_capture` entrypoint가 SessionAsset + Fixture를 재파싱해서 정합성 검증.

### 5-D. 영구 등록 검토 큐 (tracked_urls subscription lifecycle) — v4 §D-5 수용

**status (6종):** `active` / `stale` / `redirected` / `discontinued` / `duplicate_candidate` / `review_required`

**refresh_tier (5종):** `1h` / `6h` / `daily` / `weekly` / `paused`

**메타:**
- `last_seen_valid_at`
- `last_price_change_at`
- `consecutive_no_change`
- `consecutive_failures`
- `canonical_url_hash`
- `registered_by` (workbench / report_queue / manual_yaml)
- `register_capture_id`
- `is_sponsored_suspicion`

**자동 강등 규칙:**
- 30일 가격 변화 없음 → `weekly`로 강등
- 14일 연속 404/품절 → `stale` + 검토 큐 진입 (자동 삭제 X — 운영자 결정)
- canonical_url 같은 다른 URL 발견 → `duplicate_candidate`
- 사용자 신고는 많은데 crawler 정상 → `review_required`

**운영자 등록 URL도 검토 큐에 들어가지만 자동 stale 안 함.** 검토 표시까지만, 삭제는 사람 결정.

### 5-E. yaml 직접 편집 UI

핵심 섹션을 폼 + 코드 에디터 두 모드:
- `source_map[].selectors / url_template`
- `search_keywords`
- `parser_inputs`
- `output.minimum_rows / field_coverage_thresholds`
- `waf_strategy.escalation`
- `rate_limit`

**UI에서 가능:** selector/url/keyword/threshold/escalation 패치
**UI에서 불가능:** entrypoint module/class, dependency, schema_version major bump → 직접 git PR

저장 시: schema validate → git diff 미리보기 → bounded diagnostic 1회 → 통과 시 디스크 반영 + hot reload → 자동 PR 생성

---

## 6. 라이브 모니터 + 데이터 품질 게이트

### 6-A. 마트별 최소 카운트 임계

§2-3 표 그대로 yaml `output.minimum_rows`에 박음.

### 6-B. 누락 의심 자동 진단 (샘플 검색 URL diff)

- 단골 키워드 10개 (우유, 계란, 라면, 즉석밥, 휴지, 세제, 콜라, 김치, 식용유, 만두) 별도 `SearchKeyword` probe
- 메인 크롤 결과에서 해당 키워드 매칭이 baseline 대비 -50% 이상 ↓ 이면 "누락 의심"
- 카드 표시: "probe vs main: 우유 12 / 0"
- 임계 초과 시 selector drift 알람 트리거 (단 §4-B 분류로 진입, parser_drift인지 volume_anomaly인지 구분)

### 6-C. 3단 데이터 품질 게이트

1. **볼륨 게이트** — `output.minimum_rows` 미달
2. **필드 충실도 게이트** — required_fields 결측률 임계 초과
3. **현실성 게이트** — sale_price=0 또는 1억 초과, name<5자, detail_url 도메인 불일치

### 6-D. 가격 표시 변경 / 상품명 변경 추적 (v4 §E-5, §E-6 수용)

raw record에 다음 필드 보존 (정규화 X, 보존 O):

```
price_text_raw         # "1.9천원" 원문
sale_price             # int KRW, nullable
price_parse_confidence # 0.0~1.0
price_parse_rule_id    # 어떤 룰이 파싱했나
unit_price_text_raw    # "100g당 980원"
title_normalized_light # 괄호/행사문구만 제거
previous_title         # diagnostics에 후보 보존
image_url_hash         # 이미지 변화 추적
brand / unit / package_quantity (원문 보존)
```

### 6-E. 라이브 모니터 카드 (정보 밀도)

```
┌─ 롯데마트 ───────────────────────── ⚠️ 보안벽 감지 ─┐
│ 마지막 성공: 2시간 전 (240건)                      │
│ 다음 실행: 07:00 (4시간 후)                        │
│ 필드 충실도: name 100% / price 98% / url 82%       │
│ ●●●○● (최근 5회)                                    │
│ 차단: AWS WAF 202 (자동 → headful 전환 대기 30분)  │
│ tracked_urls: 23개 (active 18 / stale 5)           │
│ profile: 만료 4일 남음                             │
│                                                    │
│ [▶ 즉시 재시도] [🌐 워크밴치 열기] [📋 신고 3건]    │
│ [✏️ yaml 편집] [전략 전환 ▾]                        │
└────────────────────────────────────────────────────┘
```

**30개+ 소스 운영용:** 카드 모드(상위 위험 5~10) ↔ 테이블 모드 토글. 필터(카테고리/상태/live_ready/최근 실패), 검색, 프리셋("오늘 실패만", "live_ready=false만").

---

## 7. 보조 어댑터 (코코달인 / 오피넷 / algumon / 아카라이브)

본 크롤러 본체 (마트 4사)와 **분리된 별도 어댑터**. 단 같은 capability schema 안에서 동작.

| 어댑터 | capability | 비고 |
|---|---|---|
| 코코달인(마트형) | `transport: xhr`, `extraction: jsonpath` | 코스트코 보조용. 코스트코와 결합도 0 |
| 코코달인(핫딜형) | `transport: xhr` | 마트형과 source 분리 |
| 오피넷 | `transport: xhr`, `session: stateless`, `waf_strategy: disabled` | 공공 API |
| algumon | `transport: html`, `render: none` | 30분 주기 |
| 아카라이브 | `transport: html`, `session: persistent_profile` | 운영자 1회 로그인, profile refresh 14일 |

---

## 8. 모듈 경계

### 8-A. crawler-admin ↔ ai-admin ↔ db-admin payload schema

| 영역 | 크롤러 제공 | 크롤러 수신 | 금지 |
|---|---|---|---|
| ai-admin | raw record stream, blocker evidence, drift signal, capture artifact | yaml selector patch suggestion (운영자 review 후 적용) | AI가 크롤러 직접 import / DB 직접 쓰기 |
| db-admin | `CrawlResult` (raw item + 소스 메타) | tracked_urls 변경 통지 | DB에서 크롤러 내부 모듈 import |
| web-frontend | source 상태 read-only API, 신고 큐 POST | 사용자 신고 payload | 프론트가 yaml 직접 쓰기 (관리자 UI 경유만) |

### 8-B. crawler→db contract 안정성 (v4 §E-10 수용)

위치: **`packages/shared/core/contracts/crawler_to_db_v2.py`** (TypedDict + JSON Schema)
회귀 테스트: **`tests/contracts/test_crawler_db_compat.py`**

```python
class CrawlerToDbV2(TypedDict):
    schema_version: Literal[2]
    source_id: str
    collection_path: str
    crawl_intent: Literal["sale_listing", "single_product", "catalog_page"]
    source_record_key: str
    captured_at: str                 # ISO 8601 KST
    raw_html_ref: str | None         # s3://... or local
    surface: Literal["pc_web", "mobile_web", "mobile_app_api"]
    region_context: RegionContext | None
    item: ItemPayload
    diagnostics: Diagnostics
    evidence: EvidenceRef            # evidence_ledger 키
```

**호환 규칙:**
- major 변경 → 양쪽 PR 동시
- minor 필드 추가 → 호환
- 필드 삭제/이름 변경 → 2주 deprecation 기간
- `source_record_key` 안정성 보장 (URL 정규화 + 소스 ID 추출 룰 고정)
- `sale_price`는 int KRW 또는 null만 허용

### 8-C. evidence ledger (v4 §B-4 수용)

매 요청 단위 재현 가능. `crawlers/_evidence/{date}/{source_id}/...`.

필드: source_id, domain, collection_path, crawl_intent, request_count, status 분포, blocker_signature, egress_ip_id, proxy_provider/type/region, UA family/version/sec-ch-ua/Accept-Language, strategy, profile_id, profile_age, cookie_age, login_state, path prefix 목록, schedule source, code version (git sha + plugin.yaml sha + schema_version).

대외 협상 시 운영자가 재현/설명. **협상 템플릿은 본 문서 밖 (운영 매뉴얼).**

### 8-D. 광고/스폰서/카테고리 위장 상품 식별 (v4 §E-11, §E-12 수용)

크롤러는 제거하지 않고 **메타 보존**:

```
is_sponsored: bool
sponsored_badge_text: str | None
rank_position: int
section_name: "추천" | "광고" | "검색결과" | "전단" | ...
source_category_path: str
breadcrumb_text: str
search_keyword: str | None
result_section: str
matched_terms: list[str]
```

AI/DB가 필터링. 크롤러는 신호 전달만.

### 8-E. 지점/지역 가격 차이 (v4 §E-13 수용)

```
store_context: "online_default" | "delivery_region" | "offline_branch" | "member_only"
region_code: str | None
branch_id: str | None
region_source: "cookie" | "profile" | "manual" | "default"
price_scope: "online" | "offline" | "unknown"
membership_required: bool
```

워크밴치에서 지역 선택 시 profile의 region state가 가격에 묻는다.

---

## 9. 로드맵 P0 / P1 / P2 (최종)

### P0 — 라이브 직전 (지금 ~ 2주)

- [x] 코스트코 OCC REST v0.6.0 (995×3 검증 완료) → **yaml stale(0.4.0) 즉시 갱신**
- [x] 롯데마트 240×3 검증 완료 → yaml `live_ready: true` + waf_strategy 정합화
- [ ] **5번째 엔진 `OccRestApiRunner` 코드화** (코스트코 crawler.py 흡수)
- [ ] `pipeline/circuit_breaker.py` ↔ crawler strategy loop 연결
- [ ] 도메인별 `engine/rate_limiter.py`를 마트 crawler.py 직접 경로에도 적용
- [ ] 볼륨 + 필드 충실도 게이트 UI 표시
- [ ] WAF/Akamai 시그니처 카탈로그 (`pipeline/blocker_signatures.py`) 1차
- [ ] 차단 라벨 2층 구조 (비개발자 언어 + 접힌 코드)
- [ ] evidence ledger 골격 (요청 단위 재현 가능 필드 저장)

### P1 — 운영 편의 (2주 ~ 6주)

- [ ] capability yaml schema v2 + 25개 yaml 3단계 마이그레이션 (read-compat → write-policy → test-matrix)
- [ ] 6단계 상태 카드 (config_schema_valid / compiled / entrypoint_import / fixture / bounded_live / ui_editable)
- [ ] 워크밴치 라이브 뷰 + 4등급 산출물 (InstantHarvest / TrackedUrlEntry / SessionAsset / Fixture)
- [ ] tracked_urls subscription lifecycle (6 status × 5 tier + 검토 큐)
- [ ] profile refresh queue + state probe (만료 예측)
- [ ] 셀렉터/URL 편집 UI (yaml 폼 + diff + 1회 테스트 + 자동 PR)
- [ ] 신고큐 백엔드 + 그룹화 + 가중치 (UI에 점수 원인 표시)
- [ ] long-running lane + 코스트코 카테고리 샤드 + cron jitter
- [ ] 테이블 모드 / 문제만 보기 / 검색 / 프리셋
- [ ] drift 4분류 (parser / volume / session / business)
- [ ] 누락 의심 자동 진단 (단골 키워드 probe)
- [ ] **crawler→db contract** (`packages/shared/core/contracts`) + compat 회귀 테스트

### P2 — 확장 (6주 +)

- [ ] Playwright headful worker pool 정식화 (interactive=1 / automated=1 분리, profile lock, heartbeat, browser version pin)
- [ ] 새 소스 onboarding 위저드 (URL → probe → fixture → yaml draft → bounded diagnostic → live_ready 10단계)
- [ ] 모바일 surface 정식 채택 (홈플러스 mfront 일반화)
- [ ] 커뮤니티 플러그인 격리 실행기 (인터페이스 P1, 실행 P2)
- [ ] AI 셀렉터 patch 제안 입력 채널 (ai-admin 영역, 크롤러는 schema만)
- [ ] egress IP 풀 + 외부 프록시 (쿠팡/쇼핑몰 실험 lane)
- [ ] canary deploy + rollback (plugin.yaml sha + crawler.py sha + Chromium 버전 핀)

---

## 10. 미해결 / 추후 결단

1. **신고큐 가중치 캘리브레이션 계수의 근거** — 핫딜러 ×1.5, 신규 사용자 ×0.3은 heuristic. 운영 데이터 누적 후 보정. UI에는 점수 원인 표시(§5-D 형식)로 자의성 완화.
2. **headful worker pool 실제 자원 수치** — interactive=1, automated=1 시작. 코스트코가 OCC REST로 빠져나갔으니 부담 감소. 단 롯데/홈플 Playwright 동시 실행 시 RAM 4~6GB 가정 검증 필요.
3. **PC vs mobile surface가 가격이 다른 경우의 DB 모델** — 같은 상품인지 다른 상품인지 판정. crawler는 `surface` 메타까지, 판정은 AI/DB.
4. **egress IP 풀 도입 시점** — 쿠팡 tracked_urls 모델이 충분히 안정화된 후, P2에서 결정.
5. **schema_version 2 → 3 진화 시 마이그레이션 부담** — v5 schema가 2다. 향후 3 진화 시 read-compat 2버전 동시 부담 누적 가능.

---

## 11. v1~v4 추적 매트릭스

| 항목 | v1 | v2 | v3 | v4 | v5 결단 |
|---|---|---|---|---|---|
| 공통 엔진 4종 | 4종 제안 | 4종은 코드에 없음 지적 | 4종 신규 작업 명시 | — | **5종으로 확장 (OccRestApi 추가)** §3-A |
| yaml schema | 느슨 (자수) | name/version만 강제 지적 | capability schema v2 제안 + 일괄 마이그레이션 | 일괄 PR 깨진다 → 3단계 마이그레이션 | **3단계 마이그레이션 + 6단계 상태** §3-C |
| circuit breaker | 자수 누락 | 연결 안 됨 지적 | strategy loop 연결 | attempt_cost 보강 필요 | **yaml depth + 런타임 attempt_cost 게이트** §4-A |
| 신고큐 악용 | 자수 약점 | 그룹/가중치 제안 | 가중치 공식 + 그룹 키 | 캘리브레이션 미흡 자수 | **가중치 + 점수 원인 표시** §5-D, §10 |
| 코스트코 동시성 | 자수 약점 | 토큰버킷 + lane 제안 | long-running lane + 샤드 + jitter | 토큰버킷 값 metric 기반 조정 | **OCC REST로 본 부담 해소 + 잔여는 lane/샤드/jitter** §2-1, §9 P0 |
| operator workbench | "신뢰 경로" 표현 | "학습용 비상 경로" 격하 | 1급 시민 + 1회 흡수 | 4등급 산출물 분리 제안 | **1급 + 4등급 lifecycle** §5-C |
| 홈플러스 SSR 오류 | 오류 | 정정 | 정정 + SPA Playwright | — | **mobile surface 정식 채택** §2-1, §3-B |
| 이마트 표기 오류 | 오류 | 정정 | 정정 (`__NEXT_DATA__`) | — | §2-1 그대로 |
| 코스트코 yaml stale | (자수) | 0.4.0 stale 지적 | 0.5.0 마이그레이션 | — | **v0.6.0 + OCC REST 995×3 검증** §2-1, §9 P0 |
| 롯데 yaml/실측 충돌 | 충돌 | 충돌 지적 | live_ready=true 갱신 | — | **240×3 확정** §2-1, §2-3 |
| ToS/협상 | 미언급 | 협상 채널 제안 | 코드 영역 아님 (배척) | evidence ledger 보강 | **evidence ledger 구조화, 협상은 운영 매뉴얼로** §8-C |
| retry 상한 | 미언급 | 1~2회 상한 제안 | depth/cooldown으로 거부 | attempt_cost 모델 보강 | **depth(yaml) + cost(런타임)** §4-A |
| headful 배포 | 미언급 | 운영자 PC로 떠넘김 | worker pool 1~2개 | 자원 SLO + profile lock | **interactive 1 + automated 1 분리** §9 P2 |
| tracked_urls 수명 | 미언급 | 미언급 | "영구 등록" | subscription lifecycle 제안 | **6 status × 5 tier + 검토 큐** §5-D |
| profile 만료 | 미언급 | 미언급 | persistent profile 재사용 | 만료 루프 보강 | **refresh queue + state probe** §3-B, §4-D |
| drift false positive | 미언급 | drift 점수 제안 | drift 점수 신규 | 4분류 분리 | **parser/volume/session/business** §4-B |
| PC vs mobile | 미언급 | 홈플러스 SPA 지적 | 미언급 | 동등 surface 제안 | **`surface` 필드 정식** §3-B, §9 P2 |
| crawler→db contract | 경계만 | 미언급 | payload 예시 | shared/core/contracts 제안 | **TypedDict + JSON Schema + compat test** §8-B |
| 광고/카테고리 위장 | 미언급 | 미언급 | 미언급 | 메타 보존 제안 | **is_sponsored, rank_position 등 채택** §8-D |
| 가격 표시 변경 | 미언급 | 미언급 | 정규화 안 함 (raw만) | price_text_raw + confidence 제안 | **raw 보존 + parse_confidence** §6-D |
| 지역/지점 가격 | 미언급 | 미언급 | 미언급 | store_context 제안 | **region_context 정식** §8-E |
| deploy/rollback | 미언급 | 미언급 | 미언급 | plugin.yaml sha + canary 제안 | **P2 canary + rollback** §9 P2 |
| 안전 타령 추방 | D-3/D-4 추방 선언 | (살짝 회피적) | 재선언 | (배척 자리 일부) | **재선언 + 표로 명시** §S-3, §12 |

---

## 12. 안전 타령 + 운영자 떠넘김 + 동적 차단 배척 최종 선언

다음은 **금지** (v1 D-4 / v3 §I 재확인 + v5 추가):

1. **"안전" "보안" "위험"이라는 단어로 크롤러 기능 진입 자체를 막는 분기** — `requires_operator_capture=True`, `captcha=False, stealth=False` 같은 작업 마비 패턴. 재발 시 즉시 제거.
2. **"운영자가 매번 누르면 된다"는 전제로 자동화 회피** — 워크밴치는 1급이지만, **누를 빈도가 줄어드는 것이 정상.** 매주 → 매월 → 분기로 수렴해야 함.
3. **"외부 협상/제휴 채널로 떠넘기기"** — 크롤러 산출은 evidence ledger까지. 협상은 운영 매뉴얼.
4. **"retry 횟수 상한으로 자동 복구를 죽이기"** — depth는 yaml에서 명시(상한), cost는 런타임에서 가변. 무한 핑퐁만 차단.
5. **"yaml 강제 키 늘려서 운영자 편집 권한 축소"** — UI에서 selector/url/keyword/threshold/escalation 직접 편집 유지.
6. **"동적 차단 시그니처 감지 시 그냥 멈춤"** — 감지 → escalation → workbench까지 가야 함.

**유지하는 합법/불법 경계 (양보 없음):**
- ❌ captcha 자동풀이
- ❌ 자격증명 도용 / 인증 우회
- ❌ WAF 토큰 위조 / 액세스 컨트롤 우회
- ❌ robots.txt 명시 위배 영역 강제 진입

---

## 13. 자기검증

### 13-A. v4 약점 (v3 §I 자수 6 + v4 §C/§D/§E 보강 6) 다 답했나

| v4 약점 | v5 응답 위치 |
|---|---|
| capability schema 마이그레이션 비용 (PR 하나 안 끝남) | §3-C 3단계 마이그레이션 + 6단계 상태 |
| headful pool 실제 자원 비용 | §9 P2 interactive/automated 분리, §10 #2 자원 수치 |
| profile 만료/재학습 루프 | §3-B profile_state, §4-D refresh queue |
| drift false positive | §4-B 4분류 |
| tracked_urls 폭증/만료 | §5-D 6 status × 5 tier + 검토 큐 |
| 신고큐 가중치 캘리브레이션 | §5-D 점수 원인 표시, §10 #1 |
| evidence ledger 구조 | §8-C 필드 명시 |
| 도메인 토큰버킷 적정값 | §3-D + §10 (metric 기반 조정, 초기 보수적) |
| UA sticky vs random | §3-D `per_profile_sticky` 기본 |
| 모바일 surface 동등 | §3-B `surface` 필드 + §9 P2 |
| 가격/상품명 변경 | §6-D raw + confidence |
| deploy/rollback | §9 P2 canary + sha pin |
| 광고/스폰서 메타 | §8-D |
| 카테고리 위장 메타 | §8-D |
| 지역/지점 가격 | §8-E |
| crawler↔db contract | §8-B 위치 + 회귀 테스트 |
| yaml UI vs git PR 권한 | §5-E 섹션 경계 명시 |
| 워크밴치 영구 등록 검토 큐 | §5-D |

→ **v4 약점 18개 모두 §5 본문에 응답 위치 있음.**

### 13-B. 사용자 헌법 위반 점검

| 헌법 | 위반? | 확인 |
|---|---|---|
| 동적 대응 1급 | 없음 | escalation depth + attempt_cost (§4-A), drift 4분류 (§4-B) |
| 모듈화 / 결합도 0 | 없음 | 코코달인-코스트코 분리(§2-1), 어댑터 별도(§7), contract 위치 고정(§8-B) |
| 플러그인 자유 (커뮤니티) | 없음 | P2 격리 실행기 (§9) |
| 운영자 워크밴치 1급 | 없음 | §5 전체, 1급 탭 명시, 4등급 산출물 |
| 안전 타령 추방 | 없음 | §12 명시 선언, §S-3 v4 배척 자리 |
| 자동화 회피 금지 | 없음 | §4-D 자동화 흡수 case 명시, §12 #2 |
| raw + 메타까지만 | 없음 | §1-2 책임/비책임, §6-D 정규화 X 보존 O |

### 13-C. 다른 영역(DB/AI/웹) 기획과의 충돌 점검

본 문서 §8 모듈 경계로 정리:
- DB: contract `packages/shared/core/contracts/crawler_to_db_v2.py` 기준. major bump 시 양쪽 동시 PR. — 충돌 없음
- AI: yaml selector patch suggestion 입력 채널만 노출. AI가 크롤러 import / DB 직접 쓰기 금지. — 충돌 없음
- 웹: source 상태 read-only + 신고 큐 POST. yaml 직접 쓰기는 관리자 UI 경유만. — 충돌 없음

DB/AI/웹 v1~v4 문서를 본 문서가 직접 깊이 파지 않음 (사용자 금지 사항). 경계만 명시.

### 13-D. v5의 자기 약점 (Round-B에서 깔 만한 자리)

1. **OccRestApiRunner를 5번째 엔진으로 격상했지만, "코스트코 외 OCC 사이트"가 현재 후보 없음.** 일반화 가치가 1개 사이트 전용보다 큰지 향후 재평가 필요.
2. **attempt_cost 공식의 가중치 (`domain_pressure + worker_pressure + ...`)** 가 heuristic. drift 가중치와 마찬가지로 운영 데이터 누적 후 보정 필요.
3. **schema v2가 너무 큼.** 25개 yaml을 6주에 마이그레이션하는데, 그동안 schema v1과 v2 read-compat 코드 부담이 누적. canary 검증 부족 가능성.
4. **신고큐 점수 원인 표시 UI가 백엔드 가중치 변경에 끌려다님.** 가중치 바뀔 때마다 UI 표시 룰도 같이 바뀌어야 함. 추적 부담.
5. **headful worker pool interactive=1 / automated=1 결단이 너무 작을 수 있음.** 동시 운영자가 2명 이상이면 interactive 큐가 바로 막힘. 운영 단계에서 동적 조정 가능하게 yaml 키 필요.
6. **evidence ledger 저장 용량 폭증.** 매 요청 단위로 메타 저장 시 디스크 빠르게 참. TTL/로테이션 정책 §8-C에 빠짐.

이상 6개는 Round-B 또는 운영 단계에서 보강 대상.

---

*작성: Opus 4.7 — Round-A 마지막 타자, 단일 완성 기획서. v1~v4는 참조용으로 보존, 본 문서가 크롤러 영역 진실 원본.*
