"""Initial real-catalog evidence contracts, independent of live sites or DBs."""
from __future__ import annotations

import pytest
from services.initial_audited_emart_produce import FRUIT_TITLES, reviewed_emart_produce_leaf
from services.initial_audited_costco_cleaning import TITLES as CLEANING_TITLES, URL_ENTRIES as CLEANING_URL_ENTRIES, reviewed_costco_cleaning_leaf
from services.initial_audited_homeplus_seafood import ENTRIES as SEAFOOD_ENTRIES, reviewed_homeplus_seafood_leaf
from services.initial_audited_homeplus_snacks import ENTRIES as SNACK_ENTRIES, reviewed_homeplus_snack_leaf

from services.initial_taxonomy import (
    LEAVES,
    classify_record,
    contains_term,
    keyword_collisions,
    keyword_definitions,
    native_category_key,
    normalize_source_path,
    source_evidence,
    taxonomy_categories,
    validate_keyword_definitions,
    validate_taxonomy,
)


def test_semantic_revision_leaves_are_review_only_without_unproved_specs():
    ids={'appliances.kitchen.egg_cooker.standard','appliances.kitchen.soy_maker.standard',
         'appliances.kitchen.coffee_machine.capsule','household.cooking.grill_accessories.kit',
         'household.gardening.plants.potted_cactus','household.kitchen.coffee.drip_assist_set',
         'household.kitchen.storage.rice_container','household.kitchen.drinkware.tumbler',
         'food.seasonings.baking.food_color'}
    leaves={leaf.id:leaf for leaf in LEAVES if leaf.id in ids}
    assert set(leaves)==ids
    assert all(not leaf.source_labels and not leaf.name_terms for leaf in leaves.values())
    validate_taxonomy(taxonomy_categories(ids),ids)
    assert not keyword_collisions(keyword_definitions(ids))
    for title in ('계란찜기','두유제조기','원터치 텀블러','아이싱 칼라'):
        assert classify_record(_raw('emart','베스트',title))['unified_category_id'] is None


def test_exact_review_rejects_positive_form_not_absent_corroboration(monkeypatch):
    from services import initial_taxonomy as taxonomy
    from services.initial_numbered_reviews import rules
    matches=[key for key,leaf in rules().items() if '불고기' in key[2] and '410G' in key[2] and leaf=='food.meals.rice.bibimbap']
    assert len(matches)==1
    mart,path,title=matches[0]
    result=classify_record(_raw(mart,path,title))
    assert result['unified_category_id']=='food.meals.rice.bibimbap'
    assert result['reviewed_rejected_category_ids']==['food.meals.rice.fried']
    assert classify_record(_raw(mart,path,title+' + 볶음밥 세트'))['unified_category_id'] is None
    assert classify_record(_raw(mart,'다른 경로',title))['unified_category_id'] is None
    # An old accepted listing-bound proposal is not immutable semantic truth:
    # only this exact reviewed positive veto can remove its wrong form.
    monkeypatch.setattr(taxonomy,'reviewed_chat_leaf',lambda record,evidence:'food.meals.rice.fried')
    assert classify_record(_raw(mart,path,title))['unified_category_id']=='food.meals.rice.bibimbap'
    # A URL candidate cannot be removed even if its title veto is known.
    monkeypatch.setattr(taxonomy,'_url_candidates',lambda evidence:({'food.meals.rice.fried'},[]))
    conflict=classify_record(_raw(mart,path,title))
    assert conflict['unified_category_id'] is None
    assert conflict['candidate_category_ids']==['food.meals.rice.bibimbap','food.meals.rice.fried']


def test_ghee_oil_context_is_specific_and_all_urls_still_checked():
    url='https://www.costco.co.kr/Foods/Processed-Food/Oils/Organic-Valley-Ghee-Butter-368g/p/689481'
    title='ORGANIC VALLEY기버터 368G'
    assert classify_record(_raw('costco','우유',title,canonical_url=url))['unified_category_id']=='food.dairy.cheese.butter'
    assert classify_record(_raw('costco','우유','브랜드 그릭요거트 150g',canonical_url=url))['unified_category_id'] is None
    assert classify_record(_raw('costco','우유',title,canonical_url=url,
        detail_url='https://www.costco.co.kr/Appliances/Blenders/Product/p/2'))['unified_category_id'] is None


def test_existing_topping_and_complete_noodle_recipe_do_not_disable_ingredient_veto():
    yogurt_path=('우유/유제품','요거트/요구르트','떠먹는 요구르트','토핑요거트')
    title='서울우유 비요뜨 쿠키앤크림 131G*2'
    assert classify_record(_raw('homeplus',yogurt_path,title))['unified_category_id']=='food.dairy.yogurt.topping'
    for path,changed in [(yogurt_path,title+' + 쿠키 세트'),('과자/시리얼',title)]:
        assert classify_record(_raw('homeplus',path,changed))['unified_category_id'] is None
    from services.initial_numbered_reviews import rules
    noodle='면사랑 동치미육수 평양물냉면 1026G'
    key=next(key for key,leaf in rules().items() if key[2]==noodle and leaf=='food.meals.noodles.naengmyeon')
    assert classify_record(_raw(key[0],key[1],noodle))['unified_category_id']=='food.meals.noodles.naengmyeon'
    assert classify_record(_raw(key[0],key[1],noodle+' + 소스 세트'))['unified_category_id'] is None


def test_reviewed_polluted_shelves_replace_only_the_exact_old_hold_contracts():
    contexts=[
        ('costco','계란','보만 2단 계란찜기 EB7210WG','appliances.kitchen.egg_cooker.standard'),
        ('emart','수산물/건해산','국산 참기름 들기름 만전재래김 4g*20봉','food.seafood.seaweed.laver'),
        ('lottemart',['델리ㆍ즉석조리','샌드위치ㆍ햄버거','샌드위치'],'탱글탱글 소세지가 쏙! 15핫도그 (팩)','food.meals.prepared.hotdog'),
        ('homeplus','우유/유제품 > 두유 > 일반두유','매일 아몬드브리즈 무당 950ML','food.plant.drinks.almond'),
        ('costco','우유','마이아 프로틴 메이커 두유 제조기 800ml','appliances.kitchen.soy_maker.standard'),
    ]
    for mart,path,title,leaf in contexts:
        assert classify_record(_raw(mart,path,title))['unified_category_id']==leaf
        assert classify_record(_raw(mart,'다른 진열',title))['unified_category_id'] is None
        assert classify_record(_raw(mart,path,title+' + 다른상품 세트'))['unified_category_id'] is None



# Parent-reviewed exact Costco contexts; all other negative contexts remain held.
_REVIEWED_LEDGER001 = {
    ('고기', '궁한우나주식곰탕500gx3 +소스+ 갈비찜1kgx2 +당면'): 'food.meals.sets.soup_meat',
    ('고기', '부추고기순대500Gx3 족발슬라이스 960g'): 'food.meals.sets.sundae_jokbal',
    ('고기', '설성목장 한우불고기 덮밥소스100g x 8'): 'food.seasonings.sauces.rice_topping',
    ('고기', '안방그릴 울트라 AB1107CO'): 'household.cooking.grills.cooking',
    ('고기', '오크우드 장작 15kg'): 'household.outdoor.fire.firewood',
    ('고기', '파이어폭스 BBQ 석쇠 5개입 / 최소구매 2'): 'household.cooking.grill_accessories.grate',
    ('과일', '샤인머스캣 애플망고 사과 혼합선물세트4.6kg'): 'food.produce.assortments.fresh_fruit',
    ('과일', '애플망고 골드키위세트'): 'food.produce.assortments.fresh_fruit',
    ('과일', '허니듀 & 머스크 멜론 세트 4입 (각 2입)'): 'food.produce.fruit.melon',
    ('과일', '휴롬 원액기 P310 E31ST-BFM02MM'): 'appliances.kitchen.juicer.standard',
    ('과자', 'Delici 쿠키버터무스 76g x 6'): 'food.snacks.desserts.mousse',
    ('과자', '락앤락 휴대용 과일 & 요거트 보틀 600ml x 2P'): 'household.kitchen.storage.food_bottle',
    ('과자', '카스 초음파 야채 과일 세척기 4L'): 'appliances.kitchen.produce_washer.ultrasonic',
    ('과자', '프리미엄 제철과일 선물세트 5.5KG 이상'): 'food.produce.assortments.fresh_fruit',
    ('과자', '프리미엄 제철과일 선물세트 총 3.4kg이상'): 'food.produce.assortments.fresh_fruit',
    ('과자', '해품은김과 김부각 세트'): 'food.meals.sets.laver_laver_chip',
    ('김치', '아워홈 갈치김치 800 g x 4'): 'food.preserved.kimchi.hairtail',
    ('김치', '종가 김치공방 보쌈김치 1kg + 겉절이 1kg'): 'food.preserved.kimchi.assortment',
    ('김치', '종가 포기김치1kg x 2열무김치900g x 1혼합팩'): 'food.preserved.kimchi.assortment',
    ('라면', '코렐 더블링 라떼 면기 세트 4P'): 'household.kitchen.tableware.noodle_bowl',
    ('세제', '네일메드코세정제리필세정용분말250포'): 'beauty.personal.nasal.rinse_powder',
    ('세제', '네일메드코세정제콤보(용기3개+세정용분말250포)'): 'beauty.personal.nasal.rinse_kit',
    ('세제', '넬리 소다세제 1.5kg + 울드라이어볼x 4'): 'household.cleaning.laundry.detergent_dryer_ball_set',
    ('세제', '무아스 소프트 버블 & 젤 자동 디스펜서 2P'): 'household.hygiene.dispensers.automatic',
    ('세제', '펠로우즈 문서세단기 12C 19L (꽃가루형)'): 'office.equipment.shredder.standard',
    ('쌀', '대구농산 쌀가루 2.5kg'): 'food.seasonings.baking.plain_rice_flour',
}
def _raw(mart, path, name="검수할 상품", **extra):
    return {"mart": mart, "name": name, "attributes": {"mart_native_category_path": path}, **extra}


@pytest.mark.parametrize(("mart", "path", "title", "leaf"), [
    ("homeplus", "커피/차 > 코코아/핫초코 > 가향분말류 > 기타가향분말류",
     "티젠 콤부차 레몬 30T (150G)", "food.drinks.powders.kombucha"),
    ("homeplus", "커피/차 > 코코아/핫초코 > 가향분말류 > 기타가향분말류",
     "티젠 브이핏 말차레몬 10T(40G)", "food.drinks.powders.tea_mix"),
    ("costco", "음료", "쌍계 김동곤명인의 쑥차 파우더 15g x 40",
     "food.drinks.powders.herbal_tea"),
    ("emart", "커피/원두/차", "결명자차 18티백 (주전자용)", "food.drinks.tea.herbal"),
    ("emart", "커피/원두/차", "둥글레차 50티백", "food.drinks.tea.herbal"),
])
def test_literal_tea_preparation_form_preserves_source_conflicts(mart, path, title, leaf):
    assert classify_record(_raw(mart, path, title))["unified_category_id"] == leaf
    assert classify_record(_raw(mart, "자동차", title))["unified_category_id"] != leaf
    assert classify_record(_raw(mart, path, title + " + 젤리 세트"))["unified_category_id"] != leaf


@pytest.mark.parametrize("title", [
    "콤부차 315ml", "콤부차 1L", "콤부차 30티백", "콤부차 젤리 150g",
    "말차 주스 150g", "말차 샴푸 150g",
])
def test_powder_shelf_does_not_override_other_declared_forms(title):
    path = "커피/차 > 코코아/핫초코 > 가향분말류 > 기타가향분말류"
    result = classify_record(_raw("homeplus", path, title))
    assert result["unified_category_id"] not in {
        "food.drinks.powders.kombucha", "food.drinks.powders.tea_mix",
    }


def test_iced_tea_mix_needs_typed_native_evidence_not_grams():
    title = "4C 아이스티 복숭아맛 2.34kg"
    url = "https://www.costco.co.kr/Foods/Beverages/CocoaDrink-Mix/4C-Iced-Tea-Mix-Peach-234kg/p/505619"
    leaf = "food.drinks.powders.tea_mix"
    assert classify_record(_raw("costco", "과일", title, canonical_url=url))["unified_category_id"] == leaf
    assert classify_record(_raw("costco", "과일", title))["unified_category_id"] != leaf
    assert classify_record(_raw("costco", "과일", title, canonical_url=url.replace("www.costco.co.kr", "other.invalid")))["unified_category_id"] != leaf
    conflict = classify_record(_raw("costco", "과일", title, canonical_url=url,
        detail_url="https://www.costco.co.kr/Beauty/Razors/Blade/p/2"))
    assert conflict["unified_category_id"] is None
    assert "beauty.personal.shaving.razor" in conflict["candidate_category_ids"]


@pytest.mark.parametrize(("path", "title"), [
    ("커피/차 > 코코아/핫초코 > 가향분말류 > 가향코코아믹스", "동서 제티 쵸코스틱 20T (340G)"),
    ("커피/차 > 코코아/핫초코 > 코코아 > 코코아믹스", "허쉬 말차 핫초코 160G"),
])
def test_cocoa_mix_form_is_not_a_matcha_or_ready_milk_inference(path, title):
    leaf = "food.drinks.powders.cocoa"
    assert classify_record(_raw("homeplus", path, title))["unified_category_id"] == leaf
    assert classify_record(_raw("homeplus", path, "말차 우유 200ml"))["unified_category_id"] != leaf
    assert classify_record(_raw("homeplus", "우유/유제품", title))["unified_category_id"] != leaf


@pytest.mark.parametrize(("title", "url", "leaf"), [
    ("커피빈 얼그레이 바닐라라떼 25g x 40ct",
     "https://www.costco.co.kr/Foods/CoffeeTeaDrink/TeaLiquid-Tea/Coffee-Bean-Earl-Grey-Vanilla-Latte-25g-x-40ct/p/669844", "food.drinks.powders.tea_mix"),
    ("크라스탄 유기농 오르조 보리차 200g",
     "https://www.costco.co.kr/Foods/CoffeeTeaDrink/TeaLiquid-Tea/Crastan-Organic-Orzo-Barley-Tea-200g/p/680239", "food.drinks.powders.grain"),
])
def test_published_preparation_form_stays_bound_to_original_native_context(title, url, leaf):
    assert classify_record(_raw("costco", "커피", title, canonical_url=url))["unified_category_id"] == leaf
    for path, changed_url in [("다른 경로", url), ("커피", url + "-other"), ("커피", "https://[malformed")]:
        assert classify_record(_raw("costco", path, title, canonical_url=changed_url))["unified_category_id"] != leaf
    assert classify_record(_raw("costco", "커피", title + " + 젤리 세트", canonical_url=url))["unified_category_id"] != leaf


_COLD_NOODLE_PATH = "냉장/냉동/밀키트 > 떡볶이/면류 > 냉면/소바 > 간편냉면&소바"
_BRAISE_PATH = "냉장/냉동/밀키트 > 전/볶음/국탕 > 볶음/찜/국/탕 > 볶음/찜"
_SIMPLE_NOODLE_PATH = "냉장/냉동/밀키트 > 떡볶이/면류 > 국수/칼국수/우동 > 간편국수"
_SEAFOOD_SAUCE_PATH = "수산물/건어물 > 간편/냉동수산물 > 수산간편식 > 소스류"
_BAKING_TOPPING_PATH = "장류/양념/제빵 > 시럽/제빵믹스 > 토핑"


@pytest.mark.parametrize(("title", "path", "leaf"), [
    ("초데리소스 260G", _SEAFOOD_SAUCE_PATH, "food.seasonings.sauces.sushi_vinegar"),
    ("속초식물회소스 500G(팩)", _SEAFOOD_SAUCE_PATH, "food.seasonings.sauces.mulhoe"),
    ("케이퍼 & 홀스래디쉬 소스 60G", _SEAFOOD_SAUCE_PATH, "food.seasonings.sauces.horseradish"),
    ("홀스래디쉬 소스 210G", _SEAFOOD_SAUCE_PATH, "food.seasonings.sauces.horseradish"),
    ("브레드가든스프링클 레인보우 25G", _BAKING_TOPPING_PATH, "food.seasonings.baking.sprinkles"),
    ("브레드가든스프링클 파스텔 미니 하트 25G", _BAKING_TOPPING_PATH, "food.seasonings.baking.sprinkles"),
])
def test_reviewed_sauce_and_sprinkle_forms_require_exact_context(title, path, leaf):
    assert classify_record(_raw("homeplus", path, title))["unified_category_id"] == leaf
    assert classify_record(_raw("homeplus", "다른 선반", title))["unified_category_id"] is None
    assert classify_record(_raw("homeplus", path, title + " + 다른 상품 세트"))["unified_category_id"] is None


@pytest.mark.parametrize(("leaf", "label"), [
    ("food.seasonings.sauces.sushi_vinegar", "초데리소스"),
    ("food.seasonings.sauces.mulhoe", "물회소스"),
    ("food.seasonings.sauces.horseradish", "홀스래디쉬소스"),
    ("food.seasonings.baking.sprinkles", "제과용스프링클"),
])
def test_reviewed_sauce_and_sprinkle_leaves_have_four_levels(leaf, label):
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    assert nodes[leaf]["name_ko"] == label
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {leaf: label}


@pytest.mark.parametrize(("title", "path"), [
    ("오뚜기 카레 순한맛 100G", "라면/즉석식품/통조림 > 카레/짜장 > 카레/짜장/밥양념 > 카레/짜장"),
])
def test_neighboring_unresolved_forms_remain_pending(title, path):
    assert classify_record(_raw("homeplus", path, title))["unified_category_id"] is None


@pytest.mark.parametrize(("title", "path", "leaf"), [
    ("도드람 본래매운맛뼈찜 1KG", _BRAISE_PATH, "food.meals.prepared.meat_braise"),
    ("도드람 본래간장맛뼈찜 1KG", _BRAISE_PATH, "food.meals.prepared.meat_braise"),
    ("홈밀 돼지등뼈 김치찜 1300G", _BRAISE_PATH, "food.meals.prepared.meat_braise"),
    ("씨제이 사천 마라탕면 2인분 434G", _SIMPLE_NOODLE_PATH, "food.meals.noodles.malatang"),
])
def test_reviewed_missing_food_forms_are_exact(title, path, leaf):
    assert classify_record(_raw("homeplus", path, title))["unified_category_id"] == leaf


@pytest.mark.parametrize(("title", "path"), [
    ("도드람 본래매운맛뼈찜 1KG", _SIMPLE_NOODLE_PATH),
    ("씨제이 사천 마라탕면 2인분 434G", _BRAISE_PATH),
    ("도드람 본래매운맛뼈찜 1KG + 김치찌개 1KG", _BRAISE_PATH),
])
def test_reviewed_missing_food_forms_do_not_cover_wrong_context_or_mixed_title(title, path):
    assert classify_record(_raw("homeplus", path, title))["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("오뚜기 생 쫄면 2인분 452G", "food.meals.noodles.jjolmyeon"),
    ("씨제이 동치미 냉면육수 1인 300ML", "food.seasonings.sauces.cold_noodle_broth"),
    ("풀무원 바로조리 생쫄면 2인분 460G", "food.meals.noodles.jjolmyeon"),
    ("칠갑농산 냉면육수(5인분) 1500ML", "food.seasonings.sauces.cold_noodle_broth"),
    ("오뚜기 쫄면 4인분 904G", "food.meals.noodles.jjolmyeon"),
    ("풀무원 저당 생쫄면 2인 460G", "food.meals.noodles.jjolmyeon"),
    ("대상 청정원 동치미 육수 1인분 300G", "food.seasonings.sauces.cold_noodle_broth"),
    ("칠갑농산 냉천골 부드러운 생쫄면 424G", "food.meals.noodles.jjolmyeon"),
])
def test_reviewed_cold_noodle_form_rejects_only_wrong_retail_leaf(title, leaf):
    result = classify_record(_raw("homeplus", _COLD_NOODLE_PATH, title))
    assert result["unified_category_id"] == leaf
    assert result["reviewed_rejected_path_category"] == "food.meals.noodles.naengmyeon"


@pytest.mark.parametrize(("title", "path"), [
    ("오뚜기 생 쫄면 2인분 452G", "냉장/냉동/밀키트 > 떡볶이/면류 > 국수/칼국수/우동 > 간편국수"),
    ("씨제이 동치미 냉면육수 1인 300ML", "냉장/냉동/밀키트 > 떡볶이/면류 > 국수/칼국수/우동 > 간편국수"),
    ("오뚜기 생 쫄면 2인분 452G + 냉면육수 세트", _COLD_NOODLE_PATH),
])
def test_reviewed_cold_noodle_form_does_not_cover_other_context_or_mixed_listing(title, path):
    result = classify_record(_raw("homeplus", path, title))
    assert result["unified_category_id"] is None
    assert result["reviewed_rejected_path_category"] is None


