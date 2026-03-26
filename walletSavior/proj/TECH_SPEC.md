# 지갑 지키미 (Wallet Guardian) — 기술 기획서 v1.0

> **목적**: 이 문서는 프로젝트의 모든 기획/설계 결정사항과 개발 현황을 기록한다.
> 대화 기록이 유실되더라도 이 문서만으로 개발을 이어갈 수 있도록 한다.
> 
> **최종 갱신**: 2026-03-18

---

## 1. 프로젝트 개요

### 1.1 목표
대학 졸업작품. **각종 물가를 종합 비교하여 "이 가격이 정말 싼 건지" 판단해주는 웹서비스.**
- 대형마트 할인 정보 수집 + 정부 공식 물가와 비교
- 핫딜 게시판 통합 크롤링
- 배달앱/식당 가격 비교
- 주유소 가격 비교
- 물가 변동 추이 제공
- 유저간 할인 정보 공유 게시판 (사진 포함)

### 1.2 핵심 가치
- "이 할인가가 진짜 싼 건지" 과거 할인가 평균 DB 데이터로 검증
- 모든 분야(마트/식당/주유소/배달앱)의 가격을 한 곳에서 비교
- 실제 서비스 수준의 설계 (면접 어필용, "졸업작품이라 감안" 없이)
- **때문에 과거 할인 및 가격 데이터가 모인 DB 구축이 중요**

### 1.4 기초 DB 전략 — "오염되지 않은 가격"

> **핵심**: 핫딜 게시판 가격이나 가뭄/재해 등 특수 물가가 DB에 유입되면 평균 가격이 오염된다.
> 바이럴, 이상치, 특수 할인이 섞이면 "정상 가격"을 판단할 수 없게 된다.

**오염 방지 원칙:**

| 데이터 소스 | 신뢰도 | 용도 |
|---|---|---|
| **정부 공식 가격** (KAMIS, KOSIS) | ★★★ 최고 | 기준 가격 (baseline) |
| **마트 전단/정가** | ★★★ 높음 | 일반 시장가 + 할인가 DB |
| **핫딜 게시판** | ★☆☆ 낮음 (표시용) | 최저가 참고만, 평균 산출에 불포함 |
| **배달앱 가격** | ★★ 중간 | 외식 가격 참고 |

**DB 분리 설계:**
- `baseline_prices` — 정부 공식 + 마트 정가로만 구성. **오염 불가능한 기준 테이블**
- `discount_history` — 마트 전단 할인가 이력. 주기적 자동 수집
- `hotdeal_prices` — 핫딜 가격은 별도 저장, 평균 산출에 불포함
- 품목별 평균/중간/상위 가격은 `baseline_prices + discount_history`에서만 계산

### 1.5 UX 설계 철학

> **"사용자가 귀찮을 일을 최대한 줄여야 한다."**
> 핫딜 정보는 찾으려면 누구나 찾을 수 있다. 귀찮아서 안 하는 것이다.
> 최소한의 입력, 최소한의 터치, 복잡하지 않고 단순하지만 원하는 것을 다 얻을 수 있게.

**UX 핵심 원칙:**
1. **자동완성 검색** — '양' 입력 → '양파', '양송이', '양배추' 목록 즉시 표시
2. **자동 가격 컨텍스트** — 핫딜 글 조회 시 해당 품목의 평균·중간·최저가 자동 표시
3. **탭 기반 네비게이션** — 물가비교 / 핫딜 / 마트할인 / 주유소 / 배달 탭
4. **원터치 비교** — 품목 터치 한 번으로 날짜별 가격 추이 그래프
5. **핫딜 자동 분석** — 게시글 가격 vs DB 평균가 자동 비교 뱃지 ("평균 대비 30% 저렴!")

### 1.3 프로젝트 구성
프로젝트는 **2개의 독립 애플리케이션**으로 구성:

| # | 이름 | 설명 | 현재 개발중 |
|---|---|---|---|
| 1 | **크롤러 앱** | 데이터 수집 전용. 자체 프론트/백엔드 보유 | ✅ 현재 |
| 2 | **메인 웹서비스** | 사용자 대상 서비스 (물가비교, 게시판, 로그인 등) | ❌ 미착수 |

