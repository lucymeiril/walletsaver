# 크롤러 영역 기획 v1 — Opus 초안 (숲 관점)

> Round-A / 1번 타자. 다음: GPT 5.5 적대적 리뷰 → Opus 살붙이기 → GPT 반론 → Opus 최종.
> 범위: `packages/crawler-admin/` 만. DB/AI/웹은 경계까지만 언급.

---

## 0. 한 줄 요약

> **"크롤러는 raw record를 안정적으로 토해내는 공장이다. 사이트는 매주 바뀌고, 차단은 일상이고, 관리자는 새벽 3시에 깨고 싶지 않다. 그래서 모든 것은 plugin.yaml + 라이브 모니터 카드 + 한 줄짜리 우회 전략 토글로 끝난다."**

핵심 명제 4개:
1. **소스가 바뀌어도 코드 수정 없이 yaml만 바꿔서 복구 가능해야 한다.**
2. **차단은 버그가 아니라 정상 상태다.** 차단을 "감지 → 알림 → 전략 전환"하는 루프가 1급 시민이다.
3. **합법 위장은 기본 장착, 공격은 금지.** "안전 타령"으로 크롤러 자체를 못 돌게 만드는 코드는 v1에서 모두 추방한다.
4. **크롤러는 카테고리 추론도, 상품 매칭도 안 한다.** raw + 소스 메타데이터만 산출하고 손 뗀다.

---

## A. 현황 진단

### A-1. 마트별 도달 현황 (2026-05 기준 실측)

| 소스 | 카테고리 | 현재 행 수 | 방식 | 상태 | 비고 |
|---|---|---|---|---|---|
| 롯데마트 | mart | ~240 (목표 ≥200) | `__INITIAL_STATE__` SSR + SPA 카드 fallback | ⚠️ AWS WAF 202 간헐 | operator capture가 신뢰 경로 |
| 이마트 | mart | ~274 | SSR + 카드 파싱 | ✅ 안정 | |
| 홈플러스 | mart | ~199 | SSR | ⚠️ 임계 근접 | 200 못 넘으면 즉시 알람 |
| 코스트코 | mart | 48 → 300+ 목표 | requests 멀티패스 (15 카테고리 + 페이지네이션 7 + 검색 15) | 🟡 Playwright 백업 진행 중 | sleep 10s 필수 |
| 코코달인 | mart-adjacent | (별도 플러그인) | 독립 수집 | 🟡 진행 | 코스트코와 분리 — 결합도 0 |
| 쿠팡 | shopping | 0 | Akamai 100% 차단 | ❌ operator_capture만 가능 | traceId 변조 무효 검증됨 |
| 알구몬 | hotdeal | OK | requests 30분 주기 | ✅ | |
| 코코달인(핫딜측) | hotdeal | - | - | 🟡 | hotdeals/cocodal에도 별도 존재 |
| 아카라이브 | hotdeal | - | requests | 🟡 | |
| 오피넷 | government | - | 공공 API | ✅ 안정 | |
| 그 외 | ppomppu, fmkorea, clien, quasarzone, 11st, gmarket, naver_store, aliexpress, musinsa, uniqlo, giordano | 등록은 됨 | 다양 | 🟡 skeleton 다수 | live_ready=false 대부분 |

> 코드 근거: `crawlers/marts/{lottemart,emart,homeplus,costco,cocodalin}/plugin.yaml`, `crawlers/shopping/coupang/plugin.yaml`, `crawlers/hotdeals/*`.

### A-2. 사이트 방식 매핑 (왜 막히는가)

| 패턴 | 사이트 | 핵심 난점 | v1 해법 |
|---|---|---|---|
| **SSR + window.__INITIAL_STATE__** | 롯데마트, 일부 마트 | JSON 임베드는 쉬우나 WAF가 SPA-shell 반환 | yaml에 `parser_inputs: [initial_state, embedded_json, card_html]` 3단 fallback |
| **CSR / SPA shell** | 쿠팡, 일부 마켓플레이스 | JS 렌더 전엔 빈 껍데기 | Playwright headful, 안 풀리면 operator_capture |
| **XHR / API** | 오피넷, 일부 공공 | 안정적, 키만 잘 관리 | 그대로 |
| **WAF (AWS / Akamai / Cloudflare)** | 롯데마트(AWS WAF 202), 쿠팡(Akamai 403), 일부 | IP/UA로 즉시 차단 | UA 회전 + 세션 쿠키 jar + Referer 체인 + page sleep, 그래도 막히면 사람 한 번 풀고 세션 빌려쓰기 |
| **Bot Manager (행동 패턴)** | 일부 쇼핑몰 | 마우스/스크롤 패턴 검사 | Playwright + scroll 시뮬 + 페이지 간 sleep 10s |
| **공개 카탈로그 (게시판형)** | 알구몬, ppomppu, fmkorea, clien | 가벼움 | requests로 충분 |

