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


@pytest.fixture
def normalized_management_client(tmp_path, monkeypatch):
    """Isolated history graph; legacy tables intentionally contain no products."""
    from copy import deepcopy
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.auth import require_viewer
    from api.routes import products, prices
    from core.reviewed_content_quantities import REVIEWED_SOURCE_COMPONENT_LISTINGS

    engine = create_engine(f"sqlite:///{tmp_path / 'management.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    review = deepcopy(next(item for item in REVIEWED_SOURCE_COMPONENT_LISTINGS if not item.get('eligibility_hold_reason')))
    vector_attrs = {'quantity_basis': 'reviewed_source_component_vector_v1',
        'scalar_basis': 'one_complete_declared_vector_not_piece_count',
        'source_components': review['components'], 'source_component_listing': review}
    null_attrs = {'physical_purpose': 'declared specification only', 'package_components': [{'mass_g': 150}],
        'explicit_listing_quantity_review': {'title': 'copied unregistered proof'}}
    terms = {'source_condition_kind': 'source_quote_purchase_conditions_unverified',
        'source_quote_currency': None, 'currency_unconfirmed': True,
        'source_minimum_purchase_quantity': 1, 'payable_price_unconfirmed': True,
        'membership_required': None, 'coupon_required': None}
    with Session(engine) as session, session.begin():
        session.add(UnifiedCategory(id='viewer.leaf', slug='viewer-leaf', name_ko='조회 분류', level=0))
        session.add_all([
            NormalizedCanonicalProduct(public_product_id='prod-null', canonical_name='100% source declaration',
                unified_category_id='viewer.leaf', aliases=['literal_alias'], keywords=['keyword'], is_active=False),
            NormalizedCanonicalProduct(public_product_id='prod-vector', canonical_name=review['title'], is_active=True),
        ])
        session.flush()
        session.add_all([
            NormalizedProductVariant(public_variant_id='var-null', public_product_id='prod-null', variant_name='150g specification',
                package_quantity=None, package_unit=None, standard_unit=None, display_unit='150g specification', attributes=null_attrs),
            NormalizedProductVariant(public_variant_id='var-vector', public_product_id='prod-vector', variant_name='declared vector',
                package_quantity=1, package_unit='세트', bundle_count=1, standard_unit=None, attributes=vector_attrs),
        ])
        session.flush()
        session.add(NormalizedSourceListing(public_source_listing_id='listing-native', public_variant_id='var-null',
            source_name='homeplus', source_record_key='070914500', source_title='original title 1P 150g',
            source_unit_text='1P', source_url='https://example.test/native/070914500', is_active=False))
        session.flush()
        session.add_all([
            NormalizedOfferEvent(public_offer_event_id='event-old', public_source_listing_id='listing-native', price_state='confirmed',
                promotion_type='unknown', price=2190, original_price=3000, price_per_100g=1460, standard_unit_price=1460,
                discount_rate=27, offer_state='pending_review', crawled_at=datetime(2026, 10, 1, 23, 59, 59, 999999),
                valid_to=datetime(2026, 9, 30), raw_record_id='raw-old', raw_evidence={'promotion_conditions': terms},
                audit_provenance={'source_hash': 'original'}),
            NormalizedOfferEvent(public_offer_event_id='event-changed', public_source_listing_id='listing-native', price_state='confirmed',
                promotion_type='unknown', price=2380, offer_state='active', crawled_at=datetime(2026, 10, 1),
                raw_evidence={'promotion_conditions': {'source_quote_currency': 'KRW', 'required_selection_quantity': 3,
                    'conditional_free_quantity': 1, 'payable_price_unconfirmed': True},
                    'observation_receipt_eligible': False, 'observation_receipt_reason': 'source_period_expired'}),
            NormalizedOfferEvent(public_offer_event_id='event-null', public_source_listing_id='listing-native', price_state='unknown',
                promotion_type='unknown', price=None, offer_state='rejected', crawled_at=datetime(2026, 10, 2)),
        ])
    monkeypatch.setattr(products, 'get_session', lambda: Session(engine))
    monkeypatch.setattr(prices, 'get_session', lambda: Session(engine))
    app = FastAPI()
    app.include_router(products.router, prefix='/api')
    app.include_router(prices.router, prefix='/api')
    app.dependency_overrides[require_viewer] = lambda: {'role': 'viewer', 'id': 'synthetic-viewer'}
    with TestClient(app) as client:
        yield client, app, null_attrs, review
    engine.dispose()


def test_normalized_management_products_preserve_null_and_valid_vector(normalized_management_client):
    client, _, null_attrs, review = normalized_management_client
    result = client.get('/api/products/normalized').json()
    assert result['source_scope'] == 'admin_normalized_catalog' and result['read_only'] is True
    assert result['total'] == 2
    null_row = next(row for row in result['items'] if row['public_product_id'] == 'prod-null')
    variant = null_row['variants'][0]
    assert null_row['is_active'] is False and null_row['category_name'] == '조회 분류'
    assert variant['package_quantity'] is None and variant['package_unit'] is None
    assert variant['display_unit'] == '150g specification' and variant['attributes'] == null_attrs
    assert variant['quantity_components'] is None and variant['quantity_comparison_reason'] == 'quantity_evidence_unverified'
    assert variant['source_listings'][0]['public_source_listing_id'] == 'listing-native'
    assert variant['source_listings'][0]['source_record_key'] == '070914500'
    vector = next(row for row in result['items'] if row['public_product_id'] == 'prod-vector')['variants'][0]
    assert vector['quantity_components'] == review['components'] and vector['standard_unit'] is None
    assert client.get('/api/products/normalized', params={'q': '%'}).json()['total'] == 1
    assert client.get('/api/products/normalized', params={'q': 'LITERAL_ALIAS', 'is_active': False}).json()['total'] == 1
    page = client.get('/api/products/normalized', params={'page': 2, 'per_page': 1}).json()
    assert page['total'] == 2 and page['total_pages'] == 2 and len(page['items']) == 1


def test_normalized_management_history_keeps_quotes_states_and_period(normalized_management_client):
    client, _, null_attrs, _ = normalized_management_client
    result = client.get('/api/prices/normalized', params={'public_variant_id': 'var-null',
        'date_from': '2026-10-01', 'date_to': '2026-10-01'}).json()
    assert result['history_scope'] == 'all_stored_offer_states' and result['date_filter_basis'] == 'source_observed_at_utc'
    assert result['total'] == 2 and [row['public_offer_event_id'] for row in result['items']] == ['event-old', 'event-changed']
    old, changed = result['items']
    assert old['observed_quote'] == 2190 and changed['observed_quote'] == 2380
    assert old['public_product_id'] == changed['public_product_id'] == 'prod-null'
    assert old['public_source_listing_id'] == changed['public_source_listing_id'] == 'listing-native'
    assert old['offer_state'] == 'pending_review' and changed['offer_state'] == 'active'
    assert old['crawled_at'] == '2026-10-01T23:59:59.999999+00:00' and old['valid_to'] == '2026-09-30T00:00:00+00:00'
    assert old['recorded_price_per_100g'] == old['recorded_standard_unit_price'] == 1460
    assert old['recorded_discount_rate'] == 27 and 'price_per_100g' not in old
    assert old['raw_record_id'] == 'raw-old' and old['audit_provenance'] == {'source_hash': 'original'}
    assert old['source_quote_currency'] is None and old['quote_currency_status'] == 'source_unconfirmed'
    assert old['promotion_conditions']['source_minimum_purchase_quantity'] == 1
    assert old['promotion_conditions']['membership_required'] is None and old['variant_attributes'] == null_attrs
    assert old['receipt_evaluation'] == 'not_evaluated_admin_history' and old['observation_receipt_eligible'] is None
    assert changed['source_quote_currency'] == 'KRW' and changed['quote_currency_status'] == 'source_declared'
    assert changed['promotion_conditions']['required_selection_quantity'] == 3
    assert changed['observation_receipt_eligible'] is False and changed['observation_receipt_reason'] == 'source_period_expired'
    assert 'payable_price' not in old and 'received_quantity' not in old and 'current_price' not in old
    all_rows = client.get('/api/prices/normalized').json()
    null_quote = all_rows['items'][0]
    assert all_rows['total'] == 3 and null_quote['observed_quote'] is None and null_quote['offer_state'] == 'rejected'
    assert null_quote['quote_currency_status'] == 'not_recorded' and 'source_quote_currency' not in null_quote
    filtered = client.get('/api/prices/normalized', params={'source_name': 'homeplus', 'offer_state': 'pending_review', 'per_page': 1}).json()
    assert filtered['total'] == 1 and filtered['items'][0]['public_offer_event_id'] == 'event-old'


def test_normalized_management_readonly_auth_and_bounded_filters(normalized_management_client):
    from api.auth import require_viewer
    client, app, _, _ = normalized_management_client
    for path in ('/api/products/normalized', '/api/prices/normalized'):
        route = next(route for route in app.routes if route.path == path)
        assert route.methods == {'GET'} and any(dep.call is require_viewer for dep in route.dependant.dependencies)
        assert client.get(path, params={'page': 0}).status_code == 422
        assert client.get(path, params={'per_page': 201}).status_code == 422
    assert client.get('/api/prices/normalized', params={'date_from': '2026-10-02', 'date_to': '2026-10-01'}).status_code == 422
    assert client.get('/api/prices/normalized', params={'date_from': 'not-a-date'}).status_code == 422
    empty = client.get('/api/prices/normalized', params={'public_source_listing_id': 'missing'}).json()
    assert empty['items'] == [] and empty['total'] == empty['total_pages'] == 0
    # The editable legacy namespace still reports its actual empty tables.
    assert client.get('/api/prices/').json()['total'] == 0
