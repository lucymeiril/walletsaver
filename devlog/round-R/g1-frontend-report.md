# G1 frontend report

## Modified/created files

### crawler-admin frontend
- `packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.jsx`
  - Replaced frozen `0초 경과` progress text with live elapsed-time ticker + spinner.
  - Added per-mart counters: 총 수집/신규/중복/필터됨/오류.
- `packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.module.css`
  - Styles for elapsed badge and counter chips.
- `packages/crawler-admin/frontend/src/pages/DataReview/DataReviewPage.jsx`
  - Prioritized G1 product fields in crawl result/review grids.

### db-admin frontend/backend
- `packages/db-admin/frontend/src/pages/Products/ProductTable.jsx`
  - Added mart, mart_native_code, unit price, external seller, mart_native_category_path columns.
- `packages/db-admin/frontend/src/pages/Products/Products.jsx`
  - Added category tree viewer skeleton grouped by mart_native_category_path.
- `packages/db-admin/frontend/src/pages/Products/Products.module.css`
  - Styles for seller badges and category tree sidebar.
- `packages/db-admin/backend/api/routes/products.py`
  - Additive pass-through of Round R G1 product columns in product list/detail API.

### web frontend/API
- `packages/web-frontend/src/App.tsx`
  - `/compare` now opens a top-level 물가비교 category entry page.
- `packages/web-frontend/src/pages/ComparePage.tsx`
  - New top-level category list entry for price comparison.
- `packages/web-frontend/src/pages/CategoryPage.tsx`
  - Breadcrumb/tree pinned at top; selected category fetch includes backend subcategory expansion.
- `packages/web-frontend/src/pages/ProductDetailPage.tsx`
  - Mart table shows unit price or pack info and `입점셀러` badge; canonical_url preferred.
- `packages/web-frontend/src/components/MartPriceGrid.tsx`, `packages/web-frontend/src/types.ts`
  - G1 mart alias fields supported for card/grid rendering.
- `packages/web-api/backend/services/snapshot_repo.py`
  - Optional new mart alias columns detected dynamically and passed through.
- `packages/web-api/backend/services/search.py`
  - Category filter now includes all descendant categories.
- `packages/web-api/backend/api/routes/products.py`
  - Product detail mart_aliases include G1 fields.

## Screenshot references
- Before screenshots: not captured in this subagent.
- After screenshots: main agent should capture via Playwright MCP:
  - crawler-admin progress/counters + data review G1 fields
  - db-admin products grid + native category tree
  - web `/compare`, category drilldown, product detail mart table

## Build/test results
- `packages/web-frontend`: `npm run build` ✅, `npm test` ✅ (86 tests)
- `packages/crawler-admin/frontend`: `npm test` ✅ (28 tests), `npm run build` ✅
- `packages/db-admin/frontend`: `npm test -- --run` ✅ (23 tests), `npm run build` ✅
- `packages/web-api/backend`: `py -m pytest tests\test_api_search.py tests\test_api_categories.py -q` ✅ (7 passed)
- `packages/db-admin/backend`: `py -m pytest tests\test_admin_management_surfaces.py -q` ✅ (7 passed)
- Lint: existing repo lint failures remain in unrelated files; crawler-admin rerun has only pre-existing errors plus two hook warnings in Crawlers.

## API stubs/pass-throughs
- db-admin products route: pass-through of Product model G1 fields.
- web-api snapshot repo: dynamic optional mart_sku_alias G1 columns, so old snapshots still work.

## Price-comparison tab fix
- File: `packages/web-frontend/src/pages/ComparePage.tsx`
- Before: `/compare` used a placeholder and category entry could land users in product lists.
- After: `/compare` renders only top-level categories via `l1Categories(...)`; product cards are not rendered on entry.

Snippet:
```tsx
fetchCategories()
  .then((data) => setL1(l1Categories(data.categories as CategoryNode[])))
...
<CategoryGrid l1Nodes={l1} loading={loading} />
```

- File: `packages/web-frontend/src/pages/CategoryPage.tsx`
- Before: category page immediately rendered product grid for the selected node only.
- After: breadcrumb/drilldown is sticky at top and product fetch uses backend descendant expansion.

Snippet:
```tsx
<Drilldown ancestors={ancestors} current={currentCategory} children={children} siblings={siblings} />
searchProducts({ category: activeId, sort: sortParam, page: pageParam })
```
