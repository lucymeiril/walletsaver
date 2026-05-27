# Round R G2 Mapping Report

## 산출물
- DB 모델: `packages\db-admin\backend\storage\models.py`
  - `UnifiedCategory`: 통합 카테고리 트리 노드.
  - `MartCategoryMapping`: 4사 native category → 통합 category 매핑.
  - `Product.unified_category_id`: nullable FK.
- 서비스/API
  - `packages\db-admin\backend\services\unified_categories.py`
  - `packages\db-admin\backend\api\routes\categories.py`
  - `GET /api/categories/unified/tree`
  - `GET /api/categories/mappings?mart=<emart|homeplus|lottemart|costco>`
  - `POST /api/categories/mappings`는 운영자 저장을 `trust=human`으로 처리.
- Alembic
  - `packages\db-admin\backend\storage\migrations\versions\c3d4e5f6a7b8_round_r_g2_unified_category.py`
- Seed CLI
  - `packages\db-admin\backend\scripts\g2_seed_unified_tree.py`
  - 실행: `py -3 -m db_admin.scripts.g2_seed_unified_tree --yaml devlog\round-R\g2-unified-tree.yaml`
- Frontend
  - `packages\db-admin\frontend\src\pages\UnifiedCategories\UnifiedCategories.jsx`
  - `packages\db-admin\frontend\src\pages\UnifiedCategories\UnifiedCategories.module.css`
  - 라우터/네비/API client 등록.
- Tests
  - `packages\db-admin\backend\tests\test_g2_unified_category.py`

## 결정 사항
- matching_sync와 같은 신뢰 위계 적용: `human=2 > external-ai=1 > auto-aggregate=0`.
- 낮은 trust 입력은 높은 trust 기존 매핑을 덮어쓰지 않고 `conflict`로 유지한다.
- G2 YAML의 `lottemart.source_natives`는 권위 트리 기반 자동 매핑으로 보고 `trust=auto-aggregate`, `confidence=0.8`로 prefill한다.
- `mart_native_path`가 YAML에 직접 없으므로 seed 단계에서는 통합 카테고리 한글 경로를 fallback path로 기록한다.

## Alembic head
- 신규 revision: `c3d4e5f6a7b8`
- down_revision: `b2c3d4e5f6a7`
- `py -3 -m alembic heads` 결과 신규 G2 head 포함: `c3d4e5f6a7b8 (head)`

## 시드 결과
- 검증용 SQLite DB에서 full `g2-unified-tree.yaml` seed 2회 실행.
- 1회차: categories inserted 66, lottemart mappings inserted 324, duplicate ancestor/leaf 재방문 update 321.
- 2회차: categories inserted 0, categories updated 66, mappings inserted 0, mappings updated 645.
- 결론: category/mapping unique key 기준 idempotent.

## 검증
- Backend: `cd packages\db-admin\backend; py -3 -m pytest tests\test_g2_unified_category.py tests\test_g2_category_aggregator.py -q` → `7 passed, 2 warnings`.
- Frontend: `cd packages\db-admin\frontend; npm run build` → 성공.

## 알려진 한계
- YAML review_queue의 fixture-only 58건은 DB에 native product row가 없으면 API 목록에 표시되지 않는다.
- lottemart native path는 원천 mart 경로가 아니라 통합 트리 한글 경로 fallback이다.
- 같은 lottemart native가 ancestor와 leaf에 중복 등장하면 마지막 처리 노드가 최종 매핑이 된다.

## 다음 단계 (g2-web)
- crawler harvested native path 원본을 별도 seed 입력으로 연결해 `mart_native_path` 정확도를 높인다.
- review_queue fixture 항목도 운영 UI에서 볼 수 있도록 별도 review table 또는 seed 옵션을 추가한다.
- 상품 ingest 시 `Product.unified_category_id` 자동 채움 훅을 연결한다.