### A-3. 관리자 UI 현황 (`frontend/src/pages/Crawlers/`)

**되는 것:**
- 카테고리 필터 (전체/마트/핫딜/배달/쇼핑/공공/위치)
- 개별/일괄 실행, 활성·비활성 토글
- 실행 진행률 SSE 푸시 + 폴링 fallback (지수 백오프 2→10s)
- 미니 타임라인 (최근 5회 성공/실패 점)
- 설정 모달 (target_url, delay, max_items)

**안 되는 것 (v1에서 메꿀 갭):**
- ❌ "왜 막혔는가" 증거를 한 화면에서 못 본다 (WAF 202 / Akamai 403 같은 차단 코드 라벨 부재)
- ❌ 차단 감지 시 전략 자동 전환 토글 (`requests → Playwright headful`, UA 교체) UI 없음
- ❌ 특정 상품만 영구 등록 (사용자 요청 "검색 한 번 등록" 패턴) 없음
- ❌ 사용자 신고("이 상품 데이터 없어요") → 관리자 큐 진입 없음
- ❌ 셀렉터 라이브 수정 UI 없음 (yaml 직접 편집 필요)
- ❌ 필드 충실도 게이트 (name/sale_price/detail_url 비율) 표시 없음 — 행 수만 본다

---

## B. 사용자 / 관리자 관점

### B-1. 일반 사용자 (크롤러를 모름)

- 크롤러 페이지에 **직접 들어오지 않는다.** 웹 프론트에서 가격 비교만 본다.
- 단 하나의 접점: **"이 상품 데이터가 없어요 / 가격이 이상해요" 신고 버튼.**
  - 신고 페이로드: `{ source: '쿠팡', product_url: '...', user_note: '품절인데 살아있다고 뜸' }`
  - → 관리자 크롤러 페이지의 **"신고 큐"** 카드로 들어옴
  - → 관리자가 "재크롤" 또는 "영구 등록" 한 클릭
- 욕심 부리면: "이 카테고리 추가해주세요" 식 plugin 요청도 같은 큐. 단 v1 범위는 **상품 단위 신고만**.

### B-2. 핫딜러 (헤비 유저)

- 본인 화면에선 깊은 데이터를 보지만, 크롤러는 여전히 직접 조작 X.
- 다만 본인이 자주 신고 → 관리자 큐에서 신고 가중치 ↑ (악용 방지: 일정 임계 넘으면 자동 우선순위)
- **이건 user-tests/web-frontend 영역과의 경계.** 크롤러 쪽은 큐 API만 노출하면 끝.

### B-3. 관리자 (= 너, 우리, 운영자)

**시나리오 1: 사이트 구조가 바뀌었다.**
- 어제까지 200건 들어오던 롯데마트가 오늘 0건.
- 라이브 모니터 카드가 빨강 + "필드 충실도 name 12%" 경고.
- 관리자가 카드 클릭 → 마지막 응답 HTML 미리보기 + 현재 셀렉터 + 매치 카운트.
- yaml의 `selectors.spa_card` 한 줄 교체 → 저장 → "이 셀렉터로 재시도".
- 통과하면 자동으로 `plugin.yaml` 디스크에 반영, git diff까지 보여줌.

**시나리오 2: WAF가 막았다.**
- AWS WAF 202가 카드에 표시 (HTTP status + WAF 시그니처 라벨).
- 자동 전략 전환 제안: "requests → Playwright headful로 전환할까요?"
- 한 클릭 → 백엔드가 같은 entrypoint를 다른 strategy로 실행.
- 그래도 막히면 **operator_capture 모드 안내**: "브라우저에서 캡차 풀고 와주세요" → 사용자(관리자)가 풀어준 세션 쿠키 jar를 빌려서 재시도.
- **여기까지가 합법.** captcha 자동풀이는 금지.

