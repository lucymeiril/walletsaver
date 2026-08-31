from services.name_normalize import normalize_match_text, normalize_package_signature


def test_normalize_match_text_folds_unicode_case_and_whitespace():
    assert normalize_match_text("  ＡＢＣ   우유  ") == "abc 우유"


def test_normalize_package_signature_preserves_package_values():
    assert (
        normalize_package_signature("qty=1.0;unit=KG;bundle=2;display=kg")
        == "qty-1.0-unit-kg-bundle-2-display-kg"
    )
