# DB-admin 영역 v1 초안 (Opus, Round-A)

> 라운드: A — 4영역(DB / 크롤러 / AI / 웹) 첫 기획 슬라이스
> 담당: DB 영역
> 작성자: Opus 4.7 (v1)
> 다음 단계: GPT-5.5 적대적 검토 → Opus 살붙임

---

## 0. TL;DR (핵심 요약, 30초 컷)

- WalletSavior DB의 책임은 **"마트별로 뒤죽박죽인 가격을 하나의 캐노니컬 상품 축으로 묶어, 도매가 기준선 위에 핫딜·상한·하한 가격대를 객관 수치로 얹는 것"**.
- 이미 상당 부분 구축돼 있음: `canonical_products` / `mart_sku_alias` / `price_observations` / `price_grade`(P10/P25/P50/P75 분위수) / `product_review_queue`(escalation) / `category_node`(adjacency list 4depth) / `oneshot_public_db.build_snapshot`(공개 read-only SQLite).
- 부족한 것: ① **도매가(정부 농축산물) 기준선 모델이 코드상 비어 있음** ② **키워드 자동완성/검색 의도 학습 테이블 부재** ③ **escalation 큐 UI는 있으나 "분류만 하면 매칭테이블 자동 등록" 루프가 명시되지 않음** ④ **핫딜 게시판 ↔ 캐노니컬 상품 결합 모델 없음** ⑤ **백업/스냅샷 비교/롤백 UX 미흡**.
- v1은 **숲**을 박는다: 도매가 기준선 테이블, 키워드 의도 로그, 게시판-상품 약결합 매칭, 핫딜 점수(0–100) 산정 모델을 **데이터 모델 차원**에서 제시.

---

## A. 현황 진단

### A-1. DB-admin이 지금 하고 있는 것 (코드 기준)

| 영역 | 현 상태 | 위치 |
|---|---|---|
| 캐노니컬 상품 모델 | ✅ `CanonicalProduct` (SHA1 PK, brand+name_core+pack_qty+pack_unit) | `storage/canonical_models.py:155` |
| 마트 SKU 별칭 | ✅ `MartSkuAlias` (UNIQUE(mart, mart_item_id)) | 동 파일:210 |
| 가격 관측 | ✅ `PriceObservation` (canonical_id+mart+observed_at 인덱스, raw_payload_hash 보존) | 동 파일:261 |
| 가격 등급 | ✅ `price_grade` (P10/P25/P50/P75, sample_size, sufficient flag) | `core/price_grading.py` |
| 카테고리 트리 | ✅ adjacency list 4depth, path 문자열, slug | `canonical_models.py:106` |
| escalation 큐 | ✅ `ProductReviewQueue` (raw_payload, suggested_canonical_id, ReviewReasonEnum) | 동:322 |
| 공개 스냅샷 | ✅ `oneshot_public_db.build_snapshot` (canonical+price_grade+category+alias → read-only SQLite) | `services/oneshot_public_db.py` |
| 관리자 UI 페이지 | ✅ Dashboard / Inbox / Products / Prices / Classification(categories+keywords 통합) / Analytics / Integrity / Community | `frontend/src/App.jsx` |
| 백업 서비스 | ✅ 코드 존재 (`services/backup.py`), UI 노출은 약함 | — |
| 게시판 DB | ⚠️ **web-api 쪽**에 있음 (`packages/web-api/backend/storage/board_models.py`) — db-admin과는 **물리적으로 분리** | — |

> **결합도 정리**: 상품 DB는 db-admin이, 게시판 DB는 web-api가 보유. db-admin은 게시판 모더레이션 화면만 가짐 (`CommunityModeration` 페이지). 두 DB는 **공유 키 없이 약결합** 상태 — 이게 v1 기획의 핵심 결합점 중 하나.

### A-2. 무엇이 부족한가

