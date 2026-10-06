from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.db_admin_readonly import bulk_lookup_match_statuses, reset_db_admin_engine
from services.matching_enrichment import (
    _match_key_for_row, _source_package, enrich_items_with_matching_entries, lookup_row_match_statuses,
)


@pytest.mark.parametrize('row,expected', [
    ({'name':'국내산 양념 돼지갈비 2.9kg x 2팩','pack_qty':2,'pack_unit':'팩'}, (2900,'g',2)),
    ({'name':'호주산 냉장 안창살 로스 500g x 4팩','pack_qty':4,'pack_unit':'팩'}, (500,'g',4)),
    ({'name':'농심 신라면 120g x 30개','pack_qty':30,'pack_unit':'개'}, (120, 'g', 30)),
    ({'name':'썬키스트 견과 ３종세트 25g x 60봉','pack_qty':60,'pack_unit':'봉'}, (25, 'g', 60)),
    ({'name':'두꺼운 종이컵 260ml / 40p','package_quantity':260,'package_unit':'ml','display_unit':'260ml'}, (40, 'ea', 1)),
    ({'name':'종이컵180ml*50개','package_quantity':180,'package_unit':'ml','display_unit':'180ml×50'}, (50, 'ea', 1)),
    ({'name':'키친타올 200매*6롤','package_quantity':6,'package_unit':'롤','display_unit':'6롤'}, (200, '매', 6)),
    ({'name':'고무장갑 2켤레(중)'}, (2, '켤레', 1)),
])
def test_reviewed_recollection_uses_same_content_container_and_roll_quantities_as_staging(row, expected):
    assert _source_package(row) == (expected, None)


@pytest.mark.parametrize('title,count',[('한스팜 유기농계란15ea x 2',30),('한스팜 자연을품은동물복지란20ea x 2',40),('풀무원 동물복지란 60 구 (30ea x 2)',60)])
def test_runtime_recovers_only_reviewed_count_only_eggs(title,count):
    assert _source_package({'name':title})==((count,'ea',1),None)
    assert _source_package({'name':title,'pack_qty':1,'pack_unit':'kg'})[1] is not None


def test_runtime_recovers_reviewed_yogurt_measurement_and_rejects_change():
    row={'name':'윌 오리지날 150mlX5개','package_quantity':5,'package_unit':'개','display_unit':'5개'}
    assert _source_package(row)==((150,'ml',5),None)
    assert _source_package({**row,'display_unit':'4개'})[1] is not None


@pytest.mark.parametrize('row,expected', [
    ({'name': '종이호일30cm*40m', 'unit': '1m 당 120원', 'display_unit': '1m 당 120원',
      'attributes': {'unit_price_display': '1m 당 120원'}}, (40, 'm', 1)),
    ({'name': '(온)크리넥스 밤부케어 25m * 12개입', 'package_quantity': 12,
      'package_unit': '개입', 'unit': '12개입', 'display_unit': '12개입'}, (25, 'm', 12)),
    ({'name': '깨끗한나라 촉앤감 로얄화이트화장지40m x 30롤 x 2팩',
      'pack_qty': 2, 'pack_unit': '팩'}, (40, 'm', 60)),
    ({'name': 'simplus 쿠킹호일 30CM*30M(대)', 'unit': '30M'}, (30, 'm', 1)),
])
def test_reviewed_linear_content_recollects_original_source_boundaries(row, expected):
    assert _source_package(row) == (expected, None)
    assert _source_package({**row, 'bundle_count': 999})[1] is not None
    assert _source_package({**row, 'package_quantity': 999, 'package_unit': 'm'})[1] is not None


@pytest.mark.parametrize('changes', [
    {'package_quantity':50,'package_unit':'개'},
    {'attributes':{'package_quantity':2,'package_unit':'개'}},
    {'bundle_count':2}, {'display_unit':'20개'},
])
def test_count_recovery_does_not_hide_stale_or_conflicting_structured_values(changes):
    row = {'name':'농심 신라면 120g x 30개','pack_qty':30,'pack_unit':'개', **changes}
    assert _source_package(row)[1] is not None


@pytest.mark.parametrize('display', ['180ml×20', '200ml×50', '40개'])
def test_cup_capacity_recovery_rejects_independently_changed_display_quantity(display):
    row = {'name':'종이컵180ml*50개','package_quantity':180,'package_unit':'ml','display_unit':display}
    assert _source_package(row)[1] is not None


def test_cosmetic_fullwidth_identity_is_shared_but_real_name_or_pack_changes_are_not():
    from core.match_key import build_match_key
    assert build_match_key('ＣＪ','견과 ３종',1,'Ｌ') == build_match_key('CJ','견과 3종',1000,'ml')
    assert build_match_key(None,'견과 ３종',3,'개') != build_match_key(None,'견과 4종',3,'개')


@pytest.mark.parametrize('title,quantity,count', [
    ('설성목장한우사골 곰탕 스틱 14g x 10 x 4',14,40),
    ('카누 라떼 커피 13.5g x 50스틱 x 2박스',13.5,100),
    ('봉하쌀영양찰밥230g x 6 x 2',230,12),
    ('티젠 레몬 콤부차 5g x 30ct x 2',5,60),
    ('맥심 화이트 골드 커피믹스 11.7g x 210T x 2',11.7,420),
    ('녹차원 보이차 0.9g x 100티백 x 3',.9,300),
    ('코카콜라제로제로190ml x 30can x 2',190,60),
])
def test_reviewed_typed_chain_recollects_complete_variant_not_first_factor(title,quantity,count):
    # Source-bound drink mixtures are covered by the actual context/export test below.
    unit='ml' if 'ml' in title else 'g'
    row={'name':title,'pack_qty':quantity,'pack_unit':unit}
    assert _source_package(row)==((quantity,unit,count),None)
    assert _source_package({**row,'bundle_count':2})[1] is not None


def test_recollection_keeps_typed_wholesale_chain_held_for_review():
    row={'name':'카누 미니 다크 로스트 커피 0.9g x 150스틱 x 6박스','pack_qty':.9,'pack_unit':'g'}
    assert _source_package(row)[1] is not None


@pytest.mark.parametrize('title,changes,expected', [
    ('정관장 홍삼 원력 50ml x 30 x5', {}, (50, 'ml', 150)),
    ('정관장 홍삼 원력 50ml x 30 x5', {'bundle_count': 30}, None),
    ('정관장 홍삼 원력 50ml x 30 x5', {'attributes': {'package_quantity': 100, 'package_unit': 'ml'}}, None),
    ('정관장 홍삼 원력 50ml x 30 x5상자', {}, None),
])
def test_complete_measured_chain_uses_shared_staging_runtime_contract(title, changes, expected):
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules
    row = {'name': title, 'pack_qty': 50, 'pack_unit': 'ml', **changes}
    package, issues = normalize_catalog_package(row, changes.get('attributes', {}), title)
    actual, reason = _source_package(row)
    if expected:
        assert uses_reviewed_quantity_rules(title)
        assert not issues and actual == expected and reason is None
        assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == expected
        assert package['package_quantity'] * package['bundle_count'] == 7500
    else:
        assert actual is None and reason is not None
        if 'attributes' in changes:
            # Runtime independently checks structured layers before shared normalization.
            assert reason == 'normalized_variant_conflict'
        else:
            assert issues


def test_reviewed_stock_total_recovers_same_per_sachet_boundary_as_staging():
    row={'name':'멸치 해산물 다시팩 300G(15Gx20입)','package_quantity':300,'package_unit':'g'}
    assert _source_package(row)==((15,'g',20),None)
    assert _source_package({**row,'package_quantity':250})[1] is not None


