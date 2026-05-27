# Round S — s-verify-live report

## Lottemart URL / UUID guard

- URL normalizer is OS-code only and rejects UUID identifiers: `packages/crawler-admin/backend/crawlers/marts/source_utils.py:241-248` returns `https://lottemartzetta.com/products/OS{code}/details` and raises `ValueError` for UUID-shaped input.
- Parser identity extraction prefers `retailerProductId` / `stdGoodsCd`, then only accepts hrefs matching `/OS<13 digits>`: `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py:859-889`.
- Product entity conversion and SPA card fallback both call `normalize_lottemart_url(ean13)` after rejecting missing EAN13: `crawler.py:997-1000`, `crawler.py:1233-1235`.
- Single-product plugin template is now OS-detail only: `packages/crawler-admin/backend/crawlers/marts/lottemart/plugin.yaml:49-52`.
- Unit tests added/locked: `packages/crawler-admin/backend/tests/test_lottemart_crawler_g1.py:85-100` rejects UUID-only hrefs and converts UUID `goodsUrl` + OS EAN into `/products/OS.../details`.

## Costco URL / source

- Costco listing URL identity is `/p/<digits>` only: `_PRODUCT_RE` is used by `_extract_product_identity`, which returns `normalize_costco_url(path_with_slug, code)` in `packages/crawler-admin/backend/crawlers/marts/costco/crawler.py:163-170`.
- Source/vendor fields are self-owned: `_card_to_record` sets `mart='costco'`, `external_seller=False`, and returns `inject_source_field(record, 'costco')` in `crawler.py:319-344`.
- Canonical URL builder: `packages/crawler-admin/backend/crawlers/marts/source_utils.py:267-273` returns `https://www.costco.co.kr{path}/p/{p_number}`.

## Live probe results

Raw probe file: `devlog/round-S/s-verify-live-probe.md`.

| mart | status_code | html_len | block marker | final_url |
|---|---:|---:|---|---|
| emart | 301 | 15147 | none | https://emart.ssg.com/disp/category.ssg?dispCtgId=6000095494 |
| homeplus | 200 | 10390 | bot | https://mfront.homeplus.co.kr/search?keyword=%ED%95%A0%EC%9D%B8&page=1 |
| lottemart | 200 | 1559377 | waf, 429 | https://lottemartzetta.com/products |
| costco | 200 | 2055668 | bot, robot | https://www.costco.co.kr/Foods/c/cos_10 |

Markers are literal strings found in the fetched HTML prefix; no retry or browser bypass was attempted.

## 4-mart promo_label fixture coordinates

Exact `1+1` / `2+1` fixture markers:

- Lottemart: `packages/crawler-admin/backend/tests/fixtures/lottemart/operator_capture_3cards.html:57` has product name `[1+1] ...`; line 62 has `offer.description = "1+1 행사"`.
- Emart: no exact `1+1` / `2+1` string found under `tests/fixtures/emart`; closest promo/discount markup is `sale_listing_5cards.json:180-185` (`discountRate`, `primaryPrice`, `strikeOutPrice`).
- Homeplus: no exact `1+1` / `2+1` string found under `tests/fixtures/homeplus`; promo event fixture is `sale_listing_3items.json:25-39` (`eventInfo`, `eventInfoList`, `eventFlagList.label = "함께할인"`).
- Costco: no exact `1+1` / `2+1` string found under `tests/fixtures/costco`; promo/special-offer marker is `special_offers_5cards.html:1` (`sip-decals`, `decal_SpecialPriceOffers`).

## Verification

- `py -m pytest packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py packages\crawler-admin\backend\tests\test_source_utils_g1.py packages\crawler-admin\backend\tests\test_costco_crawler.py -q` → `46 passed in 2.60s`.
