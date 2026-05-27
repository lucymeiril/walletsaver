# RD8 C2 카테고리 트리 2패스 적대적 검토 (gpt)

검토 대상: `docs\RD8\categories_draft_opus.yaml`, 기존 export context categories, `real_data_gap_catalog.md`, 마트 4사+코코달인 plugin.yaml, crawler fixture/export 상품명. 결론은 맨 아래 250단어 미만으로 별도 정리했다.

## 1. 누락 카테고리 표

| id 후보 | display_name_ko | 이유 | 어느 마트/자료에서 발견 |
|---|---|---|---|
| `food.processed.fishcake_crabstick_pickled` | 어묵·맛살·단무지 | 초안에는 두부·반찬에 어묵 키워드가 없고, 수산/간편식 어디에도 명시 leaf가 없다. 어묵꼬치·맛살·단무지는 마트 냉장 가공식품의 반복 카테고리다. | 홈플러스 fixture: `두부/김치/반찬 > 어묵/맛살/단무지 > 어묵`, `환공어묵 부산명품 어묵꼬치 10입 350G` |
| `food.meal.tteokbokki_rabokki` | 떡볶이·라볶이 | `food.meal.frozen_korean`의 keyword에 떡볶이떡만 있고, 비비고 떡볶이/짜장라볶이 같은 즉석·냉장·상온 조리식품을 받는 leaf가 없다. 라면/면류로 보내면 비교 단위가 어긋난다. | 코코달인 fixture: `비비고 떡볶이 1440G`, `떡볶이의 신 짜장 라볶이 482G X 3` |
| `food.meal.cup_bowl_rice` | 컵밥·덮밥 | 즉석밥·죽 leaf는 햇반/죽 중심이다. 컵반/덮밥류는 구성식 HMR로 가격 비교 기준이 다르다. | 코코달인 fixture: `햇반컵반 치킨마요덮밥 233G X 6` |
| `food.meal.ready_soup_stew` 세분 또는 keyword 확장 | 탕·전골·레토르트 국탕 | 초안 `즉석국·찌개`에 국/찌개 일부만 있고 사골곰탕, 부대전골, 닭볶음탕, 추어탕, 시래기된장국 등 실 fixture coverage가 부족하다. | 코코달인 fixture 다수: `비비고 사골곰탕진`, `양반 그릴리부대전골`, `양반 통다리닭볶음탕`, `호밍스 남도추어탕` |
| `food.condiment.fish_sauce` | 액젓·피쉬소스 | 장류/소스에 간장·식초·드레싱은 있으나 피쉬소스/액젓이 없다. 김치재료나 소스에 묻히면 일반 사용자가 찾기 어렵다. | 코코달인 fixture: `CHIN-SU FOODS 남늑 피쉬소스 2L` |
| `food.condiment.meat_marinade` | 고기양념·불고기/갈비양념 | 케첩/드레싱/카레와 다른 한국식 조리양념 leaf가 없다. 가격 비교에서 갈비양념·불고기양념은 독립 수요가 크다. | 코코달인 fixture: `백설 소갈비양념 840G X 2` |
| `food.condiment.broth_pack` | 육수팩·육수한포 | `다시다·국물용`에 분말 조미료와 스톡만 있고 티백/팩형 육수 상품을 흡수하기 애매하다. | 코코달인 fixture: `FISH TREE 만능육수 요리한포` |
| `food.condiment.soup_powder` | 분말스프·즉석스프 | 양송이스프/보노스프는 HMR 국탕도 아니고 조미료도 아니다. 별도 leaf 없으면 `food.meal.soup_retort`와 혼선. | 코코달인 fixture: `KRAFT 양송이스프`, `보노 바질크림 스프` |
| `food.noodle.chilled_naengmyeon_makguksu` | 냉면·쫄면·막국수 | 초안 `cold_chilled`에 포함은 되나 display가 “냉장 생면·즉석 면”이라 사용자가 냉면/쫄면을 직관적으로 찾기 어렵고 홈플러스가 반복 노출한다. 최소 alias/keyword 강화 필요. | 홈플러스 fixture: `면사랑 동치미육수 평양물냉면`, `비빔쫄면`, `비빔막국수` |
| `food.noodle.dried_noodle_bulk` | 소면·건면 대용량 | `asian_noodle`에 소면이 있으나 코스트코형 대용량 건면(3.75kg)은 라면/즉석식품과 혼재된다. 대형마트 비교에는 일반 국수/건면 leaf를 더 명확히 해야 한다. | 코코달인 fixture: `풍국면 온동네 풍국면 소면 3.75KG` |
| `food.meal.frozen_hotdog` | 핫도그 | `frozen_chicken` display에 치킨·너겟·꼬치만 보이고 키워드에 핫도그가 섞여 있다. 홈플러스 plugin 경로가 `피자/핫도그/치킨`이므로 leaf 또는 display 반영 필요. | 홈플러스 plugin/fixture: `냉장/냉동/밀키트 > 피자/핫도그/치킨` |
| `food.fresh.meat.processed_chicken_breast` | 닭가슴살·훈제닭 | `food.fresh.meat.chicken`은 생닭 중심이고 `processed`는 햄/소시지 중심이다. 훈제 닭가슴살은 대형마트·코스트코에서 독립 반복 상품군이다. | 코스트코 fixture: `/FreshFood/Poultry/Chicken`, `닭가슴살 훈제 200g x 10입` |
| `food.fresh.fruit.tomato` 또는 `food.fresh.vegetable.tomato` 결정 필요 | 토마토·방울토마토 | 초안은 토마토를 과채류(채소)에 둔다. 홈플러스는 `과일 > 토마토 > 방울토마토`로 취급한다. 어느 한쪽 leaf/alias 없으면 plugin 경로 흡수가 불안정하다. | 홈플러스 fixture: `과일 > 토마토 > 방울토마토` |
| `food.fresh.fruit.kiwi_pomegranate_avocado` alias | 키위·석류·아보카도 | 초안은 키위를 열대과일에 묶는다. 홈플러스 실 경로는 키위/석류/아보카도이며 키위는 노출 빈도가 있다. display/keyword 보강 필요. | 홈플러스 fixture: `과일 > 키위/석류/아보카도`, raw export `제스프리 골드키위/썬골드키위` |
| `food.fresh.seafood.seaweed_snack` | 조미김·김자반·도시락김 | `seaweed` keyword에 조미김은 있으나 display가 해조류라 일반 사용자가 도시락김/김자반을 바로 못 찾는다. 실 데이터에 김 상품이 다수다. | 홈플러스 fixture: `김/미역/기타해조류 > 김/김자반`, `광천재래김 도시락김`, `대천김 김자반` |
| `household.electrical.power_strip` | 멀티탭·전기용품 | `digital.accessory` keyword에 멀티탭이 있지만 마트 멘탈 모델은 생활/전기용품이다. 디지털 주변기기로만 두면 플러그인 전기소모품 흡수가 부자연스럽다. | 코스트코/마트 일반 `Electronics`, 대형마트 생활 전기소모품; 초안 keyword 위치 문제 |
| `home.furniture` | 가구 | 기존 categories에는 `furniture`, 코스트코 plugin endpoint에도 `Furniture`가 있는데 초안은 `home.bedding`만 있고 가구 leaf가 없다. | 기존 context categories, 코스트코 plugin `Furniture` endpoint |
| `baby.kids_toy_book` | 유아동 완구·도서 | 코스트코 endpoint가 `BabyKids`인데 초안 baby는 기저귀/분유/이유식/스킨케어만 있다. Kids 상품군(완구·아동의류·도서)을 흡수 못한다. | 코스트코 plugin `BabyKids` endpoint |
| `outdoor.golf` | 골프용품 | `outdoor.sport_ball` keyword에 골프공/장갑만 섞여 있다. 코스트코/마트에서 골프용품은 별도 시즌 상품군이고 라켓·자전거와 비교 성격이 다르다. | 코스트코 `OutdoorSports`, 대형마트 레저 fixture 가능성 |
| `household.trash_bag` | 종량제·쓰레기봉투 | `household.disposable` keyword에만 쓰레기봉투가 있다. 일회용 접시/컵과 사용 목적·비교 단위가 달라 별도 leaf 후보. | 기존 context household, 마트 생활 카테고리 일반 |

