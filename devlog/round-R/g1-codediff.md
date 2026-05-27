# Round R G1 code-diff evidence

## Source reports consumed

- `g1-base-report.md` (base schema/helpers) — present
- `g1-a1-report.md` (emart) — present
- `g1-a2-report.md` (homeplus) — present
- `g1-a3-report.md` (lottemart) — present
- `g1-a4-report.md` (costco) — present
- `g1-frontend-report.md` (frontends/API) — present
- `cocodalin-seed-report.md` (cocodalin seed) — present
- `g1-regression-audit.md` (regression audit) — present
- `g1-seed-report.md` (4-mart seed) — PENDING / missing at consolidation time

## Files changed extracted per report

- `g1-base-report.md`: `source_utils.py`, `test_source_utils_g1.py`, `models.py`, `test_models.py`, `b2c3d4e5f6a7_round_r_g1_product_columns_and_price_history.py`, `HOTDEAL_HEAD_PENDING.md`.
- `g1-a1-report.md`: Emart crawler, entrypoints, plugin YAML, Emart category HTML fixture, Emart G1 tests.
- `g1-a2-report.md`: Homeplus crawler, Homeplus category-tree fixture, Homeplus G1 tests; working tree also contains HYPER/EXP list fixtures.
- `g1-a3-report.md`: Lottemart crawler and Lottemart G1/legacy test assertions/fixtures.
- `g1-a4-report.md`: Costco crawler, entrypoints, plugin metadata, Costco G1 tests.
- `g1-frontend-report.md`: crawler-admin Crawlers/DataReview pages; db-admin Products page/table/API; web `/compare`, category, product-detail, mart grid/types; web-api snapshot/search/products routes.
- `cocodalin-seed-report.md`: Cocodalin seed importer service, CLI wrappers, importer tests and fixture.
- `g1-regression-audit.md`: audit-only report; no completed files-changed section, but proposed Lottemart crawler/test work overlaps `g1-a3-report.md`.
- `g1-seed-report.md`: PENDING / missing.

## Consolidated files changed table

