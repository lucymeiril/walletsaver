# Checkpoint after pending 025

- mode: `proposal_only`
- baseline: pass41 — 5,280 loaded / 3,916 pending
- group: `pending/025` (Emart `건강식품`)
- source files: `pending/025/001.json`, `pending/025/002.json`
- observations opened: **35**
- already-classified exclusions: **0**
- strict classification reviews: **35**
- distinct source listings: **35**
- existing-leaf proposals: **0**
- holds: **35**
- proposal: `proposals/emart-health-foods-025.json`

## Accounting verification

All raw indices `ingestion:94:0` through `ingestion:94:34` were checked. Pagination-boundary records 10, 21 and 34 were explicitly fetched by raw id and are also `review_status=pending`; therefore the correct exclusion count is 0.

## Policy result

The broad `건강식품` shelf is not enough to create or infer supplement leaves. Repository evidence shows prior `food.health.supplements.*` identifiers are mainly held/new-taxonomy candidates rather than confirmed pass41 catalog leaves. Therefore none of these 35 rows is promoted to an existing leaf.

Reused established held candidate families where precedent exists:
- pure honey -> `food.seasonings.syrups.honey`
- drinkable lemon juice/concentrate -> `food.drinks.concentrates.fruit`
- ready-to-drink protein beverages -> `food.drinks.other.protein`
- protein shake/supplement -> `food.health.supplements.protein`
- multivitamins -> `food.health.supplements.multivitamin`
- collagen jelly -> `food.health.supplements.collagen`

Other products are `held_taxonomy_policy` without inventing a stable leaf id: calcium/zinc/vitamin products, probiotics, lutein, omega-3, red-ginseng health products, root functional drinks and meal/nutrition drinks.

## Prior coverage / explicit decisions

A group-marker search and five source-key batches covering all 35 listings did not surface a prior proposal claiming pending025 coverage. The same five batches surfaced no `review-decisions-input.json` collision. The 431 explicit decisions remain unchanged.

## Execution boundary

No DB import/rebuild, taxonomy code edit, repository test or idempotence run was executed in Chat.

## Next resume point

Continue with `pending 024` — Emart `커피/원두/차`, **36 observations / 36 titles**, files `001.json` and `002.json`. Directly inspect each row's review status, then measure exact prior-proposal raw/source-key coverage before trusting any historical proposal.
