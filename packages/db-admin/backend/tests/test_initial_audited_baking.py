import pytest
from services.initial_audited_baking import TITLES, reviewed_baking_leaf
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


@pytest.mark.parametrize("title,leaf", TITLES.items())
def test_reviewed_baking_title(title, leaf):
    # Exact title supplies ingredient identity; shelf supplies food context.
    row = {"source_name": "homeplus", "source_category_path": ["장류/양념/제빵", "시럽/제빵믹스", "베이킹재료/기타", "슈가파우더"], "source_title": title}
    assert classify_record(row)["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", ["CJ 백설 알룰로스 분말 400G", "CJ 백설 달콤함그대로 스테비아 400G"])
def test_sweetener_is_not_white_sugar(title):
    result = classify_record({"source_name": "homeplus", "source_category_path": ["장류/양념/제빵", "소금/설탕", "흰설탕"], "source_title": title})
    assert result["unified_category_id"] == TITLES[title]


@pytest.mark.parametrize("mart,path,title", [
    ("emart", ["장류/양념/제빵", "소금/설탕", "흰설탕"], "CJ 백설 알룰로스 분말 400G"),
    ("homeplus", ["세탁/청소", "세탁세제", "기타"], "simplus 베이킹 식소다 150G"),
    ("homeplus", ["장류/양념/제빵", "소금/설탕", "흰설탕"], "CJ 백설 알룰로스 분말 500G"),
])
def test_scope_or_changed_title_requires_review(mart,path,title):
    assert reviewed_baking_leaf({"mart":mart,"source_path_parts":path,"source_title":title}) is None


def test_reviewed_starch_does_not_infer_pure_potato_composition():
    path = ["장류/양념/제빵","밀가루/분말류","밀가루/전분","전분"]
    row = {"source_name":"homeplus", "source_category_path":path, "source_title":"simplus 감자맛 전분 400G"}
    assert classify_record(row)["unified_category_id"] == 'food.seasonings.baking.starch'
    assert classify_record({**row, 'source_category_path':['생활용품']})['unified_category_id'] is None
    assert classify_record({**row, 'source_title':row['source_title']+' + 밀가루 혼합세트'})['unified_category_id'] != 'food.seasonings.baking.starch'
