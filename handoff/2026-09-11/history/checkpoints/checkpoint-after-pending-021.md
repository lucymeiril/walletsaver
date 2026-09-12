# Checkpoint after pending 021

Mode: **proposal_only / GitHub read-write**  
Baseline: **pass41**  
DB import/rebuild/tests/idempotence: **not executed**

## accounting
- pending group: `021`
- mart/shelf: Costco `김치`
- observations opened: **41**
- already-classified exclusions: **0**
- strict/new classification reviews: **41**
- distinct source listings in this group: **41**
- existing-leaf proposals: **15**
- holds: **26**

Proposal: `proposals/costco-kimchi-shelf-021.json`

## key finding: shelf pollution
The Costco `김치` shelf is not a reliable product taxonomy label. It contains:
- finished kimchi
- kimchi marinade/seasoning
- kimchi refrigerators
- stainless food-storage containers
- instant pork-kimchi dishes
- pickles
- red pepper powder
- fermented shrimp
- prepared pork
- udon
- stir-fried anchovy side dish
- kimchi-fried-rice scorched-rice product

Title/product form and official Costco URL taxonomy were used before shelf identity.

## existing 15
- cabbage kimchi: 아워홈 포기김치, 중부식/남도식 김장김치, 종가 포기배추김치, 농협 맛김치, 비비고 묵은지 -> `food.preserved.kimchi.cabbage`
- 나박김치 + 동치미 mixed pack -> `food.preserved.kimchi.water` because both components are water-kimchi forms
- 농협선장 파김치 -> `food.preserved.kimchi.green_onion`
- 아워홈 갓석박지 -> `food.preserved.kimchi.seokbakji` (product form is explicitly 석박지; 갓 is ingredient/style modifier)
- two 고춧가루 listings -> `food.seasonings.spices.chili_powder`
- 청정원 장아찌 3종 -> `food.preserved.sides.pickled`
- 한돈 고추장 제육볶음 -> `food.meals.prepared.seasoned_meat`
- CJ 얼큰우동 -> `food.meals.noodles.udon`
- 비비고 견과류 멸치볶음 -> `food.preserved.sides.stir_fried`

## holds 26
- 10 kimchi-refrigerator appliances -> out-of-current-taxonomy holds; official URL is `Appliances/Refrigerators/Kimchi-Fridges`
- stainless food-storage container -> kitchenware/storage hold
- 김치양념 -> seasoning/marinade hold; not finished kimchi
- mixed packages crossing current kimchi leaves: 포기+열무, 포기+총각, 총각+열무
- mixed/specialized/underspecified kimchi: 농협선장김치 generic, 보쌈김치, 보쌈+겉절이, 백열무+동치미, 갈치김치, 실비김치
- standalone 깍두기 -> held new candidate `food.preserved.kimchi.kkakdugi`; no current dedicated leaf found
- 돼지고기 김치찜 / 돼지김치짜글이 -> prepared-food holds; not kimchi side dishes and no exact confirmed ready-meal leaf
- 새우젓 -> reuse held candidate `food.seafood.fermented.shrimp_paste`
- 김치볶음밥 누룽지 -> product-form hold

## coverage/collision
- all 41 observations are `review_status=pending`; exclusion count is exactly 0.
- group-marker search found no older proposal claiming pending021.
- all 41 source keys were searched in repository batches; no prior proposal source-key hit and no `review-decisions-input.json` hit surfaced.

## next
After canonical status update, resume from **pending 020**. Check exact directory/files and raw coverage before classifying; do not infer completion from any old proposal filename.
