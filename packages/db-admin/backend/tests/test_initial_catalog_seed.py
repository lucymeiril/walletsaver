from __future__ import annotations

from copy import deepcopy
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.match_key import build_match_key
from core.product_units import parse_package_quantity
from core.reviewed_content_quantities import COUNTED_CONTENT_TITLES
from services.catalog_bundle import validate_bundle
from services.initial_catalog_seed import (
    build_initial_catalog_bundle,
    normalize_pending_ingestions,
    stable_id,
    validated_brand,
    _package,
    _sheet_roll_package,
)
from storage.models import Base


@pytest.mark.parametrize('title,count', [
    ('에너자이저 맥스 AA 10+10 기획팩', None),
    ('에너자이저 맥스 AAA 10+10 기획팩', None),
    ('벡셀 프리미엄 건전지 AAA 8+8입', 16),
])
def test_reviewed_additive_battery_pack_does_not_become_purchase_multiplier(title, count):
    from core.reviewed_content_quantities import REVIEWED_NONMEASURED_LISTINGS, REVIEWED_EXPLICIT_LISTING_PACKAGES
    from core.reviewed_source_evidence import valid_nonmeasured_variant, valid_explicit_listing_variant
    from services.initial_catalog_seed import _price
    reviews = REVIEWED_NONMEASURED_LISTINGS + REVIEWED_EXPLICIT_LISTING_PACKAGES
    review = next(r for r in reviews if r['title'] == title and r.get('measurement_role') == 'declared_additive_battery_pack')
    raw = {'name': title, 'sale_price': 9000, 'attributes': {}}
    for name, value in {**review['required_source']['source_fields'], **review['quantity_fields']}.items():
        layer, key = (raw['attributes'], name[11:]) if name.startswith('attributes.') else (raw, name)
        if isinstance(value, list):
            value = f'{value[0]}{value[1]} 당 500원'
        layer[key] = value
    for key in ('canonical_url', 'detail_url', 'source_url'):
        raw[key] = review['required_source']['source_urls'][0]
    raw['attributes']['promo_label'] = review['declared_pack_specification']['expression']
    leaf = review['category_id']
    package, issues = _package(raw, raw['attributes'], title, category_id=leaf)
    assert not issues and package['package_quantity'] == count and package['bundle_count'] == 1
    valid = valid_nonmeasured_variant if count is None else valid_explicit_listing_variant
    assert valid(package)
    price, issues = _price(raw, raw['attributes'], 'emart', title)
    assert price['price'] == 9000 and price['promotion_type'] == 'unknown'
    assert price['promotion_conditions']['payable_price_unconfirmed'] is True
    assert 'buy_quantity' not in price['promotion_conditions'] and 'minimum_quantity' not in price['promotion_conditions']
    changed = deepcopy(raw)
    changed['sale_price'] = 11000
    changed['attributes']['unit_price_display'] = '1개 당 700원'
    assert _package(changed, changed['attributes'], title, category_id=leaf) == (package, [])
    wrong_quantity = deepcopy(raw)
    wrong_quantity['package_quantity'] = 7
    wrong_basis = deepcopy(raw)
    wrong_basis['attributes']['unit_price_display'] = '1마리 당 500원'
    missing_url = deepcopy(raw)
    for key in ('canonical_url', 'detail_url', 'source_url'):
        missing_url.pop(key)
    for changed in (wrong_quantity, wrong_basis, missing_url):
        assert _package(changed, changed['attributes'], title, category_id=leaf)[0] is None
    assert _package(raw, raw['attributes'], title, category_id='food.drinks.water_soda.water')[0] is None
    malformed = deepcopy(package)
    malformed['package_quantity'] = 1 if count is None else 8
    assert not valid(malformed)
    assert _package({'package_quantity': 1, 'package_unit': '개'}, {},
                    '다른 건전지 AAA 8+8입', category_id=leaf)[0] is None


@pytest.mark.parametrize('species,title', [
    ('beef', '냉동 한우 양지 500g'),
    ('pork', '냉동 돼지 삼겹살 500g'),
    ('chicken', '냉동 닭다리 500g'),
])
def test_exact_quantity_proof_survives_only_same_raw_species_storage_refinement(monkeypatch, species, title):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    from services.initial_taxonomy import taxonomy_categories
    raw = item(name=title, package_quantity=500, package_unit='g', unit='500g', display_unit='500g',
               detail_url='https://retailer.example/quantity-proof', attributes={'source_record_key':'123'})
    review = {'title': title, 'category_id': f'food.meat.fresh.{species}',
              'required_source': source_review_evidence(raw), 'quantity_fields': listing_quantity_evidence(raw),
              'normalized': [500, 'g', 1], 'reason': 'Exact named raw species and sold mass; storage is separate.'}
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_EXPLICIT_LISTING_PACKAGES', (review,))
    leaf = f'food.meat.frozen.{species}'
    leaves = {leaf, 'food.meat.frozen.beef', 'food.meat.frozen.pork', 'food.meat.frozen.chicken', 'food.meals.prepared.chicken'}
    bundle = build_initial_catalog_bundle([ingestion(rows=[raw])], categories=taxonomy_categories(leaves),
             assignments={('homeplus','123'): assignment(unified_category_id=leaf)}, run_id='storage-refinement-focused')
    assert bundle['variants'][0]['attributes']['explicit_listing_quantity_review'] == review
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'storage-proof').ok
        for wrong in leaves - {leaf}:
            changed = deepcopy(bundle)
            changed['products'][0]['unified_category_id'] = wrong
            assert any('명시적 listing 수량 계약' in error for error in validate_bundle(session, changed, 'wrong-species').errors)
        for field, value in [('package_quantity', 501), ('package_unit', 'ml'), ('bundle_count', 2)]:
            changed = deepcopy(bundle)
            changed['variants'][0][field] = value
            assert any('명시적 listing 수량 계약' in error for error in validate_bundle(session, changed, 'wrong-contents').errors)
    engine.dispose()


CATEGORIES = [
    {"id": "food", "parent_id": None, "name_ko": "식품"},
    {"id": "food.dairy", "parent_id": "food", "name_ko": "유제품"},
    {"id": "food.dairy.milk", "parent_id": "food.dairy", "name_ko": "우유"},
    {"id": "food.dairy.milk.chocolate", "parent_id": "food.dairy.milk", "name_ko": "초코우유"},
]
LEAF = "food.dairy.milk.chocolate"


@pytest.mark.parametrize('unit,layer', [('인', 'payload'), ('인분', 'payload'), ('인', 'attributes')])
def test_facility_service_occupancy_stays_unloaded_after_category_materialization(unit, layer):
    from services.initial_taxonomy import taxonomy_categories
    leaf = 'services.facility.camping.cabin_package'
    raw = item(name='캐빈 이용패키지 2인', package_quantity=None, package_unit='',
               unit='', display_unit='')
    values = {'package_quantity': 2, 'package_unit': unit, 'display_unit': '2' + unit}
    (raw if layer == 'payload' else raw['attributes']).update(values)
    original = deepcopy(raw)
    bundle = build_initial_catalog_bundle([ingestion(rows=[raw])], categories=taxonomy_categories([leaf]),
        assignments={('homeplus', '123'): assignment(unified_category_id=leaf)}, run_id='facility-occupancy')
    assert bundle['products'] == bundle['variants'] == bundle['offers'] == []
    assert 'unit_service_occupancy_not_entitlement' in bundle['unresolved'][0]['reasons']
    assert bundle['unresolved'][0]['package'] is None
    assert bundle['unresolved'][0]['raw_payload'] == original
    # A literal ticket count remains separate from how many people may occupy it.
    tickets, issues = _package({'package_quantity': 2, 'package_unit': '매', 'display_unit': '2매'},
                              {}, '캐빈 이용권 2매', category_id=leaf)
    assert not issues and (tickets['package_quantity'], tickets['package_unit']) == (2, '매')
    food, issues = _package(values, {}, '식사 2인분', category_id=LEAF)
    assert food is not None and not issues


@pytest.mark.parametrize('native,expected_count,quote', [('509119', 20, 41990), ('523645', 400, 689900)])
def test_registered_sunkist_originals_keep_recipe_vectors_and_apply_outer_sets_once(native, expected_count, quote):
    from services.initial_taxonomy import taxonomy_categories
    from core.catalog_quantity import package_pricing_measure
    # Actual original product-only fields: ingestion41:95 SHA666baad4e8cf9737a721ddab05c5c699ff9179a293fc05797e0790cecec54ae3;
    # ingestion41:91 SHA60abef485ca970eeaad6c6356bb135147fd2eaf36e4936c5282dc5f390474825.
    outer = native == '523645'
    title = '썬키스트 견과 ３종세트 25g x 60봉' + (' x 20세트' if outer else '')
    slug = 'Sunkist-Nut-3-Variety-25g-x-60-x-20set' if outer else 'Sunkist-Nut-3-Variety-Set-25g-x-60'
    url = f'https://www.costco.co.kr/Gift-Set-Special/Food-Gift-Set/{slug}/p/{native}'
    display = '개　　　당 34,495원' if outer else '100G당 2,799원'
    raw = {'name': title, 'normalized_name': title, 'raw_name': title, 'brand': '__no_brand__',
           'source': 'costco', 'mart': 'costco', 'source_record_key': native, 'mart_native_code': native,
           'canonical_url': url, 'detail_url': url, 'source_url': url,
           'category': '과자', 'mart_native_category_path': '과자',
           'image_url': ('https://www.costco.co.kr/medias/sys_master/images/ha1/h4f/9867896717342.jpg' if outer
                         else 'https://www.costco.co.kr/medias/sys_master/images/h4e/h2c/9894602407966.jpg'),
           'pack_qty': 60, 'pack_unit': '봉', 'price': quote, 'sale_price': quote,
           'unit_price_display': display, 'unit_price_text': display,
           'unit_price_basis': '개　　　' if outer else '100G',
           'unit_price_basis_raw': '개　　　' if outer else '100G',
           'crawled_at': '2026-08-31T01:51:51.875403Z'}
    before = deepcopy(raw)
    leaf = 'food.grains.nuts.mixed'
    bundle = build_initial_catalog_bundle([ingestion(rows=[raw], mart='costco')],
        categories=taxonomy_categories({leaf}),
        assignments={('costco', native): assignment(unified_category_id=leaf)}, run_id='sunkist-original-vector')
    assert not bundle['unresolved'] and len(bundle['offers']) == len(bundle['variants']) == 1
    variant = bundle['variants'][0]
    assert (variant['package_quantity'], variant['package_unit'], variant['bundle_count']) == (1, '세트', 1)
    components = variant['attributes']['source_components']
    assert [c['identity'] for c in components] == ['썬키스트 25 클래식', '썬키스트 25 팝', '썬키스트 25 재즈']
    assert all((c['quantity'], c['unit'], c['count'], c['amount_scope']) ==
               (25, 'g', expected_count, 'per_counted_component') for c in components)
    assert sum(c['quantity'] * c['count'] for c in components) == (30000 if outer else 1500)
    assert variant['standard_unit'] is None
    assert package_pricing_measure(variant) is None
    offer = bundle['offers'][0]
    assert offer['price'] == quote
    assert offer['standard_unit_price'] is None and offer['price_per_100g'] is None
    assert bundle['source_listings'][0]['source_record_key'] == native
    assert raw == before
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            assert validate_bundle(session, bundle, 'sunkist-vector').ok
            doubled = deepcopy(bundle)
            doubled['variants'][0]['attributes']['source_components'][0]['count'] *= 20
            assert not validate_bundle(session, doubled, 'repeated-outer-factor').ok
    finally:
        engine.dispose()


def test_declared_assortment_hierarchy_keeps_quantity_separate_from_recipe_hold(monkeypatch):
    from core.catalog_quantity import normalize_catalog_package
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import valid_explicit_listing_variant
    # The real Sunkist assortment now has a complete, source-bound recipe
    # vector. Keep this partial-hierarchy contract independent of that data.
    review = deepcopy(next(record for record in reviewed_content_quantities.REVIEWED_EXPLICIT_LISTING_PACKAGES
                          if record['title'] == '썬키스트 견과 3종세트 25g x 60봉 x 20세트'))
    title = '검수 견과 3종세트 25g x 60봉 x 20세트'
    review['title'] = title
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_EXPLICIT_LISTING_PACKAGES', (review,))
    row = {'name': title, 'source_url': 'https://www.costco.co.kr/Gift-Set-Special/Food-Gift-Set/Sunkist-Nut-3-Variety-25g-x-60-x-20set/p/523645',
           'category': '과자', 'mart_native_category_path': '과자', 'pack_qty': 60, 'pack_unit': '봉',
           'unit_price_display': '개당 34,495원', 'unit_price_basis': '개',
           'unit_price_basis_raw': '개', 'unit_price_text': '개당 34,495원'}
    package, issues = normalize_catalog_package(row, {}, title)
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == (25, 'g', 1200)
    assert package['attributes']['declared_package_structure']['variety_allocation'] is None
    assert 'source_assortment_composition_unresolved' in issues
    assert not valid_explicit_listing_variant(package)
    quote_changed, changed_issues = normalize_catalog_package({**row,
        'unit_price_display': '개당 30,000원', 'unit_price_text': '개당 30,000원'}, {}, title)
    assert quote_changed == package and changed_issues == issues
    for mutation in ({'pack_qty': 61}, {'source_url': 'https://www.costco.co.kr/p/other'}):
        rejected, conflicts = normalize_catalog_package({**row, **mutation}, {}, title)
        assert rejected is None and conflicts


@pytest.mark.parametrize("payload,attrs", [({}, {}), ({"package_quantity": 50, "package_unit": "매입"}, {}), ({}, {"display_unit": "50매"})])
def test_reviewed_stock_bag_count(payload, attrs):
    from core.catalog_quantity import uses_reviewed_quantity_rules
    title = "simplus 국물팩(소) 50매입"
    package, issues = _package(payload, attrs, title)
    assert issues == []
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (50, "개", 1)
    assert package["standard_unit"] is None
    assert uses_reviewed_quantity_rules(title)


@pytest.mark.parametrize("bad", [{"package_quantity": 20}, {"package_unit": "ml"}, {"bundle_count": 2}, {"bundle_count": "invalid"}, {"display_unit": "50매+50매"}, {"unit": "100개"}])
def test_reviewed_stock_bag_does_not_hide_either_layer_conflicts(bad):
    for payload, attrs in [(bad, {}), ({"package_quantity": 50, "package_unit": "개"}, bad)]:
        package, issues = _package(payload, attrs, "simplus 국물팩(소) 50매입")
        assert package is None and issues


@pytest.mark.parametrize("title", ["simplus 국물팩(소) 50매입+50매입", "simplus 국물팩(소) 50매입 x2", "simplus 국물팩(소) 50매입 혼합세트", "simplus 국물팩(소)", "정체불명 50매입"])
def test_stock_bag_repair_is_not_a_generic_quantity_guess(title):
    from core.catalog_quantity import uses_reviewed_quantity_rules
    assert not uses_reviewed_quantity_rules(title)
    package, issues = _package({}, {}, title)
    assert package is None and issues


@pytest.mark.parametrize("title,capacity,count", [
    ("종이컵180ml*50개", 180, 50),
    ("테이크아웃 종이컵 380ml 100개입", 380, 100),
    ("두꺼운 종이컵 260ml / 40p", 260, 40),
    ("종이컵 180ml*450P", 180, 450),
    ("종이컵180ml*1000개", 180, 1000),
    ("simplus 다회용투명컵 190ML*20개입", 190, 20),
    ("simplus 다회용투명소주컵65ML 25개입", 65, 25),
    ("simplus 다회용투명컵 280ML*10개입", 280, 10),
])
def test_paper_cup_capacity_is_not_consumable_volume(title, capacity, count):
    package, issues = _package({"package_quantity": capacity, "package_unit": "ml"}, {}, title)
    assert issues == []
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (count, "개", 1)
    assert package["standard_unit"] is None
    assert package["display_unit"] == title


@pytest.mark.parametrize("title", [
    "종이컵 180ml", "종이컵뚜껑 473ML 25P", "종이컵 180ml 50개+50개",
    "종이컵 180ml 50개 세트", "종이컵 180ml*50개*2팩",
    "종이컵 180ml 50~60개", "종이컵 180ml 50-60개",
    "다회용투명컵 180ml", "다회용투명컵 180ml 20개+20개", "다회용투명컵뚜껑 180ml 20개",
    "다회용투명컵 180ml 20개 혼합세트", "다회용투명컵 180ml*20개*2팩",
])
def test_ambiguous_cup_counts_and_mixed_products_remain_unresolved(title):
    package, issues = _package({"package_quantity": 180, "package_unit": "ml"}, {}, title)
    assert package is None
    assert issues


def test_cup_structured_capacity_and_count_conflicts_are_not_hidden():
    for payload in [
        {"package_quantity": 200, "package_unit": "ml"},
        {"package_quantity": 20, "package_unit": "개"},
        {"package_quantity": 180, "package_unit": "ml", "bundle_count": 2},
    ]:
        assert _package(payload, {}, "종이컵180ml*50개")[0] is None


def test_explicit_rubber_glove_pairs_recover_missing_crawler_quantity():
    package, issues = _package({}, {}, "고무장갑 2켤레(중)")
    assert issues == []
    assert package["package_quantity"] == 2
    assert package["package_unit"] == "켤레"
    assert package["standard_unit"] is None
    for title in ["고무장갑 중형", "고무장갑 2켤레+1켤레", "고무장갑 2켤레 x 2", "팬28cm", "미검토 종이호일30cm*40m"]:
        assert _package({}, {}, title)[0] is None


@pytest.mark.parametrize("title,sheets,rolls", [
    ("안심 키친타월 120매x12롤 ESG", 120, 12),
    ("키친타올 200매*6롤", 200, 6),
    ("빨아쓰는 위생행주 MAX 45매x3롤", 45, 3),
    ("커클랜드 시그니춰 종이타월 160매 x 12롤", 160, 12),
])
@pytest.mark.parametrize("structured_unit", ["롤", "매"])
def test_complete_sheet_roll_chain_preserves_per_roll_and_purchased_quantity(title, sheets, rolls, structured_unit):
    quantity = rolls if structured_unit == "롤" else sheets
    package, issues = _package({"package_quantity": quantity, "package_unit": structured_unit,
                               "display_unit": f"{quantity}{structured_unit}"}, {}, title)
    assert issues == []
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (sheets, "매", rolls)
    assert package["standard_unit"] is None
    assert package["display_unit"] == title