**현재 이 문서는 ①크롤러 앱에 대한 것이다.**

---

## 2. 아키텍처 설계 원칙

### 2.1 절대 준수 원칙

| 원칙 | 설명 |
|---|---|
| **결합도 제로** | 모듈끼리 직접 import 금지. 오직 `core/contracts`의 인터페이스만 의존 |
| **API 통신** | 모듈 간 통신은 이벤트 버스 또는 REST API로만 |
| **플러그인 패턴** | 크롤러는 플러그인으로 등록. 추가/삭제 시 다른 코드 변경 없음 |
| **DI 컨테이너** | 모든 의존성 주입. `container.py`만이 구체 클래스를 알고 조립 |
| **TDD** | 테스트 먼저 작성 → 구현 → 리팩토링. 리그레션 테스트 축적 |
| **기획 변경 내성** | 기획이 갈아엎여도 프로젝트가 안 무너지는 구조 |

### 2.2 Import 규칙 (엄격 준수)
```
engine/    → core/ 만
crawlers/  → core/ 만
storage/   → core/ 만
api/       → core/ 만
scheduler/ → core/ 만
frontend/  → import 없음 (HTTP 통신만)

❌ engine/ → crawlers/ 불가
❌ api/ → engine/ 직접 import 불가
❌ crawlers/ → storage/ 직접 import 불가
```

### 2.3 조립은 `container.py` 한 곳에서만
```python
class Container:
    # 유일하게 모든 구체 클래스를 아는 곳
    event_bus = EventBus()
    storage = DBStorage(...)
    engine = StrategyExecutor(event_bus)
    crawlers = CrawlerRegistry.discover("crawlers/")
    scheduler = CrawlScheduler(engine)
    api = create_app(engine, storage, event_bus)
```

---

## 3. 기술 스택

| 영역 | 기술 | 이유 |
|---|---|---|
| 언어 | Python 3.13 | 크롤링 생태계 최강 |
| DB | **PostgreSQL** | MVCC 동시접속, full-text search, JSON 지원 |
| ORM | SQLAlchemy 2.x | 마이그레이션(Alembic) 지원 |
| API 서버 | FastAPI | 비동기, 자동 문서화, WebSocket |
| 프론트 | Vanilla HTML/JS/CSS | 대시보드이므로 프레임워크 최소화 |
| 크롤링 | requests, cloudscraper, Selenium, undetected-chromedriver, Playwright | 5단계 전략 |
| 테스트 | pytest + pytest-asyncio + pytest-mock + vcrpy | TDD + 리그레션 |
| 스케줄링 | APScheduler | cron 방식 스케줄 |
| 이미지 저장 | **파일시스템 + DB 메타데이터** | 프로덕션 시 S3로 전환 가능 |

### 3.1 DB 선택 근거 (면접 대비)
- SQLite 미사용 이유: 동시접속 불가, 이미지 메타+사진이 매일 쌓이면 감당 불가
- PostgreSQL: MVCC로 수십~수백 사용자 동시 읽기/쓰기, 커넥션 풀링, 레플리카 가능

### 3.2 이미지 저장 전략 (면접 대비)
- DB에 BLOB 저장 ❌ (DB 비대화, 백업 느림)
- DB에는 메타데이터만 (경로, 파일명, 크기, MIME)
- 파일시스템에 WebP 변환 + 썸네일 자동 생성
- 프로덕션: S3 + CloudFront로 전환 가능하도록 StorageBackend 인터페이스

---

## 4. 다중 전략 크롤링 엔진

### 4.1 핵심 설계
하나의 사이트에 대해 **5가지 기술적 접근을 자동 cascade**:

| 순서 | 전략 | difficulty | 용도 |
|---|---|---|---|
| ① | `requests + BS4` | 1 | 정적 HTML, API |
| ② | `cloudscraper` | 2 | Cloudflare 기본 보호 우회 |
| ③ | `Selenium + stealth` | 3 | JS 렌더링 SPA |
| ④ | `undetected-chromedriver` | 4 | 강화 봇 탐지 우회 |
| ⑤ | `Playwright + stealth` | 5 | 최고 수준 봇 우회 |