## 2. 과도 평탄화 표

| 현 id | 문제 | 분할 제안 |
|---|---|---|
| `food.fresh.vegetable.root` | 감자/고구마/무/당근/양파/마늘/생강/우엉/연근이 모두 한 leaf. 장바구니 비교에서는 “감자 vs 양파”가 같은 비교군이 아니다. | `potato_sweet_potato`, `onion_garlic`, `radish_carrot`, `root_other` |
| `food.fresh.fruit.stone_pome` | 사과·배·복숭아·자두·체리를 한 leaf로 묶음. 제철/가격대/검색 의도가 다르다. | `apple_pear`, `peach_plum_cherry` |
| `food.fresh.meat.pork` | 삼겹살/목살/앞다리/갈비/다짐육이 한 leaf. 부위별 가격 비교가 핵심인 정육에서 과도하게 평평하다. | `pork_belly_neck`, `pork_leg_shoulder`, `pork_rib`, `pork_minced` |
| `food.fresh.meat.chicken` | 생닭/닭다리/닭가슴살/날개/토종닭이 한 leaf. 닭가슴살·볶음탕용·부분육 비교가 섞인다. | `whole_chicken`, `chicken_parts`, `chicken_breast`, `chicken_stew_cut` |
| `food.fresh.seafood.fish_fresh` | 고등어·갈치·삼치·연어·회감까지 한 leaf. 선어 일반으로는 비교군이 너무 넓다. | `blue_fish`, `white_fish`, `salmon_tuna_sashimi` |
| `food.fresh.seafood.seaweed` | 미역/다시마/김/김자반/도시락김이 한 leaf. 실 fixture는 김 상품이 반복되어 독립 비교 가치가 있다. | `seaweed_dried`, `roasted_laver_seasoned`, `gimjaban` |
| `food.dairy.cheese` | 슬라이스/모짜렐라/크림/자연치즈가 한 leaf. 가격 비교 단위와 구매 목적이 다르다. | `slice_string`, `mozzarella_shredded`, `cream_natural` |
| `food.meal.soup_retort` | 즉석국·찌개·죽 keyword 혼입(`양반죽`)과 탕/전골/국/찌개가 혼재. | `ready_soup`, `ready_stew_tang`, `porridge`는 `instant_rice`에서 분리 검토 |
| `food.meal.frozen_korean` | 떡갈비·전·떡볶이떡·호떡·군고구마가 한 leaf. 냉동 반찬/간식/떡류가 섞임. | `frozen_tteok_garaetteok`, `frozen_jeon_tteokgalbi`, `frozen_korean_snack` |
| `food.condiment.spice_powder` | 후추/고춧가루/깨/허브가 한 leaf. 고춧가루는 김장·양념 핵심 품목이라 독립 비교가 필요. | `pepper_salt_spice`, `red_pepper_powder`, `sesame_perilla_powder`, `western_herb` |
| `household.storage` | 지퍼백·위생장갑·호일·랩·락앤락·진공팩이 한 leaf. 소모품과 용기가 섞인다. | `wrap_foil_paper`, `zipper_bag_glove`, `food_container` |
| `beauty.makeup` | 색조 전체가 한 leaf. 마트 취급이 적다 해도 립/베이스/아이 메이크업은 비교군이 다르다. | 데이터가 충분하면 `lip`, `base`, `eye`; 부족하면 현행 유지하되 “색조 전체”로 명시 |
| `digital.accessory` | 키보드/마우스/보조배터리/충전기/케이블/멀티탭이 한 leaf. 전자소모품과 PC주변기기가 섞임. | `charger_cable_power`, `pc_peripheral`, `mobile_accessory` |
| `gift` | 상품권·기프티콘·명절선물·한우/과일/정관장 선물세트가 루트 leaf 하나. 선물세트와 상품권은 완전히 다름. | `gift.voucher`, `gift.food_set`, `gift.health_set`, `gift.household_set` |

