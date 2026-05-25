# 크롤러 영역 기획 v4 — GPT 반론자

> Round-A / 4번 타자. 입력: v1(`crawler-v1-opus.md`), v2(`crawler-v2-gpt.md`), v3(`crawler-v3-opus.md`).  
> 범위: `packages/crawler-admin/` 중심. v1~v3는 수정하지 않는다.  
> 입장: v3의 방향은 대체로 맞다. 그러나 v3는 v2의 회피성 결론을 쳐내는 과정에서 운영 비용·수명주기·상호 계약 문제를 과소평가했다. v4는 자동화를 죽이지 않고, 워크밴치도 격하하지 않고, 새로 터질 구멍을 더 세게 찍는다.

---

## A. 본문 요약 + v4 입장

v1은 “raw record 공장 + yaml 운영 + 모니터 UI”라는 큰 그림을 제시했다. v2는 실제 코드와의 불일치, 느슨한 yaml, circuit breaker 미연결, 신고큐 폭주, 코스트코 장기 실행을 정확히 찔렀다. v3는 그중 사실을 흡수했고, 동시에 operator workbench 격하·headful 외주·retry 1~2회 상한·ToS 대응을 외부 문서로만 넘기는 방식을 잘라냈다.

v4의 입장은 이렇다.

1. **워크밴치는 1급 시민이 맞다.** 다만 “항상 보인다”와 “항상 눌린다”는 다르다. 워크밴치 결과가 자동 경로·tracked_urls·fixture·profile TTL로 흡수되는 폐루프가 없으면 1급 UI는 1급 수동노동으로 변한다.
2. **retry budget이라는 말은 나쁘지만, depth/cooldown만으로도 부족하다.** 도메인·IP·UA·profile 조합별 실패 이력과 다음 시도 비용을 계산해야 한다. escalation depth는 yaml 값이 아니라 런타임 상태를 먹어야 한다.
3. **headful worker pool은 가능하다.** 하지만 v3의 “1~2개면 끝”은 숫자 없는 선언이다. 세션 수, 스크린샷 폴링, profile 잠금, worker 재시작, 브라우저 업데이트까지 운영 단위로 잡아야 한다.
4. **ToS/IP 통보 대응을 코드 밖으로만 밀면 안 된다.** 대외 대응 문서는 코드가 아니지만, 어떤 요청이 어떤 설정·IP·UA·profile로 나갔는지 재현 가능한 evidence ledger는 코드 영역이다. 단순 로그 저장보다 훨씬 구조화돼야 한다.
5. **v3가 놓친 핵심은 ‘수명주기’다.** yaml 마이그레이션, tracked_urls 정리, profile 만료, UA/프록시 풀 교체, 모바일 사이트 병행, deploy/rollback, crawler-admin↔db-admin schema 안정성 모두 시간이 지나며 터지는 문제다.

---

## B. v3가 v2를 배척한 항목 재검토

### B-1. operator workbench 1급 시민 정당성 — 자동화로 갈음 안 되는가

v3가 맞다. operator workbench는 “학습용 비상 경로”가 아니라 정식 제품 기능이다. 현재 코드에도 `/api/operator-browser`가 세션 시작, 스크린샷, DOM HTML, navigate/click/fill을 이미 라우트로 갖고 있고, `OperatorWorkbenchStore`도 capture/register 저장소를 갖고 있다. 이걸 숨기면 사용자가 요구한 “전용 브라우저로 검색·일부 긁기·영구 등록”이 사라진다.

다만 v3의 약점은 **워크밴치 산출물의 등급 구분**이 없다.

- 즉시 수확: 지금 화면에서 선택한 상품을 raw item 후보로 뽑음.
- 영구 등록: URL을 tracked_urls에 넣고 주기 갱신.
- 자동화 흡수: profile/cookie/HAR/selector 후보를 다음 cron에 반영.
- fixture화: 회귀 테스트와 drift baseline으로 고정.

이 네 가지를 한 버튼 결과처럼 취급하면 DB에 반영할 수 있는 데이터와 분석용 artifact가 섞인다. 워크밴치는 1급이어야 하지만, **산출물은 등급·TTL·검토 상태가 있어야 한다.** 자동화가 완전히 갈음할 수 없는 영역은 맞다. 대신 워크밴치가 자동화의 우회로가 아니라 자동화 입력으로 누적되는 구조가 필수다.