@pytest.mark.parametrize("payload", [
    {"package_quantity": 5, "package_unit": "롤"},
    {"package_quantity": 150, "package_unit": "매"},
    {"package_quantity": 200, "package_unit": "ml"},
    {"package_quantity": 200, "package_unit": "매", "bundle_count": 1},
    {"package_quantity": 6, "package_unit": "롤", "bundle_count": 6},
    {"package_quantity": 6, "package_unit": "롤", "bundle_count": "bad"},
    {"package_quantity": 6, "package_unit": "롤", "display_unit": "4롤"},
    {"package_quantity": 6, "package_unit": "롤", "display_unit": "200매x6롤x2"},
])
def test_sheet_roll_structured_and_display_conflicts_remain_pending(payload):
    assert _package(payload, {}, "키친타올 200매*6롤")[0] is None


@pytest.mark.parametrize("title", [
    "키친타올 200매*6롤*2팩", "키친타올 200매*6롤+행주 20매",
    "키친타올 200매*6롤 혼합세트", "키친타올 200매*5~6롤",
    "냉동식품 200매*6롤", "팬28cm*6", "종이호일30cm*40m",
])
def test_sheet_roll_recovery_does_not_resolve_partial_mixed_or_wrong_forms(title):
    assert _sheet_roll_package({"package_quantity": 200, "package_unit": "매"}, {}, title) is None


def test_sheet_roll_offer_preserves_total_sheets_without_inventing_volume_price():
    raw = item(name="키친타올 200매*6롤", package_quantity=6, package_unit="롤",
               display_unit="6롤", unit="6롤", sale_price=6000, original_price=None)
    bundle = build([ingestion(1, [raw])])
    assert not bundle["unresolved"]
    assert bundle["variants"][0]["package_quantity"] * bundle["variants"][0]["bundle_count"] == 1200
    assert bundle["offers"][0]["standard_unit_price"] is None
    assert bundle["offers"][0]["price_per_100g"] is None

@pytest.mark.parametrize("title,count", [
    ("부드러운 복숭아 4~6입 팩", 6),
    ("천안배 (배 5-6입)", 6),
    ("제스프리 골드키위 (20~25입)", 25),
])
def test_resolved_fruit_identity_does_not_make_a_quantity_range_exact(title, count):
    raw = item(name=title, package_quantity=count, package_unit="입", display_unit=f"{count}입", unit=f"{count}입")
    bundle = build([ingestion(1, [raw])])
    assert not bundle["offers"]
    assert "count_range_unresolved" in bundle["unresolved"][0]["reasons"]


@pytest.mark.parametrize('interval_unit', ['개', '송이'])
def test_reviewed_declared_count_interval_keeps_unknown_exact_count_and_price(monkeypatch, interval_unit):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    raw = item(name='검수된 복숭아 4~7입 팩', package_quantity=7, package_unit='입',
               unit='7입', display_unit='7입', original_price=None, event_name='')
    if interval_unit == '송이':
        raw.update(name='검수된 포도 3kg 내외(4~7송이)', package_quantity=3,
                   package_unit='kg', unit='3kg', display_unit='3kg')
    review = {'title':raw['name'], 'category_id':LEAF,
              'required_source':source_review_evidence(raw), 'quantity_fields':listing_quantity_evidence(raw),
              'count_interval':[4,7,interval_unit]}
    if interval_unit == '송이':
        review['identity_basis'] = 'declared_interval_unit_v2'
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_COUNT_INTERVAL_LISTINGS', (review,))
    bundle = build([ingestion(rows=[raw])])
    assert not bundle['unresolved']
    variant = bundle['variants'][0]
    assert variant['package_quantity'] is None and variant['package_unit'] == interval_unit
    assert variant['attributes']['count_interval'] == [4,7,interval_unit]
    assert variant['attributes']['sold_piece_count'] is None
    assert bundle['offers'][0]['price'] == raw['sale_price']
    assert bundle['offers'][0]['standard_unit_price'] is None
    assert bundle['offers'][0]['price_per_100g'] is None
    if interval_unit == '송이':
        # Source proof is traceability, not sold specification identity.
        first_id = variant['public_variant_id']
        review['reason'] = 'Reworded audit evidence must not change sold interval identity.'
        assert build([ingestion(rows=[raw])])['variants'][0]['public_variant_id'] == first_id
        review.pop('reason')
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'interval').ok
        for quantity in (4,5.5,7):
            forged = deepcopy(bundle); forged['variants'][0]['package_quantity'] = quantity
            assert not validate_bundle(session, forged, 'interval').ok


def test_exact_sku_title_history_preserves_original_contexts_and_offers(monkeypatch):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    old = item(name='검수브랜드 소스 350g', package_quantity=350, package_unit='g',
               unit='350g', display_unit='350g', original_price=None, event_name='')
    new = {**old, 'name':'[쿠폰] 검수브랜드 소스 350g', 'sale_price':15000}
    review = {'source_name':'homeplus', 'source_record_key':'123', 'category_id':LEAF,
              'aliases':[{'title':r['name'], 'required_source':source_review_evidence(r),
                          'quantity_fields':listing_quantity_evidence(r)} for r in (old,new)]}
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', (review,))
    bundle = build([ingestion(1,[old]),ingestion(2,[new])])
    assert not bundle['unresolved'] and len(bundle['products']) == 1
    assert len(bundle['variants']) == 1 and len(bundle['match_rules']) == 2
    assert len(bundle['observation_accounting']) == 2
    assert bundle['variants'][0]['attributes']['source_title_history'] == review
    assert {offer['price'] for offer in bundle['offers']} == {19900,15000}
    unexpected = {**new,'name':'검수브랜드 다른맛 소스 350g'}
    held = build([ingestion(1,[old]),ingestion(2,[unexpected])])
    assert not held['products'] and all('source_title_changed' in r['reasons'] for r in held['unresolved'])


@pytest.fixture
def physical_title_history_source():
    # Approved exact title/source/quantity contract. Prices and fixture ingestion
    # IDs are controlled test observations, not reconstructed production events.
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    proposal = json.loads((root / '.debug-artifacts/review-proposals/continuation228-physical-title-history-semantic.json').read_text())
    review = proposal['record']
    alias = review['aliases'][0]
    raw = item(name=alias['title'], original_price=None, event_name='',
               attributes={'source_record_key': review['source_record_key']})
    for field, value in {**alias['required_source']['source_fields'], **alias['quantity_fields']}.items():
        layer, key = (raw['attributes'], field[11:]) if field.startswith('attributes.') else (raw, field)
        layer[key] = deepcopy(value)
    raw['detail_url'] = alias['required_source']['source_urls'][0]
    return raw, review, proposal['old_primary_physical_proof']


def test_physical_single_title_history_adds_exact_unobserved_key_preserving_all_original_events(monkeypatch, physical_title_history_source):
    from core import reviewed_content_quantities
    from core.catalog_matching import _match_key_for_row
    from services.initial_taxonomy import taxonomy_categories
    raw, review, original_proof = physical_title_history_source
    observations = [ingestion(1, [raw]), ingestion(2, [deepcopy(raw)])]
    kwargs = dict(categories=taxonomy_categories([review['category_id']]),
                  assignments={('homeplus', review['source_record_key']): assignment(unified_category_id=review['category_id'])},
                  run_id='physical-title-history-focused')
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', ())
    before = build_initial_catalog_bundle(observations, **kwargs)
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', (review,))
    after = build_initial_catalog_bundle(observations, **kwargs)
    assert not before['unresolved'] and not after['unresolved']
    assert len(after['products']) == len(after['variants']) == len(after['source_listings']) == len(after['offers']) == 1
    assert len(before['match_rules']) == 1 and len(after['match_rules']) == 2
    assert len(after['observation_accounting']) == 2
    for collection in ('products', 'source_listings', 'offers', 'offer_week_links', 'observation_accounting'):
        assert after[collection] == before[collection]
    variant = deepcopy(after['variants'][0])
    assert variant == before['variants'][0]
    assert 'source_title_history' not in variant['attributes']
    assert variant['attributes']['physical_device_specification'] == original_proof
    assert variant['package_quantity'] == 1 and variant['package_unit'] == '개'
    assert variant['standard_unit'] is None and after['offers'][0]['standard_unit_price'] is None
    old_rule = before['match_rules'][0]
    assert old_rule in after['match_rules']
    # No stale normalization can stand in for the approved raw alias title.
    alias_row = {**deepcopy(raw), 'name': review['aliases'][1]['title']}
    alias_key, error = _match_key_for_row(alias_row)
    assert error is None
    assert {rule['match_key'] for rule in after['match_rules']} == {old_rule['match_key'], alias_key}
    assert all(rule['public_variant_id'] == variant['public_variant_id']
               and rule['source_raw_record_ids'] == ['ingestion:1:0', 'ingestion:2:0'] for rule in after['match_rules'])
    changed = deepcopy(raw)
    changed['sale_price'] = 21000
    changed_price = build_initial_catalog_bundle([ingestion(1, [changed])], **kwargs)
    assert changed_price['variants'][0]['public_variant_id'] == variant['public_variant_id']
    assert changed_price['variants'][0]['attributes']['physical_device_specification'] == original_proof
    assert {rule['match_key'] for rule in changed_price['match_rules']} == {old_rule['match_key'], alias_key}
    assert changed_price['offers'][0]['price'] == 21000


@pytest.mark.parametrize('conflict', ['original_url', 'original_quantity', 'original_path', 'mixed_original_path', 'record_category',
                                     'alias_url', 'alias_quantity', 'alias_count', 'alias_role'])
def test_physical_single_title_history_requires_same_source_quantity_count_role_and_category(monkeypatch, physical_title_history_source, conflict):
    from core import reviewed_content_quantities
    from services.initial_taxonomy import taxonomy_categories
    raw, review, _ = physical_title_history_source
    leaf = review['category_id']
    if conflict == 'original_url': raw['detail_url'] += '&other=context'
    if conflict == 'original_quantity': raw['package_quantity'] = 201
    if conflict == 'original_path': raw['attributes']['category_hint'] = '다른 문맥'
    if conflict == 'record_category': review['category_id'] = 'household.bath.textiles.bath_robe'
    alias = review['aliases'][1]
    if conflict == 'alias_url': alias['required_source']['source_urls'] = ['https://example.test/other']
    if conflict == 'alias_quantity': alias['quantity_fields']['package_quantity'] = 201
    if conflict == 'alias_count': alias['title'] = alias['title'].replace('1P', '2P')
    if conflict == 'alias_role': alias['quantity_fields']['package_unit'] = 'ml'
    kwargs = dict(categories=taxonomy_categories([leaf]),
                  assignments={('homeplus', '070894758'): assignment(unified_category_id=leaf)},
                  run_id='physical-title-history-source-negative')
    observations = [ingestion(rows=[raw])]
    if conflict == 'mixed_original_path':
        other = deepcopy(raw)
        other['attributes']['category_hint'] = '다른 문맥'
        observations.append(ingestion(2, [other]))
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', ())
    before = build_initial_catalog_bundle(observations, **kwargs)
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', (review,))
    after = build_initial_catalog_bundle(observations, **kwargs)
    assert after['variants'] == before['variants'] and len(after['match_rules']) == 1
    assert after['offers'] == before['offers'] and after['observation_accounting'] == before['observation_accounting']
    assert 'source_title_history' not in after['variants'][0]['attributes']


def test_physical_unobserved_alias_reconstructs_key_without_stale_original_normalization(monkeypatch, physical_title_history_source):
    from core import reviewed_content_quantities
    from core.catalog_matching import _match_key_for_row
    from services.initial_taxonomy import taxonomy_categories
    raw, review, original_proof = physical_title_history_source
    original_key, error = _match_key_for_row(raw)
    assert error is None
    raw.update(match_key=original_key, matching_status='miss', name_core='stale 다른 수건', normalized_name='stale 다른 수건')
    kwargs = dict(categories=taxonomy_categories([review['category_id']]),
                  assignments={('homeplus', review['source_record_key']): assignment(unified_category_id=review['category_id'])},
                  run_id='physical-title-history-stale-key')
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', ())
    before = build_initial_catalog_bundle([ingestion(rows=[raw])], **kwargs)
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', (review,))
    result = build_initial_catalog_bundle([ingestion(rows=[raw])], **kwargs)
    alias = {key: value for key, value in raw.items() if key not in {'match_key', 'matching_status', 'name_core', 'normalized_name'}}
    alias['name'] = review['aliases'][1]['title']
    alias_key, error = _match_key_for_row(alias)
    assert error is None and alias_key != original_key
    assert {rule['match_key'] for rule in result['match_rules']} == {original_key, alias_key}
    assert result['variants'] == before['variants']
    assert 'source_title_history' not in result['variants'][0]['attributes']
    assert result['variants'][0]['attributes']['physical_device_specification'] == original_proof
    assert len(result['observation_accounting']) == len(result['offers']) == 1


def test_ordinary_single_title_does_not_gain_unobserved_registry_alias(monkeypatch):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    raw = item(name='검수브랜드 소스 350g', package_quantity=350, package_unit='g',
               unit='350g', display_unit='350g', original_price=None, event_name='')
    aliases = [raw, {**raw, 'name':'[쿠폰] 검수브랜드 소스 350g'}]
    review = {'source_name':'homeplus', 'source_record_key':'123', 'category_id':LEAF,
              'aliases':[{'title':r['name'], 'required_source':source_review_evidence(r),
                          'quantity_fields':listing_quantity_evidence(r)} for r in aliases]}
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_LISTING_TITLE_HISTORIES', (review,))
    result = build([ingestion(rows=[raw])])
    assert not result['unresolved'] and len(result['match_rules']) == 1
    assert 'source_title_history' not in result['variants'][0]['attributes']


def test_same_sku_keeps_each_reviewed_context_without_merging_changed_specifications(monkeypatch):
    import services.initial_catalog_seed as seed
    from core.reviewed_source_evidence import source_review_evidence
    first = item(category='베스트', detail_url='https://mfront.homeplus.co.kr/item?itemNo=123',
                 attributes={'source_record_key': '123', 'category_hint': '베스트'})
    second = {**deepcopy(first), 'category': '소스',
              'detail_url': 'https://front.homeplus.co.kr/item?itemNo=123'}
    second['attributes']['category_hint'] = '소스'
    observations = normalize_pending_ingestions([ingestion(1, [first]), ingestion(2, [second])])
    reviews = {(row['source_name'], tuple(row['source_category_path']), row['source_title']):
               source_review_evidence(row['raw_payload']) for row in observations}
    monkeypatch.setattr(seed, 'source_reviews', lambda: reviews)
    bundle = build([ingestion(1, [first]), ingestion(2, [second])])
    assert not bundle['unresolved'] and len(bundle['variants']) == 1
    actual = bundle['variants'][0]['attributes']['source_evidence_reviews']
    assert actual == [dict(source_name='homeplus', source_record_key='123', **source_review_evidence(row))
                      for row in (first, second)]
    changed = {**second, 'package_quantity': 351, 'display_unit': '351g', 'unit': '351g'}
    held = build([ingestion(1, [first]), ingestion(2, [changed])])
    assert not held['products']
    assert all('source_specification_changed' in row['reasons'] for row in held['unresolved'])


@pytest.mark.parametrize('physical_presentation', ['basket', 'feeding_bottle', 'gift_wrap', 'glass', 'shopping_bag'])
def test_source_scoped_mixed_vector_retains_total_scope_and_different_contents(monkeypatch, physical_presentation):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    raw = item(name='검수국 A 100g x 2 + 검수국 B 300g', package_quantity=100, package_unit='g',
               unit='100g', display_unit='100g', original_price=None, event_name='')
    components = [dict(identity='A',quantity=100,unit='g',count=2,amount_scope='per_counted_component',presentation=None),
                  dict(identity='B',quantity=300,unit='g',count=None,amount_scope='declared_component_total',presentation=None),
                  dict(identity='바스켓',quantity=None,unit=None,count=None,
                       amount_scope='declared_nonmeasured_physical',presentation=physical_presentation)]
    review = {'title':raw['name'],'category_id':LEAF,'required_source':source_review_evidence(raw),
              'quantity_fields':listing_quantity_evidence(raw),'components':components}
    if physical_presentation in {'glass', 'shopping_bag'}:
        review.update(measurement_role='measured_food_with_nonmeasured_physical_companion',
                      source_name='homeplus', source_record_key='123')
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_SOURCE_COMPONENT_LISTINGS',(review,))
    from services import initial_numbered_reviews
    hold = {'leaf': LEAF, 'quantity_hold_reason': 'mixed_package_component_contents_unresolved'}
    monkeypatch.setattr(initial_numbered_reviews, 'form_reviews',
                        lambda: {('homeplus', ('축산/유제품', '유제품', '우유', '초코우유'), raw['name']): hold})
    bundle = build([ingestion(rows=[raw])]); assert not bundle['unresolved']
    variant = bundle['variants'][0]
    assert (variant['package_quantity'],variant['package_unit'],variant['bundle_count']) == (1,'세트',1)
    assert variant['attributes']['source_components'] == components
    assert variant['attributes']['source_components'][1]['count'] is None
    assert variant['attributes']['source_components'][2]['count'] is None
    assert 'package_components' not in variant['attributes']
    assert all(offer['standard_unit_price'] is None for offer in bundle['offers'])
    engine = create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'vector').ok
        if physical_presentation in {'glass', 'shopping_bag'}:
            for field, value in [('source_title','다른 세트'),('source_url','https://example.test/other'),
                                 ('source_name','costco'),('source_record_key','456')]:
                changed = deepcopy(bundle); changed['source_listings'][0][field] = value
                assert not validate_bundle(session, changed, 'copied-vector').ok
        changed = deepcopy(bundle)
        changed['variants'][0]['attributes']['source_components'][0]['quantity'] += 1
        changed['variants'][0]['attributes']['source_components'][1]['quantity'] -= 2
        # Equal aggregate mass is not the same composition.
        assert not validate_bundle(session, changed, 'vector').ok
        changed = deepcopy(bundle); changed['variants'][0]['attributes']['source_components'][1]['identity'] = None
        assert not validate_bundle(session, changed, 'vector').ok
        changed = deepcopy(bundle); changed['variants'][0]['attributes']['source_components'][2]['count'] = 1
        assert not validate_bundle(session, changed, 'vector').ok
    hold['quantity_hold_reason'] = 'source_food_composition_unselected'
    held = build([ingestion(rows=[raw])])
    assert not held['offers']
    assert 'source_food_composition_unselected' in held['unresolved'][0]['reasons']
    # A confirmed allocation does not resolve contradictory measured content.
    # Retain the declared components for review, without a fixed offer.
    hold['quantity_hold_reason'] = 'distinct_tea_recipe_sold_count_allocation_not_declared'
    assert not build([ingestion(rows=[raw])])['unresolved']
    review['eligibility_hold_reason'] = 'source_recipe_measured_quantity_contradiction'
    package, issues = _package(raw, raw['attributes'], raw['name'])
    assert package['attributes']['source_components'] == components
    assert issues == ['source_recipe_measured_quantity_contradiction']
    held = build([ingestion(rows=[raw])])
    assert not held['offers']
    assert 'source_recipe_measured_quantity_contradiction' in held['unresolved'][0]['reasons']
    review.pop('eligibility_hold_reason')
    hold['quantity_hold_reason'] = 'mixed_package_component_contents_unresolved'
    wrong_source = deepcopy(raw)
    wrong_source['attributes']['detail_url'] = 'https://example.test/item/456'
    held = build([ingestion(rows=[wrong_source])])
    assert not held['offers']
    assert 'mixed_package_component_contents_unresolved' in held['unresolved'][0]['reasons']
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_SOURCE_COMPONENT_LISTINGS', ())
    held = build([ingestion(rows=[raw])])
    assert not held['offers']
    assert 'mixed_package_component_contents_unresolved' in held['unresolved'][0]['reasons']


