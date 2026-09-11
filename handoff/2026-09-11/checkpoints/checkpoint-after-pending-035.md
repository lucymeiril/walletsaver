# Checkpoint after strict review of pending 035

상태: `proposal_only`. DB import/rebuild, taxonomy code edit, pytest, verify scripts는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 그대로다.

## pending 035 — Costco `우유` shelf

- files read: `pending/035/001.json`, `pending/035/002.json`
- observations opened: **27**
- already classification-complete exclusions: **2**
- new classification reviews: **25 observations / 25 listings**
- existing-leaf proposals: **9**
- holds: **16**
- proposal: `proposals/costco-milk-shelf-035.json`

### existing leaf 9
- 랑그드샤 선물세트 -> `food.snacks.baked.biscuits`
- 위메이드 밀크쿠키 -> `food.snacks.baked.biscuits`
- YoPro 블루베리 요거트 -> `food.dairy.yogurt.spoon`
- YoPro 무가당 플레인 요거트 -> `food.dairy.yogurt.spoon`
- Barilla 링귀니 -> `food.meals.noodles.pasta`
- 버터토피맛 캐슈 -> `food.grains.nuts.cashew`
- Post 통보리그래놀라 -> `food.snacks.cereal.granola`
- 생미쉘 프렌치 버터쿠키 -> `food.snacks.baked.biscuits`
- ORGANIC VALLEY 기버터 -> `food.dairy.cheese.butter`

### hold 16
- 우유거품기, 두유제조기: kitchen appliance product-form candidate. broad `우유` shelf 무시.
- 우유앙빵: pending036과 동일 `food.bakery.dessert.manju` 후보.
- 셀렉스/퓨어틴/A2 프로틴 4개: pending037과 동일 `food.drinks.other.protein` 후보.
- 펫 산양분유: Costco URL이 Pet Supplies > Dog Foods, human dairy로 분류 금지.
- 삼립 크림빵: `food.bakery.bread.sweet_bun` 후보.
- Prana overnight chia/oats: current cereal leaves가 flakes/granola뿐이라 별도 oatmeal/overnight-oats product form hold.
- Oreo O's, Cinnamon Toast Crunch: cereal은 맞지만 현재 leaves flakes/granola 중 어느 것도 제목으로 확정되지 않아 generic ready-to-eat cereal 후보 hold.
- 닥터케어 캔서코치: specialized nutrition drink hold; broad milk/protein leaf로 추정 금지.
- 정식품 국산콩 진한 콩국: exact audited test도 soymilk로 강제하지 않고 unresolved. 별도 product-form hold.
- 오트몬드 오리지널: exact audited test도 unresolved. oat/almond/soy를 브랜드명/Costco broad path만으로 추정하지 않음.
- 허쉬 아이스바: ice-cream-bar product form hold; current pass41 ice-cream leaf 미확인.

### already-classified 2
- 삼육두유 국산 검은콩 두유 -> `food.plant.soy.soymilk`; bulk package review 때문에 pending.
- 연세우유 소화가잘되는 멸균우유 -> `food.dairy.milk.plain`; bulk package review 때문에 pending.

## explicit-decision collision screen

25 source_record_key를 세 묶음으로 repository search했다. `review-decisions-input.json` hit 0; pending/raw/unresolved 자료만 확인됐다. proposal-stage screen이며 431 explicit decisions를 수정하지 않았다.

## strict reverse 누계

pending `035~043`:
- observations opened: **229**
- already-classified exclusions: **17**
- new classification reviews: **212**
- distinct newly reviewed listings: **200**
- existing leaf: **62**
- hold: **138**

남은 strict-audit 상한: `pending 001~034` **1,654 observations**, pass41 pending 3,916 대비 약 **42.2%**. 실제 새 판단량은 과거 proposal 중복 때문에 이보다 작을 수 있다.

## next resume point

**pending 034**. 이 그룹은 과거 `proposals/grains-nuts-028-034.json`과 겹칠 가능성이 있다. 기존 proposal이 있다는 이유로 완료 처리하지 말고:
1. `pending/034/` 모든 파일 조각 확인
2. raw observations 전체의 already-classified/new-classification 구분
3. 기존 `grains-nuts-028-034.json`이 어떤 raw/source keys를 실제로 커버하는지 대조
4. 누락된 분류만 새 proposal 또는 reconciliation 문서로 보완
5. 완료 즉시 `CURRENT_STATUS.md`를 033으로 갱신
