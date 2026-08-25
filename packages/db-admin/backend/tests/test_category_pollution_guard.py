"""Regression tests that keep unreviewed category guesses out of public reads."""
from __future__ import annotations

from datetime import datetime

from storage.db import DBStorage
from storage.models import Base, Category, DiscountHistory, Product


def _storage() -> DBStorage:
    storage = DBStorage("sqlite:///:memory:")
    Base.metadata.create_all(storage.engine)
    return storage


def test_suggested_or_ad_hoc_category_is_hidden_from_public_product_search():
    storage = _storage()
    product_name = "브랜드없는 크롤상품 500g"
    with storage.SessionLocal() as session:
        session.add(Category(id="crawler.generated", name=product_name, depth=0, is_active=True))
        session.add(
            Product(
                id=1,
                name=product_name,
                category_id="crawler.generated",
                unit="개",
                source_type="mart_crawl",
                categorization_method="suggested",
                categorization_confidence=0.6,
            )
        )
        session.add(
            DiscountHistory(
                product_id=1,
                source="emart",
                price=9900,
                crawled_at=datetime.now(),
            )
        )
        session.commit()

    results = storage.search_products("브랜드없는")

    assert len(results) == 1
    assert results[0]["name"] == product_name
    assert results[0]["cat"] == ""
    assert results[0]["category_id"] == ""


def test_suggested_or_ad_hoc_category_is_excluded_from_category_compare():
    storage = _storage()
    product_name = "카테고리처럼 보이면 안 되는 상품명"
    with storage.SessionLocal() as session:
        session.add(Category(id="crawler.generated", name=product_name, depth=0, is_active=True))
        session.add(
            Product(
                id=1,
                name=product_name,
                category_id="crawler.generated",
                unit="개",
                source_type="mart_crawl",
                categorization_method="suggested",
                categorization_confidence=0.6,
            )
        )
        session.add(
            DiscountHistory(
                product_id=1,
                source="emart",
                price=9900,
                crawled_at=datetime.now(),
            )
        )
        session.commit()

    result = storage.get_category_comparison("crawler.generated")

    assert result["total"] == 0
    assert result["products"] == []
