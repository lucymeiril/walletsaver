# WalletSaver 분류 체크포인트 — pending 287 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 208 완료: 1,890 / 3,916
- 이번 bulk 범위: pending 209 ~ 287
- 이번 범위에서 확인한 pending 관측: 277
- 이미 classification resolved라 제외한 관측: 2
- explicit review decision 선행 일치로 제외한 관측: 0
- 이번 범위 실제 신규 classification 검토: **275**
- 현재 누적 검토: **2,165 / 3,916 (약 55.3%)**
- 남은 미검토: **1,751 / 3,916 (약 44.7%)**
- 이번 한 번의 진척: **+275 = 약 +7.02%p**

### 중복 진척 제외 내역

- pending 284: 감귤 2관측은 이미 `food.produce.fruit.citrus`로 classified되어 있고 `source_title_changed`만 남아 있으므로 신규 classification 진척에서 제외했다.
- 그 외 pending 209~287 관측은 현재 pending snapshot에서 classification 미해결 상태였다.

## proposal 파일

- `handoff/2026-09-11/proposals/bulk-pending-209-287.json`
- 79개 pending 그룹을 한 bulk proposal에 기록했다.
- uniform product-form 그룹은 current taxonomy의 기존 leaf를 재사용하고, mixed 그룹은 제목/상품형태별 규칙을 명시했다.
- current taxonomy에 exact product-form leaf가 없는 경우에만 신규 후보로 hold했으며 taxonomy 코드는 수정하지 않았다.

## 주요 기존 leaf 재사용

- 치즈볼 -> `food.meals.prepared.cheese_ball`
- 닭강정/양념치킨 -> `food.meals.prepared.chicken`
- 백김치 -> `food.preserved.kimchi.white`
- 숙주 -> `food.produce.vegetables.sprouts`
- 스위트콘 -> `food.preserved.canned.corn`
- 즉석 카레/짜장 -> `food.meals.prepared.curry` / `food.meals.prepared.black_bean`
- 골뱅이 통조림 -> `food.preserved.canned.whelk`
- 오렌지 주스 -> `food.drinks.juice.fruit`
- 게토레이 -> `food.drinks.water_soda.sports`
- Welch's 탄산 -> `food.drinks.water_soda.soda`
- 습기제거제 -> `household.cleaning.general.dehumidifier`
- 산소계 표백제 -> `household.cleaning.laundry.oxygen_bleach`
- 변기 세정제 -> `household.cleaning.bath.toilet`
- 식기세척기 세제 -> `household.cleaning.kitchen.dishwasher`
- 김/김밥김/도시락김 -> `food.seafood.seaweed.laver`
- 꽃게 -> `food.seafood.shellfish.crab`
- 초리조/살라미 -> `food.meat.processed.sausage`
- 일반 식용유/튀김유 -> `food.seasonings.oils.cooking`
- 생닭/생돼지고기/생소고기 -> 기존 fresh meat leaf
- 건표고/건목이 -> `food.produce.processed_vegetables.dried_mushroom`
- 고추채/명이 절임 -> `food.preserved.sides.pickled`
- 양송이버섯 -> `food.produce.vegetables.mushroom`
- 대파 -> `food.produce.vegetables.scallion`
- 히비스커스/국화/생강/쌍화차 -> `food.drinks.tea.herbal`
- 옥수수차/옥수수수염차 -> `food.drinks.tea.grain`
- 카프리썬 -> `food.drinks.juice.fruit_drink`
- 김부각 -> `food.snacks.savory.seaweed`
- 카레분말 -> `food.seasonings.powders.curry`
- 스팸/살코기햄/델리햄 -> `food.meat.processed.ham`
- 고구마칩 -> `food.snacks.savory.vegetable`
- 메추리알 장조림 -> `food.preserved.sides.braised`
- 명이나물 -> `food.preserved.sides.pickled`
- 식빵 -> `food.bakery.bread.sliced`
- 드라이시트 -> `household.cleaning.laundry.dryer_sheet`
- 통등심 카츠 -> `food.meals.prepared.pork_cutlet`
- 양념 소불고기 -> `food.meals.prepared.seasoned_meat`
- 냉면육수/소고기양지육수 -> `food.seasonings.sauces.broth`
- 시즈닝 견과 -> 기존 `food.grains.nuts.*` leaf
- 유부초밥 키트 -> `food.preserved.ingredients.inari`
- 믹스넛 -> `food.grains.nuts.mixed`
- 건망고 -> `food.produce.processed_fruit.dried`

## 주요 신규 taxonomy 후보 hold / 재사용

