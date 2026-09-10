import pytest
from services.initial_audited_seasonings import TITLES, reviewed_seasoning_leaf
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


@pytest.mark.parametrize("title,leaf", TITLES.items())
def test_reviewed_seasoning(title,leaf):
    if ".spices." in leaf:
        suffix = {
            "mustard_paste": ["겨자/와사비"], "wasabi_paste": ["겨자/와사비"],
            "chili_powder": ["고추가루"], "roasted_sesame": ["후추/볶음깨", "볶음깨"],
            "whole_chili": ["후추/볶음깨", "후추"],
        }.get(leaf.rsplit(".",1)[1], ["바질/파슬리/기타향신료", "파슬리/기타향신료"])
        path = ["고추가루/깨/향신료", *suffix]
    elif ".syrups." in leaf or leaf.endswith("cooking_wine"):
        path = ["식초/물엿/맛술/액젓", "물엿/쌀엿/올리고당", "물엿/올리고당"]
    else:
        path = ["다시다/미원/맛소금", "멸치/해물다시다"]
    result = classify_record({"source_name":"homeplus", "source_category_path":["장류/양념/제빵", *path], "source_title":title})
    if leaf.endswith("whole_chili"):
        # Actual retail pepper evidence still conflicts; do not force inclusion.
        assert result["unified_category_id"] is None
        assert result["classification_reason"] == "conflicting_category_evidence"
    else:
        assert result["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", ["농심 혼다시 120G", "샘표 연두 순 320G", "CJ 백설 알룰로스 800G"])
def test_opaque_or_changed_title_not_added(title):
    assert reviewed_seasoning_leaf({"mart":"homeplus", "source_path_parts":["장류/양념/제빵","다시다/미원/맛소금","멸치/해물다시다"], "source_title":title}) is None


@pytest.mark.parametrize("mart,path", [("emart",["장류/양념/제빵","고추가루/깨/향신료","후추"]), ("homeplus",["생활용품","방향제","기타"])])
def test_scope_is_limited(mart,path):
    assert reviewed_seasoning_leaf({"mart":mart,"source_path_parts":path,"source_title":"브레드가든 쿠민 53G"}) is None
