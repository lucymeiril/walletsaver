# ARCHITECTURE.md — 시스템 아키텍처 & 데이터 흐름

> **이 문서의 목적**: 모듈 간 의존성, 데이터 파이프라인, DB 스키마, API 설계를 한눈에 파악.
> AI가 "이 코드를 어디에 넣어야 하나?" "이 데이터가 어떻게 흘러가나?" 질문에 답할 수 있도록.

---

## 1. 모듈 의존성 그래프

```
┌─────────────────────────────────────────────────────────────────┐
│                         container.py                             │
│        (유일한 조립 지점 — concrete class를 여기서만 import)       │
└──────┬──────┬──────┬──────┬──────┬──────┬──────┬───────────────┘
       │      │      │      │      │      │      │
       ▼      ▼      ▼      ▼      ▼      ▼      ▼
   engine/ crawlers/ storage/  api/  scheduler/  utils/  frontend-react/
       │      │        │       │       │
       │      │        │       │       │
       ▼      ▼        ▼       ▼       ▼
    ┌─────────────────────────────────────┐
    │              core/                   │
    │  contracts/ models.py events.py     │
    │  exceptions.py categories.py        │
    │  statistics.py verification.py      │
    │  recipe.py                          │
    └─────────────────────────────────────┘
```

### 의존 규칙

```
core/          → (없음. 최하위 모듈)
engine/        → core/ 만
crawlers/      → core/ 만
storage/       → core/ 만
api/           → core/ 만
scheduler/     → core/ 만
utils/         → (없음. 독립 유틸)
container.py   → 모든 모듈 (유일한 예외)
config.py      → container.py에서만 import
main.py        → container.py만 import
```

### 금지 의존 (절대 안 됨)

```
crawlers/ → engine/      ✗ (크롤러는 전략 실행기를 몰라야 함)
engine/   → crawlers/    ✗ (엔진은 특정 크롤러를 몰라야 함)
engine/   → storage/     ✗ (엔진은 저장소를 몰라야 함)
crawlers/ → storage/     ✗ (크롤러는 저장을 몰라야 함)
api/      → engine/      ✗ (API는 contracts로만 소통)
core/     → (아무것도)    ✗ (core는 순수 정의만)
```

---

## 2. 데이터 파이프라인 흐름

### 2.1 크롤링 파이프라인 (수집 → 저장)

```
[대상 사이트]
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  1. Crawler Plugin (crawlers/{그룹}/{사이트}/crawler.py)  │
│     - setup()     → 초기화                                │
│     - crawl()     → raw HTML/JSON 획득                    │
│     - parse()     → 구조화된 dict 리스트                    │
│     - validate()  → 유효 데이터 필터링                      │
│     - teardown()  → 정리                                  │
└──────────┬───────────────────────────────────────────────┘
           │ CrawlResult (status, items, raw_data, errors)
           ▼
┌──────────────────────────────────────────────────────────┐
│  2. Strategy Executor (engine/executor.py)                │
│     - 5-Strategy Cascade:                                │
│       requests → cloudscraper → selenium →                │
│       undetected-chromedriver → playwright                │
│     - AntiDetect: UA rotation, proxy, delay              │
│     - EventBus publish: crawl.started/completed/failed   │
└──────────┬───────────────────────────────────────────────┘
           │ CrawlResult
           ▼
┌──────────────────────────────────────────────────────────┐
│  3. Diagnostics Engine (engine/diagnostics.py)            │
│     (실패 시에만 작동)                                     │
│     - 에러 타입 분류 (11종)                                │
│     - 심각도 판정                                         │
│     - DiagnosisReport 생성                                │
└──────────┬───────────────────────────────────────────────┘
           │ DiagnosisReport (optional)
           ▼
┌──────────────────────────────────────────────────────────┐
│  4. Data Transform                                        │
│     - DiscountItem → .to_product_price() → ProductPrice  │
│     - HotdealPost → (별도 저장, 평균에 불포함)              │
│     - 카테고리 매칭 (CategoryTree)                         │
│     - 속성 태그 부여 (ProductAttribute)                    │
└──────────┬───────────────────────────────────────────────┘
           │ ProductPrice / HotdealPost
           ▼
┌──────────────────────────────────────────────────────────┐
│  5. Storage (storage/)                                    │
│     - StorageContract.save_collected_data()               │
│     - StorageContract.save_crawl_log()                   │
│     - FileStorageContract.save_image()                   │
│     - 테이블 분리: baseline / discount / hotdeal          │
└──────────────────────────────────────────────────────────┘
```

### 2.2 가격 분석 파이프라인 (조회 → 판정)

