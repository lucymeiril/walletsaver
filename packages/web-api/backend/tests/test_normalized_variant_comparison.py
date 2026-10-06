"""Current comparison must keep price, variant and observation time together."""
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routes.products import router
from services.catalog_storage import PublicCatalogStore


@pytest.mark.asyncio
async def test_promotion_history_keeps_raw_quote_separate_from_period_qualified_calculation(monkeypatch):
    from copy import deepcopy
    from api.routes import products
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 9, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(products, 'datetime', clock)
    variant = {'id':'original-variant','package_quantity':600,'package_unit':'g','bundle_count':1}
    base = {'price':8980,'price_state':'normal','offer_state':'active','promotion_type':'buy_x_get_y',
            'valid_to':'2026-09-01T15:00:00Z',
            'raw_evidence':{'promotion_conditions':{'buy_quantity':2,'free_quantity':1,'minimum_quantity':2}}}
    offers = [PublicCatalogStore._normalized_offer({**base,'public_offer_event_id':oid,'crawled_at':when}, variant)
              for oid,when in [('earlier','2026-08-31T01:46:41Z'),('later','2026-09-02T13:39:38Z')]]
    for offer in offers:
        offer['listing_id'] = 'original-listing'
    product = {'public_product_id':'prod-original','variants':[{**variant,'listings':[
        {'id':'original-listing','source':'homeplus','offers':offers}]}]}
    original = deepcopy(product)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        storage=SimpleNamespace(get_product_detail=lambda _:product))))
    result = await products.get_price_history(request, 'prod-original', days=30)
    history = {row['id']:row for row in result.data}
    assert set(history) == {'earlier','later'}
    assert all(row['price'] == row['listed_price'] == 8980 for row in history.values())
    assert all(row['variant_id'] == 'original-variant' and row['listing_id'] == 'original-listing'
               and row['promotion_conditions']['buy_quantity'] == 2 for row in history.values())
    assert history['earlier']['total_price'] == history['earlier']['comparable_price'] == 17960
    assert history['earlier']['total_quantity'] == 1800 and history['earlier']['received_package_count'] == 3
    assert history['earlier']['per_100g'] == 998 and history['earlier']['observation_receipt_eligible'] is True
    assert history['later']['total_price'] is history['later']['total_quantity'] is history['later']['per_100g'] is None
    assert history['later']['observation_receipt_eligible'] is False
    assert history['later']['observation_receipt_reason'] == 'promotion_observation_outside_period'
    assert product == original


