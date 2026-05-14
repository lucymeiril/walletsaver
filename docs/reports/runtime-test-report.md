# WalletSavior 런타임 테스트 리포트

## 1. 테스트 요약

| 프로젝트 | 단위 테스트(pytest) | 런타임 API | 프론트엔드 빌드 | 요약 |
|---|---|---|---|---|
| Website | **201 passed / 1 failed** | **17 pass / 3 fail / 0 blocked** | **PASS** | 기능 대부분 동작, 라우트 불일치와 회귀 1건 확인 |
| DB-admin | **307 passed / 0 failed** | **0 pass / 2 fail / 14 blocked** | **PASS** | 테스트 스위트는 안정적이나, 실서버 인증/헬스 경로 불일치로 API 검증 실패 |
| Crawler-admin | **완주 실패(수집 단계에서 hang)** | **2 pass / 0 fail / 5 blocked** | **PASS(경고 1건)** | 인증 없는 헬스체크만 확인, 보호 API는 키 부재로 검증 불가 |

> 비고
> - Website 인증 테스트는 랜덤 이메일 신규 가입 후 JWT로 검증했습니다.
> - DB-admin은 제공된 `admin@walletsavior.com / admin123` 로그인 실패로 보호 API 검증이 막혔습니다.
> - Crawler-admin은 `X-API-Key`가 없어 보호 API는 401 확인까지만 수행했습니다.

## 2. 단위 테스트 결과

| 프로젝트 | 실행 명령 | 결과 |
|---|---|---|
| DB-admin backend | `py -m pytest tests/ -q --tb=short` | **307 passed, 555 warnings, 17.35s** |
| Website backend | `py -m pytest tests/ -q --tb=short` | **1 failed, 201 passed, 51 warnings, 21.58s** |
| Crawler-admin backend | `py -m pytest tests/ -q --tb=short` | **실패(완주 불가)** — pytest session start 출력 후 110초 이상 진행 없음, 수동 중단 |

### Website 실패 상세

- 실패 테스트: `tests/test_api_routes.py::TestProducts::test_price_history`
- 실패 메시지: `assert body["success"] is True` → 실제 값 `False`

### 주요 경고

- DB-admin: `datetime.utcnow()` DeprecationWarning 다수
- Website: Pydantic V2 설정 관련 deprecation warning, `datetime.utcnow()` 경고
- Crawler-admin: pytest 자체가 완료되지 않아 전체 결과 미확인

## 3. 런타임 API 테스트 결과

### 3-1. Website API (`http://127.0.0.1:8000`)

| 메서드 | 엔드포인트 | 상태 | 결과 | 비고 |
|---|---|---:|---|---|
| GET | `/api/health` | 200 | PASS | 헬스 응답 정상 |
| GET | `/api/products/prices` | 422 | FAIL | `product_id` 검증 오류. `/api/products/{product_id}` 라우트와 충돌하는 것으로 보임 |
| GET | `/api/hotdeals` | 200 | PASS | `success/data` 구조 확인, `id=20` 확보 |
| POST | `/api/hotdeals/20/vote` | 200 | PASS | `votes_hot/votes_not` 응답 확인 |
| GET | `/api/hotdeals/20/comments` | 200 | PASS | 빈 배열 포함 정상 |
| POST | `/api/hotdeals/20/comments` | 200 | PASS | 댓글 생성 성공, 응답에 생성된 comment id 포함 |
| GET | `/api/posts?post_type=hotdeal` | 200 | PASS | hotdeal 필터 정상 |
| GET | `/api/posts?post_type=free` | 200 | PASS | free 필터 정상 |
| POST | `/api/posts` | 401 → 200 | PASS | 무인증 401, JWT 인증 후 게시글 생성 성공 |
| GET | `/api/search?q=사과` | 200 | PASS | 검색 JSON 정상 |
| GET | `/api/search/autocomplete?q=사` | 200 | PASS | 자동완성 JSON 정상 |
| POST | `/api/auth/register` | 201 | PASS | `access_token`, `refresh_token` 반환 |
| POST | `/api/auth/login` | 200 | PASS | JWT 발급 확인 |
| GET | `/api/auth/me` | 200 | PASS | 사용자 프로필 객체 반환 |
| GET | `/api/users/me` | 200 | PASS | `success/data` 구조 정상 |
| PUT | `/api/users/me` | 200 | PASS | 닉네임 수정 성공 |
| GET | `/api/crawlers` | 200 | PASS | 크롤러 상태 목록 반환 |
| GET | `/api/marts` | 200 | PASS | 마트 데이터 JSON 정상 |
| GET | `/api/restaurants?lat=37.5665&lng=126.978` | 404 | FAIL | 실제 구현 라우트는 `/api/restaurants/nearby` |
| GET | `/api/gas-stations?lat=37.5665&lng=126.978` | 404 | FAIL | 실제 구현 라우트는 `/api/gas/nearby` |

