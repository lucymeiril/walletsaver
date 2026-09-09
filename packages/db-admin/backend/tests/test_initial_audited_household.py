import pytest
from services.initial_audited_household import AUDITED_EMART_HOUSEHOLD_GROUPS, AUDITED_EMART_HOUSEHOLD_TITLES
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


def record(title, mart="emart", path="청소/생활용품"):
    return {"source_name": mart, "source_title": title, "source_category_path": [path]}


@pytest.mark.parametrize("title,leaf", list(AUDITED_EMART_HOUSEHOLD_TITLES.items()))
def test_reviewed_household_exact_title_and_context(title, leaf):
    result = classify_record(record(title))
    assert result["unified_category_id"] == leaf
    assert result["evidence_type"] == "audited_emart_household_title"
    for changed in (record(title + " 혼합세트"), record(title, mart="costco"), record(title, path="반려동물")):
        assert classify_record(changed)["evidence_type"] != "audited_emart_household_title"


def test_household_titles_unique_and_leaves_four_levels():
    assert sum(map(len, AUDITED_EMART_HOUSEHOLD_GROUPS.values())) == len(AUDITED_EMART_HOUSEHOLD_TITLES)
    rows = taxonomy_categories(AUDITED_EMART_HOUSEHOLD_GROUPS)
    validate_taxonomy(rows, AUDITED_EMART_HOUSEHOLD_GROUPS)
    assert all(r["level"] == 3 for r in rows if r["id"] in AUDITED_EMART_HOUSEHOLD_GROUPS)


@pytest.mark.parametrize("title", [
    "[기획세트] 퍼실 세탁세제 2.5L+1.5L(파워젤)",
    "수뜰리에 캡슐세제 로즈애플 40개입+다목적 발포세정제 40개입 선물세트",
    "거품형 순 용기 250ml", "깨끗한 리오셀 대형 34P", "시니어돌봄 리필형패드 일반 20P",
    "[NEW] 포이시안 마크2 야돔 1.7ml(6입)", "3000시리즈 헤어드라이어 BHD321/09",
])
def test_ambiguous_form_and_mixed_sets_are_not_absorbed(title):
    assert classify_record(record(title))["unified_category_id"] is None
