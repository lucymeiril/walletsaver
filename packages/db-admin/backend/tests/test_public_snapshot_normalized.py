from __future__ import annotations

import sqlite3
from datetime import datetime
import pytest

from sqlalchemy import create_engine, event, insert, select, text
from sqlalchemy.orm import Session

from services import public_snapshot_v2
from storage.models import (
    Base,
    MatchingEntry,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    UnifiedCategory,
)


@pytest.fixture
def matched_offer_source():
    from core.match_key import build_match_key
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    row = {'name': '커피 캡슐 80개입', 'source_title': '커피 캡슐 80개입',
           'source': 'costco', 'source_record_key': '111', 'brand': '__no_brand__',
           'pack_qty': 80, 'pack_unit': '개입', 'package_quantity': 80, 'package_unit': '개입',
           'source_url': 'https://www.costco.co.kr/Coffee/p/111', 'sale_price': 31000,
           'crawled_at': '2026-10-03T08:00:00Z',
           'public_product_id': 'prod-approved', 'public_variant_id': 'var-approved'}
    row['match_key'] = build_match_key(row['brand'], row['name'], 80, '개')
    with Session(engine) as session, session.begin():
        session.add(NormalizedCanonicalProduct(public_product_id='prod-approved', canonical_name='검토된 커피', brand='승인브랜드'))
        session.flush()
        session.add(NormalizedProductVariant(public_variant_id='var-approved', public_product_id='prod-approved',
            variant_name='80개', package_quantity=80, package_unit='개', bundle_count=1,
            attributes={'specification_basis': 'source_structured_and_explicit_text'}))
        session.flush()
        session.add(NormalizedSourceListing(public_source_listing_id='listing-approved',
            public_variant_id='var-approved', source_name='costco', source_record_key='111',
            source_title=row['source_title'], source_url=row['source_url']))
        session.add(MatchingEntry(match_key=build_match_key(row['brand'], row['name'], 80, '개'),
            public_product_id='prod-approved', public_variant_id='var-approved', confidence=.95, source='human'))
    yield engine, row
    engine.dispose()


def test_recollected_public_offer_preserves_identities_and_exact_retry(matched_offer_source):
    from services.normalized_mart3 import publish_matched_offer_observations
    engine, row = matched_offer_source
    with Session(engine) as session, session.begin():
        first = publish_matched_offer_observations(session, [row])[0]
        retry = publish_matched_offer_observations(session, [row])[0]
        changed = publish_matched_offer_observations(session, [{**row, 'sale_price': 32000}])[0]
        assert first['inserted'] and not retry['inserted'] and changed['inserted']
        assert first['public_offer_event_id'] == retry['public_offer_event_id'] != changed['public_offer_event_id']
        offers = session.execute(select(NormalizedOfferEvent)).scalars().all()
        assert sorted(offer.price for offer in offers) == [31000, 32000]
        assert all(offer.standard_unit_price is None and offer.price_per_100g is None for offer in offers)
        assert session.get(NormalizedCanonicalProduct, 'prod-approved').canonical_name == '검토된 커피'
        assert session.get(NormalizedProductVariant, 'var-approved').package_quantity == 80
        assert session.get(NormalizedSourceListing, 'listing-approved').source_title == row['source_title']
        assert session.execute(text('SELECT COUNT(*) FROM products')).scalar_one() == 0
        assert session.execute(text('SELECT COUNT(*) FROM normalized_canonical_products')).scalar_one() == 1
        assert session.execute(text('SELECT COUNT(*) FROM normalized_product_variants')).scalar_one() == 1
        assert session.execute(text('SELECT COUNT(*) FROM normalized_source_listings')).scalar_one() == 1


@pytest.mark.parametrize('changes', [
    {'source_title': '커피 캡슐 다른 맛 80개입'},
    {'source_record_key': 'other-sku'},
    {'source_url': 'https://www.costco.co.kr/Coffee/p/other'},
    {'package_quantity': 81},
    {'public_product_id': 'prod-other'},
    {'public_source_listing_id': 'listing-other'},
])
def test_recollected_offer_revalidates_source_despite_submitted_hit(matched_offer_source, changes):
    from services.normalized_mart3 import publish_matched_offer_observations
    engine, row = matched_offer_source
    with Session(engine) as session, session.begin():
        with pytest.raises(ValueError):
            publish_matched_offer_observations(session, [{**row, 'matching_status': 'hit', **changes}])
        assert session.execute(text('SELECT COUNT(*) FROM normalized_offer_events')).scalar_one() == 0


def test_recollected_conditional_quote_remains_pending(matched_offer_source):
    from services.normalized_mart3 import publish_matched_offer_observations
    engine, row = matched_offer_source
    with Session(engine) as session, session.begin():
        placed = publish_matched_offer_observations(session, [{**row, 'coupon_required': True}])[0]
        offer = session.get(NormalizedOfferEvent, placed['public_offer_event_id'])
        assert offer.price == 31000 and offer.offer_state == 'pending_review'
        assert offer.promotion_type == 'unknown' and offer.standard_unit_price is None
        assert offer.raw_evidence['promotion_conditions']['coupon_required'] is True


