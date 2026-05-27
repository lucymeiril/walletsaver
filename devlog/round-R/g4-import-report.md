# Round R G4 Import Report

## 산출물
- `packages\db-admin\backend\services\external_ai_export.py`
  - 미분류 `Product.unified_category_id IS NULL` 상품을 `unclassified.jsonl`로 export.
  - DB의 `unified_categories`를 `category_list.yaml`로 export.
  - `keywords` 테이블이 있으면 `keyword_list.yaml`, 없으면 코멘트 포함 빈 목록 생성.
  - `external_classify_instructions_v1.md` 본문을 `instructions.md`에 포함.
  - manifest에 파일 목록, row count, 생성 시각 기록.
- `packages\db-admin\backend\services\external_ai_import.py`
  - 3종 파일 검증 후 단일 SAVEPOINT 트랜잭션으로 DB 적용.
  - 신규 `UnifiedCategory`/`Keyword` 생성, `MartCategoryMapping` external-ai upsert, `Product` 메타 보강.
  - trust 위계 `human=2 > external-ai=1 > auto-aggregate=0`에 따라 human mapping 보호.
  - dry-run은 실제 flush 후 rollback하여 DB 제약까지 검증.
- `packages\db-admin\backend\api\routes\external_ai.py`
  - `POST /api/admin/external-ai/export`
  - `POST /api/admin/external-ai/import` multipart 업로드 및 경로 기반 import 지원.
- `packages\db-admin\frontend\src\pages\ExternalAI\ExternalAIPage.jsx`
  - 외부 AI 분류 사이클 화면 추가, 라우터/내비/API client 등록.
- `packages\db-admin\backend\tests\test_external_ai_import_e2e.py`
  - export→fixture import→DB 검증, trust 회귀, 부분 실패 rollback 검증.

## 검증
- Backend: `cd packages\db-admin\backend; py -3 -m pytest tests\test_external_ai_export.py tests\test_external_ai_import.py tests\test_external_ai_import_e2e.py -q` → `6 passed, 9 warnings`.
- Frontend: `cd packages\db-admin\frontend; npm run build` → 성공.

## 알려진 한계
- 기존 `keywords.category_id`는 legacy `categories.id` FK라서, import의 unified category id는 legacy category가 존재할 때만 연결하고 아니면 keyword/synonym만 보존한다.
- `Product`에는 별도 category trust 컬럼이 없어 native category mapping trust를 기준으로 human 보호를 적용한다.
