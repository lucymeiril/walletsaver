# Checkpoint after pending 020

Date: 2026-09-12  
Branch: `cleanup/remove-legacy-ai-admin-coupling`  
Mode: GitHub read/write, `proposal_only`

## Completed group

- group: `pending/020`
- mart/shelf: Emart `밀키트/간편식`
- source files: `pending/020/001.json`, `pending/020/002.json`
- proposal: `proposals/emart-mealkit-convenience-020.json`
- observations opened: **42**
- source listings represented: **21**
- structure: every source listing appears exactly twice, once in ingestion 84 and once in ingestion 85
- already-classification-complete exclusions: **6 observations / 3 source listings**
- strict/new classification reviews: **36 observations / 18 source listings**
- existing-leaf proposals: **4 source listings**
- holds: **14 source listings**

No DB import/rebuild, taxonomy code edit, repository test or idempotence run was executed.

## Existing-leaf proposals

1. `아삭한 쌈무 350g` -> `food.preserved.sides.pickled`
   - reuses the established strict policy that 쌈무/절임반찬 belongs to the pickled-side-dish leaf.
2. `모짜렐라 비프라자냐 350g` -> `food.meals.noodles.pasta`
   - current audited classifier explicitly treats `라자냐` as a pasta token.
3. `소금구이 모듬닭꼬치 600g` -> `food.meals.prepared.chicken`
   - reuses prior strict yakitori/닭꼬치 precedent and existing catalog classification.
4. `다담 된장찌개 양념500g` -> `food.seasonings.sauces.stew`
   - exact 찌개양념 product form; not a finished soup/stew meal.

## Important holds and policy reuse

- 맘마밀 오트밀/이유식 3 listings: baby cereal/weaning-food family held because pass41 has no confirmed baby-food leaf. Do not classify by ingredient words.
- standalone 단무지 3 listings: reuse candidate `food.preserved.sides.danmuji`; do not force into the current 장아찌 leaf.
- `우엉절임과 김밥단무지`: mixed package held across ordinary pickled-side policy and the dedicated danmuji candidate.
- 도토리묵 2 listings: reuse candidate `food.plant.muk.acorn`.
- `양념감자튀김`: reuse candidate `food.meals.prepared.frozen_potato`.
- `메밀김치전병`: hold taxonomy policy; savory filled jeonbyeong is not safely equivalent to traditional-snack `한과·전병` or generic `냉동전`.
- `정선 생 곤드레나물밥`: hold taxonomy policy; no exact current rice leaf is proven.
- `생선까스`: candidate `food.meals.prepared.fish_cutlet`; do not force into species-specific pork cutlet or grilled fish.
- `딱 한끼(순한맛) 308g`: identity hold. Collection says 삼진어묵, but title does not identify the product form; brand/collection context alone is insufficient.

## Collision / prior-coverage screen

- all **21** `source_record_key` values searched against existing proposals: **0 exact hits**
- searched against `review-decisions-input.json` (431 explicit decisions): **0 hits**
- pending-path exact-key search surfaced no cross-group hit; only pending020 itself appeared
- raw/pending/catalog-unresolved appearances were treated as evidence, not prior proposal completion

## Strict reverse-sweep cumulative accounting

Completed strict range is now **pending 020~043**.

- observations opened: **750**
- already-classified exclusions: **65**
- strict/new classification reviews: **685**
- strict group source listings reviewed: **639**
- existing-leaf proposals: **295 listings**
- taxonomy/product-form/manual-review holds: **344 listings**

These source-listing counts are strict-group decision counts, not a global unique source-key count. Cross-group duplicates remain for final reconciliation.

## Remaining strict upper bound

- incomplete strict range: `pending 001~019`
- raw observations in that range: **1,133**
- share of pass41 pending 3,916: **about 28.9%**
- observation-range coverage through `020~451`: **about 71.1%**

Do not call this a final project-completion percentage. Proposal dedupe/reconciliation, taxonomy policy, explicit-decision collision handling, DB rebuild/import/tests and idempotence are still outstanding after the strict sweep.

## Exact next resume point

Next group: **`pending/019`**

- mart/shelf: Emart `면류/통조림`
- index: **42 observations / 25 titles**
- files: `pending/019/001.json`, `pending/019/002.json`

Next AI should:

1. read both pending019 fragments completely and determine record-level already-classified exclusions;
2. measure repeated-observation/source-key structure rather than assuming 42 observations are 42 decisions;
3. calculate exact prior-proposal coverage by raw/source key;
4. classify by title/product form, not the broad Emart shelf;
5. separately screen cross-group source-key overlap and all 431 explicit review decisions;
6. after completion, update `CURRENT_STATUS.md` first and append the result to `PROGRESS.md`.