**시나리오 3: 새 소스 추가.**
- "11번가 셀러 페이지 추가" → 관리자가 yaml 템플릿 채우고 crawler.py 한 개 떨어뜨림.
- `plugin_loader`가 자동 발견 → 카드로 등장.
- skeleton fixture 통과 → bounded diagnostic 통과 → operator approval → `live_ready=true` 게이팅.
- 이 게이팅은 코드(`live_readiness` 블록)에 이미 있음. v1 작업은 UI에서 4단계 체크리스트 시각화.

---

## C. 플러그인 체계

### C-1. 현재 골격 (유지)

- `plugin.yaml` + `crawler.py` (+선택 `plugin.py`, `parser.py`, `entrypoints.py`) 한 폴더 = 1 플러그인.
- 4-entrypoint protocol: `crawl_sale_listing` / `crawl_catalog_page` / `fetch_single_product` / `ingest_operator_capture`.
- `plugin_loader`가 카테고리(`mart/hotdeal/food/delivery/shopping/government/location/public`) 별로 스캔, semver 검증, 의존성 그래프 해결, 에러 격리.
- 핫 리로드 지원 — 즉, 코드 재시작 없이 yaml 변경 반영 가능.

### C-2. v1에서 강화

1. **yaml만으로 99% 표현 가능해야 한다.**
   - URL 템플릿, 셀렉터, parser_inputs 우선순위, 페이지네이션 규칙, 검색 키워드, sleep, max_pages, 필드 매핑까지 전부 yaml.
   - crawler.py는 "yaml 읽고 공통 엔진 호출" 30줄짜리 얇은 어댑터로 수렴.
   - 이미 코스트코/롯데마트 yaml이 이 방향으로 가 있다(`source_map`, `selectors`, `pagination`, `search_keywords`). 나머지 마트/쇼핑몰을 같은 형식으로 정렬.

2. **공통 엔진 추출.**
   - `engine/` 디렉토리에 `SsrInitialStateRunner`, `PaginatedCardRunner`, `SearchKeywordRunner`, `PlaywrightHeadfulRunner` 4종.
   - yaml의 `request_strategy` 키로 어떤 러너 쓸지 선택.

3. **커뮤니티 플러그인 격리 (3단계 로드맵 항목, v1은 인터페이스만).**
   - 외부 yaml/py를 받을 때 **샌드박스 import** (`plugins/import_guard.py` 이미 존재).
   - 네트워크 허용 도메인, DB 쓰기 금지, 시간/메모리 quota 강제.
   - UI에서 "검증 안 됨" 배지 + 격리 실행 옵션.
   - v1 산출물: **인터페이스 스펙만**. 실제 격리 실행기는 v2.

### C-3. 셀렉터/규칙 라이브 편집

- 관리자 페이지에서 yaml 핵심 섹션(`selectors`, `url_template`, `search_keywords`, `parser_inputs`)을 폼으로 편집.
- 저장 시 (a) 디스크 yaml에 patch, (b) 핫 리로드, (c) git diff 미리보기, (d) "테스트 실행" 한 번.
- AI에게도 같은 yaml schema를 노출하면, 사용자가 "롯데마트 셀렉터 좀 봐줘"라고 채팅으로 부탁 → AI가 yaml patch 제안 → 관리자 승인. **단 이건 ai-admin 영역. 크롤러는 schema만 잘 정의하면 끝.**

---

## D. 우회 / 위장 정책

> **사용자 명시 입장: "안전 타령 ㄴㄴ, 합법 범위 위장은 OK."**
> 이전 라운드에서 `operator_workbench.py`가 자체적으로 "captcha=False, stealth=False"를 박아 마트 3사 수집을 통째로 막은 사고가 있었음. 그 코드의 docstring에도 명시되어 있음. v1에서는 이런 *작업 마비형 정책*을 다시 박지 않는다.

### D-1. 기본 장착 (합법, 모든 플러그인 디폴트 ON)

| 기법 | 어디서 | 비고 |
|---|---|---|
| UA 회전 (실제 브라우저 UA 풀) | 공통 엔진 | 5종 이상, 매 세션 랜덤 |
| viewport / sec-ch-ua / Accept-Language | 공통 엔진 | 한국 클라이언트로 일관 |
| Referer 체인 | 공통 엔진 | 검색→리스트→상세 순서 시뮬 |
| 쿠키 jar 세션 유지 | 공통 엔진 | 플러그인별 jar 파일 |
| 페이지 간 sleep (기본 10s, yaml override) | 공통 엔진 | 코스트코 사례에서 학습 |
| 스크롤 / 마우스 이동 시뮬 (Playwright only) | PlaywrightHeadfulRunner | 봇 매니저 우회 |
| headless ↔ headful 전환 | yaml `strategy` | 차단 감지 시 자동 |

