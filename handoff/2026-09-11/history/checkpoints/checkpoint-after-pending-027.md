# Checkpoint after pending 027

- mode: `proposal_only`
- baseline: pass41 — 5,280 loaded / 3,916 pending
- group: `pending/027` (Emart `베스트`)
- source files: `pending/027/001.json`, `pending/027/002.json`
- observations opened: **33**
- already-classified exclusions: **0**
- strict classification reviews: **33**
- distinct source listings: **33**
- existing-leaf proposals: **31**
- holds: **2**
- proposal: `proposals/emart-best-027.json`

## Review notes

The broad `베스트` shelf is a promotion/navigation surface, but these 33 rows are individual `itemView` products. Product title/form therefore wins instead of blanket promotion hold.

Existing-leaf examples include fresh tomato/grape/kiwi/apple/banana, mushroom/scallion/sweet potato/leaf/cucumber/cabbage/pepper/sprouts, shell eggs, fresh pork, crab, plain milk, water, bag ramen, tofu, toilet tissue and prepared soup/stew.

Two rows are held rather than forced into neighboring leaves:
- fresh fig -> candidate `food.produce.fruit.fig`
- `고메함박스테이크152g` -> candidate `food.meals.prepared.hamburg_steak`

Two opaque milk titles were resolved with exact retailer-product identity evidence:
- key `0000006615474`, `1000ml 나100%` -> `food.dairy.milk.plain`
- key `0000007095585`, `2.3L` -> `food.dairy.milk.plain`

Cross-group overlap is intentionally preserved in strict group accounting and deferred to final global source-key dedupe:
- key `0000006615474` is also present in pending 026.
- key `1000768602033` (`NEW 송탄식 부대찌개 1.467kg`) is also present in pending 020.

## Explicit-decision collision screen

All 33 source keys were checked in five repository-search batches. No `review-decisions-input.json` hit was found. The 431 explicit decisions were not modified.

## Execution boundary

No DB import/rebuild, taxonomy code edit, repository test or idempotence run was executed in Chat.

## Next resume point

Continue with `pending 026` (35 observations / 35 titles, Emart `우유/유제품`). Open both pending fragments and measure already-classified status and exact prior-proposal coverage before trusting any historical proposal. The source key `0000006615474` has already been reviewed in 027 but must still remain in 026 group accounting; global dedupe happens after the sweep.
