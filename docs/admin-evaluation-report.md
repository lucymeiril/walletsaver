# WalletSavior 관리 도구 기술 실사 보고서

**작성 일자**: 2025년  
**범위**: `packages/crawler-admin/`, `packages/db-admin/`, `packages/shared/`  
**목적**: 인수 후 운영·유지보수 관점의 기술 평가

---

## 목차

1. [크롤러 관리 도구 평가](#1-크롤러-관리-도구-평가)
2. [DB 관리 도구 평가](#2-db-관리-도구-평가)
3. [크롤러 품질 평가](#3-크롤러-품질-평가)
4. [데이터 파이프라인 평가](#4-데이터-파이프라인-평가)
5. [보안 평가](#5-보안-평가)
6. [운영 편의성](#6-운영-편의성)
7. [구체적 개선 제안](#7-구체적-개선-제안)

---

## 1. 크롤러 관리 도구 평가

### 1.1 아키텍처 개요

| 계층 | 기술 스택 | 주요 파일 |
|------|-----------|-----------|
| **프런트엔드** | React 19 + Vite 8 + Zustand 5 + Recharts 3 | `crawler-admin/frontend/src/` |
| **백엔드 API** | FastAPI + Uvicorn (포트 8000) | `crawler-admin/backend/api/` |
| **엔진** | Multi-strategy cascade executor | `crawler-admin/backend/engine/` |
| **스케줄러** | APScheduler BackgroundScheduler | `crawler-admin/backend/scheduler/` |
| **플러그인** | YAML 기반 동적 로드 + Kahn's 토폴로지 정렬 | `crawler-admin/backend/plugins/` |

### 1.2 프런트엔드 UI 평가

**페이지 구성** (`crawler-admin/frontend/src/App.jsx`):

| 경로 | 페이지 | 기능 | 완성도 |
|------|--------|------|--------|
| `/` | Dashboard | 4개 통계 카드, 상태 파이차트, 에러 추이 라인차트, 최근 활동 테이블 | ✅ 양호 |
| `/crawlers` | Crawlers | 카테고리 필터(5종), 수동 실행, 상태 토글, 성공률/실행 횟수 표시 | ⚠️ 부분 구현 |
| `/data-review` | DataReview | 대기/승인/거부 탭, 스키마 프리뷰, 품질 지표, 메모 기능 | ✅ 우수 |
| `/plugins` | Plugins | 토글 활성화/비활성화, YAML 설정 뷰어 | ⚠️ 기본 수준 |
| `/logs` | Logs | 크롤러명/상태 필터, 8건/페이지 페이지네이션, 상세 에러 확장 | ✅ 양호 |
| `/schedule` | Schedule | 크론식 편집, 사람이 읽을 수 있는 미리보기, 활성화/비활성화 토글 | ⚠️ 부분 구현 |

**UI/UX 강점**:
- 다크 글래스모피즘 테마 + CSS 토큰 기반 디자인 시스템 (`styles/tokens.css`)
- Zustand 상태 관리로 불필요한 prop drilling 없음 (`stores/adminStore.js`)
- 반응형 사이드바 (768px 브레이크포인트, 모바일 햄버거 메뉴)
- Lucide React 아이콘 + Noto Sans KR 한국어 지원

**UI/UX 결함**:

| 문제 | 위치 | 심각도 |
|------|------|--------|
| "크롤러 추가" 버튼에 onClick 핸들러 없음 | `Crawlers.jsx:62` | 중 |
| "설정" 버튼 미연결 | `Crawlers.jsx:146-149` | 중 |
| 스케줄의 "수동 실행" 미구현 | `Schedule.jsx:112-114` | 중 |
| 크론식 유효성 검증 없음 | `Schedule.jsx` 편집 모달 | 중 |
| 수동 실행 시 확인 대화상자 없음 | `Crawlers.jsx:36-45` | 중 |
| API 실패 시 목업 데이터로 무음 전환 (사용자에게 알림 없음) | `adminStore.js:24-35` | 높 |
| Dashboard 외 페이지에 로딩 표시 없음 | 각 페이지 | 중 |

### 1.3 백엔드 API 평가

**엔드포인트 목록** (`crawler-admin/backend/api/routes/`):

| 메서드 | 경로 | 파일 | 기능 |
|--------|------|------|------|
| GET | `/health` | `app.py:35` | 헬스체크 |
| GET | `/api/crawlers` | `crawlers.py:24-28` | 크롤러 목록 |
| GET | `/api/crawlers/{id}/status` | `crawlers.py:31-44` | 크롤러 상태 조회 |
| POST | `/api/crawlers/{id}/run` | `crawlers.py:46-59` | 수동 실행 |
| GET | `/api/schedules` | `schedules.py` | 스케줄 목록 |
| POST | `/api/schedules` | `schedules.py` | 스케줄 생성 |
| PUT | `/api/schedules/{name}` | `schedules.py` | 스케줄 수정 |
| DELETE | `/api/schedules/{name}` | `schedules.py` | 스케줄 삭제 |
| GET | `/api/logs` | `logs.py:23-37` | 실행 로그 조회 |
| GET | `/api/ingestions` | `ingestion.py:29` | 인제스천 목록 (DB-Admin 프록시) |
| GET | `/api/ingestions/{id}` | `ingestion.py` | 인제스천 상세 (프록시) |
| POST | `/api/ingestions/{id}/crawler-review` | `ingestion.py` | 크롤러 리뷰 제출 (프록시) |

**에러 핸들링**:
- 크롤러 미발견 시 `HTTPException(404)` 반환 — ✅ 적절
- 인제스천 프록시에서 `httpx.AsyncClient` + 15초 타임아웃 + `HTTPException(502)` — ✅ 양호
- 로그 필터의 쿼리 파라미터 (`job_id`, `status`) 미검증 — ⚠️ 개선 필요

### 1.4 엔진 아키텍처 평가

**Multi-Strategy Cascade** (`engine/executor.py`, 248줄):

```
요청 → StrategyExecutor.execute()
  → [Strategy 1: requests (difficulty=1)] — 가장 빠름
    → 실패 시 [Strategy 2: cloudscraper (difficulty=2)] — JS 챌린지 우회
      → 실패 시 [Strategy 3: Playwright (difficulty=4)] — 완전 브라우저
        → 모두 실패 시 DiagnosticsEngine.analyze() → DiagnosisReport 생성
```

**강점**:
- 전략별 difficulty 순 자동 정렬 (executor.py:62)
- 각 전략 실패가 다른 전략에 영향 없음 (에러 격리)
- `CrawlError.error_type` 기반 자동 진단 및 권장 조치 생성 (`diagnostics.py:44-56`)
- EventBus 연동으로 실시간 이벤트 발행 (`CRAWL_STARTED`, `STRATEGY_SWITCHED`, `CRAWL_FAILED` 등)
- Playwright 스텔스 모드 + 자동화 감지 우회 (`playwright_helper.py:76-81`)

**결함**:
- IP_BANNED 에러 발생 시 `anti_detect.remove_proxy()` 미호출 (executor.py:161)
- 동시 크롤 작업 수 제한 없음 — Playwright 동시 실행 시 메모리 폭발 가능
- CloudScraper 인스턴스 정리가 명시적 cleanup 호출에만 의존 (메모리 누수 가능)

### 1.5 스케줄러 평가

**구현**: APScheduler BackgroundScheduler 래퍼 (`scheduler/scheduler.py`, 137줄)

- 크론 트리거 기반 작업 등록 (`CronTrigger.from_crontab`)
- `init_from_registry()`: plugin.yaml의 `schedule` 필드에서 자동 등록
- `JobTracker` (`job_tracker.py`, 85줄): 최근 500건 실행 이력 인메모리 보관

**제한 사항**:
- 단일 인스턴스 전용 (분산 환경 미지원)
- 실행 중인 작업의 중복 실행 방지 메커니즘 없음
- 실행 이력이 인메모리에만 존재 (재시작 시 소실)

### 1.6 플러그인 시스템 평가

**구성** (`plugins/`, 총 842줄):
- `plugin_interface.py` (204줄): PluginStatus 상태머신 + PluginMetrics + 라이프사이클 훅
- `plugin_loader.py` (356줄): YAML 디스커버리 + semver 검증 + 동적 import + 의존성 해결
- `plugin_manager.py` (282줄): 활성화/비활성화/핫리로드/이벤트 핸들링

**강점**:
- Kahn's 알고리즘으로 순환 의존성 탐지 (`plugin_loader.py:315-355`)
- `replace_existing=True`로 멱등성 보장
- 플러그인 로드 실패가 다른 플러그인에 영향 없음
- 런타임 설정 오버라이드 지원 (`override_config`)
- 핫리로드 지원

**결함**:
- 플러그인 서명/검증 없음 — 악성 코드 실행 가능 (`plugin_loader.py:260`)
- 유효 카테고리가 하드코딩 (`plugin_loader.py:30`)

---

## 2. DB 관리 도구 평가

### 2.1 아키텍처 개요

| 계층 | 기술 스택 | 주요 파일 |
|------|-----------|-----------|
| **프런트엔드** | React 19 + Vite 8 + Zustand 5 + Recharts 3 | `db-admin/frontend/src/` |
| **백엔드** | FastAPI + SQLAlchemy + Alembic (포트 8002) | `db-admin/backend/` |
| **DB** | SQLite (개발) / PostgreSQL (프로덕션) | `db-admin/backend/walletguardian.db` |

### 2.2 프런트엔드 UI 평가

**페이지 구성** (`db-admin/frontend/src/App.jsx`):

| 경로 | 페이지 | 기능 | 완성도 |
|------|--------|------|--------|
| `/` | Dashboard | 4개 통계 카드, 인박스 알림, 데이터 신선도, 품질 점수 게이지 | ✅ 양호 |
| `/inbox` | Inbox | 인제스천 큐 리뷰, 체크박스 선택, 전체/부분 승인/거부 | ✅ 우수 |
| `/products` | Products | CRUD, 검색/카테고리 필터, 90일 가격 추이 차트, 가격 티어 배지 | ✅ 양호 |
| `/categories` | Categories | 재귀 트리뷰, 속성 태그, 하위 카테고리 추가/편집/삭제 | ✅ 양호 |
| `/keywords` | Keywords | 상위 15 인기 키워드 차트, 동의어 태그 편집기 | ✅ 양호 |
| `/prices` | Prices | 4개 탭 (티어 설정, 이상치, 가격 데이터, 통계 요약) | ✅ 양호 |
| `/analytics` | Analytics | 가격 추이 차트, 카테고리별 평균, 품질 보고서, CSV/JSON 내보내기 | ✅ 양호 |

**주요 강점**:
- 인제스천 워크플로가 완전함: 크롤러 승인 → DB 관리자 검토 → 전체/부분/거부
- 편차 기반 이상치 시각화: >50% (빨강), 25-50% (노랑), <25% (초록) (`InboxPage.jsx:67-73`)
- 카테고리 트리의 무제한 깊이 재귀 렌더링 (`Categories.jsx:120-170`)
- CSV/JSON 내보내기 기능 (`Analytics.jsx:21-30`)
- 가격 티어 배지: 초특가/특가/적정/관망/비쌈 (`Products.jsx:7-8`)

**결함**:

| 문제 | 위치 | 심각도 |
|------|------|--------|
| 프런트엔드 변경이 백엔드에 영속되지 않음 (Zustand에만 저장) | `dbAdminStore.js` 전체 | 높 |
| API 실패 시 목업 데이터로 무음 전환 | `dbAdminStore.js:36-41` | 높 |
| React Error Boundary 없음 | 앱 전체 | 중 |
| 페이지네이션 없음 (대량 데이터 시 성능 문제) | Products, Keywords, Inbox | 중 |
| ARIA 레이블 부재, 키보드 내비게이션 미지원 | 앱 전체 | 낮 |
| 프런트엔드 테스트 파일 없음 (Vitest 설정만 존재) | `frontend/src/test/` | 중 |

### 2.3 백엔드 API 평가

**엔드포인트 총 27개** (`db-admin/backend/api/routes/`):

**상품 관리** (`products.py`):

| 메서드 | 경로 | 기능 |
|--------|------|------|
| GET | `/products/` | 상품 목록 |
| GET | `/products/{id}` | 상품 상세 (404 처리) |
| POST | `/products/` | 상품 생성 |
| PUT | `/products/{id}` | 상품 수정 (404 처리) |
| GET | `/products/{id}/baseline` | 기준 가격 |
| GET | `/products/{id}/hotdeal-price` | 핫딜 가격 |
| GET | `/products/{id}/tier` | 가격 티어 |
| GET | `/products/{id}/history` | 가격 이력 |
| GET | `/products/{id}/comparison` | 가격 비교 |

**가격** (`prices.py`):

| 메서드 | 경로 | 기능 |
|--------|------|------|
| POST | `/prices/bulk` | 벌크 가격 저장 (baseline/discount 분기) |
| GET | `/prices/stats` | 가격 통계 |
| GET | `/prices/product/{id}` | 상품별 가격 |

**카테고리** (`categories.py`): CRUD 5개 + 카테고리별 상품 목록  
**키워드** (`keywords.py`): 검색, 생성, 카운트 증가, 인기 키워드, 자동완성  
**분석** (`analytics.py`): 이상치 탐지, 중복 검출, 유효성 검사, 품질 보고서, 데이터 정리, 내보내기, 요약  
**인제스천** (`ingestion.py`): 통계, 제출, 목록, 상세, 크롤러 리뷰, DB 리뷰, 삭제

**에러 핸들링 패턴**:
- try-finally + `session.close()` — DB 연결 반환 보장 ✅
- `HTTPException(404)` — 리소스 미발견 처리 ✅
- `_insert_items()` 내 `except Exception: continue` — **모든 에러 무시** ⚠️ (ingestion.py:422-423)

**서비스 계층**: `services/` 디렉토리에 비즈니스 로직 분리 ✅  
**테스트**: 서비스 계층 테스트 1,120줄 (5개 파일) — API 라우트 직접 테스트 없음 ⚠️

---

## 3. 크롤러 품질 평가

### 3.1 크롤러 인벤토리

**총 18개 크롤러**, 6개 카테고리:

| 카테고리 | 수량 | 크롤러 |
|----------|------|--------|
| **배달 (delivery)** | 3 | 배달의민족, 쿠팡이츠, 요기요 |
| **핫딜 (hotdeals)** | 7 | 뽐뿌, 아카라이브, 클리앙, 코코달, FM코리아, 퀘이사존, 알구몬 |
| **대형마트 (marts)** | 4 | 이마트, 홈플러스, 롯데마트, 코코달인 |
| **쇼핑 (shopping)** | 3 | 무신사, 유니클로, 조르다노 |
| **위치 (location)** | 1 | 네이버 플레이스 |

### 3.2 구조 일관성 분석

| 평가 항목 | 일관성 | 설명 |
|-----------|--------|------|
| **플러그인 구조** | ✅ 100% | 모든 크롤러: `plugin.yaml` + `crawler.py` + `__init__.py` |
| **CrawlerContract 준수** | ✅ 100% | `crawl()`, `parse()`, `validate()` 전부 구현 |
| **안티디텍션** | ✅ 100% | 전부 `AntiDetect` 사용 (랜덤 User-Agent, 딜레이) |
| **중복 제거** | ✅ 100% | `validate()`에서 `seen` 집합 기반 추적 |
| **데이터 포맷** | ✅ 100% | 전부 Pydantic 모델 dict 반환 |
| **에러 핸들링** | ⚠️ 80% | 배달 크롤러는 `StrategyFailure` 누적; 핫딜 일부는 단순 예외 처리 |
| **재시도 로직** | ⚠️ 70% | 배달 크롤러: 명시적 재시도 루프; 핫딜 크롤러: 재시도 없음 |
| **속도 제한 설정** | ⚠️ 70% | 딜레이 값이 크롤러마다 하드코딩 (plugin.yaml 미활용) |

### 3.3 대표 크롤러 상세 분석

**배달의민족** (`crawlers/delivery/baemin/crawler.py`, 463줄):
- 전략: `requests` → `cloudscraper` → `playwright` (3단 캐스케이드)
- 대상: `mart.baemin.com`, `bmart.baemin.com`, `www.baemin.com`
- 딜레이: `delay_min=1.5, delay_max=3.0`
- 스케줄: `0 */6 * * *` (6시간마다)
- **품질**: 에러 핸들링 우수, 전략 실패 누적, Playwright 폴백 완비

**뽐뿌** (`crawlers/hotdeals/ppomppu/crawler.py`):
- ⚠️ EUC-KR 인코딩 하드코딩 (`response.encoding = "euc-kr"`, line 72)
- 단일 `requests` 전략만 사용 (캐스케이드 없음)
- 사이트 인코딩 변경 시 파싱 실패 위험

**이마트** (`crawlers/marts/emart/crawler.py`):
- Next.js SPA의 `__NEXT_DATA__` JSON 파싱
- 검색 키워드 하드코딩: `["행사", "할인", "특가"]` (line 40)
- 30개 항목 후 수집 중단 (line 91) — 사이트 부하 방지 ✅
- ⚠️ 타임아웃 20초 고정 (line 73) — 설정에서 미참조

**무신사** (`crawlers/shopping/musinsa/crawler.py`):
- PLP API + 랭킹 API 이중 폴백
- 카테고리 코드 하드코딩 (001=상의, 003=하의 등)

### 3.4 크롤러 공통 결함

1. **딜레이 값 하드코딩**: 각 크롤러에서 `AntiDetect(delay_min=X, delay_max=Y)`를 직접 설정. plugin.yaml의 설정을 참조하지 않아 운영자가 코드 수정 없이 변경 불가.
2. **타임아웃 미통일**: 일부 20초, 일부 30초. `config.py`의 `REQUEST_TIMEOUT=30`을 모든 크롤러가 참조해야 함.
3. **검색 키워드 하드코딩**: 이마트 등에서 키워드가 소스에 직접 포함. 설정 파일로 외부화 필요.

---

## 4. 데이터 파이프라인 평가

### 4.1 전체 데이터 흐름

```
[크롤러 실행]
    │
    ├── CrawlerContract.crawl() → CrawlResult
    │       └── StrategyExecutor (requests → cloudscraper → playwright)
    │
    ▼
[파이프라인 처리] (pipeline/pipeline.py, 289줄)
    │
    ├── 1. 재시도 (최대 3회, 지수 백오프: 2s, 4s, 6s, 8s, 10s 상한)
    ├── 2. 유효성 검사 (pipeline/validator.py, 107줄)
    │       ├── 필수 필드 검증
    │       ├── 가격 범위 검증 (0 ~ 10,000,000원)
    │       ├── URL 형식 검증
    │       └── 중복 제거 (key_fields 기반)
    ├── 3. 가격 정규화 (한국 통화 → int)
    ├── 4. 카테고리 매칭 (17개 키워드 → 카테고리 매핑)
    ├── 5. 변환 (pipeline/transformer.py, 111줄)
    │       ├── to_discount_history() — 마트 할인
    │       ├── to_hotdeal_prices() — 핫딜 게시판
    │       └── to_delivery_items() — 배달 앱
    │
    ▼
[저장 분기]
    │
    ├── SKIP_REVIEW=true → DB-Admin API 직접 저장 (/api/prices/bulk)
    │
    └── SKIP_REVIEW=false (기본값) → 인제스천 큐로 전송
            │
            ▼
        [크롤러 관리자 1차 리뷰] → 승인/거부
            │
            ▼
        [DB 관리자 2차 리뷰] → 전체/부분 승인/거부
            │
            ▼
        [최종 DB 테이블 삽입]
            ├── BaselinePrice (government, mart_regular 소스)
            ├── DiscountHistory (mart_discount 소스)
            └── HotdealPrice (hotdeal 소스)
```

### 4.2 파이프라인 강점

- **2단계 리뷰 워크플로**: 크롤러 관리자 → DB 관리자 순차 검토로 데이터 품질 보장
- **품질 점수 자동 계산**: 필수 필드 누락(40%), 이상치(30%), 중복(30%) 가중치 (`ingestion.py:47-109`)
- **데이터 소스별 분류**: `DataSource` enum으로 정부/마트/핫딜 분리. 핫딜은 기준 가격 산출에서 제외하여 통계 오염 방지
- **재시도 + 지수 백오프**: `pipeline.py:112-123`에서 실패 시 최대 10초까지 증가하며 재시도
- **에러 누적 보고**: 모든 단계의 에러가 `PipelineResult.errors`에 수집

### 4.3 파이프라인 갭 (Gap)

| 갭 | 위치 | 영향 |
|----|------|------|
| **가격 None 무검증 통과** | `validator.py:39` — `if price is None: valid.append(item)` | None 가격 항목이 DB에 저장될 수 있음 |
| **가격 파싱 정규식 한계** | `validator.py:101` — `r"[\d,]+"` | "₩12,500", "12500원" 등 접두/접미사 포함 시 부분 매칭 가능 |
| **항목 수 제한 없음** | `pipeline.py` 전체 | 100만 건 데이터도 수용 — 메모리 부족 위험 |
| **인제스천 삽입 시 에러 무시** | `ingestion.py:422-423` — `except Exception: continue` | 개별 항목 삽입 실패 시 무음 건너뜀 — 데이터 손실 |
| **카테고리 매핑 하드코딩** | `transformer.py:79-97` — 17개 키워드만 지원 | 신규 상품 카테고리 누락 시 "미분류" 처리 |
| **변환 타입 분기 부족** | `pipeline.py:156-161` | 배달 데이터(`to_delivery_items`) 분기가 불완전 |

### 4.4 공유 모델 평가 (`packages/shared/core/`)

**models.py** (298줄) — 핵심 데이터 모델:
- `CrawlStatus`, `ErrorType`, `CrawlerGroup`, `DataSource`, `IngestionStatus` — 5개 enum
- `CrawlerInfo`, `CrawlRequest`, `CrawlResult`, `StrategyFailure`, `DiagnosisReport` — 크롤러 실행 모델
- `ProductPrice`, `DiscountItem`, `HotdealPost` — 가격 데이터 모델
- `PendingIngestionSummary`, `PendingIngestionDetail`, `IngestionReviewRequest` — 인제스천 모델

**contracts/** — 4개 인터페이스 계약:
- `CrawlerContract` (67줄): crawl/parse/validate + setup/teardown 훅
- `EngineContract` + `StrategyContract` (102줄): 실행 엔진 + 전략 인터페이스
- `SchedulerContract` (58줄): 작업 등록/제거/일시정지/재개
- `StorageContract` + `FileStorageContract` (105줄): 데이터 저장 + 이미지 저장

**statistics.py** (228줄):
- IQR 이상치 제거 (`remove_outliers_iqr`) — 식품 가격의 비정규 분포에 적합 ✅
- 평균/중앙값/표준편차/신뢰구간 계산 (`compute_stats`)
- SMA 7일/30일 + EMA 7일 이동평균 (`compute_moving_averages`)
- 가격 티어 결정: ultra(≤0.70)/great(≤0.85)/good(≤1.05)/wait(>1.05) (`determine_tier`)
- 계절 비교 (`seasonal_comparison`) — 전년 동기 대비

**verification.py** (122줄):
- 커뮤니티 가격 검증: <20% (의심/차단), 20-70% (핫딜), 70-120% (정상), >120% (의심/경고)
- `can_post` 플래그로 가격 조작 게시물 차단 기능

**평가**: 공유 모델 설계는 **매우 우수**. 의존성 역전 원칙 준수, Pydantic 기반 직렬화, 명확한 인터페이스 분리.

---

## 5. 보안 평가

### 5.1 치명적 (Critical) 이슈

| # | 이슈 | 위치 | 위험 | 권장 조치 |
|---|------|------|------|-----------|
| 1 | **CORS 와일드카드 + 자격증명 허용** | `crawler-admin/backend/api/app.py:13-19` | 모든 출처에서 인증 포함 요청 가능. CSRF 공격 노출 | `allow_origins`를 프런트엔드 도메인으로 한정 |
| 2 | **CORS 와일드카드** (동일 문제) | `db-admin/backend/api/app.py:13-19` | 동일 | 동일 |
| 3 | **기본 DB 자격증명 코드 노출** | `crawler-admin/backend/config.py:18` — `"postgresql://user:password@localhost:5432/..."` | 환경변수 미설정 시 기본 비밀번호 사용 | 기본값 제거, 환경변수 필수화 |
| 4 | **인증/인가 미구현** | 양쪽 `app.py` | 모든 엔드포인트 무인증 접근 가능. 데이터 삭제/수정 무제한 | JWT 미들웨어 + 역할 기반 접근 제어 추가 |

### 5.2 높음 (High) 이슈

| # | 이슈 | 위치 | 위험 |
|---|------|------|------|
| 5 | **플러그인 서명 미검증** | `crawler-admin/backend/plugins/plugin_loader.py:260` — `spec.loader.exec_module(module)` | 악성 `crawler.py`가 임의 코드 실행 가능 |
| 6 | **인제스천 에러 무시** | `db-admin/backend/api/routes/ingestion.py:422-423` — `except Exception: continue` | 삽입 실패 추적 불가, 데이터 손실 |
| 7 | **인제스천 items 미검증** | `db-admin/backend/api/routes/ingestion.py:26-34` — `items: list[dict] = []` | 임의 딕셔너리 저장 가능, XSS 페이로드 삽입 위험 |

### 5.3 중간 (Medium) 이슈

| # | 이슈 | 위치 |
|---|------|------|
| 8 | 로그 쿼리 파라미터 미검증 | `crawler-admin/backend/api/routes/logs.py:25` |
| 9 | API 키 평문 메모리 저장 | `crawler-admin/backend/config.py:21-28` |
| 10 | API 클라이언트 HTTP 응답 코드 미확인 | `crawler-admin/frontend/src/api/client.js` — `.then(r => r.json())` without status check |
| 11 | API 클라이언트 타임아웃 없음 | `db-admin/frontend/src/api/client.js` |
| 12 | 동시 크롤 실행 수 무제한 | `crawler-admin/backend/scheduler/scheduler.py` |

### 5.4 긍정적 사항

- SQL 인젝션 위험 없음: SQLAlchemy ORM 사용, 크롤러에 직접 DB 쿼리 없음 ✅
- Pydantic 모델로 기본 타입 검증 ✅
- 프록시 목록 환경변수 로드 (`config.py:31-33`) ✅
- EventBus `_safe_call`로 핸들러 예외 격리 ✅

---

## 6. 운영 편의성

### 6.1 일상 운영 시나리오 평가

| 시나리오 | 지원 여부 | 사용 용이성 | 비고 |
|----------|-----------|-------------|------|
| **크롤러 상태 모니터링** | ✅ | 양호 | 대시보드에 활성 수, 성공률, 에러 추이 표시 |
| **수동 크롤링 실행** | ✅ | 양호 | Crawlers 페이지에서 1클릭 실행. 단, 확인 대화상자 없음 |
| **실행 로그 확인** | ✅ | 양호 | 이름/상태 필터 + 상세 에러 확장 뷰 |
| **스케줄 관리** | ⚠️ 부분 | 보통 | 크론식 편집 가능하나 유효성 검증 없음 |
| **데이터 품질 검토** | ✅ | 우수 | 2단계 리뷰 + 품질 점수 + 스키마 미리보기 |
| **신규 크롤러 추가** | ✅ | 우수 | 디렉토리 생성 + plugin.yaml + crawler.py → 자동 등록 |
| **상품 관리** | ⚠️ 부분 | 보통 | UI 존재하나 백엔드 연동 불완전 |
| **카테고리 관리** | ✅ | 양호 | 재귀 트리뷰 + CRUD |
| **가격 분석** | ✅ | 양호 | 추이 차트 + 이상치 탐지 + 내보내기 |
| **장애 대응** | ⚠️ | 미흡 | 에러가 프런트엔드에 표시되지 않고 목업 전환. 운영자가 장애 인지 어려움 |
| **프록시 교체** | ⚠️ | 보통 | 환경변수 변경 + 서비스 재시작 필요 |
| **시스템 알림** | ❌ | 없음 | 이메일/Slack 등 외부 알림 없음 |

### 6.2 운영 도구 성숙도 요약

```
크롤러 관리 도구:  ████████░░  (80%) — 모니터링/실행 우수, 알림/인증 부재
DB 관리 도구:      ███████░░░  (70%) — UI 우수, 백엔드 연동/에러 처리 미흡
공유 모듈:         █████████░  (90%) — 모델/계약/통계 매우 우수
보안:              ████░░░░░░  (40%) — 인증 없음, CORS 취약
```

### 6.3 Docker 배포 준비 상태

- `docker-compose.yml`, `docker-compose.dev.yml` 존재 ✅
- 각 서비스 독립 포트 (8000, 8002) ✅
- 환경변수 기반 설정 ✅
- Alembic 마이그레이션 (`db-admin/backend/alembic.ini`) ✅

---

## 7. 구체적 개선 제안

### 7.1 [P0] 즉시 수정 — 보안

#### 7.1.1 CORS 설정 수정

**파일**: `packages/crawler-admin/backend/api/app.py:13-19`  
**파일**: `packages/db-admin/backend/api/app.py:13-19`

```python
# 현재 (위험)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 수정안
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
```

#### 7.1.2 기본 DB 자격증명 제거

**파일**: `packages/crawler-admin/backend/config.py:18`

```python
# 현재 (위험)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/wallet_guardian")

# 수정안
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ConfigError("DATABASE_URL 환경변수가 설정되지 않았습니다")
```

#### 7.1.3 인증 미들웨어 추가

**파일**: `packages/crawler-admin/backend/api/app.py` 및 `packages/db-admin/backend/api/app.py`

```python
# FastAPI 종속성 주입 패턴으로 JWT 인증 추가
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    # JWT 검증 로직
    pass

# 각 라우터에 dependencies=[Depends(verify_token)] 추가
```

### 7.2 [P1] 1주 내 수정 — 데이터 무결성

#### 7.2.1 인제스천 에러 무시 수정

**파일**: `packages/db-admin/backend/api/routes/ingestion.py:420-424`

```python
# 현재 (데이터 손실 위험)
except Exception:
    continue

# 수정안
except Exception as e:
    logger.warning(f"[Ingestion] 항목 삽입 실패: {e}", exc_info=True)
    failed_items.append({"index": idx, "error": str(e)})
    continue
# 함수 반환 시 failed_items도 포함
```

#### 7.2.2 가격 None 검증 추가

**파일**: `packages/crawler-admin/backend/pipeline/validator.py:39`

```python
# 현재
if price is None:
    valid.append(item)
    continue

# 수정안
if price is None:
    item["_validation_error"] = f"가격 없음 ({price_field})"
    invalid.append(item)
    continue
```

#### 7.2.3 프런트엔드 API 에러 핸들링

**파일**: `packages/crawler-admin/frontend/src/api/client.js`  
**파일**: `packages/db-admin/frontend/src/api/client.js`

```javascript
// 현재
getCrawlers: () => fetch(`${API_BASE}/crawlers`).then(r => r.json()),

// 수정안
getCrawlers: () => fetch(`${API_BASE}/crawlers`).then(r => {
  if (!r.ok) throw new Error(`API 오류: ${r.status} ${r.statusText}`);
  return r.json();
}),
```

**파일**: `packages/crawler-admin/frontend/src/stores/adminStore.js:24-35`

```javascript
// 현재 (무음 실패)
} catch {
  // API 실패 시 mock 데이터 유지
}

// 수정안
} catch (e) {
  console.error("[Store] fetchCrawlers 실패:", e);
  set({ error: `크롤러 목록 로드 실패: ${e.message}` });
}
```

### 7.3 [P2] 2주 내 수정 — 기능 완성

#### 7.3.1 미연결 버튼 연결

**파일**: `packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.jsx:62`
- "크롤러 추가" 버튼에 모달 폼 연결 또는 비활성화(disabled) 처리

**파일**: `packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.jsx:146-149`
- "설정" 버튼에 크롤러별 설정 모달 연결

**파일**: `packages/crawler-admin/frontend/src/pages/Schedule/Schedule.jsx:112-114`
- 스케줄의 "수동 실행" 버튼에 `runCrawler` 연결

#### 7.3.2 크론식 유효성 검증

**파일**: `packages/crawler-admin/frontend/src/pages/Schedule/Schedule.jsx` 편집 모달

```javascript
// croner 패키지 사용
import { Cron } from 'croner';

const validateCron = (expr) => {
  try { new Cron(expr); return true; }
  catch { return false; }
};
```

#### 7.3.3 프런트엔드-백엔드 영속성 연결

**파일**: `packages/db-admin/frontend/src/stores/dbAdminStore.js`

`addProduct`, `updateProduct`, `deleteProduct` 등이 현재 Zustand 상태만 변경. 
각 액션에서 해당 API 호출 (`POST /products/`, `PUT /products/{id}`) 후 성공 시 상태 업데이트하도록 수정.

### 7.4 [P3] 1개월 내 수정 — 운영 개선

#### 7.4.1 크롤러 딜레이 설정 외부화

**대상**: 모든 크롤러 (`crawlers/**/crawler.py`)

```python
# 현재 (하드코딩)
self._anti_detect = AntiDetect(delay_min=0.5, delay_max=1.5)

# 수정안: plugin.yaml에서 읽기
delay_config = self._config.get("rate_limit", {})
self._anti_detect = AntiDetect(
    delay_min=delay_config.get("delay_min", CRAWL_DELAY_MIN),
    delay_max=delay_config.get("delay_max", CRAWL_DELAY_MAX),
)
```

**plugin.yaml 추가**:
```yaml
rate_limit:
  delay_min: 0.5
  delay_max: 1.5
```

#### 7.4.2 동시 크롤 실행 제한

**파일**: `packages/crawler-admin/backend/scheduler/scheduler.py`

```python
import asyncio

class CrawlScheduler:
    def __init__(self, max_concurrent: int = 5, ...):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def _execute_job(self, crawler_name: str):
        async with self._semaphore:
            await self._pipeline.run_crawler(crawler_name)
```

#### 7.4.3 외부 알림 시스템

**추가 위치**: `packages/crawler-admin/backend/engine/` 또는 새 `notifications/` 모듈

- EventBus의 `CRAWL_FAILED` 이벤트 구독
- `AllStrategiesFailedError` 발생 시 Slack/이메일 전송
- 일일 크롤링 요약 보고서 발송

#### 7.4.4 실행 이력 영속화

**파일**: `packages/crawler-admin/backend/scheduler/job_tracker.py`

현재 인메모리 리스트 → SQLite/PostgreSQL 테이블로 전환하여 서비스 재시작 후에도 이력 유지.

#### 7.4.5 스케줄러 분산 지원

**파일**: `packages/crawler-admin/backend/scheduler/scheduler.py`

APScheduler `BackgroundScheduler` → Celery + Redis 전환으로 수평 확장 지원.

### 7.5 [P4] 장기 과제

| 항목 | 설명 |
|------|------|
| TypeScript 마이그레이션 | 프런트엔드 `.jsx` → `.tsx` 전환으로 타입 안전성 확보 |
| 플러그인 서명 검증 | cryptographic manifest + hash 검증 |
| 프런트엔드 테스트 | Vitest + React Testing Library 테스트 작성 |
| API 라우트 테스트 | pytest + FastAPI TestClient로 전 엔드포인트 테스트 |
| 메트릭/옵저버빌리티 | Prometheus 메트릭 내보내기 + Grafana 대시보드 |
| async SQLAlchemy | 동기 세션 → 비동기 세션 전환으로 동시성 개선 |
| 페이지네이션 | 모든 목록 API에 `limit/offset` 파라미터 추가 |

---

## 부록: 테스트 커버리지 현황

### 크롤러 관리 백엔드 (`crawler-admin/backend/tests/`)

| 파일 | 테스트 수 | 대상 |
|------|-----------|------|
| `test_crawler_api.py` | 25 | API 엔드포인트 |
| `test_hotdeal_crawlers.py` | 36 | 핫딜 크롤러 |
| `test_mart_crawlers.py` | 21 | 마트 크롤러 |
| `test_pipeline.py` | 29 | 파이프라인 |
| `test_registry.py` | 13 | 크롤러 레지스트리 |
| `test_scheduler.py` | 18 | 스케줄러 |
| `engine/tests/` | 28 | 엔진 (executor, strategies, diagnostics) |
| `plugins/tests/` | 100 | 플러그인 (interface, loader, manager, framework) |
| **합계** | **~270** | |

### DB 관리 백엔드 (`db-admin/backend/tests/`)

| 파일 | 대상 |
|------|------|
| `test_models.py` | ORM 모델 CRUD |
| `test_category_mgmt.py` | 카테고리 트리 |
| `test_autocomplete.py` | 키워드 검색 |
| `test_data_quality.py` | 이상치/중복 탐지 |
| `test_price_calc.py` | 가격 계산/티어 |
| **합계** | **~1,120줄** (서비스 계층 집중, API 라우트 미테스트) |

### 공유 모듈 (`shared/tests/`)

| 파일 | 대상 |
|------|------|
| `test_models.py` | Pydantic 모델 검증 |
| `test_exceptions.py` | 예외 계층 |
| `test_events.py` | EventBus |
| `test_price_models.py` | 가격 파이프라인 |
| `test_strategy.py` | 카테고리/통계/레시피/검증 |
| **합계** | **~920줄** |

---

## 종합 평가

| 영역 | 점수 | 평가 |
|------|------|------|
| **크롤러 관리 도구** | 7.5/10 | 엔진·플러그인 아키텍처 우수. UI 일부 미완성, 보안 미흡 |
| **DB 관리 도구** | 6.5/10 | UI 구성 우수. 프런트-백 연동 불완전, 보안 미흡 |
| **크롤러 품질** | 8.0/10 | 18개 크롤러 구조 일관. 일부 설정 하드코딩 |
| **데이터 파이프라인** | 7.5/10 | 2단계 리뷰 + 품질 점수 우수. 에러 무시·가격 파싱 갭 존재 |
| **공유 모듈** | 9.0/10 | 모델/계약/통계 매우 잘 설계. 프로덕션 준비 수준 |
| **보안** | 4.0/10 | 인증 없음, CORS 와일드카드, 기본 자격증명 노출 |
| **운영 편의성** | 7.0/10 | 모니터링·실행 가능. 알림·장애 인지 미흡 |
| **테스트 커버리지** | 7.0/10 | 백엔드 서비스 잘 테스트됨. API·프런트엔드 테스트 부족 |

**종합**: 기술적 기반은 **견고하며 확장 가능한 아키텍처**를 갖추고 있음. 특히 플러그인 시스템, 전략 캐스케이드 엔진, 공유 모델 설계가 뛰어남. 그러나 **보안 (인증 부재, CORS)**과 **프런트-백 연동 완성도**가 인수 전 반드시 해결해야 할 핵심 리스크. P0/P1 이슈 해결에 약 **2-3주**, 전체 프로덕션 준비에 **4-6주** 소요 예상.
