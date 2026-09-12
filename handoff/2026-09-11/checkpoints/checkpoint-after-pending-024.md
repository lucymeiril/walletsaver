# Checkpoint after pending 024

Date: 2026-09-12
Mode: GitHub read/write, proposal_only
Baseline: pass41 — 5,280 loaded / 3,916 pending

## Pending 024 strict review

- Group: `pending/024`
- Shelf: Emart `커피/원두/차`
- Files: `001.json`, `002.json`
- Observations opened: **36**
- Already-classified exclusions: **2**
- New classification reviews: **34**
- Distinct new source listings: **34**
- Existing-leaf proposals: **23**
- Holds: **11**
- Proposal: `proposals/emart-coffee-tea-024.json`

### Already classified exclusions

1. `ingestion:88:10` / `0000008398879` / `화이트골드 커피믹스 180입 (+20입)` -> existing `food.drinks.coffee.mix`; pending only for mixed-package reconciliation.
2. `ingestion:88:16` / `1000579128334` / `[카누] 마일드 로스트 아메리카노 미니 (150입+20입)` -> existing `food.drinks.coffee.instant`; pending only for mixed-package reconciliation.

A shallow status scan initially exposed only the first exclusion. Direct per-record inspection found the second; canonical accounting must use **2 exclusions**, not 1.

## Existing-leaf decisions

23 listings were proposed to confirmed current leaves. Main families:

- RTD coffee/lattes -> `food.drinks.coffee.ready`
- coffee mix -> `food.drinks.coffee.mix`
- powdered/refill instant coffee -> `food.drinks.coffee.instant`
- explicit Earl Grey/iced tea -> `food.drinks.tea.black`
- explicit green tea/matcha -> `food.drinks.tea.green`
- herbal/rooibos tea -> `food.drinks.tea.herbal`
- corn/nurungji tea -> `food.drinks.tea.grain`
- orzo/black-barley tea -> `food.drinks.tea.barley`

Exact product identity was used where the title was insufficient: Osulloc herb edition, Tizen Cafe Orzo, CafeN hazelnut sticks, Real Milk Cafe Latte, and Maxim Original refill.

## Holds

11 listings were held rather than forced into a wrong current leaf:

- two mixed Osulloc tea assortments -> taxonomy-policy hold (`mixed tea assortment`)
- two plum `매실청` -> reuse candidate `food.drinks.tea.fruit_preserve`
- plum `매실액기스` -> taxonomy-policy hold (`plum beverage concentrate/extract`)
- RTD milk tea -> reuse candidate `food.drinks.tea.milk_tea`
- 둥글레차 -> taxonomy-policy hold; combined barley/dunggeulle shelf mapping is not enough to force barley
- lemon juice -> reuse candidate `food.drinks.concentrates.fruit`
- kombucha -> reuse candidate `food.drinks.tea.kombucha`
- 결명자차 -> taxonomy-policy hold; no exact current leaf/strict precedent
- 생강청 -> reuse pending061 candidate `food.drinks.tea.ginger`

## Coverage / collision checks

- No older proposal covering pending024 was confirmed by group-marker search plus exact source-key searches.
- All **34 new source_record_keys** were searched in five batches.
- `review-decisions-input.json` hits: **0**.
- Existing 431 explicit decisions were not changed.

## Not executed

- No DB import/rebuild.
- No taxonomy code modification.
- No repository tests.
- No idempotence run.

Next canonical resume point must be determined from `pending/023` and then written to `CURRENT_STATUS.md`.
