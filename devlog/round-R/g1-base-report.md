# G1 base report

## Files modified/created
- `packages/crawler-admin/backend/crawlers/marts/source_utils.py` — appended 90-line Round R G1 helper block.
- `packages/crawler-admin/backend/tests/test_source_utils_g1.py` — created 74-line helper test suite.
- `packages/db-admin/backend/storage/models.py` — added 10 Product columns and 20-line `PriceHistory` model block.
- `packages/db-admin/backend/tests/test_models.py` — added `PriceHistory` to schema integration expectations.
- `packages/db-admin/backend/storage/migrations/versions/b2c3d4e5f6a7_round_r_g1_product_columns_and_price_history.py` — created 74-line Alembic revision.
- `packages/db-admin/backend/storage/migrations/versions/HOTDEAL_HEAD_PENDING.md` — created 2-line G5-b separation marker.

## Test results
- Baseline before G1 changes:
  - crawler-admin: `7 failed, 797 passed, 20 skipped, 929 warnings in 154.07s`.
  - db-admin: `15 failed, 629 passed, 1492 warnings in 52.80s`.
- Focused G1 helper test after changes:
  - `py -3 -m pytest packages\crawler-admin\backend\tests\test_source_utils_g1.py -q`
  - `15 passed in 0.06s`.
- Full backend tests after changes:
  - crawler-admin: `20 failed, 814 passed, 20 skipped, 929 warnings in 882.22s`.
  - db-admin: `15 failed, 629 passed, 1506 warnings in 50.65s`.
  - db-admin failures remained in the known groups (`test_canonical_seed.py`, `test_category_pollution_guard.py`, `test_ingestion_insert.py`). New crawler-admin failures are in pre-existing/in-progress crawler/workbench areas, not the new `test_source_utils_g1.py`.

## Alembic output snippets
- Upgrade: `Running upgrade 306077c6d0e2 -> b2c3d4e5f6a7, Round R G1: product native code/canon hash/external seller/unit price columns + price_history table`.
- Current: `b2c3d4e5f6a7 (head)`.
- Downgrade/upgrade round-trip: `Running downgrade b2c3d4e5f6a7 -> 306077c6d0e2` then `Running upgrade 306077c6d0e2 -> b2c3d4e5f6a7`.

## Deviations from G0-schema.md
- Hotdeal head split was intentionally deferred to `HOTDEAL_HEAD_PENDING.md` per G1 task instructions; full separation remains G5-b.
- Category mapping skeleton tables from G0 §8 were not added because this `g1-base` scope only requested Product columns, `price_history`, source utils, and the hotdeal marker.

## Reproduction one-liner
```powershell
py -3 -m pytest packages\crawler-admin\backend\tests\test_source_utils_g1.py -q; cd packages\db-admin\backend; $env:DATABASE_URL='sqlite:///walletguardian.db'; py -3 -m alembic downgrade -1; py -3 -m alembic upgrade head; py -3 -m alembic current
```
