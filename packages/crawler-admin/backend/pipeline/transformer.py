"""데이터 변환기 — 크롤링 결과를 DB 저장 형식으로 변환."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pipeline.sanitizer import sanitize_record


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


# 키워드 → 카테고리 매핑 (간소화)
_CATEGORY_KEYWORDS: dict[str, str] = {
    "삼겹살": "축산물 > 돼지고기 > 삼겹살",
    "목살": "축산물 > 돼지고기 > 목살",
    "갈비": "축산물 > 돼지고기 > 갈비",
    "등심": "축산물 > 소고기 > 등심",
    "안심": "축산물 > 소고기 > 안심",
    "닭가슴살": "축산물 > 닭고기 > 가슴살",
    "계란": "축산물 > 란류 > 계란",
    "양파": "채소류 > 근채류 > 양파",
    "감자": "채소류 > 근채류 > 감자",
    "대파": "채소류 > 조미채소 > 대파",
    "사과": "과일류 > 사과",
    "바나나": "과일류 > 바나나",
    "우유": "유제품 > 우유",
    "라면": "가공식품 > 면류 > 라면",
    "쌀": "곡류 > 쌀",
    "고등어": "수산물 > 생선류 > 고등어",
    "새우": "수산물 > 갑각류 > 새우",
}


def enrich_with_category(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """카테고리 자동 매핑. 상품명에 키워드가 포함되면 카테고리를 할당."""
    for item in items:
        if item.get("category"):
            continue
        name = item.get("name") or item.get("product_name") or item.get("title") or ""
        for keyword, category in _CATEGORY_KEYWORDS.items():
            if keyword in name:
                item["category"] = category
                break
    return items
