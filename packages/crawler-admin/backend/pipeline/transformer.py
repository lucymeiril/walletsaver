"""데이터 변환기 — 크롤링 결과를 DB 저장 형식으로 변환."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pipeline.sanitizer import sanitize_record
from services.matching_enrichment import enrich_items_with_matching_entries


def to_discount_history(
    items: list[dict[str, Any]],
    source: str = "mart_discount",
) -> list[dict[str, Any]]:
    """DiscountItem dict → DiscountHistory DB 레코드 형식으로 변환."""
    records = []
    now = datetime.now().isoformat()
    for item in items:
        record = {
            "product_name": item.get("normalized_name") or item.get("name", ""),
            "store": item.get("store", ""),
            "original_price": item.get("original_price"),
            "sale_price": item.get("sale_price") or item.get("price"),
            "discount_percent": item.get("discount_percent"),
            "category": item.get("category", ""),
            "event_name": item.get("event_name", ""),
            "valid_from": item.get("valid_from"),
            "valid_until": item.get("valid_until"),
            "source": source,
            "source_url": item.get("detail_url") or item.get("source_url", ""),
            "recorded_at": now,
        }
        records.append(record)
    return [sanitize_record(r) for r in records]


def to_hotdeal_prices(
    items: list[dict[str, Any]],
    source: str = "hotdeal",
) -> list[dict[str, Any]]:
    """HotdealPost dict → HotdealPrice DB 레코드 형식으로 변환."""
    records = []
    now = datetime.now().isoformat()
    for item in items:
        record = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source_community": item.get("source_community") or item.get("source", ""),
            "price": item.get("price"),
            "original_price": item.get("original_price"),
            "category": item.get("category", ""),
            "source": source,
            "recorded_at": now,
        }
        records.append(record)
    return [sanitize_record(r) for r in records]


def to_delivery_items(
    items: list[dict[str, Any]],
    platform: str = "",
) -> list[dict[str, Any]]:
    """DeliveryItem DB 레코드 형식으로 변환."""
    records = []
    now = datetime.now().isoformat()
    for item in items:
        record = {
            "restaurant_name": item.get("restaurant_name", ""),
            "menu_name": item.get("menu_name") or item.get("name", ""),
            "price": item.get("price"),
            "platform": platform or item.get("platform", ""),
            "category": item.get("category", ""),
            "source_url": item.get("source_url") or item.get("url", ""),
            "recorded_at": now,
        }
        records.append(record)
    return records


def enrich_with_category(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reuse persisted matching knowledge before rows enter PendingIngestion.

    The old keyword heuristic produced categories that were unrelated to the
    persistent matching table. Known products now reuse MatchingEntry data;
    misses stay unresolved so the external classification workflow can handle
    them instead of silently guessing a category.
    """
    return enrich_items_with_matching_entries(items)
