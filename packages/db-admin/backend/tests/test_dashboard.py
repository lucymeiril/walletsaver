"""Dashboard source-scope regressions using isolated catalog fixtures."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes import dashboard
from storage.models import (Base, Category, Product, BaselinePrice, Keyword, UnifiedCategory,
    NormalizedCanonicalProduct, NormalizedProductVariant, NormalizedSourceListing,
    NormalizedOfferEvent, CrawlLog, CrawlStatus, PendingIngestion, IngestionStatus)


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine)()
    monkeypatch.setattr(dashboard, "get_session", lambda: value)
    yield value
    value.close()
    engine.dispose()


def test_normalized_dashboard_counts_admin_history_and_source_clocks_with_empty_legacy(session):
    now = datetime.utcnow()
    observed = datetime(2020, 1, 2, 3, 4, 5)
    session.add(UnifiedCategory(id="food", name_ko="식품", slug="food", level=0))
    session.add(UnifiedCategory(id="food.yogurt", parent_id="food", name_ko="요거트", slug="yogurt", level=1))
    for identity, active in (("active", True), ("inactive", False)):
        session.add(NormalizedCanonicalProduct(public_product_id=identity, canonical_name=identity,
            unified_category_id="food.yogurt", is_active=active, created_at=now, updated_at=now))
        session.add(NormalizedProductVariant(public_variant_id="v-"+identity, public_product_id=identity,
            variant_name=identity, package_quantity=100, package_unit="g", is_active=active))
    for identity, source, variant in (("a", "homeplus", "active"), ("b", "홈플러스", "inactive"), ("c", "costco", "active")):
        session.add(NormalizedSourceListing(public_source_listing_id=identity, public_variant_id="v-"+variant,
            source_name=source, source_title=identity, is_active=variant=="active"))
    for identity, listing, state, price in (("one", "a", "active", 2190),
                                          ("two", "a", "pending_review", 40990),
                                          ("three", "b", "expired", 1000)):
        session.add(NormalizedOfferEvent(public_offer_event_id=identity, public_source_listing_id=listing,
            price_state="final_price", promotion_type="none", price=price, offer_state=state,
            crawled_at=observed, valid_to=observed if state=="expired" else None))
    session.add(Keyword(word="요거트", unified_category_id="food.yogurt", is_active=True))
    session.add(CrawlLog(crawler_name="real-failure", status=CrawlStatus.FAILED, items_found=9,
                        items_saved=0, started_at=now, error_message="actual failure"))
    session.add(CrawlLog(crawler_name="real-success", status=CrawlStatus.SUCCESS, items_found=4,
                        items_saved=3, started_at=now))
    session.add(PendingIngestion(crawler_name="submitted", crawl_status="success", schema_type="DiscountItem",
        items_count=1, items_json="[]", status=IngestionStatus.APPROVED, crawled_at=now))
    session.commit()

    result = dashboard.dashboard_stats()
    assert result["source_scope"] == "admin_normalized_catalog"
    assert result["publicSnapshotCounts"] is None
    assert result["totalProducts"] == 1
    assert result["catalogCounts"]["products"] == {"total": 2, "active": 1, "inactive": 1}
    assert result["totalPriceRecords"] == 3
    assert result["offerStates"] == {"active": 1, "pending_review": 1, "expired": 1}
    assert result["totalCategories"] == 2
    assert result["totalKeywords"] == 1
    assert result["lastUpdated"] == "2020-01-02T03:04:05+00:00"
    assert result["lastCrawlAt"] != result["lastUpdated"]
    assert result["changes"] == {"products": None, "priceRecords": 0, "categories": None, "keywords": None}
    assert result["qualityScore"] is None
    assert result["qualityDetails"]["status"] == "unavailable"
    assert all(result["qualityDetails"][key] is None for key in ("fillRate", "dupRate", "noCategoryRate"))
    freshness = {row["source"]: row for row in result["freshness"]}
    assert set(freshness) == {"homeplus", "홈플러스", "costco"}
    assert freshness["homeplus"]["status"] == "stale"
    assert freshness["homeplus"]["observationCount"] == 2
    assert freshness["costco"]["lastUpdate"] is None
    assert freshness["costco"]["hoursSince"] is None
    assert freshness["costco"]["status"] == "unknown"
    assert len(result["alerts"]) == 1
    activities = {row["source"]: row for row in result["recentIngestions"]}
    assert activities["real-failure"]["count"] == 0
    assert activities["real-failure"]["status"] == "error"
    assert activities["real-success"]["status"] == "success"
    assert activities["submitted"]["status"] == "approved"
    assert activities["submitted"]["activityKind"] == "ingestion_receipt"
    assert activities["submitted"]["countKind"] == "received"
    assert {row.public_offer_event_id: row.price for row in session.query(NormalizedOfferEvent)} == {
        "one": 2190, "two": 40990, "three": 1000}


def test_dashboard_keeps_legacy_fallback_when_no_normalized_products(session):
    session.add(Category(id="legacy", name="기존 분류", depth=0))
    session.add(Product(id=1, name="기존 상품", category_id="legacy"))
    session.add(BaselinePrice(product_id=1, price=1000, source="homeplus", unit="개", recorded_at=datetime.utcnow()))
    session.add(Keyword(word="기존 키워드", category_id="legacy"))
    session.commit()
    result = dashboard.dashboard_stats()
    assert result["totalProducts"] == 1
    assert result["totalPriceRecords"] == 1
    assert result["totalCategories"] == 1
    assert result["totalKeywords"] == 1
    assert result["qualityScore"] == 100
    assert "source_scope" not in result
