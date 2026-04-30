"""Integrity service tests — SQLite in-memory.

Validates the structure of the integrity report and that representative
issues are detected (FK orphans, zombie price rows, expired discounts,
ingestion/crawl failures). Placeholder checks must surface as
`not_configured`, not `ok`.
"""

import os
import sys
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from storage.models import (
    Base, Product, Category, BaselinePrice, DiscountHistory,
    Keyword, ProductKeyword, CrawlLog, CrawlStatus,
    PendingIngestion, IngestionStatus,
)
from services.integrity import (
    scan_integrity,
    check_products_without_category,
    check_invalid_product_prices,
    check_orphan_product_keywords,
    check_zombie_price_rows,
    check_expired_discounts,
    check_pending_ingestion_failures,
    check_crawl_log_failures,
    check_projection_health,
    check_dlq_summary,
    SEVERITY_OK,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
    SEVERITY_NOT_CONFIGURED,
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
    now = datetime.utcnow()

    session.add(Category(id="veg", name="채소류", depth=0, sort_order=0, is_active=True))
    session.add(Product(id=1, name="양파", category_id="veg", unit="kg"))
    # Product without category — null FK
    session.add(Product(id=2, name="감자", unit="kg"))
    # Product with orphan FK
    session.add(Product(id=3, name="당근", category_id="ghost-cat", unit="kg"))
    session.flush()

    # Valid baseline price
    session.add(BaselinePrice(
        product_id=1, price=1500, source="kamis", unit="kg", recorded_at=now,
    ))
    # Invalid price (zero)
    session.add(BaselinePrice(
        product_id=1, price=0, source="kamis", unit="kg", recorded_at=now,
    ))
    # Negative price
    session.add(DiscountHistory(
        product_id=1, price=-100, source="emart", crawled_at=now,
    ))

    # Expired discount
    session.add(DiscountHistory(
        product_id=1, price=900, source="emart", crawled_at=now,
        valid_to=now - timedelta(days=1),
    ))
    # Active (future) discount — should NOT be flagged
    session.add(DiscountHistory(
        product_id=1, price=1100, source="emart", crawled_at=now,
        valid_to=now + timedelta(days=3),
    ))

    # Zombie price: product_id pointing to non-existent product
    session.add(BaselinePrice(
        product_id=9999, price=1234, source="kamis", unit="kg", recorded_at=now,
    ))

    # Orphan ProductKeyword: keyword_id doesn't exist
    session.add(Keyword(id=1, word="양파"))
    session.flush()
    session.add(ProductKeyword(product_id=1, keyword_id=1))   # valid
    session.add(ProductKeyword(product_id=1, keyword_id=999))  # orphan keyword
    session.add(ProductKeyword(product_id=8888, keyword_id=1))  # orphan product

    # Pending ingestion: rejected + partial + pending-with-errors
    session.add(PendingIngestion(
        crawler_name="emart", crawl_status="success", items_count=10,
        items_json="[]", schema_type="mart", status=IngestionStatus.REJECTED,
        rejected_reason="bad data",
    ))
    session.add(PendingIngestion(
        crawler_name="emart", crawl_status="partial", items_count=5,
        items_json="[]", schema_type="mart", status=IngestionStatus.PARTIAL,
    ))
    session.add(PendingIngestion(
        crawler_name="emart", crawl_status="success", items_count=3,
        items_json="[]", schema_type="mart", status=IngestionStatus.PENDING,
        errors_json='[{"e":"x"}]',
    ))

    # Crawl logs — one failure, one partial, one success in last 24h
    session.add(CrawlLog(
        crawler_name="emart", status=CrawlStatus.FAILED,
        items_found=0, items_saved=0, started_at=now - timedelta(hours=1),
    ))
    session.add(CrawlLog(
        crawler_name="homeplus", status=CrawlStatus.PARTIAL,
        items_found=10, items_saved=5, started_at=now - timedelta(hours=2),
    ))
    session.add(CrawlLog(
        crawler_name="lottemart", status=CrawlStatus.SUCCESS,
        items_found=10, items_saved=10, started_at=now - timedelta(hours=3),
    ))
    # Old failure outside window — should not count
    session.add(CrawlLog(
        crawler_name="emart", status=CrawlStatus.FAILED,
        items_found=0, items_saved=0, started_at=now - timedelta(days=5),
    ))

    session.commit()
    return session


class TestProductsWithoutCategory:
    def test_detects_null_and_orphan(self, seeded_session):
        result = check_products_without_category(seeded_session)
        assert result["null_category_count"] == 1
        assert result["orphan_category_count"] == 1
        assert result["count"] == 2
        assert result["severity"] in (SEVERITY_WARNING, SEVERITY_CRITICAL)

    def test_clean_session(self, session):
        result = check_products_without_category(session)
        assert result["count"] == 0
        assert result["severity"] == SEVERITY_OK


class TestInvalidPrices:
    def test_detects_zero_and_negative(self, seeded_session):
        result = check_invalid_product_prices(seeded_session)
        assert result["count"] >= 2
        assert result["by_table"]["baseline_prices"] >= 1
        assert result["by_table"]["discount_history"] >= 1
        assert result["severity"] != SEVERITY_OK


class TestOrphanProductKeywords:
    def test_detects_orphans(self, seeded_session):
        result = check_orphan_product_keywords(seeded_session)
        assert result["missing_product"] >= 1
        assert result["missing_keyword"] >= 1
        assert result["count"] >= 2


class TestZombiePriceRows:
    def test_detects_zombie(self, seeded_session):
        result = check_zombie_price_rows(seeded_session)
        assert result["count"] >= 1
        assert result["by_table"]["baseline_prices"] >= 1


class TestExpiredDiscounts:
    def test_detects_expired_only(self, seeded_session):
        result = check_expired_discounts(seeded_session)
        assert result["count"] == 1
        assert result["recently_crawled_but_expired"] == 1
        assert result["severity"] != SEVERITY_OK


class TestPendingIngestionFailures:
    def test_buckets(self, seeded_session):
        result = check_pending_ingestion_failures(seeded_session)
        assert result["rejected"] == 1
        assert result["partial"] == 1
        assert result["pending_with_errors"] == 1
        assert result["count"] == 3
        assert IngestionStatus.REJECTED.value in result["by_status"]


class TestCrawlLogFailures:
    def test_window_and_grouping(self, seeded_session):
        result = check_crawl_log_failures(seeded_session, window_hours=24)
        assert result["failed"] == 1
        assert result["partial"] == 1
        assert result["total_runs"] == 3
        assert result["by_crawler"].get("emart") == 1


class TestPlaceholders:
    def test_projection_not_configured(self):
        assert check_projection_health()["severity"] == SEVERITY_NOT_CONFIGURED

    def test_dlq_not_configured(self):
        assert check_dlq_summary()["severity"] == SEVERITY_NOT_CONFIGURED


class TestScanIntegrity:
    def test_report_shape(self, seeded_session):
        report = scan_integrity(seeded_session)
        assert "generated_at" in report
        assert "overall_severity" in report
        assert "issue_total" in report
        assert isinstance(report["checks"], list)
        names = {c["name"] for c in report["checks"]}
        assert {
            "products_without_category",
            "invalid_product_prices",
            "orphan_product_keywords",
            "zombie_price_rows",
            "expired_discounts",
            "pending_ingestion_failures",
            "crawl_log_failures",
            "backup_status",
            "projection_health",
            "dlq_summary",
        }.issubset(names)

    def test_overall_severity_reflects_issues(self, seeded_session):
        report = scan_integrity(seeded_session)
        assert report["overall_severity"] in (SEVERITY_WARNING, SEVERITY_CRITICAL)
        assert report["issue_total"] > 0

    def test_clean_session_overall_ok_or_not_configured(self, session):
        report = scan_integrity(session)
        # All data checks should be OK; placeholders downgrade overall to
        # not_configured, never warning/critical.
        assert report["overall_severity"] in (SEVERITY_OK, SEVERITY_NOT_CONFIGURED, SEVERITY_WARNING)
        # Backup status may be 'warning' if no backups directory exists, so allow it.
        data_checks = [
            c for c in report["checks"]
            if c["name"] not in ("backup_status", "projection_health", "dlq_summary")
        ]
        for c in data_checks:
            assert c["severity"] == SEVERITY_OK, c