**일반인(소비자) 관점에서 비어 있는 것**
- "이 가격이 싼 건지 비싼 건지" 한 줄로 알려주는 **객관 기준선의 도매가 축이 없음**. 지금은 마트 누적 관측치 분위수(P10/P25/P50/P75)만 있음 → 마트들이 다 같이 비쌀 때 그 기준이 같이 비싸짐. **도매가 anchor가 빠짐**.
- 검색 자동완성·연관 키워드 테이블 없음 (`Keyword`/`ProductKeyword` 테이블은 있으나 *사용자 검색 로그* 기반 학습 모델 없음).
- 가격 추이 그래프용 **시계열 집계 캐시 테이블** 없음 — observations에서 매번 GROUP BY 하면 느려짐.

**관리자 관점에서 비어 있는 것**
- escalation 큐에서 "카테고리 지정 → 매칭테이블 자동 갱신" **루프가 명시적이지 않음**. `CategoryCorrection` 테이블이 따로 있고 운영 워크플로가 두 갈래로 보임.
- **빅데이터 누적 모니터** 부재: 마트별/카테고리별 행수, 매칭률, 최근 N일 가격 분포 히트맵을 한 화면으로 보여주는 페이지가 없음 (Analytics는 있으나 단편적).
- **백업/롤백/스냅샷 비교** UX 미흡: 백업 서비스 코드는 있는데 "어제 스냅샷과 오늘 스냅샷의 카테고리 트리 diff" 같은 화면 없음.
- 카테고리 트리 편집이 드래그앤드롭이 아닌 것으로 보임 (`ClassificationPage` 한 페이지에 카테고리+키워드 통합).

**구조 관점**
- 게시판 ↔ 상품 결합 모델이 없음 → 핫딜 게시글에 "이 상품의 적정가/핫딜선" 자동 표시 불가.
- 도매가 정기 갱신 파이프라인의 **착륙 테이블이 없음**.

### A-3. 다른 영역이 DB를 어떻게 쓰는지 (경계 지점)

| 영역 | DB에 쓰는 것 | DB에서 읽는 것 | 경계 |
|---|---|---|---|
| 크롤러 | `PriceObservation` upsert, `MartSkuAlias` 신규 생성, escalation 등록 | `canonical_id` 계산용 정규화 규칙(코드 공유) | **쓰기 API만 노출**, 카테고리 분류는 안 함 |
| AI | `ProductReviewQueue.suggested_canonical_id` 채움, 카테고리 추천 | 미해결 큐, raw_payload | **추천만 함**, 확정은 관리자/룰 |
| 웹(web-api) | 게시판 board_models 쓰기 | 공개 스냅샷 SQLite read-only | **쓰기 권한 없음**, 스냅샷 경로만 알면 됨 |
| 웹(frontend) | — | 공개 API(web-api 경유) | DB 직접 접근 없음 |

**핵심 원칙**: db-admin의 운영 DB는 **다른 영역이 직접 접근하지 않는다**. 공개 스냅샷(`public_snapshot.sqlite`)과 좁은 쓰기 API만이 경계.

---

## B. 궁극 목표 관점에서 DB가 책임져야 하는 것

### B-1. 가격 적정선 산정 데이터 모델 (3-layer anchor)

```
Layer 1 (객관 anchor)    : 도매가 (정부 농축산물 도매가)  ← 신규
Layer 2 (시장 anchor)    : 마트 누적 가격 분위수 (P10/P25/P50/P75)  ← 기존
Layer 3 (이벤트 anchor)  : 시즌·요일·연휴 보정  ← 신규(가벼운 룰셋부터)
```

**신규 제안 테이블**

