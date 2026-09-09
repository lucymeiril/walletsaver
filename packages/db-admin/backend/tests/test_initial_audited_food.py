import pytest

from services.initial_audited_food import AUDITED_EMART_FOOD_GROUPS, AUDITED_EMART_FOOD_TITLES
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


def record(title, mart="emart", path="밀키트/간편식"):
    return {"source_name": mart, "source_title": title, "source_category_path": [path]}


@pytest.mark.parametrize("title,leaf", list(AUDITED_EMART_FOOD_TITLES.items()))
def test_reviewed_food_title_uses_leaf_and_requires_exact_context(title, leaf):
    result = classify_record(record(title))
    assert result["unified_category_id"] == leaf
    assert result["evidence_type"] == "audited_emart_food_title"
    for changed in (record(title + " 혼합세트"), record(title, mart="costco"), record(title, path="반려동물")):
        assert classify_record(changed)["evidence_type"] != "audited_emart_food_title"


def test_audited_title_table_has_no_duplicates_and_all_leaves_have_four_levels():
    assert sum(map(len, AUDITED_EMART_FOOD_GROUPS.values())) == len(AUDITED_EMART_FOOD_TITLES)
    categories = taxonomy_categories(AUDITED_EMART_FOOD_GROUPS)
    validate_taxonomy(categories, AUDITED_EMART_FOOD_GROUPS)
    by_id = {r["id"]: r for r in categories}
    for leaf in AUDITED_EMART_FOOD_GROUPS:
        assert by_id[leaf]["level"] == 3


@pytest.mark.parametrize("title,path", [
    ("8월 베이커리 최대 50% 특가", "베이커리/잼"),
    ("식빵/마들렌 최대 15% 단독 특가", "베이커리/잼"),
    ("올리브 치아바타 2Pack 기획 (쁘띠 672g+이탈리안 800g)", "베이커리/잼"),
    ("샌드위치용 샐러드 계란 250g", "베이커리/잼"),
    ("다담 된장찌개 양념500g", "밀키트/간편식"),
    ("[매일유업]맘마밀 안심이유식 미역과소고기100g", "밀키트/간편식"),
    ("불닭볶음면 105g", "면류/통조림"),
    ("불닭볶음면 (70g*6개) 420g", "면류/통조림"),
    ("신상 오뚜기 동대문식 닭한마리 칼국수 115g*4개", "면류/통조림"),
])
def test_unreviewed_forms_promotions_and_conflicts_remain_pending(title, path):
    assert classify_record(record(title, path=path))["unified_category_id"] is None