```
[사용자 요청: "삼겹살 지금 싼가요?"]
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  1. API (api/)                                            │
│     GET /api/prices/{product}                             │
│     - StorageContract.get_collected_data()                │
└──────────┬───────────────────────────────────────────────┘
           │ list[ProductPrice]
           ▼
┌──────────────────────────────────────────────────────────┐
│  2. Statistics Engine (core/statistics.py)                │
│     - IQR 이상치 제거 (remove_outliers_iqr)              │
│     - 기본 통계 산출 (compute_stats → PriceStats)         │
│     - 이동평균 (SMA 7/30일, EMA 7일)                     │
│     - 계절성 비교 (전년 동기 대비)                         │
└──────────┬───────────────────────────────────────────────┘
           │ PriceStats + MovingAverage
           ▼
┌──────────────────────────────────────────────────────────┐
│  3. 등급 판정 (determine_tier)                            │
│     - ratio = 현재가 / 평균가                              │
│     - ≤70%  → "ultra"  🔥 역대급 기회!                    │
│     - ≤85%  → "great"  💙 좋은 가격                       │
│     - ≤105% → "good"   ✅ 지금 사도 괜찮아요               │
│     - >105% → "wait"   ⏳ 조금 기다려보세요                │
└──────────┬───────────────────────────────────────────────┘
           │ PriceTier
           ▼
┌──────────────────────────────────────────────────────────┐
│  4. Frontend (frontend-react/)                            │
│     - 가격 차트 (Recharts)                                │
│     - 등급 뱃지                                           │
│     - 할인 이력 리스트                                     │
│     - "집에서 해먹으면?" 레시피 비용 비교                    │
└──────────────────────────────────────────────────────────┘
```

### 2.3 커뮤니티 검증 파이프라인

```
[유저 제보: "삼겹살 9,900원에 삼!"]
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  verification.py → verify_community_price()              │
│  - <20% of avg → SUSPICIOUS_LOW (등록 차단)              │
│  - 20~70% → GREAT_DEAL (🔥 진짜 핫딜)                   │
│  - 70~120% → VERIFIED (✅ 검증됨)                        │
│  - >120% → SUSPICIOUS_HIGH (🚨 바이럴 의심)              │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 이벤트 버스 (EventBus) 토픽

모듈 간 느슨한 결합을 위한 비동기 pub/sub 시스템:

| 이벤트 | 발행자 | 구독자 (예정) | 페이로드 |
|--------|--------|--------------|----------|
| `crawl.started` | executor | scheduler, api(dashboard) | `{url, force_strategy}` |
| `crawl.completed` | executor | storage, api | `{status, strategy_used, url}` |
| `crawl.failed` | executor | diagnostics, api | `{url, errors_count, error_types}` |
| `crawl.progress` | crawler | api(realtime) | `{crawler_name, progress_pct}` |
| `strategy.switched` | executor | diagnostics | `{from_strategy, to_strategy, url}` |
| `strategy.failed` | executor | diagnostics | `{strategy, error_type, error_msg}` |
| `data.saved` | storage | api(refresh) | `{data_type, items_count}` |
| `job.scheduled` | scheduler | api | `{job_id, crawler_name, cron}` |
| `job.removed` | scheduler | api | `{job_id}` |
| `diagnosis.generated` | diagnostics | api(alert) | `{crawler_name, error_type}` |

---

## 4. DB 스키마 설계 (PostgreSQL)

### 4.1 핵심 원칙: 테이블 분리로 "가격 오염" 방지

```
baseline_prices      ← 마트4사+쿠팡 수집가 ONLY → 분위수/평균/중간값 산출 기준
discount_history     ← 마트 전단 할인가 → "이 할인이 진짜 싼가?" 판단 기준
hotdeal_prices       ← 핫딜 커뮤니티 → 참고만, 절대 평균에 불포함
crawl_logs           ← 크롤링 실행 이력 + 진단 리포트
```

### 4.2 테이블 상세

```sql
-- 기준 가격 (마트4사+쿠팡 수집가만)
CREATE TABLE baseline_prices (
    id              SERIAL PRIMARY KEY,
    product_name    VARCHAR(200) NOT NULL,      -- 표준화된 품목명
    category_path   VARCHAR(500),               -- "축산물 > 돼지고기 > 삼겹살"
    category_id     INTEGER REFERENCES categories(id),
    store           VARCHAR(100),               -- "이마트", "코스트코", "쿠팡"
    source          VARCHAR(50) NOT NULL,        -- DataSource enum
    price           INTEGER NOT NULL,            -- 원
    unit            VARCHAR(50),                 -- "1kg", "100g"
    recorded_date   TIMESTAMP NOT NULL,
    source_url      TEXT,
    raw_text        TEXT,                        -- 원본 텍스트 (검증용)
    crawled_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    
    -- 속성 태그 (JSON)
    attributes      JSONB DEFAULT '{}',          -- {"storage":"냉장","origin":"국산","grade":"1등급"}
    
    INDEX idx_baseline_product (product_name, recorded_date),
    INDEX idx_baseline_category (category_id),
    INDEX idx_baseline_source (source, recorded_date)
);

