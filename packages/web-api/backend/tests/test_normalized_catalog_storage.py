from __future__ import annotations

import json
import sqlite3

import pytest

from services.catalog_storage import PublicCatalogStore


@pytest.mark.parametrize('observed,period,reason', [
    ('2026-09-02T13:39:42Z', {'valid_to':'2026-09-01T15:00:00Z'}, 'promotion_observation_outside_period'),
    ('2026-08-30T12:00:00Z', {'valid_from':'2026-09-01'}, 'promotion_observation_outside_period'),
    ('2026-09-01T23:00:00-02:00', {'valid_to':'2026-09-01'}, 'promotion_observation_outside_period'),
    (None, {'valid_to':'2026-09-01'}, 'promotion_observation_validity_unconfirmed'),
    ('invalid', {'valid_to':'2026-09-01'}, 'promotion_observation_validity_unconfirmed'),
    ('2026-09-01', {'valid_to':'2026-09-01T15:00:00Z'}, 'promotion_observation_validity_unconfirmed'),
    ('2026-09-01T12:00:00Z', {'valid_to':'unknown'}, 'promotion_observation_validity_unconfirmed'),
])
@pytest.mark.parametrize('promotion,conditions', [
    ('buy_x_get_y', {'buy_quantity':2,'free_quantity':1,'minimum_quantity':2}),
    ('final_price', {'minimum_quantity':2}),
])
def test_purchase_count_rule_outside_observation_period_preserves_quote_not_receipt(observed, period, reason, promotion, conditions):
    from copy import deepcopy
    from services.runtime_storage import RuntimeStorage
    event = {'public_offer_event_id':'original-event', 'price':8980,
             'price_state':'normal', 'offer_state':'active', 'promotion_type':promotion,
             'raw_evidence':{'promotion_conditions':conditions}, 'crawled_at':observed, **period}
    variant = {'id':'original-variant', 'package_quantity':600,'package_unit':'g','bundle_count':1}
    original = deepcopy((event,variant))
    offer = PublicCatalogStore._normalized_offer(event, variant)
    assert offer['id'] == 'original-event' and offer['listed_price'] == 8980
    assert offer['promotion_conditions'] == conditions and offer['minimum_quantity'] == 2
    assert offer['observation_receipt_eligible'] is False and offer['observation_receipt_reason'] == reason
    assert all(offer[key] is None for key in ('total_price','comparable_price','total_quantity',
                                             'received_package_count','per_item','per_100g'))
    listing = {'id':'original-listing', 'offers':[offer]}
    variant['listings'] = [listing]
    product = {'variants':[variant]}
    row = {'variant_id':variant['id'],'listing_id':listing['id'],'offer_id':offer['id'],'price':17960}
    saved = {'package_quantity':600,'package_unit':'g','bundle_count':1,
             'listed_price':8980,'total_price':17960,'total_quantity':1800,'received_package_count':3}
    saved_original = deepcopy((row,saved))
    assert RuntimeStorage._saved_receipt_state(product, row, saved) == (False, reason)
    assert (row,saved) == saved_original  # Hold, never overwrite the user's old tuple/money.
    variant.pop('listings')
    assert (event,variant) == original


@pytest.mark.parametrize('observed,period', [
    ('2026-09-01T15:00:00Z', {'valid_to':'2026-09-01T15:00:00Z'}),
    ('2026-09-02T00:00:00+09:00', {'valid_to':'2026-09-01T15:00:00Z'}),
    ('2026-09-01T23:59:59Z', {'valid_to':'2026-09-01'}),
    ('2026-09-02T08:00:00+09:00', {'valid_to':'2026-09-01'}),
    ('2026-09-01', {'valid_from':'2026-09-01','valid_to':'2026-09-01'}),
    (None, {}),
])
def test_purchase_count_historical_rule_observed_within_period_retains_arithmetic(observed, period):
    event = {'public_offer_event_id':'same-event', 'price':8980,'price_state':'normal',
             'promotion_type':'buy_x_get_y','offer_state':'active','crawled_at':observed,
             'raw_evidence':{'promotion_conditions':{'buy_quantity':2,'free_quantity':1,'minimum_quantity':2}}, **period}
    variant = {'package_quantity':600,'package_unit':'g','bundle_count':1}
    offer = PublicCatalogStore._normalized_offer(event, variant)
    assert offer['total_price'] == 17960 and offer['total_quantity'] == 1800
    assert offer['received_package_count'] == 3 and offer['per_100g'] == 998
    assert offer['observation_receipt_eligible'] is not False
    if period:
        assert offer['availability_reason'] == 'expired'  # Today's expiry is separate.
    changed = PublicCatalogStore._normalized_offer({**event,'price':9000}, variant)
    assert changed['id'] == offer['id'] and changed['total_price'] == 18000
    assert changed['total_quantity'] == 1800 and changed['per_100g'] == 1000


@pytest.mark.parametrize('unit,amount,total,field', [
    ('g', 350, 1850, 'per_100g'), ('ml', 700, 4700, 'per_100ml'), ('매', 15, 165, None),
])
def test_homogeneous_contents_preserve_vector_receipt_and_separate_received_measure(unit, amount, total, field):
    from copy import deepcopy
    from services.catalog_storage import _homogeneous_contents, _offer_comparison_group
    components = [{'quantity':amount, 'unit':unit, 'count':1, 'identity':'same contents', 'presentation':''},
                  {'quantity':total-amount, 'unit':unit, 'count':1, 'identity':'same contents', 'presentation':'리필'}]
    variant = {'package_quantity':1, 'package_unit':'세트', 'bundle_count':1, 'standard_unit':unit,
               'attributes':{'package_components':components, 'component_basis':'reviewed_homogeneous_contents'}}
    event = {'public_offer_event_id':'vector-offer', 'price':10000, 'price_state':'normal',
             'offer_state':'active', 'promotion_type':'buy_x_get_y',
             'raw_evidence':{'promotion_conditions':{'buy_quantity':2, 'free_quantity':1}}}
    original = deepcopy(variant)
    offer = PublicCatalogStore._normalized_offer(event, variant)
    assert offer['listed_price'] == 10000 and offer['total_price'] == 20000
    assert offer['total_quantity'] == 3 and offer['quantity_unit'] == '세트'
    assert offer['received_package_count'] == 3 and offer['per_item'] == 6667
    assert offer['pricing_measure_quantity'] == total * 3
    assert offer['pricing_measure_unit'] == unit and offer['pricing_measure_basis'] == 'reviewed_homogeneous_contents'
    assert offer['received_package_count_scope'] == 'complete_declared_vector'
    assert offer['quantity_components'] == _homogeneous_contents(variant)[0]
    if field:
        assert offer[field] == round(20000 / (total * 3) * 100)
        assert _offer_comparison_group(offer)[2] == 'same_measured_unit'
    else:
        assert offer['per_100g'] is offer['per_100ml'] is None
        assert _offer_comparison_group(offer)[2] == 'source_quote_only'  # Needs selected variant receipt.
    pending = PublicCatalogStore._normalized_offer({**event, 'price_state':'unavailable'}, variant)
    assert pending['pricing_measure_quantity'] is pending['pricing_measure_unit'] is None
    assert pending['quantity_components'] == offer['quantity_components']
    for change in ({'component_basis':'unreviewed'}, {'package_components':None},
                   {'package_components':[components[0], {**components[1], 'identity':'other contents'}]},
                   {'package_components':[components[0], {**components[1], 'unit':'ml' if unit != 'ml' else 'g'}]},
                   {'package_components':[components[0], {**components[1], 'count':None}]}):
        rejected = PublicCatalogStore._normalized_offer(event, {**variant, 'attributes':{**variant['attributes'], **change}})
        assert rejected['pricing_measure_quantity'] is rejected['per_100g'] is rejected['per_100ml'] is rejected['per_item'] is None
        assert rejected['quantity_comparison_reason'] == 'quantity_evidence_unverified'
    for change in ({'standard_unit':None}, {'package_quantity':2}, {'bundle_count':2}):
        rejected = PublicCatalogStore._normalized_offer(event, {**variant, **change})
        assert rejected['pricing_measure_quantity'] is rejected['per_item'] is None
    assert variant == original