```
wholesale_baseline
─────────────────────────────────────
  id              PK
  source          ENUM('KAMIS_금지', 'ATB_도매', '농수산_공판', ...)
  commodity_key   TEXT   -- 도매 품목 코드/이름 (예: "계란_특란_30개")
  observed_date   DATE
  unit_price_krw  INTEGER   -- 도매 단가
  unit_basis      ENUM(개/kg/L/...)
  region          TEXT NULL -- 권역 (전국 평균이면 NULL)
  raw_payload     JSON       -- 원천 보존

wholesale_to_canonical_link
─────────────────────────────────────
  canonical_id    FK
  commodity_key   FK
  conversion_factor REAL    -- "도매 1kg → 소매 700g팩" 같은 환산 계수
  confidence      ENUM(MANUAL/AI_SUGGESTED)
```

> **주의**: 코드 코멘트에 "KAMIS 도입 절대 금지"라고 박혀 있음 (`oneshot_public_db.py:19`). 도매가 소스는 **그 외 채널**(농수산물유통공사 공시·도매시장 공판가 등)로 잡고, source ENUM에 KAMIS는 의도적으로 두지 않는다.

**산식 (개념)**:
```
적정가 하한 = max(도매가 × 환산, 마트P10)
적정가 상한 = 마트P50
핫딜선     = 마트P10 또는 도매가환산 × 1.1 중 작은 값
바가지선   = 마트P75
```
실제 가중치는 카테고리별로 다름 → 카테고리 노드에 `pricing_profile_id` FK 추가하고 프로파일은 별도 테이블로.

### B-2. 카테고리 트리 — 양면성

| 일반인 면 | 핫딜러 면 |
|---|---|
| 1·2단계까지가 직관 (식료품 > 정육) | 3·4단계까지 깊게 (정육 > 한우 > 등심 > 1+등급) |
| `display_for_consumer=true` 노드만 노출 | 전체 노드 노출 |
| 인기순/계절 가중치 정렬 | 알파벳/depth 정렬 |

**추가 컬럼 제안** (CategoryNode):
- `display_for_consumer BOOLEAN DEFAULT true` — 일반 사용자 메뉴에 노출할지
- `popularity_score REAL` — 검색·클릭 로그 기반 인기 점수 (배치로 갱신)
- `seasonality_json` — 월별 인기/시즌성 패턴 (예: 수박 = 6~8월 가중)
- `pricing_profile_id` — B-1과 연결

### B-3. 키워드 자동완성 — 의도 학습

```
search_query_log
─────────────────────────────────────
  id, raw_query, normalized_query, hit_canonical_id NULL,
  hit_category_id NULL, no_result BOOLEAN, ts, session_hash

autocomplete_suggestion (집계 캐시)
─────────────────────────────────────
  prefix              TEXT   -- "계란"
  suggestion          TEXT   -- "계란 30개"
  rank                INTEGER
  source              ENUM(QUERY_LOG/PRODUCT_NAME/MART_ALIAS/MANUAL)
  category_hint_id    NULL
  updated_at
```

`MartSkuAlias`에 이미 마트별 표기가 누적되니, **마트 표기 + 검색 로그**를 같이 먹여 자동완성을 만든다. 매칭 테이블 학습 결과(자주 묶이는 alias 그룹)도 source `MART_ALIAS`로 흘려준다.

### B-4. 상품 정규화 — 이미 있음 + 보강 1가지

`CanonicalProduct.id = SHA1(brand|name_core|pack_qty|pack_unit)` 이미 강력함.
다만 **"같은 우유 1L가 마트마다 다른 이름"** 케이스에서 brand 표기 차이(서울우유 vs (주)서울우유)로 다른 SHA1이 나옴 → `brand_alias` 테이블 추가:

```
brand_alias
─────────────────────────────────────
  alias       TEXT PK   -- "(주)서울우유"
  canonical   TEXT      -- "서울우유"
  approved_by user_id NULL
```
canonical 계산 직전 brand에 alias 정규화 한 번 통과.

### B-5. 게시판 결합 — 약결합 매칭