def test_reviewed_grain_drink_total_recollects_only_exact_evidence():
    from core.catalog_quantity import uses_reviewed_quantity_rules
    title = '유기농 단백질 블랙미숫가루 400g (20gx20입)'
    row = {'name': title, 'source': 'emart', 'category': '쌀/잡곡/견과',
           'package_quantity': 400, 'package_unit': 'g', 'display_unit': '400g'}
    assert uses_reviewed_quantity_rules(title)
    assert _source_package(row) == ((20, 'g', 20), None)
    for changed in ({'package_quantity': 500}, {'bundle_count': 10},
                    {'display_unit': '500g'}, {'attributes': {'package_quantity': 500, 'package_unit': 'g'}}):
        assert _source_package({**row, **changed})[1] is not None
    for changed_title in (title + ' 혼합세트', '유기농 단백질 블랙미숫가루 400g'):
        assert not uses_reviewed_quantity_rules(changed_title)
        assert _source_package({**row, 'name': changed_title})[0] != (20, 'g', 20)


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE matching_entries (
              id INTEGER PRIMARY KEY, match_key TEXT UNIQUE, canonical_product_id TEXT,
              category_id TEXT, keyword_ids JSON, confidence REAL, source TEXT,
              brand TEXT, name_core TEXT, pack_qty REAL, pack_unit TEXT,
              public_product_id TEXT, public_variant_id TEXT
            )
        """))
        connection.execute(text("""
            CREATE TABLE products (
              id INTEGER PRIMARY KEY, name TEXT, display_name TEXT, brand TEXT,
              name_core TEXT, pack_qty REAL, pack_unit TEXT, category_id TEXT,
              unified_category_id TEXT, is_active BOOLEAN
            )
        """))
        connection.execute(text("""
            CREATE TABLE normalized_canonical_products (
              public_product_id TEXT PRIMARY KEY, canonical_name TEXT, brand TEXT,
              unified_category_id TEXT, is_active BOOLEAN
            )
        """))
        connection.execute(text("""
            CREATE TABLE normalized_product_variants (
              public_variant_id TEXT PRIMARY KEY, public_product_id TEXT,
              package_quantity REAL, package_unit TEXT, bundle_count INTEGER,
              is_active BOOLEAN
            )
        """))
    return engine


@pytest.mark.parametrize('mutation', [
    'price_only', 'source_quantity', 'source_count', 'source_identity', 'source_presentation',
    'target_equal_total', 'target_missing', 'target_malformed', 'target_dimension', 'target_scalar', 'hidden_unitName',
    'target_basis', 'source_basis', 'source_dimension',
])
@pytest.mark.parametrize('sheet', [False, True])
def test_component_runtime_and_export_compare_composition_not_aggregate(tmp_path, mutation, sheet):
    import json
    from core.catalog_quantity import normalize_catalog_package
    title = '[기획세트] 퍼실 세탁세제 2.5L+1.5L(파워젤)'
    if sheet:
        title = '메르슈 건티슈 150매 x 3팩 + 15매 x 10 x 2팩'
    original = _source_row(name=title, normalized_name=title, package_quantity=1500,
                           package_unit='ml', unit='1500ml', display_unit='1500ml',
                           sale_price=10000, unit_price_display='100ml당 250원')
    if sheet:
        original.update(package_quantity=2, package_unit='팩', bundle_count=10, unit='2팩×10', display_unit='2팩×10', unit_price_display='10매당250원')
    package, issues = normalize_catalog_package(original, {}, title)
    assert not issues
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=1, unit='세트', count=1)
    target_attrs = deepcopy(package['attributes'])
    row = deepcopy(original)
    row.update(sale_price=12000, unit_price_display='100ml당 300원', match_key=key)
    if sheet:
        row['unit_price_display'] = '10매당300원'
    if mutation in {'source_quantity', 'source_count', 'source_identity', 'source_presentation'}:
        components = deepcopy(target_attrs['package_components'])
        field, value = {
            'source_quantity': ('quantity', 1600), 'source_count': ('count', 2),
            'source_identity': ('identity', '다른 세제'), 'source_presentation': ('presentation', '리필'),
        }[mutation]
        components[0][field] = value
        row['attributes']['package_components'] = components
    if mutation == 'source_basis':
        row['attributes']['component_basis'] = 'aggregate_only'
    if mutation == 'source_dimension':
        row['attributes']['standard_unit'] = 'g'
    if mutation == 'hidden_unitName':
        row['attributes']['unitName'] = 'g'
        row['attributes']['pack_qty'] = 1500
    if mutation == 'target_equal_total':
        component = deepcopy(target_attrs['package_components'][0])
        component.update(quantity=250 if sheet else 2000, count=3 if sheet else 2)
        target_attrs['package_components'] = [component]
    elif mutation == 'target_missing':
        target_attrs = {}
    elif mutation == 'target_basis':
        target_attrs['component_basis'] = 'aggregate_only'
    target_json = '{broken' if mutation == 'target_malformed' else json.dumps(target_attrs)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs, standard_unit=:unit'),
                           {'attrs': target_json, 'unit': 'g' if mutation == 'target_dimension' else ('매' if sheet else 'ml')})
        if mutation == 'target_scalar':
            connection.execute(text("UPDATE normalized_product_variants SET package_quantity=4000, package_unit='ml'"))
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title': title})
    before = deepcopy(row)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        expected = 'hit' if mutation == 'price_only' else 'normalized_variant_conflict'
        assert result['matching_status'] == ('hit' if mutation == 'price_only' else 'miss')
        if mutation != 'price_only':
            assert result['matching_miss_reason'] == expected
        else:
            assert (result['public_product_id'], result['public_variant_id']) == ('prod-choco', 'var-120')
            assert result['sale_price'] == 12000 and result['unit_price_display'] == ('10매당300원' if sheet else '100ml당 300원')
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [expected]
        assert row == before
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('title,quantity,unit,count,approximate', [
    ('Dorly 한입 전병 1,000g', 1000, 'g', 1, False),
    ('찹쌀 김부각 세트(5개입) x 5', 5, '개', 5, False),
    ('가지 2봉 (7개x 2봉)', 7, '개', 2, False),
    ('까망 애플수박 1.5kg미만', 1500, 'g', 1, True),
    ('스카치 방충망 보수테이프 롤타입 5X50cm', 0.5, 'm', 1, False),
    ('농심스낵모음 1,080g / 36개입', 1080, 'g', 1, False),
    ('오리온 스낵 모음 780g / 26개입', 780, 'g', 1, False),
    ('디아토스타통밀 토스트 레귤러 1,800g', 1800, 'g', 1, False),
    ('신라면5입600g(120gx5입)', 120, 'g', 5, False),
])
def test_residual177_runtime_export_exact_repairs_and_approximate_mass(tmp_path, title, quantity, unit, count, approximate):
    source_q, source_u = (1500, 'g') if approximate else {
        'Dorly 한입 전병 1,000g': (0, 'g'),
        '찹쌀 김부각 세트(5개입) x 5': (5, '개'),
        '가지 2봉 (7개x 2봉)': (2, '봉'),
        '스카치 방충망 보수테이프 롤타입 5X50cm': (None, ''),
        '농심스낵모음 1,080g / 36개입': (36, '개'),
        '오리온 스낵 모음 780g / 26개입': (26, '개'),
        '디아토스타통밀 토스트 레귤러 1,800g': (800, 'g'),
        '신라면5입600g(120gx5입)': (600, 'g'),
    }[title]
    original = _source_row(name=title, normalized_name=title, package_quantity=None, package_unit='',
                           pack_qty=source_q, pack_unit=source_u, unit=f'{source_q}{source_u}', display_unit=f'{source_q}{source_u}')
    if source_q is None:
        original.update(unit='', display_unit='')
    if unit == 'g' and not approximate:
        original['unit_price_display'] = '10G당 183원'
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=quantity, unit=unit, count=count)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title': title})
    reset_db_admin_engine(engine)
    try:
        refreshed = {**original, 'sale_price': 19990, 'match_key': key}
        if unit == 'g' and not approximate:
            refreshed['unit_price_display'] = '10G당 200원'
        cases = [(refreshed, 'normalized_variant_conflict' if approximate else 'hit')]
        if not approximate:
            cases += [({**refreshed, 'packQty': 999, 'packUnit': source_u}, 'normalized_variant_conflict'),
                      ({**refreshed, 'attributes': {**refreshed['attributes'], 'pack_quantity': -1, 'pack_unit': source_u}},
                       'normalized_unit_unresolved' if title == '신라면5입600g(120gx5입)' else 'normalized_variant_conflict'),
                      ({**refreshed, 'name': title + ' 변경'}, 'normalized_source_name_conflict')]
        for row, expected in cases:
            result = enrich_items_with_matching_entries([deepcopy(row)])[0]
            assert result['matching_status'] == ('hit' if expected == 'hit' else 'miss')
            with Session(engine) as session:
                assert lookup_row_match_statuses(session, [(row, key)]) == [expected]
    finally:
        reset_db_admin_engine()


def test_normalized_match_hit_preserves_source_title_and_adds_ssot_refs(tmp_path):
    from core.match_key import build_match_key

    engine = _engine(tmp_path)
    key = build_match_key("남양", "초코에몽", 120, "ml")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코에몽', '남양', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_product_variants VALUES ('var-120', 'prod-choco', 120, 'ml', 1, 1)"
        ))
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.95, 'human', '남양', '초코에몽', 120, 'ml', 'prod-choco', 'var-120')"
        ), {"key": key})
    reset_db_admin_engine(engine)
    try:
        row = {"brand": "남양", "name": "초코에몽", "pack_qty": 120, "pack_unit": "ml",
               "matching_catalog_offer_state": "pending_review", "matching_catalog_offer_available": False}
        enriched = enrich_items_with_matching_entries([row])[0]
        assert enriched["matching_status"] == "hit"
        assert enriched["source_title"] == "초코에몽"
        assert enriched["public_product_id"] == "prod-choco"
        assert enriched["public_variant_id"] == "var-120"
        assert enriched["unified_category_id"] == "food.dairy.milk.choco"
        assert "matching_catalog_offer_state" not in enriched
        assert "matching_catalog_offer_available" not in enriched
    finally:
        reset_db_admin_engine()


def _seed_source_scoped_match(engine, row, *, quantity=120, unit="ml", count=24, variant_product="prod-choco"):
    key, _ = _match_key_for_row(deepcopy(row))
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코우유', 'CJ', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_product_variants VALUES ('var-120', :product, :qty, :unit, :count, 1)"
        ), {"product": variant_product, "qty": quantity, "unit": unit, "count": count})
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.95, 'external-ai', 'CJ', '초코우유', 120, 'ml', 'prod-choco', 'var-120')"
        ), {"key": key})
    return key


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'parent_key', 'sibling_key',
                                      'parent_url', 'sibling_url', 'bare', 'quantity'])
def test_native_child_sku_recollection_and_export_preserve_exact_source_identity(tmp_path, mutation):
    import json
    from core.reviewed_source_evidence import source_review_evidence
    engine = _engine(tmp_path)
    original = _source_row(source='costco', canonical_url='https://www.costco.co.kr/p/780235-FP',
                           sale_price=12000, attributes={'source_record_key': '780235-FP',
                                                        'category_path': ['음료']})
    key = _seed_source_scoped_match(engine, original)
    review = dict(source_name='costco', source_record_key='780235-FP', **source_review_evidence(original))
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'),
                           {'attrs': json.dumps({'source_evidence_reviews': [review]})})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','costco','780235-FP',:title,1)"),
                           {'title': original['name']})
    row = deepcopy(original)
    if mutation == 'price_only': row['sale_price'] += 1000
    elif mutation == 'parent_key': row['attributes']['source_record_key'] = '780235'
    elif mutation == 'sibling_key': row['attributes']['source_record_key'] = '780235-GA'
    elif mutation == 'parent_url': row['canonical_url'] = 'https://www.costco.co.kr/p/780235'
    elif mutation == 'sibling_url': row['canonical_url'] = 'https://www.costco.co.kr/p/780235-GA'
    elif mutation == 'bare': row.pop('canonical_url'); row['attributes'] = {}
    elif mutation == 'quantity': row['package_quantity'] = 240
    valid = mutation in {'original', 'price_only'}
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert (result['matching_status'] == 'hit') == valid
        assert (result.get('public_variant_id') == 'var-120') == valid
        with Session(engine) as session:
            assert (lookup_row_match_statuses(session, [(row, key)])[0] == 'hit') == valid
        assert original['attributes']['source_record_key'] == '780235-FP'
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['unknown_price', 'price_absent', 'price_only', 'tracking',
    'wrong_url_native', 'duplicate_native', 'foreign_url', 'wrong_store', 'layer_store_conflict'])
def test_ordinary_homeplus_recollection_and_export_reject_url_context_contradictions(tmp_path, mutation):
    original = _source_row(canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123&storeType=HYPER',
                           sale_price=None)
    original['attributes']['storeType'] = 'HYPER'
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,:url,1)"),
                           {'title': original['name'], 'url': original['canonical_url']})
    row = deepcopy(original)
    if mutation == 'price_absent': row.pop('sale_price')
    elif mutation == 'price_only': row['sale_price'] = 12345.5
    elif mutation == 'tracking': row['canonical_url'] += '&campaign=other'
    elif mutation == 'wrong_url_native': row['canonical_url'] = row['canonical_url'].replace('itemNo=123', 'itemNo=456')
    elif mutation == 'duplicate_native': row['canonical_url'] += '&itemNo=456'
    elif mutation == 'foreign_url': row['canonical_url'] = row['canonical_url'].replace('mfront.homeplus.co.kr', 'unrelated.test')
    elif mutation == 'wrong_store': row['canonical_url'] = row['canonical_url'].replace('HYPER', 'EXPRESS')
    elif mutation == 'layer_store_conflict': row['attributes']['storeType'] = 'EXP'
    valid = mutation in {'unknown_price', 'price_absent', 'price_only', 'tracking'}
    reset_db_admin_engine(engine)
    try:
        enriched = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert (enriched['matching_status'] == 'hit') == valid
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [
                'hit' if valid else 'normalized_source_listing_unavailable']
        if valid:
            assert enriched['public_variant_id'] == 'var-120'
    finally:
        reset_db_admin_engine()


def _source_row(**changes):
    # Small deterministic shape of the persisted DiscountItem rows: the match
    # key uses the full raw name/unit, structured quantity is a separate field,
    # and old crawls retained ×N only in display_unit rather than bundle_count.
    row = {
        "name": "초코우유 120ml×24", "normalized_name": "초코우유 120ml×24",
        "brand": "__no_brand__", "unit": "120ml×24", "display_unit": "120ml×24",
        "package_quantity": 120, "package_unit": "ml", "source": "homeplus",
        "attributes": {"source_record_key": "123", "brand": "CJ"},
    }
    row.update(changes)
    return row


@pytest.mark.parametrize('case', ['original', 'price_only', 'unknown_price', 'wrong_url', 'bare',
                                 'inactive_variant', 'active_offer', 'unreviewed', 'missing_offer',
                                 'malformed_attributes', 'missing_source_review', 'malformed_source_review',
                                 'legacy_scalar', 'legacy_scalar_wrong_url', 'legacy_scalar_bare', 'missing_listing_url'])
def test_reviewed_pending_offer_retains_identity_without_offer_approval(tmp_path, case):
    import json
    from core.reviewed_source_evidence import source_review_evidence
    engine = _engine(tmp_path)
    original = _source_row(canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123',
                           category='검수 음료', sale_price=2500)
    _seed_source_scoped_match(engine, original)
    attributes = {'identity_basis': 'source_scoped', 'classification_attribute_evidence': [
        {'source_name': 'homeplus', 'source_record_key': '123', 'raw_record_ids': ['fixture:1'],
         'classification_reason': ['supported_by_reviewed_source_shelf_and_form']}]}
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_canonical_products ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_canonical_products SET is_active=0, attributes=:attrs'),
                           {'attrs': json.dumps(None if case == 'malformed_attributes' else
                                                {} if case == 'unreviewed' else attributes)})
        review = dict(source_name='homeplus', source_record_key='123', **source_review_evidence(original))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'),
                           {'attrs': json.dumps({'specification_basis':'source_structured_and_explicit_text'} if case.startswith('legacy_scalar') else {} if case == 'missing_source_review' else
                                                {'source_evidence_reviews': [None] if case == 'malformed_source_review' else [review]})})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_source_listing_id TEXT, public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('listing-1','var-120','homeplus','123',:title,:url,1)"),
                           {'title': original['name'], 'url': None if case == 'missing_listing_url' else original['canonical_url']})
        connection.execute(text('CREATE TABLE normalized_offer_events (public_source_listing_id TEXT, offer_state TEXT)'))
        if case != 'missing_offer':
            connection.execute(text("INSERT INTO normalized_offer_events VALUES ('listing-1',:state)"),
                               {'state': 'active' if case == 'active_offer' else 'pending_review'})
        if case == 'inactive_variant':
            connection.execute(text('UPDATE normalized_product_variants SET is_active=0'))
    row = deepcopy(original)
    if case == 'price_only': row['sale_price'] = 2600
    elif case == 'unknown_price': row.pop('sale_price')
    elif case in {'wrong_url', 'legacy_scalar_wrong_url'}: row['canonical_url'] += '4'
    elif case in {'bare', 'legacy_scalar_bare'}: row.pop('canonical_url'); row['attributes'] = {}
    reset_db_admin_engine(engine)
    try:
        key, _ = _match_key_for_row(row)
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        valid = case in {'original', 'price_only', 'unknown_price', 'legacy_scalar'}
        assert (result['matching_status'] == 'hit') == valid
        with Session(engine) as session:
            assert (lookup_row_match_statuses(session, [(row, key)])[0] == 'hit') == valid
            assert session.execute(text('SELECT is_active FROM normalized_canonical_products')).scalar() == 0
            assert session.execute(text('SELECT COUNT(*) FROM normalized_offer_events WHERE offer_state=\'active\'')).scalar() == (case == 'active_offer')
        if valid:
            assert result['matching_catalog_offer_state'] == 'pending_review'
            assert result['matching_catalog_offer_available'] is False
            assert result['public_product_id'] == 'prod-choco'
        else:
            assert not result.get('public_product_id')
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'capacity', 'new_count', 'bundle', 'basis', 'url', 'context', 'forged_singleton', 'missing_url', 'missing_quantity', 'malformed_quantity', 'bare'])
@pytest.mark.parametrize('generic_role', [False, True, 'model', 'declared_bundle', 'vessel', 'vessel_count', 'paper', 'textile', 'storage', 'shredder'])
def test_nonmeasured_listing_recollection_export_without_singleton_or_unitprice(tmp_path, monkeypatch, mutation, generic_role):
    import json
    from core import reviewed_content_quantities
    from core.catalog_quantity import normalize_catalog_package
    from core.reviewed_source_evidence import listing_quantity_evidence, source_review_evidence
    original = _source_row(name='검수된 두유제조기 800ml MX-22', normalized_name='검수된 두유제조기 800ml MX-22',
                          package_quantity=800, package_unit='ml', unit='800ml', display_unit='800ml',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123', sale_price=12000)
    original['attributes']['category_path'] = ['가전']
    review = {'title':original['name'], 'category_id':'appliances.kitchen.soy_maker.standard',
              'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original)}
    if generic_role == 'model':
        original.update(name='세탁기 + 건조기 세트명[WF25DG8250BW2T]', normalized_name='세탁기 + 건조기 세트명[WF25DG8250BW2T]',
                        package_quantity=2, package_unit='T', unit='2T', display_unit='2T')
        review = {'title':original['name'], 'category_id':'appliances.laundry.set.washer_dryer',
                  'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original)}
    if generic_role in {'vessel', 'vessel_count'}:
        original['name'] = original['normalized_name'] = '검수 보온서버 800ml' + (' 2PK' if generic_role == 'vessel_count' else '')
        review = {'title':original['name'], 'category_id':'household.kitchen.coffee.server',
                  'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original)}
    if generic_role in {'paper','textile','storage','shredder'}:
        title,quantity,unit,leaf = {
            'paper':('A4 복사지 80g 2500매',80,'g','stationery.office.paper.copy'),
            'textile':('타월 130g 5P',130,'g','household.bath.textiles.towel'),
            'storage':('금고 40L',40000,'ml','household.security.storage.safe'),
            'shredder':('문서세단기 12C 19L',19000,'ml','office.equipment.shredder.standard'),
        }[generic_role]
        original.update(name=title,normalized_name=title,package_quantity=quantity,package_unit=unit,
                        unit=f'{quantity}{unit}',display_unit=f'{quantity}{unit}')
        review={'title':title,'category_id':leaf,'required_source':source_review_evidence(original),
                'quantity_fields':listing_quantity_evidence(original)}
    if generic_role == 'declared_bundle':
        original['name'] = original['normalized_name'] = '1+1 검수된 물병 800ml'
        original['attributes']['promo_label'] = '1+1'
        review.update(title=original['name'], declared_package_bundle_count=2, required_promotion_label='1+1')
    generic_device = generic_role in (True, 'model', 'vessel', 'vessel_count', 'paper', 'textile', 'storage', 'shredder')
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_NONMEASURED_LISTINGS', () if generic_device else (review,))
    package, issues = normalize_catalog_package(original, {}, original['name'], category_id=review['category_id'] if generic_device else None)
    expected_count = {'vessel_count':2,'paper':2500,'textile':5}.get(generic_role)
    expected_unit = '매' if generic_role == 'paper' else '개' if expected_count else None
    assert not issues and package['package_quantity'] == expected_count
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=expected_count,
                                   unit=expected_unit, count=package['bundle_count'])
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(package['attributes'])})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title':original['name']})
        if mutation == 'forged_singleton':
            connection.execute(text("UPDATE normalized_product_variants SET package_quantity=1,package_unit='개'"))
    row = deepcopy(original)
    if mutation == 'price_only': row['sale_price'] = 13000
    elif mutation == 'capacity': row['package_quantity'] = 900
    elif mutation == 'new_count': row.update(packQty=2,packUnit='개')
    elif mutation == 'bundle': row['bundle_count'] = 2
    elif mutation == 'basis': row['attributes']['unit_price_display'] = '100ml당500원'
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'context': row['attributes']['category_path'] = ['식품']
    elif mutation == 'missing_url': row.pop('canonical_url')
    elif mutation == 'missing_quantity': row.pop('package_quantity')
    elif mutation == 'malformed_quantity': row['package_quantity'] = {'invalid':'amount'}
    elif mutation == 'bare': row = {'name':original['name'], 'normalized_name':original['name']}
    reset_db_admin_engine(engine)
    try:
        expected = 'hit' if mutation in {'original','price_only'} else 'normalized_variant_conflict'
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if expected == 'hit' else 'miss')
        if expected != 'hit' and mutation not in {'missing_url','missing_quantity','malformed_quantity','bare'}:
            assert result['matching_miss_reason'] == ('key_not_found' if mutation == 'new_count' else expected)
        with Session(engine) as session:
            exported = lookup_row_match_statuses(session, [(row,key)])
            if mutation in {'missing_url','missing_quantity','malformed_quantity','bare'}:
                assert exported[0] != 'hit'
            else:
                assert exported == [expected]
        if generic_role == 'declared_bundle' and mutation == 'original':
            for promo in (None, '2+1'):
                changed = deepcopy(original)
                changed['attributes']['promo_label'] = promo
                result = enrich_items_with_matching_entries([changed])[0]
                assert result['matching_status'] == 'miss'
                with Session(engine) as session:
                    assert lookup_row_match_statuses(session, [(changed, key)])[0] != 'hit'
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('quote,expected', [('1개당700원','hit'),('1개당800원','hit'),('1마리당800원','normalized_variant_conflict')])
@pytest.mark.parametrize('image_binding', ['unrequired', 'required', 'image', 'missing_image',
                                         'malformed_image', 'url', 'context', 'bare'])
def test_declared_sold_count_keeps_dosage_and_quote_amount_out_of_identity(tmp_path, monkeypatch, quote, expected, image_binding):
    import json
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import listing_quantity_evidence, source_review_evidence
    from core.catalog_quantity import normalize_catalog_package
    original = _source_row(name='검수된 오메가3 700mg x 120ct', normalized_name='검수된 오메가3 700mg x 120ct',
                          package_quantity=None, package_unit=None, unit='', display_unit='',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123', unit_price_text='1개당700원',
                          category='검수 영양제', image_url='https://example.test/package-label.jpg')
    review = {'title':original['name'], 'category_id':'food.supplements.functional.omega3',
              'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original),
              'normalized':[120,'개',1], 'independent_specifications':{'dosage_mg':700}}
    if image_binding != 'unrequired':
        review['required_source_image_url'] = original['image_url']
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_EXPLICIT_LISTING_PACKAGES',(review,))
    package, issues = normalize_catalog_package(original, {}, original['name'])
    assert not issues and package['package_quantity']==120 and package['package_unit']=='개'
    assert package['standard_unit'] is None
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=120, unit='개', count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(package['attributes'])})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title':original['name']})
    row = {**original,'sale_price':15000,'unit_price_text':quote}
    if image_binding == 'image': row['image_url'] += '?other-package'
    elif image_binding == 'missing_image': row.pop('image_url')
    elif image_binding == 'malformed_image': row['image_url'] = {'not': 'a URL'}
    elif image_binding == 'url': row['canonical_url'] += '4'
    elif image_binding == 'context': row['category'] = '다른 문맥'
    elif image_binding == 'bare': row.pop('canonical_url'); row.pop('category'); row.pop('image_url')
    if image_binding not in {'unrequired', 'required'}:
        expected = 'normalized_variant_conflict'
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if expected == 'hit' else 'miss')
        if expected != 'hit': assert result['matching_miss_reason']==expected
        with Session(engine) as session:
            assert lookup_row_match_statuses(session,[(row,key)])==[expected]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original','price_only','range','quantity','basis','url','forged_upper_bound','forged_dimension'])
@pytest.mark.parametrize('interval_unit', ['개', '송이'])
def test_count_interval_recollection_and_export_preserve_uncertainty(tmp_path, monkeypatch, mutation, interval_unit):
    import json
    from core import reviewed_content_quantities
    from core.catalog_quantity import normalize_catalog_package
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    original = _source_row(name='검수된 복숭아 4~7입 팩', normalized_name='검수된 복숭아 4~7입 팩',
                          package_quantity=7, package_unit='입', unit='7입', display_unit='7입',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123',
                          unit_price_text='1개당700원')
    if interval_unit == '송이':
        original.update(name='검수된 포도 3kg 내외(4~7송이)', normalized_name='검수된 포도 3kg 내외(4~7송이)',
                        package_quantity=3, package_unit='kg', unit='3kg', display_unit='3kg',
                        unit_price_text='100g당700원')
    review = {'title':original['name'], 'category_id':'food.produce.fruit.peach',
              'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original),
              'count_interval':[4,7,interval_unit]}
    if interval_unit == '송이':
        review['identity_basis'] = 'declared_interval_unit_v2'
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_COUNT_INTERVAL_LISTINGS',(review,))
    package, issues = normalize_catalog_package(original, {}, original['name'])
    assert not issues and package['package_quantity'] is None
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=None, unit=interval_unit, count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(package['attributes'])})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,1)"), {'title':original['name']})
        if mutation == 'forged_upper_bound':
            connection.execute(text('UPDATE normalized_product_variants SET package_quantity=7'))
        elif mutation == 'forged_dimension':
            connection.execute(text('UPDATE normalized_product_variants SET package_unit=:unit'),
                               {'unit': '개' if interval_unit == '송이' else '송이'})
    row = deepcopy(original)
    if mutation == 'price_only': row.update(sale_price=18000, unit_price_text='100g당800원' if interval_unit == '송이' else '1개당800원')
    elif mutation == 'range': row['name'] = '검수된 복숭아 4~8입 팩'
    elif mutation == 'quantity': row['package_quantity'] = 8
    elif mutation == 'basis': row['unit_price_text'] = '1마리당800원'
    elif mutation == 'url': row['canonical_url'] += '4'
    reset_db_admin_engine(engine)
    try:
        valid = mutation in {'original','price_only'}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if valid else 'miss')
        with Session(engine) as session:
            status = lookup_row_match_statuses(session,[(row,key)])[0]
            assert (status == 'hit') == valid
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original','primary','price_only','unreviewed_title','quantity','url','native','bare','missing_quantity','forged_history'])
@pytest.mark.parametrize('physical', [False, True])
def test_exact_listing_title_history_recollection_and_export(tmp_path, monkeypatch, mutation, physical):
    import json
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    original = _source_row(name='검수브랜드 소스 350g', normalized_name='검수브랜드 소스 350g',
                          package_quantity=350, package_unit='g', unit='350g', display_unit='350g',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123')
    alias = {**original,'name':'[쿠폰] 검수브랜드 소스 350g','normalized_name':'[쿠폰] 검수브랜드 소스 350g'}
    if physical:
        original.update(name='검수 타월 1P 바이올렛200g', normalized_name='검수 타월 1P 바이올렛200g',
                        package_quantity=200, unit='200g', display_unit='200g')
        alias = {**original, 'name':'검수 타월 1P 바이올렛 200g', 'normalized_name':'검수 타월 1P 바이올렛 200g'}
    review = {'source_name':'homeplus','source_record_key':'123','category_id':'food.seasonings.sauce.pasta',
              'aliases':[{'title':r['name'],'required_source':source_review_evidence(r),
                          'quantity_fields':listing_quantity_evidence(r)} for r in (original,alias)]}
    if physical:
        review['category_id'] = 'household.bath.textiles.towel'
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_LISTING_TITLE_HISTORIES',(review,))
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original if mutation == 'primary' else alias,
                                   quantity=1 if physical else 350, unit='개' if physical else 'g', count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        attrs = {} if physical else {'source_title_history':deepcopy(review)}
        if physical:
            from core.catalog_quantity import normalize_catalog_package
            package, issues = normalize_catalog_package(original, {}, original['name'], category_id=review['category_id'])
            assert not issues and package['package_quantity'] == 1
            attrs.update(package['attributes'])
        if mutation == 'forged_history':
            attrs['source_title_history'] = deepcopy(review)
            attrs['source_title_history']['aliases'].append({'title':'다른맛'})
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(attrs)})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,1)"), {'title':original['name']})
    row = deepcopy(original if mutation == 'primary' else alias)
    if mutation == 'price_only': row['sale_price'] = 18000
    elif mutation == 'unreviewed_title': row['name'] = '다른맛 소스 350g'
    elif mutation == 'quantity': row['package_quantity'] = 400
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'native': row['attributes']['source_record_key'] = '124'
    elif mutation == 'bare': row = {'name':alias['name'], 'sale_price':18000}
    elif mutation == 'missing_quantity': row.pop('package_quantity')
    reset_db_admin_engine(engine)
    try:
        valid = mutation in {'original','primary','price_only'}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if valid else 'miss')
        with Session(engine) as session:
            status = lookup_row_match_statuses(session,[(row,key)])[0]
            assert (status == 'hit') == valid
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'held_title', 'held_quantity',
                                    'quantity', 'url', 'context', 'basis', 'bare', 'malformed_source'])
def test_registered_factual_hold_recollection_and_export(tmp_path, monkeypatch, mutation):
    import json
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    original = _source_row(name='검수 딸기우유 350ml', normalized_name='검수 딸기우유 350ml',
                           package_quantity=350, package_unit='ml', unit='350ml', display_unit='350ml',
                           canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123',
                           category='검수 우유', unit_price_text='100ml당500원')
    title_gap = {**original, 'name': '검수 우유 350ml'}
    quantity_gap = {**original, 'package_quantity': 1, 'package_unit': '개',
                    'unit': '1개', 'display_unit': '1개'}
    records = tuple({'title': row['name'], 'category_id': 'food.dairy.milk.flavored',
                     'required_source': source_review_evidence(row),
                     'quantity_fields': listing_quantity_evidence(row),
                     'status': status, 'hold_reason': 'necessary_fact_missing' if status == 'hold' else None}
                    for row, status in ((original, 'eligible'), (title_gap, 'hold'), (quantity_gap, 'hold')))
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY', records)
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=350, unit='ml', count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        attrs = {'source_evidence_reviews': [dict(source_name='homeplus', source_record_key='123',
                                                 **source_review_evidence(original))]}
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs': json.dumps(attrs)})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,1)"), {'title': original['name']})
    row = deepcopy(original)
    if mutation == 'price_only': row['sale_price'] = 18000; row['unit_price_text'] = '100ml당700원'
    elif mutation == 'held_title': row = deepcopy(title_gap)
    elif mutation == 'held_quantity': row = deepcopy(quantity_gap)
    elif mutation == 'quantity': row['package_quantity'] = 400
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'context': row['category'] = '다른 문맥'
    elif mutation == 'basis': row['unit_price_text'] = '1마리당500원'
    elif mutation == 'bare': row.pop('canonical_url'); row.pop('category')
    elif mutation == 'malformed_source': row['attributes'] = '{broken'
    reset_db_admin_engine(engine)
    try:
        valid = mutation in {'original', 'price_only'}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if valid else 'miss')
        with Session(engine) as session:
            assert (lookup_row_match_statuses(session, [(row, key)])[0] == 'hit') == valid
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original','price_only','equal_total','identity','count','quantity','url','forged_target',
                                      'physical_count', 'unmeasured_consumable', 'bare', 'context', 'basis', 'malformed_source',
                                      'image', 'missing_image', 'malformed_image',
                                      'collection', 'missing_collection', 'malformed_collection', 'held_review',
                                      'price_absent', 'native', 'compatible_basis', 'missing_basis', 'invalid_basis'])
@pytest.mark.parametrize('physical_presentation', ['basket', 'feeding_bottle', 'gift_wrap', 'glass', 'shopping_bag', 'declared_measured'])
def test_source_scoped_component_vector_recollection_and_export(tmp_path, monkeypatch, mutation, physical_presentation):
    import json
    from core import reviewed_content_quantities
    from core.catalog_quantity import normalize_catalog_package
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    original = _source_row(name='검수국 A 100g x 2 + 검수국 B 300g', normalized_name='검수국 A 100g x 2 + 검수국 B 300g',
                          package_quantity=100, package_unit='g', unit='100g', display_unit='100g',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123',unit_price_text='100g당500원',
                          category='검수 구성세트', image_url='https://example.test/declared-package.jpg')
    components = [dict(identity='A',quantity=100,unit='g',count=2,amount_scope='per_counted_component',presentation=None),
                  dict(identity='B',quantity=300,unit='g',count=None,amount_scope='declared_component_total',presentation=None),
                  dict(identity='바스켓',quantity=None,unit=None,count=None,
                       amount_scope='declared_nonmeasured_physical',presentation=physical_presentation)]
    original['attributes']['collection'] = '검수제조사'
    review = {'title':original['name'],'category_id':'food.meals.prepared.soup_stew',
              'required_source':source_review_evidence(original),'quantity_fields':listing_quantity_evidence(original),
              'components':components, 'required_source_image_url':original['image_url'],
              'required_source_collection': original['attributes']['collection']}
    if physical_presentation == 'declared_measured':
        components[0].update(quantity=200, count=None, amount_scope='declared_component_total')
        components.pop()
        review.update(measurement_role='heterogeneous_declared_component_contents',
                      source_name='homeplus', source_record_key='123')
    if physical_presentation in {'glass', 'shopping_bag'}:
        review.update(measurement_role='measured_food_with_nonmeasured_physical_companion',
                      source_name='homeplus',source_record_key='123')
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_SOURCE_COMPONENT_LISTINGS',(review,))
    package, issues = normalize_catalog_package(original, {}, original['name']); assert not issues
    if mutation == 'held_review':
        review['eligibility_hold_reason'] = 'source_recipe_measured_quantity_contradiction'
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=1, unit='세트', count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        attrs = deepcopy(package['attributes'])
        if mutation == 'forged_target': attrs['source_components'][1]['count'] = 1
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(attrs)})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,1)"), {'title':original['name']})
    row = deepcopy(original)
    if mutation == 'price_only': row.update(sale_price=18000,unit_price_text='100g당650원')
    elif mutation == 'price_absent': row['sale_price'] = None
    elif mutation == 'native': row['attributes']['source_record_key'] = '456'
    elif mutation == 'compatible_basis': row['unit_price_text'] = '10g당65원'
    elif mutation == 'missing_basis': row.pop('unit_price_text')
    elif mutation == 'invalid_basis': row['unit_price_text'] = '0g당65원'
    elif mutation in {'equal_total','identity','count'}:
        changed = deepcopy(components)
        if mutation == 'equal_total': changed[0]['quantity'] += 1; changed[1]['quantity'] -= 2
        elif mutation == 'identity': changed[1]['identity'] = 'C'
        else: changed[1].update(count=1,amount_scope='per_counted_component')
        row['attributes']['source_components'] = changed
    elif mutation == 'quantity': row['package_quantity'] = 200
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'bare': row.pop('canonical_url')
    elif mutation == 'context': row['category'] = '다른 구성세트'
    elif mutation == 'basis': row['unit_price_text'] = '1마리당500원'
    elif mutation == 'malformed_source': row['canonical_url'] = ['https://mfront.homeplus.co.kr/item?itemNo=123']
    elif mutation == 'image': row['image_url'] += '-other-package'
    elif mutation == 'missing_image': row.pop('image_url')
    elif mutation == 'malformed_image': row['image_url'] = [original['image_url']]
    elif mutation == 'collection': row['attributes']['collection'] = '다른제조사'
    elif mutation == 'missing_collection': row['attributes'].pop('collection')
    elif mutation == 'malformed_collection': row['attributes']['collection'] = [original['attributes']['collection']]
    elif mutation in {'physical_count', 'unmeasured_consumable'}:
        changed = deepcopy(components)
        if mutation == 'physical_count': changed[-1]['count'] = 1
        else: changed[1].update(quantity=None,unit=None,amount_scope='declared_nonmeasured_physical',presentation='soup')
        row['attributes']['source_components'] = changed
    reset_db_admin_engine(engine)
    try:
        valid = (mutation in {'original','price_only','price_absent'}
                 or physical_presentation in {'glass', 'shopping_bag', 'declared_measured'} and mutation in {'compatible_basis','missing_basis'})
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if valid else 'miss')
        with Session(engine) as session:
            status = lookup_row_match_statuses(session,[(row,key)])[0]
            assert (status == 'hit') == valid
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'missing_url', 'wrong_url', 'extra_url', 'missing_context', 'wrong_context', 'malformed_review',
                                      'approved_second_context', 'second_context_price_only', 'crossed_url', 'crossed_context', 'duplicate_context', 'malformed_companion'])
def test_source_evidence_bound_recollection_and_export(tmp_path, mutation):
    from core.reviewed_source_evidence import source_review_evidence
    import json
    engine = _engine(tmp_path)
    original = _source_row(canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123', sale_price=12000)
    original['attributes']['category_path'] = ['우유/유제품', '우유']
    key = _seed_source_scoped_match(engine, original)
    review = {'source_name': 'homeplus', 'source_record_key': '123', **source_review_evidence(original)}
    second = deepcopy(original)
    second['canonical_url'] = 'https://front.homeplus.co.kr/item?itemNo=123'
    second['attributes']['category_path'] = ['베스트']
    reviews = [review]
    if mutation in {'approved_second_context', 'second_context_price_only', 'crossed_url', 'crossed_context', 'duplicate_context', 'malformed_companion'}:
        reviews.append({'source_name': 'homeplus', 'source_record_key': '123', **source_review_evidence(second)})
    if mutation == 'duplicate_context':
        reviews.append(deepcopy(review))
    elif mutation == 'malformed_companion':
        reviews[-1]['source_fields'] = []
    if mutation == 'malformed_review':
        review['source_fields'] = []
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'),
                           {'attrs': json.dumps({'source_evidence_reviews': reviews})})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title': original['name']})
    row = deepcopy(original)
    if mutation in {'approved_second_context', 'second_context_price_only'}:
        row = deepcopy(second)
        if mutation == 'second_context_price_only':
            row['sale_price'] += 1
    elif mutation == 'crossed_url':
        row['canonical_url'] = second['canonical_url']
    elif mutation == 'crossed_context':
        row['attributes']['category_path'] = second['attributes']['category_path']
    if mutation == 'price_only':
        row['sale_price'] = 13000
        row['attributes']['unit_price_display'] = '100ml 당 444원'
    elif mutation == 'missing_url':
        row.pop('canonical_url')
    elif mutation == 'wrong_url':
        row['canonical_url'] += '4'
    elif mutation == 'extra_url':
        row['attributes']['detail_url'] = 'https://mfront.homeplus.co.kr/item?itemNo=999'
    elif mutation == 'missing_context':
        row['attributes'].pop('category_path')
    elif mutation == 'wrong_context':
        row['attributes']['category_path'] = ['생활용품']
    reset_db_admin_engine(engine)
    try:
        before = deepcopy(row)
        expected = 'hit' if mutation in {'original', 'price_only', 'approved_second_context', 'second_context_price_only'} else 'normalized_source_evidence_conflict'
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result['matching_status'] == ('hit' if expected == 'hit' else 'miss')
        if expected != 'hit':
            assert result['matching_miss_reason'] == expected
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [expected]
        assert row == before
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("changes", "reason"), [
    ({}, None),
    ({"package_quantity": 140}, "normalized_variant_conflict"),
    ({"bundle_count": 12}, "normalized_variant_conflict"),
    ({"package_unit": "g"}, "normalized_variant_conflict"),
    ({"package_quantity": None}, "normalized_unit_unresolved"),
    ({"package_unit": None}, "normalized_unit_unresolved"),
    ({"package_quantity": float("nan")}, "normalized_unit_unresolved"),
    ({"package_quantity": "1e1000"}, "normalized_unit_unresolved"),
    ({"package_quantity": True}, "normalized_unit_unresolved"),
    ({"package_unit": "unknown"}, "normalized_unit_unresolved"),
    ({"bundle_count": 1.5}, "normalized_unit_unresolved"),
    ({"name": "새 초코우유 120ml×24"}, "normalized_source_name_conflict"),
    ({"source_title": "변경된 초코우유 120ml×24"}, "normalized_source_name_conflict"),
    ({"name": "새 초코우유 120ml×24", "normalized_name": "새 초코우유 120ml×24"}, "key_not_found"),
])
def test_runtime_and_export_revalidate_each_source_row(tmp_path, changes, reason):
    engine = _engine(tmp_path)
    original = _source_row()
    key = _seed_source_scoped_match(engine, original)
    reset_db_admin_engine(engine)
    try:
        candidate = _source_row(**changes)
        result = enrich_items_with_matching_entries([deepcopy(candidate)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert bulk_lookup_match_statuses(session, [key])[key] == "normalized_source_verification_required"
            statuses = lookup_row_match_statuses(session, [(candidate, result["match_key"])])
            assert statuses == [reason or "hit"]
    finally:
        reset_db_admin_engine()


def test_active_variant_cannot_belong_to_another_product(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row()
    key = _seed_source_scoped_match(engine, row, variant_product="different-product")
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == "miss"
        assert result["matching_miss_reason"] == "normalized_variant_product_conflict"
        with Session(engine) as session:
            assert bulk_lookup_match_statuses(session, [key])[key] == "normalized_variant_product_conflict"
            assert lookup_row_match_statuses(session, [(row, key)]) == ["normalized_variant_product_conflict"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("quantity", "unit", "display"), [(1, "L", "1L"), (1000, "ml", "1000ml")])
def test_equivalent_explicit_volume_units_are_safe(tmp_path, quantity, unit, display):
    engine = _engine(tmp_path)
    row = _source_row(name="우유", normalized_name="우유", unit=display, display_unit=display, package_quantity=quantity, package_unit=unit)
    _seed_source_scoped_match(engine, row, quantity=1000, unit="ml", count=1)
    reset_db_admin_engine(engine)
    try:
        assert enrich_items_with_matching_entries([row])[0]["matching_status"] == "hit"
    finally:
        reset_db_admin_engine()


def test_mixed_refill_quantity_cannot_hide_behind_last_parsed_measure(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row(name="샴푸 본품500ml+리필450ml", normalized_name="샴푸 본품500ml+리필450ml", unit="450ml", display_unit="450ml", package_quantity=450)
    _seed_source_scoped_match(engine, row, quantity=450, count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_conflict"
    finally:
        reset_db_admin_engine()


def test_key_only_rows_and_missing_variant_cannot_be_normalized_hits(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row()
    key = _seed_source_scoped_match(engine, row)
    reset_db_admin_engine(engine)
    try:
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [({"match_key": key}, key)]) == ["normalized_source_name_unresolved"]
        with engine.begin() as connection:
            connection.execute(text("UPDATE matching_entries SET public_variant_id=NULL"))
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_unavailable"
    finally:
        reset_db_admin_engine()


def test_lookup_failure_clears_stale_hit_metadata(tmp_path, monkeypatch):
    import services.matching_enrichment as module

    engine = _engine(tmp_path)
    reset_db_admin_engine(engine)
    def unavailable(*args):
        raise RuntimeError("isolated failure")
    monkeypatch.setattr(module, "_load_matching_entries", unavailable)
    row = _source_row(matching_status="hit", public_product_id="stale-product", public_variant_id="stale-variant")
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_status"] == "miss"
        assert result["matching_miss_reason"] == "matching_lookup_unavailable"
        assert "public_product_id" not in result
        assert "public_variant_id" not in result
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("changes", "active", "reason"), [
    ({}, 1, None),
    ({"name": "[밀키트] 변경된 상품 120ml×24"}, 1, "normalized_source_name_conflict"),
    ({"attributes": {"source_record_key": "new-listing"}}, 1, "normalized_source_listing_unavailable"),
    ({}, 0, "normalized_source_listing_unavailable"),
])
def test_original_listing_title_is_the_exact_name_contract(tmp_path, changes, active, reason):
    engine = _engine(tmp_path)
    original = _source_row(name="[밀키트] 초코우유 120ml×24")
    key = _seed_source_scoped_match(engine, original)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, :active)"
        ), {"title": original["name"], "active": active})
    reset_db_admin_engine(engine)
    try:
        row = {**original, **changes}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [reason or "hit"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize("changes,reason", [
    ({}, None),
    ({"unit_price_display": "50g 당 659원"}, "normalized_unit_unresolved"),
    ({"package_quantity": 121, "package_unit": "g"}, "normalized_variant_conflict"),
    ({"attributes": {"source_record_key": "123", "pack_qty": 121, "pack_unit": "g"}}, "normalized_variant_conflict"),
])
@pytest.mark.parametrize("title,quantity,unit,count,basis,first_price,next_price", [
    ("진라면 매운맛 (120GX5)", 120, "g", 5, "100g", 3950, 3960),
    ("종이호일30cm*40m", 40, "m", 1, "1m", 4380, 4800),
])
def test_reviewed_ramen_price_refresh_matches_original_listing(tmp_path, changes, reason, title, quantity, unit, count, basis, first_price, next_price):
    first_quote = f"{basis} 당 {110 if unit == 'm' else 658}원"
    next_quote = f"{basis} 당 {120 if unit == 'm' else 659}원"
    original = _source_row(name=title, normalized_name=title, package_quantity=None,
                           package_unit="", unit=first_quote, display_unit=first_quote,
                           unit_price_display=first_quote, sale_price=first_price)
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=quantity, unit=unit, count=count)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"
        ), {"title": title})
    reset_db_admin_engine(engine)
    try:
        row = {**original, "unit": next_quote, "display_unit": next_quote,
               "unit_price_display": next_quote, "sale_price": next_price, "match_key": key, **changes}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == ("key_not_found" if reason else None)
        assert result["sale_price"] == next_price
        assert result["unit_price_display"] == row["unit_price_display"]
        if not reason:
            assert (result["public_product_id"], result["public_variant_id"]) == ("prod-choco", "var-120")
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [reason or "hit"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("quantity", "unit", "expected"), [
    (14, "T", (14.0, "t", 1)),
    (100, "t", (100.0, "t", 1)),
    (500, "mg", (0.5, "g", 1)),
    (1, "kg", (1000.0, "g", 1)),
])
def test_catalog_count_t_is_not_ton_and_mass_conversions_stay_valid(quantity, unit, expected):
    row = {"name": "동일 상품", "package_quantity": quantity, "package_unit": unit}
    package, reason = _source_package(row)
    assert package == expected
    assert reason is None


def test_count_t_cannot_match_an_equally_numbered_mass_variant(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row(name="차 14T", normalized_name="차 14T", unit="14T", display_unit="14T", package_quantity=14, package_unit="T")
    _seed_source_scoped_match(engine, row, quantity=14000000, unit="g", count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_conflict"
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("title", "quantity", "unit", "reason"), [
    ("캡슐커피 60개입", 60, "ea", None),
    ("캡슐커피 60개입", 60, "개입", None),
    ("팬 2개입", 2, "ea", None),
    ("팬 2개입", 2, "개입", None),
    ("찹쌀 김부각 세트(5개입) x 5", 5, "ea", "normalized_variant_conflict"),
    ("네일메드코세정제콤보(용기3개+세정용분말250포)", 3, "ea", "normalized_variant_conflict"),
    ("커클랜드 시그니춰 종이타월 160매 x 12롤", 160, "매", "normalized_variant_conflict"),
    ("맑은청 찰토마토 7~10입/팩", 10, "입", "normalized_unit_unresolved"),
])
def test_count_aliases_do_not_hide_ambiguous_package_compositions(tmp_path, title, quantity, unit, reason):
    engine = _engine(tmp_path)
    # Costco uses pack_qty/pack_unit without package_quantity or display_unit.
    row = {"name": title, "pack_qty": quantity, "pack_unit": unit, "source": "costco"}
    key = _seed_source_scoped_match(engine, row, quantity=quantity, unit="ea" if unit == "개입" else unit, count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [reason or "hit"]
    finally:
        reset_db_admin_engine()


def test_runtime_keeps_explicit_weight_despite_variable_piece_count():
    package, reason = _source_package({
        "name": "토마토 1.5kg(5~6입)", "package_quantity": 1.5,
        "package_unit": "kg", "display_unit": "1.5kg",
    })
    assert package == (1500.0, "g", 1)
    assert reason is None


@pytest.mark.parametrize("count", [1, 2, 5])
def test_runtime_numeric_bundle_count_cannot_resolve_unparsed_multiplication(count):
    package, reason = _source_package({
        "name": "김부각 세트(5개입) x 5", "pack_qty": 5,
        "pack_unit": "ea", "bundle_count": count,
    })
    assert package is None
    assert reason == "normalized_variant_conflict"


@pytest.mark.parametrize("count", [None, 1, 3, 6])
@pytest.mark.parametrize("expression", ["400g x 3 x 2", "400g×3×2"])
def test_runtime_and_export_reject_a_partially_parsed_multiplier_chain(tmp_path, count, expression):
    engine = _engine(tmp_path)
    row = _source_row(name=f"다진마늘 {expression}", normalized_name=f"다진마늘 {expression}",
                      unit=expression, display_unit=expression, package_quantity=400,
                      package_unit="g", bundle_count=count)
    # Reproduce an old/externally supplied rule that incorrectly retained ×3.
    key = _seed_source_scoped_match(engine, row, quantity=400, unit="g", count=3)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == "miss"
        assert result["matching_miss_reason"] == "normalized_variant_conflict"
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == ["normalized_variant_conflict"]
    finally:
        reset_db_admin_engine()


def test_runtime_preserves_single_explicit_multiplier():
    package, reason = _source_package({"name": "다진마늘 400g×3", "package_quantity": 400, "package_unit": "g"})
    assert package == (400, "g", 3)
    assert reason is None


def test_low_confidence_matching_entry_remains_a_miss(tmp_path):
    from core.match_key import build_match_key

    engine = _engine(tmp_path)
    key = build_match_key("남양", "초코에몽", 120, "ml")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코에몽', '남양', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.79, 'external-ai', '남양', '초코에몽', 120, 'ml', 'prod-choco', NULL)"
        ), {"key": key})
    reset_db_admin_engine(engine)
    try:
        enriched = enrich_items_with_matching_entries([
            {"brand": "남양", "name": "초코에몽", "pack_qty": 120, "pack_unit": "ml"}
        ])[0]
        assert enriched["matching_status"] == "miss"
        assert enriched["matching_miss_reason"] == "low_confidence"
        assert "public_product_id" not in enriched
    finally:
        reset_db_admin_engine()


def test_runtime_export_approximate_count_pack_and_price_basis_boundaries(tmp_path):
    title = '과일 6입(1kg내외)'
    original = _source_row(name=title, normalized_name=title, package_quantity=1, package_unit='kg',
                           unit='1kg', display_unit='1kg', sale_price=3000, unit_price_display='1개당 500원')
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=6, unit='개', count=1)
    reset_db_admin_engine(engine)
    try:
        cases = [({**deepcopy(original), 'sale_price': 3600, 'unit_price_display': '1개당 600원'}, True),
                 ({**deepcopy(original), 'sale_price': 3600, 'unit_price_display': '100g당 600원'}, True)]
        for extra in (' 2팩', ' / 2봉'):
            changed_title = title + extra
            cases.append(({**deepcopy(original), 'name': changed_title, 'normalized_name': changed_title}, False))
        for basis in ('1마리당 500원', '1미당500원'):
            cases.append(({**deepcopy(original), 'unit_price_display': basis}, False))
            row = deepcopy(original)
            row['attributes']['attrs'] = {'unit_price_basis_raw': basis}
            cases.append((row, False))
        for row, expected_hit in cases:
            result = enrich_items_with_matching_entries([deepcopy(row)])[0]
            with Session(engine) as session:
                exported = lookup_row_match_statuses(session, [(row, key)])[0]
            assert (result['matching_status'] == 'hit') == expected_hit
            assert (exported == 'hit') == expected_hit
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'bounds', 'quantity', 'url', 'unreviewed_title', 'forged_target'])
def test_reviewed_title_history_keeps_interval_compatibility(tmp_path, monkeypatch, mutation):
    import json
    from core import reviewed_content_quantities
    from core.catalog_quantity import normalize_catalog_package
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    old = _source_row(name='검수사과 4~7입', normalized_name='검수사과 4~7입',
                      package_quantity=7, package_unit='입', unit='7입', display_unit='7입',
                      canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123',
                      unit_price_text='1개당700원')
    new = {**old, 'name':'검수 햇 사과 4~7입', 'normalized_name':'검수 햇 사과 4~7입'}
    records = [{'title':r['name'], 'category_id':'food.produce.fruit.apple',
                'required_source':source_review_evidence(r), 'quantity_fields':listing_quantity_evidence(r),
                'count_interval':[4,7,'개']} for r in (old,new)]
    if mutation == 'bounds': records[1]['count_interval'] = [4,8,'개']
    history = {'source_name':'homeplus', 'source_record_key':'123', 'category_id':'food.produce.fruit.apple',
               'aliases':[{'title':r['name'], 'required_source':source_review_evidence(r),
                           'quantity_fields':listing_quantity_evidence(r)} for r in (old,new)]}
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_COUNT_INTERVAL_LISTINGS',tuple(records))
    monkeypatch.setattr(reviewed_content_quantities,'REVIEWED_LISTING_TITLE_HISTORIES',(history,))
    package, issues = normalize_catalog_package(old, {}, old['name'])
    assert not issues and package['package_quantity'] is None
    package['attributes']['source_title_history'] = history
    if mutation == 'forged_target': package['attributes']['count_interval_listing'] = None
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, new, quantity=None, unit='개', count=1)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'), {'attrs':json.dumps(package['attributes'])})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','homeplus','123',:title,1)"), {'title':old['name']})
    row = deepcopy(new)
    if mutation == 'price_only': row.update(sale_price=18000, unit_price_text='1개당800원')
    elif mutation == 'quantity': row['package_quantity'] = 8
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'unreviewed_title': row['name'] = '다른품종 사과 4~7입'
    reset_db_admin_engine(engine)
    try:
        valid = mutation in {'original','price_only'}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert (result['matching_status'] == 'hit') == valid
        with Session(engine) as session:
            assert (lookup_row_match_statuses(session,[(row,key)])[0] == 'hit') == valid
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original','price_quote','quote_amount','mass_basis','count_basis',
                                      'bare','url','context','quantity','bundle','wrong_target_role'])
def test_linear_contents_recollection_and_export_require_bound_dimension(tmp_path, monkeypatch, mutation):
    import json
    from core import reviewed_content_quantities
    from core.reviewed_source_evidence import source_review_evidence, listing_quantity_evidence
    from core.catalog_quantity import normalize_catalog_package
    original = _source_row(name='검수된 선형 소모품', normalized_name='검수된 선형 소모품',
                          package_quantity=None, package_unit='', unit='', display_unit='',
                          canonical_url='https://mfront.homeplus.co.kr/item?itemNo=123', category='검수 위생', sale_price=6000)
    review = {'title':original['name'], 'category_id':'beauty.personal.oral.floss',
              'required_source':source_review_evidence(original), 'quantity_fields':listing_quantity_evidence(original),
              'normalized':[40,'m',3], 'measurement_role':'declared_linear_contents'}
    monkeypatch.setattr(reviewed_content_quantities, 'REVIEWED_EXPLICIT_LISTING_PACKAGES', (review,))
    package, issues = normalize_catalog_package(original, {}, original['name'])
    assert not issues
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=40, unit='m', count=3)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs,standard_unit=\'m\''),
                           {'attrs':json.dumps(package['attributes'] if mutation != 'wrong_target_role' else {})})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, 1)"), {'title':original['name']})
    row = deepcopy(original)
    if mutation == 'price_quote': row.update(sale_price=9000, unit_price_text='100m당7500원')
    elif mutation == 'quote_amount': row.update(sale_price=12000, unit_price_text='100m당10000원')
    elif mutation == 'mass_basis': row['unit_price_text'] = '100g당500원'
    elif mutation == 'count_basis': row['unit_price_text'] = '1개당500원'
    elif mutation == 'bare': row = {'name':original['name'], 'normalized_name':original['name']}
    elif mutation == 'url': row['canonical_url'] += '4'
    elif mutation == 'context': row['category'] = '가전'
    elif mutation == 'quantity': row.update(package_quantity=30, package_unit='cm')
    elif mutation == 'bundle': row['bundle_count'] = 4
    expected_hit = mutation in {'original','price_quote','quote_amount'}
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert (result['matching_status'] == 'hit') is expected_hit
        with Session(engine) as session:
            status = lookup_row_match_statuses(session, [(row,key)])[0]
            assert (status == 'hit') is expected_hit
    finally:
        reset_db_admin_engine()


def test_bound_quoted_display_money_changes_recollect_and_export_same_contents(tmp_path):
    import json
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from core.catalog_quantity import normalize_catalog_package
    from urllib.parse import urlparse, parse_qs
    reviews = [record for record in REVIEWED_EXPLICIT_LISTING_PACKAGES
               if any(isinstance(value, str) and '당' in value and '원' in value
                      for key, value in record['quantity_fields'].items() if key in {'unit', 'display_unit'})]
    assert reviews
    for index, review in enumerate(reviews):
        original = {'name': review['title'], 'brand': '__no_brand__', 'source': 'emart',
                    'detail_url': review['required_source']['source_urls'][0], 'sale_price': 10000, 'attributes': {}}
        native = parse_qs(urlparse(original['detail_url']).query)['itemId'][0]
        original['attributes']['source_record_key'] = native
        for fields in (review['required_source']['source_fields'], review['quantity_fields']):
            for field, value in fields.items():
                layer = original['attributes'] if field.startswith('attributes.') else original
                layer[field.rsplit('.', 1)[-1]] = str(value[0] or '') + value[1] + '당1,618원' if isinstance(value, list) else value
        package, issues = normalize_catalog_package(original, original['attributes'], review['title'])
        assert not issues
        directory = tmp_path / str(index); directory.mkdir()
        engine = _engine(directory)
        key = _seed_source_scoped_match(engine, original, quantity=review['normalized'][0], unit=review['normalized'][1], count=review['normalized'][2])
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
            connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
            connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs, standard_unit=:standard'), {'attrs': json.dumps(package['attributes']), 'standard':package['standard_unit']})
            connection.execute(text('UPDATE normalized_canonical_products SET canonical_name=:name, brand=NULL, unified_category_id=:leaf'), {'name': review['title'], 'leaf':review['category_id']})
            connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
            connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120','emart',:native,:title,1)"), {'native':native, 'title':review['title']})
        changed = deepcopy(original); basis = review['quantity_fields']['attributes.unit_price_display']
        quote = str(basis[0]) + basis[1] + '당2,222원'
        changed.update(unit=quote, display_unit=quote, sale_price=15000)
        changed['attributes']['unit_price_display'] = quote
        rejected = []
        for field, value in [('display_unit','100개당2,222원'), ('unit','100g당0원'), ('unit','100g당2,,222원'),
                             ('package_quantity',999), ('bundle_count',2), ('detail_url','https://retailer.example/wrong')]:
            row = deepcopy(changed); row[field] = value; rejected.append(row)
        bare = deepcopy(changed); bare.pop('detail_url'); bare['attributes'] = {}; rejected.append(bare)
        wrong_context = deepcopy(changed); wrong_context['category'] = '다른 문맥'; rejected.append(wrong_context)
        reset_db_admin_engine(engine)
        try:
            for row, valid in [(original,True),(changed,True),*((row,False) for row in rejected)]:
                actual = enrich_items_with_matching_entries([deepcopy(row)])[0]
                assert (actual['matching_status'] == 'hit') == valid, (review['title'], valid, row.get('unit'), actual.get('matching_miss_reason'))
                with Session(engine) as session:
                    assert (lookup_row_match_statuses(session,[(row,key)])[0] == 'hit') == valid
        finally:
            reset_db_admin_engine(); engine.dispose()


@pytest.mark.parametrize(("unit", "category", "rejected"), [
    ("인", "services.facility.camping.cabin_package", True),
    ("인분", "services.facility.camping.cabin_package", True),
    ("매", "services.facility.camping.cabin_package", False),
    ("인분", "food.meals.ready.rice", False),
])
def test_service_occupancy_recollection_export_uses_persisted_parent_leaf(tmp_path, unit, category, rejected):
    engine = _engine(tmp_path)
    row = {"name": f"시설 이용 {2}{unit}", "package_quantity": 2,
           "package_unit": unit, "display_unit": f"2{unit}", "sale_price": 12000,
           # Client categories cannot bypass canonical-purpose validation.
           "unified_category_id": "food.meals.ready.rice"}
    key = _seed_source_scoped_match(engine, row, quantity=2, unit=unit, count=1)
    with engine.begin() as connection:
        connection.execute(text("UPDATE normalized_canonical_products SET unified_category_id=:category"), {"category": category})
    reset_db_admin_engine(engine)
    try:
        for price in (12000, 13500):
            changed = {**row, "sale_price": price}
            result = enrich_items_with_matching_entries([changed])[0]
            assert result["matching_status"] == ("miss" if rejected else "hit")
            assert result["sale_price"] == price
            if rejected:
                assert result["matching_miss_reason"] == "normalized_variant_conflict"
            else:
                assert result["public_variant_id"] == "var-120"
            with Session(engine) as session:
                assert lookup_row_match_statuses(session, [(changed, key)]) == ["normalized_variant_conflict" if rejected else "hit"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize("field", ["package_unit", "pack_unit", "packUnit", "unitName", "unit"])
def test_service_source_unit_aliases_cannot_turn_occupancy_into_entitlement(field):
    row = {"name": "캐빈 시설 이용 2인", "package_quantity": 2, field: "인"}
    assert _source_package(row, category_id="services.facility.camping.cabin_package") == (None, "normalized_variant_conflict")


@pytest.mark.parametrize('native', ['696218', '604243', '114314981', '647352', '647353', '679666', '690859', '695905'])
def test_mixed_scalar_recollection_and_export_keep_price_independent_bound_identity(tmp_path,native):
    import json
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES, REVIEWED_SOURCE_COMPONENT_LISTINGS
    from core.catalog_quantity import normalize_catalog_package
    review = next(r for r in (*REVIEWED_EXPLICIT_LISTING_PACKAGES, *REVIEWED_SOURCE_COMPONENT_LISTINGS) if
                  (r.get('comparison_hold_reason') if native=='696218' else r.get('source_record_key')==native))
    original = {'name': review['title'], 'normalized_name': review['title'], 'source': 'costco',
                'brand': '__no_brand__', 'sale_price': 22990, 'pack_qty':230, 'pack_unit':'g',
                'category':'과자', 'mart_native_category_path':'과자',
                'canonical_url':review['required_source']['source_urls'][0],
                'unit_price_display':'10g', 'unit_price_basis':'10g',
                'unit_price_basis_raw':'10g', 'unit_price_text':'10g',
                'attributes':{'source_record_key':native}}
    if native!='696218':
        original={'name':review['title'],'normalized_name':review['title'],'source':review['source_name'],
                  'brand':'__no_brand__','sale_price':22990,'canonical_url':review['required_source']['source_urls'][0],
                  'attributes':{'source_record_key':native}}
        for field,value in {**review['required_source']['source_fields'],**review['quantity_fields']}.items():
            layer=original
            for part in field.split('.')[:-1]:layer=layer.setdefault(part,{})
            layer[field.split('.')[-1]]=f'{value[0] or ""}{value[1]}당 107원' if isinstance(value,list) else value
    package, issues = normalize_catalog_package(original, {}, original['name'])
    assert not issues
    quantity,unit,count = (package[k] for k in ('package_quantity','package_unit','bundle_count'))
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=quantity, unit=unit, count=count)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN standard_unit TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs, standard_unit=:unit'),
                           {'attrs':json.dumps(package['attributes']), 'unit':package['standard_unit']})
        connection.execute(text('UPDATE normalized_canonical_products SET canonical_name=:name, unified_category_id=:leaf'),
                           {'name':original['name'], 'leaf':review['category_id']})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120',:source,:native,:title,1)"),
                           {'source':original['source'],'native':native,'title':original['name']})
    reset_db_admin_engine(engine)
    try:
        cases=[({**deepcopy(original),'sale_price':25990},True),
               ({**deepcopy(original),'sale_price':25990,
                 **{field:'10'+('g' if unit=='세트' else unit)+'당280원' for field in ('unit_price_display','unit_price_basis','unit_price_basis_raw','unit_price_text')}},True),
               ({**deepcopy(original),'sale_price':None},True),
               ({**deepcopy(original),'pack_qty':250},False),
               ({**deepcopy(original),'canonical_url':'https://www.costco.co.kr/p/999'},False),
               ({'name':original['name'],'pack_qty':230,'pack_unit':'g'},False)]
        for row, hit in cases:
            result = enrich_items_with_matching_entries([deepcopy(row)])[0]
            with Session(engine) as session:
                exported = lookup_row_match_statuses(session, [(row,key)])[0]
            assert (result['matching_status']=='hit') == hit
            assert (exported=='hit') == hit
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('native', ['652658', '780235', '697186', '1000874160001', '695235', '655870', '627051', '574685', '1000631339827', '667537', '1000384981986', '696508', '1000045258266', '642459'])
def test_selectable_parent_never_exports_as_a_fixed_child_even_with_a_stored_match(tmp_path, native):
    import json
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    from core.catalog_quantity import normalize_catalog_package
    review = next(r for r in REVIEWED_EXPLICIT_LISTING_PACKAGES if r.get('source_record_key') == native)
    mart = review['source_name']
    original = {'name': review['title'], 'normalized_name': review['title'], 'source': mart,
                'brand': '__no_brand__', 'sale_price': 11990,
                'canonical_url': review['required_source']['source_urls'][0],
                'attributes': {'source_record_key': native}}
    for field, value in {**review['required_source']['source_fields'], **review['quantity_fields']}.items():
        layer = original
        for part in field.split('.')[:-1]:
            layer = layer.setdefault(part, {})
        layer[field.split('.')[-1]] = f'{value[0] or ""}{value[1]}당 107원' if isinstance(value, list) else value
    package, issues = normalize_catalog_package(original, {}, original['name'])
    assert not issues
    quantity, unit, count = review['normalized']
    assert [package['package_quantity'], package['package_unit'], package['bundle_count']] == [quantity, unit, count]
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=quantity, unit=unit, count=count)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'),
                           {'attrs': json.dumps(package['attributes'])})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)'))
        connection.execute(text("INSERT INTO normalized_source_listings VALUES ('var-120',:mart,:native,:title,1)"), {'mart': mart, 'native': native, 'title': original['name']})
    reset_db_admin_engine(engine)
    try:
        for changes in ({}, {'sale_price': 12990}, {'sale_price': None},
                        {'canonical_url': original['canonical_url'] + '-other-child'}, {'pack_qty': original.get('pack_qty', 1) + 1},
                        {'attributes': {'source_record_key': native+'-other-child'}}):
            row = {**deepcopy(original), **changes}
            result = enrich_items_with_matching_entries([deepcopy(row)])[0]
            with Session(engine) as session:
                exported = lookup_row_match_statuses(session, [(row, key)])[0]
            assert result['matching_status'] == 'miss' and exported != 'hit'
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize('mutation', ['original', 'price_only', 'price_absent', 'wrong_native', 'wrong_title', 'wrong_quantity', 'wrong_count', 'wrong_display'])
def test_actual_homeplus_cup_inner_measure_and_separate_count_match_and_export(tmp_path, mutation):
    import json
    # Exact pinned Homeplus127938195 ingestion71:21 source payload. Its 101g
    # declaration is inner cup content; literal6입 is sold count, not one cup.
    original = {'attributes': {'brand': '농심',
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
    public_product_id = 'prod-2c82a5b3e1a444ca26a637ec4c52655c'
    public_variant_id = 'var-8cebdd1b260e36b2555700cb0eb26a2e'
    engine = _engine(tmp_path)
    key = _seed_source_scoped_match(engine, original, quantity=101, unit='g', count=6)
    with engine.begin() as connection:
        connection.execute(text('UPDATE normalized_canonical_products SET public_product_id=:pid, canonical_name=:name, brand=:brand, unified_category_id=:leaf'),
                           {'pid':public_product_id, 'name':original['name'], 'brand':'농심', 'leaf':'food.meals.noodles.cup_ramen'})
        connection.execute(text('UPDATE normalized_product_variants SET public_product_id=:pid, public_variant_id=:vid'),
                           {'pid':public_product_id, 'vid':public_variant_id})
        connection.execute(text('UPDATE matching_entries SET public_product_id=:pid, public_variant_id=:vid'),
                           {'pid':public_product_id, 'vid':public_variant_id})
        connection.execute(text('ALTER TABLE normalized_product_variants ADD COLUMN attributes TEXT'))
        connection.execute(text('UPDATE normalized_product_variants SET attributes=:attrs'),
                           {'attrs':json.dumps({'specification_basis':'source_structured_and_explicit_text'})})
        connection.execute(text('CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT, is_active BOOLEAN)'))
        connection.execute(text('INSERT INTO normalized_source_listings VALUES (:vid, :source, :native, :title, :url, 1)'),
                           {'vid':public_variant_id, 'source':'homeplus', 'native':'127938195', 'title':original['name'], 'url':original['detail_url']})
    row = deepcopy(original)
    if mutation == 'price_only': row['sale_price'] = 12300
    elif mutation == 'price_absent': row['sale_price'] = None
    elif mutation == 'wrong_native': row['attributes']['source_record_key'] = '127938196'
    elif mutation == 'wrong_title': row['name'] = '농심 신라면 블랙 사발면101G 5입'
    elif mutation == 'wrong_quantity': row['package_quantity'] = 102
    elif mutation == 'wrong_count': row['bundle_count'] = 5
    elif mutation == 'wrong_display': row['display_unit'] = '101g×5'
    valid = mutation in {'original', 'price_only', 'price_absent'}
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert (result['matching_status'] == 'hit') == valid
        assert result['sale_price'] == row['sale_price']
        if valid:
            assert result['public_product_id'] == public_product_id
            assert result['public_variant_id'] == public_variant_id
            assert result.get('unified_category_id') == 'food.meals.noodles.cup_ramen'
        with Session(engine) as session:
            assert (lookup_row_match_statuses(session, [(row, key)])[0] == 'hit') == valid
    finally:
        reset_db_admin_engine()
        engine.dispose()