def test_count_quantity_uses_received_piece_count_for_per_item_price():
    offer = PublicCatalogStore._normalized_offer(
        {
            "public_offer_event_id": "offer-capsule",
            "price": 40990,
            "price_state": "normal",
            "promotion_type": "final_price",
            "raw_evidence": "{}",
        },
        {
            "package_quantity": 80,
            "package_unit": "개",
            "bundle_count": 1,
        },
    )

    assert offer["total_price"] == 40990
    assert offer["total_quantity"] == 80
    assert offer["quantity_unit"] == "개"
    assert offer["per_item"] == 512


@pytest.mark.parametrize('category,title,quantity,unit,count,count_unit', [
    ('household.security.storage.safe','금고 40L',40000,'ml',None,None),
    ('household.outdoor.bags.cooler_tote','쿨러백 16L',16000,'ml',None,None),
    ('household.bath.textiles.towel','타월 150g 1P',150,'g',1,'개'),
    ('household.bath.textiles.towel','타월 130g 5P',130,'g',5,'개'),
    ('stationery.office.paper.copy','A4 복사지 80g 500매',80,'g',500,'매'),
    ('stationery.office.paper.copy','A4 복사지 80g 2500매',80,'g',2500,'매'),
    ('office.equipment.shredder.standard','문서세단기 19L',19000,'ml',None,None),
])
def test_physical_role_detail_search_and_mart_preserve_quote_without_mass_rates(tmp_path,category,title,quantity,unit,count,count_unit):
    from core.catalog_quantity import normalize_catalog_package
    source = {'name':title,'detail_url':'https://example.test/physical','pack_qty':quantity,'pack_unit':unit}
    package, issues = normalize_catalog_package(source,{},title,category_id=category)
    assert package and not issues
    path = tmp_path / 'physical-role.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, name_ko TEXT);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT, canonical_name TEXT,
          brand TEXT, attributes TEXT, primary_image_url TEXT, is_active INTEGER);
        CREATE TABLE normalized_product_variants (
          public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, variant_name TEXT,
          package_quantity REAL, package_unit TEXT, bundle_count INTEGER, display_unit TEXT,
          standard_unit TEXT, attributes TEXT, is_active INTEGER);
        CREATE TABLE normalized_source_listings (
          public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT, source_name TEXT,
          source_record_key TEXT, source_title TEXT, source_url TEXT, image_url TEXT,
          source_unit_text TEXT, is_active INTEGER);
        CREATE TABLE normalized_offer_events (
          public_offer_event_id TEXT PRIMARY KEY, public_source_listing_id TEXT, price REAL,
          price_state TEXT, promotion_type TEXT, raw_evidence TEXT, crawled_at TEXT, offer_state TEXT);
        ''')
        db.execute('INSERT INTO unified_categories VALUES (?,?)',(category,'검수된 물리 규격'))
        db.execute('INSERT INTO normalized_canonical_products VALUES (?,?,?,?,?,?,?)',('prod-physical',category,title,'','{}',None,1))
        db.execute('INSERT INTO normalized_product_variants VALUES (?,?,?,?,?,?,?,?,?,?)',('var-physical','prod-physical',title,
            package['package_quantity'],package['package_unit'],package['bundle_count'],package['display_unit'],
            package['standard_unit'],json.dumps(package['attributes']),1))
        db.execute('INSERT INTO normalized_source_listings VALUES (?,?,?,?,?,?,?,?,?)',('listing-physical','var-physical','homeplus',
            'synthetic-physical',title,source['detail_url'],None,title,1))
        db.executemany('INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?)',[
            ('offer-old','listing-physical',10000,'normal','final_price','{}','2026-08-30','active'),
            ('offer-new','listing-physical',11000,'normal','final_price','{}','2026-08-31','active')])
    store = PublicCatalogStore(path)
    detail = store.get_normalized_product_detail('prod-physical')
    variant = detail['variants'][0]
    assert (variant['package_quantity'],variant['package_unit']) == (count,count_unit)
    assert variant['display_unit'] == title  # Literal capacity/weight specification remains visible.
    offers = variant['listings'][0]['offers']
    assert [(o['id'],o['listed_price']) for o in offers] == [('offer-new',11000),('offer-old',10000)]
    for offer in offers:
        assert offer['total_price'] == offer['listed_price']
        assert offer['per_100g'] is offer['per_100ml'] is offer['per_100m'] is None
        assert offer['total_quantity'] == count
        assert offer['per_item'] == (round(offer['listed_price']/count) if count else None)
    rows,total = store.search_normalized_products_page(title)
    assert total == 1 and rows[0]['best_offer']['id'] == 'offer-new'
    mart = store.get_mart_deals('homeplus')['homeplus']['items'][0]
    assert mart['offer_id'] == 'offer-new' and mart['sale'] == 11000
    assert mart['per_100g'] is mart['per_100ml'] is None


@pytest.mark.parametrize("category,unit,held", [
    ("services.facility.camping.cabin_package", "인", True),
    ("services.facility.camping.cabin_package", "인분", True),
    ("services.facility.camping.cabin_package", "매", False),
    ("food.prepared.meal.set", "인분", False),
])
def test_quantity_purpose_holds_occupancy_but_preserves_tickets_and_food(category, unit, held):
    offer = PublicCatalogStore._normalized_offer(
        {"public_offer_event_id": "offer-purpose", "price": 10000,
         "price_state": "normal", "promotion_type": "final_price", "raw_evidence": "{}"},
        {"package_quantity": 2, "package_unit": unit, "bundle_count": 1,
         "display_unit": f"2{unit}", "variant_name": f"선택 규격 2{unit}"},
        category_id=category,
    )
    assert offer["listed_price"] == offer["total_price"] == 10000
    if held:
        assert offer["quantity_purpose_reason"] == "unit_service_occupancy_not_entitlement"
        for field in ("comparable_price", "total_quantity", "quantity_unit", "bundle_count",
                      "received_package_count", "per_item", "per_100g", "per_100ml"):
            assert offer[field] is None
    else:
        assert offer["quantity_purpose_reason"] is None
        assert offer["quantity_unit"] == unit
        assert offer["total_quantity"] == 2 and offer["per_item"] == 5000
        assert offer["comparable_price"] == 10000


@pytest.mark.parametrize("unit", ["인", "인분"])
def test_facility_occupancy_is_not_current_in_detail_search_or_mart(tmp_path, unit):
    path = tmp_path / "facility-purpose.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, name_ko TEXT);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT, canonical_name TEXT,
          brand TEXT, attributes TEXT, primary_image_url TEXT, is_active INTEGER);
        CREATE TABLE normalized_product_variants (
          public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, variant_name TEXT,
          package_quantity REAL, package_unit TEXT, bundle_count INTEGER, display_unit TEXT,
          attributes TEXT, is_active INTEGER);
        CREATE TABLE normalized_source_listings (
          public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT, source_name TEXT,
          source_record_key TEXT, source_title TEXT, source_url TEXT, image_url TEXT,
          source_unit_text TEXT, is_active INTEGER);
        CREATE TABLE normalized_offer_events (
          public_offer_event_id TEXT PRIMARY KEY, public_source_listing_id TEXT, price REAL,
          price_state TEXT, promotion_type TEXT, raw_evidence TEXT, crawled_at TEXT, offer_state TEXT);
        INSERT INTO unified_categories VALUES ('services.facility.camping.cabin_package','캐빈');
        INSERT INTO normalized_canonical_products VALUES
          ('prod-cabin','services.facility.camping.cabin_package','캐빈','','{}',NULL,1);
        """)
        db.execute("INSERT INTO normalized_product_variants VALUES (?,?,?,?,?,?,?,?,?)",
                   ("var-cabin", "prod-cabin", f"캐빈 2{unit}", 2, unit, 1, f"2{unit}", "{}", 1))
        db.execute("INSERT INTO normalized_source_listings VALUES (?,?,?,?,?,?,?,?,?)",
                   ("listing-cabin", "var-cabin", "homeplus", "synthetic-cabin", f"캐빈 2{unit}",
                    "https://example.test/cabin", None, f"2{unit}", 1))
        db.executemany("INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?)", [
            ("offer-old", "listing-cabin", 12000, "normal", "final_price", "{}", "2026-08-30", "active"),
            ("offer-new", "listing-cabin", 10000, "normal", "final_price", "{}", "2026-08-31", "active"),
        ])
    store = PublicCatalogStore(path)
    detail = store.get_normalized_product_detail("prod-cabin")
    assert detail["best_offer"] is None and detail["cur"] is None
    offers = detail["variants"][0]["listings"][0]["offers"]
    assert [(o["id"], o["listed_price"], o["total_price"]) for o in offers] == [
        ("offer-new", 10000, 10000), ("offer-old", 12000, 12000)]
    assert all(o["current_eligible"] is False and o["per_item"] is None for o in offers)
    rows, total = store.search_normalized_products_page("캐빈")
    assert total == 1 and rows[0]["best_offer"] is None
    assert store.get_mart_deals("homeplus") == {}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT price FROM normalized_offer_events ORDER BY crawled_at").fetchall() == [(12000,), (10000,)]


def test_empty_normalized_schema_does_not_resurrect_legacy_categories(tmp_path):
    path = tmp_path / "empty-capstone.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE categories (id TEXT PRIMARY KEY, parent_id TEXT, name TEXT, sort_order INTEGER);
        INSERT INTO categories VALUES ('legacy', NULL, '레거시', 0);
        CREATE TABLE products (id INTEGER PRIMARY KEY, category_id TEXT, unified_category_id TEXT, name TEXT, is_active INTEGER);
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT, name_ko TEXT, sort_order INTEGER DEFAULT 0);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT,
          canonical_name TEXT, brand TEXT, aliases TEXT, keywords TEXT,
          attributes TEXT, primary_image_url TEXT, is_active INTEGER
        );
        """)
    store = PublicCatalogStore(path)

    assert store.get_category_tree() == []
    assert store.get_category_products("legacy", 1, 20) == ([], 0)


def test_normalized_catalog_exposes_total_bundle_and_unit_prices(tmp_path):
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT, name_ko TEXT, sort_order INTEGER DEFAULT 0);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT,
          canonical_name TEXT, brand TEXT, aliases TEXT, keywords TEXT,
          attributes TEXT, primary_image_url TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_product_variants (
          public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, variant_name TEXT,
          package_quantity REAL, package_unit TEXT, display_unit TEXT,
          bundle_count INTEGER, standard_unit TEXT, attributes TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_source_listings (
          public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT,
          source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT,
          image_url TEXT, source_unit_text TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_offer_events (
          public_offer_event_id TEXT PRIMARY KEY, public_source_listing_id TEXT,
          price_state TEXT, promotion_type TEXT, price REAL, original_price REAL,
          discount_rate REAL, event_name TEXT, raw_evidence TEXT,
          crawled_at TEXT, offer_state TEXT
        );
        """)
        db.executemany("INSERT INTO unified_categories VALUES (?,?,?,?)", [
            ("food", None, "식품", 0),
            ("food.dairy", "food", "유제품", 0),
            ("food.dairy.milk", "food.dairy", "우유", 0),
            ("food.dairy.milk.choco", "food.dairy.milk", "초코우유", 0),
        ])
        db.execute(
            "INSERT INTO normalized_canonical_products VALUES (?,?,?,?,?,?,?,?,?)",
            ("prod-choco", "food.dairy.milk.choco", "초코에몽", "남양", "[]", "[]", json.dumps({"classification_warning": True}), None, 1),
        )
        db.execute(
            "INSERT INTO normalized_product_variants VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("var-120-24", "prod-choco", "120ml 24개", 120, "ml", "120ml×24", 24, "100ml", "{}", 1),
        )
        db.execute(
            "INSERT INTO normalized_source_listings VALUES (?,?,?,?,?,?,?,?,?)",
            ("list-emart", "var-120-24", "emart", "123", "초코에몽 120ml 24개", "https://example.test", None, "120ml×24", 1),
        )
        db.execute(
            "INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("offer-1", "list-emart", "normal", "was_now_price", 24000, 28800, 0.1667, "회원가", json.dumps({"condition_text": "회원 1인 1개", "membership_required": True, "coupon_required": False, "minimum_quantity": 1}), "2026-08-30", "active"),
        )
        db.commit()

    store = PublicCatalogStore(path)
    rows, total = store.search_normalized_products_page("초코", page=1, per_page=10)

    assert total == 1
    assert rows[0]["classification_label"] == "분류 확인 필요"
    detail = store.get_normalized_product_detail("prod-choco")
    offer = detail["variants"][0]["listings"][0]["offers"][0]
    assert offer["total_price"] == 24000
    assert offer["total_quantity"] == 2880
    assert offer["per_item"] == 1000
    assert offer["per_100ml"] == 833
    assert offer["promotion_condition"] == "회원 1인 1개"
    assert offer["variant_id"] == "var-120-24" and offer["listing_id"] == "list-emart"
    assert offer["membership_required"] is True and offer["coupon_required"] is False
    assert offer["promotion_conditions"]["minimum_quantity"] == 1

    tree = store.get_category_tree()
    assert tree[0]["name"] == "식품"
    assert tree[0]["count"] == 1
    children, total, path_text = store.get_category_children("food.dairy.milk")
    assert total == 1
    assert children == [{"id": "food.dairy.milk.choco", "name": "초코우유", "count": 1}]
    assert path_text == "식품 > 유제품 > 우유"
    category_rows, category_total = store.get_category_products(
        "food.dairy", page=1, per_page=10
    )
    assert category_total == 1
    assert category_rows[0]["public_product_id"] == "prod-choco"

    mart = store.get_mart_deals("emart")
    deal = mart["emart"]["items"][0]
    assert deal["sale"] == 24000
    assert deal["per_100ml"] == 833
    assert deal["promotion_condition"] == "회원 1인 1개"
    assert (deal["product_id"], deal["variant_id"], deal["listing_id"], deal["offer_id"]) == (
        "prod-choco", "var-120-24", "list-emart", "offer-1")
    assert deal["best_offer"]["promotion_conditions"] == offer["promotion_conditions"]
    assert deal["best_offer"]["total_quantity"] == 2880
    assert deal["best_offer"]["current_eligible"] is True

    # Newest observations are chosen before active/price eligibility. Never
    # revive the earlier valid quote when the latest observation is held.
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO normalized_offer_events SELECT 'offer-2', public_source_listing_id, price_state, promotion_type, 21000, original_price, discount_rate, event_name, raw_evidence, crawled_at, offer_state FROM normalized_offer_events WHERE public_offer_event_id='offer-1'")
    assert store.get_mart_deals("emart")["emart"]["items"][0]["sale"] == 21000
    assert store.get_mart_deals("emart")["emart"]["items"][0]["offer_id"] == "offer-2"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE normalized_offer_events SET crawled_at='2026-08-31', price=20000 WHERE public_offer_event_id='offer-1'")
    assert store.get_mart_deals("emart")["emart"]["items"][0]["sale"] == 20000
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE normalized_offer_events ADD COLUMN valid_to TEXT')
        db.execute("UPDATE normalized_offer_events SET valid_to='2020-01-01T00:00:00Z' WHERE public_offer_event_id='offer-1'")
    # An older otherwise eligible observation must not revive an expired latest
    # offer. Detail still retains both prices and the source expiry.
    assert store.get_mart_deals("emart") == {}
    expired = store.get_normalized_product_detail('prod-choco')
    assert expired['cur'] is None
    assert len(expired['variants'][0]['listings'][0]['offers']) == 2
    with sqlite3.connect(path) as db:
        db.execute("UPDATE normalized_offer_events SET valid_to=NULL")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE normalized_product_variants SET package_quantity=NULL,package_unit=NULL")
    unknown = store.get_mart_deals("emart")["emart"]["items"][0]
    assert unknown["sale"] == 20000
    assert unknown["total_quantity"] is None
    assert unknown["per_item"] is None
    assert unknown["per_100g"] is None
    assert unknown["per_100ml"] is None
    for state in ("pending", "inactive"):
        with sqlite3.connect(path) as db:
            db.execute("UPDATE normalized_offer_events SET offer_state=? WHERE public_offer_event_id='offer-1'", (state,))
        assert store.get_mart_deals("emart") == {}
    with sqlite3.connect(path) as db:
        db.execute("UPDATE normalized_offer_events SET offer_state='active', promotion_type='checkout_discount' WHERE public_offer_event_id='offer-1'")
    assert store.get_mart_deals("emart") == {}


def test_confirmed_one_plus_one_uses_actual_spend_and_doubled_received_quantity(tmp_path):
    path = tmp_path / "one-plus-one.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, name_ko TEXT);
        INSERT INTO unified_categories VALUES ('cheese', '슬라이스치즈');
        CREATE TABLE normalized_canonical_products (public_product_id TEXT, unified_category_id TEXT, canonical_name TEXT, brand TEXT, attributes TEXT, primary_image_url TEXT, is_active INTEGER);
        INSERT INTO normalized_canonical_products VALUES ('prod', 'cheese', '검증 치즈', '', '{}', '', 1);
        CREATE TABLE normalized_product_variants (public_variant_id TEXT, public_product_id TEXT, variant_name TEXT, package_quantity REAL, package_unit TEXT, bundle_count INTEGER, display_unit TEXT, is_active INTEGER);
        INSERT INTO normalized_product_variants VALUES ('var', 'prod', '270g', 270, 'g', 1, '270g', 1);
        CREATE TABLE normalized_source_listings (public_source_listing_id TEXT, public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT, image_url TEXT, source_unit_text TEXT, is_active INTEGER);
        INSERT INTO normalized_source_listings VALUES ('listing', 'var', 'homeplus', '1', '검증 치즈 270g', '', '', '270g', 1);
        CREATE TABLE normalized_offer_events (public_offer_event_id TEXT, public_source_listing_id TEXT, price_state TEXT, promotion_type TEXT, price REAL, original_price REAL, discount_rate REAL, event_name TEXT, raw_evidence TEXT, crawled_at TEXT, offer_state TEXT);
        """)
        evidence = json.dumps({"promotion_conditions": {"buy_quantity": 1, "free_quantity": 1, "minimum_quantity": 1, "condition_text": "1+1"}})
        db.execute("INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", ('offer', 'listing', 'sale_price_only', 'buy_x_get_y', 9890, None, None, '1+1', evidence, '2026-09-08', 'active'))
    offer = PublicCatalogStore(path).get_normalized_product_detail("prod")["best_offer"]
    assert offer["listed_price"] == 9890
    assert offer["total_price"] == 9890
    assert offer["total_quantity"] == 540
    assert offer["per_item"] == 4945
    assert offer["per_100g"] == 1831
    assert offer["minimum_quantity"] == 1
    assert offer["received_package_count"] == 2
    assert offer["promotion_condition"] == "1+1"


@pytest.mark.parametrize("price,buy,free", [
    (True, 1, 1),
    ("not-a-price", 1, 1),
    ({"amount": 6000}, 1, 1),
    (6000, True, 1),
    (6000, 1, True),
    (6000, 2.7, 1),
    (6000, 2, 1.5),
    (6000, "2", 1),
    (6000, 1, 0),
])
def test_normalized_buy_free_malformed_source_cannot_publish_spend_or_unit_price(price, buy, free):
    conditions = {"buy_quantity": buy, "free_quantity": free, "minimum_quantity": buy,
                  "condition_text": "source terms under review", "membership_required": None}
    event = {"public_offer_event_id": "malformed-source-offer", "price": price,
             "price_state": "sale_price_only", "promotion_type": "buy_x_get_y", "offer_state": "active",
             "raw_evidence": json.dumps({"promotion_conditions": conditions})}
    offer = PublicCatalogStore._normalized_offer(event, {"package_quantity": 270, "package_unit": "g", "bundle_count": 1})
    assert offer["listed_price"] == (6000 if price == 6000 else None)
    assert offer["total_price"] is None and offer["comparable_price"] is None
    assert offer["total_quantity"] is None
    assert offer["per_item"] is None and offer["per_100g"] is None and offer["per_100ml"] is None
    assert offer["received_package_count"] is None
    # The source terms remain inspectable; failure must not rewrite them into
    # invented eligibility or rounded paid/free counts.
    assert offer["promotion_conditions"] == conditions
    assert offer["membership_required"] is None


@pytest.mark.parametrize("price,buy,free,spend,received", [
    (6000, 1, 1, 6000, 2),
    (6000, 2, 1, 12000, 3),
    ("6000", 2, 1, 12000, 3),
])
def test_normalized_buy_free_retains_valid_spend_received_contents_and_legacy_money_string(price, buy, free, spend, received):
    conditions = {"buy_quantity": buy, "free_quantity": free, "minimum_quantity": buy,
                  "condition_text": f"{buy}+{free}", "coupon_required": None}
    offer = PublicCatalogStore._normalized_offer(
        {"public_offer_event_id": "confirmed-source-offer", "price": price,
         "price_state": "sale_price_only", "promotion_type": "buy_x_get_y", "offer_state": "active",
         "raw_evidence": json.dumps({"promotion_conditions": conditions})},
        {"package_quantity": 270, "package_unit": "g", "bundle_count": 1})
    assert offer["listed_price"] == 6000
    assert offer["total_price"] == spend and offer["comparable_price"] == spend
    assert offer["received_package_count"] == received and offer["total_quantity"] == 270 * received
    assert offer["per_item"] == round(spend / received)
    assert offer["per_100g"] == round(spend / (270 * received) * 100)
    assert offer["promotion_conditions"] == conditions and offer["coupon_required"] is None


@pytest.mark.parametrize('quantity,unit,bundle', [(None, None, 1), (None, 'g', 1), (80, None, 1), (120, 'ml', None), (2, 'spec', 1)])
def test_unknown_content_or_count_basis_keeps_money_without_exact_unit_price(quantity, unit, bundle):
    offer = PublicCatalogStore._normalized_offer(
        {'public_offer_event_id': 'offer-physical-null', 'price': 2550,
         'price_state': 'normal', 'promotion_type': 'final_price',
         'offer_state': 'active', 'raw_evidence': '{}'},
        {'package_quantity': quantity, 'package_unit': unit, 'bundle_count': bundle},
    )
    assert offer['listed_price'] == 2550
    assert offer['total_price'] == 2550
    assert offer['comparable_price'] == 2550
    assert offer['per_item'] is None
    assert offer['per_100g'] is None
    assert offer['per_100ml'] is None
    assert offer['bundle_count'] == bundle


@pytest.mark.parametrize('context', [
    'mixed_original', 'mixed_price_change', 'homogeneous',
    'copied_source', 'copied_quantity', 'guessed_allocation', 'malformed_copied_proof',
])
def test_reviewed_mixed_scalar_preserves_historical_quote_and_aggregate_without_recipe_rates(context):
    from copy import deepcopy
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import explicit_listing_package
    review = next(r for r in reviewed_content_quantities.REVIEWED_EXPLICIT_LISTING_PACKAGES
                  if r['title'] == '미주라 통밀 도너츠 & 초코칩 통밀 도너츠 230g x 4')
    # Reconstruct the reviewed original source fields, not the current public
    # 2+2 allocation. The historical 920g aggregate does not prove recipe shares.
    source = {'name': review['title'], 'source': 'costco',
              'detail_url': review['required_source']['source_urls'][0],
              'attributes': {'source_record_key': '696218'}}
    for field, value in {**review['required_source']['source_fields'], **review['quantity_fields']}.items():
        layer, key = (source['attributes'], field[11:]) if field.startswith('attributes.') else (source, field)
        if isinstance(value, list):
            value = f'{value[0] or ""}{value[1]}'
        layer[key] = deepcopy(value)
    package, issues = explicit_listing_package(source, source['attributes'], source['name'])
    assert not issues and package is not None
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == (230, 'g', 4)
    assert review['component_allocation'] is None
    assert review['content_identities'] == ['통밀 도너츠', '초코칩 통밀 도너츠']
    assert 'source_components' not in package['attributes']
    variant = deepcopy(package)
    copied_review = variant['attributes']['explicit_listing_quantity_review']
    if context == 'homogeneous':
        variant['attributes'] = {}
        variant['variant_name'] = '단일 통밀 도너츠 230g x 4'
    if context == 'copied_source':
        copied_review['required_source']['source_urls'] = ['https://example.test/other-donuts']
    if context == 'copied_quantity':
        copied_review['quantity_fields']['pack_qty'] = 231
    if context == 'guessed_allocation':
        copied_review['component_allocation'] = [2, 2]
    if context == 'malformed_copied_proof':
        variant['attributes']['explicit_listing_quantity_review'] = 'copied-unverified-proof'
    variant['attributes'] = json.dumps(variant['attributes'], ensure_ascii=False)
    quote = 24000 if context == 'mixed_price_change' else 22990
    offer = PublicCatalogStore._normalized_offer(
        {'public_offer_event_id': 'historical-source-quote', 'price': quote,
         'price_state': 'normal', 'offer_state': 'active', 'promotion_type': 'final_price',
         'raw_evidence': '{}'}, variant,
    )
    assert offer['listed_price'] == offer['total_price'] == offer['comparable_price'] == quote
    assert offer['total_quantity'] == 920 and offer['quantity_unit'] == 'g'
    assert offer['bundle_count'] == 4 and offer['received_package_count'] == 1
    assert offer['membership_required'] is None and offer['coupon_required'] is None
    if context == 'homogeneous':
        assert offer['quantity_comparison_reason'] is None
        assert offer['per_100g'] == round(quote / 920 * 100)
        assert offer['per_item'] == round(quote / 4)
    else:
        expected = ('heterogeneous_contents_allocation_unverified' if context.startswith('mixed_')
                    else 'quantity_evidence_unverified')
        assert offer['quantity_comparison_reason'] == expected
        assert offer['per_item'] is offer['per_100g'] is offer['per_100ml'] is offer['per_100m'] is None


def test_known_whole_volume_preserves_buy_free_spend_without_claiming_recipe_equivalence():
    from copy import deepcopy
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    review = deepcopy(next(r for r in REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') == '071403971'))
    variant = {'package_quantity':400,'package_unit':'ml','bundle_count':1,'standard_unit':'ml',
               'attributes':json.dumps({'explicit_listing_quantity_review':review})}
    event = {'public_offer_event_id':'source-whole-volume','price':3990,'price_state':'normal',
             'offer_state':'active','promotion_type':'buy_x_get_y',
             'raw_evidence':json.dumps({'promotion_conditions':{'buy_quantity':1,'free_quantity':1}})}
    offer = PublicCatalogStore._normalized_offer(event,variant)
    assert offer['listed_price'] == offer['total_price'] == 3990
    assert offer['total_quantity'] == 800 and offer['received_package_count'] == 2
    assert offer['quantity_unit'] == 'ml' and offer['bundle_count'] == 1
    assert offer['quantity_comparison_reason'] == 'contents_identity_and_allocation_unverified'
    assert offer['per_100ml'] is offer['per_100g'] is offer['per_item'] is None
    # Current recipe names are not a registered historical proof.
    review['content_identities'] = ['현재 딸기', '현재 레몬']
    variant['attributes'] = json.dumps({'explicit_listing_quantity_review':review})
    rejected = PublicCatalogStore._normalized_offer(event,variant)
    assert rejected['quantity_comparison_reason'] == 'quantity_evidence_unverified'
    assert rejected['per_100ml'] is rejected['per_item'] is None


def test_reviewed_length_quotes_do_not_price_physical_dimensions(monkeypatch):
    from core import reviewed_content_quantities
    review = {'title':'검수된 선형 소모품','category_id':'beauty.personal.oral.floss',
              'required_source':{'source_urls':['https://example.test/linear'],'source_fields':{}},
              'quantity_fields':{},'normalized':[40,'m',3],'measurement_role':'declared_linear_contents'}
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_EXPLICIT_LISTING_PACKAGES',(review,))
    variant = {'package_quantity':40,'package_unit':'m','bundle_count':3,'standard_unit':'m',
               'attributes':json.dumps({'explicit_listing_quantity_review':review})}
    event = {'public_offer_event_id':'length-offer','price':6000,'price_state':'normal','offer_state':'active','promotion_type':'buy_x_get_y',
             'raw_evidence':json.dumps({'promotion_conditions':{'buy_quantity':2,'free_quantity':1,
                                                               'membership_required':True}})}
    offer = PublicCatalogStore._normalized_offer(event,variant)
    assert offer['total_price'] == 12000 and offer['total_quantity'] == 360
    assert offer['quantity_unit'] == 'm' and offer['per_100m'] == 3333
    assert offer['per_100g'] is offer['per_100ml'] is offer['per_item'] is None
    assert offer['membership_required'] is True and offer['received_package_count'] == 3
    assert offer['quantity_basis'] == offer['pricing_measure_basis'] == 'reviewed_declared_linear_contents'
    assert offer['scalar_basis'] == 'declared_linear_contents_not_physical_dimensions'
    assert offer['received_package_count_scope'] == 'declared_linear_package_repetitions'
    assert offer['pricing_measure_quantity'] == 360 and offer['pricing_measure_unit'] == 'm'
    changed = PublicCatalogStore._normalized_offer({**event, 'price':6600}, variant)
    assert changed['total_price'] == 13200 and changed['per_100m'] == 3667
    assert changed['pricing_measure_quantity'] == offer['pricing_measure_quantity']
    for change in ({'attributes':'{}'}, {'standard_unit':None}, {'package_quantity':30}):
        rejected = PublicCatalogStore._normalized_offer(event,{**variant,**change})
        assert rejected['per_100m'] is rejected['per_100g'] is rejected['per_100ml'] is None
        assert rejected['quantity_basis'] is rejected['pricing_measure_basis'] is rejected['pricing_measure_quantity'] is None


@pytest.mark.parametrize('role', ['measured_food_with_nonmeasured_physical_companion',
                                  'heterogeneous_declared_component_contents'])
def test_measured_food_physical_companion_keeps_known_content_without_homogeneous_unit_price(role):
    from copy import deepcopy
    from core.reviewed_content_quantities import REVIEWED_SOURCE_COMPONENT_LISTINGS
    from core.reviewed_source_evidence import valid_source_component_variant
    review = next(r for r in REVIEWED_SOURCE_COMPONENT_LISTINGS
                  if r.get('measurement_role') == role)
    components = deepcopy(review['components'])
    attributes = {'quantity_basis':'reviewed_source_component_vector_v1',
                  'scalar_basis':'one_complete_declared_vector_not_piece_count',
                  'source_components':components, 'source_component_listing':review}
    variant = {'package_quantity':1, 'package_unit':'세트', 'bundle_count':1,
               'standard_unit':None, 'attributes':attributes}
    assert valid_source_component_variant(variant)
    event = {'public_offer_event_id':'historical-gift-quote', 'price':5490,
             'price_state':'sale_price_only','promotion_type':'final_price', 'offer_state':'active',
             'standard_unit_price':3786.21, 'price_per_100g':3786.21,'raw_evidence':'{}'}
    offer = PublicCatalogStore._normalized_offer(event, {**variant,'attributes':json.dumps(attributes)})
    assert offer['listed_price'] == offer['total_price'] == 5490
    assert offer['quantity_unit'] == '세트' and offer['total_quantity'] == 1
    assert offer['received_package_count'] == 1
    assert offer['received_package_count_scope'] == 'complete_declared_vector'
    assert offer['quantity_basis'] == attributes['quantity_basis']
    assert offer['scalar_basis'] == attributes['scalar_basis']
    assert offer['per_100g'] is None and offer['per_100ml'] is None
    assert components[0]['quantity'] > 0 and components[0]['count'] is None
    if role == 'measured_food_with_nonmeasured_physical_companion':
        assert all(components[1][key] is None for key in ('quantity','unit','count'))
    else:
        assert [c['quantity'] for c in components] == [1200, 1200]
        assert all(c['count'] is None for c in components)
    assert variant['attributes']['source_components'] == components
    rejected = PublicCatalogStore._normalized_offer(event, {**variant, 'attributes': {}})
    assert rejected['quantity_basis'] is rejected['scalar_basis'] is rejected['received_package_count_scope'] is None


@pytest.fixture
def scoped_group_catalog(tmp_path, monkeypatch):
    import core.catalog_identity as identity
    path = tmp_path / 'scoped-group.sqlite'
    review = {'key': 'reviewed-milk', 'canonical_product_id': 'milk-a',
              'member_product_ids': ['milk-a', 'milk-b'], 'canonical_name': '같은 우유',
              'brand': '검토브랜드', 'review_version': 'reviewed_catalog_groups_v1'}
    monkeypatch.setattr(identity, 'reviewed_registry', lambda: {'groups': [{**review, 'leaf': 'food.milk'}]})
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE unified_categories(id TEXT PRIMARY KEY,parent_id TEXT,name_ko TEXT,sort_order INTEGER);
        CREATE TABLE normalized_canonical_products(public_product_id TEXT PRIMARY KEY,unified_category_id TEXT,
            canonical_name TEXT,brand TEXT,aliases TEXT,keywords TEXT,attributes TEXT,primary_image_url TEXT,is_active INTEGER);
        CREATE TABLE normalized_product_variants(public_variant_id TEXT PRIMARY KEY,public_product_id TEXT,
            variant_name TEXT,package_quantity REAL,package_unit TEXT,bundle_count INTEGER,display_unit TEXT,attributes TEXT,is_active INTEGER);
        CREATE TABLE normalized_source_listings(public_source_listing_id TEXT PRIMARY KEY,public_variant_id TEXT,
            source_name TEXT,source_record_key TEXT,source_title TEXT,source_url TEXT,image_url TEXT,source_unit_text TEXT,is_active INTEGER);
        CREATE TABLE normalized_offer_events(public_offer_event_id TEXT PRIMARY KEY,public_source_listing_id TEXT,
            price REAL,price_state TEXT,promotion_type TEXT,offer_state TEXT,crawled_at TEXT,raw_evidence TEXT);
        CREATE TABLE keywords(id INTEGER,word TEXT,synonyms TEXT,is_active INTEGER,unified_category_id TEXT);
        ''')
        db.executemany('INSERT INTO unified_categories VALUES(?,?,?,0)', [
            ('food', None, '식품'), ('food.milk', 'food', '우유'), ('food.snack', 'food', '과자')])
        for key, category, name, aliases, attrs, active in [
            ('milk-a', 'food.milk', '첫 상품', ['원문 별칭%'], {'catalog_group': review}, 1),
            ('milk-b', 'food.milk', '다른 원문', [], {'catalog_group': review}, 1),
            ('snack', 'food.snack', '밀크 과자', [], {}, 1),
            ('hidden', 'food.milk', '숨긴 우유', [], {}, 0)]:
            db.execute('INSERT INTO normalized_canonical_products VALUES(?,?,?,?,?,?,?,?,?)',
                (key, category, name, '브랜드', json.dumps(aliases), '[]', json.dumps(attrs), None, active))
        for key in ('milk-a', 'milk-b'):
            db.execute('INSERT INTO normalized_product_variants VALUES(?,?,?,?,?,?,?,?,?)',
                ('var-' + key, key, '200ml', 200, 'ml', 1, '200ml', '{}', 1))
            db.execute('INSERT INTO normalized_source_listings VALUES(?,?,?,?,?,?,?,?,?)',
                ('listing-' + key, 'var-' + key, 'homeplus', key, key + ' 200ml', 'https://example.test/' + key, None, '200ml', 1))
            for number, price, state in [(1, 2000, 'active'), (2, 1800, 'pending_review' if key == 'milk-a' else 'active')]:
                db.execute('INSERT INTO normalized_offer_events VALUES(?,?,?,?,?,?,?,?)',
                    (key + '-event-' + str(number), 'listing-' + key, price, 'normal', 'final_price', state,
                     '2026-10-0' + str(number) + 'T00:00:00Z', '{}'))
        db.executemany('INSERT INTO keywords VALUES(?,?,?,?,?)', [
            (1, '우유', json.dumps(json.dumps(['밀크'], ensure_ascii=True)), 1, 'food.milk'),
            (2, '과자', json.dumps(['밀크']), 0, 'food.snack'),
            (3, '오염', json.dumps(['공통검색']), 1, None),
            (4, '미등록', json.dumps(['잘못된검색']), 1, 'missing'),
            (5, '객체', json.dumps({'alias': '객체검색'}), 1, 'food.snack')])
    return path


