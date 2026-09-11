# WalletSaver 분류 체크포인트 — pending 208 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 대형 배치 전략

한 번의 연속 검토 목표를 baseline pending의 7% 이상으로 유지한다. 3,916의 7%는 약 274.1건이므로 최소 +275개의 **실제 신규 classification review**를 확보할 때까지 PENDING_INDEX 순서대로 범위를 확장한다. 이미 classification이 resolved이고 수량/행사/단위/count-range/mixed-package/title-change 등 다른 사유만 남은 관측은 누적 진척에 포함하지 않는다.

## 최신 유효 진행 회계

- pending 150 완료: 1,598 / 3,916
- 이번 bulk 범위: pending 151 ~ 208
- 이번 범위에서 확인한 pending 관측: 308
- 이미 classification resolved라 제외한 관측: 16
- 이번 범위 실제 신규 classification 검토: **292**
- 현재 누적 검토: **1,890 / 3,916 (약 48.3%)**
- 남은 미검토: **2,026 / 3,916 (약 51.7%)**
- 이번 한 번의 진척: **+292 = 약 +7.46%p**

### 중복 진척 제외 내역

- pending 169: 고추장 4관측은 이미 `food.seasonings.pastes.gochujang`로 classified이고 mixed-package/multiple-quantity 문제만 남아 있어 제외. 쇠고기 볶음고추장 2관측만 신규 검토.
- pending 184: 사과 5관측 전부 이미 `food.produce.fruit.apple`로 classified되어 count-range/source-title 문제만 남아 있어 제외.
- pending 192: 복숭아 5관측 전부 이미 `food.produce.fruit.peach`로 classified되어 promotion/count-range 문제만 남아 있어 제외.
- pending 198: 델몬트 바나나 2관측은 이미 `food.produce.fruit.banana`로 classified되고 unit 문제만 남아 있어 제외. 허니글로우 2관측만 신규 검토.

## proposal 파일

- `handoff/2026-09-11/proposals/bulk-pending-151-208.json`
- 58개 pending 그룹을 한 bulk proposal에 기록했다.
- uniform product-form 그룹은 current taxonomy의 기존 leaf를 재사용하고, mixed 그룹은 제목/상품형태별 규칙을 명시했다.
- current taxonomy에 exact product-form leaf가 없는 경우에만 신규 후보로 hold했으며 taxonomy 코드는 수정하지 않았다.

## 주요 기존 leaf 재사용

- 함박/동그랑땡 -> `food.meals.prepared.meat_patty`
- 소면/중면 -> `food.meals.noodles.wheat_noodle`
- 황도 통조림 -> `food.preserved.canned.fruit`
- 식혜 -> `food.drinks.traditional.sikhye`
- 핫식스 -> `food.drinks.water_soda.energy`
- 과일향 탄산 -> `food.drinks.water_soda.soda`
- 섬유 탈취제 -> `household.cleaning.general.deodorizer`
- 캡슐세제 -> `household.cleaning.laundry.capsule`
- 생연어 -> `food.seafood.fish.salmon`
- 조리 생선구이 -> `food.meals.prepared.grilled_fish`
- 냉장 과일음료 -> `food.drinks.juice.fruit_drink`
- 휘핑크림 -> `food.dairy.cream.fresh`
- 계란 -> `food.meat.eggs.chicken`
- 닭고기/돼지고기/소고기 -> 기존 fresh meat leaf
- 양념육 -> `food.meals.prepared.seasoned_meat`
- 생나물류 -> `food.produce.vegetables.leaf`
- 현미녹차 -> `food.drinks.tea.green`
- 메밀차 -> `food.drinks.tea.grain`
- 주방 기름때 세정제 -> `household.cleaning.kitchen.degreaser`
- 배수관 클리너 -> `household.cleaning.bath.drain`
- 까요까요 치즈 -> `food.dairy.cheese.portion`
- 팝콘 -> `food.snacks.savory.popcorn`
- 아몬드 후레이크 -> `food.snacks.cereal.flakes`
- 해물완자 -> `food.seafood.processed.seafood_ball`
- 메밀소바 -> `food.meals.noodles.buckwheat_noodle`
- 스파게티/라구/까르보나라 -> `food.meals.noodles.pasta`
- 명시적 밀키트 -> `food.meals.prepared.meal_kit`
- 삼계탕/김치찌개 -> `food.meals.prepared.soup_stew`
- 조리육수 -> `food.seasonings.sauces.broth`