## 3. 과도 세분화 표

| 현 id 집합 | 문제 | 통합 제안 |
|---|---|---|
| `beverage.soft_drink.cola`, `beverage.soft_drink.cider_lemonlime`, `beverage.soft_drink.flavored_carbonated` | 현재 fixture는 콜라/사이다 중심이고 기타 탄산 leaf는 데이터 희박 가능. 다만 콜라·사이다는 비교 가치가 있음. | 1차 런칭은 `cola`, `cider`, `other_carbonated` 유지 가능. leaf당 <5 상품이면 `carbonated`로 임시 통합. |
| `beverage.alcohol.soju`, `makgeolli`, `wine`, `spirits`, `sake_chinese` | 마트 크롤러 source query에 주류가 거의 없고 fixture 근거가 없다. 주류 전체를 깊게 쪼개면 빈 leaf 발생. | plugin/fixture 확보 전 `beverage.alcohol.beer`, `beverage.alcohol.wine`, `beverage.alcohol.other` 정도로 축소. |
| `health.supplement.omega_lutein`, `collagen_inner_beauty`, `joint_diet` | 코스트코 fixture는 멀티비타민 1건 중심. 기능성별 leaf는 실제 상품 수가 검증되지 않음. | `vitamin`, `ginseng`, `supplement_other` 우선. 데이터 누적 후 재분할. |
| `appliance.large.refrigerator`, `washer_dryer`, `aircon_heater`, `tv` | 코스트코 endpoint는 Electronics지만 fixture/export에 대형가전 데이터가 없다. 마트 핫딜 비교에서 leaf가 비기 쉽다. | `appliance.large` 하나로 시작하거나 `appliance.large.home`, `appliance.large.av` 2개만. |
| `fashion.innerwear.socks`, `underwear`, `stocking` | 실 fixture는 양말 1계열만 확인. 속옷/스타킹 leaf는 빈 leaf 가능. | `fashion.innerwear` 아래 `socks_stocking`, `underwear` 정도로 축소. |
| `outdoor.camping`, `fitness`, `sport_ball` | 코스트코 endpoint 근거만 있고 상품 fixture가 없다. 세분 leaf별 1~2건 위험. | `outdoor.camping`, `outdoor.sports_fitness` 2개로 시작. |
| `food.noodle.ramen.spicy`, `mild`, `jjajang_volcano`, `cup` | 라면은 데이터가 많지만 맛 기준(spicy/mild) 분류는 NLP 오류가 크고 같은 브랜드 가격 비교를 방해할 수 있다. | `bag_ramen`, `cup_ramen`, `bibim_jjajang_ramen`이 더 안정적. |
| `food.condiment.oil.cooking`, `olive`, `sesame_perilla` | 식용유는 중요하지만 fixture는 올리브유 중심. 참기름/들기름 leaf가 빈약할 수 있다. | 데이터 부족 시 `oil_cooking_olive`, `oil_sesame_perilla` 2개로 축소. |

