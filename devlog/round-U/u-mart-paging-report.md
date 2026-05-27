# Round U mart paging report

## Summary
- Lottemart 50-row limit cause: `promotions` HTML hydrates only 50 `productEntities`, while the storefront product-page API returns 300 decorated products per cursor page.
- Homeplus 300-row limit cause: crawler default `MAX_ITEMS=300` plus `MAX_PAGES=1`; live category API exposes `totalCount`/`totalPage` and accepts `perPage=100`.
- No new concurrency was added. Page loops remain sequential and sleep between live page fetches.

## Lottemart live probes
- `https://lottemartzetta.com/promotions`: HTTP 200, `__INITIAL_STATE__=true`, parsed `productEntities=50`.
- Initial state catalogue: `totalProducts=300`, `productGroups[0].products=300`, `nextPageToken` present, but only 50 product entity records are hydrated.
- `https://lottemartzetta.com/search?query=할인&page=1` and `page=2`: both HTTP 200 with same-size SPA/SSR shell, no useful `totalCount`/`hasMore` fields.
- Product-page API: `/api/webproductpagews/v6/product-pages?maxProductsToDecorate=300&maxPageSize=300&includeAdditionalPageInfo=true&tag=web&tag=category-item`
  - page 1: HTTP 200, raw 300, parsed 300, `nextPageToken=true`.
  - page 2 with same `requests.Session`: HTTP 200, raw 300, parsed 300, first product differs from page 1.
- Bounded crawler simulation (`MAX_PAGES=2`): SUCCESS, 600 items, source raw 600, pages attempted 2.
- Page sleep: 3.0s between Lottemart live page fetches.

## Homeplus live probes
- `category/item.json?categoryId=3&categoryDepth=0&delivery=HYPER_DRCT`:
  - `perPage=20`: totalCount 105, totalPage 6.
  - `perPage=100`: page 1 len 100, page 2 len 5, page 3 len 0; page 1/2 first item differs.
- Additional sampled HYPER category totals: categoryId 1=36, 2=25, 5=234, 10=253, 15=128, 27=135.
- Express path was probed without delivery filter: `/express/category/item.json?categoryId=3&categoryDepth=0&page=1&perPage=100` returned HTTP 200, len 0, totalCount 0.
- Small full-loop simulation (`STORE_TYPES=('HYPER',)`, `CATEGORY_IDS=(1,)`, cap off): 36 items, 1 request, stopped on totalPage.
- Page sleep: Homeplus default is now 2.5-5.0s between sequential page fetches.

## Code changes
- Lottemart default live path now uses product-page API cursor pagination; legacy HTML search path remains for overridden query tests/diagnostics.
- Lottemart parses `productGroups[].decoratedProducts` via existing API product mapper and stops on no token/no rows/no new rows/MAX_PAGES/MAX_REQUESTS.
- Homeplus default cap removed (`MAX_ITEMS=None`), `MAX_PAGES=None` means continue until API `totalPage` ends, and `perPage=100` is used.
- Homeplus HYPER keeps `delivery=HYPER_DRCT`; EXP uses express endpoints without delivery.

## Regression
- Requested unpatched command exceeded 5 minutes and was stopped after continuous progress, per instruction.
- Sleep-patched focused regression: `83 passed, 2 skipped, 28 deselected` for Lottemart/Homeplus tests in `tests/test_lottemart_crawler.py tests/test_homeplus_crawler.py tests/test_mart_crawlers.py -k "lottemart or homeplus"`.
- Sleep-patched full selected suite reached an unrelated pre-existing Emart failure in `test_crawl_http_error`; Emart was not modified for this slot.