| file | mart/scope | LOC added (approx) | nature of change |
|---|---:|---:|---|
| `packages\crawler-admin\backend\crawlers\marts\source_utils.py` | base/common | ~90 | G1 URL normalization, unit-price parser, canon/source helper block. |
| `packages\crawler-admin\backend\tests\test_source_utils_g1.py` | base/common | ~74 | Focused regression coverage for common G1 helpers. |
| `packages\db-admin\backend\storage\models.py` | base/db | ~30 | Product G1 mart-native columns plus PriceHistory model. |
| `packages\db-admin\backend\tests\test_models.py` | base/db | small | Schema integration expectation updated for price_history. |
| `packages\db-admin\backend\storage\migrations\versions\b2c3d4e5f6a7_round_r_g1_product_columns_and_price_history.py` | base/db | ~74 | Alembic revision for product columns and price_history. |
| `packages\db-admin\backend\storage\migrations\versions\HOTDEAL_HEAD_PENDING.md` | base/db | ~2 | Marker that hotdeal head split remains deferred. |
| `packages\crawler-admin\backend\crawlers\marts\emart\crawler.py` | emart | large rewrite | Category CSR/card extraction and G1 fields. |
| `packages\crawler-admin\backend\crawlers\marts\emart\entrypoints.py` | emart | small | Four-entrypoint facade retained; sale/catalog URLs point at category pages. |
| `packages\crawler-admin\backend\crawlers\marts\emart\plugin.yaml` | emart | small | Contract/strategy/selectors updated for category card HTML. |
| `packages\crawler-admin\backend\tests\fixtures\emart_category_sample.html` | emart | fixture | Trimmed 5-card fixture from G0 patterns. |
| `packages\crawler-admin\backend\tests\test_emart_crawler_g1.py` | emart | new test | G1 parser/crawl assertions for itemId, salestrNo, seller, unit price, URLs. |
| `packages\crawler-admin\backend\crawlers\marts\homeplus\crawler.py` | homeplus | rewrite | HYPER/EXP split, stable item URL identity, dynamic-scroll safety stop. |
| `packages\crawler-admin\backend\tests\fixtures\homeplus_category_tree_g1.json` | homeplus | fixture | G1 category-tree seed fixture exported for G2. |
| `packages\crawler-admin\backend\tests\fixtures\homeplus_list_sample.html` | homeplus | fixture | HYPER list fixture for parser tests. |
| `packages\crawler-admin\backend\tests\fixtures\homeplus_express_list_sample.html` | homeplus | fixture | EXP list fixture for parser tests. |
| `packages\crawler-admin\backend\tests\test_homeplus_crawler_g1.py` | homeplus | new test | Fixture-based G1 regression tests. |
| `packages\crawler-admin\backend\crawlers\marts\lottemart\crawler.py` | lottemart | targeted rewrite | Removed UUID URL fallback; canonical OS+EAN-13 extraction and G1 fields. |
| `packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py` | lottemart | new test | UUID ignore, EAN canonical URL, href fallback, UUID-only drop coverage. |
| `packages\crawler-admin\backend\crawlers\marts\costco\crawler.py` | costco | rewrite | /c/cos category tree, /p/ product key, pagination, unit price, canon hash. |
| `packages\crawler-admin\backend\crawlers\marts\costco\entrypoints.py` | costco | new | Four-entrypoint convention support. |
| `packages\crawler-admin\backend\crawlers\marts\costco\plugin.yaml` | costco | small | Plugin entrypoint metadata updated. |
| `packages\crawler-admin\backend\tests\test_costco_crawler_g1.py` | costco | new test | Category/listing/canonical/unit-price/pagination constants coverage. |
| `packages\crawler-admin\backend\services\cocodalin_seed_importer.py` | cocodalin seed | new service | JSON/CSV/live importer, matching, idempotent price_history insertion. |
| `packages\crawler-admin\backend\cli\cocodalin_seed.py` | cocodalin seed | new CLI | CLI wrapper for source, dry-run, DB URL. |
| `crawler_admin\backend\cli\cocodalin_seed.py` | cocodalin seed | new compat | Repo-root module compatibility wrapper. |
| `packages\crawler-admin\backend\tests\test_cocodalin_seed_importer.py` | cocodalin seed | new test | Exact/name/unmatched/idempotent/dry-run coverage. |
| `packages\crawler-admin\frontend\src\pages\Crawlers\Crawlers.jsx` | crawler-admin frontend | medium | Live elapsed ticker/spinner and per-mart counters. |
| `packages\crawler-admin\frontend\src\pages\Crawlers\Crawlers.module.css` | crawler-admin frontend | small | Elapsed badge and counter chip styles. |
| `packages\crawler-admin\frontend\src\pages\DataReview\DataReviewPage.jsx` | crawler-admin frontend | medium | G1 product fields prioritized in review grids. |
| `packages\db-admin\frontend\src\pages\Products\ProductTable.jsx` | db-admin frontend | medium | Mart/native/unit/seller/category columns. |
| `packages\db-admin\frontend\src\pages\Products\Products.jsx` | db-admin frontend | medium | Native category tree sidebar skeleton grouped by path. |
| `packages\db-admin\frontend\src\pages\Products\Products.module.css` | db-admin frontend | small | Seller badge and category tree sidebar styles. |
| `packages\db-admin\backend\api\routes\products.py` | db-admin API | small | Pass-through G1 product columns in list/detail API. |
| `packages\web-frontend\src\App.tsx` | web frontend | small | /compare route wired to price comparison entry. |
| `packages\web-frontend\src\pages\ComparePage.tsx` | web frontend | new/medium | Top-level category-only price comparison entry. |
| `packages\web-frontend\src\pages\CategoryPage.tsx` | web frontend | medium | Sticky drilldown and descendant category fetch. |
| `packages\web-frontend\src\pages\ProductDetailPage.tsx` | web frontend | medium | Mart table unit price/pack and seller badge; canonical URL preferred. |
| `packages\web-frontend\src\components\MartPriceGrid.tsx` | web frontend | new/medium | G1 mart alias fields for cards/grid. |
| `packages\web-frontend\src\types.ts` | web frontend | small | G1 mart alias fields added to types. |
| `packages\web-api\backend\services\snapshot_repo.py` | web API | small | Optional mart alias columns detected dynamically. |
| `packages\web-api\backend\services\search.py` | web API | small | Category filter expands to descendants. |
| `packages\web-api\backend\api\routes\products.py` | web API | small | Product detail mart_aliases include G1 fields. |

