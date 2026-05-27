# Round U native category tree report

## Native tree collection

| mart | live source | raw nodes | mapped in seed | coverage | file |
|---|---|---:|---:|---:|---|
| emart | `https://frontapi.ssg.com/dp/api/v1/category/gnb/7018?dispDvicDivCd=10` | 1983 | 33 | 1.7% | `devlog/round-U/category-native-emart.json` |
| homeplus | `https://mfront.homeplus.co.kr/category/mobile/getMap.json` | 451 | 28 | 6.2% | `devlog/round-U/category-native-homeplus.json` |
| lottemart | `https://lottemartzetta.com/` | 320 | 33 | 10.3% | `devlog/round-U/category-native-lottemart.json` |
| costco | `https://www.costco.co.kr/` | 473 | 19 | 4.0% | `devlog/round-U/category-native-costco.json` |

Collection notes:
- All four files were produced from live calls with serial requests and 3 second sleeps between mart calls.
- Emart source is the GNB API referenced by `https://emart.ssg.com/main.ssg`: `frontapi.ssg.com/dp/api/v1/category/gnb/7018?dispDvicDivCd=10`.
- Homeplus source is the mobile category map endpoint discovered from the current Vite bundle: `/category/mobile/getMap.json`.
- Lottemart source is `window.__INITIAL_STATE__.data.categories` from `lottemartzetta.com`. Old commit grep found prior `__INITIAL_STATE__` crawler code in `a3cb377:packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py`, but no reusable category seed endpoint.
- Costco source is rendered homepage category HTML; hierarchy is inferred from dotted `/c/cos_*` category codes.

## Unified seed

- Seed file: `packages/shared/data/unified_category_seed.yaml`
- Unified categories in seed: 46
- Native mappings in seed: 113
- Top-level unified roots (10): fruits, vegetables, rice_grains, meat_eggs, seafood, dairy, processed_food, beverages, living, pet.
- `coffee_tea` is under `beverages`, keeping the top-level set to 10 while still preserving coffee/tea leaves.
- Ambiguous combined native buckets such as `사과/배` are intentionally mapped to `fruits` rather than `fruits.apple` or `fruits.pear`.
- Clear leaf mappings exist where native data has leaves, for example Emart `6000213116` → `fruits.apple`, `6000213117` → `fruits.pear`, `6000213129` → `fruits.kiwi`.

## Applied DB verification

- Command: `DATABASE_URL=sqlite:///E:/pdf/capston01/packages/db-admin/backend/walletguardian.db py -3 scripts\seed_unified_categories.py`
- Idempotence rerun: `categories_inserted=0`, `categories_updated=46`, `mappings_inserted=0`, `mappings_updated=113`, `mappings_conflict=0`.
- `SELECT COUNT(*) FROM unified_categories;` → 46
- `SELECT COUNT(*) FROM mart_category_mappings;` → 113

## Mart coverage detail

- emart: 33 clear mappings out of 1983 raw native nodes (1.7%).
- homeplus: 28 clear mappings out of 451 raw native nodes (6.2%).
- lottemart: 33 clear mappings out of 320 raw native nodes (10.3%).
- costco: 19 clear mappings out of 473 raw native nodes (4.0%).