## 4. 이름 개선 (id/display 매핑 추가 안)

| 현 id | 현 display | 문제 | 개선 display/alias 제안 |
|---|---|---|---|
| `food.fresh.vegetable.leaf` | 엽채류 | 일반 사용자에게 전문어. | `잎채소·쌈채소`; alias: 엽채류 |
| `food.fresh.vegetable.root` | 근채류 | 전문어. | `뿌리채소·감자/양파` |
| `food.fresh.vegetable.fruit_vegetable` | 과채류 | 전문어이고 과일과 혼동. | `오이·호박·고추·토마토` |
| `food.fresh.vegetable.herb_spice` | 허브·향신채 | “향신채”가 낯섦. | `대파·마늘·허브류` 또는 마늘은 root에서 분리 |
| `food.fresh.fruit.stone_pome` | 사과·배·복숭아 | id가 일반 개발자도 난해. | id `apple_pear_peach`; display는 유지/분할 |
| `food.fresh.meat.duck_other` | 오리·기타 육류 | “기타”가 넓고 양고기와 오리가 다름. | `오리·양고기`; 기타는 fallback로만 |
| `food.noodle.ramen.jjajang_volcano` | 짜장·비빔라면 | `volcano`는 한국 사용자/운영자에게 의미 불명. | id `jjajang_bibim`; display `짜장·비빔·볶음라면` |
| `food.snack.nut_legume_snack` | 견과·콩 스낵 | “legume” id가 난해하고 새우깡이 keyword에 중복. | id `peanut_bean_snack`; display `땅콩·콩과자` |
| `food.snack.rice_cracker_popcorn` | 쌀과자·팝콘 | 자유시간(초코바)이 keyword에 들어가 부정확. | display 유지, 자유시간 제거/`chocolate_bar` 후보 |
| `food.dried` | 견과·건과·건어물 | 실제 하위에 건어물이 없음(수산 쪽에 있음). | `견과·건과`; 건어물 문구 제거 |
| `food.dairy.coffee_milk` | 컵커피·라떼 | 유제품 하위인데 라떼/컵커피는 음료로 찾을 사용자도 많음. | `컵커피·유음료`; beverage alias 필요 |
| `food.meal.frozen_ice` | 아이스크림·빙과 | id가 “냉동 얼음”처럼 보임. | id `icecream`; parent는 `food.frozen` 또는 `snack` 검토 |
| `food.condiment.stock_dasida` | 다시다·국물용 | 다시다 브랜드 의존적. | `조미료·육수` |
| `beverage.coffee.rtd` | 컵·캔 RTD 커피 | RTD는 일반 사용자에게 어려움. | `즉석 커피음료(컵·캔)` |
| `beverage.tea_rtd` | RTD 차 음료 | RTD 난해. | `차 음료(페트·캔)` |
| `household.dish.sponge_scour` | 수세미·고무장갑 | 행주도 keyword에 있어 display 누락. | `수세미·고무장갑·행주` |
| `health.supplement.collagen_inner_beauty` | 콜라겐·이너뷰티 | 이너뷰티는 마케팅어. | `콜라겐·피부영양` |
| `health.supplement.joint_diet` | 관절·다이어트 | 관절영양제와 다이어트 보조제는 사용자 의도가 다름. | 분리 또는 `관절/다이어트 보조식품` |
| `home.tool_hardware` | 공구·DIY·운반 | 운반카트와 공구가 한 display에 섞임. | `공구·DIY`, 별도 `카트·운반용품` 후보 |

## 5. unit_kind_default 오류 표