게시판 DB는 web-api에 있음 → DB-admin은 **공통 키만 정의**하고 web-api가 매핑을 들고 있게 함.

```
hotdeal_post_link (web-api 쪽 테이블, DB-admin은 스키마 합의만)
─────────────────────────────────────
  post_id            FK(board)
  canonical_id       TEXT NULL    -- 상품 매칭 (NULL이면 미매칭)
  match_confidence   ENUM(MANUAL/AI/USER_CLAIM)
  matched_at
```

DB-admin은 **공개 스냅샷**과 함께 `canonical_lookup_token`(짧은 검색용 토큰: brand+name_core+pack) 인덱스를 제공 → 게시글 작성 시 자동 매칭 보조.

매칭되면 web-api가 게시글 옆에 db-admin 스냅샷의 `price_grade`를 붙여 "지금 가격이 P10 이하 = 핫딜 인증" 같은 배지 표시. **DB간 FK 없음, 토큰만 공유**.

---

## C. 사용자 관점 UI/UX (DB가 web에 제공할 데이터 모양)

### C-1. 가격 추이 그래프 — 시계열 응답 모양

```json
GET /public/products/{canonical_id}/trend?window=90d&granularity=day
{
  "canonical_id": "ab12...",
  "points": [
    {"date":"2026-01-01","mart":"E","price":3200,"on_sale":false},
    {"date":"2026-01-01","mart":"H","price":2980,"on_sale":true},
    ...
  ],
  "bands": {                       // 그래프 위에 깔 가격대 띠
    "wholesale_anchor": 1800,
    "p10": 2700, "p25": 2900, "p50": 3100, "p75": 3400,
    "current_min_today": 2980
  },
  "annotations": [
    {"date":"2026-01-15","label":"설 명절"}
  ]
}
```

→ 백엔드는 매 요청마다 GROUP BY 하지 않게 **`price_daily_agg`(canonical_id, mart, date, min/avg/max/n)** 캐시 테이블을 둔다.

### C-2. 핫딜 점수 0–100점

```
hotdeal_score = 0~100

성분(가중치는 카테고리 프로파일별):
  - 가격 위치    : (P50 - current) / (P50 - P10) * 60점  (P10 이하면 60점 만점)
  - 도매 anchor 대비 : current vs wholesale*환산*1.1 → 20점
  - 등급 충분성  : sample_size >= threshold → 10점 (아니면 깎임)
  - 이벤트 라벨  : event_labels 비어있지 않으면 +10점 (실제 행사가 붙은 흔적)
```

화면 표현: **"이거 핫딜 아닙니다"도 표시한다** — 30점 이하는 빨간 배지로 "정상가 또는 비쌈".

### C-3. 적대적 정보 노출 원칙

- 게시판 핫딜 게시글이 매칭되면 db의 score를 무조건 보여준다.
- **"마케팅 가격(원가 부풀린 할인)"** 의심 탐지: regular_price가 갑자기 올라간 직후 sale_price가 같은 비율로 내려간 경우 `suspicious_regular_jump` 플래그를 PriceObservation에 추가 → 화면에서 "표시할인율이 부풀려졌을 가능성" 안내.

---

## D. 관리자 관점 UI/UX (db-admin frontend 본진)

### D-1. 카테고리 트리 편집

| 기능 | 우선순위 |
|---|---|
| 드래그앤드롭 이동 (parent_id 자동 갱신, path 재계산) | P0 |
| 노드 일괄 선택 → 이동/병합 | P1 |
| `display_for_consumer` 토글 | P0 |
| 인기점수·시즌성 시각화 (히트맵) | P2 |
| 변경 사항 미리보기 → 적용/취소 (트랜잭션 commit/rollback) | P0 |

### D-2. escalation 큐 — "분류 한 번에 매칭테이블까지"

현재 코드상 `ProductReviewQueue.resolved_at` + `CategoryCorrection` 두 갈래 → **하나의 결심 액션**으로 통합:

```
관리자 액션: "이 raw_payload는 canonical X의 마트 Y SKU다, 카테고리는 Z다"
↓ 한 번의 트랜잭션:
   1) MartSkuAlias upsert (mart, mart_item_id, canonical_id)
   2) CanonicalProduct.category_path_internal_id 채움 (비어 있었으면)
   3) ProductReviewQueue.resolved_at + resolver_user_id
   4) AuditLog 기록
   5) (옵션) 비슷한 미해결 큐 항목을 AI 추천으로 일괄 제안
```

UI: 큐 행을 클릭 → 오른쪽 패널에 raw_payload + 추천 canonical 후보 3개 + 카테고리 후보 3개 + "확정" 버튼 하나.

### D-3. 빅데이터 누적 모니터 (Dashboard 본진 강화)

한 화면에:
- 마트별 최근 24h/7d/30d observations 행수 (sparkline)
- 카테고리별 매칭률 (canonical_id 부여된 alias 비율)
- 가격 분포 히트맵 (카테고리 × 가격대)
- escalation 큐 깊이 추이
- 도매가 anchor 최근 갱신일 (오래되면 빨간 경고)

### D-4. 백업 / 롤백 / 스냅샷 비교

| 기능 | 설명 |
|---|---|
| 일일 자동 백업 | 이미 있는 `services/backup.py` 활성화, UI에 목록·복원 버튼 |
| 스냅샷 diff | 어제 `public_snapshot.sqlite` vs 오늘 → 카테고리 추가/삭제/이동, canonical 신규/사라짐, price_grade 변동 큰 항목 표시 |
| 카테고리 트리 변경 롤백 | 트리 편집 세션 단위로 묶어 "이 세션의 변경 통째로 되돌리기" |
| 운영자 단독 모드 (dry-run) | 변경을 별도 working session에 쌓고 검토 후 commit |

### D-5. "잘못 만진 거 되돌리기" — Audit + Time Travel

- 이미 `AuditLog` 테이블 있음 (`models.py:847`) → 활용도 부족.
- 모든 운영자 mutation은 audit 행 + before/after JSON 남김.
- 관리자 UI에 "최근 내 작업 30건 → 행 단위 undo" 패널.

---

## E. 모듈 / 플러그인 관점

### E-1. API 경계 (도식)

```
크롤러 ──► [POST /ingest/observation]        ──► PriceObservation
크롤러 ──► [POST /ingest/alias]              ──► MartSkuAlias (자동/escalation)
AI     ──► [POST /review/{id}/suggest]      ──► ProductReviewQueue.suggested_*
운영자 ──► [POST /review/{id}/resolve]      ──► 통합 트랜잭션 (D-2)
web-api──► [GET  /public/snapshot.sqlite]   ──► 파일 다운로드 (또는 마운트)
web-api──► [GET  /public/categories/tree]   ──► 공개 트리 (display_for_consumer 필터)
web-api──► [GET  /public/products/{id}/trend]──► C-1 응답
```

**규칙**:
- 운영 DB(SQLAlchemy 모델)는 **외부 영역에 직접 노출 금지**. 무조건 API/스냅샷 경유.
- 공개 스냅샷은 **read-only**. 멱등 빌더로 매일 새로 생성. 빌드 중 파일은 `.tmp` → atomic rename.

### E-2. 게시판 DB ↔ 상품 DB 결합도 제로 유지

- 물리적 분리 유지 (이미 그렇게 돼 있음, 좋다).
- 공유 키는 **canonical_id 문자열 한 개**. FK 없음. 매칭 끊기면 NULL.
- 게시판 쪽이 canonical_id를 모를 때 → "토큰 검색" API로 db-admin에 물어봄. db-admin은 매칭 결과만 응답.

### E-3. 카테고리/키워드 셋 플러그인 교체