#### 추가 확인(실제 구현 라우트)

| 엔드포인트 | 상태 | 결과 | 비고 |
|---|---:|---|---|
| `/api/products/category-summary` | 200 | 참고 | 홈페이지 “오늘의 물가” 실제 데이터 경로로 보임 |
| `/api/restaurants/nearby?lat=37.5665&lng=126.978` | 200 | 참고 | 요청한 `/api/restaurants` 대신 이 경로가 동작 |
| `/api/gas/nearby?lat=37.5665&lng=126.978` | 200 | 참고 | 요청한 `/api/gas-stations` 대신 이 경로가 동작 |

### 3-2. DB-admin API (`http://127.0.0.1:8002`)

| 메서드 | 엔드포인트 | 상태 | 결과 | 비고 |
|---|---|---:|---|---|
| POST | `/api/auth/login` | 401 | FAIL | 제공된 관리자 계정으로 로그인 실패 (`이메일 또는 비밀번호가 올바르지 않습니다.`) |
| GET | `/api/health` | 404 | FAIL | 요청 경로 없음. 실제로는 `/health` 가 200 응답 |
| GET | `/api/products/` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/products/stats` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/categories/` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/keywords/` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/keywords/stats` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/keywords/popular` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/dashboard/stats` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/prices/stats` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/prices/tier-config` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/analytics/summary` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/analytics/quality-report` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/ingestions?status=pending` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/ingestions/stats` | 401 | BLOCKED | 인증 필요 |
| GET | `/api/admin/data-summary` | 401 | BLOCKED | 인증 필요 |

#### 추가 확인

| 엔드포인트 | 상태 | 결과 | 비고 |
|---|---:|---|---|
| `/health` | 200 | 참고 | `status`, `service`, `checks` 구조 정상 |

### 3-3. Crawler-admin API (`http://127.0.0.1:8001`)

| 메서드 | 엔드포인트 | 상태 | 결과 | 비고 |
|---|---|---:|---|---|
| GET | `/health` | 200 | PASS | `status/service/scheduler_running` 구조 정상 |
| GET | `/api/crawlers` (without key) | 401 | PASS | `Missing X-API-Key header` 확인 |
| GET | `/api/dashboard/stats` | 401 | BLOCKED | API 키 필요 |
| GET | `/api/logs?page=1&per_page=10` | 401 | BLOCKED | API 키 필요 |
| GET | `/api/schedules` | 401 | BLOCKED | API 키 필요 |
| GET | `/api/plugins` | 401 | BLOCKED | API 키 필요 |
| GET | `/api/ingestions?status=pending` | 401 | BLOCKED | API 키 필요 |

## 4. 프론트엔드 빌드 결과

| 프로젝트 | 명령 | 결과 | 비고 |
|---|---|---|---|
| Website frontend | `npm run build` | PASS | Vite production build 성공 (`✓ built in 9.29s`) |
| Crawler-admin frontend | `npm run build` | PASS | 빌드 성공 (`✓ built in 824ms`), 단 `index-JMthCUkL.js 683.24 kB` chunk size warning 존재 |
| DB-admin frontend | `npm run build` | PASS | 빌드 성공 (`✓ built in 836ms`) |

## 5. 발견된 문제

1. **Website pytest 회귀**
   - `tests/test_api_routes.py::TestProducts::test_price_history` 실패.

2. **Website API 계약 불일치**
   - `/api/products/prices` 호출 시 422 발생.
   - 코드상 “오늘의 물가”에 가까운 구현은 `/api/products/category-summary`.
   - `/api/products/{product_id}` 동적 라우트가 `prices` 문자열을 먼저 잡는 구조로 보임.

3. **Website 위치 기반 API 경로 불일치**
   - 요청된 `/api/restaurants` 는 404.
   - 실제 구현 라우트는 `/api/restaurants/nearby`.
   - 요청된 `/api/gas-stations` 는 404.
   - 실제 구현 라우트는 `/api/gas/nearby`.

4. **Website 커뮤니티 작성 API는 인증 필요**
   - 무인증 POST `/api/posts` 는 401.
   - JWT 포함 시 200으로 정상 동작.
   - API 명세/QA 시나리오에 인증 요구사항 명시 필요.

5. **DB-admin 헬스체크 경로 불일치**
   - 요청된 `/api/health` 는 404.
   - 실제 `/health` 는 200.