| id | 현재 | 문제 | 제안 |
|---|---:|---|---:|
| `food.fresh.vegetable.fruit_vegetable` | count | 토마토/방울토마토/고추/오이/호박은 g/kg/팩이 많다. raw에도 애호박 1개가 있지만 홈플러스 대추방울토마토 500G/900G가 있음. | weight |
| `food.fresh.fruit.berry` | count | 딸기/블루베리류는 g/팩 단가 비교가 일반적. | weight |
| `food.fresh.fruit.tropical` | count | 바나나/키위/망고/아보카도는 입수와 중량 혼재. 홈플러스 키위 7-10입, raw 골드키위 EA라 count도 가능하나 kg/g 상품도 많다. | count 유지 가능하되 `unit_policy: mixed(count, weight)` 필요 |
| `food.dairy.yogurt.spoon` | count | 떠먹는 요거트는 80g×n, 400g/900g 대용량이 많아 개당보다 g당 비교가 유리. | weight |
| `food.dairy.butter_cream` | weight | 생크림/휘핑크림은 ml, 버터/마가린은 g. 한 leaf의 기본 단위가 혼재. | leaf 분리: butter=weight, cream=volume |
| `food.noodle.ramen.spicy`, `mild`, `jjajang_volcano` | pack | 상품명은 120G×20 등 중량 기반도 많다. pack은 묶음 수 비교에 좋지만 단가 비교는 g 또는 count(봉) 병행 필요. | count 또는 mixed(count, weight); 최소 pack_qty 파싱 규칙 명시 |
| `food.noodle.ramen.cup` | count | 컵라면은 65g/86g/큰컵 중량 차이가 커 count만으로 왜곡. | weight 보조 필수 또는 mixed |
| `food.meal.instant_rice` | count | 햇반 210g×n은 count와 weight 모두 필요. count만 쓰면 130g/210g/300g 비교 왜곡. | mixed(count, weight), default weight 권장 |
| `food.meal.meal_kit` | count | 2인분/652g 등 중량·인분 기준. count만으로 가격 비교 부적절. | weight 또는 pack+serving metadata |
| `food.meal.frozen_pizza_pasta` | count | 냉동피자는 판당 비교도 가능하지만 중량 차가 큼. | weight |
| `food.meal.frozen_ice` | count | 바/콘은 count, 파인트/통 아이스크림은 volume/weight. | mixed(count, volume/weight) |
| `food.condiment.mayo_ketchup` | volume | 마요네즈는 g, 케첩/머스타드는 g/ml 혼재. | weight 또는 mixed; 가능하면 mayo와 ketchup/sauce 분리 |
| `food.condiment.dressing` | volume | 드레싱은 ml도 있지만 g/kg(오리엔탈 드레싱 1KG)도 존재. | mixed(volume, weight) |
| `beverage.coffee.instant_stick` | count | 스틱 수 비교는 좋지만 11.7g×100T처럼 중량 차가 커 g 보조가 필요. | count + weight 보조 |
| `beverage.tea` | count | 티백은 count, 잎차/보리차 티백 대용량은 weight도 중요. | mixed(count, weight) |
| `household.paper.toilet_tissue` | count | 롤 수만으로 길이/겹수 차이를 반영 못함. 코스트코 `40m x 60` 근거. | count + length metadata |
| `household.paper.kitchen_towel` | count | 매수×롤(150매×6롤) 기준이므로 단순 count보다 sheet_count가 필요. | count + sheet metadata |
| `household.laundry.detergent_pod_powder` | count | 캡슐은 count, 가루세제는 kg. 한 leaf 기본 단위 오류. | 분리: pod=count, powder=weight |
| `household.cleaning.insecticide` | volume | 매트/훈증기/좀약/바퀴벌레약은 count/pack이 많다. | mixed 또는 분리 |
| `baby.snack_meal` | count | 이유식 파우치/병/아기간식은 g/ml 혼재. | mixed(weight, volume, count) |
| `pet.litter_supplies` | weight | 모래는 weight지만 배변패드/산책줄/하네스/캣타워/펫샴푸는 count/volume. | 분리: litter=weight, pad=count, supplies=count, shampoo=volume |

## 6. 부모 재배치 제안

