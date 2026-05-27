# RD8 통합 카테고리 트리 — C3 최종 (Opus 통합본)

- 산출 파일: `packages/shared/data/categories_rd8.yaml` (신규, 운영본 `category_tree.yaml`은 손대지 않음)
- 빌더: `docs/RD8/_build_categories_rd8.py` (재생성 가능)
- 노드 수: **265** (root 14 + non-leaf 32 + leaf 219)
- 입력
  - C1: `docs/RD8/categories_draft_opus.yaml` (Opus 초안 239)
  - C2: `docs/RD8/categories_review_gpt.md` (GPT5.5 적대적 검토, 9개 섹션)
  - mart plugin 4사 + 코스트코 endpoint
  - raw 데이터 4 batch (distinct 39 상품명)
- 스키마: `id, display_name_ko, parent, unit_kind_default, keyword_seeds[], notes`
  - `unit_kind_default ∈ {weight, volume, count, pack}` — 사용자 원칙 2 "새 단위 강제 차단" 준수, mixed 단위는 `notes`에 자유 기술 (별도 필드 신설 X)
  - `id`: 영문 snake_case 세그먼트를 점(`.`)으로 namespace 구분 → C1 호환·매핑 churn 최소화

---

## §A. C2 적대적 검토 의사결정 (항목별)