### 4.2 Fallback Chain
- 같은 대상의 **대체 사이트**도 지원
  - 코스트코 실패 → cocodalin.com
  - 이마트 실패 → emartmall.com
  - 홈플러스/롯데마트 실패 → 마트몬

### 4.3 에러 진단 시스템
모든 실패를 자동 분류하고 한국어 추천 대응 제공:

| 에러 타입 | 심각도 | 추천 |
|---|---|---|
| IP_BANNED | 10 | 프록시 교체 + 요청 간격 |
| CAPTCHA_DETECTED | 9 | CAPTCHA 서비스 연동 |
| JS_CHALLENGE | 7 | 브라우저 전략 사용 |
| LOGIN_REQUIRED | 6 | 인증 설정 |
| DOM_CHANGED | 5 | CSS 셀렉터 업데이트 |
| HTTP_ERROR | 4 | URL 변경 확인 |
| EMPTY_RESPONSE | 3 | 렌더링 대기 증가 |
| TIMEOUT | 3 | 타임아웃 값 증가 |

### 4.4 AntiDetect
- User-Agent 풀: 실제 브라우저 UA 18개+ 랜덤 로테이션
- Accept-Language: "ko-KR,ko" 한국어 우선
- 프록시: 라운드로빈 + 랜덤 + 동적 추가/제거
- 요청 딜레이: 1~5초 랜덤

---

## 5. 크롤링 대상 (14개)

### 5.1 공공 API (3개) — API 키 필요
| 대상 | API | 수집 데이터 | API 키 상태 |
|---|---|---|---|
| **KAMIS** | kamis.or.kr | 농축수산물 도소매 가격 (69개 도매, 90개 소매) | ❌ 미발급 |
| **OPINET** | opinet.co.kr | 전국 주유소 가격 + 최저가 Top 20 | ❌ 미발급 |
| **KOSIS** | kosis.kr | 소비자물가지수 (식료품, 외식, 교통 등) | ❌ 미발급 |