- 카테고리 트리는 `category_set_version` 컬럼을 도입 (CategoryNode에 `set_version TEXT`).
- 새 카테고리 셋을 import → 새 버전으로 적재 → 운영자가 "활성 버전 전환" 액션 → public snapshot 다음 빌드부터 적용.
- 키워드 셋도 동일 패턴 (`keyword_set_version`).
- → **운영 중에 카테고리 체계를 통째로 갈아도 트랜잭션 한 번**으로 끝남.

---

## F. "있으면 좋겠다" (자유 영역)

| 항목 | 데이터 모델 한 줄 |
|---|---|
| 사용자 즐겨찾기 카테고리·키워드 알림 | `user_watch (user_id, target_type, target_id, threshold)` — web-api 쪽 테이블, db-admin 스냅샷 키만 공유 |
| 마트별 정기 세일 사이클 학습 | `mart_sale_cycle (mart, category_id, weekday_pattern_json)` — observations 야간 배치로 갱신 |
| 도매가 자동 반영 | `wholesale_ingest_job` 큐, daily cron, 실패 시 escalation |
| 사용자가 직접 신고한 "이거 핫딜 아님" | `user_dispute (canonical_id, post_id, reason, ts)` — 운영자 대시보드에 카운트 |
| 시즌 캘린더 | 카테고리 노드의 `seasonality_json`을 화면에 띠로 시각화 |
| 위치 기반 (지역 가격차) | PriceObservation에 region_hint 컬럼 추가 (NULL 허용) — 1단계엔 안 함 |

---

## G. 단계적 로드맵

### 1단계 — 라이브 가동 직전 필수 (P0)

- [ ] **도매가 anchor 테이블 신설** (`wholesale_baseline`, `wholesale_to_canonical_link`)
- [ ] 도매가 수동 입력 UI (최소 카테고리 5개라도)
- [ ] **price_daily_agg 캐시** + 야간 빌드 잡
- [ ] escalation 큐 **통합 resolve 액션** (D-2)
- [ ] 카테고리 트리 드래그앤드롭 + display_for_consumer 토글
- [ ] 공개 스냅샷에 `wholesale_anchor` 컬럼·`hotdeal_score` 산출 컬럼 포함
- [ ] AuditLog 활성화 + 최근 작업 패널
- [ ] 일일 백업 cron + 복원 버튼

### 2단계 — 가동 직후 1개월 (P1)

- [ ] 키워드 자동완성 학습 (`search_query_log` → `autocomplete_suggestion`)
- [ ] 스냅샷 diff 뷰어
- [ ] 게시판 ↔ 상품 매칭 토큰 API
- [ ] suspicious_regular_jump 플래그
- [ ] 빅데이터 모니터 대시보드 강화
- [ ] brand_alias 정규화
- [ ] 카테고리 set_version 도입

### 3단계 — 이후 (P2+)

- [ ] 마트 세일 사이클 학습
- [ ] 사용자 watch 알림 연계
- [ ] 시즌성 가중 핫딜 점수
- [ ] 지역 가격차 (region_hint)
- [ ] 카테고리·키워드 플러그인 마켓플레이스 (조직 내부용)

---

## Z. 자기검증

### Z-1. 내가 빼먹은 것 (자수)

1. **인증·권한 모델** — 운영자 역할 분리(슈퍼/리뷰어/조회만)를 거의 안 다룸. `UserRole` enum이 있긴 함.
2. **성능 추정치** — observations가 수천만 행 가면 분위수 계산이 무거워짐. 파티셔닝/롤업 전략 미언급.
3. **공개 API 인증** — web-api가 db-admin의 좁은 API를 호출할 때 토큰/서명 정책 미언급.
4. **i18n** — 카테고리명이 한국어 전용. 단기적으론 무시 가능.
5. **테스트 데이터 시드** — `seed.py`/`canonical_seed.py`는 있지만 v1 변경분 대응 시드 갱신 계획 없음.
6. **삭제 정책** — soft delete vs hard delete가 일관성 없음.

