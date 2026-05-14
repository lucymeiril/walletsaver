# 🛡️ 지갑 지키미 (WalletSavior)

> **정부 공식 물가 데이터 기반 핫딜 가격 비교 플랫폼**
>
> 정부 공공데이터(KAMIS, KOSIS, OPINET)와 대형마트 세일 정보를 수집·분석하여
> 사용자에게 객관적인 가격 판단 기준을 제공합니다.

---

## 📌 프로젝트 소개

"이 가격이 정말 싼 걸까?" — 지갑 지키미는 이 질문에 **데이터로 답합니다.**

- 🔥 **핫딜 검증** — 커뮤니티 핫딜을 정부 데이터 기반 적정가와 자동 비교
- 📊 **가격 추이** — 30일/90일/365일 가격 차트로 구매 타이밍 판단
- 🏬 **마트 세일** — 이마트·홈플러스·롯데마트 세일 한눈에 비교
- ⛽ **주변 최저가** — 주유소·식당 가격 비교, 직접 해먹기 vs 외식 비용 분석
- 💬 **커뮤니티** — 핫딜 공유 및 가격 검증 시스템

---

## ⚡ 빠른 시작

### 사전 요구사항

- **Node.js** 18+ ([다운로드](https://nodejs.org/))
- **Python** 3.11+ (Windows: `py` 명령어로 실행)
- **Git**

### 설치 및 실행

```powershell
# 1. 저장소 클론
git clone https://github.com/lucymeiril/walletSavior.git
cd walletSavior

# 2. 프론트엔드 의존성 설치
npm install --prefix packages/website/frontend

# 3. 백엔드 의존성 설치
py -m pip install fastapi uvicorn sqlalchemy

# 4. 실행 (프론트엔드 + 백엔드 동시 시작)
./start.ps1
```

> 💡 `start.ps1`이 의존성 설치를 자동으로 확인하므로, 3단계부터 바로 실행해도 됩니다.

### 브라우저에서 확인

| 서비스 | URL | 설명 |
|--------|-----|------|
| 🌐 웹사이트 | http://localhost:5173 | 사용자 메인 화면 |
| 📡 API 문서 | http://localhost:8000/docs | Swagger UI |
| ❤️ 헬스체크 | http://localhost:8000/api/health | 서버 상태 확인 |

### CMD 사용자

```cmd
start.bat
```

---

## 🏗️ 프로젝트 구조

```
walletSavior/
├── packages/
│   ├── shared/              # 공유 모듈 (models, contracts, utils)
│   ├── website/             # 👤 사용자 웹사이트
│   │   ├── frontend/        #   React + Vite (port 5173)
│   │   └── backend/         #   FastAPI (port 8000)
│   ├── crawler-admin/       # 🕷️ 크롤러 관리 (서버 전용)
│   │   ├── frontend/        #   React + Vite (port 5174)
│   │   └── backend/         #   FastAPI (port 8001)
│   ├── ai-admin/            # 🤖 AI 검토/매칭 관리 (서버 전용)
│   │   ├── frontend/        #   React + Vite
│   │   └── backend/         #   FastAPI (port 8003)
│   └── db-admin/            # 🗄️ DB 관리 (서버 전용)
│       ├── frontend/        #   React + Vite (port 5175)
│       └── backend/         #   FastAPI (port 8002)
├── docs/                    # 📖 문서 (아키텍처, API 명세, 가이드 등)
├── start.ps1                # ▶️  웹사이트 실행
├── start-admin.ps1          # 🔧 관리 도구 실행
├── start.bat                # ▶️  웹사이트 실행 (cmd용)
├── stop.ps1                 # ⏹️  모든 서버 종료
└── run_all_tests.py         # 🧪 전체 테스트 (1,330개)
```

### 패키지별 역할

| 패키지 | 용도 | 사용자 |
|--------|------|--------|
| `website` | 핫딜·가격비교·마트세일 웹사이트 | 일반 사용자 |
| `crawler-admin` | 크롤러 실행·스케줄·로그 관리 | 개발자 (서버 전용) |
| `ai-admin` | AI 라벨링·상품 매칭·검토 제안 관리 | 개발자 (서버 전용) |
| `db-admin` | 상품·가격·카테고리 데이터 관리 | 개발자 (서버 전용) |
| `shared` | 공통 모델·유틸리티·계약 | 내부 공유 |

> ⚠️ **crawler-admin**, **ai-admin**, **db-admin**은 서버에서만 실행하는 내부 관리 도구입니다.
> 사용자에게 배포하지 않습니다.

---

## 🔄 시스템 연동 흐름

```
┌───────────────┐  원본 수집  ┌────────────┐  검토/매칭  ┌────────────┐
│ crawler-admin │ ─────────→ │  ai-admin  │ ─────────→ │  db-admin  │
└───────────────┘            └────────────┘            └─────┬──────┘
                                                             │
                                                        공개 DB 저장
                                                             │
                                                     ┌───────▼───────┐
                                                     │ website/API/UI │
                                                     └───────┬───────┘
                                                             │
                                                        🧑 일반 사용자
```

1. **crawler-admin**이 정부 공공데이터·마트 세일·커뮤니티 핫딜을 수집
2. **ai-admin**이 원본을 보존한 채 상품 매칭·카테고리·키워드·단위 후보를 검토
3. **db-admin**이 승인된 데이터만 공개 DB의 상품/가격/행사 이력으로 저장
4. **website**가 사용자에게 가격 비교·핫딜 정보를 표시

---

## 🧪 테스트

```powershell
# 전체 테스트 실행 (1,330개)
py run_all_tests.py

# 개별 패키지 테스트
cd packages/website/backend && py -m pytest tests/
cd packages/crawler-admin/backend && py -m pytest tests/
cd packages/ai-admin/backend && py -m pytest tests/
cd packages/db-admin/backend && py -m pytest tests/

# 프론트엔드 테스트
cd packages/website/frontend && npm test
cd packages/crawler-admin/frontend && npm test
cd packages/ai-admin/frontend && npm test
cd packages/db-admin/frontend && npm test
```

---

## 📦 기술 스택

### 프론트엔드
- **React** 18 / 19 — UI 라이브러리
- **Vite** — 빌드 도구 (HMR 지원)
- **Zustand** — 상태 관리
- **Recharts** — 가격 추이 차트
- **React Router** — SPA 라우팅
- **CSS Modules** — 스타일 격리
- **Vitest** — 프론트엔드 테스트

### 백엔드
- **Python** 3.11+ — 메인 언어
- **FastAPI** — API 프레임워크
- **Uvicorn** — ASGI 서버
- **SQLAlchemy** 2.0 — ORM
- **Alembic** — DB 마이그레이션
- **Pydantic** 2.0 — 데이터 검증

### 데이터베이스
- **PostgreSQL** 16 — 프로덕션
- **SQLite** — 개발/테스트

### 크롤링
- **requests** / **httpx** — HTTP 클라이언트
- **BeautifulSoup4** — HTML 파싱
- **cloudscraper** — Cloudflare 우회
- **Selenium** / **Playwright** — 브라우저 자동화
- **APScheduler** — 크롤링 스케줄러

---

## 🔧 개발 가이드

### 웹사이트 개발

```powershell
# 프론트엔드만 실행
cd packages/website/frontend
npm run dev                    # http://localhost:5173

# 백엔드만 실행
cd packages/website/backend
py -m uvicorn api.app:create_app --factory --reload --port 8000

# 프론트+백엔드 동시 실행
./start.ps1
```

### 관리 도구 개발

```powershell
# 크롤러 관리 + AI 관리 + DB 관리 동시 실행
./start-admin.ps1

# 또는 개별 실행
cd packages/crawler-admin/backend
py -m uvicorn api.app:create_app --factory --reload --port 8001

cd packages/ai-admin/backend
py -m uvicorn api.app:create_app --factory --reload --port 8003

cd packages/db-admin/backend
py -m uvicorn api.app:create_app --factory --reload --port 8002
```

### API 엔드포인트 추가하기

1. `packages/<패키지>/backend/api/routes/`에 라우터 파일 생성
2. `api/app.py`에서 라우터 등록
3. 테스트 작성: `packages/<패키지>/backend/tests/`

### 크롤러 추가하기

1. `packages/crawler-admin/backend/crawlers/`에 크롤러 모듈 생성
2. 크롤러 관리 UI에서 등록 및 스케줄 설정
3. `packages/crawler-admin/backend/tests/`에 테스트 작성

---

## 📋 명령어 모음

| 명령어 | 설명 |
|--------|------|
| `./start.ps1` | 웹사이트 실행 (프론트+백엔드) |
| `./start-admin.ps1` | 관리 도구 실행 (크롤러+DB) |
| `./stop.ps1` | 실행 중인 모든 서버 종료 |
| `start.bat` | 웹사이트 실행 (cmd용) |
| `py run_all_tests.py` | 전체 테스트 (1,330개) |
| `npm run dev` | 프론트엔드 개발 서버 |
| `py -m uvicorn ...` | 백엔드 개발 서버 |
| `py -m pytest tests/` | 개별 패키지 테스트 |

---

## 🔒 보안 참고

- **크롤러 관리**, **DB 관리** 앱은 서버에서만 실행하며 외부에 배포하지 않습니다
- **AI 관리(ai-admin)** 앱도 내부 운영 도구이며 외부에 배포하지 않습니다
- 사용자는 웹사이트를 통해 DB의 가격 데이터만 조회합니다
- JWT 시크릿 키는 환경변수(`SECRET_KEY`)로 관리하세요
- `.env`, `.env.local`, SQLite DB, 백업 DB, 로그, live validation artifact는 커밋하지 마세요
- CORS는 개발 서버(`localhost`) 전용으로 설정되어 있습니다
- 프로덕션 배포 시 CORS origin을 실제 도메인으로 변경하세요

---

## 📖 문서

| 문서 | 내용 |
|------|------|
| [USER_GUIDE.md](docs/USER_GUIDE.md) | 사용자 가이드 (기능별 사용법) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 시스템 아키텍처 |
| [API_CONTRACTS.md](docs/API_CONTRACTS.md) | API 명세 |
| [TECH_SPEC.md](docs/TECH_SPEC.md) | 기술 명세서 |
| [DEV_PHILOSOPHY.md](docs/DEV_PHILOSOPHY.md) | 개발 철학 |
| [AI_HANDOFF.md](docs/AI_HANDOFF.md) | 다음 AI/개발자용 최신 인수인계 |
| [CURRENT_STATUS.md](docs/CURRENT_STATUS.md) | 현재 AI/DB 정규화 상태와 검증 명령 |

---

<div align="center">

**🛡️ 지갑 지키미 — 데이터로 지키는 당신의 지갑**

</div>