-- 할인 이력
CREATE TABLE discount_history (
    id              SERIAL PRIMARY KEY,
    product_name    VARCHAR(200) NOT NULL,
    category_path   VARCHAR(500),
    category_id     INTEGER REFERENCES categories(id),
    store           VARCHAR(100) NOT NULL,
    original_price  INTEGER,                     -- 정가
    sale_price      INTEGER NOT NULL,            -- 할인가
    discount_pct    DECIMAL(5,2),                -- 할인율 (%)
    unit            VARCHAR(50),
    event_name      VARCHAR(200),                -- "1+1", "반값", "주간특가"
    valid_from      TIMESTAMP,
    valid_until     TIMESTAMP,
    image_url       TEXT,
    detail_url      TEXT,
    raw_text        TEXT,
    attributes      JSONB DEFAULT '{}',
    crawled_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_discount_product (product_name, crawled_at),
    INDEX idx_discount_store (store, crawled_at),
    INDEX idx_discount_date_range (valid_from, valid_until)
);

-- 핫딜 게시판 (평균에 불포함, 참고 전용)
CREATE TABLE hotdeal_prices (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    source_community VARCHAR(100),               -- "알구몬", "뽐뿌", "어미새"
    price           INTEGER,
    original_price  INTEGER,
    category        VARCHAR(200),
    matched_product VARCHAR(200),                -- DB 매칭된 표준 품목명
    price_vs_avg    DECIMAL(5,3),                -- 평균 대비 비율 (0.7 = 30% 저렴)
    crawled_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_hotdeal_community (source_community, crawled_at),
    INDEX idx_hotdeal_matched (matched_product)
);

-- 카테고리 계층
CREATE TABLE categories (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    parent_id       INTEGER REFERENCES categories(id),
    depth           INTEGER DEFAULT 0,
    path            VARCHAR(500),                -- "축산물 > 돼지고기 > 삼겹살"
    applicable_attrs TEXT[],                     -- {"storage","origin","grade","cert"}
    
    UNIQUE(name, parent_id)
);

-- 크롤링 실행 로그
CREATE TABLE crawl_logs (
    id              SERIAL PRIMARY KEY,
    crawler_name    VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL,        -- "success", "failed", "partial"
    items_count     INTEGER DEFAULT 0,
    strategy_used   VARCHAR(50),
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    duration_secs   DECIMAL(10,3),
    error_msg       TEXT,
    diagnosis       JSONB,                       -- DiagnosisReport JSON
    created_at      TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_crawl_log_crawler (crawler_name, started_at),
    INDEX idx_crawl_log_status (status)
);

