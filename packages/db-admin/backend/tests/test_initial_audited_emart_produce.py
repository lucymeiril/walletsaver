import pytest
from services.initial_audited_emart_produce import TITLES, reviewed_emart_produce_leaf
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


@pytest.mark.parametrize("title,leaf", TITLES.items())
def test_exact_organic_product_type(title,leaf):
    result = classify_record({"source_name":"emart", "source_category_path":["친환경/유기농"], "source_title":title})
    assert result["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", ["친환경 무 (1kg이상)", "친환경 오이 2입/봉 (250g내외)", "친환경 신선 행사 모음전", "모닝 샐러드 (300g)"])
def test_uncertain_items_not_in_reviewed_table(title):
    assert reviewed_emart_produce_leaf({"mart":"emart","source_path_parts":["친환경/유기농"],"source_title":title}) is None


@pytest.mark.parametrize("mart,path", [("homeplus",["친환경/유기농"]), ("emart",["반려동물"])])
def test_review_scope(mart,path):
    assert reviewed_emart_produce_leaf({"mart":mart,"source_path_parts":path,"source_title":"부추 300g"}) is None
