from __future__ import annotations

import sqlite3
from datetime import datetime
import pytest

from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.orm import Session

from services import public_snapshot_v2
from storage.models import (
    Base,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    UnifiedCategory,
)


@pytest.fixture
def review_source(tmp_path):
    """Source history and review-only rows live in a disposable FK-checked DB."""
    source_path = tmp_path / "review-source.sqlite"
    engine = create_engine(f"sqlite:///{source_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    def populate(pending_count):
        observed_at = datetime(2026, 9, 3)
        with engine.begin() as connection:
            connection.execute(insert(UnifiedCategory), {
                "id": "leaf", "slug": "leaf", "name_ko": "리프", "level": 0,
                "created_at": observed_at, "updated_at": observed_at,
            })
            for name, active in (("current", True), ("history", False)):
                connection.execute(insert(NormalizedCanonicalProduct), {
                    "public_product_id": f"product-{name}", "unified_category_id": "leaf",
                    "canonical_name": name, "is_active": active,
                    "created_at": observed_at, "updated_at": observed_at,
                })
                connection.execute(insert(NormalizedProductVariant), {
                    "public_variant_id": f"variant-{name}", "public_product_id": f"product-{name}",
                    "variant_name": "100g", "package_quantity": 100, "package_unit": "g",
                    "is_active": active,
                    "created_at": observed_at, "updated_at": observed_at,
                })
                connection.execute(insert(NormalizedSourceListing), {
                    "public_source_listing_id": f"listing-{name}", "public_variant_id": f"variant-{name}",
                    "source_name": "emart", "source_title": name, "is_active": active,
                    "created_at": observed_at, "updated_at": observed_at,
                })
            connection.execute(insert(NormalizedWeekBucket), {
                "public_week_bucket_id": "week-one", "week_start": datetime(2026, 8, 31),
                "week_end": datetime(2026, 9, 7), "generated_at": observed_at,
            })
            # There is no offer-state enum. Historical strings must survive;
            # only the explicit internal pending_review state is excluded.
            states = [("active", "current"), ("expired", "history"), ("withdrawn", "history")]
            states += [("pending_review", "current")] * pending_count
            for index, (state, parent) in enumerate(states):
                offer_id = f"offer-{index}"
                connection.execute(insert(NormalizedOfferEvent), {
                    "public_offer_event_id": offer_id,
                    "public_source_listing_id": f"listing-{parent}",
                    "price_state": "normal", "promotion_type": "final_price",
                    "price": 1000, "offer_state": state,
                    "raw_evidence": {"review_only": state == "pending_review"},
                    "crawled_at": observed_at,
                })
                connection.execute(insert(NormalizedOfferWeekLink), {
                    "public_offer_event_id": offer_id, "public_week_bucket_id": "week-one",
                    "observed_min_price": 1000, "observed_max_price": 1000,
                    "created_at": observed_at,
                })
        return engine, source_path

    yield populate
    engine.dispose()


@pytest.mark.parametrize("pending_count", [1, 705])
def test_snapshot_excludes_pending_offers_and_links_but_preserves_history(
    tmp_path, review_source, pending_count,
):
    source, source_path = review_source(pending_count)
    before = source_path.read_bytes()
    target = tmp_path / "unpublished.sqlite"
    with source.connect() as connection:
        connection.execute(text("PRAGMA query_only=ON"))
        counts = public_snapshot_v2._write_snapshot_file(target, connection, revision=1)

    assert source_path.read_bytes() == before
    assert counts["normalized_canonical_products"] == 2
    assert counts["normalized_offer_events"] == 3
    assert counts["normalized_offer_week_links"] == 3
    assert public_snapshot_v2.validate_public_snapshot(target)["revision"] == 1
    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert dict(connection.execute(
            "SELECT offer_state, COUNT(*) FROM normalized_offer_events GROUP BY offer_state"
        )) == {"active": 1, "expired": 1, "withdrawn": 1}
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_canonical_products WHERE is_active=0"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_product_variants WHERE is_active=0"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM normalized_source_listings WHERE is_active=0"
        ).fetchone()[0] == 1
    connection.close()
    with source.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM normalized_offer_events WHERE offer_state='pending_review'"
        )).scalar_one() == pending_count


def test_snapshot_validator_rejects_pending_review_in_otherwise_valid_history(
    tmp_path, review_source,
):
    source, _source_path = review_source(1)
    target = tmp_path / "mixed.sqlite"
    with source.connect() as connection:
        public_snapshot_v2._write_snapshot_file(target, connection, revision=1)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE normalized_offer_events SET offer_state='pending_review' "
            "WHERE offer_state='active'"
        )
        connection.commit()
    connection.close()
    before = target.read_bytes()

    with pytest.raises(ValueError, match="pending_review offers are not publishable: 1"):
        public_snapshot_v2.validate_public_snapshot(target)

    assert target.read_bytes() == before


def test_public_snapshot_contains_normalized_catalog_tables(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1",
            unified_category_id="food",
            canonical_name="테스트 상품",
            aliases=[], keywords=[], attributes={},
        ))
        session.commit()

    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    result = public_snapshot_v2.build_public_snapshot(target)

    assert result["row_counts"]["normalized_canonical_products"] == 1
    with sqlite3.connect(target) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "normalized_product_variants" in tables
        assert connection.execute("SELECT unified_category_id FROM normalized_canonical_products").fetchone()[0] == "food"


def test_public_snapshot_keeps_one_validated_rollback_version(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1", unified_category_id="food",
            canonical_name="첫 버전", aliases=[], keywords=[], attributes={},
        ))
        session.commit()

    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    public_snapshot_v2.build_public_snapshot(target)

    with Session(source) as session:
        session.get(NormalizedCanonicalProduct, "prod-1").canonical_name = "둘째 버전"
        session.commit()
    second = public_snapshot_v2.build_public_snapshot(target)

    assert second["previous_path"].endswith(".previous")
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT canonical_name FROM normalized_canonical_products"
        ).fetchone()[0] == "둘째 버전"
    connection.close()

    public_snapshot_v2.rollback_public_snapshot(target)
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT canonical_name FROM normalized_canonical_products"
        ).fetchone()[0] == "첫 버전"
    connection.close()


def test_snapshot_validation_rejects_missing_product_category(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="leaf", slug="leaf", name_ko="리프", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1", unified_category_id="leaf",
            canonical_name="상품", aliases=[], keywords=[], attributes={},
        ))
        session.commit()
    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    public_snapshot_v2.build_public_snapshot(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE normalized_canonical_products SET unified_category_id='missing'"
        )
        connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="leaf category"):
        public_snapshot_v2.validate_public_snapshot(target)
