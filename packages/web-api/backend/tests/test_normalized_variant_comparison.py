"""Current comparison must keep price, variant and observation time together."""
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routes.products import router
from services.catalog_storage import PublicCatalogStore


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / 'variant-comparison.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE unified_categories (id TEXT, name_ko TEXT);
            INSERT INTO unified_categories VALUES ('tuna', '참치통조림');
            CREATE TABLE normalized_canonical_products (
                public_product_id TEXT, unified_category_id TEXT, canonical_name TEXT,
                brand TEXT, attributes TEXT, primary_image_url TEXT, is_active INTEGER);
            INSERT INTO normalized_canonical_products VALUES ('prod-tuna', 'tuna', '검증 참치', '', '{}', '', 1);
            CREATE TABLE normalized_product_variants (
                public_variant_id TEXT, public_product_id TEXT, variant_name TEXT,
                package_quantity REAL, package_unit TEXT, bundle_count INTEGER,
                display_unit TEXT, is_active INTEGER);
            INSERT INTO normalized_product_variants VALUES ('var-a', 'prod-tuna', '90g 4캔', 90, 'g', 4, '90g×4', 1);
            INSERT INTO normalized_product_variants VALUES ('var-b', 'prod-tuna', '250g 1캔', 250, 'g', 1, '250g', 1);
            CREATE TABLE normalized_source_listings (
                public_source_listing_id TEXT, public_variant_id TEXT, source_name TEXT,
                source_record_key TEXT, source_title TEXT, is_active INTEGER);
            INSERT INTO normalized_source_listings VALUES ('listing-a', 'var-a', 'homeplus', 'a', '검증 참치 90g×4', 1);
            INSERT INTO normalized_source_listings VALUES ('listing-b', 'var-b', 'emart', 'b', '검증 참치 250g', 1);
            CREATE TABLE normalized_offer_events (
                public_offer_event_id TEXT, public_source_listing_id TEXT, price REAL,
                price_state TEXT, promotion_type TEXT, raw_evidence TEXT,
                crawled_at TEXT, offer_state TEXT);
            INSERT INTO normalized_offer_events VALUES ('old-a', 'listing-a', 1000, 'normal', 'final_price', '{}', '2026-09-01', 'active');
            INSERT INTO normalized_offer_events VALUES ('latest-a', 'listing-a', 9000, 'normal', 'final_price', '{}', '2026-09-03', 'active');
            INSERT INTO normalized_offer_events VALUES ('latest-b', 'listing-b', 4000, 'normal', 'final_price', '{}', '2026-09-03', 'active');
        ''')
    return PublicCatalogStore(path)


def client_for(catalog):
    app = FastAPI()
    app.state.storage = SimpleNamespace(get_product_detail=catalog.get_normalized_product_detail)
    app.include_router(router, prefix='/products')
    return TestClient(app)


def test_card_pairs_current_best_price_with_its_own_variant(catalog):
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['price'] == 4000
    assert detail['source'] == 'emart'
    assert detail['unit'] == '250g'
    assert detail['best_offer']['variant_id'] == 'var-b'
    # Full detail still retains the prior observation.
    assert len(detail['variants'][0]['listings'][0]['offers']) == 2


def test_compare_uses_latest_per_listing_while_history_keeps_every_event(catalog):
    with client_for(catalog) as client:
        response = client.get('/products/prod-tuna/price-compare')
        assert response.status_code == 200
        rows = response.json()['data']
        assert [(r['id'], r['total_price'], r['total_quantity'], r['per_100g']) for r in rows] == [
            ('latest-b', 4000, 250, 1600), ('latest-a', 9000, 360, 2500),
        ]
        assert rows[1]['per_item'] == 2250
        assert rows[1]['bundle_count'] == 4
        history = client.get('/products/prod-tuna/price-history').json()['data']
        assert len(history) == 3
        assert sorted(row['price'] for row in history) == [1000, 4000, 9000]


def test_latest_uncalculable_offer_does_not_resurrect_old_sale(catalog):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_offer_events SET promotion_type='checkout_discount' WHERE public_offer_event_id='latest-a'")
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['best_offer']['id'] == 'latest-b'
    with client_for(catalog) as client:
        rows = client.get('/products/prod-tuna/price-compare').json()['data']
        assert [row['id'] for row in rows] == ['latest-b']


def test_missing_source_display_uses_verified_winning_variant_dimensions(catalog):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_product_variants SET display_unit='' WHERE public_variant_id='var-a'")
        db.execute("UPDATE normalized_offer_events SET price=3000 WHERE public_offer_event_id='latest-a'")
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['unit'] == '90g×4'
    assert detail['price'] == 3000
