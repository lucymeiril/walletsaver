import pytest
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy

@pytest.mark.parametrize("path,title,leaf", [
    ("김치/반찬/델리","파김치 300g","food.preserved.kimchi.green_onion"),
    ("김치/반찬/델리","[키친델리] 초이스초밥 (20입)","food.meals.prepared.sushi"),
    ("김치/반찬/델리","참치마요 김밥 240g","food.meals.prepared.kimbap"),
    ("김치/반찬/델리","에그 포테이토 샐러드 500g","food.meals.prepared.salad"),
    ("수산물/건해산","[냉동][미국] 연어 스테이크 (600g/팩)","food.seafood.fish.salmon"),
    ("수산물/건해산","[냉동][국산] 손질 가자미 (500g) (소금간)","food.seafood.fish.flounder"),
    ("정육/계란류","[냉동/미국산] 우삼겹 바로구이 (1kg)","food.meat.fresh.beef"),
])
def test_reviewed_fresh_and_deli_form(path,title,leaf):
    row={"source_name":"emart","source_category_path":[path],"source_title":title}
    assert classify_record(row)["unified_category_id"]==leaf
    validate_taxonomy(taxonomy_categories({leaf}),{leaf})
    assert classify_record({**row,"source_name":"costco"})["evidence_type"]!="reviewed_emart_fresh_and_deli"

@pytest.mark.parametrize("title",["건조 황태채 ~20%","싱싱 생선회&조개류 ~50%할인","[냉동] 해물모둠 600g","[활][국산] 활 전복 (특)(100g 단위 판매)"])
def test_uncertain_or_variable_fish_listings_stay_pending(title):
    assert classify_record({"source_name":"emart","source_category_path":["수산물/건해산"],"source_title":title})["unified_category_id"] is None

@pytest.mark.parametrize("title",["(~50%) 한우 구이,국거리,불고기 등","(농할 20% 쿠폰 다운로드) 한우 국거리/불고기 등"])
def test_meat_promotion_without_specific_listing_stays_pending(title):
    assert classify_record({"source_name":"emart","source_category_path":["정육/계란류"],"source_title":title})["unified_category_id"] is None
