# g1-a1 report — Emart crawler rewrite

## Files changed
- `packages/crawler-admin/backend/crawlers/marts/emart/crawler.py` — rewritten for Round R G1 category CSR HTML/card extraction; removed legacy page-data assumptions; emits Round R product fields through item attributes and crawl output records.
- `packages/crawler-admin/backend/crawlers/marts/emart/entrypoints.py` — kept 4-entrypoint facade, updated sale/catalog URLs to category pages.
- `packages/crawler-admin/backend/crawlers/marts/emart/plugin.yaml` — updated contract/strategy/selectors to category card HTML.
- `packages/crawler-admin/backend/tests/fixtures/emart_category_sample.html` — hand-trimmed 5-card fixture based on G0-documented Emart card/link/badge/unit-price patterns; no live network used.
- `packages/crawler-admin/backend/tests/test_emart_crawler_g1.py` — G1 parser/crawl tests for itemId, salestrNo, external seller flag, unit price, canonical URL, and source injection.

## Test results
- PASS: `py -3 -m pytest packages\crawler-admin\backend\tests\test_emart_crawler_g1.py -q` — 4 passed.
- PASS: `py -3 -m pytest packages\crawler-admin\backend\tests\test_emart_crawler.py -q` — 11 passed.
- PASS: `py -3 -m pytest packages\crawler-admin\backend\tests\test_mart_crawlers.py -q -k "emart and not live"` — 39 passed, 27 deselected.
- Requested broad command `py -3 -m pytest packages\crawler-admin\backend\tests\test_emart_crawler_g1.py packages\crawler-admin\backend\tests -q -k emart` was run. Emart coverage passed, but the command also selects `lottemart` tests (substring match) and currently fails 12 unrelated Lottemart G1 assertions about EAN-13/source_record_key canonicalization.

## Caveats
- Live Emart fetch can be blocked/flaky; unit tests use the fixture only.
- The crawler imports the G1 `source_utils` helpers and keeps a pytest-only fallback for isolated testing before/while the base helper branch is in flux.
