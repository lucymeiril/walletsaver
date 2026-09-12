# Checkpoint after pending 019

Date: 2026-09-12  
Branch: `cleanup/remove-legacy-ai-admin-coupling`  
Mode: GitHub read/write, `proposal_only`

## Completed group

- group: `pending/019`
- mart/shelf: Emart `면류/통조림`
- source files: `pending/019/001.json`, `pending/019/002.json`
- proposal: `proposals/emart-noodles-canned-019.json`
- observations opened: **42**
- distinct source listings: **25**
- observation structure: **17 paired listings + 8 singleton listings**
- already-classification-complete exclusions: **19 observations / 12 source listings**
- strict/new classification reviews: **23 observations / 13 source listings**
- existing-leaf proposals: **10 source listings**
- holds: **3 source listings**

No DB import/rebuild, taxonomy code edit, repository test or idempotence run was executed.

## Existing-leaf proposals

1. `5K PRICE 간편잡채 89.5g` -> `food.meals.prepared.japchae`
2. `신상 오뚜기 동대문식 닭한마리 칼국수 115g*4개` -> `food.meals.noodles.kalguksu`
3. `불닭볶음면 (70g*6개) 420g` -> `food.meals.noodles.cup_ramen`
4. `크링클컷 슬라이스 피클 500g` -> `food.preserved.sides.pickled`
5. `샘표 메밀쌀소면 400g` -> `food.meals.noodles.naengmyeon`
6. `짜장면사리 400g` -> `food.meals.noodles.black_bean`
7. `오이피클 300g` -> `food.preserved.sides.pickled`
8. `완면각짬뽕105g` -> `food.meals.noodles.cup_ramen`
9. `삼양 1963 우지 파개장 115g` -> `food.meals.noodles.cup_ramen`
10. `불닭볶음면 105g` -> `food.meals.noodles.cup_ramen`

### Important product-form verification

The saved titles for four ramen listings did not say `컵`, so exact/current retail evidence was checked before assigning container form:

- `0000010733416` / 불닭볶음면 70g form: current SSG product information identifies it as `작은컵`.
- `1000148468400` / 완면각짬뽕 105g: current SSG product information identifies it as `보통/큰컵`.
- `1000830220975` / 삼양 1963 우지 파개장 115g: current exact-product retail evidence identifies the 115g form as large-cup ramen.
- `0000008839959` / 불닭볶음면 105g: the same 105g form is sold as `불닭볶음면큰컵`; this distinguishes it from the 140g bag listing already in the group.

This evidence was used only for classification identity/form. Quantity or price normalization was not changed.

## Holds

1. `라면사리 110g*4입`
   - hold candidate: `food.meals.noodles.ramen_sari`
   - pass41 has no dedicated plain ramen-sari leaf; do not force seasoning-free soup noodles into `bag_ramen`.
2. `아즈텍카 밀또띠아 320g`
   - hold candidate: `food.bakery.bread.tortilla`
   - pass41 has no tortilla/flatbread leaf; broad noodle/canned shelf is irrelevant to product form.
3. `썬큐 베이크드 빈스 420g`
   - reuse hold candidate: `food.preserved.canned.beans`
   - prior strict review already held canned kidney beans for the same missing pass41 canned-beans leaf.

## Pass41 snapshot vs later code

The current source code contains later noodle refinements such as `wheat_noodle`/`buckwheat_noodle`, but they are not present in the frozen pass41 category snapshot. Per handoff contract, they were not treated as existing pass41 leaves. `샘표 메밀쌀소면` therefore reuses the existing pass41 `냉면·메밀면` axis (`food.meals.noodles.naengmyeon`), consistent with the prior strict `봉평 메밀 국수` precedent.

## Coverage / collision screen

- all **25** group source keys searched against existing proposals: **0 exact hits**
- all **25** group source keys searched against `review-decisions-input.json`: **0 hits**
- all **13 classification-pending source keys** individually searched repository-wide for pending overlap: **0 cross-group pending hits**
- repository hits for those keys were limited to `pending/019`, corresponding raw observations and catalog unresolved evidence
- raw/catalog appearances are evidence, not prior proposal completion

## Strict reverse-sweep cumulative accounting

Completed strict range is now **pending 019~043**.

- observations opened: **792**
- already-classified exclusions: **84**
- strict/new classification reviews: **708**
- strict group source-listing decisions: **652**
- existing-leaf proposals: **305 listings**
- taxonomy/product-form/manual-review holds: **347 listings**

These source-listing counts are strict-group decision counts, not a global unique source-key count. Cross-group duplicates remain for final reconciliation.

## Remaining strict upper bound

- incomplete strict range: `pending 001~018`
- raw observations in that range: **1,091**
- share of pass41 pending 3,916: **about 27.9%**
- observation-range coverage through `019~451`: **about 72.1%**

This is not final project completion. Proposal dedupe/reconciliation, taxonomy policy decisions, explicit-decision collision handling, DB rebuild/import/tests and idempotence are still outstanding after the strict sweep.

## Exact next resume point

Next group: **`pending/018`**

- mart/shelf: Emart `유아동/완구`
- index: **43 observations / 43 titles**
- files: `pending/018/001.json`, `pending/018/002.json`

Next AI should:

1. read both pending018 fragments completely and count record-level `review_status=classified` exclusions;
2. measure source-key/repeated-observation structure rather than assuming 43 titles are 43 classification decisions;
3. calculate exact prior-proposal coverage and 431 explicit-decision collision by source key/raw id;
4. classify by actual product title/form, not the broad `유아동/완구` shelf;
5. separately screen cross-group source-key overlap;
6. after completion update `CURRENT_STATUS.md` first, then append the result to `PROGRESS.md`.