| 현 id | 현재 parent | 제안 parent | 이유 |
|---|---|---|---|
| `food.fresh.tofu_sundubu` | `food.fresh` | `food.chilled.tofu_bean` 또는 `food.processed_chilled.tofu` | 두부는 신선 매대에 있지만 상품 성격은 냉장 가공식품. 홈플러스도 `두부/김치/반찬` 독립 경로다. 신선 채소/정육과 같은 parent는 멘탈 모델이 흔들린다. |
| `food.fresh.banchan_kimchi` | `food.fresh` | `food.chilled.banchan_kimchi` | 김치·반찬·젓갈은 신선 원물보다 냉장 가공/반찬. `food.fresh`가 너무 넓어진다. |
| `food.fresh.meat.processed` | `food.fresh.meat` | `food.chilled.processed_meat` 또는 `food.canned`와 별도 | 햄/소시지/베이컨은 정육이 아니라 냉장 가공육. 정육 부위 비교와 섞이면 안 된다. |
| `food.dairy.milk.plant_based` | `food.dairy.milk` | `beverage.plant_based` 또는 `food.dairy_alt` | 두유/아몬드브리즈/오트밀크는 유제품이 아니며 알레르기/비건 검색 의도상 분리 필요. |
| `food.dairy.coffee_milk` | `food.dairy` | cross-list: `beverage.coffee.rtd` alias | 바리스타룰스 라떼는 유음료지만 사용자는 컵커피로도 찾는다. 단일 parent면 매칭 누락 위험. |
| `food.meal.frozen_ice` | `food.meal` | `food.frozen.icecream` 또는 `food.snack.icecream` | 아이스크림은 간편식/HMR이 아니다. 냉동 디저트/간식이 더 자연스럽다. |
| `food.dried.dried_vegetable` | `food.dried` | `food.fresh.vegetable.dried` 또는 `food.grain_dried` | 건나물은 견과·건과와 구매 맥락이 다르다. |
| `food.dried` | `food` | `food.nut_dried_fruit`로 rename | display에 건어물이 있으나 건어물 leaf가 수산에 따로 있어 parent 명칭 충돌. |
| `household.dish.sponge_scour` | `household.dish` | split: `household.dish.sponge`, `household.cleaning.glove_cloth` | 고무장갑/행주는 설거지 보조지만 수세미와 비교 단위가 다르다. |
| `household.storage` | `household` | split 후 일부는 `home.storage_container`와 merge | 락앤락/보관용기는 이미 `home.storage_container`에도 있어 중복 parent. |
| `home.auto` | `home` | `automotive` root 또는 `household.auto` | 코스트코 endpoint `Automotive`는 독립 카테고리. 집/주방용품 하위는 어색하다. |
| `digital.accessory` keyword `멀티탭` | `digital` | `household.electrical` | 멀티탭은 디지털 액세서리보다 생활 전기용품. |
| `gift` | root leaf | root + children | 선물세트는 식품/건강/생활 세트와 상품권이 섞여 parent가 너무 얕다. |

## 7. 마트 plugin.yaml 비매칭 항목 표