@pytest.mark.parametrize('query,category,expected', [
    ('밀크', None, ['milk-a']), ('우유', 'food', ['milk-a']), ('밀크 과자', None, ['snack']),
    ('밀크', 'food.snack', []), ('공통검색', None, []), ('잘못된검색', None, []),
    ('객체검색', None, []), ('원문 별칭%', None, ['milk-a']), ('다른 원문', None, ['milk-a']),
    ('%', None, ['milk-a']), ('브랜드', None, ['milk-a', 'snack']),
])
def test_scoped_synonym_alias_search_groups_before_paging(scoped_group_catalog, query, category, expected):
    store = PublicCatalogStore(scoped_group_catalog)
    rows, total = store.search_normalized_products_page(query, category=category, per_page=1)
    assert total == len(expected)
    assert [row['id'] for row in rows] == expected[:1]
    if total > 1:
        second, _ = store.search_normalized_products_page(query, category=category, page=2, per_page=1)
        assert [row['id'] for row in second] == expected[1:]


def test_group_detail_preserves_requested_id_selected_variants_and_full_history(scoped_group_catalog, monkeypatch):
    store = PublicCatalogStore(scoped_group_catalog)
    calls = []
    original = PublicCatalogStore._normalized_offer
    def counted(event, *args, **kwargs):
        calls.append(event['public_offer_event_id'])
        return original(event, *args, **kwargs)
    monkeypatch.setattr(PublicCatalogStore, '_normalized_offer', staticmethod(counted))
    rows, total = store.search_normalized_products_page('밀크')
    assert total == 1 and len(calls) == 2
    assert set(calls) == {'milk-a-event-2', 'milk-b-event-2'}
    assert rows[0]['best_offer']['id'] == 'milk-b-event-2'
    assert rows[0]['cur'] == 1800  # No fallback to milk-a's earlier eligible event.
    calls.clear()
    detail = store.get_normalized_product_detail('milk-b')
    assert detail['id'] == detail['public_product_id'] == 'milk-b'
    assert detail['canonical_public_product_id'] == 'milk-a'
    assert detail['group_member_product_ids'] == ['milk-a', 'milk-b']
    assert detail['name'] == '같은 우유' and len(calls) == 4
    assert {v['id'] for v in detail['variants']} == {'var-milk-a', 'var-milk-b'}
    assert all(v['package_quantity'] == 200 for v in detail['variants'])
    assert all(len(v['listings'][0]['offers']) == 2 for v in detail['variants'])


