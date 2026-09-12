# WalletSaver 분류 체크포인트 — pending 150 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 대형 배치 전략

사용자 요청에 따라 이번부터 한 번의 연속 검토 목표를 baseline pending의 7% 이상으로 잡았다. 3,916의 7%는 약 274.1건이므로 최소 +275개의 **실제 신규 classification review**를 확보할 때까지 PENDING_INDEX 순서대로 범위를 확장한다. 이미 classification이 resolved이고 수량/행사/단위/count-range/mixed-package 등 다른 사유만 남은 관측은 목표치와 누적 진척에 포함하지 않는다.

## 최신 유효 진행 회계

- pending 109 완료: 1,318 / 3,916
- 이번 bulk 범위: pending 110 ~ 150
- 이번 범위에서 확인한 pending 관측: 297
- 이미 classification resolved라 제외한 관측: 17
- 이번 범위 실제 신규 classification 검토: 280
- 현재 누적 검토: **1,598 / 3,916 (약 40.8%)**
- 남은 미검토: **2,318 / 3,916 (약 59.2%)**
- 이번 한 번의 진척: **+280 = 약 +7.15%p**

### 중복 진척 제외 내역

- pending 111: 샴푸 1관측은 이미 `beauty.personal.hair.shampoo`로 classified이고 `unit_unresolved`만 남아 있어 제외.
- pending 120: 참치 6관측은 이미 classification이 resolved되어 package/bundle 문제만 남아 있어 제외; 실제 미분류 2관측만 신규 검토.
- pending 122: 냉동새우 4관측은 이미 `food.seafood.shellfish.shrimp`로 classified이고 mixed-package 문제만 남아 있어 제외; 오징어링/씨푸드믹스 4관측만 신규 검토.
- pending 144: 복숭아 6관측 전부 이미 `food.produce.fruit.peach`로 classified이고 count-range 문제만 남아 있어 전부 제외.

## proposal 파일

- `handoff/2026-09-11/proposals/bulk-pending-110-150.json`
- 41개 pending 그룹을 한 bulk proposal에 기록했다.
- uniform product-form 그룹은 group-level 기존 leaf 재사용으로 기록하고, mixed 그룹은 제목/상품형태별 규칙을 명시했다.
- taxonomy에 exact leaf가 없는 상품은 신규 후보로 hold했으며 taxonomy 코드를 수정하지 않았다.

## 주요 기존 leaf 재사용

- 떡국떡 -> `food.meals.prepared.rice_cake`
- 국/탕 -> `food.meals.prepared.soup_stew`
- 샌드위치 -> `food.meals.prepared.sandwich`
- 김밥 -> `food.meals.prepared.kimbap`
- 조리 치킨 -> `food.meals.prepared.chicken`
- 석박지 -> `food.preserved.kimchi.seokbakji`
- 파김치 -> `food.preserved.kimchi.green_onion`
- 미분류 혼합 참치 -> `food.preserved.canned.tuna`
- 블랙보리 -> `food.drinks.tea.barley`
- 옥수수수염차 -> `food.drinks.tea.grain`
- 포션/미니 치즈 -> `food.dairy.cheese.portion`
- 계란 -> `food.meat.eggs.chicken`
- 한우 -> `food.meat.fresh.beef`
- 생고추류 -> `food.produce.vegetables.pepper`
- 아이스티 -> `food.drinks.tea.black`
- 찌개양념 -> `food.seasonings.sauces.stew`
- 마파두부양념 -> `food.seasonings.sauces.mapo_tofu`
- 당면 -> `food.meals.noodles.glass`
- 갈치 -> `food.seafood.fish.hairtail`
- 양념닭 -> `food.meals.prepared.seasoned_meat`
- 피스타치오 -> `food.grains.nuts.pistachio`
- 곶감/건자두/건포도류 -> `food.produce.processed_fruit.dried`
- 키위 -> `food.produce.fruit.kiwi`
- 포도 -> `food.produce.fruit.grape`
- 오란다 -> `food.snacks.traditional.hangwa`
- 짜장면/간짜장 -> `food.meals.noodles.black_bean`
- 짬뽕 -> `food.meals.noodles.jjamppong`
- 김치찐만두 -> `food.meals.dumplings.steamed`
- 순대 -> `food.meat.processed.sundae`
- 잡채 -> `food.meals.prepared.japchae`
- 초밥 -> `food.meals.prepared.sushi`
- 쌈무/절임반찬 -> `food.preserved.sides.pickled`

## 주요 신규 taxonomy 후보 hold

- `food.frozen.desserts.tube_ice_cream`
- `food.snacks.sweets.gum`
- `food.preserved.kimchi.kkakdugi`
- `food.preserved.sides.danmuji`
- `food.seafood.cephalopod.squid`
- `food.seafood.mixed.frozen`
- `food.baking.decorations.food_coloring`
- `food.baking.decorations.sprinkles`
- `food.baking.decorations.chocolate_pen`
- `household.kitchen.utensils.tongs`
- `household.kitchen.storage.bag`
- `household.kitchen.cookware.frying_pan`
- `household.kitchen.cookware.wok`
- `food.drinks.other.apple_cider_vinegar`
- `food.drinks.tea.kombucha`
- `food.drinks.tea.milk_tea`
- `food.seasonings.sauces.doenjang_bibim`
- `household.kitchen.utensils.scissors`
- `food.health.supplements.banaba`
- `food.health.supplements.protein`
- `food.grains.powder.misutgaru`
- `food.grains.powder.shake`
- `food.snacks.savory.mixed`
- `food.meals.prepared.ribs`
- broad Emart beauty shelf items were held under product-form candidates for scalp scaler, cotton swab, foaming bottle, face cleanser/oil, and hair dryer.

## 충돌/보존 원칙

- 신규/혼합 후보의 고위험 source_record_key를 기존 431개 explicit review decision과 재대조했으며 일치 항목은 0건이었다.
- 기존 explicit review decision, raw pending observation, invalid rows는 수정하지 않았다.
- 실제 product form을 broad retail shelf보다 우선했다.
- 수량, 행사조건, 가격, 원본 관측, 상품 병합, count-range, mixed-package, unit 문제는 classification-only 검토에서 수정하지 않았다.
- 신규 taxonomy 후보는 proposal-only hold이며 taxonomy 코드에 추가하지 않았다.

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

- 다음 시작: `handoff/2026-09-11/pending/151/001.json`
- 다음부터도 고정된 4개 그룹 단위가 아니라 **실제 신규 classification +275 이상**이 될 때까지 PENDING_INDEX 순서로 연속 처리한다.
- 151부터 젓갈, 햄, 소면, 과일통조림, 전통음료, 에너지/탄산음료, 세제/수산/주방용품/채소/차류 등이 이어진다.
- 이미 classified이고 비분류 사유만 남은 행이 나오면 즉시 제외하고 그만큼 뒤 pending 번호까지 범위를 확장한다.
