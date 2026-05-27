# Round R G2 Web Report

## 버그 진단
- 물가비교 진입 화면이 기존 `category_node`/상품 검색 흐름을 재사용해 leaf 상품명이 카테고리처럼 노출될 수 있었다.
- 카테고리 중간 노드에서도 상품 검색이 실행되어, 통합 카테고리 트리의 드릴다운 규칙(leaf에서만 상품 노출)이 깨졌다.
- 4사 상품은 `canon_hash` 기준 그룹 API가 없어 마트별 행이 묶이지 않았다.

## 변경
- `packages\web-api\backend\api\routes\web.py`
  - `GET /api/web/categories/tree`, `GET /api/web/categories/{slug}`, `GET /api/web/products/compare?canon_hash=...` 추가.
  - 기존 `/api/v1` 프리픽스 호환도 유지.
- `packages\web-api\backend\services\web_categories.py`
  - db-admin `storage\models.py`의 `UnifiedCategory`, `Product`, `PriceHistory` 모델을 재사용.
  - 최상위+자식 트리, leaf 분기, `canon_hash` 상품 그룹, 최신 가격/단위환산가/히스토리 응답 구성.
- `packages\web-frontend\src\pages\ComparePage.tsx`
  - 물가비교 탭을 unified 카테고리 드릴다운으로 재배선.
  - 진입 시 최상위 카테고리만 표시하고 leaf 도달 전 상품 카드 노출 금지.
  - leaf에서 4사 묶음 카드와 클릭 모달(4사 가격 + 히스토리)을 표시.
- 테스트
  - web-api leaf/non-leaf 및 4사 그룹 회귀 테스트 추가.
  - web-frontend 진입 leaf 상품 미노출 및 1단계 추가 드릴다운 회귀 테스트 추가.

## 캡쳐 필요 항목
1. `/compare` 최초 진입: 최상위 통합 카테고리만 보이고 상품명이 없는 상태.
2. 최상위 → 중간 카테고리 클릭: 하위 카테고리만 표시되고 상품 카드가 아직 없는 상태.
3. leaf 카테고리 클릭: `canon_hash` 기준 4사 묶음 카드와 원/100g 등 단위환산가 표시.
4. 카드 클릭 모달: 이마트/홈플러스/롯데마트/코스트코 현재가, 단위환산가, 가격 히스토리 영역.

## 검증
- `cd packages\web-api\backend; py -3 -m pytest tests\test_api_web_categories.py -q` → 2 passed.
- `cd packages\web-api\backend; py -3 -m pytest -q` → 102 passed.
- `cd packages\web-frontend; npm run test -- compare-page-g2.test.tsx` → 2 passed.
- `cd packages\web-frontend; npm run test` → 88 passed.
- `cd packages\web-frontend; npm run build` → 성공.