@pytest.mark.parametrize("leaf_id,path", [
    ("household.maintenance.window.screen_material", ("생활용품", "집수리", "방충망용품", "방충망보수·틈새차단재")),
    ("household.maintenance.window.screen_roller", ("생활용품", "집수리", "방충망용품", "방충망작업밀대")),
    ("household.maintenance.drain.strainer", ("생활용품", "집수리", "배수구보수", "배수구방충거름망")),
    ("household.pest_control.traps.sticky", ("생활용품", "해충관리", "해충트랩", "해충끈끈이트랩")),
    ("household.storage.transport.rolling_tote", ("생활용품", "수납·이동", "운반용품", "롤링토트카트")),
    ("household.utilities.batteries.alkaline", ("생활용품", "전기용품", "건전지", "알카라인건전지")),
    ("household.security.storage.safe", ("생활용품", "보안용품", "금고", "가정용금고")),
    ("household.outdoor.bags.cooler_tote", ("생활용품", "야외용품", "보냉용품", "보냉토트백")),
    ("household.maintenance.sealants.silicone", ("생활용품", "집수리", "실란트", "실리콘실란트")),
    ("household.safety.childproofing.outlet_cover", ("생활용품", "안전용품", "유아안전", "콘센트안전커버")),
    ("household.outdoor.cooking.portable_gas_stove", ("생활용품", "야외용품", "휴대조리", "휴대용가스버너")),
    ("household.packaging.cord.binding_twine", ("생활용품", "포장용품", "결속용품", "포장노끈")),
    ("household.workwear.gloves.work", ("생활용품", "작업용품", "작업장갑", "작업용장갑")),
    ("household.maintenance.adhesives.instant", ("생활용품", "집수리", "접착제", "순간접착제")),
    ("baby.toys.construction.set", ("유아동", "완구", "조립완구", "블록조립세트")),
    ("baby.toys.educational.computer", ("유아동", "완구", "교육완구", "학습용컴퓨터")),
    ("baby.toys.figures.character", ("유아동", "완구", "피규어", "캐릭터피규어")),
    ("baby.clothing.underwear.panty", ("유아동", "의류", "속옷", "아동팬티")),
    ("beauty.personal.hand.sanitizer", ("뷰티·개인관리", "개인위생", "손위생", "손소독제")),
    ("baby.feeding.tableware.compartment_tray", ("유아동", "수유·식사", "식기", "칸식판")),
    ("appliances.climate.dehumidifier.electric", ("가전", "계절·환경가전", "제습기", "전기제습기")),
    ("appliances.laundry.washer.standard", ("가전", "세탁가전", "세탁기", "일반세탁기")),
    ("appliances.laundry.combo.integrated", ("가전", "세탁가전", "세탁건조기", "세탁건조일체형")),
    ("appliances.laundry.dryer.standard", ("가전", "세탁가전", "건조기", "의류건조기")),
    ("appliances.laundry.tower.integrated", ("가전", "세탁가전", "워시타워", "세탁건조타워")),
    ("appliances.kitchen.refrigerator.standard", ("가전", "주방가전", "냉장고", "일반냉장고")),
    ("appliances.kitchen.kimchi_refrigerator.standard", ("가전", "주방가전", "김치냉장고", "김치냉장고")),
    ("appliances.kitchen.cooktop.induction", ("가전", "주방가전", "전기레인지", "인덕션")),
    ("appliances.floorcare.vacuum.standard", ("가전", "생활가전", "진공청소기", "진공청소기")),
    ("appliances.floorcare.robot.vacuum", ("가전", "생활가전", "로봇청소기", "로봇진공청소기")),
    ("appliances.wellness.massage.chair", ("가전", "건강가전", "안마기기", "안마의자")),
    ("health.medical.thermal.spine", ("건강·의료", "의료기기", "온열기기", "척추온열의료기기")),
    ("electronics.video.television.standard", ("디지털", "영상가전", "텔레비전", "TV")),
    ("furniture.bedroom.mattress.standard", ("가구·인테리어", "침실가구", "매트리스", "매트리스")),
    ("furniture.bedroom.frame.bed", ("가구·인테리어", "침실가구", "침대프레임", "침대프레임")),
    ("furniture.storage.drawers.chest", ("가구·인테리어", "수납가구", "서랍장", "서랍장")),
    ("furniture.storage.bookcase.rotating", ("가구·인테리어", "수납가구", "책장", "회전책장")),
    ("furniture.storage.wardrobe.built_in", ("가구·인테리어", "수납가구", "옷장", "붙박이장")),
    ("furniture.living.sofa.standard", ("가구·인테리어", "거실가구", "소파", "소파")),
    ("furniture.children.desk.set", ("가구·인테리어", "아동가구", "책상", "책상·의자세트")),
    ("furniture.seating.chair.armchair", ("가구·인테리어", "의자", "일반의자", "암체어")),
    ("furniture.dining.table.standard", ("가구·인테리어", "식당가구", "식탁", "식탁")),
    ("household.bedding.cushion.body", ("생활용품", "침구용품", "쿠션", "바디쿠션")),
    ("household.organization.basket.general", ("생활용품", "수납·정리", "바구니", "수납바구니")),
    ("food.produce.fruit.fig", ("식품", "농산물", "신선과일", "무화과")),
    ("food.meals.prepared.hamburger_steak", ("식품", "간편식·면", "조리식품", "함박스테이크")),
    ("household.utilities.batteries.lithium", ("생활용품", "전기용품", "건전지", "리튬일차전지")),
    ("household.bedding.quilt.summer", ("생활용품", "침구용품", "이불", "여름이불")),
    ("household.bedding.pad.cooling", ("생활용품", "침구용품", "침대패드", "냉감침대패드")),
    ("household.bedding.cover.pillow", ("생활용품", "침구용품", "침구커버", "베개커버")),
    ("household.pest_control.electronic.repeller", ("생활용품", "해충관리", "전자퇴치기", "전자해충퇴치기")),
    ("household.cleaning.tools.lint_roller_refill", ("생활용품", "청소·세탁", "청소도구", "테이프클리너리필")),
    ("household.outdoor.furniture.chair", ("생활용품", "야외용품", "캠핑가구", "캠핑의자")),
    ("beauty.sun.protection.patch", ("뷰티·개인관리", "선케어", "자외선차단", "선패치")),
    ("beauty.foot.care.peeling_mask", ("뷰티·개인관리", "풋케어", "발관리", "발필링마스크")),
    ("beauty.face.skincare.moisturizing_cream", ("뷰티·개인관리", "얼굴관리", "스킨케어", "보습크림")),
    ("beauty.face.skincare.soothing_gel", ("뷰티·개인관리", "얼굴관리", "스킨케어", "수딩젤")),
    ("beauty.face.cleansing.foam", ("뷰티·개인관리", "얼굴관리", "세안용품", "클렌징폼")),
    ("beauty.eye.contact.solution", ("뷰티·개인관리", "눈관리", "콘택트렌즈용품", "렌즈관리용액")),
    ("clothing.adult.tops.tshirt", ("패션", "성인의류", "상의", "반소매티셔츠")),
    ("clothing.children.tops.tshirt", ("패션", "아동의류", "상의", "아동반소매티셔츠")),
    ("clothing.children.outerwear.windbreaker", ("패션", "아동의류", "아우터", "아동바람막이")),
    ("clothing.adult.knit.pullover", ("패션", "성인의류", "니트", "니트풀오버")),
    ("clothing.adult.knit.cardigan", ("패션", "성인의류", "니트", "가디건")),
    ("clothing.adult.bottoms.pants", ("패션", "성인의류", "하의", "긴바지")),
    ("clothing.adult.bottoms.shorts", ("패션", "성인의류", "하의", "반바지")),
    ("clothing.adult.outerwear.down_jacket", ("패션", "성인의류", "아우터", "다운재킷")),
    ("clothing.adult.accessories.arm_sleeves", ("패션", "성인의류", "패션소품", "팔토시")),
    ("clothing.adult.sleepwear.pajama_set", ("패션", "성인의류", "잠옷", "파자마세트")),
    ("clothing.women.underwear.panties", ("패션", "여성의류", "속옷", "여성팬티")),
    ("clothing.women.underwear.bra", ("패션", "여성의류", "속옷", "여성브라")),
    ("clothing.men.underwear.sleeveless", ("패션", "남성의류", "속옷", "남성민소매속옷")),
    ("footwear.adult.court.shoes", ("패션", "신발", "코트화", "성인코트화")),
    ("appliances.kitchen.egg_cooker.electric", ("가전", "주방가전", "계란조리기", "전기계란찜기")),
    ("food.snacks.chestnut.roasted", ("식품", "과자·간식", "밤간식", "구운밤")),
    ("food.meals.prepared.fried_squid", ("식품", "간편식·면", "조리식품", "오징어튀김")),
    ("food.preserved.meat.jangjorim", ("식품", "반찬·저장식품", "육류반찬", "장조림")),
    ("food.preserved.kimchi.stir_fried", ("식품", "반찬·저장식품", "김치", "볶음김치")),
    ("food.produce.prepared.cooked_sweet_potato", ("식품", "농산물", "간편농산물", "조리고구마")),
    ("food.supplements.functional.black_ginseng", ("식품", "건강식품", "건강보조식품", "흑삼")),
    ("food.supplements.functional.evening_primrose", ("식품", "건강식품", "건강보조식품", "달맞이꽃종자유")),
    ("food.supplements.functional.vitamin_d", ("식품", "건강식품", "건강보조식품", "비타민D")),
    ("food.supplements.functional.vitamin_b", ("식품", "건강식품", "건강보조식품", "비타민B")),
    ("food.supplements.functional.chondroitin", ("식품", "건강식품", "건강보조식품", "콘드로이친")),
    ("food.supplements.functional.propolis", ("식품", "건강식품", "건강보조식품", "프로폴리스")),
    ("food.supplements.functional.balanced_drink", ("식품", "건강식품", "건강보조식품", "균형영양음료")),
])
def test_review_only_new_leaves_have_exact_four_level_paths(leaf_id, path):
    leaf = next(item for item in LEAVES if item.id == leaf_id)
    assert leaf.path == path


@pytest.mark.parametrize("path,title,expected", [
    ("문구/취미/도서", "프레일 북엔드", "stationery.office.organizers.bookend"),
    ("문구/취미/도서", "프레일 북엔드 신상품", None),
    ("문구/취미/도서", "프레일 북엔드 + 노트 세트", None),
    ("식품", "프레일 북엔드", None),
    ("스포츠/여행/자동차", "미쉐린_라디우스스탠다드와이퍼350mm", "automotive.maintenance.wipers.standard"),
    ("스포츠/여행/자동차", "미쉐린_F라디우스하이브리드와이퍼350mm", "automotive.maintenance.wipers.hybrid"),
    ("스포츠/여행/자동차", "보쉬 V4 클리어비젼 350mm", None),
    ("패션/언더웨어", "면100% 팬티_미디5매", None),
    ("수산물/건해산", "[냉동] 해물모둠 600g", "food.seafood.assortments.frozen"),
    ("수산물/건해산", "[냉동][베트남] 슈림프링 (453g/팩)", None),
    ("커피/원두/차", "[오설록] 티 에디션 허브 4종 (16입)", "food.drinks.tea.herbal"),
    ("커피/원두/차", "[립톤] 아이스티 복숭아 120X14G", "food.drinks.tea.black"),
])
def test_general_merchandise_review_boundaries(path, title, expected):
    assert classify_record(_raw("emart", path, title))["unified_category_id"] == expected


@pytest.mark.parametrize("path,title", [
    ("가구/인테리어", "방충망 보수테이프"),
    ("디지털/가전/렌탈", "알카라인 건전지 AA"),
    ("유아동/완구", "레고 조립세트"),
    ("헤어/바디/뷰티", "손소독제 겔"),
    ("디지털/가전/렌탈", "일반냉장고 600L"),
    ("디지털/가전/렌탈", "로봇청소기"),
    ("가구/인테리어", "퀸 매트리스"),
    ("가구/인테리어", "4인용 소파"),
    ("베스트", "GAP 무화과 1.2kg"),
    ("베스트", "고메 함박스테이크 152g"),
    ("SpecialPriceOffers", "비타민D 120정"),
    ("SpecialPriceOffers", "여성 가디건"),
    ("SpecialPriceOffers", "클렌징폼 160g"),
    ("SpecialPriceOffers", "여름 이불 퀸"),
])
def test_review_only_new_leaves_do_not_guess_unreviewed_titles(path, title):
    assert classify_record(_raw("emart", path, title))["unified_category_id"] is None


@pytest.mark.parametrize("leaf_id,path,title", [
    ("food.drinks.mix.traditional_tea", ("식품", "음료", "조제음료", "전통차믹스"), "생강차 30T"),
    ("food.seasonings.cooking_herbs.hwanggi", ("식품", "양념·소스", "조리용 건재료", "건황기"), "건황기 100g"),
    ("food.produce.vegetables.aukh", ("식품", "농산물", "신선채소", "아욱"), "아욱 1단"),
    ("food.produce.vegetables.chard", ("식품", "농산물", "신선채소", "근대"), "근대 1단"),
    ("food.produce.vegetables.young_radish", ("식품", "농산물", "신선채소", "열무"), "열무 1단"),
    ("food.produce.vegetables.herbs", ("식품", "농산물", "신선채소", "요리용생허브"), "생허브 30g"),
])
def test_followup_review_only_forms_require_exact_reviewed_context(leaf_id, path, title):
    leaf = next(item for item in LEAVES if item.id == leaf_id)
    assert leaf.path == path
    assert not (leaf.source_labels or leaf.context_labels or leaf.name_terms)
    for candidate in (title, f"{title} + 다른 상품 혼합팩"):
        assert classify_record(_raw("emart", "베스트", candidate))["unified_category_id"] != leaf_id


@pytest.mark.parametrize("leaf_id,path,title", [
    ("food.grains.rice.lentil", ("식품", "곡물·견과", "쌀·잡곡", "렌틸콩"), "렌틸콩 1kg"),
    ("food.frozen.dessert.cup_sherbet", ("식품", "냉동식품", "아이스디저트", "컵샤베트"), "유자 샤베트"),
    ("food.produce.fruit.cherry", ("식품", "농산물", "신선과일", "체리"), "체리 400g"),
    ("food.produce.fruit.pineapple", ("식품", "농산물", "신선과일", "파인애플"), "파인애플 1개"),
    ("food.snacks.assortments.savory", ("식품", "과자·간식", "혼합간식", "혼합짭짤간식"), "스낵믹스"),
    ("food.meals.prepared.chicken_cutlet", ("식품", "간편식·면", "조리식품", "치킨까스"), "치킨까스 360g"),
    ("food.meals.prepared.neobiani", ("식품", "간편식·면", "조리식품", "너비아니"), "너비아니 1kg"),
    ("food.preserved.ingredients.tteokbokki_tteok", ("식품", "반찬·저장식품", "조리재료", "떡볶이떡"), "밀 떡볶이떡"),
    ("food.preserved.ingredients.dumpling_wrapper", ("식품", "반찬·저장식품", "조리재료", "만두피"), "만두피 360g"),
    ("food.preserved.sides.seasoned_perilla", ("식품", "반찬·저장식품", "밑반찬", "양념깻잎"), "매콤 깻잎"),
    ("food.preserved.canned.silkworm_pupae", ("식품", "반찬·저장식품", "통조림", "번데기통조림"), "번데기 130g"),
    ("food.preserved.canned.mackerel", ("식품", "반찬·저장식품", "통조림", "고등어통조림"), "고등어 300g"),
    ("food.bakery.bread.hotteok", ("식품", "베이커리·스프레드", "빵", "호떡"), "꿀호떡 8입"),
    ("food.bakery.spreads.margarine", ("식품", "베이커리·스프레드", "스프레드", "마가린"), "옥수수 마아가린"),
    ("food.drinks.functional.vitamin", ("식품", "음료", "기타음료", "비타민음료"), "비타민 음료"),
    ("food.drinks.functional.hangover_marketed", ("식품", "음료", "기타음료", "숙취해소표방음료"), "숙취음료"),
    ("food.seafood.tunicates.sea_squirt", ("식품", "수산물", "멍게류", "생멍게"), "햇멍게"),
])
def test_followup2_review_only_forms_do_not_match_broad_or_mixed_listings(leaf_id, path, title):
    leaf = next(item for item in LEAVES if item.id == leaf_id)
    assert leaf.path == path
    assert not (leaf.source_labels or leaf.context_labels or leaf.name_terms)
    for candidate in (title, f"{title} + 다른 상품 혼합팩"):
        assert classify_record(_raw("emart", "베스트", candidate))["unified_category_id"] != leaf_id


@pytest.mark.parametrize("leaf_id,path,title", [
    ("food.meals.noodles.japanese_ramen_meal", ("식품", "간편식·면", "면요리", "일본식라멘조리식"), "돈코츠라멘 2인"),
    ("food.snacks.baked.stick", ("식품", "과자·간식", "구운과자", "스틱과자"), "스틱과자 45g"),
    ("food.seafood.fish.sea_bream", ("식품", "수산물", "생선", "생도미"), "생물도미 1마리"),
    ("food.seafood.processed.blanched_octopus", ("식품", "수산물", "수산가공품", "데친문어"), "데친문어 100g"),
    ("food.seasonings.stock.stock_seasoning", ("식품", "양념·소스", "조미료", "육수조미료"), "해물다시다 120g"),
    ("food.produce.leafy.minari", ("식품", "농산물", "잎채소", "미나리"), "미나리 1봉"),
    ("food.produce.leafy.radish_sprouts", ("식품", "농산물", "잎채소", "무순"), "무순 1팩"),
    ("food.produce.vegetables.celery", ("식품", "농산물", "신선채소", "셀러리"), "셀러리 1봉"),
    ("food.produce.vegetables.ginger", ("식품", "농산물", "신선채소", "생강"), "생강 150g"),
    ("food.produce.vegetables.small_green_onion", ("식품", "농산물", "신선채소", "쪽파"), "쪽파 1봉"),
    ("food.produce.vegetables.corn", ("식품", "농산물", "신선채소", "옥수수"), "옥수수 2입"),
])
def test_next3_review_only_forms_require_specific_review(leaf_id, path, title):
    leaf = next(item for item in LEAVES if item.id == leaf_id)
    assert leaf.path == path
    assert not (leaf.source_labels or leaf.context_labels or leaf.name_terms)
    for candidate in (title, f"{title} + 다른 상품 혼합팩"):
        assert classify_record(_raw("emart", "베스트", candidate))["unified_category_id"] != leaf_id


@pytest.mark.parametrize('title,entry', CLEANING_URL_ENTRIES.items())
def test_additional_costco_cleaning_forms_require_exact_official_url(title, entry):
    leaf, marker = entry
    evidence = {'mart': 'costco', 'source_path_parts': ['세제'], 'source_title': title}
    assert reviewed_costco_cleaning_leaf(evidence) is None
    assert reviewed_costco_cleaning_leaf({**evidence, 'source_urls': ['https://example.com' + marker]}) is None
    url = 'https://www.costco.co.kr/HomeKitchen/Cleaning-Products' + marker + 'p/1'
    assert classify_record(_raw('costco', '세제', title, canonical_url=url))['unified_category_id'] == leaf


@pytest.mark.parametrize('title', [
    '프로쉬 세탁세제 선물세트',
    '넬리 소다세제 1.5kg + 울드라이어볼x 4',
    '파워브라이트캡슐세제 180개x 120',
    '슈가버블베이킹소다 2kg x 3 + 500g 용기',
    '네일메드코세정제콤보(용기3개+세정용분말250포)',
    '무아스 소프트 버블 & 젤 자동 디스펜서 2P',
])
def test_costco_cleaning_audit_keeps_mixed_bulk_medical_and_appliance_rows_pending(title):
    assert classify_record(_raw('costco', '세제', title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('세제', title))


from services.initial_audited_seasonings import EMART_TITLES, reviewed_seasoning_leaf
from services.initial_audited_lotte_nuts import TITLES as LOTTE_NUT_TITLES, reviewed_lotte_nut_leaf
from services.initial_audited_costco_fruit_forms import TITLES as COSTCO_FRUIT_FORM_TITLES, reviewed_costco_fruit_form_leaf
from services.initial_audited_costco_rice_forms import TITLES as COSTCO_RICE_FORM_TITLES, reviewed_costco_rice_form_leaf
from services.initial_audited_emart_snacks import TITLES as EMART_SNACK_TITLES, reviewed_emart_snack_leaf
from services.initial_audited_emart_bakery import TITLES as EMART_BAKERY_TITLES, reviewed_emart_bakery_leaf
from services.initial_audited_emart_noodles_canned import TITLES as EMART_NOODLES_CANNED_TITLES, reviewed_emart_noodles_canned_leaf
from services.initial_audited_emart_seafood import TITLES as EMART_SEAFOOD_TITLES, reviewed_emart_seafood_leaf
from services.initial_audited_emart_meat_eggs import TITLES as EMART_MEAT_EGG_TITLES, reviewed_emart_meat_egg_leaf
from services.initial_audited_lotte_vegetables import TITLES as LOTTE_VEGETABLE_TITLES, reviewed_lotte_vegetable_leaf
from services.initial_audited_lotte_general_snacks import PATH as LOTTE_GENERAL_SNACK_PATH, TITLES as LOTTE_GENERAL_SNACK_TITLES, reviewed_lotte_general_snack_leaf
from services.initial_audited_costco_egg_meat import TITLES as EGG_MEAT_TITLES, URL_BEEF_TITLES, reviewed_costco_egg_meat_leaf
from services.initial_audited_costco_kimchi_forms import TITLES as KIMCHI_FORM_TITLES, reviewed_costco_kimchi_form_leaf
from services.initial_audited_costco_beverages import TITLES as COSTCO_BEVERAGE_TITLES, reviewed_costco_beverage_leaf
from services.initial_audited_costco_coffee_forms import TITLES as COSTCO_COFFEE_TITLES, BEAN_TITLES, URL_ENTRIES as COSTCO_COFFEE_URL_ENTRIES, reviewed_costco_coffee_form_leaf
from services.initial_audited_costco_snack_forms import ENTRIES as COSTCO_SNACK_ENTRIES, reviewed_costco_snack_form_leaf
from services.initial_audited_emart_dairy import TITLES as EMART_DAIRY_TITLES, reviewed_emart_dairy_leaf
from services.initial_audited_emart_coffee_tea import TITLES as EMART_COFFEE_TEA_TITLES, reviewed_emart_coffee_tea_leaf
from services.initial_audited_costco_meat_contaminants import ENTRIES as COSTCO_MEAT_CONTAMINANTS, reviewed_costco_meat_contaminant_leaf
from services.initial_audited_emart_organic import TITLES as EMART_ORGANIC_TITLES, reviewed_emart_organic_leaf
from services.initial_audited_emart_meals import TITLES as EMART_MEAL_TITLES, reviewed_emart_meal_leaf
from services.initial_audited_emart_health import TITLES as EMART_HEALTH_TITLES, reviewed_emart_health_leaf
from services.initial_audited_homeplus_flavored_powders import PATH as HOMEPLUS_FLAVORED_PATH, TITLES as HOMEPLUS_FLAVORED_TITLES, reviewed_homeplus_flavored_powder_leaf
from services.initial_audited_emart_pet import TITLES as EMART_PET_TITLES, reviewed_emart_pet_leaf
from services.initial_audited_emart_grains import TITLES as EMART_GRAIN_TITLES, reviewed_emart_grain_leaf


@pytest.mark.parametrize('title,leaf',EMART_DAIRY_TITLES.items())
def test_emart_broad_dairy_shelf_uses_exact_product_form(title,leaf):
    result=classify_record(_raw('emart','우유/유제품',title))
    assert result['unified_category_id']==leaf
    evidence={'mart':'emart','source_path_parts':['우유/유제품'],'source_title':title}
    assert reviewed_emart_dairy_leaf({**evidence,'mart':'homeplus'}) is None
    assert reviewed_emart_dairy_leaf({**evidence,'source_path_parts':['과자']}) is None
    assert reviewed_emart_dairy_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['1000ml 나100%','(200ml*3개)','인기 치즈/버터 모음전, 최대 ~50% 행사'])
