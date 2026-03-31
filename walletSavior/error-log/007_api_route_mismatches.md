# API Route Mismatches — 전체 3프로젝트 (2025-07-15)

## 증상
브라우저 콘솔에 모든 API 호출이 404/500으로 실패. 3개 프로젝트 전부 데이터 로드 불가.

## 근본 원인

### 1. DB-Admin 404 (`/api/products`, `/api/analytics/summary`)
- **원인**: `app.py`에서 라우터 등록 시 `prefix="/api"` 누락
- 라우터 파일은 `prefix="/products"` 등으로 정의됐지만, `app.py`가 그냥 `include_router(router)` → 최종 경로 `/products/`
- 프론트엔드 client.js는 `/api/products`로 호출 → 404
- **해결**: `app.include_router(router, prefix="/api")` 추가 (ingestion 제외 — 이미 `/api/ingestions` prefix 있음)

### 2. DB-Admin 500 (`/api/ingestions/stats`, `/api/ingestions?status=...`)
- **원인**: `config.py`의 `DATABASE_URL` 기본값이 `postgresql://localhost/walletguardian`
- PostgreSQL 미설치 → connection refused → 500
- **해결**: 기본값을 `sqlite:///{BASE_DIR}/walletguardian.db`로 변경

### 3. DB-Admin analytics/summary 500
- **원인**: `export.py`의 avg_baseline 쿼리에서 `.select_from(BaselinePrice)` 누락
- SQLAlchemy가 단독 aggregate 쿼리의 대상 테이블을 추론 못함
- **해결**: `.select_from(BaselinePrice)` 추가

### 4. Website MartPage 404
- **원인**: 프론트엔드가 `/api/marts/${key}/deals` 호출하지만 백엔드 경로는 `/promotions`
- **해결**: 프론트엔드의 `/deals` → `/promotions` 변경

### 5. Website marts/lotte 404
- **원인**: 프론트엔드 MARTS 배열에서 `key: 'lotte'`, DB에서 `source: 'lottemart'`
- **해결**: `marts.py`에 `_STORE_ALIAS = {"lotte": "lottemart"}` 매핑 추가

### 6. Website productService /prices 404
- **원인**: 프론트엔드가 `/api/products/{id}/prices` 호출, 백엔드는 `/price-history`
- **해결**: 프론트엔드 경로 `/prices` → `/price-history` 변경

### 7. Website 누락 엔드포인트
- **원인**: 프론트엔드가 `/categories`, `/popular`, `/vote`, `/report` 호출하지만 백엔드에 없음
- **해결**: `products.py`에 `/categories`, `/popular` 추가, `hotdeals.py`에 `/categories`, `/{id}/vote`, `/{id}/report` 추가
- **주의**: `/categories`, `/popular`는 반드시 `/{product_id}` 앞에 정의해야 함 (FastAPI가 "categories"를 int로 파싱 시도)

### 8. Crawler-Admin 500
- **원인**: PYTHONPATH에 shared 모듈 경로 미포함, 또는 포트에 orphaned socket
- **해결**: `start.ps1`에 PYTHONPATH 설정 추가, `start-all.ps1`에 sqlalchemy/pyyaml 의존성 추가

## 교훈
1. **프론트엔드-백엔드 API 경로는 계약 문서(API_CONTRACTS.md)와 대조 검증 필수**
2. **라우터 prefix 아키텍처 결정을 문서화**: "prefix는 어디서 붙이는가?" (라우터 파일 vs app.py)
3. **DB 기본 설정은 개발 환경에 맞추기**: PostgreSQL 필수가 아니면 SQLite 기본
4. **Windows orphaned socket**: 프로세스 종료 후에도 포트가 잠길 수 있음. 대체 포트 사용 필요
5. **FastAPI 라우트 순서 중요**: 정적 경로(`/categories`)가 동적 경로(`/{id}`) 앞에 와야 함

## 수정 파일
- `packages/db-admin/backend/config.py`
- `packages/db-admin/backend/api/app.py`
- `packages/db-admin/backend/services/export.py`
- `packages/website/backend/api/routes/products.py`
- `packages/website/backend/api/routes/hotdeals.py`
- `packages/website/backend/api/routes/marts.py`
- `packages/website/frontend/src/pages/Home/HomePage.jsx`
- `packages/website/frontend/src/pages/Mart/MartPage.jsx`
- `packages/website/frontend/src/services/productService.js`
- `start.ps1`
- `start-all.ps1`
