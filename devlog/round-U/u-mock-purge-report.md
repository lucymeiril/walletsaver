# Round U slot #4 — web mock purge + empty category audit

## 요약

- `packages/db-admin/backend/walletguardian.db`의 `products`는 현재 0건이다.
- 그런데 `/api/v1/products/search`는 기본값으로 `.walletsavior/public_snapshot.sqlite`를 읽고 있었고, 해당 스냅샷 메타에 `ai_provider_kind: mock`가 명시되어 있었다.
- 운영 경로에서 묵시적으로 mock snapshot을 서빙하지 못하도록 `WALLETSAVIOR_PUBLIC_DB`를 필수화했다.
- `products/{id}/history`의 `last_seen_at + p50` stub 시계열도 제거해 빈 시계열을 반환하도록 바꿨다.
- 프론트엔드는 지시대로 수정하지 않았다.

## 표 1. mock/하드코딩 의심 및 조치

| 파일:라인 | 함수/영역 | 증거 | fixture/test vs production | 우려 | 조치 |
|---|---|---|---|---|---|
| `.walletsavior/public_snapshot_meta.json:12` | public snapshot 메타 | `ai_provider_kind: "mock"`, 4개 마트 각 5건 총 20건 | production API 기본 입력으로 사용됨 | 높음 | 기본 서빙 차단 |
| `packages/web-api/backend/services/snapshot_repo.py:9-13` | `get_db_path()` | 기존 기본값이 `.walletsavior/public_snapshot.sqlite`였음 | production | 높음 | `WALLETSAVIOR_PUBLIC_DB` 없으면 503 |
| `packages/web-api/backend/api/routes/products.py:190-221` | `get_product_history()` | `last_seen_at` + `p50`으로 `source: stub` 포인트 생성 | production | 높음 | `source: none`, `points: []`로 변경 |
| `packages/web-api/backend/services/web_categories.py:146-172` | `grouped_products_for_category()` | DB `Product` 조회만 수행 | production real DB | 낮음 | mock 아님 |
| `packages/web-api/backend/tests/*`, `packages/web-frontend/src/__tests__/*` | tests | `mockResolvedValue`, 테스트 fixture | test only | 낮음 | 유지 |
| `packages/web-frontend/src/components/ProductCard.tsx`, `ProductDetailPage.tsx` | UI fallback label | `sample_count` 표시 fallback | production UI display only | 낮음 | 프론트 수정 금지라 미수정 |

## 실제 동작 검증

| 상태 | 호출 | 결과 |
|---|---|---|
| 수정 전, env 미설정 | `/api/v1/products/search?page_size=5` | 200, `.walletsavior` mock snapshot 20건 중 5건 반환 |
| 수정 전, env 미설정 | `/api/v1/categories` | 200, `.walletsavior` category 49 nodes 반환 |
| 수정 전, env 미설정 | `/api/web/categories/tree` | DB 기반 응답. `walletguardian.db` products 0건이면 product group은 비어야 함 |
| 수정 후, env 미설정 | `/api/v1/products/search?page_size=5` | 503, snapshot env 필수 |
| 수정 후, env 미설정 | `/api/v1/categories`, `/api/v1/health` | 503, snapshot env 필수 |
| 수정 후, 명시적 `.walletsavior` env | `/api/v1/products/search?page_size=2` | 200, 20건 반환(명시 설정 시만 허용) |
| 수정 후, 명시적 `.walletsavior` env | `/api/v1/products/{id}/history` | 200, `source: none`, `points: []` |

## 표 2. 빈 카테고리 상품 통계

### `packages/db-admin/backend/walletguardian.db`

| 쿼리 | 결과 |
|---|---:|
| `SELECT COUNT(*) FROM products` | 0 |
| `category_id IS NULL OR category_id=''` | 0 |
| `name IS NULL OR name=''` | 0 |
| sample 30 rows | 없음 |

현재 사용자가 본 “상품 탭 비어 있음”은 맞다. `products` 테이블은 비어 있다.

### `.walletsavior/public_snapshot.sqlite` (기존 API 기본 입력)

| 쿼리 | 결과 |
|---|---:|
| `SELECT COUNT(*) FROM canonical_product` | 20 |
| `category_id IS NULL OR category_id=''` | 5 |

| id/name_core | category_id |
|---|---|
| 한끼 양배추 | NULL |
| 김제 햇 감자 | NULL |
| 씨없는 아삭 파프리카 | NULL |
| 언양식 소불고기 | NULL |
| 철원 오대쌀 | NULL |

## 표 3. 크롤러 카테고리 채우기 경로

| 마트 | 기존 상태 | 누락/위험 위치 | 조치 |
|---|---|---|---|
| 이마트 | JSON 경로는 `category=category` 전달 | HTML fallback `_parse_product_card`는 category 미전달 | `data-category`/breadcrumb 추출 후 `build_source_attributes`와 `DiscountItem.category`에 전달 |
| 홈플러스 | API/mfront 일부 경로는 category 전달 | legacy HTML `_parse_product_card`는 category 미전달 | HTML fallback category 추출 및 전달 |
| 롯데마트 | entity/json 일부 경로는 category path 전달 | product API row와 HTML fallback 일부 미전달 | `categoryPath/categoryName` 및 card category 추출 후 전달 |
| 코스트코 | `mart_native_category_path`를 card→record→DiscountItem으로 전달 | 큰 누락 없음 | 변경 없음 |

## 변경 파일

- `packages/web-api/backend/services/snapshot_repo.py`
- `packages/web-api/backend/api/routes/health.py`
- `packages/web-api/backend/api/routes/products.py`
- `packages/web-api/backend/tests/test_api_products_extra.py`
- `packages/web-api/backend/README.md`
- `packages/crawler-admin/backend/crawlers/marts/emart/crawler.py`
- `packages/crawler-admin/backend/crawlers/marts/homeplus/crawler.py`
- `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py`

## 검증

| 명령 | 결과 |
|---|---|
| `py -m py_compile ...` | 통과 |
| `cd packages/web-api/backend; py -m pytest -q tests/test_api_products_extra.py tests/test_api_categories.py tests/test_api_health.py` | 14 passed |
| `cd packages/crawler-admin/backend; py -m pytest -q tests/test_emart_crawler_g1.py -x` | 실패: 기존 dirty 상태의 `EmartCrawler.parse_product_records` 누락 |
| `cd packages/crawler-admin/backend; py -m pytest -q tests/test_mart_crawlers.py ...` | 장시간 실행/행 상태로 중단. 개별 첫 실패는 위와 같음 |

## 권장 후속 조치

1. 배포/로컬 실행 스크립트에서 실제 공개 snapshot 생성 완료 후에만 `WALLETSAVIOR_PUBLIC_DB`를 명시 설정한다.
2. `.walletsavior/public_snapshot.sqlite`와 meta는 mock 샘플이므로 운영 기본값으로 쓰지 않는다.
3. `walletguardian.db.products`가 0건인 상태에서 상품 UI가 뜨면 API 경로가 `/api/v1` snapshot을 보고 있는지 우선 확인한다.
4. 카테고리 누락은 크롤러 원천 category/path 보존 + DB import 단계의 `unified_category_id` 매핑을 별도 검증해야 한다.
