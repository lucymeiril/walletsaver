# Round T — t-cocodalin-costco report

## Live probe

| Mart | URL | Status | Length | Sample |
| --- | --- | --- | ---: | --- |
| cocodalin | `https://www.cocodalin.com/api/front/bestLikeProducts` | `HTTP/1.1 200` | 11,451 | `[{"category_name":"가공식품","from_date":"2026.05.11",..."product_id":357,...}]` |
| cocodalin | `https://www.cocodalin.com/api/front/productList/10` | `HTTP/1.1 200` | 19,548 | `[{"category_name":"가공식품","from_date":"2026.05.18",..."product_id":9587,...}]` |
| costco | `https://www.costco.co.kr/` | `HTTP/1.1 200 OK` | 2,705,878 | `<!DOCTYPE html><html lang="ko"...<title>코스트코 온라인몰 | 코스트코 코리아</title>...` |
| costco | `https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers` | `HTTP/1.1 200 OK` | 2,754,976 | `<!DOCTYPE html><html lang="ko"...<title>스페셜 할인 | 코스트코 코리아</title>...` |
| costco | `https://www.costco.co.kr/c/cos_10` | `HTTP/1.1 200 OK` | 2,099,460 | `<!DOCTYPE html><html lang="ko"...<title>식품 | 코스트코 코리아</title>...` |

Saved bodies/headers: `devlog/round-T/probe/`.

## Git archaeology

- `483ae4b` contains `packages/crawler-admin/backend/crawlers/marts/cocodalin/crawler.py` old API base using `bestLikeProducts`/`saleSummary`.
- `c1f40de` also contains cocodalin legacy paths, but the archived blob is formatting-damaged.
- `c0b720f`, `c1f40de`, `483ae4b` did not contain `packages/crawler-admin/backend/crawlers/marts/costco/`; current Round R code is the restored base for costco.
- `_disabled_round_r/cocodalin/` was inspected only; not modified. No `_disabled_round_r/costco/` backup exists in this checkout.

## Code changes

- `packages/crawler-admin/backend/crawlers/marts/cocodalin/crawler.py`
  - Restored direct API crawler shape for `bestLikeProducts` + 12 `productList/{cat_id}` endpoints.
  - Added Round R fields in item attributes: `mart="cocodalin"`, `mart_native_code`, `source_record_key`, `canon_hash`, `external_seller=false`, category ids/paths, canonical URL, and `promo_label`/`promo_type`.
  - Kept sleeps; no concurrency or speed increase.
- `packages/crawler-admin/backend/crawlers/marts/costco/crawler.py`
  - Kept own-site parser (`costco.co.kr`, `/p/<code>` identity) and `external_seller=false`.
  - Added `promo_label`/`promo_type` propagation to records, attributes, and `DiscountItem`.

## Live parse + DB save

- Parsed live saved responses: `cocodalin=53`, `costco=47`.
- Inserted/upserted 5 live rows per mart into `packages/db-admin/backend/walletguardian.db`.
- DB schema in this checkout lacked `products.price`; added DB-local `price`, `sale_price`, `promo_label`, `promo_type` columns so the requested SELECT works.

```sql
SELECT mart, mart_native_code, name, price
FROM products
WHERE mart IN ('cocodalin','costco')
LIMIT 10;
```

| mart | mart_native_code | name | price |
| --- | --- | --- | ---: |
| cocodalin | 10460 | HAVANNA 밀크캐러멜 스프레드 1KG | 9990 |
| cocodalin | 10462 | ARTISAN 라자냐 키트 692G X 2 | 17990 |
| cocodalin | 2984 | C-WEED 찹쌀 김부각 250G | 14990 |
| cocodalin | 357 | GAROFALO 스파게티면 500G X 8 | 14990 |
| cocodalin | 9587 | ALTIST 설탕대신 알룰로스 1.5KG | 13990 |
| costco | 502986 | 얼라이브 원스데일리 멀티비타민 1,706mg x 100정 | 26990 |
| costco | 527203 | 제스프리 골드키위 5.7kg(37~41입) | 64900 |
| costco | 625871 | 휴럼 트루락 생 프리바이오틱스 4.5g x 30포 x 3 | 27990 |
| costco | 626186 | 수지스 그릴드 닭가슴살 1.8kg | 27490 |
| costco | 657523 | 종근당건강 락토핏 플러스 듀얼바 이오틱스 2000mg x 200포 | 35490 |

## Tests

- Passed: `cd packages/crawler-admin/backend; py -m pytest tests/test_cocodalin_crawler.py tests/test_kokodalin_crawler.py tests/test_costco_crawler_g1.py -q` → `18 passed`.
- Passed: `py -m pytest tests/test_mart_crawlers.py -q -k "cocodalin or Cocodalin"` → `2 passed, 68 deselected`.
- Full `test_mart_crawlers.py` currently stops on pre-existing Homeplus assertion (`test_homeplus_json_preserves_unit_and_source_fields` expects `www.homeplus.co.kr` URL but current code emits `mfront.homeplus.co.kr`). Per task restriction, Homeplus was not modified.
