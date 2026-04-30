"""
기존 Product/DiscountHistory/Keyword 데이터를 새 canonical/variant/offer 구조로 옮기는
매핑 보조 함수.

이 모듈은 실제 DB 마이그레이션을 실행하지 않는다. 기존 데이터를 새 public/control
계약으로 변환하는 규칙을 테스트 가능한 순수 함수로 고정해 dual-write 혼란을 줄인다.
"""

from __future__ import annotations

from typing import Any

from .contracts.ai_pipeline import CanonicalProductDraft, ProductVariantDraft, SaleOfferDraft


def product_row_to_canonical_draft(row: dict[str, Any]) -> CanonicalProductDraft:
    name = str(row.get("name") or "").strip()
    if not name:
        raise ValueError("Existing product row requires name")
    attributes = row.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {"legacy_attributes": attributes}
    keywords = row.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    return CanonicalProductDraft(
        canonical_name=name,
        brand=attributes.get("brand"),
        category_id=row.get("category_id"),
        aliases=[name],
        keywords=keywords,
        attributes={"legacy_product_id": row.get("id"), **attributes},
    )


def product_row_to_variant_draft(row: dict[str, Any]) -> ProductVariantDraft:
    name = str(row.get("name") or "").strip()
    unit = row.get("unit") or "개"
    attributes = row.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {"legacy_attributes": attributes}
    return ProductVariantDraft(
        variant_name=name,
        package_unit=str(unit),
        standard_unit=str(unit),
        attributes={"legacy_product_id": row.get("id"), **attributes},
    )


def discount_row_to_offer_draft(row: dict[str, Any], *, product_name: str) -> SaleOfferDraft:
    price = row.get("price")
    if price is None:
        raise ValueError("Existing discount row requires price")
    raw_data = row.get("raw_data") or {}
    if not isinstance(raw_data, dict):
        raw_data = {}
    return SaleOfferDraft(
        source_name=str(row.get("source") or "unknown"),
        source_record_key=str(row.get("id")) if row.get("id") is not None else None,
        source_title=str(raw_data.get("title") or product_name),
        source_url=row.get("source_url"),
        image_url=raw_data.get("image_url"),
        price=int(price),
        original_price=int(row["original_price"]) if row.get("original_price") is not None else None,
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        raw_record_id=f"legacy-discount-{row.get('id')}",
    )