@pytest.mark.parametrize("title,quantity", [
    ("액츠 프리미엄 젤 세탁세제 2.7L x 2 + 리필 1L x 4", 2.7),
    ("무궁화키친솝주방세제4L + 700ml", 4),
])
def test_reviewed_components_do_not_erase_incompatible_source_measurement(title, quantity):
    raw = item(name=title, package_quantity=quantity, package_unit="l", display_unit=f"{quantity}L", unit=f"{quantity}L")
    bundle = build([ingestion(1, [raw])])
    assert not bundle["offers"]
    assert "unit_reviewed_component_conflict" in bundle["unresolved"][0]["reasons"]


@pytest.mark.parametrize("title", sorted(COUNTED_CONTENT_TITLES))
def test_reviewed_purchased_count_recovers_content_boundary_without_changing_source(title):
    expected = parse_package_quantity(title)
    count = expected["bundle_count"]
    payload = {"package_quantity": count, "package_unit": "입", "display_unit": f"{count}입"}
    before = deepcopy(payload)
    package, issues = _package(payload, {}, title)
    assert issues == []
    # Parser preserves the printed unit; staging SSOT stores grams/ml.
    factor, unit = {"kg": (1000, "g"), "l": (1000, "ml")}.get(expected["package_unit"].lower(), (1, expected["package_unit"]))
    assert package["package_quantity"] == expected["package_quantity"] * factor
    assert package["package_unit"] == unit
    assert package["bundle_count"] == count
    assert package["standard_unit"] in {"g", "ml"}
    assert payload == before


@pytest.mark.parametrize("payload", [
    {"package_quantity": 29, "package_unit": "개"},
    {"package_quantity": 30, "package_unit": "개", "bundle_count": 30},
    {"package_quantity": 30, "package_unit": "개", "bundle_count": "bad"},
    {"package_quantity": 30, "package_unit": "개", "display_unit": "20개"},
    {"package_quantity": 30, "package_unit": "개", "display_unit": "30개x2"},
    {"package_quantity": 30, "package_unit": "개", "display_unit": "100g"},
])
def test_counted_content_recovery_does_not_hide_structured_or_display_conflicts(payload):
    package, issues = _package(payload, {}, "농심 신라면 120g x 30개")
    assert package is None or issues


@pytest.mark.parametrize("title,source,expected", [
    ("자미에슨 비오틴 230mg x 60정 x 2병", {}, (120, "개", 1)),
    ("컬럼비아 쿨토시 2쌍 세트", {}, (2, "쌍", 1)),
    ("네일메드코세정제리필세정용분말250포", {}, (250, "포", 1)),
    ("제스프리 골드키위 5.7kg(37~41입)", {"pack_qty": 41, "pack_unit": "입"}, (5700, "g", 1)),
    ("삼육케어 당밸런스 호두맛 200ml x 24개", {"pack_qty": 24, "pack_unit": "개"}, (200, "ml", 24)),
])
def test_parent_reviewed_quantity_boundaries_preserve_source(title, source, expected):
    original = deepcopy(source)
    package, issues = _package(source, {}, title)
    assert not issues
    assert tuple(package[key] for key in ("package_quantity", "package_unit", "bundle_count")) == expected
    assert package["display_unit"] == title
    assert source == original


@pytest.mark.parametrize("title,grams,count,display", [
    ("진라면 매운맛 (120GX5)", 120, 5, "100g 당 658원"),
    ("진라면 순한맛 (120GX5)", 120, 5, "100g 당 658원"),
    ("진비빔면 (156GX4)", 156, 4, "100g 당 718원"),
    ("짜슐랭(145GX5)", 145, 5, "100g 당 687원"),
    ("컵누들 매콤한맛 컵 (37.8GX6)", 37.8, 6, "100g 당 3,824원"),
])
def test_reviewed_ramen_exact_price_basis_display_preserves_source(title, grams, count, display):
    payload = {"unit": display, "display_unit": display}
    attrs = {"unit_price_display": display}
    original = deepcopy((payload, attrs))
    package, issues = _package(payload, attrs, title)
    assert not issues
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (grams, "g", count)
    assert package["display_unit"] == title
    assert (payload, attrs) == original
    for bad_payload, bad_attrs in [
        ({"display_unit": "50g 당 659원"}, attrs),
        (payload, {"unit_price_display": "100ml 당 659원"}),
        (payload, {"unit": "100g 당"}),
        (payload, {"pack_qty": grams + 1, "pack_unit": "g"}),
        (payload, {"bundle_count": 1}),
        (payload, {"package_quantity": grams, "package_unit": "ml"}),
    ]:
        assert _package(bad_payload, bad_attrs, title)[0] is None


@pytest.mark.parametrize("quote", ["100g 당 659원", "１００ｇ  당  ３，８２５원", "100 g\t당 659 원", "１００Ｇ 당 ６５９원"])
def test_reviewed_ramen_price_quote_changes_preserve_package(quote):
    package, issues = _package({"unit": quote, "display_unit": quote},
                               {"unit_price_display": quote}, "진라면 매운맛 (120GX5)")
    assert not issues
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (120, "g", 5)


@pytest.mark.parametrize("quote", ["100g", "100g 당 0원", "100g 당 -1원", "100g 당 6,59원", "100g 당 659.5원", "100g 당 659원 할인", "가격 659원"])
def test_reviewed_ramen_rejects_incomplete_or_non_price_quote(quote):
    assert _package({}, {"unit_price_display": quote}, "진라면 매운맛 (120GX5)")[0] is None


def test_reviewed_sheet_multichain_retains_sheet_comparability():
    title = "모나리자 미니플러스 미용티슈 250매 x 12 x 4팩"
    source = {"pack_qty": 4, "pack_unit": "팩"}
    original = deepcopy(source)
    package, issues = _package(source, {}, title)
    assert not issues
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (250, "매", 48)
    assert package["standard_unit"] is None
    assert source == original


def test_reviewed_count_mass_structural_boundary_preserves_original_bundle():
    title = "친환경 추부깻잎 20장*2입/봉 (25g*2)"
    source = {"package_quantity": 20, "package_unit": "장", "display_unit": "20장×2", "bundle_count": 2}
    original = deepcopy(source)
    package, issues = _package(source, {}, title)
    assert not issues
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (25, "g", 2)
    assert source == original
    for mutation in ({"bundle_count": 1}, {"bundle_count": 20}, {"display_unit": "20장×3"}, {"package_quantity": 21}):
        assert _package({**source, **mutation}, {}, title)[0] is None
    assert _package(source, {"bundle_count": 1}, title)[0] is None
    egg_title = "행복한 특란 30구 (15구 X 2ea, 1800g)"
    egg, issues = _package({"package_quantity": 15, "package_unit": "구", "display_unit": "15구×2"}, {}, egg_title)
    assert not issues
    assert (egg["package_quantity"], egg["bundle_count"], egg["standard_unit"]) == (15, 2, None)


def test_reviewed_homogeneous_addition_keeps_exact_source_contract():
    title = "피죤 섬유유연제 블루비앙카 기획팩 2.1L+2.1L"
    source = {"package_quantity": 2.1, "package_unit": "L", "display_unit": "2.1L"}
    original = deepcopy(source)
    package, issues = _package(source, {}, title)
    assert not issues
    assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (2100, "ml", 2)
    assert source == original
    for mutation in ({"bundle_count": 3}, {"display_unit": "2.2L"}, {"package_quantity": 2.2}):
        assert _package({**source, **mutation}, {}, title)[0] is None
    assert _package(source, {"package_quantity": 2.2, "package_unit": "L"}, title)[0] is None
    assert _package(source, {}, "피죤 섬유유연제 블루비앙카 기획팩 2.1L+1.5L")[1]


@pytest.mark.parametrize("attrs", [
    {"pack_qty": 40, "pack_unit": "입"},
    {"package_quantity": 41, "package_unit": "g"},
    {"bundle_count": 2}, {"bundle_count": "bad"},
    {"display_unit": "5.7kg(26~31입)"}, {"unit": "40입"},
])
def test_parent_reviewed_quantity_checks_hidden_attribute_contradictions(attrs):
    package, issues = _package({"pack_qty": 41, "pack_unit": "입"}, attrs,
                              "제스프리 골드키위 5.7kg(37~41입)")
    assert package is None and issues


@pytest.mark.parametrize("title", [
    "자미에슨 비오틴 240mg x 60정 x 2병",
    "제스프리 골드키위 5.7kg(26~31입)",
    "프로메가식물성rTG 츄어블오메가3 키즈 700mg x 120",
])
def test_parent_reviewed_quantity_does_not_extend_exact_identity(title):
    from core.catalog_quantity import _REVIEWED_SOURCE_PACKAGES
    assert title not in _REVIEWED_SOURCE_PACKAGES


@pytest.mark.parametrize("payload,attrs", [
    ({"pack_qty": 24, "pack_unit": "개", "bundle_count": 24}, {}),
    ({"pack_qty": 24, "pack_unit": "개"}, {"bundle_count": 24}),
    ({"package_quantity": 200, "package_unit": "ml", "bundle_count": 1}, {}),
    ({}, {}), ({"pack_qty": 24}, {}),
])
def test_parent_reviewed_content_requires_complete_original_or_corrected_tuple(payload, attrs):
    package, issues = _package(payload, attrs, "삼육케어 당밸런스 호두맛 200ml x 24개")
    assert package is None and issues


@pytest.mark.parametrize("title", [
    "농심 신라면 120g x 30개 x 2박스", "농심 신라면 120g x 30개+사은품",
    "머그컵 350ml x 30개", "새로운 불명품 120g x 30개",
])
def test_counted_content_recovery_requires_reviewed_title_not_measurement_alone(title):
    assert title not in COUNTED_CONTENT_TITLES
    package, issues = _package({"package_quantity": 30, "package_unit": "개"}, {}, title)
    assert package is None or issues


def test_counted_ramen_one_plus_one_uses_received_content_for_unit_price():
    raw = item(name="농심 신라면 120g x 30개", package_quantity=30, package_unit="개",
               display_unit="30개", unit="30개", sale_price=36000, original_price=None,
               promo_label="1+1", promotion_type="buy_x_get_y")
    bundle = build([ingestion(1, [raw])])
    assert not bundle["unresolved"]
    assert bundle["variants"][0]["package_quantity"] == 120
    assert bundle["variants"][0]["bundle_count"] == 30
    assert bundle["offers"][0]["price_per_100g"] == 500


def test_typed_coffee_chain_retains_real_paid_total_and_complete_content():
    raw = item(name="맥심 화이트 골드 커피믹스 11.7g x 210T x 2", package_quantity=11.7, package_unit="g",
               display_unit="", unit="", sale_price=49140, original_price=None)
    bundle = build([ingestion(1, [raw])])
    assert not bundle['unresolved']
    assert bundle['variants'][0]['bundle_count'] == 420
    assert bundle['offers'][0]['price'] == 49140
    assert bundle['offers'][0]['price_per_100g'] == 1000


def test_typed_chain_does_not_override_count_conflict_or_wholesale_boundary():
    conflicting = item(name="카누 라떼 커피 13.5g x 50스틱 x 2박스", package_quantity=13.5, package_unit="g", bundle_count=50, display_unit='', unit='')
    assert 'bundle_count_conflict' in build([ingestion(1,[conflicting])])['unresolved'][0]['reasons']
    wholesale = item(name="카누 미니 다크 로스트 커피 0.9g x 150스틱 x 6박스", package_quantity=.9, package_unit="g", display_unit='',unit='')
    assert 'bulk_package_review_required' in build([ingestion(1,[wholesale])])['unresolved'][0]['reasons']


def test_typed_chain_keeps_mixed_and_unknown_package_labels_unresolved():
    for title in ['커피 11.7g x 210T x 2unknown', '커피 11.7g x 210T + 12g x 10T']:
        package, issues = _package({'package_quantity':11.7,'package_unit':'g'}, {}, title)
        assert package is None or issues


def item(**changes):
    row = {
        "name": "초코우유 120ml×24", "brand": "__no_brand__", "source": "homeplus",
        "sale_price": 19900, "original_price": 24000,
        "package_quantity": 120, "package_unit": "ml", "display_unit": "120ml×24",
        "unit": "120ml×24", "crawled_at": "2026-09-02T10:00:00+09:00",
        "detail_url": "https://example.test/item/123", "category": "축산/유제품",
        "event_name": "홈플러스 할인",
        "attributes": {"source_record_key": "123", "brand": "씨제이", "mart_native_category_path": "축산/유제품 > 유제품 > 우유 > 초코우유"},
    }
    row.update(changes)
    return row


def ingestion(identifier=1, rows=None, mart="homeplus"):
    return {"id": identifier, "crawler_name": mart, "items_json": json.dumps(rows or [item()], ensure_ascii=False)}


def assignment(**changes):
    value = {"unified_category_id": LEAF, "classification_confidence": 0.95, "review_status": "classified"}
    value.update(changes)
    return value


