# cocodalin-seed report

## Files changed/created
- `packages/crawler-admin/backend/services/cocodalin_seed_importer.py` — Cocodalin JSON/CSV/live importer, native-code/name matching, idempotent `price_history` insertion, `ImportReport`.
- `packages/crawler-admin/backend/cli/cocodalin_seed.py` — CLI wrapper for `--source`, `--dry-run`, and `--database-url`.
- `crawler_admin/backend/cli/cocodalin_seed.py` — compatibility wrapper so `py -3 -m crawler_admin.backend.cli.cocodalin_seed` works from repo root.
- `packages/crawler-admin/backend/tests/test_cocodalin_seed_importer.py` and `tests/fixtures/cocodalin/seed_sample.json` — exact match, name match, unmatched, idempotency, dry-run coverage.

## Test results
- `py -3 -m pytest packages\crawler-admin\backend\tests\test_cocodalin_seed_importer.py -q`
- Result: `3 passed, 22 warnings` (warnings are existing SQLAlchemy `datetime.utcnow()` deprecations from models).

## ImportReport schema
`total_input`, `matched_by_native_code`, `matched_by_name`, `unmatched`, `inserted`, `skipped_duplicates`, `errors`.

## Sample dry-run output (counts only)
```json
{
  "total_input": 3,
  "matched_by_native_code": 1,
  "matched_by_name": 1,
  "unmatched": 1,
  "inserted": 2,
  "skipped_duplicates": 0,
  "errors": 0
}
```

## Assumptions / open questions
- Current Cocodalin crawler returns `DiscountItem` dictionaries and raw API rows keyed by Cocodalin `product_id`, not Costco `/p/<digits>`; importer therefore supports future native-code fields but falls back to normalized fuzzy name matching today.
- One Cocodalin discount period is imported as one `price_history` observation using `from_date`/`valid_from` as `observed_at`.
- Deferred: scheduled-job integration (G3) and non-Costco backfills.
