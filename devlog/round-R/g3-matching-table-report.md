# Round R G3-1 Matching Table Report

## 산출물
- 신규 서비스: `packages\db-admin\backend\services\auto_classify.py`
  - `RawProduct` 입력 DTO와 `auto_classify_products()` 파이프라인을 추가했다.
  - `mart + mart_native_code`를 영구 키로 Product를 upsert하고, `canon_hash`는 4사 횡단 동일 상품군 묶음 키로 보존한다.
- 신규 CLI: `packages\db-admin\backend\scripts\g3_auto_classify_run.py`
  - `--jsonl` 크롤러 산출 파일 또는 `--staging-table` DB staging 테이블을 읽는다.
  - 기본은 dry-run이며 `--commit` 지정 시 DB에 반영한다.
- API: `POST /api/admin/auto-classify/run`
  - 요청의 `products` 배열 또는 `jsonl_path`를 실행 입력으로 받아 신규/업데이트/분류/미분류/가격 히스토리 요약을 반환한다.
- 테스트: `packages\db-admin\backend\tests\test_auto_classify.py`
  - 4사 동일 `canon_hash`, native category 매핑, 미매핑, human 보존, 주간 idempotency, URL slug 변경 대비를 검증한다.

## 알고리즘 결정
1. RawProduct는 `source → mart`, `name/product_name/title → raw_name`, `native_code → mart_native_code` 등 크롤러별 alias를 수용한다.
2. Product 식별은 `mart + mart_native_code`를 최우선으로 한다. URL은 표시/이동용으로만 갱신하며 식별에 사용하지 않는다.
3. `canon_hash`가 같은 상품은 별도 Product row를 유지하되 같은 상품군으로 묶을 수 있도록 모든 row에 동일 hash를 저장한다.
4. `mart + mart_native_category_id`로 `mart_category_mappings`를 조회하고, 매핑이 있으면 `Product.unified_category_id`를 채운다.
5. 매핑이 없으면 `unclassified` 카운트로 집계하고 `Product.unified_category_id`는 NULL 상태로 남긴다.

## trust 정책
- G2와 같은 신뢰 위계 `human=2 > external-ai=1 > auto-aggregate=0`를 재사용했다.
- Product에는 별도 unified-category trust 컬럼이 없으므로 기존 `categorization_method`가 `manual`, `corrected`, `human`이고 `unified_category_id`가 있으면 수동 분류로 간주한다.
- 자동 분류는 `categorization_method='auto-aggregate'`, `categorization_confidence=1.0`으로 기록하며, human 기존값은 덮어쓰지 않고 `human_preserved`로 집계한다.

## 주간 누적 모델 검증
- 기존 `price_history`에는 `week_of`와 `(product_id, week_of, mart)` UNIQUE가 없어서 신규 Alembic revision `c4d5e6f7a8b9`를 추가했다.
- `PriceHistory.product_id`, `PriceHistory.week_of`를 추가하고 `uq_price_history_product_week_mart`로 같은 주 중복 삽입을 막는다.
- 서비스는 `observed_at` 기준 월요일을 `week_of`로 계산한다.
- 같은 week에 두 번 실행하면 기존 PriceHistory를 재사용하고, 다음 week 실행은 새 행을 추가한다.

## 검증
- `cd packages\db-admin\backend; py -3 -m pytest tests\test_auto_classify.py -q` → `6 passed, 21 warnings`.
- `cd packages\db-admin\backend; py -3 -m compileall services\auto_classify.py scripts\g3_auto_classify_run.py api\routes\admin.py storage\models.py -q` → 성공.
- `cd packages\db-admin\backend; py -3 -m alembic heads --verbose`에서 `c4d5e6f7a8b9`가 `c3d4e5f6a7b8` 다음 revision으로 인식됨을 확인했다. 현재 최종 head는 기존 G5 계열 `r_g5c_opinet`이다.

## 알려진 한계
- Product에 unified-category 전용 trust 컬럼이 없어 `categorization_method` 기반으로 human 보존을 판단한다.
- 미매핑 native category는 별도 `unclassified` category row를 만들지 않고 NULL + 요약 카운트로 남긴다.
- cross-mart 동일 상품군은 현재 `canon_hash` 저장과 요약 집계까지이며, 별도 canonical group 테이블은 만들지 않았다.

## 다음 단계
- g3-export: `canon_hash` 그룹 단위 export와 unclassified review queue 산출.
- g3-e2e: 실제 4사 크롤러 산출 JSONL/staging table을 연결한 end-to-end 실행 검증.