@pytest.mark.parametrize('native', ['652658', '780235', '697186', '1000874160001', '695235', '655870', '627051', '574685', '1000631339827', '667537', '1000384981986', '696508', '1000045258266', '642459'])
def test_known_quantity_option_parent_is_retained_without_a_selected_child_or_fixed_match(monkeypatch, native):
    from core import reviewed_content_quantities as registry
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure
    from services.initial_taxonomy import taxonomy_categories
    review = deepcopy(next(r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') == native))
    mart = review['source_name']
    raw = {'name': review['title'], 'source': mart, 'source_record_key': native,
           'crawled_at': '2026-08-31T01:51:41.209255Z',
           'source_url': review['required_source']['source_urls'][0],
           'sale_price': 11990, 'price': 14990}
    for key, value in {**review['required_source']['source_fields'], **review['quantity_fields']}.items():
        layer = raw
        for part in key.split('.')[:-1]:
            layer = layer.setdefault(part, {})
        layer[key.split('.')[-1]] = f'{value[0] or ""}{value[1]}당 107원' if isinstance(value, list) else value
    batches = [ingestion(38, [raw], mart=mart)]
    row = normalize_pending_ingestions(batches)[0]
    outer = review.get('measurement_role') == 'declared_outer_set_count'
    nonexact = review.get('measurement_role') == 'declared_nonexact_mass_specification'
    entitlement = review.get('measurement_role') == 'declared_incomplete_entitlement_specification'
    partial_retail = review.get('measurement_role') == 'declared_incomplete_retail_package_specification'
    hash_scope = review['independent_specifications'] if outer or nonexact or entitlement or partial_retail else review['source_parent_selection']
    hash_scope['original_raw_payload_hashes'] = {row['raw_record_id']: row['raw_payload_sha256']}
    monkeypatch.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                        (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') != native], review))
    leaf = review['category_id']
    bundle = build_initial_catalog_bundle(batches, categories=taxonomy_categories({leaf}),
        assignments={(mart, native): assignment(unified_category_id=leaf)}, run_id='unselected-parent')
    assert not bundle['unresolved'], [row['reasons'] for row in bundle['unresolved']]
    assert bundle['build_report']['included_observations'] == 1
    product, variant, listing, offer = (bundle[key][0] for key in
                                      ('products', 'variants', 'source_listings', 'offers'))
    quantity, unit, count = review['normalized']
    assert [variant['package_quantity'], variant['package_unit'], variant['bundle_count']] == [quantity, unit, count]
    assert variant['standard_unit'] == (unit if unit in {'g', 'ml'} else None)
    assert not product['is_active'] and not variant['is_active'] and not listing['is_active']
    assert product['attributes']['identity_basis'] == ('source_partial_retail_observation' if partial_retail else 'source_incomplete_entitlement_observation' if entitlement else 'source_nonexact_contents_observation' if nonexact else 'source_incomplete_set_observation' if outer else 'source_selectable_parent_observation')
    assert offer['price'] == 11990 and offer['offer_state'] == 'pending_review'
    assert offer['standard_unit_price'] is None and offer['price_per_100g'] is None
    assert not bundle['match_rules'] and package_pricing_measure(variant) is None
    for price in (12990, None):
        package, issues = normalize_catalog_package({**raw, 'sale_price': price}, {}, raw['name'])
        assert not issues and [package['package_quantity'], package['package_unit'], package['bundle_count']] == [quantity, unit, count]
    if native == '642459':
        from core.reviewed_source_evidence import valid_explicit_listing_variant
        assert quantity == 4 and unit == '개' and count == 1
        assert review['declared_sold_entity_count']['counted_entity'] == 'whole_pizza'
        # A registered review still needs coherent whole-entity count evidence.
        for field, value in [('normalized', [16, '개', 1]),
                             ('declared_sold_entity_count', {'value': 4}),
                             ('source_parent_selection', None),
                             ('title', review['title'] + ' 2팩'),
                             ('title', review['title'] + ' 700g'),
                             ('title', review['title'].replace('피자', '피자팬'))]:
            broken = deepcopy(review)
            broken[field] = value
            bad_variant = deepcopy(variant)
            bad_variant['attributes']['explicit_listing_quantity_review'] = broken
            monkeypatch.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                                (*registry.REVIEWED_EXPLICIT_LISTING_PACKAGES, broken))
            assert not valid_explicit_listing_variant(bad_variant)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'parent-observation').ok
        if native == '1000874160001':
            from core.reviewed_source_evidence import source_selection_alternatives
            assert source_selection_alternatives(variant) == (('델리황', 10, '봉'), ('황홀태', 5, '봉'))
            assert quantity is None and unit is None
        if nonexact:
            from core.reviewed_source_evidence import source_nonexact_contents_specification
            spec = source_nonexact_contents_specification(variant)
            assert spec == review['nonexact_contents_specification']
            assert quantity is unit is None and count == 1
            assert spec['operator'] == ('<' if native in {'574685', '1000045258266'} else 'approximately')
            for changes in ({'bundle_count': 2}, {'package_quantity': 1, 'package_unit': '개'},
                            {'unit_price_basis_raw': '100ml'}, {'source_url': raw['source_url']+'-other'}):
                assert normalize_catalog_package({**raw, **changes}, {}, raw['name'])[0] is None
            for extra in (' 2팩', ' / 2봉'):
                assert normalize_catalog_package(raw, {}, raw['name']+extra)[0] is None
            assert normalize_catalog_package({'name':raw['name']}, {}, raw['name'])[0] is None
        if partial_retail:
            from core.reviewed_source_evidence import source_partial_retail_specification
            spec = source_partial_retail_specification(variant)
            assert spec['net_contents'] == {'value': 700, 'unit': 'g'}
            assert spec['declared_count'] == {'value': 50, 'literal_unit': '개입', 'counted_entity': None}
            assert spec['unresolved_source_factors'] == [{'literal': '14', 'unit': None, 'role': None}]
            assert spec['whole_sold_contents'] is None and spec['sold_retail_package_count'] is None
            assert quantity is unit is None and count == 1
            for field, value in (('sold_retail_package_count', 14), ('whole_sold_contents', {'value': 700, 'unit': 'g'}),
                                 ('net_contents', {'value': 9800, 'unit': 'g'}),
                                 ('unresolved_source_factors', []), ('per_count_mass', 14)):
                broken = deepcopy(review)
                broken['partial_retail_specification'][field] = value
                with monkeypatch.context() as scoped:
                    scoped.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                        (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') != native], broken))
                    rejected, issues = normalize_catalog_package(raw, {}, raw['name'])
                    assert rejected is None and 'bundle_multiplier_unresolved' in issues
            for changes in ({'bundle_count': 14}, {'package_quantity': 9800, 'package_unit': 'g'},
                            {'unit_price_basis_raw': '1개'}, {'source_url': raw['source_url']+'-other'}):
                assert normalize_catalog_package({**raw, **changes}, {}, raw['name'])[0] is None
            assert normalize_catalog_package({'name': raw['name']}, {}, raw['name'])[0] is None
        if entitlement:
            from core.reviewed_source_evidence import source_entitlement_specification
            assert source_entitlement_specification(variant) == review['entitlement_specification']
            assert quantity is unit is None and count == 1
            if native == '667537':
                assert offer['promotion_conditions']['minimum_quantity'] == 2
                assert review['entitlement_specification']['denomination_amount'] == 50000
            for changes in ({'bundle_count': 2}, {'package_quantity': 2, 'package_unit': '개'},
                            {'unit_price_basis_raw': '1인'}, {'source_url': raw['source_url']+'-other'}):
                assert normalize_catalog_package({**raw, **changes}, {}, raw['name'])[0] is None
            assert normalize_catalog_package({'name': raw['name']}, {}, raw['name'])[0] is None
            for field, value in (('sold_certificate_count', 2), ('granted_person_count', 2),
                                 ('maximum_capacity', 2), ('duration', 1)):
                broken = deepcopy(review)
                broken['entitlement_specification'][field] = value
                with monkeypatch.context() as scoped:
                    scoped.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                        (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') != native], broken))
                    assert normalize_catalog_package(raw, {}, raw['name'])[0] is None
        if outer:
            assert quantity == (5 if native == '695235' else 10) and unit == '세트' and count == 1
        for mutation in ('active_price', 'child_alias', 'fixed_rule', 'quantity_proof', 'raw_hash', 'removed_proof', 'fake_scalar'):
            changed = deepcopy(bundle)
            if mutation == 'active_price':
                changed['offers'][0]['offer_state'] = 'active'
            elif mutation == 'child_alias':
                changed['source_listings'][0]['source_record_key'] = native+'-other-child'
            elif mutation == 'fixed_rule':
                changed['match_rules'] = [{'match_key': 'parent-key', 'public_product_id': product['public_product_id'],
                    'public_variant_id': variant['public_variant_id'], 'confidence': .95}]
            elif mutation == 'raw_hash':
                if native not in {'1000874160001', '695235', '655870', '627051', '574685', '1000631339827', '667537', '1000384981986', '696508', '1000045258266'}:
                    continue
                changed['offers'][0]['raw_evidence']['observations'][0]['raw_payload']['sale_price'] = 17990
            elif mutation in {'removed_proof', 'fake_scalar'}:
                if native not in {'1000874160001', '695235', '655870', '627051', '574685', '1000631339827', '667537', '1000384981986', '696508', '1000045258266'}:
                    continue
                if mutation == 'removed_proof':
                    changed['variants'][0]['attributes'] = {}
                else:
                    changed['variants'][0]['package_quantity'] = 1
            else:
                proof = changed['variants'][0]['attributes']['explicit_listing_quantity_review']
                if partial_retail:
                    proof['partial_retail_specification']['sold_retail_package_count'] = 1
                elif entitlement:
                    proof['entitlement_specification']['sold_entitlement_count'] = 1
                elif nonexact:
                    proof['nonexact_contents_specification']['value'] += 1
                elif outer:
                    proof['declared_outer_set_count'] += 1
                elif quantity is None:
                    proof['source_exclusive_alternatives'][0]['container_count'] = 10
                else:
                    proof['source_parent_selection']['selected_value'] = '프레시가든'
            assert not validate_bundle(session, changed, 'unproved-selection').ok
        if native in {'1000874160001', '695235', '655870', '627051', '574685', '1000631339827', '667537', '1000384981986', '696508', '1000045258266'}:
            broken = deepcopy(review)
            if outer or nonexact or entitlement or partial_retail:
                del broken['independent_specifications']
            else:
                del broken['source_parent_selection']
            with monkeypatch.context() as scoped:
                scoped.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                    (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                       if r.get('source_record_key') != native], broken))
                rejected, issues = normalize_catalog_package(raw, {}, raw['name'])
                assert rejected is None and issues
        if nonexact:
            for mutation in ('operator', 'nominal', 'tolerance', 'added_bundle', 'exact_count'):
                broken = deepcopy(review)
                candidate = deepcopy(raw)
                spec = broken['nonexact_contents_specification']
                if mutation == 'operator':
                    spec['operator'] = '<='
                elif mutation == 'nominal':
                    spec['value'] += 1
                elif mutation == 'tolerance':
                    spec['tolerance'] = 0
                else:
                    broken['title'] += ' 2팩' if mutation == 'added_bundle' else ' 6입'
                    candidate['name'] = broken['title']
                with monkeypatch.context() as scoped:
                    scoped.setattr(registry, 'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                        (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') != native], broken))
                    rejected, issues = normalize_catalog_package(candidate, {}, candidate['name'])
                    assert rejected is None and 'approximate_measured_quantity_unresolved' in issues
        from services.catalog_bundle import apply_bundle
        from storage.models import NormalizedProductVariant, NormalizedOfferEvent
        apply_bundle(session, bundle, 'parent-observation', user='focused-observation-review')
        saved_variant = session.get(NormalizedProductVariant, variant['public_variant_id'])
        saved_offer = session.get(NormalizedOfferEvent, offer['public_offer_event_id'])
        assert [saved_variant.package_quantity, saved_variant.package_unit, saved_variant.bundle_count] == [quantity, unit, count]
        assert saved_offer.standard_unit_price is None and saved_offer.price_per_100g is None
    engine.dispose()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'wrong_url', 'other_observation_url'])
def test_reviewed_display_name_requires_every_original_source_context(monkeypatch, mutation):
    import services.initial_catalog_seed as seed
    from services import initial_numbered_reviews
    from core.reviewed_source_evidence import source_review_evidence
    raw = item(name='120ml×24')
    key = ('homeplus', ('축산/유제품', '유제품', '우유', '초코우유'), raw['name'])
    required = source_review_evidence(raw)
    monkeypatch.setattr(initial_numbered_reviews, 'form_reviews',
                        lambda: {key: {'leaf': LEAF, 'canonical_name': '검수된 초코우유'}})
    monkeypatch.setattr(seed, 'source_reviews', lambda: {key: required})
    changed = deepcopy(raw)
    if mutation == 'price_only':
        changed['sale_price'] = 21000
    if mutation in {'wrong_url', 'other_observation_url'}:
        changed['detail_url'] = 'https://example.test/item/other'
    ingestions = ([ingestion(1, [changed]), ingestion(2, [raw])]
                  if mutation == 'other_observation_url' else [ingestion(rows=[changed])])
    result = build(ingestions)
    if mutation in {'wrong_url', 'other_observation_url'}:
        assert not result['products'] and not result['offers']
        assert all('reviewed_product_name_source_conflict' in row['reasons'] for row in result['unresolved'])
    else:
        assert result['products'][0]['canonical_name'] == '검수된 초코우유'
        assert result['variants'][0]['variant_name'] == '검수된 초코우유 120ml×24'
        assert result['source_listings'][0]['source_title'] == raw['name']
        assert result['offers'][0]['price'] == changed['sale_price']


def build(ingestions=None, assignments=None):
    return build_initial_catalog_bundle(
        ingestions or [ingestion()], categories=CATEGORIES,
        assignments=assignments if assignments is not None else {("homeplus", "123"): assignment()},
        run_id="test-initial-catalog",
    )


@pytest.mark.parametrize('gap', ['title', 'quantity'])
@pytest.mark.parametrize('all_held', [False, True])
def test_registered_factual_hold_preserves_independent_observation_and_accounting(monkeypatch, gap, all_held):
    import services.initial_catalog_seed as seed
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    exact = item(name='검수 딸기우유 350ml', package_quantity=350, package_unit='ml',
                 display_unit='350ml', unit='350ml', original_price=None, event_name='',
                 detail_url='https://mfront.homeplus.co.kr/item?itemNo=123')
    uncertain = deepcopy(exact)
    if gap == 'title':
        uncertain['name'] = '검수 우유 350ml'
    else:
        uncertain.update(package_quantity=1, package_unit='개', display_unit='1개', unit='1개')
    records = tuple({'title': row['name'], 'category_id': LEAF,
                     'required_source': source_review_evidence(row),
                     'quantity_fields': listing_quantity_evidence(row),
                     'status': status, 'hold_reason': 'necessary_fact_missing' if status == 'hold' else None}
                    for row, status in ((exact, 'eligible'), (uncertain, 'hold')))
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY', records)
    monkeypatch.setattr(seed, 'source_reviews', lambda: {})
    inputs = [ingestion(2, [uncertain])] if all_held else [ingestion(1, [exact]), ingestion(2, [uncertain])]
    original = deepcopy(inputs)
    bundle = build(inputs)
    assert inputs == original
    assert len(bundle['observation_accounting']) == len(inputs)
    assert len(bundle['unresolved']) == 1
    assert 'necessary_fact_missing' in bundle['unresolved'][0]['reasons']
    assert bundle['unresolved'][0]['raw_payload'] == uncertain
    assert len(bundle['products']) == (0 if all_held else 1)
    if not all_held:
        variant = bundle['variants'][0]
        assert (variant['package_quantity'], variant['package_unit']) == (350, 'ml')
        assert variant['attributes']['source_evidence_reviews'] == [
            {'source_name': 'homeplus', 'source_record_key': '123', **source_review_evidence(exact)}]
        assert bundle['source_listings'][0]['source_title'] == exact['name']
        assert len(bundle['offers']) == 1
        # A changed quantity that was never reviewed stays a whole-SKU conflict.
        # Only the registered factual gap may be partitioned independently.
        changed = deepcopy(exact)
        changed.update(package_quantity=400, display_unit='400ml', unit='400ml')
        unreviewed = build([ingestion(1, [exact]), ingestion(3, [changed])])
        assert not unreviewed['products']
        assert len(unreviewed['observation_accounting']) == 2
        assert all('source_specification_changed' in row['reasons'] for row in unreviewed['unresolved'])


@pytest.mark.parametrize('native', ['069582950', '068777382'])
def test_reviewed_source_identity_contexts_preserve_anchor_and_reject_cross_context(native):
    from core.reviewed_content_quantities import REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
    from core.catalog_matching import _match_key_for_row, _normalized_source_reason
    from services.initial_taxonomy import taxonomy_categories
    records = [r for r in REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
               if (r.get('identity_context') or {}).get('source_record_key') == native]
    rows = []
    for record in records:
        raw = item(name=record['title'], detail_url=record['required_source']['source_urls'][0],
                   attributes={'source_record_key': native}, original_price=None,
                   brand='__no_brand__')
        for fields in (record['required_source']['source_fields'], record['quantity_fields']):
            for field, value in fields.items():
                layer = raw['attributes'] if field.startswith('attributes.') else raw
                layer[field.rsplit('.', 1)[-1]] = str(value[0])+value[1] if isinstance(value, list) else value
        rows.append(raw)
    decision = assignment(unified_category_id=records[0]['category_id'])
    inputs = [ingestion(i+1, [row]) for i, row in enumerate(rows)]
    original = deepcopy(inputs)
    result = build_initial_catalog_bundle(inputs, categories=taxonomy_categories({records[0]['category_id']}),
        assignments={('homeplus', native): decision}, run_id='source-context')
    assert inputs == original and not result['unresolved']
    assert len(result['products']) == len(result['variants']) == len(result['source_listings']) == 2
    anchor = next(r for r in records if not r['identity_context']['partition_key'])
    anchor_listing = next(r for r in result['source_listings'] if r['source_title'] == anchor['title'])
    assert anchor_listing['public_source_listing_id'] == stable_id('listing', 'homeplus', native)
    variants = {v['public_variant_id']: v for v in result['variants']}
    matching_variants = {key: {**deepcopy(variant), 'source_listings': [listing for listing in result['source_listings']
                         if listing['public_variant_id'] == key]} for key, variant in variants.items()}
    anchor_variant = variants[anchor_listing['public_variant_id']]
    assert anchor_variant['public_product_id'] == stable_id('prod', 'source', 'homeplus', native)
    assert 'source_identity_context' not in anchor_variant['attributes']
    anchor_raw = next(row for row in rows if row['name'] == anchor['title'])
    anchor_only = build_initial_catalog_bundle([ingestion(rows=[anchor_raw])],
        categories=taxonomy_categories({anchor['category_id']}),
        assignments={('homeplus', native): decision}, run_id='anchor-unchanged')
    assert anchor_variant == anchor_only['variants'][0]
    for row in rows:
        listing = next(r for r in result['source_listings'] if r['source_title'] == row['name'])
        variant = variants[listing['public_variant_id']]
        rule = next(r for r in result['match_rules'] if r['public_variant_id'] == variant['public_variant_id'])
        key, reason = _match_key_for_row(row)
        assert not reason and key == rule['match_key']
        assert _normalized_source_reason(row, key, rule, matching_variants) is None
        assert _normalized_source_reason({**deepcopy(row), 'sale_price': 22000}, key, rule, matching_variants) is None
        other = next(r for r in rows if r['name'] != row['name'])
        for changed in ({'name': other['name']}, {'source_record_key': 'other'},
                        {'detail_url': 'https://example.test/other'}, {'package_quantity': 9},
                        {'category': '다른 분류'}):
            assert _normalized_source_reason({**deepcopy(row), **changed}, key, rule, matching_variants) is not None
        assert _normalized_source_reason({'name': row['name']}, key, rule, matching_variants) is not None
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, result, 'source-context').ok
        invalid = deepcopy(result)
        split = next(v for v in invalid['variants'] if 'source_identity_context' in v['attributes'])
        split['attributes'].pop('source_identity_context')
        assert not validate_bundle(session, invalid, 'unreviewed-duplicate').ok
    engine.dispose()


@pytest.mark.parametrize('native,expected_amounts,quote', [
    ('684160', [1500, 1000, 1000], 53900),
    ('695905', [1200, 1200], 21990),
])
def test_declared_meat_component_totals_do_not_invent_counts_or_homogeneous_unit_prices(native, expected_amounts, quote):
    from core.reviewed_content_quantities import REVIEWED_SOURCE_COMPONENT_LISTINGS
    from core.catalog_matching import _match_key_for_row, _normalized_source_reason
    from services.initial_taxonomy import classify_record, taxonomy_categories
    review = next(r for r in REVIEWED_SOURCE_COMPONENT_LISTINGS
                  if (r.get('source_record_key') == native if native != '684160'
                      else r['category_id'] == 'food.meat.sets.mixed_components'))
    raw = item(name=review['title'], original_price=None,
               source='costco',
               detail_url=review['required_source']['source_urls'][0],
               attributes={'source_record_key': native}, sale_price=quote)
    # Reconstruct the actual declared source fields, including its component
    # 1kg display basis, without turning that basis into the whole sold set.
    for field in ('package_quantity', 'package_unit', 'display_unit', 'unit'):
        raw.pop(field, None)
    for fields in (review['required_source']['source_fields'], review['quantity_fields']):
        for field, value in fields.items():
            layer = raw['attributes'] if field.startswith('attributes.') else raw
            layer[field.rsplit('.', 1)[-1]] = str(value[0])+value[1] if isinstance(value, list) else value
    raw['source_record_key'] = native
    assert classify_record(raw)['unified_category_id'] == review['category_id']
    result = build_initial_catalog_bundle([ingestion(rows=[raw], mart='costco')],
        categories=taxonomy_categories({review['category_id']}),
        assignments={('costco', native): assignment(unified_category_id=review['category_id'])},
        run_id='meat-components')
    assert not result['unresolved'] and len(result['offers']) == 1
    variant = result['variants'][0]
    components = variant['attributes']['source_components']
    assert [c['quantity'] for c in components] == expected_amounts
    assert all(c['count'] is None and c['amount_scope'] == 'declared_component_total' for c in components)
    offer = result['offers'][0]
    assert offer['price'] == quote and offer['standard_unit_price'] is None and offer['price_per_100g'] is None
    variants = {variant['public_variant_id']: {**variant, 'source_listings': result['source_listings']}}
    rule = result['match_rules'][0]
    key, reason = _match_key_for_row(raw)
    assert not reason and _normalized_source_reason(raw, key, rule, variants) is None
    assert _normalized_source_reason({**deepcopy(raw), 'sale_price': 55000,
        'unit_price_display': '100g당 1600원'}, key, rule, variants) is None
    for mutation in ({'name': '다른 고기 3.5kg'}, {'pack_qty': 3.5},
                     {'source_record_key': 'other'}, {'detail_url': 'https://example.test/other'},
                     {'category': '다른 문맥'}, {'source_components': []}):
        assert _normalized_source_reason({**deepcopy(raw), **mutation}, key, rule, variants) is not None
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, result, 'declared-meat').ok
    engine.dispose()


