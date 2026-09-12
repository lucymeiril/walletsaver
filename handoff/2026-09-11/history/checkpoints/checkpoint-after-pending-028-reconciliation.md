# Checkpoint — pending 028 strict reconciliation complete

Date: 2026-09-12
Branch: `cleanup/remove-legacy-ai-admin-coupling`
Mode: GitHub read/write, **proposal_only**. No DB import/rebuild/tests run.

## accounting
- parts inspected: `pending/028/001.json`, `002.json`
- observations opened: **33**
- already-classified exclusions: **0**
- strict classification reviews: **33**
- distinct source listings: **33**
- old proposal: `proposals/grains-nuts-028-034.json`
- old proposal exact raw coverage: **11/33**
- previously uncovered: **22/33**
- old 11 revalidation conflicts: **0**
- final existing-leaf decisions: **28**
- final holds: **5**
- explicit review-decision collision screen across all 33 source keys: **0 returned matches**

Reconciliation proposal: `proposals/reconciliation-pending-028.json`

## coverage gap
The older proposal listed group 028 as reviewed but only contained 11 exact pending-028 raw IDs. The strict audit found and classified/held the missing 22 rows. This is the second confirmed case (after pending 034) where a group-level old proposal marker overstated raw coverage.

## final holds
- `바삭한 피칸 (120G)` -> candidate `food.grains.nuts.pecan`
- `구운 호박씨 (300G)` -> candidate `food.grains.seeds.pumpkin`
- `명인부각 누룽지 (180G)` -> candidate `food.grains.processed.nurungji`
- `듀럼밀 (1.5KG)` -> candidate `food.grains.wheat.durum`; raw grain, do not reuse pasta examples
- `HBAF 카라멜 아몬드 앤 프레첼 (120G)` -> mixed-product-form hold; non-nut pretzel component is material

## notable existing decisions
- sweet-potato chips/sticks and pumpkin chip -> existing `food.snacks.savory.vegetable`
- banana chips -> existing `food.produce.processed_fruit.dried`
- flavored single-nut products keep their core nut leaf
- almond+peanut mixes -> `food.grains.nuts.mixed`
- all 11 old decisions remain valid under current strict policy

## resume
Next strict reverse-sweep group: **pending 027**.

List every file under `handoff/2026-09-11/pending/027/`, inspect all parts, separate already-classified rows first, then search for any old proposal and measure exact raw/source-key coverage before treating it as completed.
