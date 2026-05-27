# WalletSavior Round R 다중 에이전트 동시 작업 회귀 스윕

**실행 일시**: 2026-05-04  
**실행 범위**: Round R db-admin, crawler-admin, shared, 3 frontend builds

---

## 테스트 결과 요약

| 영역 | 명령 | 결과 | 비고 |
|------|------|------|------|
| **DB-Admin Backend** | `alembic heads` | ✅ PASS | 단일 head: `r_g5c_opinet` |
| **DB-Admin Backend** | `pytest tests/test_g2_category_aggregator.py tests/test_g2_unified_category.py tests/test_auto_classify.py tests/test_external_ai_export.py tests/test_external_ai_import.py tests/test_external_ai_import_e2e.py tests/test_unmatched_isolation.py -q` | ❌ FAIL | 3 failed, 21 passed, 39 warnings. 실패: test_same_canon_hash_groups_four_marts, test_case_b_name_variant_keeps_stable_canon_hash, test_export_manifest_separates_unmatched_cases |
| **Crawler-Admin Backend** | `pytest tests/test_emart_crawler_g1.py tests/test_homeplus_crawler_g1.py tests/test_lottemart_crawler_g1.py tests/test_costco_crawler_g1.py tests/test_source_utils_g1.py tests/test_algumon_crawler.py tests/test_opinet_crawler.py tests/test_mart_crawlers.py -q` | ✅ PASS | 121 passed, 3 skipped in 85.61s |
| **Shared** | `pytest -q` | ❌ FAIL | 1 failed, 622 passed in 3.21s. 실패: test_ai_job_batch_rejects_prompt_text_over_2000_chars_without_splitting_records |
| **DB-Admin Frontend** | `npm run build` | ✅ PASS | ✓ built in 1.14s |
| **Crawler-Admin Frontend** | `npm run build` | ⚠️ WARN | ✓ built in 1.18s (chunk size warning: 735.79 kB gzip) |
| **Web-Frontend** | `npm run build` | ✅ PASS | ✓ built in 379ms |

---

## 상세 실패 분석

### 1. DB-Admin Backend Failures (3 failed)

#### 실패 #1: `test_same_canon_hash_groups_four_marts`
```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) 
UNIQUE constraint failed: products.brand, products.name_core, products.pack_qty, products.pack_unit

[SQL: INSERT INTO products (...) VALUES (...)]
[parameters: ('테스트 우유 1L', None, 'L', None, None, 1, '2026-05-26 12:32:16.042047', 
'2026-05-04 09:00:00.000000', 'mart_crawl', None, None, '테스트', '테스트 우유 1L', 1.0, 'L', 
None, '테스트 우유 1L', None, 'emart', 'cat-100', '30d7232ae1e0e44f60a88ddb69361a486d0f0bb9', 
0, None, None, 'new-native', '식품 > new-native', None, None, None)]
```
**상태**: UNIQUE 제약조건 위반 (테스트 데이터 중복 삽입 문제)

#### 실패 #2: `test_case_b_name_variant_keeps_stable_canon_hash`
```
assert False is True
```
**상태**: 로직 검증 실패

#### 실패 #3: `test_export_manifest_separates_unmatched_cases`
```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) 
UNIQUE constraint failed: products.brand, products.name_core, products.pack_qty, products.pack_unit
```
**상태**: 위와 동일한 UNIQUE 제약조건 위반

### 2. Shared Failures (1 failed)

#### 실패: `test_ai_job_batch_rejects_prompt_text_over_2000_chars_without_splitting_records`
```python
def test_ai_job_batch_rejects_prompt_text_over_2000_chars_without_splitting_records():
    records = [make_record(i, title="긴상품명" * 60) for i in range(10)]
    
    with pytest.raises(ValidationError, match="max is 2000"):
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   Failed: DID NOT RAISE <class 'pydantic_core._pydantic_core.ValidationError'>
```
**상태**: 검증 로직 실패 (ValidationError 미발생 예상 vs 실제)

---

## 종합 판정

| 항목 | 상태 |
|------|------|
| **Alembic Migration** | ✅ PASS |
| **DB-Admin Backend Tests** | ❌ FAIL (3 failures - data integrity, validation) |
| **Crawler-Admin Backend Tests** | ✅ PASS (121 passed, 3 skipped) |
| **Shared Tests** | ❌ FAIL (1 failure - validation logic) |
| **Frontend Builds** | ⚠️ MOSTLY PASS (db-admin frontend chunk warning 제외) |

### 전체 평가
**회귀 상태**: 🔴 **FAILED**  
- DB-Admin 테스트 영역에서 UNIQUE 제약조건 위반 (test_auto_classify.py, test_unmatched_isolation.py)
- Shared 테스트에서 검증 로직 실패 (test_ai_pipeline_contracts.py)
- Crawler-Admin, Frontend는 정상 동작
- 데이터 무결성 및 검증 레이어 문제로 인한 불안정성 확인

---

## 다음 단계
1. DB-Admin 테스트 UNIQUE 제약조건 위반 원인 분석
   - test_auto_classify.py, test_unmatched_isolation.py 테스트 격리 문제 검토
2. Shared 검증 로직 (AIJobBatch validation) 점검
3. Crawler-Admin Frontend 청크 크기 최적화 (선택사항)