## Actual git diff stat capture

- Span selected: `HEAD~1` because the only commit dated today is `d638a97` and Round R G1 work is currently in the working tree after that baseline.
- Command captured: `git --no-pager diff --stat=120,80 HEAD~1 -- <Round-R paths>`
- Note: git diff stat only includes tracked paths. New untracked G1 files are included in the table above using report/file line-count estimates.

```text
packages/crawler-admin/backend/crawlers/marts/costco/crawler.py         | 1064 +++++++++++++------------------
 packages/crawler-admin/backend/crawlers/marts/costco/plugin.yaml        |   21 +-
 packages/crawler-admin/backend/crawlers/marts/emart/crawler.py          | 1317 +++++++++++++++++++--------------------
 packages/crawler-admin/backend/crawlers/marts/emart/entrypoints.py      |   24 +-
 packages/crawler-admin/backend/crawlers/marts/emart/plugin.yaml         |   37 +-
 packages/crawler-admin/backend/crawlers/marts/homeplus/crawler.py       |  371 ++++++++---
 packages/crawler-admin/backend/crawlers/marts/source_utils.py           |   90 +++
 packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.jsx         |   76 ++-
 packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.module.css  |    9 +-
 packages/crawler-admin/frontend/src/pages/DataReview/DataReviewPage.jsx |    9 +-
 packages/db-admin/backend/api/routes/products.py                        |   20 +
 packages/db-admin/backend/storage/models.py                             |   35 ++
 packages/db-admin/backend/tests/test_models.py                          |    4 +-
 packages/db-admin/frontend/src/pages/Products/ProductTable.jsx          |   25 +-
 packages/db-admin/frontend/src/pages/Products/Products.jsx              |   70 ++-
 packages/db-admin/frontend/src/pages/Products/Products.module.css       |   12 +
 packages/web-api/backend/api/routes/products.py                         |    9 +
 packages/web-api/backend/services/search.py                             |   14 +-
 packages/web-api/backend/services/snapshot_repo.py                      |   72 ++-
 packages/web-frontend/src/App.tsx                                       |    6 +-
 packages/web-frontend/src/pages/CategoryPage.tsx                        |   91 +--
 packages/web-frontend/src/pages/ProductDetailPage.tsx                   |   27 +-
 packages/web-frontend/src/types.ts                                      |    9 +
 23 files changed, 1891 insertions(+), 1521 deletions(-)
[stderr]
warning: in the working copy of 'packages/crawler-admin/backend/crawlers/marts/costco/crawler.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/crawler-admin/backend/crawlers/marts/emart/crawler.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/crawler-admin/backend/crawlers/marts/emart/entrypoints.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/crawler-admin/backend/crawlers/marts/source_utils.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/crawler-admin/frontend/src/pages/DataReview/DataReviewPage.jsx', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/db-admin/backend/api/routes/products.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/db-admin/backend/storage/models.py', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/db-admin/frontend/src/pages/Products/ProductTable.jsx', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/db-admin/frontend/src/pages/Products/Products.jsx', CRLF will be replaced by LF the next time Git touches it
warning: in the working copy of 'packages/web-api/backend/services/search.py', CRLF will be replaced by LF the next time Git touches it
```

Shortstat:

```text
23 files changed, 1891 insertions(+), 1521 deletions(-)
```
