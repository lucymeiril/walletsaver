# Reverse sweep checkpoint: pending 040~043

상태: proposal-only. staging DB/import/rebuild/taxonomy code/tests는 실행하지 않았다. pass41 baseline 수치(5,280 loaded / 3,916 pending)는 변경하지 않았다.

## 완료한 그룹

### pending 043 — 롯데마트 채소
- proposal: `proposals/lottemart-vegetables-043.json`
- commit: `1f96ee450b2c277ea05b5d0a594920a2b9591193`
- 23관측 / 23 listing 전량 검토
- existing leaf 제안 21건
- 신규 taxonomy 후보 hold 2건: lettuce, broccoli
- broad `채소` shelf는 정답으로 사용하지 않고 title-first 적용

### pending 042 — 홈플러스 일회용/다회용 공기
- proposal: `proposals/homeplus-tableware-042.json`
- commit: `7b39bd0041c0d47bf14e5e594003f9d6c9031039`
- `001.json` + `002.json`, 24관측 / 12 listing
- 같은 판매페이지 반복관측 2개씩 묶음
- 실제 제품은 spoon/bowl/plate/food-container/chopsticks/condiment-dish로 혼재
- pass41 snapshot에 대응 kitchen tableware leaf가 확인되지 않아 12 listing 전부 신규 후보 hold
- legacy `category_data/categories.py`의 kitchen leaf는 pass41 current snapshot 존재 증거로 사용하지 않음

### pending 041 — 코스트코 생선
- proposal: `proposals/costco-fish-shelf-041.json`
- commit: `68c2d46be9a01d2600a7f8a6685cad608223ce30`
- 24관측 / 24 listing 전량 검토
- existing leaf 13건, 신규 후보 hold 11건
- 조리생선구이/어묵/건멸치/건어물/김/해장국 등은 existing leaf 재사용
- cod, semi-dried fish, fresh tuna, pet food, cactus, prepared pork assortment는 후보 hold
- `생선뼈 선인장`, 고양이/강아지 사료, 족발/편육 등을 `생선` shelf 때문에 수산물로 넣지 않음

### pending 040 — 코스트코 채소
- proposal: `proposals/costco-vegetable-shelf-040.json`
- commit: `5ec5493ebbd3d97c5d2c8fe17afe813c949aff77`
- `001.json` + `002.json`, 25관측 전량 확인
- 이미 classification 완료된 5관측은 신규 classification count에서 제외:
  - onion `ingestion:47:81`
  - carrot `ingestion:47:83`
  - pepper `ingestion:47:89`
  - mushroom `ingestion:47:96`
  - dried fruit `ingestion:48:1`
- 신규 classification review 20건
- existing leaf 제안 8건, taxonomy/product-form hold 12건
- kitchen tools, pet food, planter, seaweed, guacamole, bulk berry product 등이 broad `채소` shelf에 오염되어 있음

## accounting 규칙

과거 누적 `reviewed` 숫자는 duplicate/re-review/already-classified observation이 섞여 있으므로 이번 reverse sweep에서는 누적 총합을 갱신하지 않는다.

각 proposal은 대신 다음을 독립적으로 기록한다.
- observations opened/reviewed
- source listings
- already-classified exclusion
- new classification reviews
- existing leaf decisions
- held taxonomy/product-form candidates

## explicit decision 충돌 점검

040~043에서 새로 분류 판단한 source keys는 batched repository search로 `review-decisions-input.json` exact-key 충돌 흔적을 확인했다. 해당 검색들에서는 `review-decisions-input.json` match가 나오지 않았다. 이는 proposal-stage screen이며 DB mutation이 아니다.

## 다음 재개점

`pending 039`부터 역순으로 계속 검토한다. 각 group 시작 시 반드시 pending directory file list를 먼저 확인해 `001.json`만 존재한다고 가정하지 않는다.
