# Checkpoint after pending 022

Mode: **proposal_only / GitHub read-write**  
Baseline: **pass41**  
DB import/rebuild/tests/idempotence: **not executed**

## accounting
- pending group: `022`
- mart/shelf: Emart `친환경/유기농`
- observations opened: **40**
- already-classified exclusions: **2**
- strict/new classification reviews: **38**
- distinct source listings in this group: **38**
- existing-leaf proposals: **31**
- holds: **7**

Proposal: `proposals/emart-organic-022.json`

## classified exclusions
- `ingestion:95:7` / `1000547040107` / 델파파 유기농 엑스트라 버진 올리브 오일 250ml -> already `food.seasonings.oils.olive`
- `ingestion:95:24` / `1000631306405` / 친환경 추부깻잎 20장*2입/봉 (25g*2) -> already `food.produce.vegetables.leaf`

## main existing-leaf decisions
The broad organic shelf was treated as navigation evidence only. Product identity/form controlled classification.

- fresh chicken eggs -> `food.meat.eggs.chicken`
- peeled quail eggs -> `food.meat.eggs.quail`
- plain organic milk -> `food.dairy.milk.plain`
- 85g baby/youth yogurt cup multipacks -> `food.dairy.yogurt.spoon`
- 100ml liquid yogurt multipack -> `food.dairy.yogurt.drink`
- baby/children cheese -> `food.dairy.cheese.sliced`
- whole-wheat fusilli -> `food.meals.noodles.pasta`
- fresh perilla/lettuce/mixed wrap greens -> `food.produce.vegetables.leaf`
- cucumber -> `food.produce.vegetables.cucumber`
- zucchini -> `food.produce.vegetables.zucchini`
- radish -> `food.produce.vegetables.radish`
- tomato assortment -> `food.produce.vegetables.tomato`
- fresh mixed mushrooms -> `food.produce.vegetables.mushroom`

## holds 7
- `ingestion:95:20`, `ingestion:95:21` — 얼려먹는 아이스크림 밀크/초코: freezable ice-cream form; no exact confirmed pass41 leaf.
- `ingestion:95:50` — 유기농 수정과: traditional beverage; no confirmed exact leaf.
- `ingestion:95:51` — 유기농 서리태: reuse held black-soybean candidate (`food.grains.rice.black_soybean`); do not substitute another bean/grain leaf.
- `ingestion:95:54` — 석류클렌즈콤부차: reuse held candidate `food.drinks.tea.kombucha`.
- `ingestion:95:57` — 현미 스틱 미숫가루: reuse held candidate `food.grains.powder.misutgaru`.
- `ingestion:95:70` — 유기농 발아 깨소금: current `roasted_sesame` leaf is not exact enough; taxonomy-policy hold.

## overlap / collision
- exact cross-group proposal overlap: source key `1000011626449`, group022 `ingestion:95:5` and group026 `ingestion:83:71`; both independently resolve to `food.dairy.yogurt.spoon`. Preserve strict group accounting; final global source-key dedupe will merge it.
- group-marker search found no older proposal claiming pending022.
- all 38 classification-pending source keys were batched through repository collision searches; `review-decisions-input.json` hits: **0**.

## next
After canonical status update, resume from **pending 021** using its exact PENDING_INDEX/raw count. Do not infer completion from proposal filename existence.