### B-2. retry budget 상한 → escalation depth/cooldown 갈음 충분성

v3가 “사이클당 1~2회 상한”을 거부한 건 맞다. 쿠팡/롯데/홈플 같은 소스에서 한 번 막혔다고 다음 cron까지 기다리면 복구가 늦다.

하지만 v3의 `escalation depth + cooldown`만으로는 충분하지 않다.

문제는 retry 횟수가 아니라 **시도 조합의 비용**이다.

- 같은 egress IP에서 requests 실패 후 headless, headful까지 가는 비용
- 같은 persistent profile이 오염됐을 때 재사용하는 비용
- UA를 바꾸면 cookie/profile fingerprint와 불일치하는 비용
- headful worker를 점유해 다른 워크밴치 세션을 밀어내는 비용
- category shard 중 일부만 실패했는데 full source escalation으로 번지는 비용

따라서 v5는 `budget`이라는 단어를 버리되, 다음 상태 모델은 넣어야 한다.

```text
attempt_cost = domain_pressure + worker_pressure + profile_age + blocker_severity + shard_scope
next_step = escalation_depth[step] if attempt_cost <= source_max_cost else defer_to_next_window
```

즉, 상한이 아니라 **상태 기반 비용 게이트**다. 자동 복구는 계속 살리고, 무의미한 반복만 잘라낸다.

### B-3. headful worker pool 자원 부담

v3의 반박은 맞다. headful을 “서버에서 안 뜬다”로 끝내는 건 과잉 단정이다. Windows desktop session, Xvfb, VNC, 전용 worker 모두 선택지다.

그러나 v3는 pool을 너무 쉽게 썼다. headful pool에는 최소 다음 수치가 필요하다.

| 항목 | v3 표현 | v4 보강 |
|---|---|---|
| 동시 세션 | 1~2개 | `workbench_interactive=1`, `automated_headful=1` 분리. 사람이 조작하는 세션과 자동 escalation 세션을 같은 큐에 넣지 말 것 |
| 메모리 | worker당 1.5GB | 실제로 페이지 3~5개, screenshot polling, devtools protocol 켜면 2~3GB까지 잡아야 함 |
| profile lock | 언급 약함 | source별 profile은 동시에 한 세션만 mount. 같은 profile 동시 사용 시 쿠키 DB 손상 가능 |
| 라이브 뷰 | 스크린샷/VNC | 1초 폴링 PNG면 대역폭·CPU가 크다. 기본 2~3초, 움직임 감지 시 가속 |
| 장애 복구 | 없음 | worker heartbeat, 브라우저 zombie cleanup, session timeout, profile backup/restore 필요 |
| 브라우저 버전 | 없음 | Playwright/Chromium 업데이트가 fingerprint와 파서를 동시에 흔든다. 버전 pin + staged rollout 필요 |

결론: headful pool은 v3 말대로 내부 자산이어야 한다. 단, v5는 pool을 기능명이 아니라 **스케줄링 대상 자원**으로 설계해야 한다.

### B-4. ToS 증거 로그까지가 코드 영역 — 진짜 그런가

v3가 “대외 대응 문서는 코드 영역 아님”이라고 잘라낸 건 맞다. 하지만 “증거 로그까지”라는 표현은 너무 얇다.

코드가 해야 할 것은 단순 로그 파일이 아니라 **evidence ledger**다.

필수 필드:

- source_id, domain, collection_path, crawl_intent
- request count, status 분포, blocker_signature
- egress_ip_id, proxy_provider/type, region
- UA family/version, sec-ch-ua 계열, Accept-Language
- strategy: requests/cloudscraper/playwright_headless/headful/workbench
- profile_id, profile_age, cookie_age, login_state 추정
- robots-sensitive path 접근 여부가 아니라 실제 path prefix 목록
- schedule source: cron/manual/workbench/tracked_url/report_queue
- code version: git sha, plugin.yaml sha, schema_version

이 정도가 있어야 “무엇이 나갔는가”를 재현하고 조정한다. v5는 대외 대응 템플릿을 만들 필요가 없다. 대신 **요청 단위 재현성**은 코드가 책임져야 한다.

---