def test_emart_dairy_audit_does_not_guess_size_only_or_promotion_titles(title):
    assert classify_record(_raw('emart','우유/유제품',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf', EMART_COFFEE_TEA_TITLES.items())
def test_emart_coffee_tea_shelf_uses_exact_product_form(title, leaf):
    result = classify_record(_raw('emart', '커피/원두/차', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['커피/원두/차'], 'source_title': title}
    assert reviewed_emart_coffee_tea_leaf({**evidence, 'mart': 'costco'}) is None
    assert reviewed_emart_coffee_tea_leaf({**evidence, 'source_path_parts': ['생활용품']}) is None
    assert reviewed_emart_coffee_tea_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', [
    '티 에디션 아일랜드 6종 (18입)',
    '러블리 티박스 4종 (12입)',
    '트루 레몬즙 14입',
    '오리지널 리필 170g',
])
def test_emart_coffee_tea_audit_keeps_mixed_corrupt_or_opaque_forms_pending(title):
    assert classify_record(_raw('emart', '커피/원두/차', title))['unified_category_id'] is None


@pytest.mark.parametrize('title,entry', COSTCO_MEAT_CONTAMINANTS.items())
def test_costco_meat_shelf_contaminants_need_exact_official_url(title, entry):
    leaf, marker = entry
    evidence = {'mart': 'costco', 'source_path_parts': ['고기'], 'source_title': title}
    assert reviewed_costco_meat_contaminant_leaf(evidence) is None
    assert reviewed_costco_meat_contaminant_leaf({**evidence, 'source_urls': ['https://example.com' + marker]}) is None
    url = 'https://www.costco.co.kr/Foods' + marker + 'p/1'
    assert reviewed_costco_meat_contaminant_leaf({**evidence, 'source_urls': [url]}) == leaf
    assert classify_record(_raw('costco', '고기', title, canonical_url=url))['unified_category_id'] == leaf


@pytest.mark.parametrize('title', [
    '안방그릴 울트라 AB1107CO',
    '파이어폭스 BBQ 석쇠 5개입 / 최소구매 2',
    '궁한우나주식곰탕500gx3 +소스+ 갈비찜1kgx2 +당면',
    '부추고기순대500Gx3 족발슬라이스 960g',
    '마이셰프X EBS 산더미소고기콩불830g x 2',
])
def test_costco_meat_shelf_does_not_guess_grills_or_mixed_food_sets(title):
    assert classify_record(_raw('costco', '고기', title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('고기', title))


@pytest.mark.parametrize('title,leaf', EMART_ORGANIC_TITLES.items())
def test_emart_organic_shelf_uses_exact_leaf_level_form(title, leaf):
    result = classify_record(_raw('emart', '친환경/유기농', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['친환경/유기농'], 'source_title': title}
    assert reviewed_emart_organic_leaf({**evidence, 'mart': 'costco'}) is None
    assert reviewed_emart_organic_leaf({**evidence, 'source_path_parts': ['생활용품']}) is None
    assert reviewed_emart_organic_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', ['친환경 인기상품 모음전', '유기농 500g', '유기농 우유와 요거트 혼합세트', '유기농 요구르트 500ml (100mlx5)'])
def test_emart_organic_shelf_does_not_guess_promotions_size_only_or_mixed_forms(title):
    assert classify_record(_raw('emart', '친환경/유기농', title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf', EMART_MEAL_TITLES.items())
def test_emart_meal_shelf_uses_exact_product_form(title, leaf):
    result = classify_record(_raw('emart', '밀키트/간편식', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['밀키트/간편식'], 'source_title': title}
    assert reviewed_emart_meal_leaf({**evidence, 'mart': 'homeplus'}) is None
    assert reviewed_emart_meal_leaf({**evidence, 'source_path_parts': ['생활용품']}) is None
    assert reviewed_emart_meal_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', ['딱 한끼(순한맛) 308g', '간편식 모음 최대 30%'])
def test_emart_meal_shelf_keeps_mixed_opaque_and_promotion_rows_pending(title):
    assert classify_record(_raw('emart', '밀키트/간편식', title))['unified_category_id'] is None


@pytest.mark.parametrize('shelf,title,leaf', [
    ('밀키트/간편식', '우엉절임과 김밥단무지 220g', 'food.preserved.sides.pickled'),
    ('쌀/잡곡/견과', '유기농 단백질 블랙미숫가루 400g (20gx20입)', 'food.drinks.powders.grain'),
])
def test_residual_reviewed_food_titles_require_exact_context(shelf, title, leaf):
    row = _raw('emart', shelf, title)
    assert classify_record(row)['unified_category_id'] == leaf
    assert classify_record(_raw('emart', '베스트', title))['unified_category_id'] != leaf
    assert classify_record(_raw('emart', shelf, title + ' 혼합세트'))['unified_category_id'] != leaf


@pytest.mark.parametrize('title,leaf', [
    (title, 'food.supplements.sets.red_ginseng_bag'
     if title == '6년근홍삼정업 2개입세트 (240g*2병) (쇼핑백동봉)' else leaf)
    for title, leaf in EMART_HEALTH_TITLES.items()
])
def test_emart_health_shelf_uses_exact_product_form(title, leaf):
    result = classify_record(_raw('emart', '건강식품', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['건강식품'], 'source_title': title}
    assert reviewed_emart_health_leaf({**evidence, 'mart': 'costco'}) is None
    assert reviewed_emart_health_leaf({**evidence, 'source_path_parts': ['화장품']}) is None
    assert reviewed_emart_health_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', ['서울우유 한끼식사 구수한 맛 190ml*18입', '건강식품 베스트 모음', '비타민과 화장품 혼합세트'])
def test_emart_health_shelf_keeps_opaque_promotion_and_mixed_rows_pending(title):
    assert classify_record(_raw('emart', '건강식품', title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf', HOMEPLUS_FLAVORED_TITLES.items())
def test_homeplus_misc_flavored_powder_uses_exact_form(title, leaf):
    result = classify_record({'source_name': 'homeplus', 'source_title': title, 'source_category_path': list(HOMEPLUS_FLAVORED_PATH)})
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'homeplus', 'source_path_parts': list(HOMEPLUS_FLAVORED_PATH), 'source_title': title}
    assert reviewed_homeplus_flavored_powder_leaf({**evidence, 'mart': 'emart'}) is None
    assert reviewed_homeplus_flavored_powder_leaf({**evidence, 'source_path_parts': ['커피/차']}) is None
    assert reviewed_homeplus_flavored_powder_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


def test_reviewed_homeplus_vinegar_mix_requires_exact_source_context():
    row = {'source_name': 'homeplus', 'source_title': '티젠 애플사이다비니거 사과&배 30T(150G)', 'source_category_path': list(HOMEPLUS_FLAVORED_PATH)}
    assert classify_record(row)['unified_category_id'] == 'food.drinks.mix.vinegar'
    assert classify_record({**row, 'source_category_path': ['커피/차']})['unified_category_id'] is None
    assert classify_record({**row, 'source_title': row['source_title'] + ' 혼합세트'})['unified_category_id'] is None


@pytest.mark.parametrize('title', ['가향분말 베스트 모음', '콤부차와 단백질 혼합세트'])
def test_homeplus_misc_flavored_powder_keeps_vinegar_opaque_and_mixed_rows_pending(title):
    row = {'source_name': 'homeplus', 'source_title': title, 'source_category_path': list(HOMEPLUS_FLAVORED_PATH)}
    assert classify_record(row)['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf', EMART_PET_TITLES.items())
def test_emart_pet_shelf_uses_exact_animal_and_product_form(title, leaf):
    result = classify_record(_raw('emart', '반려동물', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['반려동물'], 'source_title': title}
    assert reviewed_emart_pet_leaf({**evidence, 'mart': 'costco'}) is None
    assert reviewed_emart_pet_leaf({**evidence, 'source_path_parts': ['과자']}) is None
    assert reviewed_emart_pet_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', [
    '해피밀 황태와 소고기 1.2kg', '몰리스 프로발란스 어덜트 8kg',
    '몰리스 미니캔 닭가슴살과연어 6개입', '더리얼 오븐베이크드 소고기 어덜트 1kg', '클래식 5kg',
])
def test_emart_pet_shelf_keeps_unknown_animal_or_opaque_forms_pending(title):
    assert classify_record(_raw('emart', '반려동물', title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf', EMART_GRAIN_TITLES.items())
def test_emart_grain_shelf_uses_exact_product_form(title, leaf):
    result = classify_record(_raw('emart', '쌀/잡곡/견과', title))
    assert result['unified_category_id'] == leaf
    evidence = {'mart': 'emart', 'source_path_parts': ['쌀/잡곡/견과'], 'source_title': title}
    assert reviewed_emart_grain_leaf({**evidence, 'mart': 'lotte'}) is None
    assert reviewed_emart_grain_leaf({**evidence, 'source_path_parts': ['과자']}) is None
    assert reviewed_emart_grain_leaf({**evidence, 'source_title': title + ' 혼합세트'}) is None


@pytest.mark.parametrize('title', ['씻거나 불릴필요 없는 맛있는 우리 엄마 밥상 2kg', '쌀과 견과 혼합선물세트', '잡곡 베스트 모음'])
def test_emart_grain_shelf_keeps_opaque_bundle_and_promotion_rows_pending(title):
    assert classify_record(_raw('emart', '쌀/잡곡/견과', title))['unified_category_id'] is None


@pytest.mark.parametrize('title,entry',COSTCO_SNACK_ENTRIES.items())
def test_costco_snack_unusual_forms_require_official_product_url(title,entry):
    leaf,marker=entry
    evidence={'mart':'costco','source_path_parts':['과자'],'source_title':title}
    assert reviewed_costco_snack_form_leaf(evidence) is None
    assert reviewed_costco_snack_form_leaf({**evidence,'source_urls':['https://example.com/'+marker]}) is None
    url='https://www.costco.co.kr/Foods/Snack/'+marker+'item/p/1'
    assert reviewed_costco_snack_form_leaf({**evidence,'source_urls':[url]})==leaf
    # The legacy URL review remains evidence; a proved literal physical form
    # may refine its old broad biscuit leaf without weakening URL validation.
    expected = ('food.snacks.baked.crispy_roll' if '크리스피 코코넛롤' in title else
                'food.snacks.sweets.marshmallow' if '마시멜로우' in title else
                'food.snacks.traditional.monaka' if '모나카' in title else leaf)
    assert classify_record(_raw('costco','과자',title,canonical_url=url))['unified_category_id']==expected


@pytest.mark.parametrize('title',['산리오 캐릭터즈 디저트 휘핑 데코 놀이 세트','락앤락 휴대용 과일 & 요거트 보틀 600ml x 2P','카스 초음파 야채 과일 세척기 4L','프리미엄 제철과일 선물세트 5.5KG 이상','말랑말랑꿀오랑오리지날480g (16g x 10 x 3pk)','말랑말랑꿀오랑780g (26g x 10 x 3pk)'])
def test_costco_snack_url_audit_does_not_accept_pet_food_kits_or_tools(title):
    assert classify_record(_raw('costco','과자',title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('과자', title))


@pytest.mark.parametrize('title,leaf',COSTCO_COFFEE_TITLES.items())
def test_costco_coffee_shelf_explicit_food_forms_are_separate(title,leaf):
    result=classify_record(_raw('costco','커피',title))
    assert result['unified_category_id']==leaf
    evidence={'mart':'costco','source_path_parts':['커피'],'source_title':title}
    assert reviewed_costco_coffee_form_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_costco_coffee_form_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_costco_coffee_form_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',sorted(BEAN_TITLES))
def test_costco_blend_requires_official_bean_or_ground_coffee_url(title):
    evidence={'mart':'costco','source_path_parts':['커피'],'source_title':title}
    assert reviewed_costco_coffee_form_leaf(evidence) is None
    assert reviewed_costco_coffee_form_leaf({**evidence,'source_urls':['https://example.com/Whole-BeansGround-Coffee/x']}) is None
    result=classify_record(_raw('costco','커피',title,canonical_url='https://www.costco.co.kr/Foods/CoffeeTeaDrink/Whole-BeansGround-Coffee/item/p/1'))
    assert result['unified_category_id']=='food.drinks.coffee.beans'


@pytest.mark.parametrize('title,entry', COSTCO_COFFEE_URL_ENTRIES.items())
def test_costco_additional_coffee_food_requires_exact_official_url(title, entry):
    leaf, marker = entry
    evidence = {'mart': 'costco', 'source_path_parts': ['커피'], 'source_title': title}
    assert reviewed_costco_coffee_form_leaf(evidence) is None
    assert reviewed_costco_coffee_form_leaf({**evidence, 'source_urls': ['https://example.com' + marker]}) is None
    url = 'https://www.costco.co.kr/Foods' + marker + 'p/1'
    assert classify_record(_raw('costco', '커피', title, canonical_url=url))['unified_category_id'] == leaf


@pytest.mark.parametrize('title', [
    '스타벅스 아메리카노 & 드립백커피 선물세트',
    '폴바셋 x 오덴세 홈카페 선물세트',
    '드쉘 네스프레소호환캡슐머신 클리닝캡슐30EA(10EAx3PK)',
])
def test_costco_coffee_shelf_keeps_mixed_gifts_and_cleaner_pending(title):
    expected = 'household.cleaning.appliance.coffee_cleaning_capsule' if title == '드쉘 네스프레소호환캡슐머신 클리닝캡슐30EA(10EAx3PK)' else None
    assert classify_record(_raw('costco', '커피', title))['unified_category_id'] == expected


@pytest.mark.parametrize('title,leaf',COSTCO_BEVERAGE_TITLES.items())
def test_costco_beverage_shelf_uses_explicit_drink_or_frozen_form(title,leaf):
    result=classify_record(_raw('costco','음료',title))
    refined = {'델몬트 스퀴즈 사과/오렌지 에이드 240ml x 30 x 2팩': 'food.drinks.juice.fruit_ade',
               '리퀴드 아이비 전해질드링크 파우더 믹스 16g x 30': 'food.drinks.powders.electrolyte'}
    assert result['unified_category_id']==refined.get(title, leaf)
    assert result['evidence_type']==('literal_beverage_preparation_form_and_context' if title in refined else 'reviewed_source_shelf_and_form')
    evidence={'mart':'costco','source_path_parts':['음료'],'source_title':title}
    assert reviewed_costco_beverage_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_costco_beverage_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_costco_beverage_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['뉴케어 당플랜 플러스 200ml X 24개입','정관장 활기력 20ml x 16병','끌레드벨 럭셔리 콜라겐 82 앰플 100ml x 2','벤딕트 차량용 보냉 컵홀더 2개','스타벅스피지오쿨라임400ml x 6 + 피치딸기 400ml x 6'])
def test_costco_beverage_audit_does_not_guess_supplement_cosmetic_tool_or_mixed_pack(title):
    expected = ('household.vehicle.accessories.cup_holder' if title == '벤딕트 차량용 보냉 컵홀더 2개'
                else 'food.drinks.assortments.combo' if title.startswith('스타벅스피지오') else None)
    assert classify_record(_raw('costco','음료',title))['unified_category_id'] == expected
    if expected == 'food.drinks.assortments.combo':
        from core.catalog_quantity import normalize_catalog_package
        assert normalize_catalog_package({'pack_qty': 400, 'pack_unit': 'ml'}, {}, title)[1]


def test_costco_polaretti_needs_its_official_frozen_ice_bar_url():
    title='폴라레티 후르트 아이스바 40ml x 80'
    assert classify_record(_raw('costco','음료',title))['unified_category_id'] is None
    url='https://www.costco.co.kr/Foods/Frozen-Foods/BeverageIce-Cream/Polaretti-Fruit-Ice-Bar-40ml-x-80/p/669975'
    assert classify_record(_raw('costco','음료',title,canonical_url=url))['unified_category_id']=='food.frozen.dessert.ice_bar'


@pytest.mark.parametrize('title,leaf',KIMCHI_FORM_TITLES.items())
def test_costco_kimchi_shelf_declared_forms_do_not_become_kimchi_by_shelf(title,leaf):
    result=classify_record(_raw('costco','김치',title))
    assert result['unified_category_id']==leaf
    assert result['evidence_type']=='reviewed_source_shelf_and_form'
    evidence={'mart':'costco','source_path_parts':['김치'],'source_title':title}
    assert reviewed_costco_kimchi_form_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_costco_kimchi_form_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_costco_kimchi_form_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['종가 포기김치1kg x 2열무김치900g x 1혼합팩','종가 김치공방 보쌈김치 1kg + 겉절이 1kg','LG 디오스 김치톡톡 217L- 메탈 린넨화이트','아워홈 갈치김치 800 g x 4','농협선장김치5kg x 2'])
def test_costco_kimchi_audit_does_not_guess_mixed_unknown_types_or_appliances(title):
    assert classify_record(_raw('costco','김치',title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('김치', title))


@pytest.mark.parametrize('title,leaf',{
    **EGG_MEAT_TITLES,
    '국내산 냉동 돈육 한입 삼겹살 (1.0kg x 2)': 'food.meat.frozen.pork',
}.items())
def test_costco_egg_shelf_declared_species_and_seasoning_are_separate(title,leaf):
    result=classify_record(_raw('costco','계란',title))
    assert result['unified_category_id']==leaf
    evidence={'mart':'costco','source_path_parts':['계란'],'source_title':title}
    assert reviewed_costco_egg_meat_leaf({**evidence,'mart':'homeplus'}) is None
    assert reviewed_costco_egg_meat_leaf({**evidence,'source_path_parts':['가구']}) is None
    assert reviewed_costco_egg_meat_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',sorted(URL_BEEF_TITLES))
def test_ambiguous_costco_cut_requires_independent_beef_product_url(title):
    evidence={'mart':'costco','source_path_parts':['계란'],'source_title':title}
    assert reviewed_costco_egg_meat_leaf(evidence) is None
    for url in ['https://www.costco.co.kr/Foods/AU-Pork-500g/p/1','https://example.com/AU-Beef/p/1','https://www.costco.co.kr/Foods/Cut/p/1?beef=1']:
        assert reviewed_costco_egg_meat_leaf({**evidence,'source_urls':[url]}) is None
    url='https://www.costco.co.kr/Foods/MeatEggs/AU-Fresh-Beef-500g/p/1'
    assert reviewed_costco_egg_meat_leaf({**evidence,'source_urls':[url]})=='food.meat.fresh.beef'
    result=classify_record(_raw('costco','계란',title,canonical_url=url))
    assert result['unified_category_id']=={
        '미국산 냉동 차돌박이 1.3kg x 2팩': 'food.meat.frozen.beef',
        '미국산 냉동 척아이롤 1.5kg x 2팩': 'food.meat.frozen.beef',
    }.get(title, 'food.meat.fresh.beef')


@pytest.mark.parametrize('title',['포크밸리 삼겹 1kg +칼집삼겹 1kg +목심 1kg (로스용)','국내산냉동돈육한입삼겹살1.0kg +등심돈가스1.0kg'])
def test_costco_egg_meat_audit_does_not_accept_tools_or_mixed_cuts(title):
    assert classify_record(_raw('costco','계란',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',EMART_SNACK_TITLES.items())
def test_emart_snack_shelf_only_readable_product_forms_are_classified(title,leaf):
    result=classify_record(_raw('emart','과자/간식',title))
    expected = 'food.snacks.chewy.rice_cake_pie' if '찰떡파이' in title else leaf
    expected = {'라면스낵 250g':'food.snacks.savory.noodle',
                '도도한나쵸 155g':'food.snacks.savory.tortilla_nacho',
                '출출할때 먹는 간식소시지 300g':'food.snacks.savory.snack_sausage'}.get(title, expected)
    assert result['unified_category_id']==expected
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['과자/간식'],'source_title':title}
    assert reviewed_emart_snack_leaf({**evidence,'mart':'homeplus'}) is None
    assert reviewed_emart_snack_leaf({**evidence,'source_path_parts':['생활용품']}) is None
    assert reviewed_emart_snack_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['비쵸비 125g','왕고래밥 56g','롯데 빈츠 204g','롯데 몽쉘 오리지널 12입 408G','고소미 216g','코코넛로쉐 238 g','초코베어 300g','스니커즈 아몬드 펀사이즈 500g','옥수수로 만든 밀크롤 35g','롯데 마가렛트구운모카352g'])
def test_emart_snack_audit_does_not_guess_opaque_brands_or_roll_form(title):
    assert classify_record(_raw('emart','과자/간식',title))['unified_category_id'] is None


@pytest.mark.parametrize('title',['포카칩 소금 66g','참쌀선과 253g','참붕어빵 8입 232g(패키지 랜덤 발송)','X복순도가 쌀젤라또 474ml'])
def test_emart_snack_audit_rejects_mixed_package_and_wrong_context_mutations(title):
    evidence={'mart':'emart','source_path_parts':['과자/간식'],'source_title':title}
    assert reviewed_emart_snack_leaf({**evidence,'mart':'lotte'}) is None
    assert reviewed_emart_snack_leaf({**evidence,'source_path_parts':['생활용품']}) is None
    assert reviewed_emart_snack_leaf({**evidence,'source_title':title+' 혼합박스'}) is None


@pytest.mark.parametrize('title,leaf',EMART_BAKERY_TITLES.items())
def test_emart_bakery_audit_classifies_only_exact_single_product_forms(title,leaf):
    result=classify_record(_raw('emart','베이커리/잼',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['베이커리/잼'],'source_title':title}
    assert reviewed_emart_bakery_leaf({**evidence,'mart':'homeplus'}) is None
    assert reviewed_emart_bakery_leaf({**evidence,'source_path_parts':['과자/간식']}) is None
    assert reviewed_emart_bakery_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['8월 베이커리 최대 50% 특가','식사빵 & 간식빵 최대 50% 특가전','찹쌀깨찰빵 4입'])
def test_emart_bakery_audit_keeps_promotions_mixed_packages_and_unclear_forms_pending(title):
    expected = 'food.bakery.bread.glutinous_rice' if title == '찹쌀깨찰빵 4입' else None
    assert classify_record(_raw('emart','베이커리/잼',title))['unified_category_id'] == expected


@pytest.mark.parametrize('title,leaf',EMART_NOODLES_CANNED_TITLES.items())
def test_emart_noodles_canned_audit_uses_only_exact_declared_food_forms(title,leaf):
    result=classify_record(_raw('emart','면류/통조림',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['면류/통조림'],'source_title':title}
    assert reviewed_emart_noodles_canned_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_emart_noodles_canned_leaf({**evidence,'source_path_parts':['베이커리/잼']}) is None
    assert reviewed_emart_noodles_canned_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['삼양 1963 우지 파개장 115g','면류/통조림 최대 30% 할인','라면과 통조림 혼합세트'])
def test_emart_noodles_canned_audit_keeps_opaque_promotions_and_mixed_sets_pending(title):
    assert classify_record(_raw('emart','면류/통조림',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',EMART_SEAFOOD_TITLES.items())
def test_emart_seafood_audit_classifies_exact_single_seafood_forms(title,leaf):
    result=classify_record(_raw('emart','수산물/건해산',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['수산물/건해산'],'source_title':title}
    assert reviewed_emart_seafood_leaf({**evidence,'mart':'homeplus'}) is None
    assert reviewed_emart_seafood_leaf({**evidence,'source_path_parts':['면류/통조림']}) is None
    assert reviewed_emart_seafood_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


# Explicit frozen assortments now have their own reviewed leaf; opaque prepared
# foods and marketing events still lack sufficient product-form evidence.
@pytest.mark.parametrize('title',['싱싱 생선회&조개류 ~50%할인','[냉동][베트남] 슈림프링 (453g/팩)','볶음/국물용 멸치 ~40% 할인'])
def test_emart_seafood_audit_keeps_promotions_mixed_and_unclear_preparations_pending(title):
    assert classify_record(_raw('emart','수산물/건해산',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',EMART_MEAT_EGG_TITLES.items())
def test_emart_meat_egg_audit_classifies_only_exact_species_declared_forms(title,leaf):
    result=classify_record(_raw('emart','정육/계란류',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['정육/계란류'],'source_title':title}
    assert reviewed_emart_meat_egg_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_emart_meat_egg_leaf({**evidence,'source_path_parts':['수산물/건해산']}) is None
    assert reviewed_emart_meat_egg_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title,leaf',[
    ('국내산 앞다리 불고기용 (100g)',None),
    ('국내산 등심 카레용 (100g) (팩)',None),
    ('국내산 냉장 갈비 찜용 (100g)',None),
    ('[더느림+] 무항생제 목심 (100g)',None),
    ('닭다리살/닭가슴살 등 ~20%',None),
    ('냉동 삼겹살/목심 할인행사','food.meat.frozen.pork'),
])
def test_emart_meat_egg_audit_separates_declared_frozen_pork_from_unclear_forms(title,leaf):
    assert classify_record(_raw('emart','정육/계란류',title))['unified_category_id']==leaf


@pytest.mark.parametrize('title,leaf',LOTTE_VEGETABLE_TITLES.items())
def test_lotte_vegetable_audit_separates_exact_produce_tofu_and_sprouts(title,leaf):
    result=classify_record(_raw('lottemart','채소',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'lottemart','source_path_parts':['채소'],'source_title':title}
    assert reviewed_lotte_vegetable_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_lotte_vegetable_leaf({**evidence,'source_path_parts':['과자']}) is None
    assert reviewed_lotte_vegetable_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['채소 최대 30% 할인','콩나물과 두부 혼합세트','오늘좋은 신선상품'])
def test_lotte_vegetable_audit_rejects_promotions_mixed_sets_and_opaque_names(title):
    assert classify_record(_raw('lottemart','채소',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',LOTTE_GENERAL_SNACK_TITLES.items())
def test_lotte_general_snack_audit_classifies_exact_declared_chip_forms(title,leaf):
    path=' > '.join(LOTTE_GENERAL_SNACK_PATH)
    result=classify_record(_raw('lottemart',path,title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'lottemart','source_path_parts':list(LOTTE_GENERAL_SNACK_PATH),'source_title':title}
    assert reviewed_lotte_general_snack_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_lotte_general_snack_leaf({**evidence,'source_path_parts':['채소']}) is None
    assert reviewed_lotte_general_snack_leaf({**evidence,'source_title':title+' 혼합박스'}) is None


@pytest.mark.parametrize('title',['오리온 왕 고래밥 (56G)','오리온 꼬북칩초코츄러스 (64G)','오늘좋은 땅콩 오징어볼 (200G)','농심 바삭츄리 고튀 (90G)','농심 망고킥 (100G)','오늘좋은 오징어해씨볼 (200G)','일반과자 최대 30% 할인'])
def test_lotte_general_snack_audit_keeps_opaque_mixed_and_promotion_rows_pending(title):
    assert classify_record(_raw('lottemart',' > '.join(LOTTE_GENERAL_SNACK_PATH),title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',COSTCO_RICE_FORM_TITLES.items())
def test_costco_rice_shelf_declared_grains_and_prepared_food_are_separate(title,leaf):
    result=classify_record(_raw('costco','쌀',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'costco','source_path_parts':['쌀'],'source_title':title}
    assert reviewed_costco_rice_form_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_costco_rice_form_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_costco_rice_form_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['세계인의 건강곡물 선물세트 1.54kg x 10세트','세계인의 건강 곡물 선물세트 1.54kg','대구농산 쌀가루 2.5kg'])
def test_costco_rice_form_audit_does_not_guess_opaque_or_mixed_goods(title):
    assert classify_record(_raw('costco','쌀',title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('쌀', title))


@pytest.mark.parametrize('title,leaf',COSTCO_FRUIT_FORM_TITLES.items())
def test_costco_fruit_shelf_processed_forms_are_not_fresh_fruit(title,leaf):
    result=classify_record(_raw('costco','과일',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'costco','source_path_parts':['과일'],'source_title':title}
    assert reviewed_costco_fruit_form_leaf({**evidence,'mart':'emart'}) is None
    assert reviewed_costco_fruit_form_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_costco_fruit_form_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['샤인머스캣 애플망고 사과 혼합선물세트4.6kg','애플망고 골드키위세트','허니듀 & 머스크 멜론 세트 4입 (각 2입)','휴롬 원액기 P310 E31ST-BFM02MM','Tropical Maria 망고청크2.27kg X 200개'])
def test_costco_fruit_form_audit_does_not_guess_mixed_fresh_or_frozen_form(title):
    assert classify_record(_raw('costco','과일',title))['unified_category_id'] == _REVIEWED_LEDGER001.get(('과일', title))


@pytest.mark.parametrize('title,leaf',LOTTE_NUT_TITLES.items())
def test_lotte_nuts_and_chips_are_not_assumed_raw_grains(title,leaf):
    result=classify_record(_raw('lottemart','쌀ㆍ잡곡ㆍ견과류',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'lottemart','source_path_parts':['쌀ㆍ잡곡ㆍ견과류'],'source_title':title}
    assert reviewed_lotte_nut_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_lotte_nut_leaf({**evidence,'source_path_parts':['가전']}) is None
    assert reviewed_lotte_nut_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['고구마 스틱 (300G)','명인부각 누룽지 (180G)'])
def test_lotte_mixed_nut_kits_and_unclear_product_forms_remain_pending(title):
    assert classify_record(_raw('lottemart','쌀ㆍ잡곡ㆍ견과류',title))['unified_category_id'] is None


@pytest.mark.parametrize('title,leaf',EMART_TITLES.items())
def test_emart_pantry_exact_forms_reuse_leaves_without_shelf_guessing(title,leaf):
    result=classify_record(_raw('emart','양념/오일',title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'emart','source_path_parts':['양념/오일'],'source_title':title}
    assert reviewed_seasoning_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_seasoning_leaf({**evidence,'source_path_parts':['과자/간식']}) is None
    assert reviewed_seasoning_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title',['백설 알룰로스 700g'])
def test_emart_pantry_does_not_guess_unspecified_form_or_opaque_sauce(title):
    assert classify_record(_raw('emart','양념/오일',title))['unified_category_id'] is None


@pytest.mark.parametrize('mart,path,title,leaf', [
    ('lottemart','과일','프라임 사과, 배 (사과4입, 배6입)','food.produce.assortments.fresh_fruit'),
    ('lottemart','과일','한가득 정성담은 혼합과일 11종 (4KG/박스)','food.produce.assortments.fresh_fruit'),
    ('lottemart','과일','망고 혼합 (옐로망고, 애플망고) (태국망고 3입,애플망고 6입)','food.produce.fruit.mango'),
    ('emart','양념/오일','현미유1L','food.seasonings.oils.rice_bran'),
    ('emart','양념/오일','백설 멸치디포리가득 육수에는 1분링 80g','food.seasonings.stock.stock_seasoning'),
    ('emart','양념/오일','데일리갈릭디핑소스315g','food.seasonings.sauces.garlic_dip'),
    ('emart','양념/오일','장아찌간장소스 1.7L','food.seasonings.sauces.pickling_soy'),
    ('lottemart','쌀ㆍ잡곡ㆍ견과류','바프 HBAF 허니버터아몬드&땅콩 (280G)','food.grains.nuts.mixed'),
    ('lottemart','쌀ㆍ잡곡ㆍ견과류','바프 HBAF 와사비맛아몬드&땅콩 (280G)','food.grains.nuts.mixed'),
    ('lottemart','쌀ㆍ잡곡ㆍ견과류','듀럼밀 (1.5KG)','food.grains.rice.durum_wheat'),
    ('lottemart','쌀ㆍ잡곡ㆍ견과류','HBAF 카라멜 아몬드 앤 프레첼 (120G)','food.snacks.assortments.nuts_pretzels'),
])
def test_sep27_explicit_forms_replace_missing_leaf_holds(mart,path,title,leaf):
    assert classify_record(_raw(mart,path,title))['unified_category_id'] == leaf
    assert classify_record(_raw(mart,'가전',title))['unified_category_id'] is None
    assert classify_record(_raw(mart,path,title+' + 다른상품 혼합세트'))['unified_category_id'] != leaf


@pytest.mark.parametrize("mart,title,leaf", [(mart, title, leaf) for mart, titles in FRUIT_TITLES.items() for title, leaf in titles.items()])
def test_reviewed_single_fruit_titles_reuse_existing_leaves_without_approval(mart, title, leaf):
    result = classify_record(_raw(mart, "과일", title))
    assert result["unified_category_id"] == leaf
    assert result["review_status"] == "classified"
    assert result["classification_confidence"] >= 0.80
    evidence = {"mart": mart, "source_title": title, "source_path_parts": ["과일"]}
    assert reviewed_emart_produce_leaf({**evidence, "source_path_parts": ["무관한 매대"]}) is None
    assert reviewed_emart_produce_leaf({**evidence, "mart": "costco"}) is None
    assert reviewed_emart_produce_leaf({**evidence, "source_title": title + " 혼합세트"}) is None


@pytest.mark.parametrize("mart,title", [
    ("emart", "부드러운 복숭아 1.25kg 내외 (4~6입)/팩"),
    ("emart", "까망 애플수박 1.5kg미만"),
    ("emart", "친환경 신선 행사 모음전"),
])
def test_new_fruit_table_does_not_resolve_mixed_or_variable_weight_listings(mart, title):
    result = classify_record(_raw(mart, "과일", title))
    expected = {'부드러운 복숭아 1.25kg 내외 (4~6입)/팩': 'food.produce.fruit.peach',
                '까망 애플수박 1.5kg미만': 'food.produce.fruit.watermelon'}.get(title)
    assert result["unified_category_id"] == expected
    if expected:
        from core.catalog_quantity import normalize_catalog_package
        assert normalize_catalog_package({'package_quantity': 1500, 'package_unit': 'g'}, {}, title)[1]


@pytest.mark.parametrize("title,leaf", CLEANING_TITLES.items())
def test_reviewed_cleaning_forms_use_exact_titles_and_context_not_shelf_alone(title, leaf):
    result = classify_record(_raw("costco", "세제", title))
    assert result["unified_category_id"] == leaf
    assert result["review_status"] == "classified"
    assert result["evidence_type"] == "audited_costco_cleaning_title"
    evidence = {"mart": "costco", "source_title": title, "source_path_parts": ["세제"]}
    assert reviewed_costco_cleaning_leaf({**evidence, "mart": "emart"}) is None
    assert reviewed_costco_cleaning_leaf({**evidence, "source_path_parts": ["가전"]}) is None
    assert reviewed_costco_cleaning_leaf({**evidence, "source_title": title + " 혼합 선물세트"}) is None


@pytest.mark.parametrize("title", [
    "레고 시티 드라이브스루 세차장 60497", "펠로우즈 문서세단기 12C 19L (꽃가루형)",
    "네일메드코세정제리필세정용분말250포", "프로쉬 세탁세제 선물세트",
    "비트세탁세제 7kg", "넬리 소다세제 1.5kg + 울드라이어볼x 4",
])
def test_cleaning_shelf_does_not_infer_devices_medical_or_opaque_forms(title):
    assert classify_record(_raw("costco", "세제", title))["unified_category_id"] == _REVIEWED_LEDGER001.get(('세제', title))


@pytest.mark.parametrize('path,title,leaf',[(path,title,leaf) for (path,title),leaf in SEAFOOD_ENTRIES.items()])
def test_reviewed_seafood_requires_exact_title_full_path_and_real_product_form(path,title,leaf):
    result=classify_record(_raw('homeplus',list(path),title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    assert len(result['category_path'])==4
    evidence={'mart':'homeplus','source_path_parts':list(path),'source_title':title}
    assert reviewed_homeplus_seafood_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_homeplus_seafood_leaf({**evidence,'source_path_parts':['수산물/건어물']}) is None
    assert reviewed_homeplus_seafood_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('path,title',[
    (['수산물/건어물','간편/냉동수산물','수산간편식','소스류'],'홀스래디쉬 소스 210G'),
    (['수산물/건어물','간편/냉동수산물','냉동간편수산물','냉동새우'],'간편 씨푸드믹스 600G(팩)'),
    (['수산물/건어물','연체갑각류','새우/게/랍스터/크랩류','꽃게'],'서해안 꽃게(국내산/해동) 100G'),
])
def test_seafood_table_does_not_guess_sauces_mixed_or_counter_sale_quantity(path,title):
    assert reviewed_homeplus_seafood_leaf({'mart':'homeplus','source_path_parts':path,'source_title':title}) is None


def test_audited_squid_only_removes_vetoed_shrimp_not_other_valid_conflicts():
    path=['수산물/건어물','간편/냉동수산물','냉동간편수산물','냉동새우']
    result=classify_record(_raw('homeplus',path,'손질 오징어링 500G(팩)'))
    assert result['unified_category_id']=='food.seafood.molluscs.squid'


def test_audited_seafood_does_not_override_a_candidate_without_a_veto(monkeypatch):
    import services.initial_taxonomy as taxonomy
    original=taxonomy._suspicion_reason
    def suspicion(category,evidence):
        return None if category=='food.seafood.shellfish.shrimp' else original(category,evidence)
    monkeypatch.setattr(taxonomy,'_suspicion_reason',suspicion)
    path=['수산물/건어물','간편/냉동수산물','냉동간편수산물','냉동새우']
    result=classify_record(_raw('homeplus',path,'손질 오징어링 500G(팩)'))
    assert result['unified_category_id'] is None
    assert set(result['candidate_category_ids'])=={'food.seafood.molluscs.squid','food.seafood.shellfish.shrimp'}


@pytest.mark.parametrize('path,title,leaf',[(path,title,leaf) for (path,title),leaf in SNACK_ENTRIES.items()])
def test_snack_and_bakery_forms_are_not_the_mixed_retail_leaf(path,title,leaf):
    result=classify_record(_raw('homeplus',list(path),title))
    assert result['unified_category_id']==leaf
    assert result['review_status']=='classified'
    evidence={'mart':'homeplus','source_path_parts':list(path),'source_title':title}
    assert reviewed_homeplus_snack_leaf({**evidence,'mart':'costco'}) is None
    assert reviewed_homeplus_snack_leaf({**evidence,'source_path_parts':['과자/시리얼']}) is None
    assert reviewed_homeplus_snack_leaf({**evidence,'source_title':title+' 혼합세트'}) is None


@pytest.mark.parametrize('title', ['풀무원 토이쿠키 만들기 300G'])
def test_frozen_dessert_brand_or_diy_kit_does_not_prove_ready_baked_cookie(title):
    from services.initial_audited_homeplus_snacks import FROZEN
    assert classify_record(_raw('homeplus',list(FROZEN),title))['unified_category_id'] == 'food.bakery.kits.cookie'


@pytest.mark.parametrize('title', ['화정당 두바이 쫀득쿠키 오리지널 160G','화정당 두바이+말차 쫀득쿠키 160G'])
def test_reviewed_chewy_cookie_is_not_assumed_baked(title):
    from services.initial_audited_homeplus_snacks import FROZEN
    assert classify_record(_raw('homeplus',list(FROZEN),title))['unified_category_id'] == 'food.snacks.chewy.cookie'
    assert classify_record(_raw('homeplus',['가전'],title))['unified_category_id'] is None
    assert classify_record(_raw('homeplus',list(FROZEN),title+' + 아이스크림 혼합세트'))['unified_category_id'] != 'food.snacks.chewy.cookie'


@pytest.mark.parametrize('leaf_id', [
    'food.seasonings.roux.curry', 'food.meals.prepared.meatballs',
    'food.supplements.functional.banaba', 'food.drinks.powders.grain', 'food.snacks.chewy.cookie',
])
def test_operator_batch_leaves_remain_review_only(leaf_id):
    leaf = next(item for item in LEAVES if item.id == leaf_id)
    assert len(leaf.path) == 4
    assert not leaf.name_terms and not leaf.source_labels


@pytest.mark.parametrize('title', ['돌핀 폴라레티 후르트 400ML','돌핀 폴라레티 해피썸머 400ML','돌핀 폴라레티 후르츠 바이오 400ML'])
def test_unknown_liquid_jelly_shelf_forms_are_not_assumed_pudding(title):
    from services.initial_audited_homeplus_snacks import JELLY
    assert classify_record(_raw('homeplus',list(JELLY),title))['unified_category_id'] is None


def test_residual177_exact_soymilk_and_jelly_context_do_not_create_brand_guesses():
    soy_path = ['우유/유제품', '두유', '일반두유']
    title = '정식품 베지밀 달콤한 검은콩B 190ML*16'
    assert classify_record(_raw('homeplus', soy_path, title))['unified_category_id'] == 'food.plant.soy.soymilk'
    for name in ('정식품 베지밀 검은콩 190ML', '하이뮨 프로틴밸런스 액티브 딸기 250ML', '하이뮨 프로틴액티브 밀크 250ML'):
        assert classify_record(_raw('homeplus', soy_path, name))['unified_category_id'] is None
    assert classify_record(_raw('homeplus', ['우유/유제품'], title))['unified_category_id'] is None
    from services.initial_audited_homeplus_snacks import ACTUAL_JELLY
    for name in ('자임 콜라겐 레몬 젤리 210G', '자임 콜라겐 애사비 젤리 210G'):
        assert classify_record(_raw('homeplus', list(ACTUAL_JELLY), name))['unified_category_id'] == 'food.snacks.sweets.jelly'
        assert reviewed_homeplus_snack_leaf({'mart': 'homeplus', 'source_path_parts': ['건강식품'], 'source_title': name}) is None
    assert classify_record(_raw('homeplus', list(ACTUAL_JELLY), '돌핀 폴라레티 후르트 400ML'))['unified_category_id'] is None


def test_residual177_drinking_greek_conjunction_and_seokbakji_positive_veto():
    path = ['우유ㆍ유제품', '요거트ㆍ요구르트', '마시는요구르트']
    combined = classify_record(_raw('lottemart', path, '요즘 마시는 그릭요거트 무가당 플레인 (750ML)'))
    assert combined['candidate_category_ids'] == ['food.dairy.yogurt.drinking_greek']
    assert combined['unified_category_id'] == 'food.dairy.yogurt.drinking_greek'
    assert not combined['reviewed_rejected_category_ids']  # valid broader forms are subsumed
    plain = classify_record(_raw('lottemart', path, '그릭요거트 플레인 750ML'))
    assert plain['unified_category_id'] is None  # drink path alone cannot prove conjunction
    conflict = classify_record(_raw('lottemart', path + ['초코우유'], '마시는 그릭요거트 750ML'))
    assert conflict['unified_category_id'] is None and 'food.dairy.yogurt.drinking_greek' in conflict['candidate_category_ids']
    from services.initial_taxonomy import _suspicion_reason, source_evidence
    evidence = source_evidence(_raw('lottemart', ['김치', '총각김치'], '대상 종가 석박지 900G'))
    assert _suspicion_reason('food.preserved.kimchi.radish', evidence) == 'source_title_product_type_conflict'


@pytest.mark.parametrize('mart,path,title,url,leaf', [
    ('costco', 'SpecialPriceOffers', '정관장 홍삼원 50ml x 60포 x 5',
     'https://www.costco.co.kr/Gift-Set-Special/Food-Gift-Set/Jung-Kwan-Jang-Red-Ginseng-Tonic-50ml-x-60-x-5/p/599850', 'food.supplements.extract.red_ginseng'),
    ('costco', 'SpecialPriceOffers', '햇반 김치치즈 주먹밥 100g X 12 X 2',
     'https://www.costco.co.kr/Foods/Frozen-Foods/Instant-FoodDumplingTraditional-PancakesCheese/Rice-Ball-Kimchi-Cheese-100g-x-12-x-2/p/674445', 'food.meals.rice.rice_ball'),
    ('emart', '베스트', '신라면 5입 600g (120gx5입)',
     'https://m-emart.ssg.com/item/itemView.ssg?itemId=0000008333648&siteNo=6001&salestrNo=2037', 'food.meals.noodles.bag_ramen'),
])
def test_residual177_promotion_source_corroboration_requires_exact_official_listing(mart,path,title,url,leaf):
    assert classify_record(_raw(mart,path,title,canonical_url=url,sale_price=100))['unified_category_id'] == leaf
    assert classify_record(_raw(mart,path,title,canonical_url=url,sale_price=200))['unified_category_id'] == leaf
    wrong_host = url.replace('www.costco.co.kr', 'example.com').replace('m-emart.ssg.com', 'example.com')
    for actual_path, actual_title, actual_url in (
        (path,title,''), (path,title,wrong_host), (path,title,url.replace('/p/', '/p/9').replace('itemId=', 'itemId=9')),
        ('무관한매대',title,url), (path,title+' 변경',url),
    ):
        assert classify_record(_raw(mart,actual_path,actual_title,canonical_url=actual_url))['unified_category_id'] != leaf


def test_homeplus_full_path_maps_to_a_four_level_flavoured_milk_leaf():
    result = classify_record(_raw("homeplus", "식품 > 유제품 > 우유 > 초코우유"))
    assert result["unified_category_id"] == "food.dairy.milk.chocolate"
    assert result["category_path"] == ["식품", "유제품", "우유", "초코우유"]
    assert result["classification_confidence"] >= 0.95
    assert result["evidence_type"] == "source_full_path"
    assert result["review_status"] == "classified"  # Never approval/publication.


def test_homeplus_adjacent_duplicates_collapse_without_losing_full_path():
    result = classify_record(_raw("homeplus", "우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트 > 떠먹는 요구르트"))
    assert result["source_path_parts"] == ["우유/유제품", "요거트/요구르트", "떠먹는 요구르트"]
    assert result["unified_category_id"] == "food.dairy.yogurt.spoon"


def test_homeplus_nested_path_beats_top_level_root_only_category():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유/저지방우유 > 흰우유", category="우유/유제품", mart_native_category_id="root-only-17"))
    assert result["unified_category_id"] == "food.dairy.milk.plain"
    assert result["source_path_field"] == "attributes.mart_native_category_path"
    assert result["raw_native_category_id"] == "root-only-17"
    assert result["native_category_key"].startswith("homeplus:path:")


def test_lotte_list_path_is_retained_and_consolidated():
    record = {"source": "롯데마트", "name": "검수할 상품", "attributes": {"category_path": ["우유ㆍ유제품", "우유", "바나나ㆍ딸기ㆍ초코ㆍ커피우유", "딸기우유"]}}
    result = classify_record(record)
    assert result["mart"] == "lottemart"
    assert result["unified_category_id"] == "food.dairy.milk.strawberry"
    assert result["source_path_parts"] == record["attributes"]["category_path"]


@pytest.mark.parametrize("wrapper", ["payload", "raw_payload"])
def test_normalized_observation_wrapper_is_equivalent_to_raw_payload(wrapper):
    raw = _raw("homeplus", "우유/유제품 > 치즈/버터 > 슬라이스 치즈 > 슬라이스 치즈")
    direct = classify_record(raw)
    normalized = classify_record({"source_name": "homeplus", "source_record_key": "123", wrapper: raw})
    assert normalized == direct


def test_normalized_observation_top_level_path_fallback():
    result = classify_record({"source_name": "lottemart", "source_title": "상품", "source_category_path": ["과일", "사과ㆍ배", "사과"], "raw_payload": {"name": "상품"}})
    assert result["unified_category_id"] == "food.produce.fruit.apple"


@pytest.mark.parametrize("path", ["우유/유제품", "생수/음료/주류", "정육/계란류"])
def test_emart_slashes_are_not_hierarchy_or_specific_leaf_evidence(path):
    result = classify_record(_raw("emart", path))
    assert result["source_path_parts"] == [path]
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "broad_source_category"
    assert result["proposed_path"] == [path]


def test_broad_milk_path_needs_specific_flavour_name():
    path = "우유/유제품 > 우유 > 딸기/초코/바나나/기타 우유"
    unresolved = classify_record(_raw("homeplus", path, "브랜드 가공우유 200ml"))
    assert unresolved["unified_category_id"] is None
    assert unresolved["proposed_path"] == path.split(" > ")
    classified = classify_record(_raw("homeplus", path, "브랜드 초코우유 200ml"))
    assert classified["unified_category_id"] == "food.dairy.milk.chocolate"
    assert classified["evidence_type"] == "unambiguous_name_tokens"


@pytest.mark.parametrize("surface", ["Best", "Obanjang", "SpecialPriceOffers", "베스트", "오반장"])
def test_promotion_surface_is_not_a_category(surface):
    result = classify_record(_raw("costco", surface))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"
    assert result["classification_reason"] == "promotion_surface_without_leaf_evidence"


def test_costco_official_razor_taxonomy_resolves_promotion_surface():
    result = classify_record(_raw("costco", "SpecialPriceOffers", "질레트 상품", canonical_url="https://www.costco.co.kr/Health-Beauty/Shaving/Razors/Gillette-Proshield/p/123456"))
    assert result["unified_category_id"] == "beauty.personal.shaving.razor"
    assert result["evidence_type"] == "official_url_taxonomy"
    assert result["source_path"] == "SpecialPriceOffers"
    assert "razors" in result["url_taxonomy_hints"]


def test_costco_broad_shaving_url_needs_product_name_not_a_guessed_leaf():
    url = "https://www.costco.co.kr/Health-Beauty/Shaving/Gillette-Set/p/123456"
    assert classify_record(_raw("costco", "SpecialPriceOffers", canonical_url=url))["unified_category_id"] is None
    result = classify_record(_raw("costco", "SpecialPriceOffers", "질레트 면도기 세트", detail_url=url))
    assert result["unified_category_id"] == "beauty.personal.shaving.razor"


@pytest.mark.parametrize("url", [
    "https://example.test/Health-Beauty/Shaving/Razors/Product/p/123",
    "https://www.costco.co.kr.evil.test/Health-Beauty/Shaving/Razors/Product/p/123",
    "https://www.costco.co.kr/Food/Razors/p/123",  # Product slug, not category.
])
def test_url_must_be_official_and_category_prefix_not_product_slug(url):
    assert classify_record(_raw("costco", "SpecialPriceOffers", canonical_url=url))["unified_category_id"] is None


def test_costco_url_name_conflict_remains_unresolved():
    result = classify_record(_raw("costco", "과자", "브랜드 샴푸 500ml", canonical_url="https://www.costco.co.kr/Health-Beauty/Shaving/Razors/Product/p/123"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "conflicting_category_evidence"
    assert len(result["candidate_category_ids"]) == 2


def test_exact_source_name_conflict_remains_unresolved():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", "브랜드 초코우유 200ml"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "conflicting_category_evidence"


def test_homeplus_root_native_id_does_not_merge_different_paths():
    plain = source_evidence(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", mart_native_category_id="same-root"))
    chocolate = source_evidence(_raw("homeplus", "우유/유제품 > 우유 > 초코우유", mart_native_category_id="same-root"))
    assert plain["raw_native_category_id"] == chocolate["raw_native_category_id"]
    assert plain["native_category_key"] != chocolate["native_category_key"]
    assert plain["native_category_key"] == native_category_key("homeplus", ["우유/유제품", " 우유 ", "흰우유"])


def test_missing_lotte_native_id_still_gets_stable_key():
    a = source_evidence(_raw("lottemart", ["과일", "사과ㆍ배", "사과"]))
    b = source_evidence(_raw("lottemart", ["과일", "사과·배", "사과"]))
    assert a["raw_native_category_id"] is None
    assert a["native_category_key"] == b["native_category_key"]
    assert native_category_key("lottemart", []) is None


@pytest.mark.parametrize(("mart", "path", "category_id"), [
    ("homeplus", "과자/시리얼 > 과자/쿠키/파이 > 비스켓/쿠키/프레첼 > 초코비스켓", "food.snacks.baked.biscuits"),
    ("lottemart", ["라면ㆍ통조림ㆍ즉석밥", "라면", "컵라면", "일반라면"], "food.meals.noodles.cup_ramen"),
    ("lottemart", ["라면ㆍ통조림ㆍ즉석밥", "라면", "봉지라면", "일반라면"], "food.meals.noodles.bag_ramen"),
    ("homeplus", "냉장/냉동/밀키트 > 만두 > 교자만두/군만두 > 고기교자만두", "food.meals.dumplings.gyoza"),
    ("lottemart", ["채소", "고구마ㆍ감자", "감자"], "food.produce.vegetables.potato"),
    ("lottemart", ["정육ㆍ계란", "국내산소고기"], "food.meat.fresh.beef"),
    ("homeplus", "수산물/건어물 > 간편/냉동수산물 > 냉동간편수산물 > 냉동새우", "food.seafood.shellfish.shrimp"),
    ("lottemart", ["양념ㆍ오일ㆍ분말류", "소스류", "파스타소스"], "food.seasonings.sauces.pasta"),
    ("homeplus", "세탁/청소 > 세탁세제/섬유유연제 > 섬유유연제 > 고농축 섬유유연제", "household.cleaning.laundry.softener"),
    ("homeplus", "기저귀 > 하기스/마미포코 > 하기스 > 하기스", "baby.hygiene.diapering.diapers"),
])
def test_semantic_paths_cover_multiple_departments(mart, path, category_id):
    title = "냉동 새우" if category_id == "food.seafood.shellfish.shrimp" else "검수할 상품"
    assert classify_record(_raw(mart, path, title))["unified_category_id"] == category_id


def test_unknown_source_root_is_not_accepted_just_because_leaf_word_matches():
    result = classify_record(_raw("homeplus", "반려동물 > 우유 > 초코우유"))
    assert result["unified_category_id"] is None


def test_internal_node_is_never_filled_with_an_invented_other_leaf():
    result = classify_record(_raw("homeplus", "식품 > 유제품 > 우유"))
    assert result["unified_category_id"] is None
    assert result["proposed_path"] == ["식품", "유제품", "우유"]
    assert not any("기타" in leaf.path[-1] for leaf in LEAVES)


def test_taxonomy_is_deterministic_four_levels_and_assignments_are_leaves():
    categories = taxonomy_categories()
    assert categories == taxonomy_categories(reversed([leaf.id for leaf in LEAVES]))
    validate_taxonomy(categories, [leaf.id for leaf in LEAVES])
    assert max(row["level"] for row in categories) == 3
    assert {row["name_ko"] for row in categories if row["parent_id"] is None} >= {"식품", "생활용품", "유아동"}
    subset = taxonomy_categories(["food.dairy.milk.chocolate"])
    assert len(subset) == 4


def test_taxonomy_validation_rejects_internal_assignment_and_bad_trees():
    categories = taxonomy_categories(["food.dairy.milk.chocolate"])
    with pytest.raises(ValueError, match="leaf"):
        validate_taxonomy(categories, ["food.dairy.milk"])
    with pytest.raises(ValueError, match="four levels"):
        validate_taxonomy([*categories, {"id": "fifth", "parent_id": "food.dairy.milk.chocolate"}])
    with pytest.raises(ValueError, match="Missing"):
        validate_taxonomy([{ "id": "orphan", "parent_id": "absent"}])
    with pytest.raises(ValueError, match="cycle"):
        validate_taxonomy([{"id": "a", "parent_id": "b"}, {"id": "b", "parent_id": "a"}])
    with pytest.raises(ValueError, match="Duplicate"):
        validate_taxonomy([categories[0], categories[0]])


def test_keyword_seed_is_fresh_leaf_only_and_collision_free():
    rows = keyword_definitions()
    assert len(rows) > 100
    validate_keyword_definitions(rows)
    assert keyword_collisions(rows) == {}
    assert all(len(row["word"]) >= 2 for row in rows)
    assert all(row["unified_category_id"] in {leaf.id for leaf in LEAVES} for row in rows)


def test_keywords_use_token_boundaries_and_multiword_synonyms():
    assert contains_term("[브랜드] 초코우유 200ml", "초코우유")
    assert contains_term("BRAND Chocolate Milk 200ml", "chocolate milk")
    assert not contains_term("초코우유맛과자 200g", "초코우유")
    assert not contains_term("초코우유맛 과자 200g", "우유")
    assert classify_record(_raw("emart", "베스트", "초코우유맛과자"))["unified_category_id"] is None


def test_keyword_ambiguous_collision_and_one_character_are_rejected():
    rows = [
        {"word": "초코우유", "synonyms": ["chocolate milk"], "unified_category_id": "food.dairy.milk.chocolate"},
        {"word": "딸기우유", "synonyms": ["Chocolate-Milk"], "unified_category_id": "food.dairy.milk.strawberry"},
    ]
    assert keyword_collisions(rows) == {"chocolate milk": ["food.dairy.milk.chocolate", "food.dairy.milk.strawberry"]}
    with pytest.raises(ValueError, match="collision"):
        validate_keyword_definitions(rows)
    with pytest.raises(ValueError, match="two characters"):
        validate_keyword_definitions([{ "word": "유", "synonyms": [], "unified_category_id": "food.dairy.milk.plain"}])


def test_path_normalization_preserves_nonadjacent_repeats_and_slashes():
    assert normalize_source_path(["A", "A", "B/C", "A"]) == ("A", "B/C", "A")
    assert normalize_source_path('["우유/유제품", "우유", "초코우유"]') == ("우유/유제품", "우유", "초코우유")


def test_milk_fat_and_sterilization_are_attributes_not_flavour_siblings():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", "매일 소화가잘되는우유 멸균 저지방 190ML*6"))
    assert result["unified_category_id"] == "food.dairy.milk.plain"
    assert result["classification_attributes"] == {"fat_content": "low_fat", "sterilized": True}
    chocolate = classify_record(_raw("emart", "우유/유제품", "저지방 초코우유 200ml"))
    assert chocolate["unified_category_id"] == "food.dairy.milk.chocolate"
    assert chocolate["classification_attributes"]["fat_content"] == "low_fat"
    assert "food.dairy.milk.low_fat" not in {leaf.id for leaf in LEAVES}


@pytest.mark.parametrize(("mart", "path", "title"), [
    ("homeplus", "라면/즉석식품/통조림 > 즉석식품/누룽지/죽 > 즉석국 > 즉석국(레토르트)", "오뚜기 3분 카레 매운맛 200G"),
    ("homeplus", "냉장/냉동/밀키트 > 돈까스/떡갈비/너겟 > 돈까스", "목우촌 주부9단치킨까스 360G"),
    ("homeplus", "두부/김치/반찬 > 두부/나물 > 낫또", "풀무원 국산콩 진한 콩국물 960G"),
    ("homeplus", "두부/김치/반찬 > 두부/나물 > 순두부/연두부", "씨제이 다담 순두부 찌개 양념 140G"),
    ("homeplus", "냉장/냉동/밀키트 > 떡볶이/면류 > 냉면/소바 > 간편냉면&소바", "씨제이 동치미 냉면육수 300ML"),
    ("homeplus", "수산물/건어물 > 간편/냉동수산물 > 냉동간편수산물 > 냉동새우", "손질 오징어링 500G"),
    ("homeplus", "두부/김치/반찬 > 어묵/맛살/단무지 > 어묵 > 볶음용어묵", "사조대림 실 곤약 400G"),
    ("emart", "수산물/건해산", "고소한 참기름 돌 김자반 50G"),
    ("emart", "베스트", "화장지/키친타올/생리대 특가(※일부품목제외)"),
    ("homeplus", "세탁/청소 > 세탁세제/섬유유연제 > 섬유유연제", "LG 아우라 피톤치드 편백탈취제 숲속향 500ML"),
    ("emart", "반려동물", "강아지 샴푸 500ml"),
])
def test_observed_source_path_pollution_does_not_get_high_confidence(mart, path, title):
    result = classify_record(_raw(mart, path, title))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"
    assert result["classification_confidence"] < 0.80
    assert result["source_path_parts"]


@pytest.mark.parametrize(("mart", "path", "title", "leaf"), [
    ("costco", "커피", "커클랜드 시그니춰 인스턴트 커피 454g", "food.drinks.coffee.instant"),
    ("costco", "커피", "스타벅스 카페 베로나 홀빈 커피 1.13kg", "food.drinks.coffee.beans"),
    ("costco", "커피", "Hamaya 드립백 커피 8g x 36", "food.drinks.coffee.drip"),
    ("costco", "커피", "벨미오 캡슐커피 클래식 80개입", "food.drinks.coffee.capsule"),
    ("costco", "커피", "네스카페 돌체구스토 아이스 아메리카노 캡슐 36P", "food.drinks.coffee.capsule"),
    ("costco", "커피", "스타벅스 더블샷 200ml x 36캔", "food.drinks.coffee.ready"),
    ("emart", "커피/원두/차", "콜드브루아메리카노(390ml×6)", "food.drinks.coffee.ready"),
    ("homeplus", "커피/차 > 원두커피/캡슐커피 > 분쇄커피 > 분쇄커피", "맥널티 리치 헤이즐넛 분쇄 1KG", "food.drinks.coffee.beans"),
    ("lottemart", ["커피ㆍ원두", "커피믹스ㆍ프림", "커피믹스"], "동서 카누 미니 마일드로스트 아메리카노 100포", "food.drinks.coffee.instant"),
])
def test_audited_coffee_shelves_use_explicit_product_form(mart, path, title, leaf):
    result = classify_record(_raw(mart, path, title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "프리파라 네스프레소 전용 캡슐홀더",
    "아소부 뉴 콜드브루 커피메이커", "쏘울핸드 커피 그라인더",
    "카피탈리 시스템 캡슐 커피 머신", "쓰임 스테이블 커피잔 세트",
    "카페, 진정성 밀크티 350ml", "루카스나인 우베라떼 18g x 50",
    "맥널티 스테비아 단백질 고구마크림라떼 20T(360G)",
])
def test_polluted_coffee_shelf_accessories_and_other_drinks_stay_pending(title):
    reviewed = {
        '프리파라 네스프레소 전용 캡슐홀더': 'household.kitchen.coffee.capsule_holder',
        '아소부 뉴 콜드브루 커피메이커': 'household.kitchen.coffee.cold_brew_maker',
        '쏘울핸드 커피 그라인더': 'household.kitchen.coffee.grinder',
    }
    result = classify_record(_raw("costco", "커피", title))
    assert result["unified_category_id"] == reviewed.get(title)
    assert result["review_status"] == ("classified" if title in reviewed else "pending")


def test_mixed_instant_and_drip_coffee_gift_set_stays_pending():
    result = classify_record(_raw("costco", "커피", "스타벅스 아메리카노 & 드립백커피 선물세트"))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("커클랜드 시그니춰 홍자몽주스 2.84L x 2", "food.drinks.juice.fruit"),
    ("델몬트 스테비아 토마토 주스 950ml x 6", "food.drinks.juice.vegetable"),
    ("야채듬뿍 더'진한 레드 주스 125ml x 24", "food.drinks.juice.vegetable"),
    ("풀무원녹즙 프레시업 양배추천해 190ml x 10", "food.drinks.juice.vegetable"),
    ("커클랜드 시그니춰 유기농 코코넛워터 330mlx12", "food.drinks.juice.coconut"),
    ("피지워터 330ml X 24", "food.drinks.water_soda.water"),
    ("동원미네마인스파클링워터 500ml x 48", "food.drinks.water_soda.sparkling"),
    ("코카콜라 250ml x 30", "food.drinks.water_soda.cola"),
    ("칠성사이다 1.8L x 6", "food.drinks.water_soda.cider"),
    ("몬스터에너지울트라 355ml x 24캔", "food.drinks.water_soda.energy"),
    ("토레타과채이온음료 340ml x 24캔", "food.drinks.water_soda.sports"),
    ("분다버그 진저 비어캔 200ml x 24", "food.drinks.water_soda.soda"),
    ("녹차원 보이차 0.9g x 100티백 x 3", "food.drinks.tea.puer"),
    ("동원보성말차500ml x 24병", "food.drinks.tea.green"),
    ("동원보성홍차아이스티 500ml x 24병", "food.drinks.tea.black"),
    ("블랙보리 520ml X 24", "food.drinks.tea.barley"),
    ("쌍계 김동곤명인의 쑥차 파우더 15g x 40", "food.drinks.powders.herbal_tea"),
    ("양반가마솥누룽지500ml x 24", "food.drinks.tea.grain"),
    ("스타벅스더블샷바닐라 275ml x 24", "food.drinks.coffee.ready"),
])
def test_audited_costco_beverage_shelf_uses_explicit_drink_form(title, leaf):
    result = classify_record(_raw("costco", "음료", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "베트남 영코코넛 9입(7.5kg내외)",
    "폴라레티 후르트 아이스바 40ml x 80",
    "끌레드벨 럭셔리 콜라겐 82 앰플 100ml x 2",
    "벤딕트 차량용 보냉 컵홀더 2개",
    "본비 유차청 2kg",
    "정관장 홍삼원력 50ml x 30포",
    "프리미어 단백질 드링크 325ml x 12팩",
    "칠성사이다 250ml x 30 + 펩시콜라 250ml x 30 콤보팩",
])
def test_audited_costco_beverage_shelf_contaminants_and_unclear_forms_stay_pending(title):
    reviewed = {
        '베트남 영코코넛 9입(7.5kg내외)': 'food.produce.fruit.coconut',
        '벤딕트 차량용 보냉 컵홀더 2개': 'household.vehicle.accessories.cup_holder',
        '정관장 홍삼원력 50ml x 30포': 'food.supplements.extract.red_ginseng',
        '프리미어 단백질 드링크 325ml x 12팩': 'food.supplements.protein.drink',
        '칠성사이다 250ml x 30 + 펩시콜라 250ml x 30 콤보팩': 'food.drinks.assortments.combo',
    }
    result = classify_record(_raw("costco", "음료", title))
    assert result["unified_category_id"] == reviewed.get(title)
    assert result["review_status"] == ("classified" if title in reviewed else "pending")
    if result['unified_category_id'] == 'food.drinks.assortments.combo':
        from core.catalog_quantity import normalize_catalog_package
        _, issues = normalize_catalog_package({'pack_qty':250,'pack_unit':'ml'}, {}, title)
        assert 'mixed_package_unresolved' in issues


def test_frozen_watermelon_juice_does_not_match_the_korean_word_for_bottled_water():
    result = classify_record(_raw("costco", "음료", "엘제이드얼린생수박주스340ml x 8 x 2"))
    assert result["unified_category_id"] == "food.drinks.juice.fruit"


@pytest.mark.parametrize(("title", "leaf"), [
    ("초정탄산수 1.5L", "food.drinks.water_soda.sparkling"),
    ("백산수 2L", "food.drinks.water_soda.water"),
    ("에비앙 500ml*12입+쇼퍼백 기획", "food.drinks.water_sets.water_bag"),
    ("포카리스웨트900ml", "food.drinks.water_soda.sports"),
    ("칠성사이다 1.8L*2입", "food.drinks.water_soda.cider"),
    ("제로사이다 1L", "food.drinks.water_soda.cider"),
    ("썬키스트 애사비 제로스파클링 500ML", "food.drinks.water_soda.soda"),
    ("[논알콜] 클라우스탈러 330ml(캔)", "food.drinks.non_alcoholic.beer"),
    ("이토엔 오이오차녹차 525ml", "food.drinks.tea.green"),
    ("하늘보리 500ml", "food.drinks.tea.barley"),
    ("옥수수수염차 1.5L", "food.drinks.tea.grain"),
    ("비락식혜 1.5L", "food.drinks.tea.grain"),
    ("스페인 햇살 담은 오렌지 100% 착즙주스 1L", "food.drinks.juice.fruit"),
    ("Fresh토마토음료 1.5L", "food.drinks.juice.vegetable_drink"),
    ("Fresh감귤음료1.5L", "food.drinks.juice.fruit_drink"),
    ("Fresh알로에음료1.5L", "food.drinks.juice.aloe"),
    ("쿨피스플러스 930ml*2입", "food.drinks.juice.fruit_drink"),
])
def test_audited_emart_beverage_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("emart", "생수/음료/주류", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "1.8L*2입",
    "처음먹는 배도라지",
    "오트몬드 프로틴 초코 250ml",
])
def test_audited_emart_beverage_shelf_requires_explicit_form_evidence(title):
    result = classify_record(_raw("emart", "생수/음료/주류", title))
    # Literal protein + measured beverage context establishes marketed drink
    # form, not a plant/dairy base inferred from the brand.
    expected = 'food.supplements.protein.drink' if title == '오트몬드 프로틴 초코 250ml' else None
    assert result["unified_category_id"] == expected


def test_explicit_bottled_water_name_stays_consistent_on_emart_promotion_shelf():
    result = classify_record(_raw("emart", "베스트", "삼다수 2L (무라벨)"))
    assert result["unified_category_id"] == "food.drinks.water_soda.water"


def test_non_alcoholic_word_without_audited_beer_evidence_does_not_mean_beer():
    result = classify_record(_raw("emart", "생수/음료/주류", "논알콜 샹그리아 750ml"))
    assert result["unified_category_id"] is None


def test_apple_cider_vinegar_drink_does_not_become_korean_cider_soda():
    result = classify_record(_raw("costco", "음료", "쌍계 애플사이다비니거 드링크 사과 5g x 40ct"))
    assert result["unified_category_id"] is None


def test_adjacent_bottle_count_waits_until_package_parser_supports_it():
    result = classify_record(_raw("emart", "생수/음료/주류", "제주 삼다수 그린 500ml 40병"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "source_title_product_type_conflict"


@pytest.mark.parametrize(("title", "leaf"), [
    ("커클랜드 시그니춰 탈각 피스타치오 680g", "food.grains.nuts.pistachio"),
    ("커클랜드 시그니춰 무염 견과 스낵팩 945g", "food.grains.nuts.mixed"),
    ("커클랜드 시그니춰 핑크 솔트감자칩 907g", "food.snacks.savory.potato"),
    ("G.H.CRETORS 시카고 믹스 팝콘 737g", "food.snacks.savory.popcorn"),
    ("El Sabroso 옐로우콘토티야칩851g", "food.snacks.savory.tortilla_nacho"),
    ("Jackson고구마칩454g", "food.snacks.savory.vegetable"),
    ("C-WEED다시마 부각칩 150g", "food.snacks.savory.seaweed"),
    ("갓 튀김 어포 400g", "food.seafood.processed.fish_snack"),
    ("미왕 고소한 쌀과자 250g x 5", "food.snacks.savory.grain"),
    ("Shultz 미니 프레첼 2.72kg", "food.snacks.baked.pretzel"),
    ("커피크림 웨이퍼롤 180g x 6", "food.snacks.baked.wafer"),
    ("롯데찰떡파이 35g x 35ea", "food.snacks.chewy.rice_cake_pie"),
    ("허쉬 초콜릿칩 쿠키 720g x 2", "food.snacks.baked.biscuits"),
    ("Sennenya 브라운버터 바움쿠헨 50g x 16", "food.snacks.baked.cake"),
    ("화과방 프리미엄 양갱 40g x 40", "food.snacks.traditional.yanggaeng"),
    ("대조 우리쌀 전병 세트 24g x 24", "food.snacks.traditional.hangwa"),
    ("Trolli 젤리 4종 100g x 12", "food.snacks.sweets.jelly"),
    ("Trefin 벨기에 커피 캔디 1.5kg", "food.snacks.sweets.candy"),
    ("Dole 복숭아 과일컵 113g x 16", "food.produce.processed_fruit.cup"),
    ("100% 순수사과 동결건조 과일 30g x 10", "food.produce.processed_fruit.dried"),
    ("카프리썬 오렌지망고 주스 200ml x 20", "food.drinks.juice.fruit"),
    ("LOTTE 빼빼로 모음 644g / 15팩", "food.snacks.baked.biscuits"),
    ("정직하개 애견용 소고기 육포 1kg", "pet.food.treats.meat"),
    ("Arla 하바티 & 고다 스낵치즈 510g x 432ea", "food.dairy.cheese.snack"),
])
def test_audited_costco_snack_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("costco", "과자", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize(('title', 'leaf'), [
    ('피넛버터 크레페 85G', 'food.snacks.baked.crepe'),
    ('크라운 버터와플 316G', 'food.snacks.baked.waffle'),
    ('크리스피 코코넛 롤 400g', 'food.snacks.baked.crispy_roll'),
    ('피넛버터 프레첼 1.56kg', 'food.snacks.baked.pretzel'),
    ('도라야끼 팬케익 310g x 3', 'food.bakery.dessert.pancake'),
    ('명가 찰떡파이 350g (패키지랜덤발송)', 'food.snacks.chewy.rice_cake_pie'),
    ('통밀도너츠 & 초코칩 통밀도너츠 230g x 4', 'food.bakery.dessert.donut'),
    ('토스트 비스켓 1600g', 'food.snacks.baked.toast'),
    ('통밀 참깨 스틱 150G', 'food.snacks.baked.stick'),
    ('딸기 생크림 케이크 408G', 'food.snacks.baked.cake'),
])
def test_literal_baked_form_refines_broad_shelf_without_composition_inference(title, leaf):
    record = _raw('homeplus', '과자/시리얼 > 과자/쿠키/파이 > 비스켓/쿠키/프레첼 > 버터비스켓', title)
    result = classify_record(record)
    # Unrelated path evidence stays a conflict, rather than being discarded.
    if leaf in {'food.bakery.dessert.pancake', 'food.snacks.chewy.rice_cake_pie', 'food.snacks.baked.cake'}:
        record = _raw('costco', '과자', title)
        result = classify_record(record)
    assert result['unified_category_id'] == leaf
    assert result['evidence_type'] == 'literal_baked_product_form_and_context'
    assert not result.get('component_allocation')


@pytest.mark.parametrize('title', ['와플 믹스 500g', '크레페 만들기 키트 200g',
                                  '와플 메이커', '크리스피 웨이퍼롤 200g'])
def test_baked_form_does_not_override_ingredients_equipment_or_other_forms(title):
    result = classify_record(_raw('homeplus', '과자/시리얼 > 과자/쿠키/파이 > 비스켓/쿠키/프레첼 > 버터비스켓', title))
    assert result['unified_category_id'] not in {
        'food.snacks.baked.crepe', 'food.snacks.baked.waffle', 'food.snacks.baked.crispy_roll'}


def test_cake_flavour_on_explicit_cracker_shelf_keeps_cracker_form():
    record = _raw('lottemart', '과자ᆞ스낵ᆞ간식 > 과자ᆞ쿠키ᆞ파이 > 크래커ᆞ샌드 > 크래커',
                  '해태 에이스 바스크치즈케이크 (73G)')
    assert classify_record(record)['unified_category_id'] == 'food.snacks.baked.cracker'
    assert classify_record(_raw('homeplus', '베스트', '버터와플 316G'))['unified_category_id'] is None


@pytest.mark.parametrize("title", [
    "프리미엄 제철과일 선물세트 총 3.4kg이상",
    "락앤락 휴대용 과일 & 요거트 보틀 600ml x 2P", "카스 초음파 야채 과일 세척기 4L",
    "산리오 캐릭터즈 디저트 휘핑 데코 놀이 세트",
    "Snapik 화이트 마시멜로우 1kg x 176",
    "Delici 쿠키버터무스 76g x 6", "해품은김과 김부각 세트",
])
def test_audited_costco_snack_shelf_contaminants_and_bad_packages_stay_pending(title):
    result = classify_record(_raw("costco", "과자", title))
    if '마시멜로우' in title:
        assert result['unified_category_id'] == 'food.snacks.sweets.marshmallow'
        # Literal form is independent of unsupported sold quantities.
        from core.catalog_quantity import normalize_catalog_package
        package, issues = normalize_catalog_package({}, {}, title)
        assert package is None and 'unit_unresolved' in issues
    else:
        assert result["unified_category_id"] == _REVIEWED_LEDGER001.get(('과자', title))


@pytest.mark.parametrize(("title", "leaf"), [
    ("농심 신라면 120g x 30개", "food.meals.noodles.bag_ramen"),
    ("농심 육개장 사발면 86g x 24개", "food.meals.noodles.cup_ramen"),
    ("데 체코파스타면1kg x 4", "food.meals.noodles.pasta"),
    ("백제 김치 쌀국수100g x 10", "food.meals.noodles.rice_noodle"),
    ("풍국면 우리밀 국수 400g x 10팩", "food.meals.noodles.wheat_noodle"),
    ("풍국면 메밀국수 500g x 6팩", "food.meals.noodles.buckwheat_noodle"),
    ("동원들깨칼국수258g x 4", "food.meals.noodles.kalguksu"),
    ("백제 도토리 비빔막국수 297.5g x 8", "food.meals.noodles.makguksu"),
    ("이가자연면 감자수제비186.5g x 8", "food.meals.noodles.sujebi"),
    ("마이노멀 두부면 130g x 12", "food.meals.noodles.tofu_noodle"),
    ("풀무원 수타식 즉석생우동 195g x 10", "food.meals.noodles.udon"),
    ("풀무원 평양 물냉면 205g x 8", "food.meals.noodles.naengmyeon"),
    ("풀무원 로스팅 파기름 짜장면 105g x 24", "food.meals.noodles.black_bean"),
    ("비비고 고메 중화짬뽕 326g x 6", "food.meals.noodles.jjamppong"),
    ("Blue Dragon 팟타이키트 440g x 2", "food.meals.noodles.pad_thai"),
    ("농심 짜파게티범벅 70g x30개", "food.meals.noodles.cup_ramen"),
    ("오뚜기 진짬뽕 130g x32", "food.meals.noodles.bag_ramen"),
    ("농심 사리면 110g x30", "food.meals.noodles.bag_ramen"),
    ("풀무원 생면식감 순한맛 95.9g x 20", "food.meals.noodles.bag_ramen"),
])
def test_audited_costco_noodle_shelf_uses_explicit_noodle_form(title, leaf):
    result = classify_record(_raw("costco", "라면", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize("title", [
    "마이어 라면 조리기", "코렐 더블링 라떼 면기 세트 4P",
    "오뚜기 뿌셔뿌셔 불고기맛 95g x 16",
])
def test_audited_costco_noodle_shelf_contaminants_stay_pending(title):
    result = classify_record(_raw("costco", "라면", title))
    assert result["unified_category_id"] == _REVIEWED_LEDGER001.get(('라면', title))


@pytest.mark.parametrize(("title", "leaf"), [
    ("Mama's Choice치즈 오징어 120g x 3", "food.seafood.processed.dried_fish"),
    ("한우물치즈닭갈비구운주먹밥100gx30", "food.meals.rice.rice_ball"),
    ("풀무원치즈볼4개골라담기(360g x 4)", "food.meals.prepared.cheese_ball"),
    ("애슐리 트리플 치즈 피자 395g x 3", "food.meals.prepared.pizza"),
    ("폰타나토마토&로제파스타소스600g x 4", "food.seasonings.sauces.pasta"),
    ("마다마 피티드 올리브 480g x 3", "food.produce.processed_vegetables.olive"),
    ("수지탈 뇨끼 파타타(감자) 1kg x 3", "food.meals.noodles.gnocchi"),
    ("덕화명란튜브110g x 8", "food.seafood.processed.pollock_roe"),
    ("사옹원 소고기육전 765g x 2", "food.meals.prepared.pancake"),
    ("개성제주돼지감자만두 2KG X 2", "food.meals.dumplings.assorted"),
    ("동원 딤섬 새우하가우1.2KG X 2", "food.meals.dumplings.dimsum"),
    ("CJ 비비고 소고기 듬뿍 설렁탕 460g x 6", "food.meals.prepared.soup_stew"),
    ("하림 치킨너겟 1.5kg x 2", "food.meals.prepared.nugget"),
    ("동원 7겹돈까스 1040g x 2", "food.meals.prepared.pork_cutlet"),
    ("BBQ 야자당 닭강정 1.2KG x 2", "food.meals.prepared.chicken"),
    ("테이블마크키츠네 유부우동 283G X 6", "food.meals.noodles.udon"),
    ("마음이가 모둠 꿀떡1.4kg X 2ea", "food.meals.prepared.rice_cake"),
    ("오마뎅 진짜 부산 떡볶이 352g x 5", "food.meals.prepared.tteokbokki"),
    ("천하장사 더블링 콰트로치즈 25g X 40", "food.meat.processed.sausage"),
    ("Scoiattolo 트러플파마지아노라비올리 908g", "food.meals.noodles.ravioli"),
    ("덴마크 구워먹는치즈 500g x 2", "food.dairy.cheese.grilling"),
])
def test_audited_costco_cheese_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("costco", "치즈", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize("title", [
    "딩고 애견 치킨껌 2개 x 10봉",
    "구르메 치즈 & 초리조선물세트 875g", "타카쇼 로즈아치",
    "쿠진아트 미니 중식도 & 강판 세트", "치자 2개입",
])
def test_audited_costco_cheese_shelf_ambiguous_and_nonfood_items_stay_pending(title):
    reviewed = {
        '딩고 애견 치킨껌 2개 x 10봉': 'pet.food.treats.chew',
        '구르메 치즈 & 초리조선물세트 875g': 'food.meals.sets.cheese_processed_meat',
        '타카쇼 로즈아치': 'household.garden.structures.arch',
        '쿠진아트 미니 중식도 & 강판 세트': 'household.kitchen.utensils.cleaver_grater_set',
    }
    result = classify_record(_raw("costco", "치즈", title))
    assert result["unified_category_id"] == reviewed.get(title)


def test_reviewed_ghee_is_butter_but_mixed_and_wrong_context_stay_pending():
    title = "ORGANIC VALLEY기버터 368G"
    assert classify_record(_raw("costco", "우유", title))["unified_category_id"] == "food.dairy.cheese.butter"
    assert classify_record(_raw("emart", "우유/유제품", title))["unified_category_id"] == "food.dairy.cheese.butter"
    assert classify_record(_raw("costco", "우유", title + " 쿠키 혼합세트"))["unified_category_id"] is None
    assert classify_record(_raw("costco", "자동차", title))["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("후레쉬 라임 8kg", "lime"),
    ("남아공 자몽16kg", "grapefruit"),
    ("용과 4.8kg 선물세트", "dragon_fruit"),
    ("브라질애플망고선물세트3.7kg", "mango"),
])
def test_audited_fruit_title_requires_matching_store_and_shelf(title, leaf):
    result = classify_record(_raw("costco", "과일", title))
    assert result["unified_category_id"] == f"food.produce.fruit.{leaf}"
    assert result["evidence_type"] == "audited_costco_fruit_title"
    assert classify_record(_raw("costco", "과일", title + " 주스"))["unified_category_id"] is None
    assert classify_record(_raw("costco", "커피", title))["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("한우물 소고기잡채350g x 5 x 2pk", "food.meals.prepared.japchae"),
    ("오늘차림 한돈 양념 불고기600g x 3ea", "food.meals.prepared.seasoned_meat"),
    ("부추고기순대 500gx3x2", "food.meat.processed.sundae"),
    ("오리늘보 훈제 슬라이스 500g x 2", "food.meat.processed.smoked_duck"),
    ("마이셰프한우소고기미역국 254g x 2", "food.meals.prepared.soup_stew"),
    ("피터루거 스테이크소스 714ml x 2", "food.seasonings.sauces.meat"),
    ("실키 핑크토마토4kg", "food.produce.fruit.tomato"),
])
def test_audited_meat_shelf_uses_food_form_not_ingredient(title, leaf):
    result = classify_record(_raw("costco", "고기", title))
    assert result["unified_category_id"] == leaf
    assert result["evidence_type"] == "audited_costco_meat_shelf_title"
    assert classify_record(_raw("costco", "고기", title + " 혼합세트"))["unified_category_id"] != leaf
    assert classify_record(_raw("costco", "커피", title))["unified_category_id"] != leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", [
    "안방그릴 울트라 AB1107CO", "오크우드 장작 15kg",
    "하림 더리얼 밀 냉동 화식 닭고기 60g x 10",
    "하림 더리얼 밀 그레인프리 냉동 화식 닭고기 60g x 10",
    "부추고기순대500Gx3 족발슬라이스 960g",
    "설성목장 한우불고기 덮밥소스100g x 8",
])
def test_meat_shelf_contaminants_and_mixed_sets_stay_pending(title):
    assert classify_record(_raw("costco", "고기", title))["unified_category_id"] == _REVIEWED_LEDGER001.get(('고기', title))


@pytest.mark.parametrize("title", [
    "수박2호 ( 6KG 미만 )", "허니듀 & 머스크 멜론 세트 4입 (각 2입)",
    "샤인머스캣 애플망고 사과 혼합선물세트4.6kg", "휴롬 원액기 P310 E31ST-BFM02MM",
])
def test_fruit_shelf_does_not_prove_a_single_fixed_product(title):
    assert classify_record(_raw("costco", "과일", title))["unified_category_id"] == _REVIEWED_LEDGER001.get(('과일', title))


def test_audited_costco_cheese_shelf_keeps_shredded_pizza_cheese_as_cheese():
    result = classify_record(_raw("costco", "치즈", "소와나무 이태리안 피자치즈 1kg x 3"))
    assert result["unified_category_id"] == "food.dairy.cheese.shredded"


@pytest.mark.parametrize(("title", "leaf"), [
    ("소화잘되는 배안아픈저지방우유 (900ml*2)", "food.dairy.milk.plain"),
    ("서울 A2플러스우유 710ml", "food.dairy.milk.plain"),
    ("유기농우유 900ml", "food.dairy.milk.plain"),
    ("후레쉬 밀크 기획(900ml*2) 1800ml", "food.dairy.milk.plain"),
    ("바나나맛우유 무가당(240ml*4입)", "food.dairy.milk.banana"),
    ("필라델피아 크림치즈190g", "food.dairy.cheese.cream"),
    ("생크림500ml", "food.dairy.cream.fresh"),
    ("버터450g(해동)", "food.dairy.cheese.butter"),
    ("상하 프로틴치즈 라이트 슬라이스15매", "food.dairy.cheese.sliced"),
    ("모짜렐라 슈레드치즈800g", "food.dairy.cheese.shredded"),
    ("상하 프로틴 스트링치즈200g", "food.dairy.cheese.string"),
    ("덴마크 후레쉬 모짜렐라 미니125g", "food.dairy.cheese.fresh_mozzarella"),
    ("보꼬네 올리브오일 모짜렐라 보코치니200g", "food.dairy.cheese.fresh_mozzarella"),
    ("덴마크 후레쉬 리코타150g", "food.dairy.cheese.ricotta"),
    ("덴마크 드링킹요구르트 딸기275ml", "food.dairy.yogurt.drink"),
    ("상하 그릭요거트 무가당80g*4", "food.dairy.yogurt.greek"),
    ("검은콩 블랙9곡두유190ml*16", "food.plant.soy.soymilk"),
])
def test_reviewed_emart_dairy_compound_titles_require_compatible_context(title, leaf):
    result = classify_record(_raw("emart", "우유/유제품", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.80
    assert len(result["category_path"]) == 4


@pytest.mark.parametrize(("title", "section", "leaf"), [
    ("연세우유소화가잘되는멸균우유190mlx24", "Beverages/Soy-MilkMilk", "food.dairy.milk.plain"),
    ("연세 말차라떼 멸균우유190ml x24", "Beverages/Soy-MilkMilk", "food.dairy.milk.matcha"),
    ("매일유업 Arla 크림치즈 플레인150gx6", "Chilled-Foods/Chilled-Foods", "food.dairy.cheese.cream"),
    ("RoyalOrange 에멘탈 슬라이스150gx3", "Chilled-Foods/CheeseButter", "food.dairy.cheese.sliced"),
    ("커클랜드 쉬레드파마지아노레지아노500gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.shredded"),
    ("Zanetti리코타250gx3", "Chilled-Foods/CheeseButter", "food.dairy.cheese.ricotta"),
    ("Zanetti 마스카르포네500gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.mascarpone"),
    ("커클랜드 Isigny 브리600gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.brie"),
    ("일드프랑스 미니까망베르25gx10x4", "Chilled-Foods/CheeseButter", "food.dairy.cheese.camembert"),
    ("Rabel만체고트러플200gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.hard_aged"),
    ("EuroPomella 냉동부라타치즈100gx8", "Frozen-Foods/Instant-FoodDumplingTraditional-PancakesCheese", "food.dairy.cheese.burrata"),
    ("코우카키스딸기그릭요거트150gx6", "Chilled-Foods/Chilled-Foods", "food.dairy.yogurt.greek"),
    ("커클랜드 시그니춰아몬드음료946ml x12", "Beverages/Soy-MilkMilk", "food.plant.drinks.almond"),
    ("Blue Diamond 아몬드 브리즈 오리지널190ml x24", "Beverages/Soy-MilkMilk", "food.plant.drinks.almond"),
    ("아몬드 브리즈 프로틴190ml x24 x2", "Beverages/SoftConcentrated-Drinks", "food.plant.drinks.almond"),
    ("연세우리콩두유 검은콩190mlx24", "Beverages/Soy-MilkMilk", "food.plant.soy.soymilk"),
])
def test_reviewed_costco_dairy_uses_official_context_and_explicit_type(title, section, leaf):
    result = classify_record(_raw("costco", "SpecialPriceOffers", title, canonical_url=f"https://www.costco.co.kr/Foods/{section}/Product/p/12345"))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.80


@pytest.mark.parametrize("title", [
    "우유맛과자200g", "초코우유 맛 쿠키200g", "모짜렐라 치즈피자500g",
    "두유 제조기800ml", "가정용 우유 거품기", "그릭요거트 보틀500ml",
    "고마워 치즈야 치즈볼 애견간식", "치즈브림요구르트 애견간식",
    "유기농 우유 반려견 간식", "필라델피아 크림치즈 케이크500g",
    "마스카르포네 파스타소스500g", "스키피땅콩버터크리미462g",
    "인기 치즈/버터 모음전 최대50%행사",
    "서울우유 카페라떼300ml", "연세우유 바닐라딜라이트300ml",
    "할리스 바닐라딜라이트300ml", "커피포리200ml*4입",
    "목장의 신선함이 살아 있는 저지방1L", "1000ml 나100%",
    "윌 오리지날150mlX5개", "비요뜨 초코링", "짜요짜요 딸기맛240g",
    "더 진한 순수 플레인 요거트1.8L", "다논 하루요거트플레인80g*4",
    "소와나무 체다치즈270g", "구워먹는치즈500g", "치즈큐빅파티 플레인87g",
    "오트몬드 오리지널190ml x24", "국산콩 진한 콩국950MLx4",
])
def test_dairy_words_do_not_resolve_non_dairy_or_unspecified_types(title):
    assert classify_record(_raw("emart", "우유/유제품", title))["unified_category_id"] is None


@pytest.mark.parametrize("section", [
    "Fresh-Foods/KimchiSide-Dishes", "Snack/Chocolates-Bars", "Processed-Food/Oils",
    "Processed-Food/SaucesCondiments", "Bread/Bread", "RiceGrains/Rice",
])
def test_dairy_title_does_not_override_a_conflicting_costco_food_url(section):
    result = classify_record(_raw("costco", "우유", "브랜드 그릭요거트 150g", canonical_url=f"https://www.costco.co.kr/Foods/{section}/Product/p/12345"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "dairy_source_context_conflict"


@pytest.mark.parametrize("section", ["Appliances/Blenders", "BabyKidsToysPets/Pet-Supplies/Dog-Foods", "HomeKitchen/Food-Storage"])
def test_costco_nonfood_url_blocks_even_unambiguous_name_token(section):
    result = classify_record(_raw("costco", "치즈", "그릭요거트 150g", canonical_url=f"https://www.costco.co.kr/{section}/Product/p/12345"))
    assert result["unified_category_id"] is None


def test_conflicting_costco_canonical_url_cannot_be_hidden_by_detail_url():
    result = classify_record(_raw("costco", "우유", "그릭요거트 150g", canonical_url="https://www.costco.co.kr/Foods/Fresh-Foods/KimchiSide-Dishes/Product/p/1", detail_url="https://www.costco.co.kr/Foods/Chilled-Foods/Chilled-Foods/Product/p/1"))
    assert result["unified_category_id"] is None


def test_dairy_context_needs_official_url_not_costco_search_label_or_product_slug():
    for url in (None, "https://example.test/Foods/Beverages/Soy-MilkMilk/Product/p/1", "https://www.costco.co.kr/Appliances/Soy-MilkMilk/p/1"):
        assert classify_record(_raw("costco", "우유", "유기농우유900ml", canonical_url=url))["unified_category_id"] is None
    assert classify_record(_raw("costco", "우유", "연세우유 멸균우유200mlx24", canonical_url="https://www.costco.co.kr/Foods/p/1"))["unified_category_id"] == "food.dairy.milk.plain"


def test_dairy_context_does_not_override_specific_source_type_conflict():
    # Reviewed Greek-vs-spoon shelf resolution is covered by
    # test_initial_homeplus_dairy_forms; other conflicts still require review.
    for path, title in (
        ("우유/유제품 > 치즈/버터 > 슬라이스 치즈", "필라델피아 크림치즈190g"),
    ):
        assert classify_record(_raw("homeplus", path, title))["unified_category_id"] is None


def test_explicit_review_only_leaves_do_not_add_loose_name_rules():
    ids = {"food.meals.noodles.glass", "food.bakery.spreads.peanut", "food.seasonings.sauces.black_bean"}
    validate_taxonomy(taxonomy_categories(ids), ids)
    for title in ("오뚜기옛날자른당면1kg", "스키피땅콩버터청크462g", "차오차이짜장소스165g"):
        assert classify_record(_raw("emart", "베스트", title))["unified_category_id"] is None


def test_efficiency_review_forms_are_distinct_and_require_exact_review():
    ids = {
        "food.meat.fresh.duck", "food.drinks.mix.vinegar", "food.drinks.mix.milk_tea",
        "food.snacks.dried.sweet_potato", "food.meals.noodles.milmyeon",
        "food.preserved.sides.cheongpomuk", "food.seafood.processed.salted_squid",
        "food.plant.konjac.food", "food.seafood.sashimi.aged_skate",
        "food.dairy.milk.condensed", "food.seasonings.sauces.chocolate_syrup",
    }
    leaves = {leaf.id: leaf for leaf in LEAVES if leaf.id in ids}
    assert set(leaves) == ids
    assert all(len(leaf.path) == 4 and not leaf.source_labels and not leaf.name_terms for leaf in leaves.values())
    validate_taxonomy(taxonomy_categories(ids), ids)
    for title in ("곤약면", "밀면", "청포묵", "연유", "초콜릿시럽"):
        assert classify_record(_raw("emart", "베스트", title))["unified_category_id"] is None
    for title in ("곤약면과 어묵 혼합세트", "밀면과 냉면 혼합세트"):
        assert classify_record(_raw("emart", "베스트", title))["unified_category_id"] is None


def test_reviewed_produce_leaves_have_four_levels_and_unique_search_keywords():
    paths = {
        "food.produce.fruit.avocado": ["식품", "농산물", "신선과일", "아보카도"],
        "food.produce.fruit.mango": ["식품", "농산물", "신선과일", "망고"],
        "food.produce.fruit.jujube": ["식품", "농산물", "신선과일", "대추"],
        "food.produce.vegetables.scallion": ["식품", "농산물", "신선채소", "대파"],
        "food.produce.vegetables.napa_cabbage": ["식품", "농산물", "신선채소", "배추"],
        "food.produce.processed_vegetables.dried": ["식품", "농산물", "가공채소", "건채소"],
        "food.produce.processed_vegetables.dried_mushroom": ["식품", "농산물", "가공채소", "건버섯"],
        "food.produce.processed_vegetables.frozen": ["식품", "농산물", "가공채소", "냉동채소"],
    }
    categories = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(categories.values(), paths)
    for leaf_id, expected_path in paths.items():
        actual_path = []
        cursor = leaf_id
        while cursor:
            actual_path.insert(0, categories[cursor]["name_ko"])
            cursor = categories[cursor]["parent_id"]
        assert actual_path == expected_path
    keywords = keyword_definitions(paths)
    assert {row["unified_category_id"]: row["word"] for row in keywords} == {
        leaf_id: path[-1] for leaf_id, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize(("path", "title"), [
    ("과일", "페루산 아보카도 1kg (5~6입)"),
    ("과일", "브라질애플망고3.7kg(7~9입)"),
    ("과일", "사과대추 500g 팩"),
    ("채소", "흙대파 750g"), ("채소", "손질배추 (통)"),
    ("채소", "건고사리 200g"), ("채소", "일품채 목이버섯 200g / 최소구매 2"),
    ("채소", "[냉동] 대파 (500g)"), ("채소", "[냉동] 볶음밥용 채소 (500g)"),
    ("채소", "냉동 다진마늘 400g x 3 x 2"),
    ("과일", "애플 & 태국망고 선물세트 2.8kg"),
    ("과일", "샤인머스캣&애플망고세트3.5kg"),
    ("과일", "아보카도 오일 1L"),
    ("채소", "채소 행사전 (대파/배추 등)"),
    ("채소", "뉴트리플랜 동결건조 야채트릿 200g"),
])
def test_new_produce_leaves_do_not_implicitly_classify_unreviewed_listings(path, title):
    result = classify_record(_raw("emart", path, title))
    assert result["unified_category_id"] is None


def test_fresh_napa_cabbage_leaf_does_not_override_existing_kimchi_contract():
    result = classify_record(_raw("emart", "채소", "배추김치 1kg"))
    assert result["unified_category_id"] == "food.preserved.kimchi.cabbage"


def test_prepared_soup_stew_label_covers_the_existing_stew_contract():
    result = classify_record(_raw("homeplus", "라면/즉석식품/통조림 > 즉석식품/누룽지/죽 > 즉석국", "CJ 비비고 두부 듬뿍 된장찌개 460G"))
    assert result["unified_category_id"] == "food.meals.prepared.soup_stew"
    assert result["category_path"] == ["식품", "간편식·면", "조리식품", "국·탕·찌개"]


@pytest.mark.parametrize(("mart", "path", "title", "leaf"), [
    ("homeplus", "우유/유제품 > 치즈/버터 > 슈레드/피자치즈/파마산 > 피자치즈", "매일 쫄깃하게늘어나는 피자용 슈레드치즈75G*4", "food.dairy.cheese.shredded"),
    ("lottemart", "우유ㆍ유제품 > 치즈 > 슈레드ㆍ피자치즈", "덴마크 피자 모짜렐라 치즈300G", "food.dairy.cheese.shredded"),
    ("homeplus", "우유/유제품 > 치즈/버터 > 스트링/과일/스낵치즈 > 구워먹는치즈등", "오뚜기 스트링치즈 플레인20G*10", "food.dairy.cheese.string"),
    ("homeplus", "우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트", "서울우유 생크림 요거트85G*4", "food.dairy.yogurt.spoon"),
    ("lottemart", "우유ㆍ유제품 > 우유 > 바나나ㆍ딸기ㆍ초코ㆍ커피우유 > 바나나우유", "동원 덴마크 바나바나 우유300ML", "food.dairy.milk.banana"),
    ("lottemart", "우유ㆍ유제품 > 우유 > 바나나ㆍ딸기ㆍ초코ㆍ커피우유 > 초코우유", "푸르밀 가나 쵸코우유225ML*4", "food.dairy.milk.chocolate"),
])
def test_contextual_refinement_preserves_valid_dairy_source_contracts(mart, path, title, leaf):
    assert classify_record(_raw(mart, path, title))["unified_category_id"] == leaf


def test_opaque_flavour_in_mixed_milk_source_is_not_defaulted_to_plain_milk():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 딸기/초코/바나나/기타 우유", "브랜드 바나바나 우유300ml"))
    assert result["unified_category_id"] is None


def test_reviewed_chinese_meals_and_sauces_have_separate_leaf_paths():
    paths = {
        'food.meals.prepared.mapo_tofu': ['식품', '간편식·면', '조리식품', '즉석마파두부'],
        'food.seasonings.sauces.mapo_tofu': ['식품', '양념·소스', '조미소스', '마파두부소스'],
        'food.seasonings.sauces.pepper_stir_fry': ['식품', '양념·소스', '조미소스', '고추잡채소스'],
        'food.seasonings.sauces.fish_fragrant': ['식품', '양념·소스', '조미소스', '어향소스'],
    }
    nodes = {r['id']: r for r in taxonomy_categories(paths)}
    validate_taxonomy(nodes.values(), paths)
    for leaf, expected in paths.items():
        actual, cursor = [], leaf
        while cursor:
            actual.insert(0, nodes[cursor]['name_ko'])
            cursor = nodes[cursor]['parent_id']
        assert actual == expected
    assert {r['unified_category_id']: r['word'] for r in keyword_definitions(paths)} == {leaf:path[-1] for leaf,path in paths.items()}
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize('title', ['마파두부 180g', '홍콩식 마파두부소스 150g', '한국풍 마파두부소스 150g', '고추잡채소스 100g', '어향가지소스 100g'])
def test_review_only_chinese_leaves_do_not_create_implicit_title_rules(title):
    assert classify_record(_raw('emart', '밀키트/간편식', title))['unified_category_id'] is None


def test_reviewed_sauce_and_cooking_oil_leaves_have_separate_four_level_paths():
    paths = {
        "food.seasonings.sauces.meat": ["식품", "양념·소스", "조미소스", "고기용소스"],
        "food.seasonings.oils.cooking": ["식품", "양념·소스", "식용유", "요리유"],
    }
    nodes = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(nodes.values(), paths)
    for leaf, expected in paths.items():
        actual = []
        cursor = leaf
        while cursor:
            actual.insert(0, nodes[cursor]["name_ko"])
            cursor = nodes[cursor]["parent_id"]
        assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions(paths)} == {
        leaf: path[-1] for leaf, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("path,title", [
    ("양념/오일", "고기엔 참소스 800g"),
    ("식용유/참기름", "해표 바삭요리유 900ml"),
])
def test_review_only_sauce_and_cooking_oil_leaves_do_not_widen_automatic_rules(path, title):
    assert classify_record(_raw("emart", path, title))["unified_category_id"] is None


def test_reviewed_grain_snack_leaf_has_four_levels_and_a_unique_keyword():
    leaf = "food.snacks.savory.grain"
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == ["식품", "과자·간식", "스낵", "곡물스낵"]
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: "곡물스낵"
    }
    assert keyword_collisions(keyword_definitions()) == {}


def test_review_only_grain_snack_leaf_does_not_widen_automatic_rules():
    assert classify_record(_raw("homeplus", "쌀/곡물 과자", "크라운 죠리퐁 74G"))["unified_category_id"] is None


def test_reviewed_soda_leaf_has_four_levels_and_a_unique_keyword():
    leaf = "food.drinks.water_soda.soda"
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == ["식품", "음료", "생수·탄산", "탄산음료"]
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: "탄산음료"
    }
    assert keyword_collisions(keyword_definitions()) == {}


def test_review_only_soda_leaf_does_not_widen_automatic_rules():
    assert classify_record(_raw("emart", "생수/음료/주류", "맥콜 제로 1.5L"))["unified_category_id"] is None


@pytest.mark.parametrize("leaf,expected", [
    ("food.meals.prepared.pancake", ["식품", "간편식·면", "조리식품", "냉동전"]),
    ("food.seasonings.powders.curry", ["식품", "양념·소스", "분말조미료", "카레가루"]),
])
def test_reviewed_ready_meal_leaves_have_four_levels_and_unique_keywords(leaf, expected):
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: expected[-1]
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("path,title", [
    ("냉동전", "풀무원 철판 오징어김치전 300g"),
    ("카레가루/카레소스", "오뚜기 백세카레 순한맛 100g"),
])
def test_reviewed_ready_meal_leaves_do_not_widen_automatic_rules(path, title):
    assert classify_record(_raw("lottemart", path, title))["unified_category_id"] is None


@pytest.mark.parametrize("leaf,expected", [
    ("food.produce.vegetables.radish", ["식품", "농산물", "신선채소", "무"]),
    ("food.produce.vegetables.zucchini", ["식품", "농산물", "신선채소", "애호박"]),
    ("food.meals.prepared.fried_shrimp", ["식품", "간편식·면", "조리식품", "새우튀김"]),
    ("food.preserved.sides.stir_fried", ["식품", "반찬·저장식품", "밑반찬", "볶음반찬"]),
])
def test_reviewed_remaining_exact_leaves_have_four_levels(leaf, expected):
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual, cursor = [], leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == expected
    keywords = {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})}
    if leaf.endswith(".radish"):
        assert keywords == {}  # 한 글자 '무'는 무가당/무염 오탐 때문에 자동 키워드로 쓰지 않는다.
    else:
        assert keywords == {leaf: expected[-1]}


@pytest.mark.parametrize("path,title", [
    # Literal fresh 애호박 now has the bounded crop/context rule below;
    # a vegetable promotion still cannot create an unspecified crop leaf.
    ("채소", "무 (개)"), ("채소", "채소 특가"),
    ("기타튀김", "사세 바삭 튀긴 통새우튀김 300g"),
    ("볶음반찬", "샘표 오징어채볶음 60g"),
])
def test_reviewed_remaining_exact_leaves_do_not_widen_automatic_rules(path, title):
    result = classify_record(_raw("lottemart", path, title))["unified_category_id"]
    assert result not in {
        "food.produce.vegetables.radish", "food.produce.vegetables.zucchini",
        "food.meals.prepared.fried_shrimp", "food.preserved.sides.stir_fried",
    }


def test_reviewed_grain_leaves_have_independent_four_level_paths_and_keywords():
    labels = {"glutinous": "찹쌀", "black": "흑미", "barley": "보리", "millet": "기장", "chickpea": "병아리콩"}
    paths = {f"food.grains.rice.{key}": ["식품", "곡물·견과", "쌀·잡곡", label] for key, label in labels.items()}
    categories = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(categories.values(), paths)
    for leaf, expected in paths.items():
        actual = []
        cursor = leaf
        while cursor:
            actual.insert(0, categories[cursor]["name_ko"])
            cursor = categories[cursor]["parent_id"]
        assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions(paths)} == {
        leaf: path[-1] for leaf, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("title", [
    "국산 찹쌀 5kg", "찰흑미 5kg", "찰보리쌀 4kg", "찰기장쌀 500g", "병아리콩 500g",
    "찹쌀 호떡믹스 400g", "흑미과자 200g", "보리새우 200g", "보리차 500ml", "병아리콩 후무스 200g",
])
def test_review_only_grains_do_not_add_ingredient_based_automatic_assignments(title):
    assert classify_record(_raw("emart", "쌀/잡곡/견과", title))["unified_category_id"] not in {
        f"food.grains.rice.{key}" for key in ("glutinous", "black", "barley", "millet", "chickpea")
    }


@pytest.mark.parametrize("title", [
    "코코넛우유200ml", "아몬드우유200ml", "오트밀크1L", "식물성 우유1L",
    "비건 저지방 우유1L", "식물성 그릭요거트150g", "코코넛그릭요거트150g",
    "비건 슬라이스 치즈200g", "망고우유200ml", "검은콩우유200ml", "밤우유200ml",
])
def test_plant_alternatives_and_unresolved_flavours_are_not_assumed_plain_dairy(title):
    result = classify_record(_raw("emart", "우유/유제품", title))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize('title,leaf', [
    ('귀리음료 두유 대체 1L', 'food.plant.drinks.oat'),
    ('오트음료 두유대용 1L', 'food.plant.drinks.oat'),
    ('아몬드음료 두유 대신 1L', 'food.plant.drinks.almond'),
    ('베지밀 오트밀 두유 190ml', 'food.plant.soy.soymilk'),
    ('아몬드 두유 190ml', 'food.plant.soy.soymilk'),
])
def test_plant_drink_form_does_not_treat_soy_comparisons_as_soy_contents(title, leaf):
    assert classify_record(_raw('homeplus', ['우유/유제품', '두유', '일반두유'], title))['unified_category_id'] == leaf
    assert classify_record(_raw('homeplus', ['가전'], title))['unified_category_id'] is None


@pytest.mark.parametrize('title', [
    '귀리음료 + 두유 190ml', '귀리음료 두유맛 1L',
    '귀리음료 두유 대체 + 다른상품 세트', '귀리음료 + 다른상품 세트',
    '귀리음료 아몬드음료 혼합세트', '두유 대체 음료 1L',
    '귀리음료 두유 대체 제조기', '귀리음료 두유 대체 반려동물용 1L',
    '귀리음료 두유 대체 분말 30g', '귀리음료 두유 대체 농축원액 100ml',
    '아몬드음료 두유 대체 아이스크림 500ml',
])
def test_plant_drink_comparisons_do_not_resolve_mixtures_or_unspecified_forms(title):
    assert classify_record(_raw('homeplus', ['우유/유제품', '두유', '일반두유'], title))['unified_category_id'] is None


def test_literal_oat_drink_needs_compatible_context_and_preserves_url_conflicts(monkeypatch):
    from services import initial_taxonomy as taxonomy
    title = '귀리음료 두유 대체 1L'
    assert classify_record(_raw('emart', '우유/유제품', '귀리음료 1L'))['unified_category_id'] == 'food.plant.drinks.oat'
    assert classify_record(_raw('homeplus', ['우유/유제품', '반려동물'], title))['unified_category_id'] is None
    monkeypatch.setattr(taxonomy, '_url_candidates', lambda evidence: ({'food.plant.soy.soymilk'}, []))
    conflict = classify_record(_raw('homeplus', ['우유/유제품', '두유', '일반두유'], title))
    assert conflict['unified_category_id'] is None
    assert conflict['candidate_category_ids'] == ['food.plant.drinks.oat', 'food.plant.soy.soymilk']


@pytest.mark.parametrize('path,title,leaf', [
    ('국내산소고기', '냉동 한우 양지 500g', 'food.meat.frozen.beef'),
    ('돼지고기', '냉동 삼겹살 500g', 'food.meat.frozen.pork'),
    ('닭고기', '냉동 닭다리 500g', 'food.meat.frozen.chicken'),
    ('국내산소고기', '냉장 한우 양지 500g', 'food.meat.fresh.beef'),
    ('국내산소고기', '한우 양지 500g 냉동 보관 가능', 'food.meat.fresh.beef'),
])
def test_raw_meat_storage_refines_only_the_same_corroborated_species(path, title, leaf):
    result = classify_record(_raw('lottemart', ['정육ㆍ계란', path], title))
    assert result['unified_category_id'] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize('title', [
    '냉동 양념 소고기 500g', '냉동 훈제 닭고기 500g',
    '냉동 소고기 만두 500g', '냉동 돼지고기 소고기 혼합 500g',
    '강아지 냉동 닭고기 500g', '냉동 LA갈비 500g',
])
def test_frozen_storage_does_not_establish_raw_species_or_erase_other_forms(title):
    result = classify_record(_raw('lottemart', ['정육ㆍ계란', '국내산소고기'], title))
    assert not (result['unified_category_id'] or '').startswith('food.meat.frozen.')


@pytest.mark.parametrize('shelf,title,expected', [
    ('애호박','새산지 애호박 2입','food.produce.vegetables.zucchini'),
    ('단호박','새산지 단호박 1통','food.produce.vegetables.pumpkin'),
    ('호박','호박죽용 단호박 1통','food.produce.vegetables.pumpkin'),
    ('애호박','애호박 퓨레 100g',None),
    ('단호박','단호박 가루 100g',None),
    ('호박','호박즙 100ml',None),
    ('애호박','냉동 애호박 200g',None),
    ('호박','호박씨앗 100g',None),
    ('호박','호박잎 200g',None),
])
def test_specific_fresh_squash_aliases_do_not_accept_processed_forms(shelf,title,expected):
    actual=classify_record({'source':'homeplus','name':title,'attributes':{'category_path':['채소',shelf]}})
    assert actual['unified_category_id'] == expected
    if expected is None:
        assert actual['classification_reason'] == 'source_title_product_type_conflict'


@pytest.mark.parametrize('path,title,expected', [
    (['채소'], '새산지 애호박 2입', 'food.produce.vegetables.zucchini'),
    (['채소','오이/가지/호박/옥수수','호박'], '새산지 애호박 2입', 'food.produce.vegetables.zucchini'),
    (['채소','호박'], '새산지 애호박(국산/1개)', 'food.produce.vegetables.zucchini'),
    (['채소'], '새산지 미니단호박 1통', 'food.produce.vegetables.pumpkin'),
    (['채소','단호박'], '새산지 애호박 2입', None),
    (['채소','애호박'], '새산지 단호박 1통', None),
    (['채소','호박'], '애호박과 단호박', None),
    (['채소','호박'], '애호박/오이', None),
    (['채소','호박'], '애호박 모둠 채소', None),
    (['채소','호박'], '애호박 밀키트 200g', None),
    (['채소','호박'], '애호박 된장찌개 200g', None),
    (['채소','호박'], '단호박 식빵 200g', None),
    (['채소','호박'], '호박죽 용 단호박 1통', 'food.produce.vegetables.pumpkin'),
    (['채소'], '애호박 퓨레 100g', None),
    (['채소','냉동채소'], '애호박 200g', None),
    (['반려동물'], '애호박 200g', None),
])
def test_fresh_squash_refines_generic_shelves_without_erasing_specific_conflicts(path,title,expected):
    actual=classify_record({'source':'homeplus','name':title,'attributes':{'category_path':path}})
    assert actual['unified_category_id'] == expected
    if expected:
        validate_taxonomy(taxonomy_categories({expected}), {expected})


@pytest.mark.parametrize('title,path,leaf,broad', [
    ('프리시아 메가BBQ 마시멜로우 300G', '과자/시리얼 > 캔디 > 소프트캔디',
     'food.snacks.sweets.marshmallow', 'food.snacks.sweets.candy'),
    ('Senoble 크렘브륄레 100g x 8', '과자',
     'food.snacks.desserts.creme_brulee', 'food.snacks.sweets.pudding'),
    ('종합 모나카 840g / 280g X 3', '과자',
     'food.snacks.traditional.monaka', 'food.snacks.traditional.hangwa'),
    ('Dorly 오란다 720g / 20g x 36', '과자',
     'food.snacks.traditional.oranda', 'food.snacks.traditional.hangwa'),
    ('엠앤엠즈 유리컵 기획팩 레드 145G', '과자/시리얼 > 초콜릿 > 볼초콜릿',
     'food.snacks.sets.chocolate_glass', 'food.snacks.sweets.chocolate'),
])
def test_literal_confection_form_refines_only_related_leaf_and_keeps_url_conflicts(
        title, path, leaf, broad, monkeypatch):
    from services import initial_taxonomy as taxonomy
    row = _raw('homeplus', path, title)
    result = classify_record(row)
    assert result['unified_category_id'] == leaf
    assert result['evidence_type'] == 'literal_confection_product_form_and_context'
    assert 'package_quantity' not in result
    assert classify_record(_raw('homeplus', ['다른 상품'], title))['unified_category_id'] is None
    monkeypatch.setattr(taxonomy, '_url_candidates', lambda evidence: ({broad}, []))
    conflict = classify_record(row)
    assert conflict['unified_category_id'] is None
    assert set(conflict['candidate_category_ids']) == {leaf, broad}


@pytest.mark.parametrize('title', [
    '마시멜로우맛 쿠키 300g', '크렘브륄레맛 아이스크림 100g',
    '모나카 만들기 믹스 280g', '오란다맛 과자 160g',
    '빈 유리컵 기획팩 레드 145g', '마시멜로우 반려동물 간식',
])
def test_confection_flavour_kits_and_empty_gifts_do_not_establish_literal_form(title):
    from services.initial_product_forms import confection_form_refinement
    evidence = source_evidence(_raw('homeplus', '과자/시리얼 > 초콜릿 > 캔디', title))
    assert confection_form_refinement(evidence) == (set(), set())


@pytest.mark.parametrize('title,native,leaf', [
    ('포스트 오레오 오즈 (500G)', '8801037065626', 'food.snacks.cereal.rings'),
    ('포스트 오곡코코볼 컵 시리얼 (30G)', '8801037096569', 'food.snacks.cereal.balls'),
])
def test_reviewed_native_cereal_shape_does_not_transfer_flavour_package_or_context(title, native, leaf):
    from services.initial_product_forms import reviewed_cereal_form_refinement
    url = 'https://lottemartzetta.com/products/OS' + native + '/details'
    row = {'source_name':'lottemart', 'source_title':title,
           'source_category_path':['과자ㆍ스낵ㆍ간식','시리얼','후레이크'], 'source_url':url}
    result = classify_record(row)
    assert result['unified_category_id'] == leaf
    assert result['evidence_type'] == 'reviewed_native_package_cereal_shape'
    assert 'package_quantity' not in result
    for change in ({'source_url':url+'-other'}, {'source_title':title.replace('G)', 'G) 맛 쿠키')},
                   {'source_category_path':['다른 상품']}, {'source_name':'homeplus'},
                   {'source_url':None}):
        assert reviewed_cereal_form_refinement(source_evidence({**row, **change})) == (set(), set())


@pytest.mark.parametrize('title,path,leaf', [
    ('커클랜드 시그니춰 토티야 칩스 1.13kg', '과자', 'food.snacks.savory.tortilla_nacho'),
    ('리코스 나쵸칩 454G', '과자/시리얼 > 나쵸', 'food.snacks.savory.tortilla_nacho'),
    ('크라운 카라멜콘과땅콩 72G', '과자/시리얼 > 옥수수스낵', 'food.snacks.assortments.corn_peanut'),
    ('우리식품 마카로니 스낵 160G', '과자/시리얼 > 기타곡물스낵', 'food.snacks.savory.noodle'),
    ('검정고무신 왕라면스낵 160G', '과자/시리얼 > 유탕과자', 'food.snacks.savory.noodle'),
    ('그린피스 와사비스낵 380G', '과자/시리얼 > 기타곡물스낵', 'food.snacks.savory.beans_peas'),
    ('바싹콩콩 서리태 스낵 650G', '과자', 'food.snacks.savory.beans_peas'),
    ('AMANOYA 쌀 크래커 600g / 25g x 24', '과자', 'food.snacks.savory.rice_cracker'),
])
def test_savory_preparation_refines_material_without_inventing_recipe_or_quantity(title, path, leaf, monkeypatch):
    import services.initial_taxonomy as taxonomy
    row = _raw('homeplus', path, title)
    result = classify_record(row)
    assert result['unified_category_id'] == leaf
    assert result['evidence_type'] == 'explicit_savory_preparation_and_context'
    assert 'package_quantity' not in result
    monkeypatch.setattr(taxonomy, '_url_candidates', lambda evidence: ({'food.dairy.milk.chocolate'}, []))
    assert classify_record(row)['unified_category_id'] is None


@pytest.mark.parametrize('title', [
    '오리온 치킨팝 닭강정맛 (65G)', '롯데 꼬깔콘 매콤달콤한맛 (52G)',
    '나초치즈맛 감자칩 100g', '서리태맛 밀가루스낵 100g', '누룽지팝 달콤한맛 288G',
    '나초 만들기 소스 100g', '강아지 라면스낵 100g',
    'simplus 누룽지사탕 200G', 'CJ 햇반 누룽지닭백숙죽 (267G)',
])
def test_savory_native_shelf_and_flavour_are_not_physical_form_or_base(title):
    from services.initial_product_forms import savory_form_refinement
    assert savory_form_refinement(source_evidence(_raw('lottemart', '과자 > 나쵸', title))) == (set(), set())


def test_puffed_native_url_form_never_transfers_package_or_to_other_source():
    from services.initial_product_forms import savory_form_refinement
    row = _raw('costco', '과자', '베베쿡 처음먹는 빼빼롱뻥 30g x 10')
    row['source_url'] = 'https://www.costco.co.kr/Foods/Snack/CookieCracker/Bebecook-First-Puffed-Stick-Snack-30g-x-10/p/689543'
    assert classify_record(row)['unified_category_id'] == 'food.snacks.savory.puffed'
    for changed in ({'source_url':None}, {'source_url':row['source_url'].replace('costco.co.kr','other.test')}):
        assert savory_form_refinement(source_evidence({**row, **changed})) == (set(), set())
    wrong_context = _raw('costco', '다른 상품', '베베쿡 처음먹는 빼빼롱뻥 30g x 10')
    wrong_context['source_url'] = row['source_url']
    assert savory_form_refinement(source_evidence(wrong_context)) == (set(), set())


def test_reviewed_native_snack_form_preserves_price_independence_and_context_boundary():
    from services.initial_product_forms import reviewed_native_snack_form_refinement
    title = '오뚜기 뿌셔뿌셔 불고기맛 1.52kg / 95g x 16'
    url = 'https://www.costco.co.kr/Foods/Snack/CookieCracker/Ottogi-Pusho-Pusho-Bulgogi-flavor-152kg-95g-x16/p/610710'
    row = {'source_name':'costco','source_title':title,'source_category_path':['라면'],'source_url':url}
    for price in (13990,15990,None):
        actual = classify_record({**row,'sale_price':price})
        assert actual['unified_category_id'] == 'food.snacks.savory.noodle'
        assert actual['evidence_type'] == 'reviewed_native_snack_physical_form'
        assert 'package_quantity' not in actual
    for change in ({'source_url':None},{'source_url':url+'-other'},
                   {'source_url':url.replace('610710','637021')},
                   {'source_title':title+' 만들기 재료'}, {'source_title':title.replace('불고기','떡볶이')},
                   {'source_title':title.replace('95g x 16','95g x 20')},
                   {'source_name':'homeplus'}, {'source_category_path':['다른 상품']}):
        assert reviewed_native_snack_form_refinement(source_evidence({**row,**change})) == (set(),set())
    # The stale bare/shelf-only legacy label cannot acquire the captured native form.
    bare = classify_record({'source_name':'costco','source_title':title,'source_category_path':['라면']})
    assert bare['unified_category_id'] == 'food.snacks.savory.wheat'


@pytest.mark.parametrize('title,path,leaf', [
    ('리퀴드 아이비 전해질드링크 파우더 믹스 16g x 30','음료','food.drinks.powders.electrolyte'),
    ('델몬트 스퀴즈 사과/오렌지 에이드 240ml x 30 x 2팩','음료','food.drinks.juice.fruit_ade'),
    ('푸르밀 웰치 사과 에이드 250ML','우유/유제품 > 냉장디저트/음료 > 냉장주스 > 냉장주스','food.drinks.juice.fruit_ade'),
    ('팔도 뽀로로 딸기맛 235ML','생수/음료/주류 > 과일/야채음료 > 어린이음료 > 어린이음료','food.drinks.flavoured.strawberry'),
    ('자임 비타민이 들어있는 사과당근 착즙주스 245ML','우유/유제품 > 냉장디저트/음료 > 냉장주스 > 냉장주스','food.drinks.juice.fruit_vegetable'),
    ('[매일유업] 썬업 100% 과즙 파인애플 750mL','생수/음료/주류','food.drinks.juice.fruit'),
])
def test_literal_beverage_form_refines_broad_leaf_without_ingredient_or_amount_defaults(title,path,leaf):
    actual = classify_record(_raw('costco' if path=='음료' else ('homeplus' if path.startswith('우유/') or '어린이' in path else 'emart'),path,title))
    assert actual['unified_category_id'] == leaf
    assert 'package_quantity' not in actual


@pytest.mark.parametrize('title,path',[
    ('사과 에이드 분말 100g','음료'), ('사과맛 에이드 250ml','음료'),
    ('사과 에이드 250ml','생수/음료/주류 > 농축액'), ('사과 에이드 원액 250ml','음료'),
    ('딸기맛 우유 235ml','생수/음료/주류 > 과일/야채음료 > 어린이음료'),
    ('딸기맛 젤리 235g','생수/음료/주류 > 과일/야채음료 > 어린이음료'),
    ('전해질드링크 500ml','음료'), ('전해질분말 시약 16g','음료'),
    ('사과당근맛 주스 250ml','음료'), ('사과당근 착즙주스 파우더 20g','음료'),
    ('100% 과즙 파인애플 농축액 250ml','음료'), ('100% 과즙 파인애플 250ml','분말/농축액'),
])
def test_beverage_forms_reject_flavour_ingredient_concentrate_and_unrelated_context(title,path):
    from services.initial_product_forms import beverage_form_refinement
    assert beverage_form_refinement(source_evidence(_raw('costco',path,title))) == (set(),set())


@pytest.mark.parametrize('title,path,leaf',[
    ('CJ 더건강한 닭가슴살 소시지 청양고추 (80G)','햄ㆍ어묵ㆍ맛살ㆍ닭가슴살 > 닭가슴살 > 닭가슴살','food.meat.processed.sausage'),
    ('CJ 더건강한 부드러운 닭가슴살 샌드위치햄 (90G)','햄ㆍ어묵ㆍ맛살ㆍ닭가슴살 > 닭가슴살 > 닭가슴살','food.meat.processed.ham'),
    ('진주햄 천하장사 오리지날 (448G)','햄ㆍ어묵ㆍ맛살ㆍ닭가슴살 > 햄ㆍ소시지ㆍ베이컨ㆍ하몽 > 간식용소시지','food.snacks.savory.snack_sausage'),
    ('갓 튀김 어포 900g (60g x 15봉)','과자','food.seafood.processed.fish_snack'),
    ('정화 쥐포튀김 120G','수산물/건어물 > 건오징어/건어물/다시팩 > 쥐포/어포/육포 > 어포','food.seafood.processed.fish_snack'),
    ('촉촉한 반건조 열빙어1.2kg X 2pack','생선','food.seafood.processed.semi_dried_fish'),
])
def test_declared_processed_food_shape_refines_ingredients_and_drying(title,path,leaf):
    result = classify_record(_raw('costco' if path in {'과자','생선'} else ('homeplus' if path.startswith('수산물/') else 'lottemart'),path,title))
    assert result['unified_category_id'] == leaf
    assert 'package_quantity' not in result


@pytest.mark.parametrize('title,path',[
    ('닭가슴살 소시지 만들기 재료','닭가슴살'),
    ('천하장사 콰트로 치즈 25g','치즈'),
    ('강아지 간식소시지 100g','과자'),
    ('반건조 홍시 100g','생선'),
    ('반건조 생선 조림 밀키트','생선'),
    ('어포튀김 소스 혼합세트','과자'),
])
def test_processed_shapes_do_not_guess_species_recipe_or_unrelated_form(title,path):
    from services.initial_product_forms import processed_food_form_refinement
    assert processed_food_form_refinement(source_evidence(_raw('costco',path,title))) == (set(),set())


@pytest.mark.parametrize('title,path,url,leaf,helper_name',[
    ('루카스나인 우베라떼 18g x 50','커피','https://www.costco.co.kr/Foods/CoffeeTeaDrink/Instant-Coffee/Lookas9-Ube-Latte-18g-x-50/p/695490','food.drinks.powders.ube_latte','reviewed_native_drink_form_refinement'),
    ('천하장사 더블링 콰트로치즈 25g X 40','치즈','https://www.costco.co.kr/Foods/Processed-Food/Instant-Food/Double-Ring-Quattro-Cheese-25g-X-40/p/691985','food.seafood.processed.fish_sausage','reviewed_native_processed_form_refinement'),
])
def test_reviewed_native_body_form_retains_price_independence_and_exact_source_boundary(title,path,url,leaf,helper_name):
    from services import initial_product_forms
    helper = getattr(initial_product_forms,helper_name)
    row = {'source_name':'costco','source_title':title,'source_category_path':[path],'source_url':url}
    for price in (13490,15490,None):
        result = classify_record({**row,'sale_price':price})
        assert result['unified_category_id'] == leaf
        assert 'package_quantity' not in result
    for change in ({'source_url':None},{'source_url':url+'-other'},
                   {'source_url':url.replace('/p/','/p/0')},
                   {'source_title':title+' 만들기 재료'}, {'source_title':title.replace('50','51').replace('40','41')},
                   {'source_name':'homeplus'}, {'source_category_path':['다른 상품']}):
        assert helper(source_evidence({**row,**change})) == (set(),set())
    assert classify_record({**row,'source_url':None})['unified_category_id'] != leaf


def test_native_ricecake_fishcake_kit_keeps_separate_components_and_exact_native_context():
    from services.initial_product_forms import reviewed_native_processed_form_refinement
    row = {'source_name':'homeplus', 'source_title':'환공어묵 부산명품 물떡 어묵꼬치 10입 460G',
           'source_category_path':['두부/김치/반찬','어묵/맛살/단무지','어묵','국탕용어묵'],
           'source_url':'https://mfront.homeplus.co.kr/item?itemNo=069798234&storeType=HYPER'}
    for price in (9990,10990,None):
        assert classify_record({**row,'sale_price':price})['unified_category_id'] == 'food.meals.sets.ricecake_fishcake'
    for change in ({'source_url':None}, {'source_url':row['source_url'].replace('069798234','069798235')},
                   {'source_name':'costco'}, {'source_category_path':['다른 상품']},
                   {'source_title':row['source_title'].replace('460G','4600G')}):
        assert reviewed_native_processed_form_refinement(source_evidence({**row,**change})) == (set(),set())


def test_explicit_stock_tablets_refine_cooking_ingredient_without_soup_or_quantity_guesses():
    from services.initial_audited_seasonings import stock_tablet_form_refinement
    for title, leaf in [('오늘좋은 코인육수 멸치디포리 (80G)', 'stock_seasoning'),
                        ('샘표 연두링 다시마표고야채 (80G)', 'vegetable_tablet')]:
        row = _raw('lottemart', '양념ㆍ오일ㆍ분말류', title)
        assert classify_record(row)['unified_category_id'] == 'food.seasonings.stock.' + leaf
        # Unrelated source contexts and other explicit product forms are retained.
        for changed_title in (title + ' 혼합세트', '설성목장 한우사골 곰탕 스틱 14g x10 x4'):
            evidence = source_evidence(_raw('lottemart', '양념ㆍ오일ㆍ분말류', changed_title))
            assert stock_tablet_form_refinement(evidence) == (set(), set())
        assert stock_tablet_form_refinement(source_evidence(_raw('lottemart', '과자', title))) == (set(), set())


def test_literal_portable_screen_form_preserves_unspecified_technology_and_accessory_boundary():
    leaf = 'electronics.video.screens.portable'
    for title, context in [('포터블스크린 카드할인 구매찬스', '오반장'),
                           ('포터블 스크린', '디지털')]:
        for price in (499000, 509000, None):
            result = classify_record({**_raw('emart', context, title), 'sale_price': price})
            assert result['unified_category_id'] == leaf
            assert result['category_path'] == ['디지털', '영상가전', '스크린', '포터블스크린']
    for title, context in [('포터블스크린 커버', '디지털'),
                           ('포터블스크린 + TV 혼합세트', '디지털'),
                           ('포터블스크린 프로젝터 세트', '디지털'),
                           ('포터블스크린', '문구'), ('카드할인 구매찬스', '오반장')]:
        assert classify_record(_raw('emart', context, title))['unified_category_id'] != leaf
    # Classification and search do not infer tuner, panel technology or a sold count.
    definitions = keyword_definitions([leaf])
    assert definitions == [{'word': '포터블스크린', 'synonyms': [], 'unified_category_id': leaf}]
    validate_taxonomy(taxonomy_categories([leaf]), [leaf])
