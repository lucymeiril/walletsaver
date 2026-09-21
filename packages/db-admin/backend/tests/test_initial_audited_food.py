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
])
def test_promotion_surfaces_remain_pending(title, path):
    assert classify_record(record(title, path=path))["unified_category_id"] is None