@pytest.mark.parametrize('mutation', ['nonreciprocal', 'unregistered', 'wrong_leaf', 'malformed', 'inactive_canonical'])
def test_invalid_group_metadata_cannot_merge_product_identities(scoped_group_catalog, mutation):
    with sqlite3.connect(scoped_group_catalog) as db:
        if mutation == 'nonreciprocal':
            db.execute("UPDATE normalized_canonical_products SET attributes='{}' WHERE public_product_id='milk-b'")
        elif mutation == 'unregistered':
            rows = db.execute("SELECT public_product_id,attributes FROM normalized_canonical_products WHERE public_product_id LIKE 'milk-%'").fetchall()
            for key, text in rows:
                attrs = json.loads(text)
                attrs['catalog_group']['key'] = 'invented'
                db.execute('UPDATE normalized_canonical_products SET attributes=? WHERE public_product_id=?', (json.dumps(attrs), key))
        elif mutation == 'wrong_leaf':
            db.execute("UPDATE normalized_canonical_products SET unified_category_id='food.snack' WHERE public_product_id LIKE 'milk-%'")
        elif mutation == 'malformed':
            db.execute("UPDATE normalized_canonical_products SET attributes='null' WHERE public_product_id='milk-b'")
        else:
            db.execute("UPDATE normalized_canonical_products SET is_active=0 WHERE public_product_id='milk-a'")
    store = PublicCatalogStore(scoped_group_catalog)
    rows, total = store.search_normalized_products_page('브랜드')
    expected = 2 if mutation == 'inactive_canonical' else 3
    assert total == len(rows) == expected
    assert all(row['group_member_product_ids'] == [row['id']] for row in rows)


