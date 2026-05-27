import hashlib

import pytest

from crawlers.marts.source_utils import (
    UNIT_PRICE_RE,
    classify_external_seller_emart,
    classify_external_seller_homeplus,
    compute_canon_hash,
    inject_source_field,
    normalize_name_core,
    normalize_costco_url,
    normalize_emart_url,
    normalize_homeplus_url,
    normalize_lottemart_url,
    parse_unit_price,
)


@pytest.mark.parametrize(
    ("text", "expected_price", "expected_basis"),
    [
        ("10g 당 314원", 314.0, "10g"),
        ("10G당 200원", 200.0, "10G"),
        ("100g당 400원", 400.0, "100g"),
        ("100ml당 1,234원", 1234.0, "100ml"),
    ],
)
def test_parse_unit_price_formats(text, expected_price, expected_basis):
    assert UNIT_PRICE_RE.search(text)
    assert parse_unit_price(text) == (expected_price, expected_basis)


def test_parse_unit_price_missing_returns_none_tuple():
    assert parse_unit_price("가격 정보 없음") == (None, None)


def test_normalize_lottemart_url_happy_path():
    assert (
        normalize_lottemart_url("8801234567890")
        == "https://lottemartzetta.com/products/OS8801234567890/details"
    )


@pytest.mark.parametrize("bad_code", ["", "550e8400-e29b-41d4-a716-446655440000"])
def test_normalize_lottemart_url_rejects_empty_and_uuid(bad_code):
    with pytest.raises(ValueError):
        normalize_lottemart_url(bad_code)


def test_normalize_emart_url_with_optional_salestr_no():
    assert (
        normalize_emart_url("1234567890123")
        == "https://emart.ssg.com/item/itemView.ssg?itemId=1234567890123&siteNo=7009"
    )
    assert (
        normalize_emart_url("1234567890123", salestr_no="2449")
        == "https://emart.ssg.com/item/itemView.ssg?itemId=1234567890123&siteNo=7009&salestrNo=2449"
    )


def test_normalize_homeplus_url_happy_and_invalid_store_type():
    assert (
        normalize_homeplus_url("123456789", store_type="EXP")
        == "https://mfront.homeplus.co.kr/item?itemNo=123456789&storeType=EXP"
    )
    with pytest.raises(ValueError):
        normalize_homeplus_url("123456789", store_type="MART")


def test_normalize_costco_url_forces_leading_slash():
    assert normalize_costco_url("Food/Rice", 12345) == "https://www.costco.co.kr/Food/Rice/p/12345"
    assert normalize_costco_url("/Food/Rice/", "12345") == "https://www.costco.co.kr/Food/Rice/p/12345"


def test_compute_canon_hash_is_deterministic_and_uses_empty_for_none():
    expected = hashlib.sha1("|두부 300g|300.0|g".encode("utf-8")).hexdigest()
    assert compute_canon_hash(None, "두부 300g", 300.0, "g") == expected
    assert compute_canon_hash(None, "두부 300g", 300.0, "g") == expected


def test_compute_canon_hash_strips_promotion_markers_before_hashing():
    expected = compute_canon_hash("테스트", "테스트 우유 1L", 1, "L")
    variants = [
        "[행사] 테스트 우유 1L",
        "[1+1] 테스트 우유 1L",
        "(NEW) 테스트 우유 1L",
        "{신상} 테스트 우유 1L",
        "【한정】 테스트 우유 1L",
        "<특가> 테스트 우유 1L",
        "★특가★ 테스트 우유 1L",
        "테스트 우유 1L 한정판매",
        "테스트 우유 1L 2+1",
    ]
    assert all(compute_canon_hash("테스트", name, 1, "L") == expected for name in variants)
    assert normalize_name_core("  [NEW]  Test   Milk  ", fold_case=True) == "test milk"


def test_classify_external_seller_emart_branches():
    assert classify_external_seller_emart(["foo", "bar"], "2449") is True
    assert classify_external_seller_emart(["cdtl_ico_item"], "2449") is False
    assert classify_external_seller_emart([], "7009") is False
    assert classify_external_seller_emart([], None) is False


def test_classify_external_seller_homeplus_branches():
    assert classify_external_seller_homeplus("판매자택배") is True
    assert classify_external_seller_homeplus("매직배송") is False
    assert classify_external_seller_homeplus("새벽배송 판매자택배") is False
    assert classify_external_seller_homeplus("") is False


def test_inject_source_field_overwrites_and_returns_record():
    record = {"source": "old", "name": "item"}
    assert inject_source_field(record, "emart") is record
    assert record["source"] == "emart"
