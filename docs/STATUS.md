# STATUS.md — 프로젝트 현황판

> **이 문서의 목적**: AI가 "지금 뭐가 되어있고, 다음에 뭘 해야 하는지" 즉시 파악.
> 작업 완료/착수 시 반드시 이 문서를 업데이트할 것.
>
> **마지막 업데이트**: 2026-03-25

---

## 1. Phase별 진행 상황

| Phase | 내용 | 상태 | 테스트 수 | 비고 |
|-------|------|------|-----------|------|
| **1** | Core 아키텍처 | ✅ **완료** | 36개 | contracts, models, events, exceptions, DI, CLI |
| **2** | 크롤링 엔진 | ✅ **완료** | 28개 | 5-전략 executor, diagnostics, anti-detect |
| **3** | 공공 API 크롤러 | ❌ 미착수 | 0 | KAMIS, OPINET, KOSIS — API 키 미발급 |
| **4** | 마트 크롤러 | ❌ 미착수 | 0 | 이마트, 홈플러스, 롯데마트, 코스트코 |
| **5** | 핫딜 크롤러 | 🔄 진행중 | — | 알구몬, 코코달인 작동 확인 / 아카, FM코리아 미착수 |
| **6** | 배달/식당 크롤러 | ❌ 미착수 | 0 | 배달의민족, 요기요, 쿠팡이츠, 네이버 플레이스 |
| **7** | 백엔드 (FastAPI + 스케줄러) | ❌ 미착수 | 0 | API 라우트, WebSocket, APScheduler |
| **8** | 프론트엔드 | 🔄 진행중 | — | 바닐라 프로토타입 완료, React 마이그레이션 착수 |
| **9** | 통합/회귀 테스트 + CI/CD | ❌ 미착수 | 0 | |

**전체 테스트**: 64개 (실행시간 ~0.20s)

---

## 2. 모듈별 상세 현황

### 2.1 core/ — ✅ 완료

| 파일 | 상태 | 설명 |
|------|------|------|
| `contracts/crawler.py` | ✅ 완료 | CrawlerContract (crawl, parse, validate, setup, teardown) |
| `contracts/engine.py` | ✅ 완료 | EngineContract + StrategyContract |
| `contracts/scheduler.py` | ✅ 완료 | SchedulerContract (add/remove/list/pause/resume) |
| `contracts/storage.py` | ✅ 완료 | StorageContract + FileStorageContract |
| `models.py` | ✅ 완료 | 10개 모델 (CrawlResult, ProductPrice, DiscountItem, HotdealPost 등) |
| `events.py` | ✅ 완료 | EventBus + 10개 이벤트 타입 상수 |
| `exceptions.py` | ✅ 완료 | 7개 예외 클래스 (CrawlError, CrawlerBlockedError 등) |
| `categories.py` | ✅ 완료 | CategoryTree + ProductAttribute + 기본 트리 |
| `statistics.py` | ✅ 완료 | IQR, SMA, EMA, 등급판정, 계절성 비교 |
| `verification.py` | ✅ 완료 | 커뮤니티 가격 검증 (verified/great_deal/suspicious) |
| `recipe.py` | ✅ 완료 | 레시피 비용 계산기 + 기본 레시피 5개 |

### 2.2 engine/ — ✅ 완료

| 파일 | 상태 | 테스트 |
|------|------|--------|
| `executor.py` | ✅ 완료 | ✅ |
| `diagnostics.py` | ✅ 완료 | ✅ |
| `anti_detect.py` | ✅ 완료 | ✅ |
| `strategies/base.py` | ✅ 완료 | ✅ |
| `strategies/requests_st.py` | ✅ 완료 | ✅ |
| `strategies/cloudscraper_st.py` | ✅ 완료 | ✅ |
| `strategies/selenium_st.py` | ✅ 완료 | ✅ |
| `strategies/undetected_st.py` | ✅ 완료 | ✅ |
| `strategies/playwright_st.py` | ✅ 완료 | ✅ |