## C. v3 새 도입의 약점

### C-1. capability 기반 yaml schema 마이그레이션 비용

v3는 25개 plugin.yaml을 한 번에 schema v2로 바꾼다고 했다. 실제로는 PR 하나로 끝나지 않는다.

현재 yaml은 이미 서로 다르다.

- 롯데/홈플러스 `entrypoints`는 list 형태.
- 이마트 계열은 dict 형태가 섞인다.
- 코스트코는 `version: 0.4.0`, `strategy: requests`, `live_ready: true`인데 코드 방향은 Playwright/OCC다.
- 아카라이브 yaml은 `name`, `group`, `target_url`, `strategies` 정도만 있는 얇은 파일이다.
- `rate_limit_seconds`는 숫자이고, v3 schema는 `rate_limit.per_domain_rps/page_sleep_sec/jitter_sec`다.

마이그레이션은 세 단계여야 한다.

1. **read compatibility**: loader가 v1/v2를 둘 다 읽고 내부 normalized config로 컴파일.
2. **write policy**: UI 저장은 v2만 쓰게 하되, v1 파일은 자동 저장하지 말고 명시적 변환 큐에 넣음.
3. **test matrix**: fixture 없는 skeleton 플러그인은 live_ready=false로 묶되, schema 변환 실패와 crawler 실패를 분리해서 표시.

v5가 “일괄 변환”만 쓰면 다음 라운드에서 운영 파일이 깨진다.

### C-2. tracked_urls 폭증 시 정리

v3는 영구 등록을 핵심 기능으로 올렸다. 맞다. 그런데 `tracked_urls`는 반드시 썩는다.

폭증 경로:

- 워크밴치에서 매주 100개 등록
- 신고큐에서 URL 자동 등록
- 쿠팡처럼 카탈로그 대신 tracked_url만 쓰는 소스 증가
- 모바일/PC URL이 같은 상품을 중복 등록
- 품절/삭제/리다이렉트 상품이 계속 6시간 주기로 돈다

정리 정책:

- `status`: active / stale / redirected / discontinued / duplicate_candidate / review_required
- `refresh_tier`: 1h / 6h / daily / weekly / paused
- `last_seen_valid_at`, `last_price_change_at`, `consecutive_no_change`, `consecutive_failures`
- 30일 가격 변화 없음 + 조회 가치 낮음 → weekly로 강등
- 14일 연속 404/품절/상품삭제 → stale 후 검토 큐
- canonical_url 같으면 병합 후보
- 같은 상품 다른 URL은 DB/AI 매칭 전이라도 `source_record_key` 후보로 묶기

“영구”라는 단어를 UI에 쓰더라도 내부는 **수명 있는 subscription**이어야 한다.

### C-3. profile 만료 루프

v3는 “워크밴치로 한 번 로그인 → persistent profile 재사용”을 강하게 밀었다. 이건 필요한데, 만료 루프가 빠졌다.

세션 만료는 단순 401이 아니다.

- 로그인 페이지로 redirect
- 가격만 비회원가로 강등
- 지역 선택 초기화
- 성인/연령 확인 reset
- bot challenge cookie만 만료
- 사이트가 device fingerprint를 갱신해 기존 profile을 의심
- Chromium 버전 변경으로 storage가 깨짐

profile에는 다음 메타가 필요하다.

```yaml
profile_state:
  profile_id: arca-main-operator
  last_human_refresh_at: ...
  cookie_expires_min: ...
  last_success_strategy: playwright_headful
  login_state_probe: selector_or_url_rule
  region_state_probe: selector_or_cookie_rule
  refresh_due_at: ...
  backup_snapshot: ...
```

그리고 “워크밴치 열어라”가 아니라 **profile refresh queue**가 있어야 한다. 어떤 profile이 언제 만료될지 먼저 보여줘야 새벽 장애가 줄어든다.

### C-4. drift 감지 false positive

v3의 drift 점수는 필요하다. 그러나 row count 하락을 구조 변경으로 바로 해석하면 알람이 터진다.

false positive 원인:

- 시즌 행사 종료
- 특정 카테고리 일시 품절
- 마트가 오늘 전단을 늦게 배포
- 지점/배송지 선택이 풀려 상품 수가 줄어듦
- 모바일/PC 중 한쪽만 먼저 업데이트
- 가격은 있는데 할인 배지만 빠짐
- 검색 키워드 트렌드 변화

