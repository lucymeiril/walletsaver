import pytest
from services.initial_product_forms import FORM_RULES, product_form_candidates
from services.initial_taxonomy import classify_record,taxonomy_categories,validate_taxonomy

CASES = [
 ('몰리스픽 전연령 반려묘사료 15KG','반려동물','pet.food.feed.cat'),
 ('몰리스픽 전연령 반려견 사료 15kg','반려동물','pet.food.feed.dog'),
 ('풀무원아미오 건강담은 칠면조육포50g','반려동물','pet.food.treats.chew'),
 ('챠오 츄르 참치 4개입','반려동물','pet.food.treats.creamy'),
 ('건강한간식 순살듬뿍 안심오리 300g','반려동물','pet.food.treats.meat'),
 ('아미오 자연담은 간식 채소쏙쏙 두부봉 (17g x 6ea)','반려동물','pet.food.treats.tofu'),
 ('국민 두부 고양이 모래(녹차) 7L','반려동물','pet.cat.hygiene.litter'),
 ('배변패드(특대)75*90cm*24매','반려동물','pet.hygiene.waste.pads'),
 ('종이컵180ml*50개','주방용품','household.kitchen.consumables.paper_cup'),
 ('커피필터(100매) #2','주방용품','household.kitchen.consumables.coffee_filter'),
 ('싱크대거름망 100매(대)','주방용품','household.kitchen.consumables.drain_net'),
 ('나무젓가락 80P','주방용품','household.kitchen.consumables.chopsticks'),
 ('컬러풀주방가위_SBLU','주방용품','household.kitchen.utensils.scissors'),
 ('실리콘 뒤집개 민트','주방용품','household.kitchen.utensils.turner'),
 ('스타 사각 채칼','주방용품','household.kitchen.utensils.slicer'),
 ('몽블랑 IH 에칭 궁중팬 28cm','주방용품','household.kitchen.cookware.wok'),
 ('에어프라이어 종이호일 24cm*60매','주방용품','household.kitchen.consumables.baking_paper'),
 ('하루하나 유기농 레몬즙 480ML','커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액','food.drinks.bases.lemon'),
 ('비타민 레몬 티앤에이드 680G','커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액','food.drinks.bases.tea_ade'),
 ('simplus 생강레몬청 1KG','커피/차 > 전통차/액상차/꿀 > 유자차','food.drinks.tea.fruit_preserve'),
 ('간편 삼계재료 티백 100G','채소 > 건채소 > 건약재','food.seasonings.cooking_herbs.samgyetang'),
 ('녹차원 깔라만시 100 480G','커피/차 > 액상차/농축액 > 농축액','food.drinks.bases.calamansi'),
 ('고무장갑 2켤레','주방용품','household.kitchen.gloves.rubber'),
 ('니트릴 장갑 100매','주방용품','household.kitchen.gloves.nitrile'),
 ('망사 수세미 6입','주방용품','household.kitchen.cleaning.scourer'),
 ('부직포 행주 8입','주방용품','household.kitchen.cleaning.cloth'),
 ('롱샤워볼 1P','욕실용품','household.bath.accessories.shower_ball'),
 ('때타올 2입','욕실용품','household.bath.accessories.towel'),
 ('데일리 타월 1P','욕실용품','household.bath.textiles.towel'),
 ('뉴롤백 200매','주방용품','household.kitchen.storage.bag'),
 ('가위형 집게','주방용품','household.kitchen.utensils.tongs'),
 ('롯데 자일리톨 86G','과자','food.snacks.sweets.gum'),
 ('코주부 육포 130G','수산물/건어물','food.meat.processed.jerky'),
 ('가마솥 누룽지 2.5KG','곡물가공','food.meals.rice.nurungji'),
 ('종가 깍두기 500G','김치','food.preserved.kimchi.kkakdugi'),
 ('꼬들 단무지 300G','반찬','food.preserved.sides.danmuji'),
 ('홈밀 왕족발 600G','냉장','food.meals.prepared.jokbal'),
 ('롱치즈스틱 400G','냉동','food.meals.prepared.cheese_stick'),
 ('소프트 또띠아 320G','또띠아','food.bakery.bread.tortilla'),
 ('크링클컷 냉동감자 650G','냉동','food.meals.prepared.frozen_potato'),
]

@pytest.mark.parametrize('title,path,leaf',CASES)
def test_explicit_form_requires_both_title_and_context(title,path,leaf):
    evidence={'source_title':title,'source_path_parts':[path]}
    assert product_form_candidates(evidence)=={leaf}
    assert product_form_candidates({**evidence,'source_title':'정체불명 상품'})==set()
    assert product_form_candidates({**evidence,'source_path_parts':['무관한 매대']})==set()
    validate_taxonomy(taxonomy_categories({leaf}),{leaf})

