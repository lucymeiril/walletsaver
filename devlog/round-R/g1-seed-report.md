# Round R G1 Seed Report

Generated: 2026-05-26T23:38:48

## Live vs fixture
| mart | mode | reason |
| --- | --- | --- |
| costco | live-blocked | bot/block marker: bot fetching https://www.costco.co.kr/c/cos_10.1 |


## Counts per mart
| mart | count |
| --- | --- |
| costco | 3 |
| emart | 5 |
| homeplus | 3 |
| lottemart | 5 |


## Distinct native category paths
| mart | distinct_category_paths |
| --- | --- |
| costco | 2 |
| emart | 1 |
| homeplus | 3 |
| lottemart | 5 |


## Sample dump (new columns visible)
| mart | mart_native_code | mart_native_category_path | unit_price_displayed | unit_price_basis_raw |
| --- | --- | --- | --- | --- |
| costco | 602630 | 식품 |  |  |
| costco | 801234 | 식품 > 쌀/잡곡 |  |  |
| costco | 999999 | 식품 > 쌀/잡곡 |  |  |
| emart | 1001234567890 | 과일/채소 | 99.0 | 10g |
| emart | 1002222222222 | 과일/채소 | 3160.0 | 100g |
| emart | 1003333333333 | 과일/채소 |  |  |
| emart | 1004444444444 | 과일/채소 | 288.0 | 100ml |
| emart | 1005555555555 | 과일/채소 | 3980.0 | 1kg |
| homeplus | 123456789 | 정육 | 200.0 | 10G |
| homeplus | 222333444 | 익스프레스 | 356.0 | 100ML |


## Reproduction one-liner
`py -3 packages\crawler-admin\backend\scripts\round_r_g1_seed.py --live --marts emart --limit 5`

DB URL used: `sqlite:///E:/pdf/capston01/packages/db-admin/backend/walletguardian.db`

## Blockers encountered
None