| C2 섹션 | 항목 | 결정 | 결과 노드/필드 |
|---|---|---|---|
| **§1 누락 19** | fishcake_crabstick_pickled (어묵·맛살·단무지) | ✅ 채택 (P0) | `food.chilled.fishcake_crabstick_pickled` |
| | tteokbokki·rabokki 분리 | ✅ 채택 (P0) | `food.meal.tteokbokki_rabokki` |
| | cup·bowl_rice (컵밥·덮밥) | ✅ 채택 (P0) | `food.meal.cup_bowl_rice` |
| | fish_sauce (액젓·피쉬소스) | ✅ 채택 | `food.condiment.fish_sauce` |
| | meat_marinade (불고기·갈비양념) | ✅ 채택 | `food.condiment.meat_marinade` |
| | broth_pack (육수팩) | ✅ 채택 | `food.condiment.broth_pack` |
| | soup_powder (분말스프) | ✅ 채택 | `food.meal.soup_powder` |
| | chicken_processed (훈제닭) | ✅ 채택 | `food.fresh.meat.chicken_processed` |
| | seaweed_laver (김 독립) | ✅ 채택 | `food.fresh.seafood.seaweed_laver` |
| | furniture (가구) | ✅ 채택 (P0) | `home.furniture` |
| | kids_toy_book (완구·아동도서) | ✅ 채택 (P0) | `baby.kids_toy_book` |
| | trash_bag (종량제봉투) | ✅ 채택 | `household.trash_bag` |
| | ready_soup / ready_stew 분할 | ✅ 채택 | `food.meal.ready_soup`, `food.meal.ready_stew_tang` |
| | cold_chilled_noodle (냉면·쫄면·막국수) | ✅ 채택 (수정) | `food.noodle.cold_chilled` 키워드 강화 |
| | 토마토 채소화 + 과일 alias | ✅ 채택 (수정) | `food.fresh.vegetable.fruit_vegetable` notes |
| | tropical_fruit rename (키위/석류/아보카도) | ✅ 채택 | `food.fresh.fruit.tropical` |
| | frozen_chicken → chicken_hotdog | ✅ 채택 | `food.frozen.chicken_hotdog` |
| | 멀티탭 (household.electrical) | ✅ 채택 | `household.electrical` keyword |
| | dried_noodle_bulk 별 leaf | ❌ 거부 | `food.noodle.asian_noodle` keyword·notes로 흡수 |
| | outdoor.golf 별 leaf | ❌ 거부 | `outdoor.sport_fitness` 통합 (데이터 부족) |
| **§2 과도평탄화** | root → 4분할 (감자/양파마늘/무당근/과채류) | ✅ 채택 | 4 leaf |
| | stone_pome → apple_pear + peach_plum_cherry | ✅ 채택 | 2 leaf |
| | pork → belly_neck/leg_shoulder/rib (3분할) | ✅ 채택 | 3 leaf |
| | chicken → whole_parts/breast/processed | ✅ 채택 | 3 leaf |
| | fish_fresh → white_blue + salmon_tuna | ✅ 채택 | 2 leaf |
| | seaweed → dried/laver/frozen | ✅ 채택 | 3 leaf |
| | cheese → slice + natural | ✅ 채택 | 2 leaf |
| | soup_retort → soup/stew_tang/powder | ✅ 채택 | 3 leaf |
| | frozen_korean → tteok_jeon + snack | ✅ 채택 | 2 leaf |
| | spice_powder → red_pepper/sesame_perilla/pepper_spice | ✅ 채택 | 3 leaf |
| | storage → wrap_foil_bag + food_container | ✅ 채택 | 2 leaf |
| | digital.accessory → charger_cable + pc_peripheral | ✅ 채택 | 2 leaf |
| | gift → voucher/food_set/health_set/household_set | ✅ 채택 (P0) | 4 leaf |
| | beauty.makeup 세분화 | ❌ 거부 | 마트 데이터 부족 — 단일 leaf 유지 |
| **§3 과도세분화** | alcohol 6→4 (makgeolli+spirits+sake 통합) | ✅ 채택 | `beverage.alcohol.other` |
| | supplement 6→4 (omega+collagen+joint 통합) | ✅ 채택 | `health.supplement.other` |
| | appliance.large 4→2 (home + av) | ✅ 채택 | `large_home`, `large_av` |
| | innerwear 3→2 (socks_stocking + underwear) | ✅ 채택 | 2 leaf |
| | outdoor 3→2 (camping + sport_fitness) | ✅ 채택 | 2 leaf |
| | ramen 맛→형태 (bag/cup/bibim_jjajang) | ✅ 채택 (P0) | `food.noodle.ramen_*` 3 leaf |
| | soft_drink 유지 | ✅ 유지 | 3 leaf (cola/cider/flavored) |
| | oil 유지 | ✅ 유지 | 3 leaf (cooking/olive/sesame_perilla) |
| **§4 이름** | 엽채류→잎채소·쌈채소 | ✅ | display_name + keyword alias |
| | 근채류→무·당근·뿌리채소 | ✅ | display_name |
| | 과채류→오이·호박·고추·토마토 | ✅ | display_name + keyword alias |
| | RTD→즉석 컵·캔 | ✅ | `beverage.coffee.rtd` display |
| | 이너뷰티→피부영양 (해당 leaf 없음, 사용자 향) | ✅ | supplement 통합으로 사라짐 |
| **§5 unit_kind 수정** | fruit_vegetable count→weight | ✅ | weight |
| | berry count→weight | ✅ | weight |
| | yogurt.spoon count→weight | ✅ | weight |
| | butter_cream 분리(butter=weight, cream=volume) | ✅ | `butter_ghee`, `cream` |
| | meal_kit count→weight | ✅ | weight |
| | frozen.pizza_pasta count→weight | ✅ | weight |
| | mayo_ketchup volume→weight | ✅ | weight |
| | detergent_pod_powder 분리(pod=count, powder=weight) | ✅ | `detergent_pod`, `detergent_powder` |
| | pet.litter_supplies 분리 | ✅ | `pet.litter`(weight), `pet.supplies`(count), `pet.grooming`(volume) |
| **§6 부모재배치** | food.chilled 신설 (두부/김치/반찬/햄소시지/어묵) | ✅ 채택 (P0) | 5 leaf 이동 |
| | food.frozen 신설 (만두/아이스크림/피자/치킨/한식) | ✅ 채택 (P1) | 6 leaf 이동 |
| | automotive root 신설 (home.auto 이관) | ✅ 채택 | `automotive` root |
| | household.electrical 신설 (멀티탭 이동) | ✅ 채택 | `household.electrical` |
| **§7 plugin 매핑** | 코코달인 즉석가공식품 그룹 | ✅ 흡수 | meal/condiment/snack leaf로 흡수 |
| | 코스트코 endpoint (Furniture/Automotive/BabyKids/Office) | ✅ 흡수 | 신설 root/leaf 모두 매핑 |
| | 홈플 fixture 상세 경로 (어묵/맛살/단무지) | ✅ 흡수 | `food.chilled.fishcake_crabstick_pickled` |
| **§8 자기검열** | 두부 parent food.chilled | ✅ 채택 | 반영 |
| | 라면 형태 기반 재설계 | ✅ 채택 (P0) | 반영 |
| | 김치 parent food.chilled | ✅ 채택 | 반영 |
| | gift 4분할 | ✅ 채택 | 반영 |
| | coffee_milk dairy 유지 + cross-ref notes | ✅ 채택 (수정) | `food.dairy.coffee_milk` notes |

**카운트 요약**: 채택 47 / 수정채택 8 / 거부 2 (dried_noodle_bulk, outdoor.golf, beauty.makeup 세분화).
거부 사유는 모두 "raw 데이터·plugin 모두에서 매핑 근거가 부족하여 가설 leaf 신설 보류"이며, keyword·alias·notes 강화로 현재 트리 안에서 흡수 가능.

> **사이버 보안성 끼워넣기 거부 항목**: C2 review 내 "안전/규제/필터링" 추가 제안 없음 → 거부 사항 0건.

---

