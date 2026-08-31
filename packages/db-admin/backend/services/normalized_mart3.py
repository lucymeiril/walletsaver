"""Minimal DB-admin normalized mart3 projection helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import math
import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.promotion_semantics import PriceState, PromotionPriceFacts, PromotionType
from services.name_normalize import normalize_match_text, normalize_package_signature
from storage.models import (
    Category,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    UnifiedCategory,
)


def publish_mart3_rows(
    session: Session,
    rows: list[dict[str, Any]],
    *,
    projection_version: str = "mart3-v1",
) -> list[dict[str, Any]]:
    """Persist a small deterministic mart3 sample into normalized public tables."""

    placements: list[dict[str, Any]] = []
    for row in rows:
        unified_category_id = row.get("unified_category_id") or row.get("category_id")
        category_id = _reviewed_legacy_category_id(session, row.get("category_id"))
        unified_category_id = _reviewed_unified_category_id(session, unified_category_id)

        product = _upsert_product(
            session,
            row,
            category_id,
            unified_category_id,
            projection_version,
        )
        package_signature = _row_package_signature(row)
        listing, variant, match_result = _resolve_or_create_listing(
            session,
            row,
            product,
            package_signature,
            projection_version,
        )
        offer = _upsert_offer_event(session, row, listing, projection_version)
        week = _upsert_week_bucket(session, row, projection_version)
        link = session.get(
            NormalizedOfferWeekLink,
            (offer.public_offer_event_id, week.public_week_bucket_id),
        )
        facts = _price_facts(row)
        comparable_price = facts.comparable_price
        if link is None:
            session.add(
                NormalizedOfferWeekLink(
                    public_offer_event_id=offer.public_offer_event_id,
                    public_week_bucket_id=week.public_week_bucket_id,
                    observed_min_price=comparable_price,
                    observed_max_price=comparable_price,
                )
            )
        else:
            link.observed_min_price = comparable_price
            link.observed_max_price = comparable_price
        placements.append(
            {
                "raw_record_id": row.get("raw_record_id"),
                "match_result": match_result,
                "public_product_id": product.public_product_id,
                "public_variant_id": variant.public_variant_id,
                "public_source_listing_id": listing.public_source_listing_id,
                "public_offer_event_id": offer.public_offer_event_id,
                "public_week_bucket_id": week.public_week_bucket_id,
                "comparable_price": comparable_price,
            }
        )
    session.flush()
    return placements


def _reviewed_legacy_category_id(session: Session, category_id: Any) -> str | None:
    """Never manufacture a category from a crawler-provided identifier."""
    value = str(category_id or "").strip()
    return value if value and session.get(Category, value) is not None else None


def _reviewed_unified_category_id(session: Session, category_id: Any) -> str | None:
    value = str(category_id or "").strip()
    return value if value and session.get(UnifiedCategory, value) is not None else None


def _upsert_product(
    session: Session,
    row: dict[str, Any],
    category_id: str | None,
    unified_category_id: str | None,
    projection_version: str,
) -> NormalizedCanonicalProduct:
    canonical_name = row.get("canonical_name") or row.get("name") or row.get("source_title")
    public_product_id = row.get("public_product_id") or _stable_id(
        "prod",
        unified_category_id or category_id or "unclassified",
        canonical_name,
        row.get("brand") or "",
    )
    product = session.get(NormalizedCanonicalProduct, public_product_id)
    data = {
        "category_id": category_id,
        "unified_category_id": unified_category_id,
        "canonical_name": canonical_name,
        "brand": row.get("brand"),
        "aliases": _list(row.get("aliases")),
        "keywords": _list(row.get("keywords")),
        "attributes": row.get("attributes") if isinstance(row.get("attributes"), dict) else {},
        "projection_version": projection_version,
        "updated_at": datetime.utcnow(),
    }
    if product is None:
        product = NormalizedCanonicalProduct(
            public_product_id=public_product_id,
            primary_image_url=row.get("image_url"),
            **data,
        )
        session.add(product)
        session.flush()
        return product
    for key, value in data.items():
        setattr(product, key, value)
    if not product.primary_image_url and row.get("image_url"):
        product.primary_image_url = row.get("image_url")
    return product


def _resolve_or_create_listing(
    session: Session,
    row: dict[str, Any],
    product: NormalizedCanonicalProduct,
    package_signature: str,
    projection_version: str,
) -> tuple[NormalizedSourceListing, NormalizedProductVariant, str]:
    source_name = _source_name(row)
    source_title = row.get("source_title") or row.get("name") or product.canonical_name
    title_key = normalize_match_text(source_title)
    existing_same_title = [
        listing
        for listing in session.execute(
            select(NormalizedSourceListing).where(NormalizedSourceListing.source_name == source_name)
        ).scalars()
        if normalize_match_text(listing.source_title) == title_key
    ]
    for listing in existing_same_title:
        if _variant_package_signature(listing.variant) == package_signature:
            _update_listing(listing, row, projection_version)
            return listing, listing.variant, "auto_same_title_package"

    match_result = "candidate_package_mismatch" if existing_same_title else "new_listing"
    variant_id = row.get("public_variant_id") or _stable_id(
        "var",
        product.public_product_id,
        package_signature,
    )
    variant = session.get(NormalizedProductVariant, variant_id)
    if variant is None:
        variant = NormalizedProductVariant(
            public_variant_id=variant_id,
            public_product_id=product.public_product_id,
            variant_name=row.get("variant_name") or source_title,
            package_quantity=_positive_float_or_none(row.get("package_quantity")),
            package_unit=row.get("package_unit"),
            display_unit=row.get("display_unit") or row.get("unit"),
            bundle_count=int(row.get("bundle_count") or 1),
            standard_unit=row.get("standard_unit"),
            attributes=row.get("variant_attributes") if isinstance(row.get("variant_attributes"), dict) else {},
            projection_version=projection_version,
        )
        session.add(variant)
        session.flush()

    listing_id = row.get("public_source_listing_id") or _stable_id(
        "listing",
        variant.public_variant_id,
        source_name,
        row.get("source_record_key") or title_key,
    )
    listing = session.get(NormalizedSourceListing, listing_id)
    if listing is None:
        listing = NormalizedSourceListing(
            public_source_listing_id=listing_id,
            public_variant_id=variant.public_variant_id,
            source_name=source_name,
            source_record_key=row.get("source_record_key"),
            source_title=source_title,
            source_unit_text=row.get("source_unit_text") or row.get("unit"),
            projection_version=projection_version,
        )
        session.add(listing)
        session.flush()
    _update_listing(listing, row, projection_version)
    return listing, variant, match_result


def _update_listing(
    listing: NormalizedSourceListing,
    row: dict[str, Any],
    projection_version: str,
) -> None:
    listing.source_record_key = row.get("source_record_key") or listing.source_record_key
    listing.source_title = row.get("source_title") or row.get("name") or listing.source_title
    listing.source_url = row.get("source_url") or row.get("detail_url") or listing.source_url
    listing.image_url = row.get("listing_image_url") or row.get("image_url") or listing.image_url
    listing.source_unit_text = row.get("source_unit_text") or row.get("unit") or listing.source_unit_text
    listing.projection_version = projection_version
    listing.updated_at = datetime.utcnow()


def _upsert_offer_event(
    session: Session,
    row: dict[str, Any],
    listing: NormalizedSourceListing,
    projection_version: str,
) -> NormalizedOfferEvent:
    facts = _price_facts(row)
    event_id = row.get("public_offer_event_id") or _stable_id(
        "offer",
        listing.public_source_listing_id,
        facts.price_state.value,
        facts.promotion_type.value,
        facts.current_price,
        facts.original_price,
        facts.discount_rate,
        row.get("event_name") or "",
        _datetime_key(row.get("valid_from")),
        _datetime_key(row.get("valid_to")),
    )
    offer = session.get(NormalizedOfferEvent, event_id)
    data = {
        "public_source_listing_id": listing.public_source_listing_id,
        "price_state": facts.price_state.value,
        "promotion_type": facts.promotion_type.value,
        "price": facts.current_price,
        "original_price": facts.original_price,
        "discount_rate": facts.discount_rate,
        "event_name": row.get("event_name"),
        "standard_unit_price": _positive_float_or_none(row.get("standard_unit_price")),
        "price_per_100g": _positive_float_or_none(row.get("price_per_100g")),
        "valid_from": _parse_datetime(row.get("valid_from")),
        "valid_to": _parse_datetime(row.get("valid_to")),
        "raw_record_id": row.get("raw_record_id"),
        "raw_evidence": row.get("raw_evidence") if isinstance(row.get("raw_evidence"), dict) else {},
        "audit_provenance": row.get("audit_provenance") if isinstance(row.get("audit_provenance"), dict) else {},
        "crawled_at": _parse_datetime(row.get("crawled_at")) or datetime.utcnow(),
        "offer_state": row.get("offer_state") or "active",
        "projection_version": projection_version,
    }
    if offer is None:
        offer = NormalizedOfferEvent(public_offer_event_id=event_id, **data)
        session.add(offer)
    else:
        data["raw_evidence"] = _merge_evidence(offer.raw_evidence or {}, data["raw_evidence"])
        data["audit_provenance"] = _merge_evidence(offer.audit_provenance or {}, data["audit_provenance"])
        for key, value in data.items():
            setattr(offer, key, value)
    session.flush()
    return offer


def _upsert_week_bucket(
    session: Session,
    row: dict[str, Any],
    projection_version: str,
) -> NormalizedWeekBucket:
    week_start = _parse_datetime(row.get("week_start")) or _week_start(
        _parse_datetime(row.get("crawled_at")) or datetime.utcnow()
    )
    week_end = _parse_datetime(row.get("week_end")) or (week_start + timedelta(days=6))
    week_id = row.get("public_week_bucket_id") or _stable_id(
        "week",
        week_start.date().isoformat(),
        week_end.date().isoformat(),
    )
    week = session.get(NormalizedWeekBucket, week_id)
    if week is None:
        week = NormalizedWeekBucket(
            public_week_bucket_id=week_id,
            week_start=week_start,
            week_end=week_end,
            projection_version=projection_version,
        )
        session.add(week)
    else:
        week.projection_version = projection_version
    session.flush()
    return week


def _price_facts(row: dict[str, Any]) -> PromotionPriceFacts:
    discount_percent = row.get("discount_percent")
    return PromotionPriceFacts.from_source(
        current_price=row.get("price", row.get("current_price", row.get("sale_price"))),
        original_price=row.get("original_price"),
        discount_rate=_discount_percent_rate(discount_percent)
        if discount_percent is not None
        else _discount_rate(row.get("discount_rate")),
        price_state=row.get("price_state"),
        promotion_type=row.get("promotion_type") or PromotionType.UNKNOWN,
    ).with_safe_calculations()


def _discount_rate(value: Any) -> float | None:
    number = _finite_float_or_none(value)
    if number is None:
        return None
    return number / 100 if number >= 1 else number


def _discount_percent_rate(value: Any) -> float | None:
    number = _finite_float_or_none(value)
    if number is None:
        return None
    return number / 100


def _row_package_signature(row: dict[str, Any]) -> str:
    quantity = _positive_float_or_none(row.get("package_quantity"))
    unit = (row.get("package_unit") or "").strip().lower()
    bundle_count = int(row.get("bundle_count") or 1)
    display_unit = (row.get("display_unit") or row.get("unit") or "").strip().lower()
    raw = f"qty={quantity or ''};unit={unit};bundle={bundle_count};display={display_unit}"
    return normalize_package_signature(raw)


def _variant_package_signature(variant: NormalizedProductVariant) -> str:
    raw = (
        f"qty={variant.package_quantity or ''};unit={(variant.package_unit or '').strip().lower()};"
        f"bundle={variant.bundle_count or 1};display={(variant.display_unit or '').strip().lower()}"
    )
    return normalize_package_signature(raw)


def _source_name(row: dict[str, Any]) -> str:
    return str(row.get("source_name") or row.get("source") or row.get("store") or "unknown").strip().lower()


def _merge_evidence(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if not incoming:
        return existing
    if not existing or existing == incoming:
        return incoming
    observations = existing.get("observations") if isinstance(existing.get("observations"), list) else [existing]
    if incoming not in observations:
        observations = [*observations, incoming]
    return {"observations": observations}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    normalized = unicodedata.normalize("NFKC", raw).strip().lower()
    readable = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE).strip("-_.")[:48]
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{readable}-{digest}" if readable else f"{prefix}-{digest}"


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _finite_float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "").replace("원", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_float_or_none(value: Any) -> float | None:
    number = _finite_float_or_none(value)
    return number if number is not None and number > 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _datetime_key(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else ""


def _week_start(value: datetime) -> datetime:
    start = value - timedelta(days=value.weekday())
    return datetime(start.year, start.month, start.day)