보강:

- selector hit 하락과 HTML 구조 hash 변화가 같이 있을 때 구조 drift로 승격
- row count만 줄면 volume anomaly로 분리
- fixture drift와 live business fluctuation을 다른 라벨로 표시
- 단골 probe 키워드도 전년/전월/요일 baseline을 가져야 함
- “우유 12→0”이 아니라 전체 카테고리 중 몇 개가 동시에 빠졌는지 봐야 함

v5는 drift를 한 점수로 만들지 말고 `parser_drift`, `source_volume_anomaly`, `session_state_loss`, `catalog_business_change`로 나눠야 한다.

### C-5. 도메인 토큰버킷의 적정 값 결정

v3는 `per_domain_rps=0.1~0.5`를 제시했다. 숫자가 너무 둥글다.

도메인 rate limit은 source 단위가 아니라 다음 차원으로 결정된다.

- domain + egress_ip_id
- strategy(headless/headful/requests)
- path group(search/category/detail)
- time window(새벽 full crawl vs 저녁 tracked_url)
- response class(200/202/403/timeout)
- worker pool pressure

초기값은 보수적으로 둬도, 운영 중 조정은 metric 기반이어야 한다.

필수 지표:

- request interval histogram
- blocker rate by interval
- success rows per request
- bytes per request
- median/95p response time
- egress_ip별 403/202 비율
- source별 “한 건 유효 item을 얻는 비용”

토큰버킷 값은 yaml에 박되, UI에서 “최근 7일 기준 이 값이 너무 높다/낮다”를 보여줘야 한다.

---

## D. v3 자수 6포인트 보강

### D-1. capability yaml schema v2 마이그레이션 비용

v3 자수 그대로 맞다. 추가로 **schema drift와 code drift를 분리**해야 한다. yaml 변환 실패, crawler runtime 실패, parser coverage 실패가 같은 빨강으로 보이면 못 고친다.

필요 상태:

- `config_schema_valid`
- `config_compiled`
- `entrypoint_import_ok`
- `fixture_parse_ok`
- `bounded_live_ok`
- `ui_editable`

이 6단계를 카드에 따로 보여줘야 한다.

### D-2. headful worker pool 실제 자원 비용

v3 자수보다 더 크다. headful은 CPU/RAM만 문제가 아니라 **profile 독점**과 **사람 세션 우선순위**가 문제다. automated headful이 operator interactive 세션을 밀어내면 워크밴치 1급 시민 선언이 무너진다.

추가 정책:

- interactive workbench는 자동 escalation보다 우선
- source profile lock이 걸리면 다른 작업은 read-only fixture replay만 가능
- 세션 종료 시 profile snapshot 저장, 실패 시 이전 snapshot restore
- worker 재시작은 source 단위가 아니라 profile 단위로 감사

### D-3. persistent profile + 쿠키 jar 만료/재학습 루프

v3 자수 정확하다. 보강은 **만료 예측**이다.

- 마지막 성공 후 N일이 아니라 cookie expiry min을 읽는다.
- 로그인 state probe를 source별 yaml에 둔다.
- profile refresh를 cron으로 미리 띄운다.
- profile이 손상되면 새 profile 생성 전 기존 profile을 격리 보관한다.
- “한 번 로그인”은 초기 bootstrap일 뿐, 운영 모델은 profile lifecycle이다.

### D-4. selector drift 점수 false positive

v3 자수 정확하다. 보강은 **원인 분류**다.

- DOM 구조 변화: selector/path 후보 재학습
- 상품량 변화: schedule/probe/baseline 확인
- 세션 상태 손실: 지역/로그인/profile probe
- blocker soft fail: 200이지만 challenge shell 반환
- parser regression: fixture도 실패하면 코드 변경 문제

이렇게 갈라야 알람이 행동으로 연결된다.

### D-5. tracked_urls 누적 폭증과 만료 정책

v3 자수 정확하다. 보강은 **검토 큐**다. 영구 등록 URL은 삭제보다 검토가 먼저다.

검토 큐 조건:

- 14일 연속 invalid
- canonical_url 변경
- 같은 source_record_key 후보 2개 이상
- 가격 변화 90일 없음
- 사용자 신고는 많은데 crawler는 정상이라고 보는 충돌
- 광고/스폰서 의심 플래그 발생

운영자가 워크밴치로 등록한 URL도 예외가 아니다. “사람이 등록했으니 영원히 믿는다”는 운영 부채다.

### D-6. 신고큐 가중치 캘리브레이션

v3 자수 정확하다. 계수는 처음부터 맞출 수 없다. 최소한 다음 데이터를 쌓아야 한다.

- 신고 그룹이 실제 crawler/parser 수정으로 이어진 비율
- 신고 후 가격/품절 오류가 확인된 비율
- 사용자 신뢰 등급별 precision
- source별 허위/중복 신고율
- 신고가 tracked_url 등록으로 이어진 뒤 30일 생존율

처음 계수는 heuristic이어도 된다. 단, UI에는 점수 원인을 표시해야 한다. “신고 37점”이 아니라 “유니크 9명 + 최근 Akamai 403 + 동일 IP 폭주 감점”처럼 보여야 한다.

---

## E. v1~v3가 놓친 시나리오

### E-1. IP 풀/프록시 운영 — 자체호스팅 vs 외부

코드에는 `AntiDetect`의 proxy rotation 골격이 있다. 하지만 운영 모델은 비어 있다.

선택지는 둘이다.

| 방식 | 장점 | 약점 | v5 결론 포인트 |
|---|---|---|---|
| 자체호스팅 egress 1~2개 | 통제 쉬움, 비용 예측 | IP 다양성 낮음, 한 번 찍히면 회복 느림 | 마트 4사 기본값 |
| 외부 프록시 풀 | IP 다양성, 지역 선택 | 품질 편차, 세션 일관성 깨짐, 비용 큼 | 쿠팡/쇼핑몰 실험 lane 한정 |

핵심은 proxy를 많이 넣는 게 아니라 **egress_ip_id를 모든 로그·circuit·rate limit key에 넣는 것**이다. IP가 바뀌면 profile/UA/cookie도 같이 맞춰야 한다.

### E-2. User-Agent 변경/관리

현재 UA pool은 있다. 문제는 무작위 선택이 항상 답이 아니라는 점이다.

- cookie jar는 특정 UA/fingerprint에서 만들어졌는데 다음 요청이 다른 UA면 의심 신호가 된다.
- 모바일 UA로 접근하면 모바일 DOM/API가 열려 parser가 달라진다.
- Safari UA인데 sec-ch-ua를 Chrome처럼 보내면 fingerprint가 어긋난다.
- UA 버전이 너무 최신/낡으면 사이트별 차단률이 달라진다.

필요 모델:

```yaml
ua_profile:
  family: chrome_windows
  version_pin: 131
  mobile: false
  rotate_policy: per_profile_sticky   # per_request 아님
  compatible_headers: chrome_desktop_ko
```

UA는 per-request random이 아니라 **profile/session 단위 sticky**가 기본이어야 한다.

### E-3. 마트 모바일 사이트 별도 크롤링 가능성

홈플러스는 이미 `mfront`가 핵심이다. 다른 마트도 모바일 경로가 더 단순할 수 있다.

v5는 source_map에 `surface`를 넣어야 한다.

```yaml
source_map:
  - id: weekly_sale_pc
    surface: pc_web
  - id: weekly_sale_mobile
    surface: mobile_web
```

장점: 모바일 API/DOM이 더 안정적일 수 있다.  
단점: 가격/행사/배송지/회원가가 PC와 다를 수 있다.  
따라서 모바일은 fallback이 아니라 **동등한 surface**로 수집하고, DB에는 `surface` 메타를 넘겨야 한다.

### E-4. 로그인 필요 사이트(아카라이브) 후순위 — 진짜 운영자 1회 로그인으로 충분?

충분하지 않다. 아카라이브 yaml은 현재 매우 얇고, 로그인/profile 수명주기 정보가 없다.

필요 항목:

- login_state_probe: 로그인 상태를 확인할 selector/url
- content_access_probe: 핫딜 본문 접근 가능 여부
- profile_refresh_cadence: 예: 14일
- session_expired_signature: 로그인 페이지 redirect, 권한 문구
- workbench_refresh_action: 같은 profile로 워크밴치 열기