- `food.meals.prepared.cheese_stick`
- 기존 후보 재사용 `food.plant.soy.soy_liquid`
- `food.plant.muk`
- `food.plant.konjac`
- `food.drinks.water_soda.tonic`
- `food.seasonings.stock.dashi_pack`
- `food.seafood.processed.dried_fish`
- `food.seafood.processed.dried_pollock`
- `household.bath.slippers`
- `food.dairy.condensed_milk`
- `food.bakery.toppings.chocolate_syrup`
- `food.seasonings.oils.cooking_spray`
- `household.kitchen.utensils.cooking_spoon`
- `household.kitchen.wrap.plastic_wrap`
- `household.fragrance.incense`
- `household.kitchen.consumables.stock_bag`
- `food.produce.vegetables.yeolmu`
- `food.produce.vegetables.broccoli`
- `food.health.supplements.greens`
- 기존 후보 재사용 `food.drinks.tea.root`
- `food.seasonings.curry.roux`
- `food.meals.prepared.meatball`
- apparel/accessory candidates for socks and hair elastic
- `food.produce.processed_vegetables.dried_sweet_potato`
- `food.produce.fruit.lemon`
- `food.produce.fruit.orange`
- `food.seafood.fish.skate`
- `food.produce.vegetables.herb`
- `food.meals.rice.soup_rice`
- `food.meat.processed.jerky`
- `food.health.supplements.multivitamin`
- `food.health.supplements.collagen`
- `food.grains.powder.sunsik`
- `food.produce.fruit.fig`
- `food.produce.fruit.cherry`

## 중요한 mixed-shelf 판단

- pending 209: 치즈볼과 치즈스틱을 제품형태로 분리했다.
- pending 211: 배추김치 shelf라도 실제 제목이 백김치이므로 white kimchi로 검토했다.
- pending 212: 낫또 shelf의 콩물/콩국물은 두유나 낫또가 아니라 기존 soy-liquid 후보를 재사용했다.
- pending 215: 어묵 shelf의 곤약은 fishcake로 분류하지 않았다.
- pending 217: 즉석국 shelf의 카레/짜장을 실제 ready-meal 형태로 분리했다.
- pending 233: 치즈 관련 shelf에 들어간 초리조/살라미는 processed meat로 검토했다.
- pending 245: 데친나물 shelf의 고추채/명이 절임은 pickled side로 검토했다.
- pending 252: 차 shelf의 컬리케일 건강식품을 tea로 강제하지 않았다.
- pending 256: 카레분말과 고형 카레 roux를 분리했다.
- pending 257: 소시지 shelf의 미트볼/스팸/살코기햄/델리햄을 실제 제목형태로 분리했다.
- pending 262: 메추리알 장조림을 fresh/quail-egg leaf로 보내지 않고 조림반찬으로 검토했다.
- pending 271: 돈까스 shelf의 모둠 소시지를 sausage로 분리했다.
- pending 273: 새싹채소 shelf의 바질/고수는 herb 후보로 hold했다.
- pending 274: 냉면 shelf의 냉면육수는 noodles.naengmyeon으로 강제하지 않고 existing broth leaf로 검토했다.
- pending 275: 국·탕 shelf의 육수는 broth로, 차돌짬뽕밥/차돌된장밥은 rice soup 후보로 분리했다.
- pending 276: 수산물 merchandising root의 육포는 meat jerky 후보로 hold했다.

## explicit review decision 대조

- existing explicit review decision 431개는 수정하지 않았다.
- prior reviewed Yangban gimbap-laver family가 존재하지만 pending 229~230의 source_record_key와 일치하지 않았다.
- pending 217 카레/짜장, 229~230 김, 254 카프리썬, 257 미트볼/햄, 278 유부초밥의 고위험 source key를 재대조했고 exact match는 0건이었다.
- 따라서 explicit review decision 선행 일치로 이번 진척에서 추가 제외한 관측은 0건이다.

## 충돌/보존 원칙

- 기존 explicit review decision, raw pending observation, invalid rows는 수정하지 않았다.
- 실제 product form을 broad retail shelf보다 우선했다.
- 수량, 행사조건, 가격, 원본 관측, 상품 병합, count-range, mixed-package, unit, title-change 문제는 classification-only 검토에서 수정하지 않았다.
- 신규 taxonomy 후보는 proposal-only hold이며 taxonomy 코드에 추가하지 않았다.
- 건강식품 shelf/title의 마케팅 문구를 효능 증거로 취급하지 않았다.

## 실제로 실행하지 않은 검증/반영

이번 작업에서는 다음을 실행하지 않았다.

- staging SQLite import 또는 재구축
- proposal을 explicit review decision으로 승격/적용
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 전체 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성 및 데이터 무결성 검증

따라서 이번 결과는 분류 제안이며 운영/DB 반영 상태가 아니다.

## 다음 재개점

- 다음 시작: `handoff/2026-09-11/pending/288/001.json`
- pending 288은 `과일 > 바나나/파인애플 > 파인애플`, 2관측 / 1고유 제목이다.
- 이후 289 배, 290 자몽/메로골드, 291 아보카도, 292 한과, 293 시리얼바/에너지바, 294 샐러드 등이 이어진다.
- 다음 배치도 실제 신규 classification +275 이상이 될 때까지 PENDING_INDEX 순서로 연속 처리하고, 이미 classified인 행은 진척에서 제외한다.