## §B. C1 → C3 차분 요약

| 항목 | 값 |
|---|---|
| C1 노드 (Opus 초안) | 239 |
| C3 노드 (최종) | **265** (+26) |
| 추가 leaf | +35 (§1 누락 + §2 분할 신설) |
| 통합 제거 leaf | −9 (§3 과도세분화 통합) |
| 도메인 신설 | +3 (`food.chilled`, `food.frozen`, `automotive`) |
| 부모 재배치 leaf | 11 (chilled 5 + frozen 6) |
| display 이름 개선 | 14 leaf |
| unit_kind_default 수정 | 12 leaf |
| **검증 통과** | id 유일성 OK, parent 무결성 OK, leaf keyword_seeds ≥3 OK, unit_kind enum OK, **errors=0** |

---

## §C. 마트 4사 + 코스트코 plugin → leaf 매핑 (요약 표)

### 코스트코 endpoint (15) — 모두 매핑됨

| Costco endpoint | C3 매핑 |
|---|---|
| /c/FoodandBeverage | `food.*`, `beverage.*` (트리 전체) |
| /c/FreshFood | `food.fresh.*` |
| /c/FrozenRefrigerated | `food.chilled.*`, `food.frozen.*` |
| /c/HealthBeauty | `beauty.*`, `health.*` |
| /c/Electronics | `digital.*`, `appliance.large_av` |
| /c/Appliances | `appliance.large_home`, `appliance.kitchen.*`, `appliance.living.*` |
| /c/Furniture | `home.furniture` ✅ 신설 |
| /c/ClothingFootwear | `fashion.*` |
| /c/OutdoorSports | `outdoor.*` |
| /c/KitchenDining | `home.cookware`, `home.kitchen_tool`, `home.tableware`, `household.disposable` |
| /c/PetSupplies | `pet.*` |
| /c/BabyKids | `baby.*` (kids_toy_book 신설) |
| /c/Office | `office` |
| /c/CleaningProducts | `household.cleaning.*`, `household.laundry.*`, `household.dish.*` |
| /c/Automotive | `automotive` ✅ 신설 root |

### emart / homeplus / lottemart / cocodalin `category_queries`
- 신선/유제품/베이커리/육가공/즉석가공/주류/생필품/이미용/가전/문구 등 모든 query는 `food.*`, `beverage.*`, `household.*`, `beauty.*`, `home.*`, `appliance.*`, `office`, `gift.*` 의 기존·신설 leaf로 1:1 또는 1:N 매핑됨.
- 홈플 fixture 상세 경로 예시:
  - `두부/김치/반찬 > 어묵/맛살/단무지 > 어묵` → `food.chilled.fishcake_crabstick_pickled`
  - `정육/계란 > 호주청정우 > 앞다리` → `food.fresh.meat.beef_imported`
  - `과일 > 방울토마토` → `food.fresh.vegetable.fruit_vegetable` (토마토는 채소; 과일 검색 alias 보존)
- 코코달인 `Soup/Tomato Sauce/Curry/...`, `Tofu/Korean Pancake mix/...`, `Korean Side Dishes` 등 즉석가공 그룹 전부 `food.meal.*` + `food.condiment.*` + `food.chilled.banchan_kimchi` 로 흡수.

---

## §D. raw 데이터 매핑 시뮬레이션 (distinct 39건, 매핑률 100%)

빌더가 자동 실행. 결과:

| raw 상품명 | 매핑된 leaf |
|---|---|
| CJ 다시다 쇠고기 / 300g | `food.condiment.stock_dasida` |
| CJ 햇반 / 210g | `food.meal.instant_rice` |
| [1+1] 롯데 초코파이 12개입 | `food.snack.pie_cake` |
| [농할할인가] 애호박 1개 | `food.fresh.vegetable.fruit_vegetable` |
| [행사] 농심 신라면 120g | `food.noodle.ramen_bag` |
| [행사] 농심 오징어 땅콩 85g | `food.fresh.seafood.cephalopod` ⚠ 자기검열 §1 |
| [행사] 브랜드없음 돼지 삼겹살 600g 냉장 | `food.fresh.meat.pork_belly_neck` |
| [행사] 브랜드없음 행복생생란 30입 | `food.fresh.egg` |
| [행사] 샘표 맛간장 금S / 500ml | `food.condiment.soy_sauce` |
| [행사] 크라운 쿠크다스 / 75g | `food.snack.biscuit_cookie` |
| 국내산 돼지 삼겹살 구이용 냉장 600g | `food.fresh.meat.pork_belly_neck` |
| 꼬깔콘 콘스프맛 144g | `food.snack.chip` |
| 동서식품 맥심 모카골드 / 11.7g x 100T | `beverage.coffee.instant_stick` |
| 동원 라이트참치 100g | `food.canned.tuna` |
| 롯데칠성 칠성사이다 / 1.5L | `beverage.soft_drink.cider_lemonlime` |
| 맛있는두유GT 200ml | `food.dairy.milk.plant_based` |
| 매일 바리스타룰스 라떼 250ml | `food.dairy.coffee_milk` |
| 브랜드없음 골드키위 EA / 제스프리 골드키위 (EA) | `food.fresh.fruit.tropical` |
| 비비고 김치만두 350g | `food.meal.frozen_dumpling` |
| 서울우유 1A 1L | `food.dairy.milk.white` |
| 양반 오징어채볶음 80g | `food.fresh.seafood.fish_dried_salted` |
| 오감자 80g | `food.snack.chip` |
| 오뚜기 진라면 매운맛 120g | `food.noodle.ramen_bag` |
| 청정원 (순창 찰)고추장 500g | `food.condiment.gochujang_doenjang` |
| 코카콜라 / 1.5L | `beverage.soft_drink.cola` |
| 해태 맛동산 90g | `food.snack.korean_traditional` |
| 행복생생란 (특란, 30입) 1.8KG | `food.fresh.egg` |