@pytest.mark.parametrize('title,path',[
 ('정직하개 애견용 소고기 육포 1kg','과자'),
 ('누룽지차 100티백','곡물가공'),('누룽지 삼계재료','곡물가공'),
 ('수세미즙','주방용품'),('행주 전용비누','주방용품'),
 ('샤워볼 워시 세트','욕실용품'),('빨래집게','주방용품'),
 ('또띠아 칩','빵'),('족발 소스','냉장'),('강아지 껌','과자'),
 ('김밥용 단무지와 우엉 250G','단무지'),('하선정치자단무지와우엉 220G','반찬'),
 ('찹쌀 누룽지 품은 삼계재료 220G','건채소 > 건약재'),
 ('삼계재료와 닭 밀키트','건채소 > 건약재'),('완성 삼계탕 1KG','건채소 > 건약재'),
 ('국산 황기 80G','건채소 > 건약재'),
 ('깔라만시 100 에이드 혼합 세트','액상차/농축액 > 농축액'),
 ('하루하나 유기농 레몬즙 480ML','액상차/농축액 > 농축액'),
 ('레몬즙 탄산 에이드 혼합세트','커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액'),
 ('티앤에이드 젤리 사탕','커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액'),
 ('스텐 만능채칼&가위&도마&믹싱볼 외 BEST 주방용품 특가','주방용품'),
 ('커피 필터 머신 세트','주방용품'),('궁중팬 뚜껑 세트','주방용품'),
 ('도시락 일회용 젓가락 세트','주방용품'),('에어프라이어 사각종이호일5L','주방용품'),
 ('레몬청과 유자차 혼합 세트','커피/차 > 전통차/액상차/꿀 > 유자차'),
 ('한라봉차 탄산 주스','커피/차 > 전통차/액상차/꿀 > 유자차'),
])
def test_nonfood_ingredients_and_mixed_products_are_excluded(title,path):
    assert product_form_candidates({'source_title':title,'source_path_parts':[path]})==set()

def test_registry_depth_and_unique_ids():
    assert len({r[0] for r in FORM_RULES})==len(FORM_RULES)==len(CASES)
    validate_taxonomy(taxonomy_categories(),{r[0] for r in FORM_RULES})


@pytest.mark.parametrize('title',[
 '고양이와 강아지 사료 혼합세트', '강아지 고양이 사료',
 '몰리스 프로발란스 어덜트 8kg', '클래식 5kg', '건강한간식 300g',
 '덴탈껌 장난감 혼합 세트', '고양이 모래 간식 세트',
])
def test_pet_forms_do_not_guess_opaque_products_or_accept_mixed_kits(title):
    assert product_form_candidates({'source_title':title,'source_path_parts':['반려동물']}) == set()


@pytest.mark.parametrize('title', ['자연소재 오리고기 육포스틱 460g', '통통닭가슴살225g', '츄잉스틱플레인요거트230g'])
def test_pet_shelf_never_creates_a_human_food_form(title):
    candidates = product_form_candidates({'source_title':title,'source_path_parts':['반려동물']})
    assert all(leaf.startswith('pet.') for leaf in candidates)


def test_pet_jerky_is_pet_chew_not_a_blanket_pet_exclusion():
    assert product_form_candidates({'source_title':'오리고기 육포스틱','source_path_parts':['반려동물']}) == {'pet.food.treats.chew'}

def test_existing_conflicts_are_not_overridden():
    row={'source_name':'homeplus','source_record_key':'071390258',
         'source_title':'동원 포도씨유 참치 150G*2+살코기참치 135G*4',
         'source_category_path':['라면/즉석식품/통조림','통조림','참치']}
    assert classify_record(row)['unified_category_id'] is None

@pytest.mark.parametrize('title',[
 'simplus 한라봉청 1KG','simplus 자몽청 1KG','simplus 레몬청 1KG',
 'simplus 생강레몬청 1KG','자임 비타민들어있는 햇 제주 한라봉차 800G',
])
@pytest.mark.parametrize('duplicate_leaf',[False,True])
def test_homeplus_non_citron_preserves(title,duplicate_leaf):
    path=['커피/차','전통차/액상차/꿀','유자차']+(['유자차'] if duplicate_leaf else [])
    result=classify_record({'source_name':'homeplus','source_title':title,'source_category_path':path})
    assert result['unified_category_id']=='food.drinks.tea.fruit_preserve'
    assert result['classification_confidence']==0.90

@pytest.mark.parametrize('title',[
 '유자차 1KG','레몬청과 유자차 혼합 세트','레몬청 녹차 1KG','정체불명 청 1KG',
])
def test_fruit_preserve_does_not_replace_other_evidence(title):
    result=classify_record({'source_name':'homeplus','source_title':title,
        'source_category_path':['커피/차','전통차/액상차/꿀','유자차']})
    assert result['unified_category_id']!='food.drinks.tea.fruit_preserve'

def test_non_exact_citron_shelf_is_not_overridden():
    result=classify_record({'source_name':'homeplus','source_title':'simplus 레몬청 1KG',
        'source_category_path':['커피/차','전통차/액상차/꿀','유자차','다른 상품']})
    assert result['unified_category_id'] is None

def test_lemon_classification_does_not_invent_contents():
    row={'source_name':'homeplus','source_title':'하루하나 유기농 레몬즙 14T',
        'source_category_path':['커피/차','전통차/액상차/꿀','액상차/농축액','농축액']}
    result=classify_record(row)
    assert result['unified_category_id'] is None
    assert 'package_quantity' not in result
