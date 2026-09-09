import pytest
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy

@pytest.mark.parametrize("path,title,leaf", [
    ("햄/소시지 > 비엔나/후랑크/동그랑땡", "동원 스페셜 후랑크 250G*2", "food.meat.processed.sausage"),
    ("햄/소시지 > 닭가슴살/훈제오리", "하림 닭가슴살 갈릭 100G", "food.meat.processed.breast"),
    ("반찬/젓갈 > 조림/볶음/기타반찬류", "씨제이 비비고 고등어 구이 60G", "food.meals.prepared.grilled_fish"),
    ("반찬/젓갈 > 조림/볶음/기타반찬류", "콩조림 100G", "food.preserved.sides.braised"),
    ("반찬/젓갈 > 조림/볶음/기타반찬류", "깻잎 장아찌 110G", "food.preserved.sides.pickled"),
    ("반찬/젓갈 > 조림/볶음/기타반찬류", "무말랭이 120G", "food.preserved.sides.seasoned"),
])
def test_form_and_full_shelf_are_required(path,title,leaf):
    row={"source_name":"homeplus","source_title":title,"source_category_path":["두부/김치/반찬",*path.split(" > ")]}
    assert classify_record(row)["unified_category_id"]==leaf
    validate_taxonomy(taxonomy_categories({leaf}),{leaf})
    assert classify_record({**row,"source_title":title+" 혼합세트"})["evidence_type"]!="reviewed_homeplus_shelf_and_form"
    assert classify_record({**row,"source_name":"emart"})["evidence_type"]!="reviewed_homeplus_shelf_and_form"

@pytest.mark.parametrize("title",["씨제이 맥스봉 숯불구이맛 핫바 70G","동그랑땡 300G","소시지 소스 300G"])
def test_sausage_shelf_does_not_prove_sausage(title):
    row={"source_name":"homeplus","source_title":title,"source_category_path":["두부/김치/반찬","햄/소시지","비엔나/후랑크/동그랑땡"]}
    assert classify_record(row)["unified_category_id"] is None