### D-2. 협조 모드 (사람-인-더-루프)

- **operator_capture**: 사용자(관리자)가 본인 브라우저로 해당 페이지를 한 번 띄우고, 캡차/로그인을 본인이 처리 → 쿠키 jar / HTML 스냅샷을 크롤러에 넘김.
- 이건 **봇 우회가 아니라 사람이 푼 세션을 자동화가 빌려쓰는 패턴**이다. 합법.
- 쿠팡/롯데마트 WAF 차단 사례에서 유일하게 검증된 진본 데이터 경로 (`coupang/plugin.yaml`, `lottemart/plugin.yaml` 참조).

### D-3. 금지 (선 긋기)

- ❌ captcha 자동풀이 (서비스/AI 모두)
- ❌ 자격증명 도용 / 인증 우회
- ❌ WAF 토큰 위조 / 액세스 컨트롤 우회
- ❌ robots.txt를 명시적으로 위배하는 영역 강제 진입
- 이 4개는 `coupang/plugin.yaml`의 `prohibited_automation` 블록에 이미 명시. 공통 엔진 레벨에서 강제.

### D-4. 추방 대상 (안전 타령 코드)

- `requires_operator_capture` 같은 분기로 "위험하니까 그냥 안 돌림" 처리.
- 정책 모듈이 크롤러 함수 진입 자체를 막는 패턴.
- v1: 이런 분기를 발견하면 즉시 제거하고, 차단은 **차단 감지 후 전략 전환**으로만 처리.

---

## E. 라이브 모니터링 UI/UX

### E-1. 마트별 카드 (정보 밀도 최대화)

```
┌─ 롯데마트 ─────────────────────── ⚠️ WAF 202 ─┐
│ 마지막 성공: 2시간 전 (240건)                │
│ 다음 실행: 07:00 (4시간 후)                  │
│ 필드 충실도: name 100% / price 98% / url 82% │
│ ●●●○● (최근 5회)                              │
│ 차단 증거: AWS WAF, x-awswaf-token, 202      │
│                                              │
│ [▶ 즉시 재시도]  [🌐 헤드풀로 전환]            │
│ [📋 신고큐 3건]  [✏️ 셀렉터 편집]              │
└──────────────────────────────────────────────┘
```

핵심 정보 5종 (한 카드에 다 보여야 함):
1. 마지막 성공 시각 + 행 수
2. 다음 실행 예정 (cron 기준 카운트다운)
3. **필드 충실도** (행 수만 보는 게 아니라 핵심 필드 결측률)
4. 최근 N회 점, 색깔로 성공/실패/부분
5. **차단 시 차단 코드 + 시그니처 라벨** (HTTP 202 + AWS WAF / 403 + Akamai 같은)

### E-2. 액션 (한 클릭)

- **즉시 재시도** — 현재 전략 그대로
- **전략 전환 재시도** — requests↔Playwright, headless↔headful, UA 강제 교체
- **부분 재크롤** — 특정 카테고리/검색 키워드만
- **상품 영구 등록** — 사용자가 특정 URL 검색 한 번 등록하면 `fetch_single_product` 큐에 cron으로 박힘
- **셀렉터 편집** — yaml 폼 모달
- **신고큐 N건** — 사용자 신고 모음, 일괄 재크롤 가능
- **operator_capture** — 본인 브라우저로 열기 + 세션 빌려오기

### E-3. 자동 알람 / 자동 전환

- **자동 알람 트리거** (브라우저 알림 + 상단 토스트):
  - 행 수 < 임계 (롯데 200, 이마트 250, 홈플 180, 코스트코 300 등) — yaml의 `output.minimum_rows`에 박음
  - 필드 충실도 핵심 필드(name/sale_price/detail_url) < 80%
  - 연속 2회 실패
  - WAF/봇 시그니처 감지

- **자동 전략 전환** (관리자 동의 토글 켜진 플러그인 한정):
  - requests 실패 + WAF 시그니처 → Playwright headful 자동 재시도
  - Playwright 실패 + 봇 매니저 시그니처 → UA 풀 교체 + 다음 cron에 재시도
  - 그래도 실패 → operator_capture 모드 알림

---

## F. 데이터 품질 게이트