@pytest.mark.parametrize('generic_role', [False, True, 'model', 'declared_bundle', 'vessel', 'vessel_count'])
def test_nonmeasured_device_retains_capacity_null_count_and_listing_price(monkeypatch, generic_role):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import listing_quantity_evidence, source_review_evidence
    from services.initial_taxonomy import taxonomy_categories
    leaf = 'appliances.kitchen.soy_maker.standard'
    raw = item(name='검수된 두유제조기 800ml MX-22', package_quantity=800, package_unit='ml',
               display_unit='800ml', unit='800ml', detail_url='https://mfront.homeplus.co.kr/item?itemNo=123',
               category='가전', event_name='', original_price=None,
               attributes={'source_record_key':'123', 'mart_native_category_path':'가전'})
    if generic_role == 'model':
        leaf = 'appliances.laundry.set.washer_dryer'
        raw.update(name='세탁기 + 건조기 세트명[WF25DG8250BW2T]', package_quantity=2,
                   package_unit='T', display_unit='2T', unit='2T')
    if generic_role in {'vessel', 'vessel_count'}:
        leaf = 'household.kitchen.coffee.server'
        raw['name'] = '검수 보온서버 800ml' + (' 2PK' if generic_role == 'vessel_count' else '')
    review = {'title':raw['name'], 'category_id':leaf, 'required_source':source_review_evidence(raw),
              'quantity_fields':listing_quantity_evidence(raw)}
    if generic_role == 'declared_bundle':
        raw['name'] = '1+1 검수된 두유제조기 800ml MX-22'
        raw['attributes']['promo_label'] = '1+1'
        review.update(title=raw['name'], declared_package_bundle_count=2, required_promotion_label='1+1')
    generic_device = generic_role in (True, 'model', 'vessel', 'vessel_count')
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_NONMEASURED_LISTINGS', () if generic_device else (review,))
    bundle = build_initial_catalog_bundle([ingestion(rows=[raw])], categories=taxonomy_categories([leaf]),
              assignments={('homeplus','123'):assignment(unified_category_id=leaf)}, run_id='nonmeasured-focused')
    assert not bundle['unresolved']
    variant = bundle['variants'][0]
    expected_count = 2 if generic_role == 'vessel_count' else None
    assert variant['package_quantity'] == expected_count
    assert variant['package_unit'] == ('개' if expected_count else None)
    proof = variant['attributes']['physical_device_specification'] if generic_device else variant['attributes']['nonmeasured_listing']
    assert (proof['sold_piece_count'] if generic_device else variant['attributes']['sold_piece_count']) == expected_count
    assert variant['bundle_count'] == (2 if generic_role == 'declared_bundle' else 1)
    assert proof['quantity_fields']['package_quantity'] == raw['package_quantity']
    assert all(offer['standard_unit_price'] is None and offer['price_per_100g'] is None for offer in bundle['offers'])
    assert bundle['offers'][0]['price'] == raw['sale_price']
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'focused').ok
        bad = deepcopy(bundle)
        bad['variants'][0]['package_quantity'] = 1
        bad['variants'][0]['package_unit'] = '개'
        # A forged exact singleton cannot borrow NULL-count listing evidence.
        assert not validate_bundle(session, bad, 'focused').ok
        if generic_role == 'declared_bundle':
            bad = deepcopy(bundle)
            bad['variants'][0]['bundle_count'] = 1
            assert not validate_bundle(session, bad, 'focused').ok
    for changes in ({'package_quantity':801}, {'packQty':1,'packUnit':'개'}, {'bundle_count':2},
                    {'unit_price_text':'100ml당500원'}, {'detail_url':raw['detail_url']+'4'}):
        package, issues = _package({**raw, **changes}, raw['attributes'], raw['name'], category_id=leaf if generic_device else None)
        assert (package is None and issues) or generic_device and package['attributes']['physical_device_specification'] != proof


@pytest.mark.parametrize('repeated_terminal', [False, True])
def test_confirmed_leaf_does_not_turn_unknown_gift_components_into_scalar_offer(monkeypatch, repeated_terminal):
    from services import initial_numbered_reviews
    raw = item(name='곡물 선물세트 1.54kg', package_quantity=1540, package_unit='g',
               display_unit='1.54kg', unit='1.54kg', category='곡물선물',
               attributes={'source_record_key':'123','mart_native_category_path':
                           '곡물선물 > 곡물선물' if repeated_terminal else '곡물선물'})
    monkeypatch.setattr(initial_numbered_reviews, 'form_reviews', lambda: {
        ('homeplus', ('곡물선물',), raw['name']):{'quantity_hold_reason':'mixed_package_component_contents_unresolved'}})
    bundle = build([ingestion(rows=[raw])])
    assert not bundle['products'] and not bundle['offers']
    assert 'mixed_package_component_contents_unresolved' in bundle['unresolved'][0]['reasons']


def _component_bundle():
    title = "[기획세트] 퍼실 세탁세제 2.5L+1.5L(파워젤)"
    raw = item(name=title, package_quantity=1.5, package_unit="l", display_unit="1.5L", unit="1.5L",
               sale_price=20000, original_price=None,
               attributes={"source_record_key": "123", "unit_price_display": "100ml 당 500원"})
    refreshed = {**deepcopy(raw), "sale_price": 22000, "crawled_at": "2026-09-09T10:00:00+09:00",
                 "attributes": {**raw["attributes"], "unit_price_display": "100ml 당 550원"}}
    categories = [{"id": "home", "parent_id": None, "name_ko": "생활"},
                  {"id": "home.clean", "parent_id": "home", "name_ko": "세정"},
                  {"id": "home.clean.laundry", "parent_id": "home.clean", "name_ko": "세탁세제"},
                  {"id": "home.clean.laundry.liquid", "parent_id": "home.clean.laundry", "name_ko": "액체세탁세제"}]
    sources = [ingestion(1, [raw]), ingestion(2, [refreshed])]
    original = deepcopy(sources)
    bundle = build_initial_catalog_bundle(sources, categories=categories,
        assignments={("homeplus", "123"): assignment(unified_category_id="home.clean.laundry.liquid")},
        run_id="component-test")
    assert sources == original
    return bundle


def test_component_bundle_identity_and_offer_price_are_separate():
    from core.catalog_quantity import component_signature, package_pricing_measure
    bundle = _component_bundle()
    assert not bundle["unresolved"]
    variant = bundle["variants"][0]
    assert (variant["package_quantity"], variant["package_unit"], variant["bundle_count"]) == (1, "세트", 1)
    assert package_pricing_measure(variant) == (4000, "ml")
    signature = component_signature(variant)
    assert [c[:3] for c in signature] == [(1500, "ml", 1), (2500, "ml", 1)]
    assert variant["public_variant_id"] == stable_id("var", variant["public_product_id"], "component-set-v1", signature)
    assert len(bundle["products"]) == len(bundle["variants"]) == len(bundle["source_listings"]) == 1
    assert {o["standard_unit_price"] for o in bundle["offers"]} == {500, 550}
    assert all(o["price_per_100g"] is None for o in bundle["offers"])
    assert len(bundle["offers"]) == 2
    scalar = build()["variants"][0]
    assert scalar["public_variant_id"] == stable_id("var", scalar["public_product_id"], 120.0, "ml", 24)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, "component-test").ok
        other = deepcopy(variant)
        other["attributes"]["package_components"] = [{"quantity": 2000.0, "unit": "ml", "count": 2,
            "identity": signature[0][3], "presentation": ""}]
        other["public_variant_id"] = stable_id("var", other["public_product_id"], "component-set-v1", component_signature(other))
        assert other["public_variant_id"] != variant["public_variant_id"]
        assert package_pricing_measure(other) == package_pricing_measure(variant)
        distinct = deepcopy(bundle)
        distinct["variants"].append(other)
        assert validate_bundle(session, distinct, "distinct").ok
        duplicate = deepcopy(bundle)
        duplicate["variants"].append({**deepcopy(variant), "public_variant_id": "duplicate-component"})
        assert not validate_bundle(session, duplicate, "duplicate").ok
    engine.dispose()


@pytest.mark.parametrize("change", ["shape", "dimension", "mixed_contents", "basis", "count"])
def test_component_bundle_rejects_incomplete_or_mixed_contract(change):
    bundle = _component_bundle()
    variant = bundle["variants"][0]
    if change == "shape":
        variant["package_quantity"] = 4000
    elif change == "dimension":
        variant["standard_unit"] = "g"
    elif change == "basis":
        variant["attributes"].pop("component_basis")
    elif change == "count":
        variant["attributes"]["package_components"][0]["count"] = 0
    else:
        variant["attributes"]["package_components"][0]["identity"] = "다른 제형"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert not validate_bundle(session, bundle, "invalid-component").ok
    engine.dispose()


def test_component_import_read_model_and_snapshot_preserve_multiset(tmp_path):
    from services.catalog_bundle import apply_bundle
    from services.normalized_price_read import get_normalized_price_comparison
    from services.public_snapshot_v2 import _write_snapshot_file
    bundle = _component_bundle()
    attrs = bundle["variants"][0]["attributes"]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        apply_bundle(session, bundle, "component-import", user="test")
        session.commit()
        read = get_normalized_price_comparison(session)
        assert read["products"][0]["variants"][0]["attributes"] == attrs
    target = tmp_path / "component-snapshot.sqlite"
    with engine.connect() as source:
        _write_snapshot_file(target, source, 1)
    snapshot = create_engine(f"sqlite:///{target.as_posix()}")
    with Session(snapshot) as session:
        copied = get_normalized_price_comparison(session)
        assert copied["products"][0]["variants"][0]["attributes"] == attrs
        assert {o["standard_unit_price"] for o in copied["products"][0]["variants"][0]["source_listings"][0]["offer_events"]} == {500, 550}
    snapshot.dispose()
    engine.dispose()


def test_reviewed_ramen_price_refresh_keeps_identity_and_distinct_offers():
    first = item(name="진라면 매운맛 (120GX5)", package_quantity=None, package_unit="",
                 unit="100g 당 658원", display_unit="100g 당 658원", sale_price=3950,
                 original_price=None, attributes={"source_record_key": "123", "unit_price_display": "100g 당 658원"})
    first.update(match_key="__no_brand__|진라면 매운맛 120gx5||100g 당 658원", matching_status="miss")
    refreshed = {**first, "unit": "100g 당 659원", "display_unit": "100g 당 659원",
                 "sale_price": 3960, "crawled_at": "2026-09-09T10:00:00+09:00",
                 "attributes": {**first["attributes"], "unit_price_display": "100g 당 659원"}}
    batches = [ingestion(1, [first]), ingestion(2, [refreshed])]
    original = deepcopy(batches)
    bundle = build(batches)
    assert bundle["unresolved"] == []
    assert len(bundle["products"]) == len(bundle["variants"]) == len(bundle["source_listings"]) == 1
    assert len(bundle["offers"]) == 2
    assert {offer["price"] for offer in bundle["offers"]} == {3950, 3960}
    from services.initial_catalog_seed import _runtime_match_key
    expected_key = build_match_key("__no_brand__", first["name"], 120, "g")
    assert {rule["match_key"] for rule in bundle["match_rules"]} == {expected_key}
    assert _runtime_match_key({"raw_payload": first}) == _runtime_match_key({"raw_payload": refreshed}) == expected_key
    assert {offer["raw_evidence"]["observations"][0]["raw_payload"]["unit"] for offer in bundle["offers"]} == {"100g 당 658원", "100g 당 659원"}
    assert batches == original


def test_reviewed_linear_content_keeps_width_and_mutable_price_out_of_quantity():
    title = "종이호일30cm*40m"
    for quote in ["1m 당 110원", "1m 당 120원"]:
        package, issues = _package({"unit": quote, "display_unit": quote},
                                   {"unit_price_display": quote}, title)
        assert issues == []
        assert (package["package_quantity"], package["package_unit"], package["bundle_count"]) == (40, "m", 1)
        assert package["standard_unit"] is None
        assert package["display_unit"] == title
    for bad in [{"package_quantity": 30, "package_unit": "m"}, {"bundle_count": 2},
                {"display_unit": "1g 당 110원"}, {"display_unit": "30CM"}]:
        assert _package(bad, {}, title)[0] is None
    assert _package({}, {}, "미검토 종이호일30cm*40m")[0] is None


def test_reviewed_length_offer_keeps_linear_unit_without_mass_price():
    raw = item(name="종이호일30cm*40m", package_quantity=None, package_unit="",
               unit="1m 당 110원", display_unit="1m 당 110원", sale_price=4380,
               original_price=None, attributes={"source_record_key": "123", "unit_price_display": "1m 당 110원"})
    bundle = build([ingestion(1, [raw])])
    assert bundle["unresolved"] == []
    assert bundle["variants"][0]["package_unit"] == "m"
    assert bundle["offers"][0]["standard_unit_price"] is None
    assert bundle["offers"][0]["price_per_100g"] is None
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, "length-contract").ok
        changed = deepcopy(bundle)
        changed["variants"][0]["package_unit"] = "unknown-length"
        assert not validate_bundle(session, changed, "length-contract").ok
        changed["variants"][0]["package_unit"] = "m"
        changed["variants"][0]["package_quantity"] = -40
        assert not validate_bundle(session, changed, "length-contract").ok


def test_nested_brand_and_full_source_path_win_over_enrichment_placeholders():
    normalized = normalize_pending_ingestions([ingestion()])[0]
    assert normalized["brand"] == "CJ"
    assert normalized["source_category_path"] == ["축산/유제품", "유제품", "우유", "초코우유"]
    assert normalized["source_record_key"] == "123"
    assert normalized["package"]["bundle_count"] == 24
    assert normalized["crawled_at"] == "2026-09-02T01:00:00Z"
    assert normalized["raw_payload"]["brand"] == "__no_brand__"
    assert normalized["issues"] == []


@pytest.mark.parametrize("value", ["__no_brand__", "브랜드없음", "단독기획", "국내산", "미국산", ""])
def test_generic_brand_is_not_a_product_brand(value):
    assert validated_brand(value) is None


def test_emart_collection_is_not_inferred_to_be_a_brand_and_no_brand_is_real_brand():
    row = item(attributes={"source_record_key": "123", "collection": "백설", "category_path": ["식품", "소스"]})
    assert normalize_pending_ingestions([ingestion(rows=[row], mart="emart")])[0]["brand"] is None
    assert validated_brand("노브랜드") == "노브랜드"
    assert validated_brand("12Brix") is None
    assert validated_brand("국내산(제주)") is None


def test_display_unit_restores_explicit_multiplier_when_title_has_no_quantity():
    bundle = build([ingestion(1, [item(name="초코우유", sale_price=24000, original_price=None)])])
    assert bundle["variants"][0]["bundle_count"] == 24
    assert bundle["offers"][0]["standard_unit_price"] == pytest.approx(833.3333)


def test_display_and_title_multiplier_conflict_is_held():
    bundle = build([ingestion(1, [item(display_unit="120ml×12")])])
    assert "bundle_count_conflict" in bundle["unresolved"][0]["reasons"]


@pytest.mark.parametrize(("title", "quantity", "unit", "reason"), [
    ("찹쌀 김부각 세트(5개입) x 5", 5, "ea", None),
    ("네일메드코세정제콤보(용기3개+세정용분말250포)", 3, "ea", "mixed_package_unresolved"),
    ("커클랜드 시그니춰 종이타월 160매 x 12롤 x 2팩", 160, "매", "bundle_multiplier_unresolved"),
])
def test_unparsed_multipliers_and_mixed_count_packages_are_not_staged(title, quantity, unit, reason):
    raw = item(name=title, package_quantity=None, package_unit=None, pack_qty=quantity, pack_unit=unit, display_unit="", unit="")
    bundle = build([ingestion(1, [raw])])
    if reason is None:
        # The exact reviewed count chain now stages; unreviewed/mixed shapes
        # below and the following generic multiplication contract stay held.
        assert not bundle['unresolved']
        variant = bundle['variants'][0]
        assert (variant['package_quantity'], variant['package_unit'], variant['bundle_count']) == (5, '개', 5)
        assert len(bundle['offers']) == len(bundle['match_rules']) == 1
        return
    assert reason in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []
    assert bundle["match_rules"] == []


@pytest.mark.parametrize("count", [1, 2, 5])
def test_numeric_bundle_count_does_not_override_unparsed_parenthesized_multiplication(count):
    raw = item(name="김부각 세트(5개입) x 5", package_quantity=5, package_unit="ea", bundle_count=count, display_unit="5개", unit="5개")
    bundle = build([ingestion(1, [raw])])
    assert "bundle_multiplier_unresolved" in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []


@pytest.mark.parametrize(("title", "quantity"), [
    ("냉동 다진마늘 400g x 3 x 2", 400),
    ("차 5g x 30ct x 2", 5),
    ("냉동 다진마늘 400g×3×2", 400),
])
@pytest.mark.parametrize("count", [None, 1, 3, 6])
def test_complete_chain_requires_structured_count_agreement(title, quantity, count):
    raw = item(name=title, package_quantity=quantity, package_unit="g", bundle_count=count, display_unit=f"{quantity}g", unit=f"{quantity}g")
    bundle = build([ingestion(1, [raw])])
    expected = 60 if quantity == 5 else 6
    if count is None or count == expected:
        assert bundle["unresolved"] == []
        assert bundle["variants"][0]["bundle_count"] == expected
        assert bundle["variants"][0]["package_quantity"] == quantity
    else:
        assert "bundle_count_conflict" in bundle["unresolved"][0]["reasons"]
        assert bundle["variants"] == []
        assert bundle["offers"] == []
        assert bundle["match_rules"] == []


def test_complete_chain_in_display_unit_is_recovered():
    raw = item(name="냉동 다진마늘", package_quantity=400, package_unit="g", display_unit="400g x 3 x 2", unit="400g")
    bundle = build([ingestion(1, [raw])])
    assert bundle["unresolved"] == []
    assert bundle["variants"][0]["bundle_count"] == 6


@pytest.mark.parametrize("title", [
    "마늘 400g x 3 + 생강 200g x 2", "마늘 400g x 3묶음 x 2",
    "마늘 400g x 3 x 2.5", "마늘 400g x 3 x 2종",
])
def test_separate_or_partially_parsed_chains_remain_unresolved(title):
    raw = item(name=title, package_quantity=400, package_unit="g", display_unit="400g", unit="400g")
    bundle = build([ingestion(1, [raw])])
    assert "bundle_multiplier_unresolved" in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []


def test_thousands_parser_does_not_overwrite_conflicting_collected_quantity():
    raw = item(name="국 2,500g", package_quantity=500, package_unit="g", display_unit="500g", unit="500g")
    bundle = build([ingestion(1, [raw])])
    assert "unit_title_conflict" in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []


def test_wholesale_chain_is_parsed_but_requires_package_review():
    raw = item(name="두유 190ml x 24 x 189", package_quantity=190, package_unit="ml", display_unit="190ml", unit="190ml")
    bundle = build([ingestion(1, [raw])])
    assert "bulk_package_review_required" in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []


def test_single_explicit_mass_bundle_is_still_comparable():
    raw = item(name="목이버섯 200g×2", package_quantity=200, package_unit="g", display_unit="200g×2", unit="200g×2", sale_price=10000, original_price=None)
    bundle = build([ingestion(1, [raw])])
    assert bundle["unresolved"] == []
    assert bundle["variants"][0]["package_quantity"] == 200
    assert bundle["variants"][0]["bundle_count"] == 2
    assert bundle["offers"][0]["standard_unit_price"] == 2500


