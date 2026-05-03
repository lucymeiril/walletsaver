"""Regression tests for category pollution from crawled products."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from storage.db import DBStorage
import storage.db as storage_db_module
from storage.models import Base, Category, DiscountHistory, PendingCategorization, Product


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


def test_mid_confidence_categorization_creates_pending_without_public_assignment(monkeypatch):
    storage = _storage()
    with storage.SessionLocal() as session:
        session.add(Category(id="approved", name="승인카테고리", depth=0, is_active=True))
        session.add(Product(id=1, name="검토필요상품", unit="개", source_type="mart_crawl"))
        session.commit()

    @dataclass
    class Result:
        category_id: str = "approved"
        confidence: float = 0.6
        candidates: list[tuple[str, float]] = None
        parsed_keywords: list[str] = None
        attributes: dict = None

    monkeypatch.setattr(storage_db_module, "auto_categorize", lambda name, source=None: Result())

    storage.categorize_product(1, source="emart")

    with storage.SessionLocal() as session:
        product = session.get(Product, 1)
        pending = session.query(PendingCategorization).filter_by(product_id=1).one()

    assert product.category_id is None
    assert product.categorization_method == "suggested"
    assert pending.suggested_category_id == "approved"
    assert pending.status == "pending"
