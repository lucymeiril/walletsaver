import pytest
from services.initial_product_forms import FORM_RULES, product_form_candidates
from services.initial_taxonomy import classify_record,taxonomy_categories,validate_taxonomy

CASES = [
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
 ('정직하개 애견용 소고기 육포 1kg','과자'),('오리고기 육포스틱','반려동물'),
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
 ('레몬청과 유자차 혼합 세트','커피/차 > 전통차/액상차/꿀 > 유자차'),
 ('한라봉차 탄산 주스','커피/차 > 전통차/액상차/꿀 > 유자차'),
])
def test_nonfood_ingredients_and_mixed_products_are_excluded(title,path):
    assert product_form_candidates({'source_title':title,'source_path_parts':[path]})==set()

def test_registry_depth_and_unique_ids():
    assert len({r[0] for r in FORM_RULES})==len(FORM_RULES)==len(CASES)
    validate_taxonomy(taxonomy_categories(),{r[0] for r in FORM_RULES})

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