@pytest.mark.asyncio
async def test_normalized_history_preserves_composition_reason_quotes_and_original_aggregate(monkeypatch):
    from copy import deepcopy
    from api.routes import products
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 9, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(products, 'datetime', clock)
    reason = 'heterogeneous_contents_allocation_unverified'
    product = {'public_product_id': 'prod-donut', 'variants': [
        {'id': 'var-original-scalar', 'name': '230g×4', 'listings': [
            {'id': 'listing-original', 'source': 'costco', 'offers': [
                {'id': 'offer-original', 'listing_id': 'listing-original', 'listed_price': 22990,
                 'total_price': 22990, 'comparable_price': 22990, 'total_quantity': 920,
                 'quantity_unit': 'g', 'quantity_comparison_reason': reason,
                 'quantity_basis': 'reviewed_source_component_vector_v1',
                 'scalar_basis': 'one_complete_declared_vector_not_piece_count',
                 'received_package_count_scope': 'complete_declared_vector',
                 'crawled_at': '2026-08-31T01:51:51.875403Z', 'offer_state': 'active'},
                {'id': 'offer-control', 'listing_id': 'listing-original', 'listed_price': 24000,
                 'total_price': 24000, 'comparable_price': 24000, 'total_quantity': 920,
                 'quantity_unit': 'g', 'crawled_at': '2026-09-01T01:00:00Z', 'offer_state': 'active'},
            ]},
        ]},
    ]}
    original = deepcopy(product)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        storage=SimpleNamespace(get_product_detail=lambda _id: product))))
    result = await products.get_price_history(request, 'prod-donut', days=30)
    history = {row['id']: row for row in result.data}
    assert set(history) == {'offer-original', 'offer-control'}
    assert history['offer-original']['quantity_comparison_reason'] == reason
    assert history['offer-original']['received_package_count_scope'] == 'complete_declared_vector'
    assert history['offer-original']['quantity_basis'] == 'reviewed_source_component_vector_v1'
    assert history['offer-original']['scalar_basis'] == 'one_complete_declared_vector_not_piece_count'
    assert history['offer-control']['quantity_comparison_reason'] is None
    assert history['offer-original']['price'] == history['offer-original']['listed_price'] == 22990
    assert history['offer-original']['total_quantity'] == 920 and history['offer-original']['quantity_unit'] == 'g'
    assert history['offer-original']['variant_id'] == 'var-original-scalar'
    assert product == original


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    from api.routes import products
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 9, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(products, 'datetime', clock)
    path = tmp_path / 'variant-comparison.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE unified_categories (id TEXT, name_ko TEXT, parent_id TEXT);
            INSERT INTO unified_categories (id,name_ko) VALUES ('tuna', '참치통조림');
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
    app.state.storage = SimpleNamespace(
        catalog=catalog,
        get_product_detail=catalog.get_normalized_product_detail,
        search_products_page=catalog.search_normalized_products_page,
        get_category_children=lambda _category: ([], 1, '참치통조림'),
        get_category_products=lambda category, page, per_page: catalog.search_normalized_products_page('', category=category, page=page, per_page=per_page),
    )
    app.include_router(router, prefix='/products')
    from api.routes.search import router as search_router
    app.include_router(search_router, prefix='/search')
    return TestClient(app)


def test_homogeneous_contents_reach_detail_history_and_measured_comparison_without_changing_receipt(catalog):
    components = [{'quantity':350, 'unit':'g', 'count':1, 'identity':'참치', 'presentation':''},
                  {'quantity':1500, 'unit':'g', 'count':1, 'identity':'참치', 'presentation':''}]
    with sqlite3.connect(catalog.path) as db:
        db.execute('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT')
        db.execute('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT')
        db.execute("UPDATE normalized_product_variants SET package_quantity=1,package_unit='세트',bundle_count=1,standard_unit='g',attributes=? WHERE public_variant_id='var-a'",
                   (json.dumps({'component_basis':'reviewed_homogeneous_contents','package_components':components}),))
    detail = catalog.get_normalized_product_detail('prod-tuna')
    vector = detail['variants'][0]
    assert vector['id'] == 'var-a' and vector['quantity_components'] == components
    offer = vector['listings'][0]['offers'][0]
    assert offer['total_quantity'] == 1 and offer['quantity_unit'] == '세트'
    assert offer['pricing_measure_quantity'] == 1850 and offer['pricing_measure_unit'] == 'g'
    assert detail['comparison_reference']['basis'] == '100g'
    assert detail['comparison_reference']['comparable_count'] == 2
    with client_for(catalog) as client:
        history = client.get('/products/prod-tuna/price-history').json()['data']
        compared = client.get('/products/prod-tuna/price-compare').json()['data']
    assert {r['id'] for r in history} == {'old-a','latest-a','latest-b'}
    for row in history:
        if row['variant_id'] == 'var-a':
            assert row['pricing_measure_quantity'] == 1850
            assert row['quantity_components'] == components
            assert row['quantity_unit'] == '세트' and row['total_quantity'] == 1
    assert {r['comparison_basis'] for r in compared} == {'100g'}
    from services.account_feature_storage import AccountFeatureStore
    from services.runtime_storage import RuntimeStorage
    listing = vector['listings'][0]
    item = {'variant_id':vector['id'], 'listing_id':listing['id'], 'offer_id':offer['id'],
            'item_price':offer['total_price']}
    saved = AccountFeatureStore._selected_quote(detail, item)['offer_context']
    assert saved['pricing_measure_quantity'] == 1850 and saved['pricing_measure_unit'] == 'g'
    assert saved['quantity_components'] == components
    assert saved['total_quantity'] == 1 and saved['quantity_unit'] == '세트'
    assert RuntimeStorage._saved_receipt_state(detail, item, saved) == (True, None)


