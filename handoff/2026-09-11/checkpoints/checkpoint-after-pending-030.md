# Checkpoint — pending 030 strict audit complete

Date: 2026-09-12
Branch: `cleanup/remove-legacy-ai-admin-coupling`
Mode: GitHub read/write, **proposal_only**. No DB import/rebuild/tests run.

## accounting
- parts inspected: `pending/030/001.json`, `002.json`
- observations opened: **32**
- already-classified exclusions: **1**
- classification-review observations: **31**
- distinct source listings: **31**
- existing-leaf proposals: **5**
- holds: **26**
  - promotion/deal surfaces: **24**
  - taxonomy/mixed-bundle holds: **2**
- explicit review-decision collision screen: **0 returned matches**

Proposal: `proposals/emart-obanjang-030.json`

## actual product itemView decisions
- `찰흑미 4kg (2kg+2kg) 26년 햇곡` -> `food.grains.rice.black`
- 황태 스낵 선택 listing -> `food.seafood.processed.dried_fish`
- `바삭한치킨윙 800g` -> `food.meals.prepared.chicken`
- 홍두깨 육포세트 -> hold new candidate `food.meat.processed.jerky`
- `오리지널 국물떡볶이 570g` -> `food.meals.prepared.tteokbokki`
- 밀키트 3종 기획 bundle -> mixed-bundle hold
- 우주인 불고기풀토핑 화덕피자 -> `food.meals.prepared.pizza`

## promotion handling
All other new rows are `dealItemView` promotion surfaces. Product/category words in their titles were not treated as one SKU. This prevents broad event pages such as crab sales, snack collections, detergent 1+1, egg events, coffee brand sales, and electronics card promotions from becoming fake product classifications.

## reconciliation anomaly
- `ingestion:1:25`, key `1000601687276`, title `석박지/맛김치 1+1` is already `review_status=classified` as `food.preserved.kimchi.cabbage` while the URL is `dealItemView` and the title is a mixed promotion.
- It remains excluded from **new** classification accounting per strict policy, but is explicitly flagged for final global reconciliation because this is a pre-existing classified-promotion anomaly.

## resume
Next strict reverse-sweep group: **pending 029**. List every file under the group first; inspect all parts; separate already-classified rows; then measure any old proposal by raw/source-key coverage rather than filename existence.