def test_structured_total_and_compact_title_bundle_recover_per_package_boundary():
    raw = item(
        name="에이클래스 체다 슬라이스치즈 210g (30gX7)",
        package_quantity=210, package_unit="g", display_unit="210g", unit="210g",
        sale_price=7000, original_price=None,
    )
    bundle = build([ingestion(1, [raw])])
    assert bundle["unresolved"] == []
    assert bundle["variants"][0]["package_quantity"] == 30
    assert bundle["variants"][0]["bundle_count"] == 7
    assert bundle["offers"][0]["standard_unit_price"] == pytest.approx(3333.3333)


@pytest.mark.parametrize('default_count', [None, 1, 6])
def test_separate_cup_measure_and_sold_count_preserve_source_inner_contents(default_count):
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules
    title = '농심 신라면 블랙 사발면101G 6입'
    # Original Homeplus127938195 fields:101g is inner cup content, with a
    # separate literal6입. A schema default1 is not a second outer factor.
    raw = {'package_quantity':101, 'package_unit':'g', 'display_unit':'101g',
           'unit':'101g', 'attributes':{'unit_price_basis_raw':'100G'}}
    if default_count is not None:
        raw['bundle_count'] = default_count
    before = deepcopy(raw)
    assert uses_reviewed_quantity_rules(title)
    outputs = [normalize_catalog_package({**raw, 'sale_price':quote}, raw['attributes'], title,
               category_id='food.meals.noodles.cup_ramen') for quote in (9600, 12300)]
    assert outputs[0] == outputs[1]
    package, issues = outputs[0]
    assert issues == []
    assert (package['package_quantity'],package['package_unit'],package['bundle_count']) == (101,'g',6)
    assert raw == before


@pytest.mark.parametrize('title,quantity,unit,display,expected', [
    ('시험음료 병당100ml 6병',100,'ml','100ml',(100,'ml',6)),
    ('시험식품 개당101g 6입',606,'g','606g',(101,'g',6)),
    ('시험식품 101g씩 6입',101,'g','101g×6',(101,'g',6)),
    ('시험식품 개당101g 6입',101,'g','6입',(101,'g',6)),
])
def test_separate_count_explicit_per_pack_scope_preserves_total_without_repeating_count(title,quantity,unit,display,expected):
    from core.catalog_quantity import normalize_catalog_package
    package, issues = normalize_catalog_package(
        {'package_quantity':quantity,'package_unit':unit,'display_unit':display}, {}, title)
    assert issues == []
    assert (package['package_quantity'],package['package_unit'],package['bundle_count']) == expected


