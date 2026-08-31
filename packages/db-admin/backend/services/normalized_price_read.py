"""Read model for normalized public price-comparison data."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core.promotion_semantics import comparable_price_or_none
from storage.models import (
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
)


def get_normalized_price_comparison(
    session: Session,
    *,
    category_id: str | None = None,
    public_product_id: str | None = None,
    public_variant_id: str | None = None,
    include_inactive: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a small nested read model for public product price comparison."""

    stmt = (
        select(NormalizedCanonicalProduct)
        .options(
            selectinload(NormalizedCanonicalProduct.variants)
            .selectinload(NormalizedProductVariant.source_listings)
            .selectinload(NormalizedSourceListing.offer_events)
            .selectinload(NormalizedOfferEvent.week_links)
            .selectinload(NormalizedOfferWeekLink.week_bucket),
        )
        .order_by(NormalizedCanonicalProduct.canonical_name.asc())
        .limit(limit)
    )
    if category_id:
        stmt = stmt.where(NormalizedCanonicalProduct.unified_category_id == category_id)
    if public_product_id:
        stmt = stmt.where(NormalizedCanonicalProduct.public_product_id == public_product_id)
    if not include_inactive:
        stmt = stmt.where(NormalizedCanonicalProduct.is_active.is_(True))

    products = []
    week_bucket_index: dict[str, dict[str, Any]] = {}
    for product in session.execute(stmt).scalars().unique().all():
        variants = [
            _variant_payload(variant, public_variant_id, include_inactive, week_bucket_index)
            for variant in product.variants
            if (include_inactive or variant.is_active)
            and (public_variant_id is None or variant.public_variant_id == public_variant_id)
        ]
        variants = [variant for variant in variants if variant is not None]
        variants.sort(key=_variant_sort_key)
        if public_variant_id and not variants:
            continue
        products.append(
            {
                "public_product_id": product.public_product_id,
                "category_id": product.category_id,
                "unified_category_id": product.unified_category_id,
                "canonical_name": product.canonical_name,
                "brand": product.brand,
                "aliases": product.aliases or [],
                "keywords": product.keywords or [],
                "attributes": product.attributes or {},
                "primary_image_url": product.primary_image_url,
                "projection_version": product.projection_version,
                "variants": variants,
            }
        )

    return {
        "products": products,
        "week_buckets": sorted(week_bucket_index.values(), key=lambda row: row["week_start"] or ""),
        "sort_policy": "comparable_price_ascending_then_non_comparable",
    }


def _variant_payload(
    variant: NormalizedProductVariant,
    public_variant_id: str | None,
    include_inactive: bool,
    week_bucket_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    listings = [
        _listing_payload(listing, include_inactive, week_bucket_index)
        for listing in variant.source_listings
        if include_inactive or listing.is_active
    ]
    listings = [listing for listing in listings if listing is not None]
    listings.sort(key=_listing_sort_key)
    if public_variant_id and not listings:
        return None
    return {
        "public_variant_id": variant.public_variant_id,
        "variant_name": variant.variant_name,
        "package_quantity": variant.package_quantity,
        "package_unit": variant.package_unit,
        "display_unit": variant.display_unit,
        "bundle_count": variant.bundle_count,
        "standard_unit": variant.standard_unit,
        "attributes": variant.attributes or {},
        "source_listings": listings,
    }


def _listing_payload(
    listing: NormalizedSourceListing,
    include_inactive: bool,
    week_bucket_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    events = [
        _offer_event_payload(event, week_bucket_index)
        for event in listing.offer_events
        if include_inactive or event.offer_state == "active"
    ]
    events.sort(key=_offer_sort_key)
    return {
        "public_source_listing_id": listing.public_source_listing_id,
        "source_name": listing.source_name,
        "source_record_key": listing.source_record_key,
        "source_title": listing.source_title,
        "source_url": listing.source_url,
        "latest_source_url": listing.source_url,
        "image_url": listing.image_url,
        "source_unit_text": listing.source_unit_text,
        "offer_events": events,
        "best_comparable_price": _first_comparable(events),
    }


def _offer_event_payload(
    event: NormalizedOfferEvent,
    week_bucket_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    comparable_price = comparable_price_or_none(
        {
            "price": event.price,
            "original_price": event.original_price,
            "discount_rate": event.discount_rate,
            "price_state": event.price_state,
            "promotion_type": event.promotion_type,
        }
    )
    weeks = []
    for link in event.week_links:
        week = link.week_bucket
        if week is None:
            continue
        week_payload = {
            "public_week_bucket_id": week.public_week_bucket_id,
            "week_start": _iso(week.week_start),
            "week_end": _iso(week.week_end),
            "observed_min_price": link.observed_min_price,
            "observed_max_price": link.observed_max_price,
        }
        weeks.append(week_payload)
        week_bucket_index.setdefault(
            week.public_week_bucket_id,
            {
                "public_week_bucket_id": week.public_week_bucket_id,
                "week_start": _iso(week.week_start),
                "week_end": _iso(week.week_end),
                "projection_version": week.projection_version,
            },
        )
    weeks.sort(key=lambda row: row["week_start"] or "")
    return {
        "public_offer_event_id": event.public_offer_event_id,
        "price_state": event.price_state,
        "promotion_type": event.promotion_type,
        "price": event.price,
        "original_price": event.original_price,
        "discount_rate": event.discount_rate,
        "event_name": event.event_name,
        "standard_unit_price": event.standard_unit_price,
        "price_per_100g": event.price_per_100g,
        "valid_from": _iso(event.valid_from),
        "valid_to": _iso(event.valid_to),
        "crawled_at": _iso(event.crawled_at),
        "offer_state": event.offer_state,
        "comparable_price": comparable_price,
        "comparable_price_available": comparable_price is not None,
        "is_default_sortable": comparable_price is not None,
        "display_state": _display_state(event, comparable_price),
        "weeks": weeks,
    }


def _display_state(event: NormalizedOfferEvent, comparable_price: int | None) -> str:
    if comparable_price is not None:
        return "comparable"
    if event.price_state == "price_hidden":
        return "hidden"
    if event.price_state == "discount_rate_only":
        return "rate_only"
    if event.promotion_type == "checkout_discount":
        return "card_or_checkout"
    return "non_comparable"


def _offer_sort_key(event: dict[str, Any]) -> tuple[int, float, str]:
    price = event["comparable_price"]
    return (0, float(price), event["public_offer_event_id"]) if price is not None else (1, 0.0, event["public_offer_event_id"])


def _listing_sort_key(listing: dict[str, Any]) -> tuple[int, float, str]:
    price = listing["best_comparable_price"]
    return (0, float(price), listing["source_name"]) if price is not None else (1, 0.0, listing["source_name"])


def _variant_sort_key(variant: dict[str, Any]) -> tuple[int, float, str]:
    listing_prices = [
        listing["best_comparable_price"]
        for listing in variant["source_listings"]
        if listing["best_comparable_price"] is not None
    ]
    return (
        0,
        float(min(listing_prices)),
        variant["public_variant_id"],
    ) if listing_prices else (1, 0.0, variant["public_variant_id"])


def _first_comparable(events: list[dict[str, Any]]) -> int | None:
    for event in events:
        if event["comparable_price"] is not None:
            return event["comparable_price"]
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