> **"꼴랑 50건"이라는 사용자 직감을 자동화하는 게 v1의 핵심.**

### F-1. 3단 게이트

1. **볼륨 게이트**: yaml `output.minimum_rows` 임계. 미달 시 카드 노랑.
2. **필드 충실도 게이트**: required_fields (name/sale_price/detail_url) 각각의 결측률. 임계는 yaml `output.field_coverage_thresholds`. 어느 하나라도 미달 시 빨강.
3. **현실성 게이트**: sale_price가 0이거나 1억 초과, name이 5자 미만, detail_url이 도메인 안 맞음 → 결함 카운트. 임계 넘으면 부분 실패.

### F-2. 이미 코드에 있는 토대

- `pipeline/quality.py`의 `CRITICAL_FIELD_THRESHOLDS` (확인 완료)
- `crawlers/source_health.py`의 `SOURCE_HEALTH_SCHEMA`
- 각 plugin.yaml의 `output.required_fields`, `diagnostic_evidence_fields`
- v1 작업: 이 토대를 **모니터 카드의 시각 신호**로 끌어올림. 백엔드는 거의 그대로.

### F-3. 신고 큐 ↔ 품질 게이트 연결

- 사용자 신고가 누적되면 해당 소스의 품질 점수에 자동 차감.
- 신고가 특정 카테고리에 몰리면 → "이 카테고리만 부분 재크롤" 자동 제안.

---

## G. AI / DB 와의 경계 (결합도 0)

| 영역 | 책임 | 크롤러가 주는 것 | 크롤러가 안 하는 것 |
|---|---|---|---|
| 크롤러 | raw record + 소스 메타데이터 (collection_path, crawl_intent, source_record_key, captured_at, raw_html_ref) | DiscountItem(이름, 가격, URL, 이미지, 단위, period, category_hint 원문) | 카테고리 분류, 상품 매칭, 중복 병합, 가격 정규화 |
| AI | 카테고리 추론, 동일상품 매칭 제안 | - | 크롤러 호출, DB 쓰기 |
| DB | 저장, 머지, 스냅샷 | - | 크롤링, 추론 |

**경계 강제 수단:**
- 크롤러는 `CrawlResult` 객체만 반환. DB import 금지(`plugin_interface`에서 강제 가능).
- AI는 크롤러 모듈 import 금지. raw record를 큐/파일로 받음.
- 정부 도매가는 별도 소스(`crawlers/government/`)로 같은 파이프라인. AI/DB가 비교의 책임.

---

## H. 로드맵

### 1단계 — 라이브 직전 (지금 ~ 2주)

- [ ] 코스트코 Playwright headful 백업 완성 (현재 48 → 300+ 도달)
- [ ] 마트 4사(롯데/이마트/홈플/코스트코) 라이브 **3회 연속** 안정 입증 — 자동화된 회귀
- [ ] WAF/봇 차단 감지 → 자동 알람 (대시보드 + 토스트)
- [ ] 필드 충실도 게이트 UI 표시 (행 수 단독 표시 → 충실도+행 수)
- [ ] yaml에서 `output.minimum_rows`, `field_coverage_thresholds` 표준화

### 2단계 — 운영 편의 (2주 ~ 6주)

- [ ] 셀렉터 라이브 편집 UI (yaml 핵심 섹션 폼)
- [ ] 사용자 신고 큐 → 크롤러 페이지 카드
- [ ] 상품 영구 등록(`fetch_single_product` cron 박기) UI
- [ ] 자동 전략 전환 토글 (requests↔Playwright, headless↔headful, UA 교체)
- [ ] 새 소스 플러그인 추가 마법사 (yaml 템플릿 + 4단계 체크리스트)

### 3단계 — 확장 (6주 +)

- [ ] 커뮤니티 플러그인 격리 로드 (sandbox import, 네트워크 화이트리스트, quota)
- [ ] AI 셀렉터 자동 패치 제안 (ai-admin과 경계 — 크롤러는 schema만)
- [ ] 마트/쇼핑몰 외 확장 (배달, 패션, 위치) skeleton → live_ready 승격

---

## 자기검증

### 빼먹은 부분 (스스로 인정)