def test_registered_linear_contents_reach_history_and_saved_quote_without_promoting_generic_m(catalog):
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from services.account_feature_storage import AccountFeatureStore
    from services.runtime_storage import RuntimeStorage
    review = next(r for r in REVIEWED_EXPLICIT_LISTING_PACKAGES if r.get('measurement_role') == 'declared_linear_contents')
    quantity, unit, count = review['normalized']
    with sqlite3.connect(catalog.path) as db:
        db.execute('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT')
        db.execute('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT')
        db.execute("UPDATE normalized_product_variants SET package_quantity=?,package_unit=?,bundle_count=?,standard_unit='m',attributes=? WHERE public_variant_id='var-a'",
                   (quantity,unit,count,json.dumps({'explicit_listing_quantity_review':review})))
        db.execute("UPDATE normalized_product_variants SET package_quantity=?,package_unit='m',bundle_count=?,attributes='{}' WHERE public_variant_id='var-b'", (quantity,count))
    detail = catalog.get_normalized_product_detail('prod-tuna')
    vector, unproven = detail['variants']
    offer = vector['listings'][0]['offers'][0]
    assert offer['quantity_basis'] == 'reviewed_declared_linear_contents'
    assert offer['pricing_measure_quantity'] == offer['total_quantity'] == quantity * count
    assert offer['per_100m'] == round(9000 / (quantity * count) * 100)
    assert unproven['listings'][0]['offers'][0]['pricing_measure_quantity'] is None
    assert unproven['listings'][0]['offers'][0]['per_100m'] is None
    with client_for(catalog) as client:
        history = client.get('/products/prod-tuna/price-history').json()['data']
    assert {r['id'] for r in history} == {'old-a','latest-a','latest-b'}
    proved = next(r for r in history if r['id'] == 'latest-a')
    assert proved['per_100m'] == offer['per_100m']
    assert proved['pricing_measure_quantity'] == quantity * count
    assert proved['received_package_count_scope'] == 'declared_linear_package_repetitions'
    listing = vector['listings'][0]
    row = {'variant_id':vector['id'], 'listing_id':listing['id'], 'offer_id':offer['id'], 'item_price':offer['total_price']}
    saved = AccountFeatureStore._selected_quote(detail, row)['offer_context']
    assert saved['per_100m'] == offer['per_100m']
    assert saved['pricing_measure_unit'] == 'm'
    assert RuntimeStorage._saved_receipt_state(detail, row, saved) == (True, None)
    legacy = {k:v for k,v in saved.items() if k != 'quantity_basis'}
    assert RuntimeStorage._saved_receipt_state(detail, row, legacy) == (False, 'receipt_basis_revised')


def test_unified_search_preserves_normalized_id_and_observation_time(catalog):
    from api.routes.search import _product_observed_times, router as search_router

    storage = SimpleNamespace(
        catalog=catalog,
        search_products_page=catalog.search_normalized_products_page,
    )
    app = FastAPI()
    app.state.storage = storage
    app.include_router(search_router, prefix='/search')
    with TestClient(app) as client:
        response = client.get('/search', params={'q': '참치', 'type': 'product', 'sort': 'recent'})
    assert response.status_code == 200
    data = response.json()
    assert data['meta']['total'] == 1
    assert data['data'][0]['id'] == 'prod-tuna'
    assert data['data'][0]['price'] == 4000
    assert _product_observed_times(storage, ['prod-tuna']) == {'prod-tuna': '2026-09-03'}


def test_unified_search_keeps_legacy_numeric_id_contract():
    from api.routes.search import router as search_router

    storage = SimpleNamespace(search_products_page=lambda *args, **kwargs: (
        [{'id': '17', 'name': '참치', 'price': 3000}], 1,
    ))
    app = FastAPI()
    app.state.storage = storage
    app.include_router(search_router, prefix='/search')
    with TestClient(app) as client:
        response = client.get('/search', params={'q': '참치', 'type': 'product'})
    assert response.status_code == 200
    assert response.json()['data'][0]['id'] == 17