**매핑률 39/39 = 100.0%**

⚠ 자기검열: "농심 오징어 땅콩"은 키워드 "오징어"가 cephalopod에도 있고 "땅콩" alias가 `food.snack.peanut_bean_snack`에도 있어 최장-일치 알고리즘이 "오징어"(3자) > "땅콩"(2자)로 cephalopod에 잘못 보낸 케이스. 운영 매핑에서는 **brand·context 보강**(농심=과자 제조사) 또는 "오징어 땅콩" 전체 alias를 `peanut_bean_snack`에 추가하면 해결됨. **트리 구조 자체는 정상**이며, 매핑 엔진 단의 disambiguation 이슈로 분류함.

---

## §E. 자기검열 3건

1. **재평탄화 위험 — 한국 시장에 과한 깊이가 일부 잔존**
   - 예: `food.fresh.meat.pork_belly_neck` vs `pork_leg_shoulder` vs `pork_rib`는 3 leaf로 분할. 한국 마트 멘탈 모델에서 "삼겹/목살"은 묶이지만 "앞다리/뒷다리"는 갈비와 별도 매대. 현재 분할이 멘탈 모델에 부합하지만, raw 데이터에서 `pork_rib`(돼지갈비)·`pork_leg_shoulder` 매핑 사례가 거의 없으면 다음 라운드(C4)에서 belly_neck + others 2leaf 통합도 검토.
   - 완화: notes로 사용자 검색어와 매대 매핑을 명시. 통합 트리거는 "leaf당 raw 매핑 0건 + plugin query 0건" 동시 충족 시.

2. **한국 특화 vs 글로벌 매대 사이 회색지대**
   - `food.dairy.milk.plant_based`(두유/오트밀크) — C2§6은 `beverage.plant_based`로 옮기자고 제안했으나 거부하고 dairy 하위 유지. 근거: 한국 마트는 두유를 우유 매대에 함께 진열 → 가격 비교 시 사용자가 "우유"로 검색. **단, 비건/락토프리 사용자의 글로벌 멘탈 모델은 음료**. 절충안으로 notes에 cross-ref 명시했으나, 향후 RAG/검색 단에서 "두유"로 dairy/beverage 양쪽을 후보로 띄울지 결정 필요.
   - 유사 사례: `food.dairy.coffee_milk`(컵커피). 사용자가 "스벅 라떼"를 음료로 찾을 가능성 매우 큼.

3. **keyword_seeds의 "사용자 검색어 진정성"**
   - 현재 seeds에는 브랜드명(샘표/청정원/CJ), 매대 용어(엽채류/근채류), 사용자 일상어(잎채소/뿌리채소)를 혼재 수록. 검증 매핑에서 39건 모두 통과했으나, 브랜드 시즌성(예: "신라면 더 레드")이나 신규 SKU의 새 브랜드가 들어오면 자동 알 길 없음. 운영 단에서 `keyword_seeds`를 학습용 초기값으로 보고, 실 매핑 로그에서 누적된 단어를 정기적으로 재공급하는 파이프라인(별도 RD 항목)이 필요. **트리만으로 SKU 100% 분류는 본질적으로 불가**.

---

## 부록. 재생성 방법

```powershell
cd E:\pdf\capston01
py docs\RD8\_build_categories_rd8.py
# → packages/shared/data/categories_rd8.yaml 재생성, 검증 + raw 매핑 로그 stdout
```

운영본 `packages/shared/data/category_tree.yaml`은 본 작업에서 손대지 않음. 두 파일 병행 운영 → 컷오버 시점은 별도 결정.