> API 키는 [data.go.kr](https://data.go.kr) 회원가입 후 발급. `.env`에 넣으면 바로 동작하도록 설계.

### 5.2 대형마트 (4+1개) — 웹 크롤링
| 대상 | URL | 전략 조합 | Fallback |
|---|---|---|---|
| 이마트 | emart.com | ①→②→③→④ | emartmall.com |
| 홈플러스 | homeplus.co.kr | ①→②→③→④ | 마트몬 |
| 롯데마트 | lottemartgo.com | ①→②→③→④ | 마트몬 |
| 코스트코 | costco.co.kr | ①→②→③ | cocodalin.com |
| cocodalin | cocodalin.com | ①→② | - |

### 5.3 핫딜 게시판 (3개) — 커뮤니티 크롤링
| 대상 | URL |
|---|---|
| 아카라이브 | arca.live/b/hotdeal |
| 에펨코리아 | fmkorea.com/hotdeal |
| 알구몬 | algumon.com/n/deal |

### 5.4 배달/식당 (4개)
| 대상 | 방식 |
|---|---|
| 배달의민족 | Selenium (JS 필수) |
| 요기요 | Selenium |
| 쿠팡이츠 | Selenium |
| 네이버 플레이스 | API + Selenium |

---

## 6. 프로젝트 구조

```
e:\pdf\capston01\proj\
├── core/                          # 계약만 (인터페이스, 구현 없음)
│   ├── contracts/
│   │   ├── crawler.py             # CrawlerContract
│   │   ├── engine.py              # EngineContract + StrategyContract
│   │   ├── storage.py             # StorageContract + FileStorageContract
│   │   └── scheduler.py           # SchedulerContract
│   ├── models.py                  # 공유 Pydantic 모델 (10개)
│   ├── events.py                  # EventBus (async pub/sub)
│   └── exceptions.py              # 예외 계층 (ErrorType 분류)
│
├── engine/                        # 크롤링 엔진 (core만 의존)
│   ├── executor.py                # StrategyExecutor (cascade)
│   ├── diagnostics.py             # 에러 자동 진단
│   ├── anti_detect.py             # UA풀, 프록시, 딜레이
│   ├── strategies/
│   │   ├── base.py                # BaseStrategy
│   │   ├── requests_st.py         # ① difficulty:1
│   │   ├── cloudscraper_st.py     # ② difficulty:2
│   │   ├── selenium_st.py         # ③ difficulty:3
│   │   ├── undetected_st.py       # ④ difficulty:4
│   │   └── playwright_st.py       # ⑤ difficulty:5
│   └── tests/                     # 28개 테스트
│
├── crawlers/                      # 크롤러 플러그인 (core만 의존)
│   ├── registry.py                # 플러그인 자동 발견 [미구현]
│   ├── public/ (kamis, opinet, kosis)      [미구현]
│   ├── marts/ (emart, homeplus, ...)       [미구현]
│   ├── hotdeals/ (arca, fmkorea, algumon)  [미구현]
│   └── food/ (baemin, yogiyo, ...)         [미구현]
│
├── storage/                       # DB + 파일 저장소 [미구현]
├── api/                           # FastAPI 서버 [미구현]
├── scheduler/                     # APScheduler [미구현]
├── frontend/                      # 대시보드 UI [미구현]
├── utils/                         # 유틸리티 [미구현]
│
├── container.py                   # DI 컨테이너 (스켈레톤)
├── main.py                        # CLI 진입점
├── config.py                      # .env 기반 설정
├── conftest.py                    # 전역 pytest fixture
├── pytest.ini                     # 테스트 설정
├── requirements.txt               # 의존성
├── .env.example                   # 환경변수 템플릿
└── tests/                         # 36개 core 테스트
```

---

## 7. DB 스키마 (초안 — 확정 아님)

> 로그인, 게시판 등 추후 기능에 따라 테이블이 추가/변경된다.
> 현재는 크롤러 운영에 필요한 최소 구조만 구상.

| 테이블 | 설명 |
|---|---|
| `categories` | 품목 카테고리 (계층구조) |
| `products` | 품목 마스터 |
| `official_prices` | 공식 물가 (KAMIS) |
| `discount_items` | 마트 할인 상품 |
| `gas_stations` | 주유소 마스터 |
| `gas_prices` | 주유소 가격 이력 |
| `price_indices` | 소비자물가지수 |
| `hotdeal_posts` | 핫딜 게시판 글 |
| `hotdeal_images` | 이미지 메타데이터 |
| `restaurants` | 식당 정보 |
| `restaurant_menus` | 식당 메뉴/가격 |
| `delivery_deals` | 배달앱 할인 |
| `crawl_logs` | 크롤링 실행 로그 |
| `crawl_errors` | 에러 상세 + 진단 JSON |

---

## 8. 크롤러 앱 기능 요구사항

### 8.1 백엔드 (FastAPI)
| 엔드포인트 | 기능 |
|---|---|
| `GET /api/crawlers` | 등록 크롤러 목록 + 상태 |
| `POST /api/crawlers/{name}/run` | 즉시 크롤링 |
| `POST /api/crawlers/{name}/stop` | 크롤링 중지 |
| `GET/POST /api/jobs` | 스케줄 관리 |
| `GET /api/logs` | 크롤링 로그 (필터링) |
| `GET /api/logs/{id}/diagnosis` | 실패 상세 진단 |
| `GET /api/data/{type}` | 수집 데이터 조회 |
| `WS /ws/status` | 실시간 진행률 |

### 8.2 프론트엔드 (대시보드)
1. **대시보드 홈** — 크롤러 상태 카드
2. **크롤링 제어** — 개별/일괄 시작/정지/스케줄
3. **에러 & 진단** — 실패 로그 + 원인 분류 + 추천 대응
4. **데이터 미리보기** — 수집된 데이터 테이블/카드 뷰

---

## 9. 개발 현황

### 9.1 완료된 Phase

| Phase | 내용 | Tests |
|---|---|---|
| **Phase 1** ✅ | 프로젝트 구조, core 계약 4개, EventBus, Pydantic 모델 10개, 예외 8종, DI 컨테이너, CLI | 36 |
| **Phase 2** ✅ | StrategyExecutor, DiagnosticsEngine, AntiDetect, BaseStrategy, 5가지 전략 구현 | 28 |
| **총 테스트** | | **64 (0.20s)** |

### 9.2 남은 Phase

| Phase | 내용 | 우선순위 |
|---|---|---|
| 3 | 공공 API 크롤러 (KAMIS, OPINET, KOSIS) | API 키 발급 후 |
| 4 | 대형마트 크롤러 (이마트, 홈플러스, 롯데마트, 코스트코) | 높음 |
| 5 | 핫딜 게시판 크롤러 (아카, 에펨, 알구몬) | 높음 |
| 6 | 배달/식당 크롤러 (배민, 요기요, 쿠팡이츠, 네이버) | 중간 |
| 7 | FastAPI 백엔드 + 스케줄러 | 높음 |
| 8 | 프론트엔드 대시보드 | 중간 |
| 9 | 통합 테스트 + 리그레션 | 높음 |

### 9.3 API 키 미발급 상태
- KAMIS, OPINET, KOSIS 모두 **미발급**
- data.go.kr 회원가입 필요
- `.env.example`에 키 템플릿은 작성됨
- **API 키 없어도 나머지 크롤러는 전부 동작 가능하도록 설계**

---

## 10. 크롤러 플러그인 작성법

새 크롤러 추가 시 **다른 코드 변경 없이** 폴더 하나만 추가:

```python
# crawlers/marts/emart/__init__.py
plugin_info = {
    "name": "이마트",
    "version": "1.0.0",
    "group": "marts",
    "strategies": ["requests", "cloudscraper", "selenium"],
}

# crawlers/marts/emart/crawler.py
class EmartCrawler(CrawlerContract):
    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(**plugin_info)

    async def crawl(self) -> CrawlResult: ...
    async def parse(self, raw_data: str) -> list[dict]: ...
    async def validate(self, items: list[dict]) -> list[dict]: ...
```

---

## 11. 개발 방법론

### 11.1 TDD (Red → Green → Refactor)
1. 실패하는 테스트 작성 (Red)
2. 테스트 통과하는 최소 구현 (Green)
3. 리팩토링
4. 다음 테스트 → 반복

### 11.2 테스트 구조
- 모듈별 독립 테스트 (`engine/tests/`, `crawlers/.../tests/`)
- 전역 fixture (`conftest.py`)
- VCR 카세트로 API 응답 녹화/재생 (네트워크 불필요)
- `pytest.ini`로 테스트 경로 및 마커 설정

### 11.3 실행 명령
```bash
# 전체 테스트
python -m pytest tests/ engine/tests/ -v --tb=short

# 특정 모듈만
python -m pytest engine/tests/test_executor.py -v

# CLI
python main.py server          # API 서버
python main.py crawl emart     # 이마트 크롤링
python main.py list            # 크롤러 목록
python main.py init-db         # DB 초기화
```

---

## 12. 핵심 설계 결정 기록

| 결정 | 이유 |
|---|---|
| PostgreSQL ≠ SQLite | 동시접속, 이미지 메타 누적, 실서비스 수준 |
| 이미지 파일시스템 저장 | DB BLOB 비대화 방지, S3 전환 대비 |
| 5단계 전략 cascade | 어떤 방식으로 막혀도 대안 자동 시도 |
| 모듈 완전 분리 | 기획 뒤엎어도 프로젝트 안 무너짐 |
| EventBus | 모듈 간 느슨한 결합 (서로 존재 모름) |
| 플러그인 레지스트리 | 크롤러 추가 = 폴더 추가, 코드 변경 0 |
| TDD | 리그레션 방지, CI 가능 |
| 크롤러 = 독립 앱 | 부가 기능 아닌 완성도 높은 별도 프로그램 |
| **기준가격 DB 분리** | 핫딜/바이럴 가격이 평균을 오염시키지 않도록 |
| **정부+마트전단 기준** | 오염 불가능한 공식/전단가만으로 baseline 구축 |

---

## 13. 유의사항 & TODO

- [ ] data.go.kr에서 KAMIS, OPINET, KOSIS API 키 발급
- [ ] PostgreSQL 로컬 설치 및 DB 생성
- [ ] `pip install -r requirements.txt` (전체 의존성 설치)
- [ ] 크롤러 대상 사이트들의 `robots.txt` 확인
- [ ] 대형마트 사이트 구조 분석 (CSS 셀렉터 확정)