6. **DB-admin 기본 관리자 계정 미동작**
   - 제공된 `admin@walletsavior.com / admin123` 로그인 실패.
   - 그 결과 보호 API 14개는 라이브 검증이 막힘.

7. **Crawler-admin 라이브 API 검증 제한**
   - `X-API-Key` 없이는 보호 API 전체가 401.
   - 실제 `.env.example` 에서도 `CRAWLER_ADMIN_API_KEY` 설정이 필수로 정의됨.

8. **Crawler-admin pytest 스위트 hang**
   - pytest 세션 시작 직후 진행률이 전혀 출력되지 않았고, 110초 이상 정지 상태.
   - 회귀 테스트 자동화 안정성 문제로 판단.

9. **Crawler-admin 프론트 번들 크기 경고**
   - Vite가 `500 kB` 초과 chunk 경고 출력.
   - 기능 실패는 아니지만 성능/배포 품질 이슈 후보.

## 6. 리그레션 체크리스트

### Website

#### 기존 pytest
- [ ] `packages\website\backend\tests\test_api_routes.py`
- [ ] `packages\website\backend\tests\test_auth.py`
- [ ] `packages\website\backend\tests\test_health.py`
- [ ] `packages\website\backend\tests\test_naver_scraping.py`
- [ ] `packages\website\backend\tests\test_sanitize.py`
- [ ] `packages\website\backend\tests\test_sse_disconnect.py`
- [ ] `packages\website\backend\tests\test_storage_proxy.py`

#### 런타임 API
- [ ] `GET /api/health`
- [ ] `GET /api/products/prices` 또는 실제 대체 경로(`/api/products/category-summary`) 계약 검증
- [ ] `GET /api/hotdeals`
- [ ] `POST /api/hotdeals/{id}/vote`
- [ ] `GET /api/hotdeals/{id}/comments`
- [ ] `POST /api/hotdeals/{id}/comments`
- [ ] `GET /api/posts?post_type=hotdeal`
- [ ] `GET /api/posts?post_type=free`
- [ ] `POST /api/posts` (무인증 401 + 인증 후 생성 성공 둘 다 확인)
- [ ] `GET /api/search?q=사과`
- [ ] `GET /api/search/autocomplete?q=사`
- [ ] `POST /api/auth/register`
- [ ] `POST /api/auth/login`
- [ ] `GET /api/auth/me`
- [ ] `GET /api/users/me`
- [ ] `PUT /api/users/me`
- [ ] `GET /api/crawlers`
- [ ] `GET /api/marts`
- [ ] 위치 기반 식당 API 경로 검증 (`/api/restaurants` vs `/api/restaurants/nearby`)
- [ ] 위치 기반 주유소 API 경로 검증 (`/api/gas-stations` vs `/api/gas/nearby`)

#### 프론트엔드
- [ ] `packages\website\frontend` → `npm run build`

### DB-admin

#### 기존 pytest
- [ ] `packages\db-admin\backend\tests\test_api_docs.py`
- [ ] `packages\db-admin\backend\tests\test_audit_log.py`
- [ ] `packages\db-admin\backend\tests\test_auth.py`
- [ ] `packages\db-admin\backend\tests\test_auto_categorize.py`
- [ ] `packages\db-admin\backend\tests\test_autocomplete.py`
- [ ] `packages\db-admin\backend\tests\test_background.py`
- [ ] `packages\db-admin\backend\tests\test_backup.py`
- [ ] `packages\db-admin\backend\tests\test_bind_address.py`
- [ ] `packages\db-admin\backend\tests\test_category_mgmt.py`
- [ ] `packages\db-admin\backend\tests\test_config_security.py`
- [ ] `packages\db-admin\backend\tests\test_data_quality.py`
- [ ] `packages\db-admin\backend\tests\test_db_engine.py`
- [ ] `packages\db-admin\backend\tests\test_db_retry.py`
- [ ] `packages\db-admin\backend\tests\test_disk_monitor.py`
- [ ] `packages\db-admin\backend\tests\test_error_handling.py`
- [ ] `packages\db-admin\backend\tests\test_getattr_safety.py`
- [ ] `packages\db-admin\backend\tests\test_health.py`
- [ ] `packages\db-admin\backend\tests\test_input_validation.py`
- [ ] `packages\db-admin\backend\tests\test_like_escape.py`
- [ ] `packages\db-admin\backend\tests\test_logging_config.py`
- [ ] `packages\db-admin\backend\tests\test_models.py`
- [ ] `packages\db-admin\backend\tests\test_price_calc.py`
- [ ] `packages\db-admin\backend\tests\test_rate_limiting.py`
- [ ] `packages\db-admin\backend\tests\test_security_headers.py`