@pytest.mark.parametrize('change,attrs,title,leaf', [
    ({'bundle_count':2},{},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({},{'bundleCount':2},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({},{'pack_qty':606,'pack_unit':'g'},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({'display_unit':'101g×2'},{},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({'display_unit':'101g 5입'},{},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({'display_unit':'606g×6'},{},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({'display_unit':'100g 당 1584원','unit':''},{},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({},{'unit_price_basis_raw':'1개'},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({},{'unit_price_basis_raw':'100ml'},'농심 신라면 블랙 사발면101G 6입','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6입',None),
    ({},{},'시험식품101G 6입','food.meals.noodles.cup_ramen'),
    ({'package_quantity':600,'display_unit':'600g','unit':'600g'},{},'시험식품600g5입',None),
    ({},{},'농심 신라면 블랙 사발면 총101G 6입','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6입×2팩','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6입 2팩','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6입+1입','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6입 혼합세트','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 6.5입','food.meals.noodles.cup_ramen'),
    ({},{},'농심 신라면 블랙 사발면101G 5~6입','food.meals.noodles.cup_ramen'),
])
def test_separate_measured_count_conflicts_and_ambiguous_scope_stay_held(change,attrs,title,leaf):
    from core.catalog_quantity import normalize_catalog_package
    raw = {'package_quantity':101,'package_unit':'g','display_unit':'101g','unit':'101g',**change}
    package, issues = normalize_catalog_package(raw, attrs, title, category_id=leaf)
    assert package is None and issues


@pytest.mark.parametrize('title', ['시험컵101g 6호','시험컵101g 모델6','시험컵101g 6Brix'])
def test_grade_and_model_numbers_are_not_separate_sold_counts(title):
    from core.catalog_quantity import normalize_catalog_package
    package, issues = normalize_catalog_package(
        {'package_quantity':101,'package_unit':'g','display_unit':'101g'}, {}, title,
        category_id='food.meals.noodles.cup_ramen')
    assert issues == [] and package['bundle_count'] == 1


def test_separate_count_never_materializes_approximate_mass_as_inner_contents():
    from core.catalog_quantity import normalize_catalog_package
    package, issues = normalize_catalog_package(
        {'package_quantity':101,'package_unit':'g','display_unit':'101g'}, {},
        '시험사발면101g 내외 6입', category_id='food.meals.noodles.cup_ramen')
    assert issues == []
    assert (package['package_quantity'],package['package_unit'],package['bundle_count']) == (6,'개',1)


@pytest.mark.parametrize('title,quantity,unit,display,leaf,bundle', [
    ('저지방 우유 (1L2개)',1,'L','1L','plain',None),
    ('저지방 우유 (1L2개)',1,'L','1L','plain',1),
    ('저지방 우유 (1L2개)',1,'L','1L','plain',2),
    ('저지방 우유 (1L2개)',1000,'ml','1L×2','plain',2),
    ('시험 바나나 우유 200ml 3개',200,'ml','200ml','banana',None),
    ('시험 초코우유 200ml 3개',200,'ml','200ml','chocolate',None),
])
def test_separate_liquid_milk_count_requires_source_inner_container_scope(title,quantity,unit,display,leaf,bundle):
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules
    attrs = {'category_hint':'우유/유제품','mart_native_category_path':'우유/유제품',
             'collection':'서울우유','unit_price_display':'100ml 당 274원'}
    raw = {'package_quantity':quantity,'package_unit':unit,'display_unit':display,
           'unit':display,'category':'우유/유제품','attributes':attrs}
    if bundle is not None:
        raw['bundle_count'] = bundle
    before = deepcopy(raw)
    assert uses_reviewed_quantity_rules(title)
    results = [normalize_catalog_package({**raw,'sale_price':quote},attrs,title,
               category_id='food.dairy.milk.'+leaf) for quote in (5480,6500)]
    assert results[0] == results[1]
    package, issues = results[0]
    assert issues == []
    expected = (1000,'ml',2) if unit.lower() == 'l' or quantity == 1000 else (200,'ml',3)
    assert (package['package_quantity'],package['package_unit'],package['bundle_count']) == expected
    assert raw == before


@pytest.mark.parametrize('title,leaf,change,attrs', [
    ('저지방 우유 (1L2개)',None,{},{}),
    ('저지방 우유 (1L2개)','food.drinks.juice.fruit',{},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{'category':'주방용품/세제'},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{}, {'mart_native_category_path':'반려동물'}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{'bundle_count':3},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{}, {'bundleCount':3}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{'package_quantity':2,'display_unit':'2L','unit':'2L'},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{'display_unit':'1L×3'},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{'display_unit':'100ml 당 274원','unit':''},{}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{}, {'unit_price_basis_raw':'100g'}),
    ('저지방 우유 (1L2개)','food.dairy.milk.plain',{}, {'unit_price_basis_raw':'1개'}),
    ('시험 오렌지주스1L2개','food.dairy.milk.plain',{},{}),
    ('시험 두유1L2개','food.dairy.milk.plain',{},{}),
    ('시험 우유맛음료1L2개','food.dairy.milk.plain',{},{}),
    ('시험 우유분말600g5입','food.dairy.milk.plain',{'package_quantity':600,'package_unit':'g','display_unit':'600g','unit':'600g'},{}),
    ('시험 우유용용기1L2개','food.dairy.milk.plain',{},{}),
    ('시험 우유600g5입','food.dairy.milk.plain',{'package_quantity':600,'package_unit':'g','display_unit':'600g','unit':'600g'},{}),
    ('시험 우유1L2개+다른우유500ml','food.dairy.milk.plain',{},{}),
    ('시험 우유1L2개 2팩','food.dairy.milk.plain',{},{}),
    ('시험 우유1L2개×2팩','food.dairy.milk.plain',{},{}),
    ('시험 우유1L2~3개','food.dairy.milk.plain',{},{}),
    ('시험 우유1L내외2개','food.dairy.milk.plain',{},{}),
    ('시험 우유1L2개내외','food.dairy.milk.plain',{},{}),
])
def test_separate_milk_count_does_not_broaden_unknown_or_conflicting_roles(title,leaf,change,attrs):
    from core.catalog_quantity import normalize_catalog_package
    raw = {'package_quantity':1,'package_unit':'L','display_unit':'1L','unit':'1L',
           'category':'우유/유제품',**change}
    package, issues = normalize_catalog_package(raw,attrs,title,category_id=leaf)
    assert package is None and issues


@pytest.mark.parametrize(("title", "quantity", "unit"), [
    ("맑은청 찰토마토 7~10입/팩", 10, "입"),
    ("토마토 7입~10입/팩", 10, "입"),
    ("홍로사과 4-8입(봉)", 1, "봉"),
])
def test_count_interval_is_not_a_fixed_quantity(title, quantity, unit):
    raw = item(name=title, package_quantity=quantity, package_unit=unit, display_unit=f"{quantity}{unit}", unit=f"{quantity}{unit}")
    bundle = build([ingestion(1, [raw])])
    assert "count_range_unresolved" in bundle["unresolved"][0]["reasons"]
    assert bundle["offers"] == []


def test_fixed_mass_with_variable_piece_count_remains_mass_based():
    raw = item(name="토마토 1.5kg(5~6입)", package_quantity=1.5, package_unit="kg", display_unit="1.5kg", unit="1.5kg")
    bundle = build([ingestion(1, [raw])])
    assert not bundle["unresolved"]
    assert bundle["variants"][0]["package_quantity"] == 1500
    assert bundle["variants"][0]["package_unit"] == "g"
    assert bundle["variants"][0]["bundle_count"] == 1


def test_legacy_comma_quantity_misparse_and_mixed_refill_are_held():
    for raw in [
        item(name="샴푸 1,050ml", package_quantity=50, display_unit="50ml"),
        item(name="샴푸 본품500ml+리필450ml", package_quantity=450, display_unit="450ml"),
    ]:
        bundle = build([ingestion(1, [raw])])
        assert "multiple_package_quantities" in bundle["unresolved"][0]["reasons"]


def test_generic_homeplus_badge_does_not_invent_conditional_benefit():
    bundle = build([ingestion(1, [item(event_name="행사상품")])])
    assert bundle["offers"][0]["price"] == 19900
    assert bundle["offers"][0]["promotion_type"] == "was_now_price"


@pytest.mark.parametrize(("label", "buy", "free", "spend", "received"), [
    ("1+1", 1, 1, 19900, 2),
    ("2+1", 2, 1, 39800, 3),
])
def test_explicit_buy_x_get_y_preserves_terms_and_effective_unit_price(label, buy, free, spend, received):
    bundle = build([ingestion(1, [item(original_price=None, promo_label=label, event_name=label)])])
    offer = bundle["offers"][0]
    assert offer["offer_state"] == "active"
    assert offer["promotion_type"] == "buy_x_get_y"
    assert offer["promotion_conditions"] == {
        "buy_quantity": buy,
        "free_quantity": free,
        "minimum_quantity": buy,
        "condition_text": label,
    }
    assert offer["raw_evidence"]["promotion_conditions"] == offer["promotion_conditions"]
    assert offer["standard_unit_price"] == pytest.approx(spend * 100 / (120 * 24 * received))
    assert bundle["offer_week_links"][0]["observed_min_price"] == spend


def test_buy_x_get_y_without_numeric_terms_requires_review():
    bundle = build([ingestion(1, [item(original_price=None, promo_type="buy_x_get_y", event_name="증정")])])
    offer = bundle["offers"][0]
    assert offer["offer_state"] == "pending_review"
    assert offer["standard_unit_price"] is None
    assert "promotion_conditions_unresolved" in offer["audit_provenance"]["review_reasons"]


def test_different_explicit_promotion_conditions_do_not_collapse():
    first = item(promo_type="checkout_discount")
    second = deepcopy(first)
    first["attributes"]["is_member_only"] = True
    second["attributes"]["is_member_only"] = False
    bundle = build([ingestion(1, [first]), ingestion(2, [second])])
    assert len(bundle["offers"]) == 2


def test_conditional_price_without_safe_semantics_is_not_comparable():
    row = item(original_price=None, coupon_required=True)
    bundle = build([ingestion(1, [row])])
    offer = bundle["offers"][0]
    assert offer["offer_state"] == "pending_review"
    assert offer["promotion_type"] == "unknown"
    assert offer["price"] == row["sale_price"]
    assert offer["standard_unit_price"] is None
    assert offer["price_per_100g"] is None
    assert bundle["offer_week_links"][0]["observed_min_price"] is None
    assert bundle["offer_week_links"][0]["observed_max_price"] is None
    assert bundle["products"][0]["is_active"] is False
    assert "promotion_conditions_unresolved" in offer["audit_provenance"]["review_reasons"]
    assert bundle["unresolved"] == []


@pytest.mark.parametrize("source_title", [
    "일품채 목이버섯 200g / 최소구매 2",
    "일품채 목이버섯 200g / 최소 구매 수량: 2개",
    "일품채 목이버섯 200g / 최소구매 수량 별도 안내",
])
@pytest.mark.parametrize("promotion_type", [None, "final_price", "checkout_discount", "bundle_price"])
def test_source_title_minimum_purchase_is_preserved_and_requires_offer_review(source_title, promotion_type):
    # The public category decision cannot approve an unmodelled purchase
    # condition, even when a crawler supplies an otherwise known promo type.
    raw = item(
        source="costco", name="일품채 목이버섯 200g", sale_price=16990,
        original_price=None, event_name=None, promotion_type=promotion_type,
        package_quantity=200, package_unit="g", display_unit="200g", unit="200g",
        attributes={"source_record_key": "615852", "raw_name": source_title},
    )
    bundle = build([ingestion(1, [raw], "costco")], {("costco", "615852"): assignment()})
    offer = bundle["offers"][0]
    assert offer["promotion_conditions"]["source_title_purchase_condition"] == source_title
    assert offer["price"] == 16990  # Never invent 33980 or claim one pack is purchasable.
    assert offer["offer_state"] == "pending_review"
    assert offer["promotion_type"] == "unknown"
    assert offer["standard_unit_price"] is None
    assert offer["price_per_100g"] is None
    assert offer["audit_provenance"]["review_reasons"] == ["promotion_conditions_unresolved"]
    assert offer["raw_evidence"]["observations"][0]["raw_payload"] == raw
    assert bundle["variants"][0]["package_quantity"] == 200
    assert bundle["variants"][0]["bundle_count"] == 1
    assert bundle["offer_week_links"][0]["observed_min_price"] is None
    assert bundle["offer_week_links"][0]["observed_max_price"] is None
    assert bundle["products"][0]["is_active"] is False
    assert bundle["observation_accounting"][0]["offer_state"] == "pending_review"
    assert bundle["unresolved"] == []


def test_costco_title_without_purchase_condition_remains_comparable():
    raw = item(
        source="costco", name="일품채 목이버섯 200g", sale_price=16990,
        original_price=None, event_name=None,
        package_quantity=200, package_unit="g", display_unit="200g", unit="200g",
    )
    bundle = build([ingestion(1, [raw], "costco")], {("costco", "123"): assignment()})
    offer = bundle["offers"][0]
    assert offer["offer_state"] == "active"
    assert offer["promotion_type"] == "final_price"
    assert offer["promotion_conditions"] == {}
    assert offer["standard_unit_price"] == 8495


def test_costco_only_can_use_explicitly_labelled_utc_batch_received_time_proxy():
    raw = item(crawled_at=None)
    batch = {**ingestion(1, [raw], "costco"), "crawled_at": "2026-09-02T01:02:03.123456"}
    bundle = build([batch], {("costco", "123"): assignment()})
    offer = bundle["offers"][0]
    assert offer["crawled_at"] == "2026-09-02T01:02:03.123456Z"
    assert offer["audit_provenance"]["timestamp_source"] == "ingestion_received_at"
    assert offer["audit_provenance"]["observed_time_precision"] == "batch"
    assert offer["raw_evidence"]["observations"][0]["raw_payload"]["crawled_at"] is None
    homeplus = build([{**batch, "crawler_name": "homeplus"}])
    assert "item_crawled_at_missing_or_invalid" in homeplus["unresolved"][0]["reasons"]


def test_exact_retry_collapses_offer_but_keeps_each_original_payload_and_id():
    first = ingestion(10)
    second = ingestion(11)
    bundle = build([first, second])
    assert len(bundle["source_listings"]) == 1
    assert len(bundle["offers"]) == 1
    offer = bundle["offers"][0]
    assert offer["audit_provenance"]["source_ingestion_ids"] == [10, 11]
    assert offer["audit_provenance"]["raw_record_ids"] == ["ingestion:10:0", "ingestion:11:0"]
    assert len(offer["raw_evidence"]["observations"]) == 2
    assert all(row["raw_payload"] == item() for row in offer["raw_evidence"]["observations"])
    assert bundle["build_report"]["exact_retry_observations_collapsed"] == 1
    assert bundle["build_report"]["source_observations"] == 2


def test_real_same_day_and_next_day_crawls_remain_distinct_offers():
    bundle = build([
        ingestion(1),
        ingestion(2, [item(crawled_at="2026-09-02T10:06:00+09:00")]),
        ingestion(3, [item(crawled_at="2026-09-03T10:00:00+09:00")]),
    ])
    assert len(bundle["source_listings"]) == 1
    assert len(bundle["offers"]) == 3
    assert len({row["crawled_at"] for row in bundle["offers"]}) == 3


def test_timezone_equivalent_retries_are_the_same_observation_time():
    bundle = build([ingestion(1), ingestion(2, [item(crawled_at="2026-09-02T01:00:00Z")])])
    assert len(bundle["offers"]) == 1


def test_costco_uses_checkout_sale_not_regular_price():
    row = item(source="costco", price=39990, sale_price=35990, original_price=None,
               promo_label="4,000원 할인", promo_type="checkout_discount", event_name="4,000원 할인")
    bundle = build([ingestion(1, [row], "costco")], {("costco", "123"): assignment()})
    offer = bundle["offers"][0]
    assert offer["price"] == 35990
    assert offer["original_price"] == 39990
    assert offer["promotion_type"] == "checkout_discount"
    assert bundle["offer_week_links"][0]["observed_min_price"] is None


def test_costco_nested_regular_price_is_preserved():
    row = item(source="costco", sale_price=35990, original_price=None, promo_label="4,000원 할인")
    row["attributes"].update(price=39990, sale_price=35990)
    bundle = build([ingestion(1, [row], "costco")], {("costco", "123"): assignment()})
    assert bundle["offers"][0]["original_price"] == 39990


@pytest.mark.parametrize("change,reason", [
    ({"package_unit": "mystery"}, "unit_unknown"),
    ({"package_quantity": None}, "unit_unresolved"),
    ({"crawled_at": None}, "item_crawled_at_missing_or_invalid"),
    ({"sale_price": 0}, "sale_price_missing_or_invalid"),
    ({"name": "초코우유 120ml+120ml 기획", "display_unit": "120ml"}, "mixed_package_unresolved"),
])
def test_ambiguous_source_is_held_with_complete_evidence(change, reason):
    raw = item(**change)
    bundle = build([ingestion(1, [raw])])
    assert bundle["offers"] == []
    assert reason in bundle["unresolved"][0]["reasons"]
    assert bundle["unresolved"][0]["raw_payload"] == raw
    assert bundle["observation_accounting"][0]["status"] == "unresolved"


def test_name_or_spec_change_on_same_listing_is_not_an_automatic_alias():
    changed = item(name="초코우유 새이름 140ml×12", package_quantity=140, display_unit="140ml×12")
    bundle = build([ingestion(1), ingestion(2, [changed])])
    assert not bundle["products"] and not bundle["source_listings"]
    assert len(bundle["unresolved"]) == 2
    assert all("source_title_changed" in row["reasons"] for row in bundle["unresolved"])
    assert all("source_specification_changed" in row["reasons"] for row in bundle["unresolved"])


def test_unassigned_internal_leaf_and_low_confidence_do_not_publish():
    assert "catalog_assignment_missing" in build(assignments={})["unresolved"][0]["reasons"]
    for decision in [assignment(unified_category_id="food.dairy"), assignment(classification_confidence=0.79)]:
        assert not build(assignments={("homeplus", "123"): decision})["offers"]
    approved = build(assignments={("homeplus", "123"): assignment(classification_confidence=0.79, review_status="approved")})
    assert len(approved["offers"]) == 1
    assert approved["match_rules"] == []


def test_same_unbranded_name_across_marts_does_not_merge_and_collision_rule_is_held():
    raw = item(brand="__no_brand__")
    raw["attributes"]["brand"] = "국내산"
    bundle = build([ingestion(1, [raw], "homeplus"), ingestion(2, [raw], "emart")], {
        ("homeplus", "123"): assignment(), ("emart", "123"): assignment(),
    })
    assert len(bundle["products"]) == 2
    assert len(bundle["variants"]) == 2
    assert len(bundle["source_listings"]) == 2
    assert all(product["brand"] is None for product in bundle["products"])
    assert bundle["match_rules"] == []
    assert bundle["review_issues"][0]["reason"] == "runtime_match_key_collision"


def test_reviewed_product_group_has_distinct_package_variants():
    small = item(name="초코우유 140ml×12", package_quantity=140, display_unit="140ml×12")
    decision = assignment(product_group_key="cj-chocolate-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [small], "emart")], {
        ("homeplus", "123"): decision, ("emart", "123"): decision,
    })
    assert len(bundle["products"]) == 1
    assert len(bundle["variants"]) == 2
    assert {(row["package_quantity"], row["bundle_count"]) for row in bundle["variants"]} == {(120, 24), (140, 12)}


def test_explicit_product_group_with_conflicting_fallback_brands_is_held():
    first, second = item(), item()
    first["attributes"]["brand"] = "Brand A"
    second["attributes"]["brand"] = "Brand B"
    decision = assignment(product_group_key="same", canonical_name="초코우유")
    bundle = build([ingestion(1, [first]), ingestion(2, [second], "emart")], {
        ("homeplus", "123"): decision, ("emart", "123"): decision,
    })
    assert bundle["products"] == []
    assert all("product_group_conflict" in row["reasons"] for row in bundle["unresolved"])


def test_classification_attributes_are_preserved_with_source_evidence_without_mutation():
    attributes = {"fat_content": "low_fat", "sterilized": False, "unknown_trait": None, "source_labels": ["저지방"]}
    assignments = {("homeplus", "123"): assignment(classification_attributes=attributes, classification_reason="explicit name token")}
    original = deepcopy(assignments)
    bundle = build(assignments=assignments)
    product_attributes = bundle["products"][0]["attributes"]
    assert product_attributes["classification_attributes"] == attributes
    assert product_attributes["classification_attribute_evidence"] == [{
        "source_name": "homeplus", "source_record_key": "123",
        "classification_attributes": attributes, "classification_reason": "explicit name token",
        "source_ingestion_ids": [1], "raw_record_ids": ["ingestion:1:0"],
    }]
    product_attributes["classification_attributes"]["source_labels"].append("changed output")
    assert assignments == original


def test_explicit_group_merges_compatible_known_attributes_but_none_is_not_false():
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [item()], "emart")], {
        ("homeplus", "123"): {**common, "classification_attributes": {"fat_content": None, "sterilized": False}},
        ("emart", "123"): {**common, "classification_attributes": {"fat_content": "low_fat", "sterilized": False}},
    })
    assert len(bundle["products"]) == 1
    attributes = bundle["products"][0]["attributes"]
    assert attributes["classification_attributes"] == {"fat_content": "low_fat", "sterilized": False}
    assert {row["source_name"] for row in attributes["classification_attribute_evidence"]} == {"homeplus", "emart"}
    assert any(row["classification_attributes"]["fat_content"] is None for row in attributes["classification_attribute_evidence"])
    assert bundle["build_report"]["classification_attribute_conflict_groups"] == 0


@pytest.mark.parametrize("first_value,second_value", [("low_fat", "fat_free"), (True, False), (False, 0)])
def test_explicit_group_attribute_conflicts_hold_all_members_and_preserve_candidates(first_value, second_value):
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    decisions = {
        ("homeplus", "123"): {**common, "classification_attributes": {"trait": first_value}},
        ("emart", "123"): {**common, "classification_attributes": {"trait": second_value}},
    }
    sources = [ingestion(1), ingestion(2, [item()], "emart")]
    bundle = build(sources, decisions)
    assert bundle == build(list(reversed(sources)), dict(reversed(list(decisions.items()))))
    assert bundle["products"] == []
    assert bundle["variants"] == []
    assert bundle["source_listings"] == []
    assert bundle["offers"] == []
    assert bundle["match_rules"] == []
    assert len(bundle["unresolved"]) == 2
    assert all("product_group_classification_attribute_conflict" in row["reasons"] for row in bundle["unresolved"])
    assert bundle["unresolved"][0]["classification_attributes"] == {"trait": first_value}
    assert bundle["unresolved"][1]["classification_attributes"] == {"trait": second_value}
    issue = bundle["review_issues"][0]
    assert issue["reason"] == "product_group_classification_attribute_conflict"
    assert issue["raw_record_ids"] == ["ingestion:1:0", "ingestion:2:0"]
    assert len(issue["attribute_conflicts"]["trait"]) == 2
    assert {source["source_name"] for candidate in issue["attribute_conflicts"]["trait"] for source in candidate["sources"]} == {"homeplus", "emart"}
    assert all(row["status"] == "unresolved" for row in bundle["observation_accounting"])
    assert bundle["build_report"]["classification_attribute_conflict_groups"] == 1


def test_nested_classification_attributes_compare_values_not_object_key_order():
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [item()], "emart")], {
        ("homeplus", "123"): {**common, "classification_attributes": {"nutrition": {"fat": "low", "sugar": "none"}}},
        ("emart", "123"): {**common, "classification_attributes": {"nutrition": {"sugar": "none", "fat": "low"}}},
    })
    assert len(bundle["products"]) == 1
    assert bundle["products"][0]["attributes"]["classification_attributes"] == {"nutrition": {"fat": "low", "sugar": "none"}}


def test_classification_attribute_evidence_survives_an_unrelated_unit_blocker():
    bundle = build([ingestion(1, [item(package_unit="unknown-unit")])], {
        ("homeplus", "123"): assignment(classification_attributes={"fat_content": "low_fat"}),
    })
    assert bundle["products"] == []
    unresolved = bundle["unresolved"][0]
    assert unresolved["classification_attributes"] == {"fat_content": "low_fat"}
    assert unresolved["classification_attribute_evidence"]["raw_record_ids"] == ["ingestion:1:0"]
    assert "unit_unknown" in unresolved["reasons"]


def test_non_object_classification_attributes_are_held_not_silently_discarded():
    bundle = build(assignments={("homeplus", "123"): assignment(classification_attributes=["low_fat"])})
    assert bundle["products"] == []
    unresolved = bundle["unresolved"][0]
    assert "classification_attributes_invalid" in unresolved["reasons"]
    assert unresolved["classification_attributes"] == ["low_fat"]
    assert unresolved["classification_attribute_evidence"]["classification_attributes"] == ["low_fat"]


def test_report_separates_classification_from_safe_offer_coverage():
    bundle = build([ingestion(1, [item(promo_label="함께할인")])])
    assert bundle["build_report"]["classification_coverage"]["observations"] == 1
    assert bundle["build_report"]["included_observations"] == 1
    assert bundle["build_report"]["staged_observations"] == 1
    assert bundle["build_report"]["active_offer_observations"] == 0
    assert bundle["build_report"]["pending_promotion_observations"] == 1
    assert bundle["build_report"]["pending_promotion_offers"] == 1
    assert bundle["build_report"]["offer_coverage_by_mart"] == {"homeplus": 1}
    assert bundle["build_report"]["active_offer_coverage_by_mart"] == {}
    assert bundle["build_report"]["included_means"] == "staged_only_not_publicly_approved"
    assert bundle["build_report"]["public_approval"] is False
    assert bundle["observation_accounting"][0]["offer_state"] == "pending_review"
    assert bundle["observation_accounting"][0]["publication_status"] == "not_approved"


def test_promotion_only_retry_retains_all_raw_evidence_and_one_review_issue():
    raw = item(promo_label="함께할인")
    bundle = build([ingestion(1, [raw]), ingestion(2, [raw])])
    assert len(bundle["offers"]) == 1
    assert bundle["offers"][0]["offer_state"] == "pending_review"
    assert [row["raw_payload"] for row in bundle["offers"][0]["raw_evidence"]["observations"]] == [raw, raw]
    assert len(bundle["review_issues"]) == 1
    assert bundle["review_issues"][0]["reason"] == "promotion_pending_review"
    assert bundle["review_issues"][0]["raw_record_ids"] == ["ingestion:1:0", "ingestion:2:0"]
    assert bundle["build_report"]["runtime_match_key_collisions"] == 0
    assert bundle["build_report"]["pending_promotion_observations"] == 2


def test_promotion_plus_identity_problem_still_holds_entire_observation():
    bundle = build([ingestion(1, [item(promo_label="함께할인", package_unit="unknown-unit")])])
    assert bundle["offers"] == []
    assert "unit_unknown" in bundle["unresolved"][0]["reasons"]
    assert "promotion_unresolved" in bundle["unresolved"][0]["reasons"]


def test_group_is_active_if_any_listing_has_an_active_offer_regardless_of_order():
    decision = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    for first_pending in (True, False):
        homeplus = item(promo_label="함께할인") if first_pending else item()
        emart = item() if first_pending else item(promo_label="함께할인")
        bundle = build([ingestion(1, [homeplus]), ingestion(2, [emart], "emart")], {
            ("homeplus", "123"): decision, ("emart", "123"): decision,
        })
        assert len(bundle["products"]) == 1
        assert bundle["products"][0]["is_active"] is True
        assert {row["offer_state"] for row in bundle["offers"]} == {"active", "pending_review"}


def test_fixed_display_label_requires_exact_independent_price_match():
    exact = build([ingestion(1, [item(event_name="균일가 5,980원", sale_price=5980, original_price=None)])])
    assert exact["offers"][0]["offer_state"] == "active"
    assert exact["offers"][0]["promotion_type"] == "final_price"
    assert exact["offers"][0]["price"] == 5980
    mismatch = build([ingestion(1, [item(event_name="균일가 5,980원", sale_price=6980, original_price=None)])])
    assert mismatch["offers"][0]["offer_state"] == "pending_review"
    assert mismatch["offers"][0]["price"] == 6980


def test_runtime_miss_match_key_is_preserved_and_fallback_matches_shared_contract():
    runtime = item(match_key="__no_brand__|runtime full name|120.0|ml", matching_status="miss")
    assert build([ingestion(1, [runtime])])["match_rules"][0]["match_key"] == runtime["match_key"]
    assert build()["match_rules"][0]["match_key"] == build_match_key("__no_brand__", item()["name"], None, "120ml×24")


def test_ids_and_bundle_are_stable_under_ingestion_order_and_input_is_unchanged():
    ingestions = [ingestion(5), ingestion(6, [item(crawled_at="2026-09-03T10:00:00+09:00")])]
    original = deepcopy(ingestions)
    assert build(ingestions) == build(reversed(ingestions))
    assert ingestions == original
    assert stable_id("listing", "a|b", "c") != stable_id("listing", "a", "b|c")
    assert len(normalize_pending_ingestions([ingestions[0], ingestions[0]])) == 1


def test_generated_bundle_validates_against_current_v2_import_contract():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        result = validate_bundle(session, build(), "test-hash")
    assert result.ok, result.errors


def test_all_raw_rows_accounted_even_with_invalid_item_and_missing_source_key():
    missing = item(attributes={"brand": "CJ"})
    bundle = build([ingestion(1, [item(), missing, None])])
    assert bundle["build_report"]["source_observations"] == 3
    assert len(bundle["observation_accounting"]) == 3
    assert {row["raw_record_id"] for row in bundle["observation_accounting"]} == {"ingestion:1:0", "ingestion:1:1", "ingestion:1:2"}
    assert bundle["unresolved"][-1]["raw_payload"] is None


def test_reviewed_linear_contents_keep_dimension_and_source_price_basis(monkeypatch):
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence, valid_linear_contents_variant
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure
    raw = item(name='검수된 선형 위생소모품', package_quantity=None, package_unit='', unit='', display_unit='',
               sale_price=6000, original_price=None)
    review = {'title':raw['name'], 'category_id':LEAF, 'required_source':source_review_evidence(raw),
              'quantity_fields':listing_quantity_evidence(raw), 'normalized':[40,'m',3],
              'measurement_role':'declared_linear_contents'}
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_EXPLICIT_LISTING_PACKAGES', (review,))
    package, issues = normalize_catalog_package(raw, raw['attributes'], raw['name'])
    assert not issues and valid_linear_contents_variant(package)
    assert package['display_unit'] == '40m×3' and package_pricing_measure(package) == (120,'m')
    assert package_pricing_measure({**package, 'attributes':{}}) is None
    for mutation in ({'sale_price':9000,'unit_price_display':'100m당 7,500원'},
                     {'unit_price_text':'1m당50원'}, {'unit_price_text':'1m당75원'}):
        value, conflicts = normalize_catalog_package({**raw, **mutation}, raw['attributes'], raw['name'])
        assert not conflicts and value == package
    for mutation in ({'unit_price_text':'100g당500원'}, {'unit_price_text':'1개당500원'},
                     {'unit_price_text':'0m당500원'}, {'unit_price_text':'unknown'},
                     {'package_quantity':30,'package_unit':'cm'}, {'bundle_count':4},
                     {'detail_url':'https://example.test/item/other'}, {'category':'가전'},
                     {'package_quantity':{'invalid':40}}):
        value, conflicts = normalize_catalog_package({**raw, **mutation}, raw['attributes'], raw['name'])
        assert value is None and conflicts
    assert normalize_catalog_package({'name':raw['name']}, {}, raw['name'])[0] is None
    result = build([ingestion(rows=[raw])])
    assert len(result['products']) == len(result['variants']) == len(result['offers']) == 1
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, result, 'linear').ok
    offer = result['offers'][0]
    assert offer['standard_unit_price'] == 5000 and offer['price_per_100g'] is None
    assert result['variants'][0]['standard_unit'] == 'm'


def test_source_bound_partial_entitlement_survives_quantity_and_offer_hold():
    from services.initial_taxonomy import classify_record, taxonomy_categories
    from services.initial_catalog_workspace import prepare_assignments
    from core.reviewed_content_quantities import REVIEWED_LISTING_SPECIFICATIONS
    review = REVIEWED_LISTING_SPECIFICATIONS[0]
    raw = {'name':review['title'], 'raw_name':review['title'], 'source':review['source_name'],
           'mart':review['source_name'], 'source_record_key':review['source_record_key'],
           'mart_native_code':review['source_record_key'], 'source_url':review['required_source']['source_urls'][0],
           'sale_price':44750, 'pack_qty':None, 'pack_unit':None,
           **review['required_source']['source_fields']}
    for price in (44750, 40000):
        actual = {**deepcopy(raw), 'sale_price':price}
        inputs = [ingestion(1, [actual], 'costco')]
        rows = normalize_pending_ingestions(inputs)
        assignments, decisions = prepare_assignments(rows, classify_record)
        bundle = build_initial_catalog_bundle(inputs, categories=taxonomy_categories({review['category_id']}),
                                               assignments=assignments, run_id='partial-entitlement')
        assert not bundle['products'] and not bundle['variants'] and not bundle['offers']
        assert len(bundle['unresolved']) == 1 and len(bundle['observation_accounting']) == 1
        held = bundle['unresolved'][0]
        assert held['classification_attributes'] == {key:value for key,value in review['classification_attributes'].items() if value is not None}
        assert held['classification_attributes'].get('sold_certificate_count') is None
        assert held['classification_attributes'].get('aggregate_entitlement_amount') is None
        assert held['classification_attribute_evidence']['raw_record_ids'] == ['ingestion:1:0']
        assert held['promotion_conditions']['minimum_quantity'] == 2
        assert held['promotion_type'] == 'unknown'
        from core.reviewed_source_evidence import source_entitlement_specification
        spec = source_entitlement_specification(held['package'])
        assert spec['denomination_amount'] == 50000 and spec['sold_certificate_count'] is None
        assert [held['package'][key] for key in ('package_quantity', 'package_unit', 'bundle_count')] == [None, None, 1]
        # A same-title synthetic row has no approved original observation hash.
        assert 'source_entitlement_evidence_conflict' in held['reasons']
        assert held['price'] == price
    for mutation in ({'source_record_key':'other'}, {'mart_native_code':'other'}, {'source_url':'https://retailer.example/other'},
                     {'name':'다른 상품권', 'raw_name':'다른 상품권'}, {'category':'다른 문맥'}, {'source':'emart'}):
        changed = {**deepcopy(raw), **mutation}
        assert not classify_record(changed).get('classification_attributes')
    assert not classify_record({'name':raw['name']}).get('classification_attributes')