def test_card_pairs_current_best_price_with_its_own_variant(catalog):
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['price'] == 4000
    assert detail['source'] == 'emart'
    assert detail['unit'] == '250g'
    assert detail['best_offer']['variant_id'] == 'var-b'
    # Full detail still retains the prior observation.
    assert len(detail['variants'][0]['listings'][0]['offers']) == 2


def test_mixed_measured_dimensions_choose_stable_reference_not_numeric_global_low(catalog):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_product_variants SET package_unit='ml' WHERE public_variant_id='var-b'")
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['best_offer']['id'] == 'latest-a'
    assert detail['price'] == 9000
    assert detail['comparison_reference']['basis'] == '100g'
    assert detail['comparison_reference']['comparable_count'] == 1
    with client_for(catalog) as client:
        rows = client.get('/products/prod-tuna/price-compare').json()['data']
        history = client.get('/products/prod-tuna/price-history').json()['data']
    assert [(row['id'], row['comparison_basis'], row['is_reference_group']) for row in rows] == [
        ('latest-a', '100g', True), ('latest-b', '100ml', False)]
    assert [row['rank_within_group'] for row in rows] == [1, 1]
    assert {row['id'] for row in history} == {'old-a', 'latest-a', 'latest-b'}
    # A price-only observation change cannot select the other dimension.
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_offer_events SET price=1000 WHERE public_offer_event_id='latest-b'")
    assert catalog.get_normalized_product_detail('prod-tuna')['best_offer']['id'] == 'latest-a'


@pytest.mark.parametrize('unit', ['인', '인분', '매'])
def test_typed_count_comparison_keeps_distinct_variant_entitlements_separate(catalog, unit):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_product_variants SET package_quantity=2,package_unit=?,bundle_count=1", (unit,))
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['best_offer']['id'] == 'latest-a'
    assert detail['comparison_reference']['basis'] == 'variant:var-a'
    assert detail['comparison_reference']['comparable_count'] == 1
    with client_for(catalog) as client:
        rows = client.get('/products/prod-tuna/price-compare').json()['data']
    assert [row['id'] for row in rows] == ['latest-a', 'latest-b']
    assert [row['quantity_unit'] for row in rows] == [unit, unit]
    assert [row['comparison_basis'] for row in rows] == ['variant:var-a', 'variant:var-b']
    assert rows[0]['comparison_group'] != rows[1]['comparison_group']
    assert rows[0]['is_reference_group'] and not rows[1]['is_reference_group']


@pytest.mark.parametrize('conditions,same_receipt', [
    ({}, True), ({'membership_required': True}, False),
    ({'minimum_quantity': 2}, False),
])
def test_count_variant_only_ranks_compatible_receipts_and_conditions(catalog, conditions, same_receipt):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_product_variants SET package_quantity=2,package_unit='매',bundle_count=1")
        db.execute("INSERT INTO normalized_source_listings VALUES ('listing-aa','var-a','emart','aa','이용권 2매',1)")
        db.execute("INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?)",
                   ('latest-aa', 'listing-aa', 6000, 'normal', 'final_price',
                    json.dumps({'promotion_conditions': conditions}), '2026-09-03', 'active'))
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['best_offer']['id'] == ('latest-aa' if same_receipt else 'latest-a')
    assert detail['comparison_reference']['comparable_count'] == (2 if same_receipt else 1)
    with client_for(catalog) as client:
        rows = client.get('/products/prod-tuna/price-compare').json()['data']
    original = next(row for row in rows if row['id'] == 'latest-a')
    other = next(row for row in rows if row['id'] == 'latest-aa')
    assert (original['comparison_group'] == other['comparison_group']) is same_receipt
    assert other['promotion_conditions'] == conditions
    assert len(rows) == 3


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
        recent = client.get('/products/prod-tuna/price-history?days=7').json()['data']
        assert sorted(row['id'] for row in recent) == ['latest-a', 'latest-b']
        # The API period does not delete older source evidence from detail.
        detail = client.get('/products/prod-tuna').json()['data']
        assert len(detail['variants'][0]['listings'][0]['offers']) == 2


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


