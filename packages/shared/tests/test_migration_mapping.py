"""기존 DB row -> 새 canonical/variant/offer 계약 매핑 테스트."""

from shared.core.migration_mapping import (
    discount_row_to_offer_draft,
    product_row_to_canonical_draft,
    product_row_to_variant_draft,
)


def test_product_row_maps_to_canonical_and_variant_with_legacy_id():
    row = {
        "id": 10,
        "name": "국내산 냉장 삼겹살 1kg",
        "category_id": "meat.pork.belly",
        "unit": "1kg",
        "attributes": {"origin": "domestic", "storage_state": "chilled"},
        "keywords": ["삼겹살", "돼지고기"],
    }

    canonical = product_row_to_canonical_draft(row)
    variant = product_row_to_variant_draft(row)

    assert canonical.canonical_name == row["name"]
    assert canonical.attributes["legacy_product_id"] == 10
    assert variant.package_unit == "1kg"
    assert variant.attributes["storage_state"] == "chilled"


def test_discount_row_maps_to_offer_without_losing_source_title():
    offer = discount_row_to_offer_draft(
        {
            "id": 5,
            "source": "emart",
            "price": 10990,
            "original_price": 13990,
            "source_url": "https://example.com",
            "raw_data": {"title": "알프스 탄탄포크 정육 행사", "image_url": "https://img"},
        },
        product_name="국내산 냉장 삼겹살",
    )

    assert offer.source_title == "알프스 탄탄포크 정육 행사"
    assert offer.raw_record_id == "legacy-discount-5"
    assert offer.original_price == 13990