| 마트/소스 | 실 크롤 카테고리 경로 또는 source_map | 매핑 가능 여부 | 평가/조치 |
|---|---|---|---|
| emart | `category_queries: 과일, 채소, 정육, 수산, 유제품, 생수, 간편식` | 가능 | 초안의 핵심 식품 트리로 흡수 가능. 단 `간편식` 내부 냉장/냉동/즉석식 구분 강화 필요. |
| homeplus | `category_queries: 과일, 채소, 정육, 계란, 쌀, 생수, 우유, 유제품, 간편식, 냉동식품, 라면, 과자, 커피, 세제, 화장지` | 대부분 가능 | `냉동식품`이 초안에서는 `food.meal.*`에 흩어짐. `food.frozen` parent가 없어서 plugin path 매핑이 지저분해질 수 있음. |
| homeplus fixture | `냉장/냉동/밀키트 > 피자/핫도그/치킨 > 치킨` | 부분 가능 | `food.meal.frozen_chicken`으로 가능하지만 핫도그/피자/치킨 parent가 명확하지 않다. |
| homeplus fixture | `장류/양념/제빵 > 식용유/참기름 > 올리브유` | 가능 | `food.condiment.oil.olive`로 정확. |
| homeplus fixture | `과자/시리얼 > 과자/쿠키/파이 > 파이/케이크류` | 가능 | `food.snack.pie_cake`로 가능. |
| homeplus fixture | `제지/위생/뷰티 > 화장지/키친타월/물티슈 > 키친타월` | 가능 | `household.paper.kitchen_towel`. 단 홈플러스 상위가 뷰티와 섞여 있어 매핑 테이블 필요. |
| homeplus fixture | `견과 > 믹스넛/하루견과 > 믹스넛`; `캐슈넛/피스타치오`, `아몬드/호두/땅콩` | 가능 | `food.dried.nut_mix`; 상품 수 충분하면 견과 하위 분할 검토. |
| homeplus fixture | `정육/계란 > 수입육 > 국거리/불고기/다짐/샤브샤브` | 가능 | `food.fresh.meat.beef_imported`; 부위별 세분 필요. |
| homeplus fixture | `수산물/건어물 > 생선 > 조기/굴비` | 가능 | `food.fresh.seafood.fish_dried_salted`; display가 굴비까지 포함해 적절. |
| homeplus fixture | `패션의류/잡화 > 패션잡화 > 양말/스타킹 > 양말` | 가능 | `fashion.innerwear.socks`. |
| homeplus fixture | `우유/유제품 > 우유 > 흰우유/…`, `딸기/초…` | 가능 | `food.dairy.milk.white/flavored`. |
| homeplus fixture | `두부/김치/반찬 > 두부/나물 > 부침/찌…` | 가능하지만 parent 부적합 | 초안 `food.fresh.tofu_sundubu`로 받지만 신선 parent 재배치 권장. |
| homeplus fixture | `두부/김치/반찬 > 어묵/맛살/단무지 > 어묵` | 비매칭 | 신규 `food.processed.fishcake_crabstick_pickled` 필요. |
| homeplus fixture | `과일 > 토마토 > 방울토마토` | 부분 가능 | 초안은 채소 과채류로 받음. 홈플러스 path 흡수를 위해 토마토 alias/leaf 정책 필요. |
| homeplus fixture | `라면/즉석식품/통조림 > 당면/건면/스파게티 > 즉석면요…` | 부분 가능 | 냉면/쫄면/막국수는 `food.noodle.cold_chilled` keyword로 가능하나 display/alias 부족. |
| homeplus fixture | `생수/음료/주류 > 탄산/이온/비타민음료 > 콜라/사…` | 가능 | `beverage.soft_drink.cola/cider_lemonlime`; 이온음료는 `energy_health`와 혼재 가능. |
| lottemart | `category_queries: 과일, 채소, 정육, 계란, 생수, 유제품, 간편식` | 가능 | 홈플러스와 동일. 다만 plugin이 롯데 내부 세부 경로를 드러내지 않아 fixture 확대 필요. |
| costco | endpoint `/c/FoodandBeverage` | 부분 가능 | 식품 전반 가능하나 코스트코 대용량 가공식품은 초안의 세부 누락(피쉬소스, 시럽, 스프 등)이 드러남. |
| costco | endpoint `/c/FreshFood` | 가능 | 신선식품 전반 가능. 단 `Poultry/Chicken/Smoked-Chicken-Breast`는 생닭/가공닭 경계 보완 필요. |
| costco | endpoint `/c/FrozenRefrigerated` | 부분 가능 | 초안에 `food.frozen` 상위가 없어 냉동·냉장 경로가 meal/dairy/fresh에 산재. 매핑 유지보수성이 낮음. |
| costco | endpoint `/c/HealthBeauty` | 가능 | `beauty`, `health`로 흡수 가능. body lotion fixture는 가능. |
| costco | endpoint `/c/Electronics` | 가능 | `appliance`, `digital`로 가능하나 대형가전 세분은 데이터 부족. |
| costco | endpoint `/c/Furniture` | 비매칭 | 초안에 가구 root/leaf 없음. `home.furniture` 필요. |
| costco | endpoint `/c/ClothingFootwear` | 가능 | `fashion`으로 가능. |
| costco | endpoint `/c/OutdoorSports` | 부분 가능 | `outdoor`로 가능하지만 golf/seasonal/cycling 등 실제 세부 흡수력 부족. |
| costco | endpoint `/c/KitchenDining` | 가능 | `home.cookware`, `home.kitchen_tool`, `home.tableware`; 조리도구/식기 괜찮음. |
| costco | endpoint `/c/PetSupplies` | 가능 | `pet`으로 가능하나 사료/모래/용품 단위 분리 필요. |
| costco | endpoint `/c/BabyKids` | 부분 비매칭 | baby 소모품은 가능, kids 완구/아동용품은 없음. |
| costco | endpoint `/c/Office` | 가능 | `office` 단일 leaf 가능. |
| costco | endpoint `/c/CleaningProducts` | 가능 | `household.laundry/cleaning/dish`; 세제 단위 조정 필요. |
| costco | endpoint `/c/Automotive` | 부분 가능 | `home.auto`가 있으나 parent가 부자연스럽다. root/household 재배치 권장. |
| costco search keyword | `고기`, `생선`, `빵`, `치즈`, `휴지`, `세제`, `샴푸` 등 | 가능 | 대부분 가능. `빵`은 `food.breakfast.bread`, 샴푸는 `beauty.haircare.shampoo`. |
| cocodalin plugin | output category broad, fixture `가공식품`, `식품`, `세제/청소`, `건강기능식품` | 부분 가능 | broad category는 가능하나 가공식품 내부 피쉬소스/시럽/스프/라볶이/컵반 등 초안 누락 많음. |

## 8. opus 자기검열 5건 평가

