# t-lottemart-legacy report

## 채택 커밋
- 채택 base: `a3cb377 fix(lottemart): collect 200+ items via Playwright API intercept scroll strategy`에서 최신 `lottemart/crawler.py`의 productEntities 파서/R 필드 구조를 확인.
- 요청에 따라 Playwright/XHR scroll runtime은 제거하고, `c0b720f feat: complete all crawlers`의 requests legacy 방향(HTTP GET + HTML/JSON parse)을 복원.
- 인용: `a3cb377` stat `314 insertions(+), 50 deletions(-)`, `c0b720f` walletSavior path stat `20 insertions(+), 2 deletions(-)`.

## 라이브 probe
| name | URL | status | len | markers |
|---|---|---:|---:|---|
| home | https://lottemartzetta.com/ | 200 | 868613 | __INITIAL_STATE__, productEntities, awswaf, products |
| promotions | https://lottemartzetta.com/promotions?source=header%20button | 200 | 1700556 | __INITIAL_STATE__, productEntities, awswaf, products, OS880 |
| search_sale | https://lottemartzetta.com/search?query=%ED%95%A0%EC%9D%B8&page=1 | 200 | 1652534 | __INITIAL_STATE__, productEntities, awswaf, products, OS880 |
| search_milk | https://lottemartzetta.com/search?query=%EC%9A%B0%EC%9C%A0&page=1 | 200 | 1652534 | __INITIAL_STATE__, productEntities, awswaf, products, OS880 |
| detail_os | https://lottemartzetta.com/products/OS8801114111147/details | 200 | 615380 | __INITIAL_STATE__, productEntities, awswaf, products, OS880 |
| api_products_get | https://lottemartzetta.com/api/webproductpagews/v6/products | 405 | 286 | products |

Raw: `devlog/round-T/lottemart-probe.json`.

## 코드 변경 요약
- `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py:46,284`: requests-only crawl, `SLEEP_BETWEEN_LIVE_GETS=3.0`, no gather/semaphore/browser fallback.
- `crawler.py:557,574,877,1267`: UUID guard path, `mart_native_code`, OS canonical URL, `canon_hash`, `promo_label`, DB Product insert.
- `packages/crawler-admin/backend/crawlers/marts/source_utils.py:241`: `normalize_lottemart_url()` accepts `OS...` and rejects UUID.
- `packages/crawler-admin/backend/crawlers/marts/lottemart/plugin.yaml`, `entrypoints.py`: Round T requests legacy capability/docs, Playwright wording removed.
- Tests updated/added: `test_lottemart_crawler.py:316`, `test_lottemart_crawler_g1.py:112,120`.

## 라이브 crawl + DB 저장
- Live crawl: status `success`, strategy `requests`, items `20`, fetch `200`, bytes `1652534`, sleep `3.0`.
- DB Product model insert: inserted `10`, skipped `0`, failed `[]`.

`SELECT mart, mart_native_code, name, NULL as price, canonical_url as url FROM products WHERE mart='lottemart' LIMIT 10` 결과(현재 products schema에는 price/url 컬럼이 없어 alias 사용):

| mart | mart_native_code | name | price | url |
|---|---|---|---:|---|
| lottemart | 0430001251062 | 제스프리 골드키위 (EA) | NULL | https://lottemartzetta.com/products/OS0430001251062/details |
| lottemart | 2700000034736 | 손질 오징어 (마리) | NULL | https://lottemartzetta.com/products/OS2700000034736/details |
| lottemart | 8801007033686 | CJ 동치미 냉면육수 (1인) (300G) | NULL | https://lottemartzetta.com/products/OS8801007033686/details |
| lottemart | 8801045440040 | 오뚜기 옛날참기름 (450ML) | NULL | https://lottemartzetta.com/products/OS8801045440040/details |
| lottemart | 8801114119426 | 풀무원 국산 부침두부 (340G) | NULL | https://lottemartzetta.com/products/OS8801114119426/details |
| lottemart | 8801117165802 | 오리온 썬핫스파이시맛 (66G) | NULL | https://lottemartzetta.com/products/OS8801117165802/details |
| lottemart | 8801118250996 | 롯데 빠삐코 (130ML) | NULL | https://lottemartzetta.com/products/OS8801118250996/details |
| lottemart | 8809002360110 | 애호박 (개) | NULL | https://lottemartzetta.com/products/OS8809002360110/details |
| lottemart | 8809214203632 | 행복생생란 (특란, 30입) (1.8KG) | NULL | https://lottemartzetta.com/products/OS8809214203632/details |
| lottemart | 8809597441812 | 햇 양파 (3KG) | NULL | https://lottemartzetta.com/products/OS8809597441812/details |

Raw: `devlog/round-T/lottemart-live-db-result.json`.

## 테스트
- PASS: `py -3 -m pytest packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py -q` → `8 passed`.
- PASS: `py -3 -m pytest packages\crawler-admin\backend\tests\test_lottemart_crawler.py packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py packages\crawler-admin\backend\tests\test_mart_crawlers.py -q -m "not live" -k "lottemart"` → `51 passed, 49 deselected`.
- Full `test_mart_crawlers.py -m "not live"` is not claimed: it reaches unrelated emart/current-slot failure `TestCrawlWithMock::test_crawl_http_error` after `56 passed`; emart folder was not modified.
