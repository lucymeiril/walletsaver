"""Price calculation service tests — SQLite in-memory"""
import sys
import os
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from storage.models import Base, Product, BaselinePrice, DiscountHistory, HotdealPrice, Category, DeliveryItem
from services.price_calc import (
    calculate_baseline_average,
    calculate_hotdeal_price,
    get_price_tier,
    get_price_history,
    get_price_comparison,
    calculate_recipe_vs_delivery,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def seeded_session(session):
    cat = Category(id="veg", name="채소류", depth=0, sort_order=0, is_active=True)
    session.add(cat)

    p = Product(id=1, name="양파", category_id="veg", unit="kg")
    session.add(p)
    session.flush()

    now = datetime.utcnow()
    # baseline prices over 30 days
    for i in range(20):
        session.add(BaselinePrice(
            product_id=1,
            price=1500 + (i * 50),
            source="kamis",
            unit="kg",
            recorded_at=now - timedelta(days=i),
        ))

    # discount history from marts
    for source in ["emart", "homeplus", "lottemart"]:
        for i in range(5):
            session.add(DiscountHistory(
                product_id=1,
                price=1200 + (i * 100),
                source=source,
                crawled_at=now - timedelta(days=i),
            ))

    # hotdeal prices
    hotdeal_prices = [900, 950, 1000, 1050, 1100, 5000, 800]  # 5000 is outlier
    for i, price in enumerate(hotdeal_prices):
        session.add(HotdealPrice(
            product_id=1,
            price=price,
            source="ppomppu",
            crawled_at=now - timedelta(days=i),
        ))

    session.commit()
    return session


class TestCalculateBaselineAverage:
    def test_with_data(self, seeded_session):
        result = calculate_baseline_average(seeded_session, 1, days=90)
        assert result["count"] > 0
        assert result["average"] > 0
        assert result["days"] == 90

    def test_no_data(self, session):
        p = Product(id=99, name="없는상품", unit="개")
        session.add(p)
        session.commit()
        result = calculate_baseline_average(session, 99, days=90)
        assert result["average"] == 0
        assert result["count"] == 0

    def test_ignores_zero_and_negative_placeholder_prices(self, session):
        p = Product(id=100, name="가격숨김상품", unit="개")
        session.add(p)
        now = datetime.utcnow()
        session.add_all([
            BaselinePrice(product_id=100, price=0, source="placeholder", unit="개", recorded_at=now),
            DiscountHistory(product_id=100, price=-1, source="placeholder", crawled_at=now),
        ])
        session.commit()

        result = calculate_baseline_average(session, 100, days=90)

        assert result["average"] == 0
        assert result["count"] == 0


class TestCalculateHotdealPrice:
    def test_with_outlier_removal(self, seeded_session):
        result = calculate_hotdeal_price(seeded_session, 1)
        assert result["count"] > 0
        assert result["hotdeal_avg"] > 0
        # 5000 outlier should be removed
        assert result["hotdeal_avg"] < 2000

    def test_no_hotdeal(self, session):
        p = Product(id=99, name="없는상품", unit="개")
        session.add(p)
        session.commit()
        result = calculate_hotdeal_price(session, 99)
        assert result["hotdeal_avg"] == 0
        assert result["count"] == 0


class TestGetPriceTier:
    def test_good_price(self, seeded_session):
        result = get_price_tier(seeded_session, 1500, 1)
        assert result["tier"] in ("ultra", "great", "good", "wait")
        assert "ratio" in result

    def test_expensive_price(self, seeded_session):
        result = get_price_tier(seeded_session, 5000, 1)
        assert result["tier"] == "wait"

    def test_cheap_price(self, seeded_session):
        result = get_price_tier(seeded_session, 500, 1)
        assert result["tier"] in ("ultra", "great")

    def test_no_data(self, session):
        p = Product(id=99, name="없는상품", unit="개")
        session.add(p)
        session.commit()
        result = get_price_tier(session, 1000, 99)
        assert result["tier"] == "good"


class TestGetPriceHistory:
    def test_returns_history(self, seeded_session):
        history = get_price_history(seeded_session, 1, days=30)
        assert len(history) > 0
        assert "date" in history[0]
        assert "price" in history[0]

    def test_empty_history(self, session):
        p = Product(id=99, name="없는상품", unit="개")
        session.add(p)
        session.commit()
        history = get_price_history(session, 99, days=30)
        assert history == []


class TestGetPriceComparison:
    def test_comparison_by_source(self, seeded_session):
        result = get_price_comparison(seeded_session, 1)
        assert len(result) >= 3  # emart, homeplus, lottemart
        sources = {r["source"] for r in result}
        assert "emart" in sources

    def test_no_data(self, session):
        p = Product(id=99, name="없는상품", unit="개")
        session.add(p)
        session.commit()
        result = get_price_comparison(session, 99)
        assert result == []


class TestRecipeVsDelivery:
    def test_comparison(self, seeded_session):
        # Add delivery item
        seeded_session.add(DeliveryItem(
            restaurant_name="테스트식당",
            menu_name="양파볶음",
            price=8000,
            platform="baemin",
        ))
        seeded_session.commit()

        result = calculate_recipe_vs_delivery(
            seeded_session,
            [{"product_id": 1, "quantity": 2}],
        )
        assert "cook_cost" in result
        assert result["cook_cost"] > 0
        assert "delivery_avg" in result