### 2.3 crawlers/ — 🔄 일부 진행

| 크롤러 | 그룹 | 상태 | 비고 |
|--------|------|------|------|
| 알구몬 | hotdeals | ✅ 작동 확인 | `crawlers/hotdeals/algumon/` |
| 코코달인 | marts | ✅ 작동 확인 | API 엔드포인트 발견하여 직접 호출 |
| KAMIS | public | ❌ 미착수 | API 키 발급 필요 |
| OPINET | public | ❌ 미착수 | API 키 발급 필요 |
| KOSIS | public | ❌ 미착수 | API 키 발급 필요 |
| 이마트 | marts | ❌ 미착수 | |
| 홈플러스 | marts | ❌ 미착수 | |
| 롯데마트 | marts | ❌ 미착수 | |
| 코스트코 | marts | ❌ 미착수 | |
| 아카라이브 | hotdeals | ❌ 미착수 | |
| FM코리아 | hotdeals | ❌ 미착수 | |
| 배달의민족 | food | ❌ 미착수 | |
| 요기요 | food | ❌ 미착수 | |
| 쿠팡이츠 | food | ❌ 미착수 | |

### 2.4 storage/ — ❌ 미착수

| 항목 | 상태 |
|------|------|
| PostgreSQL 연결 | ❌ |
| SQLAlchemy 모델 정의 | ❌ |
| Alembic 마이그레이션 | ❌ |
| StorageContract 구현 | ❌ |
| FileStorageContract 구현 | ❌ |
| 이미지 WebP 변환 | ❌ |
| 썸네일 생성 | ❌ |

### 2.5 api/ — ❌ 미착수

| 항목 | 상태 |
|------|------|
| FastAPI 앱 초기화 | ❌ |
| 가격 관련 라우트 | ❌ |
| 할인 관련 라우트 | ❌ |
| 핫딜 관련 라우트 | ❌ |
| 레시피 관련 라우트 | ❌ |
| 크롤러 관리 라우트 | ❌ |
| WebSocket 대시보드 | ❌ |

### 2.6 scheduler/ — ❌ 미착수

| 항목 | 상태 |
|------|------|
| APScheduler 래핑 | ❌ |
| SchedulerContract 구현 | ❌ |
| cron 표현식 파싱 | ❌ |

### 2.7 frontend-react/ — 🔄 초기 단계

| 항목 | 상태 | 비고 |
|------|------|------|
| Vite + React 프로젝트 초기화 | ✅ 완료 | |
| 디자인 토큰 (tokens.css) 이식 | ✅ 완료 | 바닐라에서 포팅 |
| 목 데이터 (mockData.js) | ✅ 완료 | ES Module 형식 |
| 공통 컴포넌트 (Button, Card 등) | ❌ 미착수 | |
| 홈 페이지 | ❌ 미착수 | |
| 가격 비교 페이지 | ❌ 미착수 | |
| 할인 모아보기 페이지 | ❌ 미착수 | |
| 핫딜 페이지 | ❌ 미착수 | |
| 레시피 비용 비교 페이지 | ❌ 미착수 | |
| 대시보드 (관리자) | ❌ 미착수 | |

### 2.8 인프라/기타

| 항목 | 상태 |
|------|------|
| `.env.example` | ✅ 완료 |
| `config.py` | ✅ 완료 |
| `container.py` | ✅ 스켈레톤 (Phase별 구현 예정) |
| `main.py` CLI | ✅ 스켈레톤 (명령어 매핑 완료) |
| `pytest.ini` | ✅ 완료 |
| `requirements.txt` | ✅ 완료 |
| Git 설정 | ✅ .gitignore 완료 |
| CI/CD | ❌ 미설정 |
| Docker | ❌ 미설정 |

---

## 3. 외부 의존 & 블로커