def test_one_plus_one_ranks_by_effective_unit_price_and_keeps_actual_spend(catalog):
    evidence = json.dumps({"promotion_conditions": {"buy_quantity": 1, "free_quantity": 1, "minimum_quantity": 1, "condition_text": "1+1"}})
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_offer_events SET promotion_type='buy_x_get_y', raw_evidence=? WHERE public_offer_event_id='latest-a'", (evidence,))
    with client_for(catalog) as client:
        rows = client.get('/products/prod-tuna/price-compare').json()['data']
    assert [row['id'] for row in rows] == ['latest-a', 'latest-b']
    assert rows[0]['listed_price'] == 9000
    assert rows[0]['total_price'] == 9000
    assert rows[0]['total_quantity'] == 720
    assert rows[0]['per_100g'] == 1250
    assert rows[0]['promotion_condition'] == '1+1'
    assert rows[0]['promotion_conditions']['buy_quantity'] == 1
    assert rows[0]['promotion_conditions']['free_quantity'] == 1
    with client_for(catalog) as client:
        selected = next(row for row in client.get('/products/prod-tuna/price-history').json()['data'] if row['id'] == 'latest-a')
    assert selected['listing_id'] == rows[0]['listing_id']
    assert selected['variant_id'] == rows[0]['variant_id']
    assert selected['received_package_count'] == 2 and selected['total_quantity'] == 720
    assert selected['minimum_quantity'] == 1 and selected['promotion_conditions']['free_quantity'] == 1


@pytest.mark.parametrize('state', ['pending', 'inactive'])
def test_latest_nonactive_current_is_held_across_detail_search_compare_and_tagged_history(catalog, state):
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_offer_events SET offer_state=?,crawled_at='2026-09-04' WHERE public_offer_event_id IN ('latest-a','latest-b')", (state,))
    detail = catalog.get_normalized_product_detail('prod-tuna')
    assert detail['id'] == 'prod-tuna'
    assert detail['best_offer'] is None
    assert detail['cur'] is None
    assert detail['price'] is None
    assert detail['observed_at'] == '2026-09-04'
    current = detail['variants'][0]['listings'][0]['offers'][0]
    assert current['id'] == 'latest-a'
    assert current['offer_state'] == state
    assert current['listed_price'] == 9000
    assert current['total_price'] is None
    assert current['total_quantity'] is None
    assert current['comparable_price'] is None
    assert current['per_item'] is None
    assert current['is_latest'] is True
    assert current['current_eligible'] is False
    with client_for(catalog) as client:
        assert client.get('/products/prod-tuna/trust').json()['data']['current_price'] is None
        assert client.get('/products/prod-tuna/price-compare').json()['data'] == []
        history = client.get('/products/prod-tuna/price-history').json()['data']
        assert {row['id'] for row in history} == {'latest-a', 'latest-b', 'old-a'}
        assert all(not row['current_eligible'] for row in history)
        assert next(row for row in history if row['id'] == 'old-a')['is_latest'] is False
        assert next(row for row in history if row['id'] == 'latest-a')['offer_state'] == state
        assert sorted(row['listed_price'] for row in history) == [1000, 4000, 9000]
        search = client.get('/products/search', params={'q': '검증'}).json()['data'][0]
        assert search['id'] == 'prod-tuna' and search['price'] is None
        unified = client.get('/search', params={'q': '검증', 'type': 'product'}).json()['data'][0]
        assert unified['id'] == 'prod-tuna' and unified['price'] is None
        assert unified['description'] == '비교 가능한 현재가 미확인'
        category_response = client.get('/products/category/tuna/compare')
        assert category_response.status_code == 200, category_response.text
        category = category_response.json()['data']
        assert category['products'][0]['price']['current'] is None
        assert category['products'][0]['observed_at'] == '2026-09-04'
        assert category['summary']['avg_comparison_price'] is None
        assert category['summary']['comparison_product_count'] == 0
    from api.routes.search import _product_observed_times
    assert _product_observed_times(SimpleNamespace(catalog=catalog), ['prod-tuna']) == {'prod-tuna': '2026-09-04'}


