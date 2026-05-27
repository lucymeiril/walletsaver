# Round R unique cross-mart regression fix

## Summary

- Replaced the product canonical uniqueness rule that blocked cross-mart G1 grouping.
- `canon_hash` remains non-unique and indexed so four marts can share the same canonical hash.
- Added the mart-native permanent key uniqueness rule: `UNIQUE(mart, mart_native_code)`.

## Files

- Model: `packages/db-admin/backend/storage/models.py`
- Migration: `packages/db-admin/backend/storage/migrations/versions/c5e6f7a8b9c0_round_r_unique_relax_cross_mart.py`

## Verification

- Targeted regression tests: `py -3 -m pytest tests/test_auto_classify.py::test_same_canon_hash_groups_four_marts tests/test_unmatched_isolation.py::test_export_manifest_separates_unmatched_cases -q` → 2 passed.
- Sanity tests: `py -3 -m pytest tests/test_auto_classify.py tests/test_unmatched_isolation.py tests/test_g2_unified_category.py tests/test_external_ai_import.py -q` → 17 passed.
- Alembic heads: `py -3 -m alembic heads` → `c5e6f7a8b9c0 (head)`.