| 항목 | 상태 | 블로킹 대상 |
|------|------|-------------|
| KAMIS API 키 발급 | ❌ 미발급 | Phase 3 (공공 API 크롤러) |
| OPINET API 키 발급 | ❌ 미발급 | Phase 3 |
| KOSIS API 키 발급 | ❌ 미발급 | Phase 3 |
| Naver API 키 발급 | ❌ 미발급 | 네이버 플레이스 연동 |
| PostgreSQL 설치/설정 | ❌ 미설정 | Phase 3+ (storage 모듈) |
| Chrome/Chromedriver | ✅ 로컬 설치됨 | — |
| Node.js | ✅ 설치됨 | frontend-react 빌드 |

---

## 4. 다음 우선순위 작업

> 현재 시점에서 추천하는 작업 순서:

### 즉시 가능 (블로커 없음)

1. **Storage 모듈 구현** — PostgreSQL 설정 + SQLAlchemy 모델 + Alembic
2. **React 프론트엔드 진행** — 공통 컴포넌트 → 홈 → 가격 비교 페이지
3. **container.py 실제 연결** — 완성된 모듈들을 DI 컨테이너에 조립

### API 키 필요

4. **KAMIS 크롤러** — API 키 발급 후 즉시 착수 (baseline 데이터의 핵심)
5. **OPINET 크롤러** — 주유소 가격
6. **KOSIS 크롤러** — 물가지수

### 이후

7. **마트 크롤러** (이마트, 홈플러스, 롯데마트, 코스트코)
8. **FastAPI 백엔드** — API 라우트 + WebSocket
9. **APScheduler 연동** — 자동 크롤링 스케줄
10. **통합 테스트** — 전체 파이프라인 검증

---

## 5. 알려진 이슈 & 기술 부채

| # | 이슈 | 심각도 | 관련 파일 |
|---|------|--------|-----------|
| 1 | container.py의 모든 `_init_*` 메서드가 TODO 상태 | 중 | `container.py` |
| 2 | main.py CLI 명령어 모두 스켈레톤 | 중 | `main.py` |
| 3 | 프록시 설정이 비어있음 | 저 | `.env` |
| 4 | 바닐라 frontend/와 React frontend-react/ 공존 | 저 | 마이그레이션 완료 후 제거 |
| 5 | 이미지 처리 파이프라인 미구현 | 중 | storage/ |

---

## 6. 문서 현황

| 문서 | 역할 | 상태 | 최종 업데이트 |
|------|------|------|--------------|
| `AI_GUIDE.md` | AI 작업 규칙 + 문서 관리 + Git + 자율 판단 | ✅ 최신 | 2026-03-25 |
| `STATUS.md` | 실시간 현황판 (가장 자주 갱신) | ✅ 최신 | 2026-03-25 |
| `INVARIANTS.md` | 불변 제약 vs 가변 영역 | ✅ 최신 | 2026-03-25 |
| `DECISIONS.md` | AI 자율 결정 추적 (사람 리뷰용) | ✅ 최신 | 2026-03-25 (2건) |
| `TECH_SPEC.md` | 전체 프로젝트 설계 청사진 | ✅ 최신 | 2026-03-18 |
| `ARCHITECTURE.md` | 모듈 의존성, 데이터 흐름, DB, API | ✅ 최신 | 2026-03-25 |
| `DEV_PHILOSOPHY.md` | 11가지 개발 철학 | ✅ 최신 | 2026-03-18 |
| `TECH_DECISIONS.md` | 기술 스택 선택 근거 | ✅ 최신 | 2026-03-25 |
| `GLOSSARY.md` | 도메인 용어 사전 | ✅ 최신 | 2026-03-25 |
| `ERROR_LOG.md` | 오류 발생/해결 이력 | ✅ 최신 | 2026-03-18 (5건) |
| `devlog/001_*.md` | React 마이그레이션 시작 | ✅ | 2026-03-25 |
| `devlog/002_*.md` | 상품 전략 & 데이터 아키텍처 | ✅ | 2026-03-25 |
