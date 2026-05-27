# Round V fleet 슬롯 #4 — Matching UI / unit price report

## 구현 요약
- 기존 `product_matches`는 마트별 동일 상품 연결, `matching_entries`는 `brand|name_core|pack_qty|pack_unit` 기반 canonical lookup 테이블임을 확인했다.
- 사용자 요구의 “상품 제목 기반 자동 분류 매칭 테이블”로 `product_match_rules`를 추가했다.
  - schema: `id`, `pattern_type(exact|normalized|regex)`, `pattern_value`, `canonical_category_id`, `canonical_product_id`, `trust(0..2)`, `created_by`, `created_at`, `hit_count`
  - SQLAlchemy 모델: `packages/db-admin/backend/storage/models.py`
  - Alembic migration: `packages/db-admin/backend/storage/migrations/versions/v4m_product_match_rules.py`
- Backend API 추가: `packages/db-admin/backend/api/routes/matching_rules.py`
  - `GET /api/matching-rules?page=&search=&pattern_type=`
  - `GET /api/matching-rules/stats`
  - `POST /api/matching-rules`
  - `PUT /api/matching-rules/{id}`
  - `DELETE /api/matching-rules/{id}`
- Admin UI 추가: `packages/db-admin/frontend/src/pages/MatchingTable/MatchingTablePage.jsx`
  - 컬럼: 패턴 유형 / 패턴 값 / 매칭된 unified 카테고리 / 매칭된 표준 상품 / trust / 생성자 / hit_count / 관리
  - 검색, 유형 필터, 페이지네이션, 추가/수정/삭제 폼 포함
  - `/matching` route 및 NAV `매칭 테이블` 추가

## Ingestion 적용
- `packages/db-admin/backend/api/routes/ingestion.py`에서 category가 비었거나 1-depth일 때 상품명으로 `product_match_rules`를 조회한다.
- match 시:
  - `Product.unified_category_id`에 `canonical_category_id` 반영
  - `Product.canonical_product_id`에 `canonical_product_id` 반영
  - `Product.attributes.product_match_rule_id` 기록
  - `hit_count += 1`

## 단위 환산가 검증
- `packages/shared/core/models.py` `DiscountItem`에 `unit_price_display: str = ""` 추가.
- ingestion raw 저장에 `unit_price_display` / `unit_price_displayed`를 mirror한다.
- `Product.attributes.unit_price_display`에도 보존한다.
- DB admin 상품 목록에 `단위 환산가` 컬럼을 추가했다.
- 검증 테스트에서 `sale_price=9920`, `unit_price_display="100g당 1,984원"` 입력 시:
  - `discount_history.price == 9920`
  - `discount_history.raw_data["unit_price_display"] == "100g당 1,984원"`
  - 즉 100g 환산 표시가 판매가 컬럼으로 들어가지 않음을 확인했다.

## 검증 결과
- `cd packages\db-admin\frontend; npm run build -- --clearScreen=false` ✅ 성공
- `cd packages\db-admin\backend; py -3 -m pytest tests\test_matching_rules_round_v.py tests\test_ingestion_insert.py -q` ✅ 22 passed
- `cd packages\db-admin\backend; py -3 -m pytest tests\test_models.py::TestSchemaIntegration::test_all_tables_created tests\test_matching_rules_round_v.py tests\test_ingestion_insert.py -q` ✅ 23 passed
- matching API 200 검증: `tests/test_matching_rules_round_v.py::test_matching_rules_api_lists_and_stats`에서 TestClient로 `GET /api/matching-rules`, `GET /api/matching-rules/stats` 모두 200 확인.
- 전체 backend suite `py -3 -m pytest tests -q`는 실행했으나 현재 `packages/db-admin/backend/walletguardian.db`가 `database disk image is malformed` 상태라 health/auth 등 기존 DB 의존 테스트가 실패했다. 관련 subset 및 신규 기능 테스트는 통과했다.
- 실제 `walletguardian.db` SELECT 검증도 동일한 malformed 오류로 불가했다. 대신 in-memory DB publish 테스트로 raw → DB 보존 경로를 검증했다.

## 미수정 범위
- `packages/web-frontend/`는 건드리지 않았다.
- 크롤러 페이지네이션 및 SQLite engine 설정은 변경하지 않았다.