“운영자 1회 로그인”은 시작점이다. v5는 **재로그인 예측과 실패 감지**를 yaml에 넣어야 한다.

### E-5. 가격 표시 변경 — `원` → `₩`, 천원 단위

가격 파서는 숫자만 뽑으면 끝이 아니다.

변경 시나리오:

- `1,990원` → `₩1,990`
- `1.9천원`
- `2개 5천원`
- `100g당 980원`
- `회원가 12,900 / 정상가 15,900`
- 이미지 배지에만 가격 표시

크롤러는 최종 단위 정규화까지 하지 않더라도, **가격 파싱 confidence와 원문 price_text**를 넘겨야 한다.

필수 필드:

- `price_text_raw`
- `sale_price` nullable
- `price_parse_confidence`
- `price_parse_rule_id`
- `unit_price_text_raw`

필드 coverage가 100%여도 가격 파서가 `1.9천원`을 19원으로 읽으면 장애다.

### E-6. 상품명 변경 — 같은 상품 다른 이름 추적

마트는 같은 상품명을 자주 바꾼다.

- `서울우유 1L` → `서울우유 나100% 1L`
- `농심 신라면 5입` → `신라면 멀티팩 120g*5`
- 행사명/증정 문구가 title에 붙음

크롤러는 cross-source 매칭을 하지 않는다. 하지만 source 내부 추적을 위해 다음 키는 만들어야 한다.

- source_product_id 추출 우선
- canonical_url
- image_url hash 후보
- brand/unit/package_quantity 원문
- title_normalized_light: 괄호/행사문구/공백 정도만 제거
- previous_title 후보를 diagnostics에 남김

DB/AI가 최종 매칭을 하더라도 크롤러가 raw clue를 안 주면 못 맞춘다.

### E-7. 크롤러 자체 deploy/rollback

v1~v3는 crawler.py/plugin.yaml 수정 이후 배포를 거의 다루지 않았다.

필수:

- plugin.yaml sha와 crawler.py sha를 run record에 저장
- schema migration 전후 fixture 결과 비교
- canary source 1개만 새 parser로 실행
- 실패 시 이전 plugin.yaml/crawler.py 조합으로 rollback
- operator UI 저장분도 git diff만 보여주고 끝내지 말고 rollback point 생성
- Playwright/Chromium 버전도 배포 단위에 포함

크롤러는 사이트 변화만 상대하는 게 아니다. **우리 배포가 사이트 변화처럼 장애를 만든다.**

### E-8. 운영자가 워크밴치로 영구 등록한 URL의 검토 큐

영구 등록은 등록 순간보다 정리 순간이 더 중요하다.

검토 큐 컬럼:

- 등록자/등록 경로(workbench/report_queue/manual yaml)
- 등록 근거 capture_id
- 마지막 유효 가격 시각
- 마지막 사용자 노출 시각
- 실패 연속 횟수
- canonical merge 후보
- 광고/스폰서 의심
- 삭제/강등/유지 액션

tracked_url이 많아질수록 검토 큐가 없으면 crawler 비용이 조용히 샌다.

### E-9. yaml 편집 UI vs 직접 git PR

v3는 UI 저장 + git diff를 말했다. 결단이 더 필요하다.

- 긴급 selector 수정: UI에서 patch, bounded diagnostic 통과, hot reload. 이후 자동 PR 생성.
- 구조 큰 변경: 직접 git PR, fixture/test 포함.
- UI 저장 권한: 운영자만. 일반 web frontend는 신고만.
- UI가 고칠 수 있는 섹션: selector/url_template/search_keywords/output threshold/waf escalation 정도.
- UI가 못 고치는 섹션: entrypoint module/class, dependency, schema_version major.

UI 직접 저장과 git PR을 섞을 수 있다. 단, **권한과 섹션 경계**가 없으면 운영 중 config가 추적 불가능해진다.

### E-10. crawler-admin과 db-admin 사이 schema 안정성

v3는 raw payload schema 예시를 줬다. 부족한 건 compatibility 정책이다.

필요 규칙:

- crawler output schema major 변경 시 db-admin이 거부 가능
- minor 필드 추가는 허용
- 필드 삭제/이름 변경은 deprecation 기간 필요
- `source_record_key` 안정성은 테스트로 보장
- `sale_price` 타입은 int KRW 또는 null만 허용
- price_text/raw fields는 optional로 추가하되 DB ingest가 보존 가능해야 함
- crawler-admin 배포와 db-admin 배포 순서가 바뀌어도 ingest가 깨지지 않게 contract test 필요

`packages/shared/core/contracts`가 있으니 여기에 crawler→db contract를 명시해야 한다.

### E-11. 광고/스폰서 상품 식별

마트/쇼핑몰은 검색 결과에 광고/스폰서/추천 상품을 섞는다.

문제:

- 광고 상품은 카테고리와 무관하게 상단 노출
- 가격 비교에서 일반 상품처럼 보이면 왜곡
- 스폰서 배지는 DOM에만 있고 API 필드에는 없을 수 있음

크롤러는 제거하지 말고 메타를 남겨야 한다.

- `is_sponsored`
- `sponsored_badge_text`
- `rank_position`
- `section_name` (추천/광고/검색결과/전단)
- `extraction_selector_id`

DB/AI가 필터링하게 하되, 크롤러가 신호를 보존해야 한다.

### E-12. 카테고리 위장 상품

잘못 분류된 상품은 흔하다.

- 라면 카테고리에 냄비 광고
- 신선식품 카테고리에 배송비 쿠폰
- 검색 키워드 `우유`에 바디워시가 걸림

크롤러는 카테고리 추론을 하지 않는다. 하지만 `category_hint` 하나로는 부족하다.

필요 raw meta:

- `source_category_path`
- `breadcrumb_text`
- `search_keyword`
- `result_section`
- `rank_position`
- `matched_terms`

이 정보가 있어야 AI/DB가 “위장/오분류”를 판단한다.

### E-13. 지점별 가격 차이 — 오프라인 가격 vs 온라인

마트 가격은 지역/배송지/회원/오프라인 전단에 따라 다를 수 있다.

v5는 가격 record에 context를 붙여야 한다.

- `store_context`: online_default / delivery_region / offline_branch / member_only
- `region_code` 또는 `branch_id` nullable
- `region_source`: cookie/profile/manual/default
- `price_scope`: online / offline / unknown
- `membership_required`

워크밴치에서 지역 선택을 했다면 그 profile의 region state가 가격에 묻는다. 이걸 안 남기면 같은 상품 가격이 “드리프트”처럼 보인다.

---

## F. v5(Opus 최종)가 결단할 질문 5개

1. **워크밴치 산출물 4등급을 schema로 분리할 것인가?** 즉시 수확, 영구 등록, 자동화 흡수, fixture화를 같은 capture로 둘지, 서로 다른 lifecycle 객체로 둘지 결정해야 한다.
2. **retry를 횟수가 아니라 attempt_cost 모델로 갈 것인가?** v3의 depth/cooldown에 domain/IP/profile/worker 비용을 붙일지, 단순 yaml depth로 끝낼지 결단해야 한다.
3. **tracked_urls를 ‘영구 URL’이 아니라 subscription lifecycle로 설계할 것인가?** tier, stale, review queue, canonical merge, TTL을 P1에 넣을지 뒤로 미룰지 결정해야 한다.
4. **PC web과 mobile web을 동등한 surface로 둘 것인가?** 홈플러스 mfront처럼 모바일 경로가 핵심인 경우를 일반화할지, fallback 취급할지 정해야 한다.
5. **crawler-admin↔db-admin contract를 어디서 고정할 것인가?** `packages/shared/core/contracts`에 schema/version/compat test를 둘지, 문서와 예시 payload로만 둘지 결정해야 한다.

---

## v4 결론

v3의 큰 방향은 유지한다. 워크밴치 1급 시민, capability yaml, 도메인 circuit, headful pool, tracked_urls, drift 감지는 맞다. 하지만 v3는 “만든다”에 강하고 “늙는다”에 약하다. v5는 운영 수명주기까지 닫아야 한다. profile은 만료되고, URL은 썩고, UA는 낡고, proxy는 더러워지고, schema는 서로 어긋나고, 가격 표시는 바뀐다. 이걸 처음부터 상태·TTL·검토 큐·contract로 박아야 크롤러가 한 달 뒤에도 돈다.



