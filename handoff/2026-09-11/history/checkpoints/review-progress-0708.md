# Initial product classification review checkpoint — 708 / 3,916

- Baseline pass: `pass41`
- Branch: `cleanup/remove-legacy-ai-admin-coupling`
- Manual proposal-only review progress: **708 / 3,916 observations (18.1%)**
- Remaining not yet manually reviewed in this proposal workflow: **3,208 / 3,916 (81.9%)**
- This is a review-progress metric, **not** a staging DB load count.
- Actual pass41 staging baseline remains **5,280 loaded / 3,916 held** until an executable environment performs approved import/rebuild and validation.

## Latest completed batches

The following pending groups are closed as proposal-only review batches after the 600-observation checkpoint:

- `051` — Lotte fruit: 20 observations. Existing fruit/dried-fruit leaves proposed where product identity is singular; mixed fresh-fruit gift sets held. Proposal: `proposals/lottemart-fruit-051.json`.
- `052` — Homeplus laver/bugak shelf: 19 observations. 김자반/김가루 -> `food.seafood.seaweed.laver`; 김부각 -> `food.snacks.savory.seaweed`. Proposal: `proposals/homeplus-laver-bugak-052.json`.
- `053` — Homeplus bean sprouts: 18 observations, all proposed to existing `food.produce.vegetables.sprouts`. Proposal: `proposals/homeplus-bean-sprouts-053.json`.
- `054` — Homeplus cup-rice meals: 18 observations, all proposed to existing `food.meals.rice.cup`; structured promotions remain untouched. Proposal: `proposals/homeplus-cup-rice-054.json`.
- `055` — Homeplus frozen seafood: 17 observations. Existing fish leaves used for 삼치/동태/고등어/갈치; cooked 주꾸미볶음/낙지볶음/아귀찜 and 대구 require policy/new leaves. Proposal: `proposals/homeplus-frozen-seafood-055.json`.
- `056` — Emart vegetables: 16 observations. Existing leaves used for mushrooms/zucchini/pepper/salad/carrot/miyeok; two multi-product deal surfaces held; 청경채/우엉 recorded as new-leaf candidates; one previously explicit-reviewed bean-sprout classification preserved without duplication. Proposal: `proposals/emart-vegetables-056.json`.

## Existing-decision preservation

`review-decisions-input.json` remains unchanged. During `056`, `ingestion:79:2` (`국산콩 전주콩나물 340g+60g`) was found in the 431 explicit decisions with `food.produce.vegetables.sprouts`; the pending reason is quantity/package ambiguity, not classification. The existing classification was preserved and no replacement decision was proposed.

## New taxonomy/policy candidates from the latest sequence

These are proposal-only candidates; no taxonomy code was edited:

- `food.meals.prepared.seafood_dish` — cooked seafood dishes such as 주꾸미볶음/낙지볶음/아귀찜.
- `food.seafood.fish.cod` — 대구; do not collapse into pollock/명태.
- `food.produce.vegetables.bok_choy` — 청경채.
- `food.produce.vegetables.burdock` — 우엉.

## Safeguards / unresolved data preserved

- Mixed-package and multiple-quantity flags are not overwritten.
- Count ranges and unit-unresolved records remain unresolved when classification alone can be reviewed.
- 1+1 / 2+1 and other promotion structures remain independent from category classification.
- Multi-product promotion/deal pages do not receive a single product leaf.
- Mart category paths are evidence only; title/product form wins when the shelf is broad or wrong.

## Execution status

- Staging SQLite rebuild/import: **not run**
- `verify_initial_stage.py`: **not run**
- pytest/regression suite: **not run**
- idempotent import validation: **not run**
- Production/publication approval: **not performed**

## Resume point

Continue at `pending/057`. Before counting a new observation, check exact source keys against existing `proposal_only` files. Preserve any matching explicit review decision instead of duplicating it. After each completed group, update the proposal file's cumulative reviewed/remaining fields from **708 / 3,208**.