def category_client(rows, *, fallback=False):
    def fetch(_query='', category=None, page=1, per_page=20):
        size = min(per_page, 2) if fallback else per_page
        start = (page - 1) * size
        return rows[start:start + size], len(rows)
    storage = SimpleNamespace(
        get_category_children=lambda _: ([], len(rows), '검증 분류'),
        get_category_products=(lambda *args, **kwargs: ([], 0)) if fallback else (
            lambda category, page, per_page: fetch(category=category, page=page, per_page=per_page)),
        search_products_page=fetch,
    )
    app = FastAPI()
    app.state.storage = storage
    app.include_router(router, prefix='/products')
    return TestClient(app)


@pytest.mark.parametrize('field,value,reason', [
    ('valid_to', '2020-01-01T15:00:00Z', 'expired'),
    ('valid_from', '2099-01-01T00:00:00+09:00', 'not_yet_valid'),
    ('valid_to', 'unconfirmed date', 'validity_unconfirmed'),
])
def test_current_validity_holds_latest_quote_but_preserves_entire_history(catalog, field, value, reason):
    with sqlite3.connect(catalog.path) as db:
        db.execute(f'ALTER TABLE normalized_offer_events ADD COLUMN {field} TEXT')
        db.execute(f"UPDATE normalized_offer_events SET {field}=? WHERE public_offer_event_id IN ('latest-a','latest-b')", (value,))
    product = catalog.get_normalized_product_detail('prod-tuna')
    assert product['best_offer'] is None and product['cur'] is None
    events = [offer for variant in product['variants'] for listing in variant['listings'] for offer in listing['offers']]
    assert len(events) == 3 and sorted(event['listed_price'] for event in events) == [1000, 4000, 9000]
    assert all(not event['current_eligible'] for event in events)
    assert all(event['availability_reason'] == reason for event in events if event['is_latest'])
    with client_for(catalog) as client:
        assert client.get('/products/prod-tuna/price-compare').json()['data'] == []
        assert len(client.get('/products/prod-tuna/price-history').json()['data']) == 3
        assert client.get('/products/search', params={'q': '검증'}).json()['data'][0]['price'] is None


def comparison_row(pid, price, **offer):
    return {'id': pid, 'public_product_id': pid, 'name': pid,
            'best_offer': {'id': 'offer-' + pid, 'comparable_price': price, 'total_price': price, **offer}}


@pytest.mark.parametrize('sort', ['price_asc', 'price_desc'])
def test_category_shared_basis_ranks_only_proven_quotes_and_preserves_spend(sort):
    rows = [comparison_row('no-basis', 1), comparison_row('high-unit', 2000, per_100g=400),
            comparison_row('low-unit', 5000, per_100g=200), comparison_row('unknown', None)]
    with category_client(rows) as client:
        result = client.get('/products/category/test/compare', params={'sort': sort}).json()['data']
    expected = ['low-unit', 'high-unit'] if sort == 'price_asc' else ['high-unit', 'low-unit']
    assert [row['id'] for row in result['products']] == expected + ['no-basis', 'unknown']
    assert result['summary']['comparison_basis'] == '100g'
    assert result['summary']['avg_comparison_price'] == 300
    assert result['summary']['comparison_product_count'] == 2
    assert next(row for row in result['products'] if row['id'] == 'low-unit')['promotion']['total_spend'] == 5000
    assert result['products'][-1]['price']['current'] is None
    assert all(row['price']['original'] is None for row in result['products'])


@pytest.mark.parametrize('mixed', [False, True])
def test_category_unknown_or_mixed_basis_never_ranks_transaction_totals(mixed):
    rows = [comparison_row('expensive-total', 9000, **({'per_100g': 200} if mixed else {})),
            comparison_row('cheap-total', 1000, **({'per_100ml': 300} if mixed else {}))]
    with category_client(rows) as client:
        result = client.get('/products/category/test/compare', params={'sort': 'price_asc', 'per_page': 1}).json()['data']
    assert result['products'][0]['id'] == 'expensive-total'
    summary = result['summary']
    assert summary['comparison_basis'] is None and summary['avg_comparison_price'] is None
    assert summary['min_comparison_price'] is None and summary['hotdeal_threshold'] is None
    assert summary['comparison_product_count'] == 0