def test_recollected_partial_purchase_quote_retains_reviewable_original_observation(matched_offer_source):
    from services.normalized_mart3 import publish_matched_offer_observations
    from services.catalog_bundle import _review_observations
    engine, row = matched_offer_source
    conditions = {'source_condition_kind': 'source_quote_purchase_conditions_unverified',
                  'payable_price_unconfirmed': True,
                  'minimum_purchase_quantity_unconfirmed': True,
                  'coupon_application_unconfirmed': True}
    row = {**row, 'event_name': None, 'promotion_conditions': conditions}
    with Session(engine) as session, session.begin():
        first = publish_matched_offer_observations(session, [row])[0]
        retry = publish_matched_offer_observations(session, [row])[0]
        offer = session.get(NormalizedOfferEvent, first['public_offer_event_id'])
        assert first['inserted'] and not retry['inserted']
        assert offer.price == 31000 and offer.offer_state == 'pending_review'
        assert offer.promotion_type == 'unknown'
        assert offer.standard_unit_price is None and offer.price_per_100g is None
        assert offer.raw_evidence['promotion_conditions']['promotion_conditions'] == conditions
        bindings = _review_observations(offer.raw_evidence)
        assert len(bindings) == 1 and bindings[0]['raw_record_id'].startswith('recollected:')
        assert offer.raw_evidence['observations'][0]['raw_payload'] == row


def test_recollected_offer_uses_aware_source_or_explicit_receipt_time(matched_offer_source):
    from services.normalized_mart3 import publish_matched_offer_observations
    engine, row = matched_offer_source
    with Session(engine) as session, session.begin():
        offset = publish_matched_offer_observations(session, [{**row, 'crawled_at': '2026-10-03T17:00:00+09:00'}])[0]
        assert session.get(NormalizedOfferEvent, offset['public_offer_event_id']).crawled_at == datetime(2026, 10, 3, 8)
        with pytest.raises(ValueError, match='timestamp missing'):
            publish_matched_offer_observations(session, [{**row, 'crawled_at': '2026-10-03T17:00:00'}])
        receipt = publish_matched_offer_observations(session, [{**row, 'crawled_at': None}], observed_at=datetime(2026, 10, 3, 8, 1))[0]
        offer = session.get(NormalizedOfferEvent, receipt['public_offer_event_id'])
        assert offer.crawled_at == datetime(2026, 10, 3, 8, 1)
        assert offer.raw_evidence['observations'][0]['timestamp_source'] == 'explicit_receipt_time'


def test_recollected_offer_accepts_only_server_canonical_brand_enrichment(matched_offer_source):
    from services.normalized_mart3 import publish_matched_offer_observations
    engine, row = matched_offer_source
    with Session(engine) as session, session.begin():
        assert publish_matched_offer_observations(session, [{**row, 'brand': '승인브랜드'}])[0]['inserted']
        for changed in ({'brand': '다른브랜드'}, {'brand': '승인브랜드', 'package_quantity': 81}):
            with pytest.raises(ValueError):
                publish_matched_offer_observations(session, [{**row, **changed}])


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


@pytest.mark.parametrize('kind', ['selection_parent', 'outer_set_count', 'nonexact_contents', 'entitlement', 'partial_retail'])
def test_snapshot_keeps_selectable_parent_private_even_if_its_quote_state_is_active(tmp_path, review_source, kind):
    source, source_path = review_source(1)
    proof = ({'source_parent_selection': {'identity_scope': 'source_selectable_parent_observation'}}
             if kind == 'selection_parent' else {'measurement_role': 'declared_outer_set_count' if kind == 'outer_set_count' else 'declared_incomplete_retail_package_specification' if kind == 'partial_retail' else 'declared_incomplete_entitlement_specification' if kind == 'entitlement' else 'declared_nonexact_mass_specification'})
    with source.begin() as connection:
        connection.execute(NormalizedProductVariant.__table__.update()
            .where(NormalizedProductVariant.public_variant_id == 'variant-current')
            .values(attributes={'explicit_listing_quantity_review': proof}))
    before = source_path.read_bytes()
    target = tmp_path / 'parent-private.sqlite'
    with source.connect() as connection:
        counts = public_snapshot_v2._write_snapshot_file(target, connection, revision=1)
    assert source_path.read_bytes() == before
    assert counts['normalized_offer_events'] == 2 and counts['normalized_offer_week_links'] == 2
    with sqlite3.connect(target) as connection:
        assert connection.execute('SELECT public_offer_event_id FROM normalized_offer_events ORDER BY 1').fetchall() == [('offer-1',), ('offer-2',)]
    # Unrelated expired/withdrawn history is retained, not collapsed to latest.
    assert public_snapshot_v2.validate_public_snapshot(target)['revision'] == 1


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