-- 이미지 메타데이터
CREATE TABLE images (
    id              SERIAL PRIMARY KEY,
    original_url    TEXT,
    file_path       VARCHAR(500) NOT NULL,
    thumbnail_path  VARCHAR(500),
    file_size       INTEGER,
    mime_type       VARCHAR(50),
    width           INTEGER,
    height          INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### 4.3 Alembic 마이그레이션

```
storage/
├── alembic/
│   ├── env.py
│   ├── versions/
│   │   ├── 001_initial_schema.py
│   │   └── ...
│   └── alembic.ini
```

---

## 5. API 엔드포인트 설계 (FastAPI)

### 5.1 가격 관련

```
GET    /api/prices/{product_name}              # 품목별 가격 조회 + 통계
GET    /api/prices/{product_name}/history       # 가격 이력 (차트용)
GET    /api/prices/{product_name}/tier          # 현재 가격 등급 판정
GET    /api/prices/compare?items=삼겹살,양파     # 복수 품목 비교
```

### 5.2 할인 관련

```
GET    /api/discounts                           # 현재 진행중인 할인 목록
GET    /api/discounts?store=이마트              # 매장별 필터
GET    /api/discounts?category=축산물           # 카테고리별 필터
GET    /api/discounts/best                      # 역대급/좋은가격 할인 TOP
```

### 5.3 핫딜 관련

```
GET    /api/hotdeals                            # 핫딜 목록
GET    /api/hotdeals?community=알구몬           # 커뮤니티별 필터
POST   /api/hotdeals/verify                     # 커뮤니티 가격 검증
```

### 5.4 레시피 관련

```
GET    /api/recipes                             # 레시피 목록
GET    /api/recipes/{recipe_name}               # 레시피 상세 + 현재 재료비
GET    /api/recipes/{recipe_name}/savings       # 절약 금액 계산
```

### 5.5 크롤러 관리 (대시보드용)

```
GET    /api/crawlers                            # 등록된 크롤러 목록
GET    /api/crawlers/{name}/status              # 크롤러 상태
POST   /api/crawlers/{name}/run                 # 수동 크롤링 실행
GET    /api/crawlers/logs                       # 크롤링 로그
GET    /api/crawlers/logs/{id}/diagnosis        # 진단 리포트
```

### 5.6 스케줄러

```
GET    /api/scheduler/jobs                      # 스케줄된 작업 목록
POST   /api/scheduler/jobs                      # 새 작업 등록
DELETE /api/scheduler/jobs/{job_id}             # 작업 삭제
PATCH  /api/scheduler/jobs/{job_id}/pause       # 일시 정지
PATCH  /api/scheduler/jobs/{job_id}/resume      # 재개
```

### 5.7 카테고리

```
GET    /api/categories                          # 전체 카테고리 트리
GET    /api/categories/{id}/products            # 카테고리별 품목
```

### 5.8 WebSocket (실시간 대시보드)

```
WS     /ws/dashboard                            # 크롤링 진행상황 실시간 스트림
```

---

## 6. 프론트엔드 페이지 구성

```
/                       → 홈 (오늘의 할인 요약, 가격 등급 TOP)
/prices                 → 가격 비교 (품목 검색 → 차트 + 등급)
/prices/{product}       → 품목 상세 (이력, 통계, 추천)
/discounts              → 마트 할인 모아보기
/hotdeals               → 핫딜 게시판 모아보기
/recipes                → "집에서 해먹으면?" 레시피 비용 비교
/recipes/{name}         → 레시피 상세
/dashboard              → 크롤러 관리 대시보드 (관리자)
```

---

## 7. 5-Strategy Cascade 상세

```
Difficulty 1: RequestsStrategy
    └─ 순수 HTTP (가장 빠르고 가벼움)
    └─ 실패 조건: JS 렌더링 필요, Cloudflare 차단

Difficulty 2: CloudscraperStrategy  
    └─ Cloudflare UAM 자동 우회
    └─ 실패 조건: 고급 JS Challenge, 브라우저 필요

Difficulty 3: SeleniumStrategy
    └─ 실제 Chrome + selenium-stealth
    └─ 실패 조건: 고급 봇 탐지 (Incapsula 등)

Difficulty 4: UndetectedStrategy
    └─ undetected-chromedriver (패치된 Chrome)
    └─ 실패 조건: 최신 봇 탐지 업데이트

Difficulty 5: PlaywrightStrategy
    └─ Playwright + stealth (최종 수단)
    └─ 가장 무겁지만 가장 강력
```

---

## 8. 에러 타입 분류 체계

```
ErrorType (11종)
├── HTTP_ERROR          (심각도 4) — 4xx/5xx 응답
├── CAPTCHA_DETECTED    (심각도 9) — CAPTCHA 감지
├── IP_BANNED           (심각도 10) — IP 차단 (최고 심각)
├── JS_CHALLENGE        (심각도 7) — Cloudflare 등 JS 챌린지
├── DOM_CHANGED         (심각도 5) — CSS 셀렉터 불일치
├── TIMEOUT             (심각도 3) — 요청 시간 초과
├── LOGIN_REQUIRED      (심각도 6) — 인증 필요
├── EMPTY_RESPONSE      (심각도 3) — 빈 응답
├── PARSE_ERROR         (심각도 2) — 파싱 오류
├── NETWORK_ERROR       (심각도 2) — 네트워크 오류
└── UNKNOWN             (심각도 1) — 분류 불가
```

---

## 9. 데이터 소스 신뢰도 계층

```
 신뢰도 HIGH ──────────────────────────── LOW
 
 ┌────────────┐  ┌──────────────┐  ┌───────────┐
 │ GOVERNMENT │  │ MART_REGULAR │  │ MART_DISC │
 │ (공공 통계) │  │ (마트4사+쿠팡) │  │ (전단할인) │
 │            │  │              │  │           │
 │            │  │              │  │           │
 │ → baseline │  │ → baseline   │  │→ discount │
 │   평균에    │  │   평균에     │  │  별도저장  │
 │   포함     │  │   포함       │  │           │
 └────────────┘  └──────────────┘  └───────────┘
 
 ┌────────────┐  ┌──────────────┐
 │ HOTDEAL    │  │ DELIVERY     │
 │ (커뮤니티) │  │ (배달앱)     │
 │            │  │              │
 │ → 참고만   │  │ → 외식 참고  │
 │   평균에   │  │              │
 │   불포함   │  │              │
 └────────────┘  └──────────────┘
```