def test_category_fallback_checks_basis_after_all_storage_pages():
    rows = [comparison_row('a', 1000, per_100g=100), comparison_row('b', 2000, per_100g=200),
            comparison_row('c', 3000, per_100ml=300)]
    with category_client(rows, fallback=True) as client:
        result = client.get('/products/category/test/compare', params={'per_page': 1}).json()['data']
    assert result['pagination']['total'] == 3
    assert result['summary']['comparison_basis'] is None
    assert result['summary']['avg_comparison_price'] is None


def test_category_group_selection_uses_whole_leaf_before_paging_and_never_mixes_units():
    rows = [comparison_row('a', 1000, per_100g=300), comparison_row('b', 2000, per_100ml=10),
            comparison_row('c', 6000, per_100g=100), comparison_row('unknown', None)]
    with category_client(rows, fallback=True) as client:
        result = client.get('/products/category/test/compare', params={
            'comparison_basis': '100g', 'per_page': 1}).json()['data']
        invalid = client.get('/products/category/test/compare', params={'comparison_basis': '100m'})
    assert invalid.status_code == 422
    assert result['pagination']['total'] == 2
    assert result['summary']['category_product_count'] == 4
    assert result['summary']['avg_comparison_price'] == 200
    assert result['products'][0]['id'] == 'c'
    groups = {row['basis']: row for row in result['summary']['comparison_groups']}
    assert groups['100g']['comparable_count'] == 2 and groups['100ml']['comparable_count'] == 1
    assert result['products'][0]['promotion']['total_spend'] == 6000


@pytest.mark.parametrize('other_variant', [False, True])
def test_category_explicit_variant_per_item_basis_does_not_compare_different_variants(other_variant):
    rows = [comparison_row('a', 1000, variant_id='same', per_item=1000),
            comparison_row('b', 1500, variant_id='other' if other_variant else 'same', per_item=750)]
    with category_client(rows) as client:
        result = client.get('/products/category/test/compare').json()['data']
    assert result['summary']['comparison_basis'] == (None if other_variant else 'variant:same')
    assert result['summary']['comparison_product_count'] == (0 if other_variant else 2)
    assert [row['id'] for row in result['products']] == (['a', 'b'] if other_variant else ['b', 'a'])


def test_category_projects_actual_selected_offer_quantity_and_purchase_conditions(catalog):
    conditions = {'buy_quantity': 1, 'free_quantity': 1, 'minimum_quantity': 1,
                  'membership_required': True, 'coupon_required': False, 'condition_text': '회원 1+1'}
    with sqlite3.connect(catalog.path) as db:
        db.execute("UPDATE normalized_offer_events SET promotion_type='buy_x_get_y',raw_evidence=? WHERE public_offer_event_id='latest-a'",
                   (json.dumps({'promotion_conditions': conditions}),))
    with client_for(catalog) as client:
        result = client.get('/products/category/tuna/compare').json()['data']['products'][0]
    assert (result['variant_id'], result['listing_id'], result['offer_id']) == ('var-a', 'listing-a', 'latest-a')
    offer = result['promotion']
    assert offer['total_spend'] == offer['total_price'] == 9000
    assert offer['listed_price'] == 9000 and offer['total_quantity'] == 720
    assert offer['quantity_unit'] == 'g' and offer['received_package_count'] == 2
    assert offer['promotion_conditions'] == conditions and offer['condition'] == '회원 1+1'
    assert offer['membership_required'] is True and offer['coupon_required'] is False
    assert offer['package_quantity'] == 90 and offer['package_unit'] == 'g' and offer['bundle_count'] == 4
    assert offer['display_unit'] == '90g×4'
    assert result['best_offer']['id'] == 'latest-a'