def test_declared_contents_price_key_retains_observed_key_in_raw_history():
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from services.initial_taxonomy import taxonomy_categories
    from core.catalog_matching import _match_key_for_row
    from urllib.parse import urlparse, parse_qs
    review = next(record for record in REVIEWED_EXPLICIT_LISTING_PACKAGES
                  if 'display_unit' in record['quantity_fields'] and isinstance(record['quantity_fields']['display_unit'],str)
                  and '당' in record['quantity_fields']['display_unit'])
    raw = {'name':review['title'], 'source':'emart', 'source_url':review['required_source']['source_urls'][0],
           'sale_price':10000, 'match_key':'immutable-crawler-historical-key', 'attributes':{}, 'brand':'__no_brand__', 'crawled_at':'2026-09-02T16:43:28Z'}
    for fields in (review['required_source']['source_fields'], review['quantity_fields']):
        for field, value in fields.items():
            layer = raw['attributes'] if field.startswith('attributes.') else raw
            layer[field.rsplit('.',1)[-1]] = str(value[0] or '')+value[1]+'당1,618원' if isinstance(value,list) else value
    native = parse_qs(urlparse(raw['source_url']).query)['itemId'][0]
    raw['attributes']['source_record_key'] = native
    original = deepcopy(raw)
    assignments = {('emart',native):assignment(unified_category_id=review['category_id'])}
    bundle = build_initial_catalog_bundle([ingestion(1,[raw],'emart')], categories=taxonomy_categories({review['category_id']}),
                                          assignments=assignments, run_id='quoted-contents-key')
    assert not bundle['unresolved'], [row['reasons'] for row in bundle['unresolved']]
    changed = deepcopy(raw); basis=review['quantity_fields']['attributes.unit_price_display']
    quote=str(basis[0])+basis[1]+'당2,222원'
    changed.update(unit=quote,display_unit=quote,sale_price=12000); changed['attributes']['unit_price_display']=quote
    keys = {rule['match_key'] for rule in bundle['match_rules']}
    assert keys == {_match_key_for_row(raw)[0]}
    assert bundle['offers'][0]['raw_evidence']['observations'][0]['raw_payload']['match_key'] == raw['match_key']
    assert _match_key_for_row(changed)[0] == _match_key_for_row(raw)[0]
    assert len({rule['public_variant_id'] for rule in bundle['match_rules']}) == 1
    assert raw == original


def test_historical_mixed_scalar_retains_identity_and_quote_without_homogeneous_rate():
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from core.catalog_quantity import package_pricing_measure
    from services.initial_taxonomy import taxonomy_categories
    review = next(r for r in REVIEWED_EXPLICIT_LISTING_PACKAGES if r.get('comparison_hold_reason'))
    raw = {'name': review['title'], 'source': 'costco', 'sale_price': 22990,
           'brand': '__no_brand__', 'pack_qty': 230, 'pack_unit': 'g',
           'category': '과자', 'mart_native_category_path': '과자',
           'canonical_url': review['required_source']['source_urls'][0],
           'unit_price_display': '10g', 'unit_price_basis': '10g',
           'unit_price_basis_raw': '10g', 'unit_price_text': '10g',
           'crawled_at': '2026-08-31T10:51:51.875403+09:00',
           'attributes': {'source_record_key': '696218'}}
    original = deepcopy(raw)
    bundle = build_initial_catalog_bundle([ingestion(41, [raw], mart='costco')],
        categories=taxonomy_categories({review['category_id']}),
        assignments={('costco', '696218'): assignment(unified_category_id=review['category_id'])},
        run_id='mixed-scalar-focused')
    assert raw == original
    variant = bundle['variants'][0]
    assert [variant[k] for k in ('package_quantity','package_unit','bundle_count')] == [230,'g',4]
    assert variant['public_variant_id'] == stable_id('var', variant['public_product_id'], 230.0, 'g', 4)
    assert package_pricing_measure(variant) is None
    assert variant['attributes']['explicit_listing_quantity_review']['component_allocation'] is None
    assert bundle['offers'][0]['price'] == 22990
    assert bundle['offers'][0]['standard_unit_price'] is None
    assert bundle['offers'][0]['price_per_100g'] is None
    assert bundle['build_report']['included_observations'] == 1
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'mixed-history').ok


@pytest.mark.parametrize('native', ['069798234', '071403971', '070068619', '071403942', '114314981', '604243',
                                  '647352', '647353', '679666', '690859'])
def test_known_whole_scalar_keeps_unknown_composition_separate_from_identity(native):
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from core.reviewed_source_evidence import explicit_listing_package, package_comparison_reason
    from core.catalog_quantity import package_pricing_measure
    from core.catalog_matching import _match_key_for_row, _normalized_source_reason
    from services.initial_taxonomy import taxonomy_categories, classify_record
    review = next(r for r in REVIEWED_EXPLICIT_LISTING_PACKAGES if r.get('source_record_key') == native)
    mart=review.get('source_name','homeplus')
    raw = {'name':review['title'], 'source':mart, 'source_record_key':native, 'brand':'__no_brand__',
           'sale_price':3990, 'crawled_at':'2026-08-31T01:46:21Z', 'attributes':{'source_record_key':native},
           'source_url':review['required_source']['source_urls'][0]}
    for fields in (review['required_source']['source_fields'], review['quantity_fields']):
        for field, value in fields.items():
            layer = raw['attributes'] if field.startswith('attributes.') else raw
            layer[field.rsplit('.',1)[-1]] = str(value[0] or '')+value[1] if isinstance(value,list) else value
    if native != '069798234':
        raw['event_name'] = '1+1'
    original = deepcopy(raw)
    leaf = review['category_id']
    assert classify_record(raw)['unified_category_id'] == leaf
    bundle = build_initial_catalog_bundle([ingestion(18,[raw],mart=mart)], categories=taxonomy_categories({leaf}),
        assignments={(mart,native):assignment(unified_category_id=leaf)}, run_id='known-whole-composition')
    assert raw == original and not bundle['unresolved']
    variant, offer, rule = bundle['variants'][0], bundle['offers'][0], bundle['match_rules'][0]
    assert [variant[k] for k in ('package_quantity','package_unit','bundle_count')] == review['normalized']
    assert package_comparison_reason(variant) == review['comparison_hold_reason']
    assert package_pricing_measure(variant) is None
    assert offer['price'] == 3990 and offer['standard_unit_price'] is None and offer['price_per_100g'] is None
    assert review['component_allocation'] is None
    if review['comparison_hold_reason'] == 'contents_identity_and_allocation_unverified':
        assert review['content_identities'] is None
    else:
        assert len(set(review['content_identities'])) >= 2
    variant_with_sources = {**variant, 'source_listings':bundle['source_listings']}
    variants = {variant['public_variant_id']:variant_with_sources}
    for basis in ('10'+review['normalized'][1]+'당999원', '100'+review['normalized'][1]+'당1,111원', None):
        changed = deepcopy(raw); changed['sale_price'] = 4990
        if basis is None:
            changed['attributes'].pop('unit_price_basis_raw',None)
        else:
            changed['attributes']['unit_price_basis_raw'] = basis
        assert _match_key_for_row(changed)[0] == rule['match_key']
        assert _normalized_source_reason(changed,rule['match_key'],rule,variants) is None
    missing_context=({'attributes':{}} if any(field.startswith('attributes.')
                    for field in review['required_source']['source_fields']) else {'source_url':None})
    for change in ({'name':raw['name']+' 선택'}, {'source':'emart'}, {'source_url':raw['source_url']+'-other'},
                   {'source_record_key':'other'}, {'package_quantity':401}, {'package_unit':'개'},
                   {'category':'다른 문맥'}, missing_context,
                   {'attributes':{**raw['attributes'],'unit_price_basis_raw':'개당100원'}},
                   {'attributes':{**raw['attributes'],'unit_price_basis_raw':'0ml당100원'}},
                   {'attributes':{**raw['attributes'],'unit_price_basis_raw':'잘못된 표시'}}):
        changed = {**deepcopy(raw),**change}
        assert _normalized_source_reason(changed,rule['match_key'],rule,variants) is not None
    assert explicit_listing_package({'name':raw['name']},{},raw['name'])[0] is None
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session,bundle,'known-whole').ok
    engine.dispose()


@pytest.mark.parametrize('title', ['초콜릿 유리컵 기획팩 200g', '생수 200ml+쇼퍼백 기획', '홍삼정 200g (쇼핑백동봉)'])
def test_unreviewed_glass_gift_does_not_turn_food_mass_into_a_homogeneous_package(title):
    package, issues = _package({'package_quantity':200,'package_unit':'g','display_unit':'200g'},
                              {}, title)
    assert package is None and 'mixed_package_unresolved' in issues
    for ordinary_title in ['초콜릿 200g', '홍삼정 200g (쇼핑백 미포함)', '홍삼정 200g+쇼퍼백 별도']:
        ordinary, issues = _package({'package_quantity':200,'package_unit':'g','display_unit':'200g'},
                                   {}, ordinary_title)
        assert ordinary is not None and not issues and ordinary['package_quantity'] == 200


def test_original_hierarchy_is_loaded_with_later_conflict_held_in_offers(monkeypatch):
    from core import reviewed_content_quantities as registry
    from core.reviewed_source_evidence import (package_comparison_reason, package_publication_reason,
                                              original_quantity_assertion)
    from core.catalog_matching import _match_key_for_row, _normalized_source_reason
    from services.initial_taxonomy import taxonomy_categories
    from services.catalog_bundle import apply_bundle
    from services.normalized_mart3 import publish_matched_offer_observations
    from storage.models import NormalizedCanonicalProduct, NormalizedOfferEvent
    review = deepcopy(next(r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') == '670430'))
    raw = {'name':review['title'], 'source':'costco', 'source_record_key':'670430',
           'brand':'__no_brand__', 'sale_price':34790, 'crawled_at':'2026-08-31T01:51:55.448754Z',
           'source_url':review['required_source']['source_urls'][0]}
    for fields in (review['required_source']['source_fields'], review['quantity_fields']):
        for field, value in fields.items():
            raw[field] = str(value[0] or '')+value[1] if isinstance(value,list) else value
    batches = [ingestion(42,[raw],mart='costco')]
    row = normalize_pending_ingestions(batches)[0]
    # The isolated fixture has index0; the production record retains its actual
    # index92/hash. Bind the fixture's complete raw observation, never its price.
    review['original_quantity_assertion']['raw_payload_hashes'] = {row['raw_record_id']:row['raw_payload_sha256']}
    monkeypatch.setattr(registry,'REVIEWED_EXPLICIT_LISTING_PACKAGES',
                        (*[r for r in registry.REVIEWED_EXPLICIT_LISTING_PACKAGES
                           if r.get('source_record_key') != '670430'],review))
    original = deepcopy(raw)
    leaf = review['category_id']
    bundle = build_initial_catalog_bundle(batches,categories=taxonomy_categories({leaf}),
        assignments={('costco','670430'):assignment(unified_category_id=leaf)},run_id='original-hierarchy')
    assert raw == original and not bundle['unresolved']
    variant, offer, rule = bundle['variants'][0],bundle['offers'][0],bundle['match_rules'][0]
    assert [variant[k] for k in ('package_quantity','package_unit','bundle_count')] == [180,'ml',20]
    assert original_quantity_assertion(variant)['nested_sold_counts'] == [5,4]
    assert package_comparison_reason(variant) == 'contents_identity_and_allocation_unverified'
    assert package_publication_reason(variant) == 'later_source_quantity_conflict_unresolved'
    assert not bundle['products'][0]['is_active']
    assert offer['price'] == 34790 and offer['promotion_type'] == 'final_price'
    assert offer['offer_state'] == 'pending_review' and offer['standard_unit_price'] is None
    assert bundle['review_issues'][0]['reason'] == 'source_version_pending_review'
    variants = {variant['public_variant_id']:{**variant,'source_listings':bundle['source_listings']}}
    changed = {**raw,'sale_price':35990,'unit_price_display':'100ml당999원'}
    assert _match_key_for_row(changed)[0] == rule['match_key']
    assert _normalized_source_reason(changed,rule['match_key'],rule,variants) is None
    for mutation in ({'name':raw['name'].replace('x 4','x 5')}, {'source_record_key':'other'},
                     {'source_url':raw['source_url']+'-other'}, {'pack_qty':181},
                     {'pack_unit':'개'}, {'category':'다른 문맥'}, {'unit_price_basis':'개당100원'}):
        assert _normalized_source_reason({**raw,**mutation},rule['match_key'],rule,variants) is not None
    other = build_initial_catalog_bundle([ingestion(43,[raw],mart='costco')],
        categories=taxonomy_categories({leaf}),assignments={('costco','670430'):assignment(unified_category_id=leaf)},
        run_id='unreviewed-observation')
    assert other['unresolved'][0]['reasons'] == ['source_declared_package_quantity_contradiction']
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session,bundle,'source-history').ok
        wrong = deepcopy(bundle);wrong['offers'][0]['offer_state'] = 'active'
        assert not validate_bundle(session,wrong,'wrong-publication').ok
        apply_bundle(session,bundle,'source-history',user='test-manager')
        # An independently visible product is still not authority to clear this
        # source-version conflict on a new price-only observation.
        session.get(NormalizedCanonicalProduct,variant['public_product_id']).is_active = True
        session.flush()
        incoming = {**changed,'public_product_id':variant['public_product_id'],
                    'public_variant_id':variant['public_variant_id']}
        placement = publish_matched_offer_observations(session,[incoming])[0]
        event = session.get(NormalizedOfferEvent,placement['public_offer_event_id'])
        assert event.price == 35990 and event.offer_state == 'pending_review'
        assert event.standard_unit_price is None and event.promotion_type == 'final_price'
        assert 'later_source_quantity_conflict_unresolved' in event.audit_provenance['review_reasons']
        assert not publish_matched_offer_observations(session,[incoming])[0]['inserted']
        assert not validate_bundle(session,{**bundle,'products':[],'variants':[],'source_listings':[],
            'offers':wrong['offers']},'existing-wrong-publication').ok
        stripped = deepcopy(bundle)
        stripped['variants'][0]['attributes'].pop('explicit_listing_quantity_review')
        assert not validate_bundle(session,stripped,'stripped-original-history').ok
    engine.dispose()


def test_actual_homeplus_cup_builder_and_formal_listing_guard_preserve_product_identity():
    from services.initial_taxonomy import taxonomy_categories
    from services.catalog_bundle import apply_bundle
    from storage.models import NormalizedProductVariant
    # Pinned original Homeplus127938195 ingestion71:21 payload, selected only.
    raw = {'attributes': {'brand': '농심',
                'canon_hash': '0ec3999c003d0d1bc52b8d8dc056c84c0a519ba6',
                'canonical_url': 'https://mfront.homeplus.co.kr/item?itemNo=127938195&storeType=HYPER',
                'category_hint': '컵라면',
                'docId': 'H127938195N37O0',
                'external_seller': False,
                'legacy_detail_url': 'https://mfront.homeplus.co.kr/p/%EB%86%8D%EC%8B%AC-%EC%8B%A0%EB%9D%BC%EB%A9%B4-%EB%B8%94%EB%9E%99-%EC%82%AC%EB%B0%9C%EB%A9%B4101G-6%EC%9E%85/127938195',
                'mart_native_category_id': '16',
                'mart_native_category_path': '라면/즉석식품/통조림 > 라면/수입면류 > 컵라면 > 컵라면',
                'mart_native_code': '127938195',
                'normalized_name': '농심 신라면 블랙 사발면101G 6입',
                'permanent_url': 'https://mfront.homeplus.co.kr/item?itemNo=127938195&storeType=HYPER',
                'raw_name': '농심 신라면 블랙 사발면101G 6입',
                'source': 'homeplus',
                'source_name': 'homeplus',
                'source_record_key': '127938195',
                'source_url': 'https://mfront.homeplus.co.kr/item?itemNo=127938195&storeType=HYPER',
                'storeType': 'HYPER',
                'unit_price_basis_raw': '100G',
                'unit_price_displayed': 1584.0},
 'brand': '__no_brand__',
 'category': '컵라면',
 'crawled_at': '2026-09-02T22:39:30.951033',
 'detail_url': 'https://mfront.homeplus.co.kr/item?itemNo=127938195&storeType=HYPER',
 'discount_percent': None,
 'display_unit': '101g',
 'event_name': '홈플러스 할인',
 'image_url': '',
 'match_key': '__no_brand__|농심 신라면 블랙 사발면101g 6입||101g',
 'matching_miss_reason': 'key_not_found',
 'matching_status': 'miss',
 'name': '농심 신라면 블랙 사발면101G 6입',
 'normalized_name': '농심 신라면 블랙 사발면101G 6입',
 'original_price': None,
 'package_quantity': 101.0,
 'package_unit': 'g',
 'price_per_100g': 9504.95,
 'promo_label': None,
 'promo_type': None,
 'sale_price': 9600,
 'source': 'homeplus',
 'store': '홈플러스',
 'unit': '101g',
 'unit_price_display': '',
 'valid_from': None,
 'valid_until': None}
    leaf = 'food.meals.noodles.cup_ramen'
    bundle = build_initial_catalog_bundle([ingestion(71, [raw])], categories=taxonomy_categories([leaf]),
        assignments={('homeplus', '127938195'): assignment(unified_category_id=leaf)}, run_id='actual-cup-count-boundary')
    assert bundle['unresolved'] == []
    assert bundle['products'][0]['public_product_id'] == 'prod-2c82a5b3e1a444ca26a637ec4c52655c'
    variant = bundle['variants'][0]
    assert variant['public_variant_id'] == 'var-8cebdd1b260e36b2555700cb0eb26a2e'
    assert variant['public_variant_id'] != 'var-68327a307c884a3f8ae63e3e64151a9e'
    assert (variant['package_quantity'], variant['package_unit'], variant['bundle_count']) == (101, 'g', 6)
    assert bundle['offers'][0]['price'] == raw['sale_price'] == 9600
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert validate_bundle(session, bundle, 'correct-six').ok
        bad = deepcopy(bundle)
        bad['variants'][0]['bundle_count'] = 1
        assert not validate_bundle(session, bad, 'wrong-single').ok
        apply_bundle(session, bundle, 'correct-six', user='test')
        stored = session.get(NormalizedProductVariant, variant['public_variant_id'])
        stored.bundle_count = 1
        session.flush()
        listing_only = deepcopy(bundle)
        for field in ('categories', 'products', 'variants', 'offers', 'match_rules', 'keywords'):
            listing_only[field] = []
        assert not validate_bundle(session, listing_only, 'listing-only-stale').ok
        stored.bundle_count = 6
        session.flush()
        assert validate_bundle(session, listing_only, 'listing-only-six').ok
    engine.dispose()
