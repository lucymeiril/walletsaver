"""
control DB 승인 데이터를 public catalog/pricing read model로 투영하는 순수 로직.

실제 DB 쓰기는 db-admin repository가 담당한다. 이 모듈은 idempotent public ID 생성,
projection checksum, rollback 대상 기록 등 publish 정책을 고정한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from .contracts.ai_pipeline import CanonicalProductDraft, ProductVariantDraft, SaleOfferDraft
from .contracts.public_catalog import (
    CatalogDeltaManifest,
    ProjectionRunContract,
    PublicCatalogProduct,
    PublicProductVariant,
    PublicSaleOffer,
)


def stable_slug(value: str, *, fallback: str = "item") -> str:
    """한글/영문 원문에서 public ID에 쓸 안정 slug를 만든다."""
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback


def build_public_product_id(canonical_name: str, brand: str | None = None) -> str:
    base = f"{brand}-{canonical_name}" if brand else canonical_name
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"prod-{stable_slug(base)}-{digest}"


def build_public_variant_id(public_product_id: str, variant: ProductVariantDraft) -> str:
    basis = json.dumps(
        {
            "product": public_product_id,
            "name": variant.variant_name,
            "qty": variant.package_quantity,
            "unit": variant.package_unit,
            "bundle": variant.bundle_count,
            "attrs": variant.attributes,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"var-{digest}"


def build_public_offer_id(public_variant_id: str, offer: SaleOfferDraft) -> str:
    basis = json.dumps(
        {
            "variant": public_variant_id,
            "source": offer.source_name,
            "key": offer.source_record_key,
            "title": offer.source_title,
            "price": offer.price,
            "from": offer.valid_from.isoformat() if offer.valid_from else None,
            "to": offer.valid_to.isoformat() if offer.valid_to else None,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"offer-{digest}"


def project_product(
    draft: CanonicalProductDraft,
    *,
    projection_version: str,
) -> PublicCatalogProduct:
    public_product_id = build_public_product_id(draft.canonical_name, draft.brand)
    return PublicCatalogProduct(
        public_product_id=public_product_id,
        canonical_name=draft.canonical_name,
        brand=draft.brand,
        category_id=draft.category_id,
        aliases=draft.aliases,
        keywords=draft.keywords,
        attributes=draft.attributes,
        projection_version=projection_version,
    )


def project_variant(
    product: PublicCatalogProduct,
    draft: ProductVariantDraft,
    *,
    projection_version: str,
) -> PublicProductVariant:
    public_variant_id = build_public_variant_id(product.public_product_id, draft)
    return PublicProductVariant(
        public_variant_id=public_variant_id,
        public_product_id=product.public_product_id,
        variant_name=draft.variant_name,
        package_quantity=draft.package_quantity,
        package_unit=draft.package_unit,
        bundle_count=draft.bundle_count,
        standard_unit=draft.standard_unit,
        attributes=draft.attributes,
        projection_version=projection_version,
    )


def project_offer(
    variant: PublicProductVariant,
    draft: SaleOfferDraft,
    *,
    projection_version: str,
) -> PublicSaleOffer:
    return PublicSaleOffer(
        public_offer_id=build_public_offer_id(variant.public_variant_id, draft),
        public_variant_id=variant.public_variant_id,
        source_name=draft.source_name,
        source_record_key=draft.source_record_key,
        source_title=draft.source_title,
        source_url=draft.source_url,
        image_url=draft.image_url,
        price=draft.price,
        original_price=draft.original_price,
        standard_unit_price=draft.standard_unit_price,
        valid_from=draft.valid_from,
        valid_to=draft.valid_to,
        projection_version=projection_version,
    )


def projection_checksum(items: Iterable[object]) -> str:
    payload = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in items
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_projection_run(
    *,
    projection_version: str,
    source_control_run_id: str,
    products: list[PublicCatalogProduct],
    variants: list[PublicProductVariant],
    offers: list[PublicSaleOffer],
    published_by: str,
    rollback_of_version: str | None = None,
) -> ProjectionRunContract:
    checksum = projection_checksum([*products, *variants, *offers])
    return ProjectionRunContract(
        projection_version=projection_version,
        source_control_run_id=source_control_run_id,
        product_count=len(products),
        variant_count=len(variants),
        offer_count=len(offers),
        snapshot_checksum=checksum,
        published_by=published_by,
        rollback_of_version=rollback_of_version,
    )


def build_delta_manifest(
    *,
    from_version: str | None,
    to_version: str,
    previous_ids: set[str],
    current_products: list[PublicCatalogProduct],
    current_variants: list[PublicProductVariant],
    current_offers: list[PublicSaleOffer],
) -> CatalogDeltaManifest:
    current_ids = {
        *{item.public_product_id for item in current_products},
        *{item.public_variant_id for item in current_variants},
        *{item.public_offer_id for item in current_offers},
    }
    checksum = projection_checksum([*current_products, *current_variants, *current_offers])
    return CatalogDeltaManifest(
        from_version=from_version,
        to_version=to_version,
        checksum=checksum,
        changed_products=len(current_products),
        changed_variants=len(current_variants),
        changed_offers=len(current_offers),
        removed_public_ids=sorted(previous_ids - current_ids),
    )