@pytest.mark.parametrize('query,category,expected', [
    ('펩시콜라', None, {'pepsi', 'named-alias'}),
    ('코카콜라', None, {'coke'}),
    ('아이시스', None, {'isis'}),
    ('펩시제로', None, {'pepsi-zero'}),
    ('아이시스 생수', None, {'isis'}),
    ('콜라', None, {'pepsi', 'coke', 'pepsi-zero', 'named-alias'}),
    ('펩시콜라', 'food.milk', set()),
    ('초콜릿우유', None, {'milk-a'}),
    ('초콜릿우유', 'food.snack', set()),
    ('유제품', None, {'milk-a'}),
    ('자펩시음료', None, {'pepsi', 'coke', 'pepsi-zero', 'named-alias'}),
    ('ABCs', None, {'milk-a'}),
    ('펩시%콜라', None, {'named-alias'}),
    ('펩시_콜라', None, {'named-alias'}),
    ('모형 콜라', None, {'named-alias'}),
])
def test_named_identity_keyword_synonyms_do_not_expand_to_competing_brands(scoped_group_catalog, monkeypatch, query, category, expected):
    import core.catalog_identity as identity
    groups = identity.reviewed_registry()['groups']
    monkeypatch.setattr(identity, 'reviewed_registry', lambda: {'groups': groups + [
        {'brand':'펩시', 'canonical_name':'펩시콜라'},
        {'brand':'코카콜라', 'canonical_name':'코카콜라'},
        {'brand':'아이시스', 'canonical_name':'아이시스'},
        {'brand':None, 'canonical_name':None},
        {'brand':'유', 'canonical_name':'별도 상품'},
        {'brand':'ABC', 'canonical_name':'ABC plain milk'},
        {'brand':None, 'canonical_name':'모형콜라'},
    ]})
    with sqlite3.connect(scoped_group_catalog) as db:
        db.executemany('INSERT INTO unified_categories VALUES(?,?,?,0)', [
            ('food.cola', 'food', '콜라'), ('food.water', 'food', '생수')])
        for key, leaf, name, brand, aliases in [
            ('pepsi', 'food.cola', '펩시콜라', '펩시', []),
            ('pepsi-zero', 'food.cola', '펩시제로', '펩시', []),
            ('coke', 'food.cola', '코카콜라', '코카콜라', []),
            ('named-alias', 'food.cola', '출처 음료', None, ['펩시콜라','펩시%콜라','펩시_콜라','모형 콜라']),
            ('isis', 'food.water', '아이시스 생수', '아이시스', []),
            ('samdasu', 'food.water', '삼다수 생수', '삼다수', []),
            ('branded-snack', 'food.snack', '펩시콜라맛 과자', '펩시', []),
        ]:
            db.execute('INSERT INTO normalized_canonical_products VALUES(?,?,?,?,?,?,?,?,?)',
                       (key, leaf, name, brand, json.dumps(aliases), '[]', '{}', None, 1))
        db.execute("UPDATE normalized_canonical_products SET canonical_name='초콜릿우유맛 쿠키' WHERE public_product_id='snack'")
        db.executemany('INSERT INTO keywords VALUES(?,?,?,?,?)', [
            (10, '콜라', json.dumps(['펩시콜라','코카콜라','펩시제로','자펩시음료','펩시%콜라','펩시_콜라','모형 콜라']), 1, 'food.cola'),
            (11, '생수', json.dumps(['아이시스']), 1, 'food.water'),
            (12, '우유', json.dumps(['초콜릿우유','유제품','ABCs']), 1, 'food.milk'),
        ])
    rows, total = PublicCatalogStore(scoped_group_catalog).search_normalized_products_page(query, category=category)
    assert total == len(expected)
    assert {row['id'] for row in rows} == expected