## 주요 신규 taxonomy 후보 hold / 재사용

- `food.preserved.sides.jeotgal`
- `food.drinks.traditional.sujeonggwa`
- `food.seafood.processed.dried_shrimp`
- `food.seafood.fish.eel`
- `food.seafood.processed.gulbi`
- 기존 후보 재사용 `food.seafood.cephalopod.squid`
- `household.bath.shower_head`
- `household.bath.shower_hose`
- 기존 후보 재사용 `household.bath.accessories.shower_ball`
- `food.seasonings.pastes.stir_fried_gochujang`
- `food.seasonings.liquid_seasoning`
- `food.seasonings.baking.starch`
- `household.kitchen.utensils.spatula`
- `household.kitchen.wrap.parchment_paper`
- `household.kitchen.wrap.aluminum_foil`
- `food.produce.vegetables.radish_sprouts`
- `food.drinks.tea.root`
- apparel underwear candidates (`brief`, `undershirt`, `trunks`)
- `food.seafood.shellfish.clam`
- `food.seafood.mixed.raw`
- 기존 후보 재사용 `food.seasonings.sauces.stir_fry`
- health-supplement candidates for weight-management, vitamin C, and multivitamin product forms; no efficacy claim is inferred.
- `food.produce.fruit.pineapple`
- 기존 후보 재사용 `food.meals.prepared.ribs`

## 중요한 mixed-shelf 판단

- pending 152: 햄 shelf라도 실제 함박스테이크는 `meat_patty`로 검토.
- pending 161: 생 민물장어는 eel 후보, 양념 장어구이/황태구이는 prepared grilled fish로 분리.
- pending 180: 깐양파/파채/마늘쫑 채절임/무순을 실제 제품형태별로 분리.
- pending 186: 고농축 주방세제 shelf의 주방청소 스프레이/후드클리너/배수관클리너를 세정 용도별로 분리.
- pending 189: 슬라이스치즈 shelf의 까요까요 제품은 current taxonomy의 `portion`으로 검토; sliced leaf의 explicit veto를 존중.
- pending 193: 코카콜라/칠성사이다/맥콜을 cola/cider/soda로 분리.
- pending 198: `고산지 허니글로우`를 바나나 shelf만 보고 banana로 강제하지 않고 pineapple 후보로 hold.
- pending 206: `[밀키트]` 명시 상품만 meal-kit로, 단순 김치찌개 제목은 soup/stew로 검토.
- pending 207: 삼계탕 shelf에 들어간 폭립은 기존 ribs 후보를 재사용하고 실제 삼계탕만 soup/stew로 검토.
- pending 208: `육수`는 soup/stew가 아니라 current `broth` leaf로 검토.

## 충돌/보존 원칙

- 신규/혼합 후보의 고위험 source key를 기존 431개 explicit review decision과 재대조했으며 일치 항목은 0건이었다.
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

- 다음 시작: `handoff/2026-09-11/pending/209/001.json`
- pending 209는 `냉장/냉동/밀키트 > 피자/핫도그/치킨 > 냉동감자/치즈스틱 > 치즈스틱`, 4관측 / 2고유 제목이다.
- 이후 210 양념치킨, 211 배추김치, 212 낫또, 213 묵류, 214 숙주, 215 간식용어묵, 216 스위트콘 등이 이어진다.
- 다음 배치도 실제 신규 classification +275 이상이 될 때까지 PENDING_INDEX 순서로 연속 처리하고, 이미 classified인 행은 진척에서 제외한다.