### Z-2. 적대적 검토자가 가장 먼저 깔만한 약점

1. **"도매가 anchor 어디서 수급?"** — 코드에 KAMIS 금지가 박혀 있는데 대체 소스 구체화 안 됨. → 다음 라운드에서 소스 후보(농수산물유통공사 OPEN API, aT 도매시장 공판가 등) 구체 명시 필요.
2. **"핫딜 점수 산식이 자의적"** — 60/20/10/10 가중치 근거 없음. 카테고리별 보정 필요한데 그 보정 학습 데이터를 어떻게 만들지 미정.
3. **"escalation 통합 resolve = 트랜잭션 폭탄"** — 한 액션이 5개 테이블을 건드리면 실패 시 롤백 시나리오·동시성(같은 큐 항목을 두 운영자가 동시에 처리)·옵티미스틱 락 전략 부재.
4. **"공개 스냅샷 sqlite 파일 크기"** — observations 누적분이 그대로 들어가면 수백 MB. 분위수만 넣고 raw는 빼는 게 맞는지, 핫딜 그래프용 daily_agg는 얼마나 자르는지 미정.
5. **"게시판 약결합이 진짜 약결합이냐"** — canonical_id 토큰을 공유하는 순간, db-admin의 캐노니컬 정책 변경(SHA1 입력 컴포넌트 변경 등)이 web-api 매칭을 깨뜨림. **id 안정성 계약(immutable 보장)** 명시 필요.

### Z-3. "일반인 가장 쉽고 핫딜러 가장 깊은" 충족 여부

| 면 | 충족? | 메모 |
|---|---|---|
| 일반인 — 한 줄 답("싸/적정/비쌈") | ✅ hotdeal_score 0–100 + 가격대 띠로 시각화 |
| 일반인 — 검색이 잘 됨 | ⚠️ 자동완성 학습은 2단계에 두었음 — 1단계엔 마트 alias 기반 정적 자동완성으로 메꿔야 함 |
| 일반인 — 핫딜인지 사기인지 구분 | ✅ suspicious 플래그 + adversarial 노출 원칙 |
| 핫딜러 — 깊은 필터/추이 | ✅ price_daily_agg + 마트별 분리 + event_labels 노출 |
| 핫딜러 — 도매 anchor까지 본다 | ✅ wholesale_baseline (1단계 P0) |
| 커뮤니티 검증 | ⚠️ 약결합으로 가능은 하나, 2단계로 미룬 매칭 토큰 API가 1단계 가동에 늦지 않게 들어가야 함 — **재검토 포인트** |

---

## ★ 다음 단계(GPT 적대적 검토자)가 봐야 할 포인트 5개

1. **도매가 anchor 소스 구체화** — KAMIS 금지 제약 하에서 어디서, 어떤 빈도로, 어떤 라이선스로 가져올 것인가. v1은 테이블 모양만 박았고 소스가 비어 있음.
2. **canonical_id 안정성 계약** — SHA1 입력이 바뀌면 모든 매칭이 깨짐. brand_alias 정규화 도입 시점에 이미 깨질 수 있음. 마이그레이션 전략 필요.
3. **escalation resolve 트랜잭션 + 동시성** — 5테이블 단일 트랜잭션의 실패/락/동시 처리 시나리오.
4. **공개 스냅샷 파일 크기·갱신 주기 SLA** — 매일 빌드인지, observations 어디까지 자르는지, 빌드 시간이 길어지면 어떻게 atomic rename.
5. **1단계 P0에 매칭 토큰 API를 넣을지 말지** — 게시판 결합이 가동 직전부터 필요하다면 2단계가 아니라 1단계여야 함. 우선순위 재판정.

---

_v1 끝. v2(적대적 검토)에서 갈리고, v3(살붙임)에서 단단해질 것._