#### 런타임 API
- [ ] `POST /api/auth/login` (기본 관리자 계정 또는 사전 준비된 QA 관리자 계정)
- [ ] `GET /api/health` 와 실제 `/health` 경로 계약 일치 검증
- [ ] `GET /api/products/`
- [ ] `GET /api/products/stats`
- [ ] `GET /api/categories/`
- [ ] `GET /api/keywords/`
- [ ] `GET /api/keywords/stats`
- [ ] `GET /api/keywords/popular`
- [ ] `GET /api/dashboard/stats`
- [ ] `GET /api/prices/stats`
- [ ] `GET /api/prices/tier-config`
- [ ] `GET /api/analytics/summary`
- [ ] `GET /api/analytics/quality-report`
- [ ] `GET /api/ingestions?status=pending`
- [ ] `GET /api/ingestions/stats`
- [ ] `GET /api/admin/data-summary`
- [ ] JWT 인증과 `X-API-Key` 인증 모두 검증

#### 프론트엔드
- [ ] `packages\db-admin\frontend` → `npm run build`

### Crawler-admin

#### 기존 pytest
- [ ] `packages\crawler-admin\backend\tests\test_all_hotdeal_crawlers.py`
- [ ] `packages\crawler-admin\backend\tests\test_audit.py`
- [ ] `packages\crawler-admin\backend\tests\test_circuit_breaker.py`
- [ ] `packages\crawler-admin\backend\tests\test_concurrency.py`
- [ ] `packages\crawler-admin\backend\tests\test_crawler_api.py`
- [ ] `packages\crawler-admin\backend\tests\test_dead_letter.py`
- [ ] `packages\crawler-admin\backend\tests\test_error_handler.py`
- [ ] `packages\crawler-admin\backend\tests\test_hotdeal_crawlers.py`
- [ ] `packages\crawler-admin\backend\tests\test_logging_config.py`
- [ ] `packages\crawler-admin\backend\tests\test_mart_crawlers.py`
- [ ] `packages\crawler-admin\backend\tests\test_pipeline.py`
- [ ] `packages\crawler-admin\backend\tests\test_pipeline_store_failure.py`
- [ ] `packages\crawler-admin\backend\tests\test_rate_limiter.py`
- [ ] `packages\crawler-admin\backend\tests\test_registry.py`
- [ ] `packages\crawler-admin\backend\tests\test_sanitizer.py`
- [ ] `packages\crawler-admin\backend\tests\test_scheduler.py`
- [ ] `packages\crawler-admin\backend\tests\test_security.py`
- [ ] `packages\crawler-admin\backend\tests\test_shopping_crawlers.py`
- [ ] 전체 pytest 스위트가 hang 없이 종료되는지 먼저 확인

#### 런타임 API
- [ ] `GET /health`
- [ ] `GET /api/crawlers` (without key → 401)
- [ ] `GET /api/crawlers` (with valid `X-API-Key`)
- [ ] `GET /api/dashboard/stats`
- [ ] `GET /api/logs?page=1&per_page=10`
- [ ] `GET /api/schedules`
- [ ] `GET /api/plugins`
- [ ] `GET /api/ingestions?status=pending`

#### 프론트엔드
- [ ] `packages\crawler-admin\frontend` → `npm run build`
- [ ] 번들 크기 경고 재확인 및 임계치 관리

## 7. 추가 필요 테스트

1. **Website**
   - `/api/products/prices` 라우트 충돌 회귀 테스트 추가
   - `/api/restaurants` → `/api/restaurants/nearby` 호환성/리다이렉션 테스트 추가
   - `/api/gas-stations` → `/api/gas/nearby` 호환성/리다이렉션 테스트 추가
   - 커뮤니티 작성 API의 인증 필수 여부를 명시하는 계약 테스트 추가

2. **DB-admin**
   - 기본 관리자 계정 시드/QA 계정 준비 검증 테스트 추가
   - `/api/health` 와 `/health` 중 표준 경로를 고정하는 계약 테스트 추가
   - 보호 API에 대한 라이브 JWT 인증 smoke test 추가

3. **Crawler-admin**
   - pytest hang 원인 분석용 최소 smoke test 및 collection test 추가
   - `X-API-Key`가 설정된 상태의 라이브 API smoke test 추가
   - 스케줄러/로그/플러그인 API의 정상 응답 스키마 검증 추가

4. **공통**
   - CI에서 “실행 성공 여부”뿐 아니라 **API 계약 경로**까지 검증하는 runtime smoke test 추가
   - 실제 서버 기동 후 `/health` 계열 엔드포인트와 프론트 빌드를 묶은 배포 전 체크 자동화 필요
