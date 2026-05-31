"""통합 카탈로그 동기화(Catalog Sync) 모듈.

정본 데이터(unified_categories + mart_category_mappings + Product.unified_category_id)에 대한
export / import(dry-run·apply) / 상품 일괄 재분류를 한 줄기로 제공한다.

설계 원칙(plan.md 참조):
  - 정본은 unified_categories 트리. 레거시 categories/matching_entries는 사용하지 않는다.
  - 검증기는 raise하지 않고 리포트를 반환한다(외부 import_classification_import 패턴 차용).
  - 모든 apply는 dry-run preview 후 수행하며, 파괴적 작업 전 DB 스냅샷을 남긴다.
"""

SCHEMA_VERSION = "catalog-sync-v1"