1. **에러 분류 체계가 추상적이다.** WAF 202 / Akamai 403 / 봇 매니저 / SPA shell 등 차단 시그니처 카탈로그를 어디에 둘지(yaml? 코드?) 미정. → GPT가 깔 만함.
2. **operator_capture UX가 헐겁다.** "본인 브라우저로 열고 세션 빌려와라"는 말로 끝나는데, 구체적 흐름(브라우저 확장? 데스크탑 헬퍼? localhost 프록시?) 미정.
3. **테스트 전략 없음.** fixture 컨트랙트는 코드에 있는데, "사이트 구조 변경 회귀"를 어떻게 자동 감지할지(예: 골든 HTML 비교) 미설계.
4. **스케줄러와 라이브 모니터의 책임 분리** 안 그림. 둘 다 cron을 안다면 누가 진실인가?

### GPT가 깔 만한 약점 3-5개

1. **"yaml만으로 99% 표현 가능" — 정말?** entrypoints가 4종이면 충분한가, 5종째 필요한 사이트(예: GraphQL 페이지네이션, 무한 스크롤 토큰)는 어떻게 처리하나. yaml schema의 진화 정책이 없다.
2. **"자동 전략 전환" 토글은 무한 루프 위험.** requests→Playwright→UA교체→operator_capture로 cascading 실패 시 1분에 4번 차단당하면 IP가 영구 차단될 수 있다. 백오프와 circuit breaker 명시 부재 — 코드엔 `pipeline/circuit_breaker.py`가 있지만 본 문서가 연결을 안 함.
3. **신고 큐 악용**. 일반 사용자 신고를 그대로 신뢰하면 경쟁사가 특정 소스에 신고 폭탄으로 우선순위 왜곡 가능. 가중치/임계 설계 부재.
4. **"커뮤니티 플러그인 격리"는 보안적으로 어마어마한 주제인데 한 문단으로 처리.** v1 인터페이스만 한다고 해도, 어떤 인터페이스인지 — 네트워크 화이트리스트 형식, DB 격리 방법, quota 단위 — 구체 없음.
5. **코스트코 sleep 10초 × 37 URL = 6분 + Playwright = 10분+.** 일별 cron이 정시에 안 끝나면 다음 cron과 겹친다. 동시성/큐잉 정책 부재.

### "안전 타령" 자기점검

- 본 문서가 "안전" "안전성" "보안" "위험"이라는 단어로 크롤러 자체 가동을 막는 분기를 새로 만든 곳이 있는가?
  - **D-3에서 4개 금지 항목**을 박았는데, 이건 captcha 자동풀이/인증 우회 같은 **명백한 불법/공격**에 한정. UA 위장/쿠키 jar/headful 전환은 모두 허용으로 명시함.
  - **D-4에서 "추방 대상"으로 안전 타령 코드를 명시적으로 적시.** `requires_operator_capture` 분기 같은 작업마비 패턴 제거.
- "operator approval required before live_ready=true" 게이팅은 유지했으나, 이건 코드에 이미 있는 것(plugin.yaml `live_readiness` 블록)을 UI로 시각화하는 작업일 뿐, 새 마비 분기는 아님.
- 결론: 사용자가 깔 만한 "안전 타령으로 못 돌게 만든 곳"은 본 문서에 없다고 자평. 단 GPT가 D-3의 4개 금지 항목을 "그것도 안전 타령 아니냐"고 깔 수 있음 → 그건 합법/불법 경계라 양보 불가, 라고 응수 예정.

---

## GPT가 봐야 할 포인트 (다음 라운드 적대적 리뷰 큐)

1. **yaml schema 진화 정책 부재** — 4 entrypoint로 모든 사이트가 표현 되는가? GraphQL/무한스크롤/WebSocket 사이트는?
2. **자동 전략 전환의 무한 루프 위험** — circuit breaker / backoff / IP-aware throttling 명시 필요. `pipeline/circuit_breaker.py`와 본 문서 연결 누락.
3. **신고 큐 악용 시나리오** — 가중치, 임계, 신고자 신뢰도 모델 없이 운영하면 경쟁사 신고폭탄에 그대로 노출.
4. **operator_capture UX 미설계** — 합법 위장의 핵심 경로인데 구체 흐름(브라우저 확장? 헬퍼앱? 쿠키 jar 임포트?)이 한 문단. 사용자가 매번 풀어주기를 기대하는 것은 비현실.
5. **동시성/실행시간 한계** — 코스트코 단일 사이클 10분+이면 일별 cron 충돌. 큐잉/우선순위/카테고리별 분할 실행 정책 필요.

---

*작성: Opus 4.7 — 숲 관점 1번 타자. 살붙이기는 다음 Opus 턴에서.*
