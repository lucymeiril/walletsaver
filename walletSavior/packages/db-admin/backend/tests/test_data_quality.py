"""Data quality service tests — SQLite in-memory"""
import sys
import os
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from storage.models import Base, Product, BaselinePrice, DiscountHistory, HotdealPrice, Category
from services.data_quality import (
    check_price_outliers,
    find_duplicates,
    validate_crawl_data,
    generate_quality_report,
    cleanup_stale_data,
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
    session.add(Category(id="veg", name="채소류", depth=0, sort_order=0, is_active=True))
    session.add(Product(id=1, name="양파", category_id="veg", unit="kg"))
    session.add(Product(id=2, name="감자", unit="kg"))  # no category
    session.flush()

    now = datetime.utcnow()

    # Normal prices + outliers
    normal_prices = [1500, 1550, 1600, 1480, 1520, 1580, 1510, 1490]
    outlier_prices = [100, 9999]  # clear outliers
    all_prices = normal_prices + outlier_prices

    for i, price in enumerate(all_prices):
        session.add(BaselinePrice(
            product_id=1,
            price=price,
            source="kamis",
            unit="kg",
            recorded_at=now - timedelta(days=i),
        ))

    # Old data for cleanup test
    for i in range(5):
        session.add(BaselinePrice(
            product_id=1,
            price=1400,
            source="old",
            unit="kg",
            recorded_at=now - timedelta(days=200 + i),
        ))
        session.add(DiscountHistory(
            product_id=1,
            price=1300,
            source="emart",
            crawled_at=now - timedelta(days=200 + i),
        ))

    # Duplicates in products
    session.add(Product(id=3, name="양파", unit="kg"))  # duplicate name

    session.commit()
    return session


class TestCheckPriceOutliers:
    def test_detects_outliers(self, seeded_session):
        result = check_price_outliers(seeded_session, 1)
        assert result["total_prices"] == 15  # 10 normal range + 5 old
        assert result["outliers_count"] > 0
        outlier_prices = {o["price"] for o in result["outliers"]}
        # 100 and 9999 should be detected as outliers
        assert 100 in outlier_prices or 9999 in outlier_prices

    def test_insufficient_data(self, session):
        session.add(Product(id=99, name="적은데이터", unit="개"))
        session.add(BaselinePrice(
            product_id=99, price=1000, source="test", unit="개",
            recorded_at=datetime.utcnow(),
        ))
        session.commit()
        result = check_price_outliers(session, 99)
        assert result["message"] == "데이터 부족"


class TestFindDuplicates:
    def test_finds_name_duplicates(self, seeded_session):
        result = find_duplicates(seeded_session, "products", ["name"])
        assert len(result) > 0
        dup_names = {r["name"] for r in result}
        assert "양파" in dup_names

    def test_unknown_table(self, seeded_session):
        result = find_duplicates(seeded_session, "nonexistent_table", ["id"])
        assert result == []

    def test_no_duplicates(self, seeded_session):
        result = find_duplicates(seeded_session, "categories", ["name"])
        assert result == []


class TestValidateCrawlData:
    def test_valid_data(self):
        items = [
            {"name": "양파", "price": 1500, "source": "emart"},
            {"name": "감자", "price": 2000, "source": "homeplus"},
        ]
        result = validate_crawl_data(items)
        assert result["total"] == 2
        assert result["valid"] == 2
        assert result["invalid"] == 0

    def test_invalid_data(self):
        items = [
            {"name": "양파", "price": 1500, "source": "emart"},
            {"name": "감자", "source": "homeplus"},  # missing price
            {"price": 1000, "source": "lottemart"},  # missing name
            {"name": "당근", "price": -100, "source": "x"},  # negative price
        ]
        result = validate_crawl_data(items)
        assert result["total"] == 4
        assert result["valid"] == 1
        assert result["invalid"] == 3

    def test_empty_list(self):
        result = validate_crawl_data([])
        assert result["total"] == 0
        assert result["valid"] == 0


class TestGenerateQualityReport:
    def test_report(self, seeded_session):
        report = generate_quality_report(seeded_session)
        assert report["counts"]["products"] == 3
        assert report["counts"]["baseline_prices"] == 15
        assert report["counts"]["categories"] == 1
        assert report["quality"]["products_without_category"] == 2  # 감자 + 양파(dup)
        assert "generated_at" in report


class TestCleanupStaleData:
    def test_removes_old_data(self, seeded_session):
        # Count before
        from sqlalchemy import select, func
        before_baseline = seeded_session.execute(
            select(func.count()).select_from(BaselinePrice)
        ).scalar()

        result = cleanup_stale_data(seeded_session, days=180)
        assert result["baseline_deleted"] > 0
        assert result["discount_deleted"] > 0

        # Count after
        after_baseline = seeded_session.execute(
            select(func.count()).select_from(BaselinePrice)
        ).scalar()
        assert after_baseline < before_baseline

    def test_no_stale_data(self, session):
        result = cleanup_stale_data(session, days=180)
        assert result["baseline_deleted"] == 0
        assert result["discount_deleted"] == 0