초안 파일에 “자기검열 5건”이라는 명시 섹션은 없다. 따라서 초안 notes에서 스스로 위험을 표시한 5개 항목을 기준으로 평가한다.

| 항목 | opus 판단 | 동의/반대 | 추가 의견 |
|---|---|---|---|
| 두부·순두부: “마트별 분류 상이 — 채소/유제품/가공식품 매핑 모두 흡수” | `food.fresh.tofu_sundubu`에 둠 | 반대(부분) | leaf 자체는 필요하나 parent가 `food.fresh`인 것은 사용자 멘탈 모델과 plugin path(`두부/김치/반찬`) 모두에 어긋난다. `food.chilled`/`food.processed_chilled` 상위 신설 권장. 어묵·맛살·단무지 누락도 함께 처리해야 한다. |
| 컵커피·라떼: “분류상 음료/유제품 모두 가능 — 유음료로 통합” | `food.dairy.coffee_milk` | 부분 동의 | 바리스타룰스 같은 유음료는 dairy가 맞지만 사용자는 “커피”에서 찾는다. 단일 parent 대신 beverage coffee alias/cross mapping 필요. |
| 라면 spicy note: “봉지/컵 모두 포함” | `spicy` leaf에 봉지/컵 포함 | 반대 | 컵라면 leaf를 따로 만들었는데 spicy에 봉지/컵 모두 포함하면 중복·충돌. 맛 기준보다 용기/조리형태(`bag_ramen`, `cup_ramen`, `bibim_jjajang`)가 가격 비교에 안정적. |
| 김치·반찬을 신선 하위에 배치 | `food.fresh.banchan_kimchi` | 반대 | 김치/반찬/젓갈/장아찌는 냉장 가공·반찬 parent가 더 자연스럽다. 신선 원물과 같은 parent는 필터링·단위·검색 intent가 흔들린다. |
| gift: “명절/이벤트 시즌 마트 핵심 카테고리. 4사 모두 별도 페이지 운영” | `gift` 단일 root leaf | 동의하나 불충분 | gift root는 필요. 그러나 상품권과 식품/건강/생활 선물세트가 한 leaf라 비교 불가. 최소 voucher vs gift_set, 선물세트는 식품/건강/생활로 분기해야 한다. |

## 9. 종합 의견 — 3패스 우선순위

**P0 (반드시 수정)**
- `food.chilled` 또는 `food.processed_chilled` 상위 신설: 두부·김치·반찬·어묵/맛살/단무지·냉장면을 정리.
- 코스트코 `Furniture`, `BabyKids`의 kids, 홈플러스 `어묵/맛살/단무지` 비매칭 해소.
- 라면 분류를 맛(spicy/mild) 중심에서 형태(`bag`, `cup`, `bibim/jjajang`) 중심으로 재설계.
- unit_kind mixed 정책 도입: 즉석밥, 라면, 요거트, 티슈/키친타월, 세제 pod/powder 등.

**P1 (강력 권장)**
- `food.frozen` parent 신설: 냉동피자/핫도그/치킨/만두/아이스크림/냉동한식이 현재 HMR에 과밀.
- 정육·수산·채소 핵심 leaf는 가격 비교 단위에 맞게 부위/품목별로 추가 분할.
- 코코달인 가공식품 fixture 기반으로 피쉬소스, 고기양념, 육수팩, 즉석스프, 떡볶이/라볶이, 컵밥 보강.

**P2 (데이터 누적 후)**
- 대형가전, 주류, 건강기능식품, outdoor 세부 leaf는 빈 leaf 위험이 커 축소 유지 후 실데이터로 확장.
- display_name은 전문어(엽채류/근채류/과채류/RTD/이너뷰티)를 일반어+alias 구조로 바꿀 것.

### 250단어 미만 결론

opus 초안은 기존 flat taxonomy보다 훨씬 낫지만, “마트 실제 경로 흡수” 관점에서는 냉장가공/냉동/선물/가구·키즈 쪽이 빈틈이다. 특히 홈플러스 `어묵/맛살/단무지`, 코스트코 `Furniture`, `BabyKids` kids 상품군은 현재 트리에 직접 들어갈 곳이 없다. 두부·김치·반찬을 `fresh`에 둔 결정은 재고해야 하며, 냉장가공 parent가 필요하다. 라면은 매운/순한 맛 기준보다 봉지/컵/비빔·짜장 기준이 가격 비교에 맞다. unit_kind는 단일 default로 버티기 어려운 leaf가 많으므로 mixed/metadata 정책을 넣어야 한다. 3패스는 P0 비매칭과 parent 재배치부터 처리하고, 데이터가 부족한 주류·건강·가전·레저 세분 leaf는 과감히 접는 방향이 안전하다.

