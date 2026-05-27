# G1-A4 Costco crawler report

- Reworked `marts/costco/crawler.py` around the G0-confirmed `/c/cos_<a.b.c>` category tree and `/p/<digits>` product key.
- Added homepage category harvesting, leaf category crawling, `/p/` dedupe, pagination discovery, Costco URL normalization, unit-price parsing, `external_seller=false`, `source=costco`, and SHA1 `canon_hash` emission.
- Product records expose `mart_native_code`; this is also emitted as `cocodalin_join_key` for the sibling seed/backfill task.
- Added `marts/costco/entrypoints.py` and plugin entrypoint metadata matching the four-entrypoint convention.
- Added `tests/test_costco_crawler_g1.py` fixtures for category tree, listing parsing, canonical URL, unit price, pagination, and constants.

Validation: `py -3 -m pytest packages\crawler-admin\backend\tests -q -k costco` → 31 passed.
