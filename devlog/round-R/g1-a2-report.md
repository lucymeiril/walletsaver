# G1 A2 — Homeplus crawler rewrite

- Reworked Homeplus category collection around two store types: HYPER `/list` and EXP `/express/list`.
- Canonical identity now requires `/item?itemNo=<9-digit>&storeType=HYPER|EXP`; internal SPA routing hrefs are ignored by the parser.
- Added Homeplus-specific card attributes: `storeType`, `mart_native_code`, `canonical_url`, `external_seller`, unit-price fields, `canon_hash`, and injected `source=homeplus`.
- Added a configurable dynamic-scroll safety net: unchanged item count, end marker, and empty latest XHR; crawler stops only when at least 2 of 3 conditions are true.
- Exported a G1 category-tree seed fixture for G2: `packages/crawler-admin/backend/tests/fixtures/homeplus_category_tree_g1.json`.
- Added fixture-based G1 regression tests in `packages/crawler-admin/backend/tests/test_homeplus_crawler_g1.py`.

Validation command:

```powershell
py -3 -m pytest packages\crawler-admin\backend\tests -q -k homeplus
```
