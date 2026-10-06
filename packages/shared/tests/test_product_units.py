from __future__ import annotations

from core.product_units import normalize_unit_metadata, parse_package_quantity
import pytest
import re
from core.reviewed_content_quantities import REVIEWED_QUANTITY174_PACKAGES, REVIEWED_EXPLICIT_LISTING_PACKAGES


def test_reviewed_device_capacity_is_not_sold_content_or_an_assumed_count():
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules
    from core.reviewed_content_quantities import CAPACITY_NOT_CONTENT_TITLES
    for title in CAPACITY_NOT_CONTENT_TITLES - REVIEWED_QUANTITY174_PACKAGES.keys():
        measure=re.search(r'(\d+)\s*(ml|l)\b',title,re.I)
        capacity=float(measure[1]) * (1000 if measure[2].casefold() == 'l' else 1)
        source={'package_quantity':capacity,'package_unit':'ml','bundle_count':1}
        before=dict(source)
        assert uses_reviewed_quantity_rules(title)
        assert normalize_catalog_package(source,{},title)==(None,['unit_container_capacity_not_contents'])
        assert source==before
        assert normalize_catalog_package({'package_quantity':1,'package_unit':'개'},source,title)[1]
    for title in ('생수 500ml','텀블러 세척액 500ml'):
        package,issues=normalize_catalog_package({'package_quantity':500,'package_unit':'ml'}, {}, title)
        assert not issues and package['package_quantity']==500 and package['package_unit']=='ml'


@pytest.mark.parametrize('title,boundary', [
    (title, REVIEWED_QUANTITY174_PACKAGES[title]) for title in (
        '블랙포레 루트파워 쿨&딥클린 탈모완화샴푸 1,050ml',
        '백제 쌀국수 컵 58g x 6입 x 4',
        '커클랜드 시그니춰 주방용 랩 30cmx231Mx2',
    )
])
def test_quantity174_exact_source_boundary_rejects_hidden_mutations(title, boundary):
    import copy
    import unicodedata
    from core.catalog_quantity import normalize_catalog_package
    quantity, unit, bundle, source_quantity, source_unit = boundary
    exact_title = unicodedata.normalize('NFKC', title)
    source = {'pack_qty': source_quantity if source_quantity is not None else quantity,
              'pack_unit': source_unit if source_unit is not None else unit}
    before = copy.deepcopy(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == (quantity, unit, bundle)
    assert package['display_unit'] == exact_title
    assert source == before
    corrected = {'package_quantity': quantity, 'package_unit': unit, 'bundle_count': bundle}
    assert normalize_catalog_package(corrected, {}, title)[1] == []
    for payload, attrs in (
        ({**source, 'package_quantity': 999999, 'package_unit': source['pack_unit']}, {}),
        (source, {'pack_qty': 999999, 'pack_unit': unit}),
        ({**corrected, 'bundle_count': bundle + 1}, {}),
        (source, {'display_unit': '999999g'}),
        (source, {'unit': '999999개'}),
    ):
        assert normalize_catalog_package(payload, attrs, title)[1]
    mutated_package, mutated_issues = normalize_catalog_package(source, {}, title + ' 변경')
    assert mutated_issues or mutated_package != package


def test_quantity174_rice_vessel_explicit_count_retains_capacity_identity():
    from core.catalog_quantity import normalize_catalog_package
    title = '[쓱7클럽] 락앤락 티니핑 밥용기 320ML 3P 하츄핑'
    source = {'package_quantity': 320, 'package_unit': 'ml', 'bundle_count': 1}
    before = dict(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and package['package_quantity'] == 3 and package['package_unit'] == '개'
    assert package['display_unit'] == title and source == before
    for payload, attrs in (
        ({**source, 'package_quantity': 400}, {}),
        ({**source, 'pack_qty': 321, 'pack_unit': 'ml'}, {}),
        (source, {'package_quantity': 4, 'package_unit': '개'}),
        ({**source, 'bundle_count': 2}, {}),
    ):
        assert normalize_catalog_package(payload, attrs, title)[1]
    for changed_title in (title.replace('320', '400'), title.replace('3P', '4P')):
        package, issues = normalize_catalog_package(source, {}, changed_title)
        assert issues or package['package_unit'] != '개' or package['package_quantity'] != 3


@pytest.mark.parametrize('title,source,expected', [
    ('Dorly 한입 전병 1,000g', {'pack_qty': 0, 'pack_unit': 'g'}, (1000, 'g', 1)),
    ('찹쌀 김부각 세트(5개입) x 5', {'pack_qty': 5, 'pack_unit': '개'}, (5, '개', 5)),
    ('가지 2봉 (7개x 2봉)', {'pack_qty': 2, 'pack_unit': '봉'}, (7, '개', 2)),
    ('농심스낵모음 1,080g / 36개입', {'pack_qty': 36, 'pack_unit': '개', 'unit_price_basis': '10G', 'unit_price_display': '10G당 194원'}, (1080, 'g', 1)),
    ('오리온 스낵 모음 780g / 26개입', {'pack_qty': 26, 'pack_unit': '개', 'unit_price_basis': '10G', 'unit_price_display': '10G당 211원'}, (780, 'g', 1)),
    ('디아토스타통밀 토스트 레귤러 1,800g', {'pack_qty': 800, 'pack_unit': 'g', 'unit_price_basis': '10G', 'unit_price_display': '10G당 119원'}, (1800, 'g', 1)),
])
def test_residual177_exact_boundary_requires_all_source_evidence(title, source, expected):
    from copy import deepcopy
    from core.catalog_quantity import normalize_catalog_package
    before = deepcopy(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and source == before
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == expected
    assert package['display_unit'] == title
    corrected = {'package_quantity': expected[0], 'package_unit': expected[1], 'bundle_count': expected[2]}
    assert normalize_catalog_package(corrected, {}, title)[0] == package
    assert normalize_catalog_package({**corrected, 'package_quantity': expected[0] + 1}, {}, title)[1]
    if source.get('unit_price_display'):
        assert normalize_catalog_package({**source, 'unit_price_display': '10G당 999원'}, {}, title)[0] == package
    for payload, attrs in (
        ({}, {}), ({**source, 'packQty': 999, 'packUnit': source['pack_unit']}, {}),
        ({**source, 'bundle_count': 999}, {}), (source, {'attrs': {'pack_qty': -1, 'pack_unit': source['pack_unit']}}),
        ({**source, 'unitName': 'ml'}, {}), (source, {'unit': '999개'}),
        (source, {'unit_price_basis_raw': '10ml'}), (source, {'unit_price_unit': 'ml'}),
        ({**source, 'package_quantity': float('nan'), 'package_unit': source['pack_unit']}, {}),
    ):
        assert normalize_catalog_package(payload, attrs, title)[1]
    changed, problems = normalize_catalog_package(source, {}, title + ' 변경')
    assert problems or changed != package
    if expected[2] > 1:
        assert normalize_catalog_package({**source, 'bundle_count': 1}, {'bundleCount': expected[2]}, title)[1]


def test_residual177_declared_fixed_piece_quote_is_exact_listing_only():
    from copy import deepcopy
    from core.catalog_quantity import normalize_catalog_package
    title = '셀렉스 프로핏 완전단백질 - 모카초콜릿 250ml x 24팩'
    source = {'pack_qty': 24, 'pack_unit': '팩', 'unit_price_basis': '개', 'unit_price_display': '개 당1,625원'}
    before = deepcopy(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and source == before
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == (250, 'ml', 24)
    for count in (1, 24):
        assert normalize_catalog_package({**source, 'bundle_count': count}, {}, title)[0] == package
    for quote in ('1개당999원', '개당2,100원'):
        assert normalize_catalog_package({**source, 'unit_price_display': quote}, {}, title)[0] == package
    for key, value in (('unit_price_basis', '2개'), ('unit_price_unit', '봉'), ('unit_price_basis_raw', '10g'),
                       ('pack_qty', 25), ('bundle_count', 2)):
        assert normalize_catalog_package({**source, key: value}, {}, title)[1]
    assert normalize_catalog_package(source, {'attrs': {'unit_price_basis': '2개'}}, title)[1]
    assert normalize_catalog_package(source, {}, title.replace('24팩', '25팩'))[0] != package
    assert normalize_catalog_package({'pack_qty': 36, 'pack_unit': '개', 'unit_price_basis': '개'}, {},
                                     '농심스낵모음 1,080g / 36개입')[1]


def test_residual177_cm_roll_retains_width_and_rejects_source_dimension_mutations():
    from core.catalog_quantity import normalize_catalog_package
    title = '스카치 방충망 보수테이프 롤타입 5X50cm'
    source = {'package_quantity': None, 'package_unit': '', 'unit': '', 'display_unit': ''}
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and (package['package_quantity'], package['package_unit'], package['bundle_count']) == (0.5, 'm', 1)
    assert package['display_unit'] == title
    assert normalize_catalog_package({'packQty': 50, 'packUnit': 'cm'}, {}, title)[0] == package
    assert normalize_catalog_package({**source, 'unit_price_display': '1m당 100원'}, {}, title)[1] == []
    assert normalize_catalog_package({**source, 'unit_price_display': '1m당 200원'}, {}, title)[1] == []
    for attrs in ({'pack_quantity': 1, 'pack_unit': 'm'}, {'attrs': {'packQty': 51, 'packUnit': 'cm'}},
                  {'display_unit': '6X50cm'}, {'bundleCount': 2}, {'unit_price_basis_raw': '10ml'}):
        assert normalize_catalog_package(source, attrs, title)[1]
    assert normalize_catalog_package(source, {}, title.replace('50', '60'))[0] != package


def test_approximate_mass_guard_does_not_turn_estimates_into_exact_contents():
    from core.catalog_quantity import normalize_catalog_package
    for title in ('수박 1.5kg미만', '메론 2.2kg내외', '복숭아 1250g 내외 (4~6입)'):
        assert normalize_catalog_package({'package_quantity': 1500, 'package_unit': 'g'}, {}, title) == (None, ['approximate_measured_quantity_unresolved'])
    fixed, issues = normalize_catalog_package({'package_quantity': 1250, 'package_unit': 'g'}, {}, '복숭아 1.25kg (4~6입)')
    assert not issues and fixed['package_quantity'] == 1250
    volume, issues = normalize_catalog_package({'package_quantity': 500, 'package_unit': 'ml'}, {}, '음료 500ml')
    assert not issues and volume['package_unit'] == 'ml'


def _component(quantity, unit='ml', count=1, identity='같은 세제', presentation=''):
    return dict(quantity=quantity, unit=unit, count=count, identity=identity, presentation=presentation)


def test_component_multiset_identity_and_pricing_are_separate():
    from core.catalog_quantity import canonical_components, component_signature, package_pricing_measure
    def package(rows):
        return {'package_quantity': 1, 'package_unit': '세트', 'bundle_count': 1,
                'attributes': {'package_components': rows}}
    unequal = package([_component(2.5, 'l'), _component(1500)])
    equal = package([_component(2000, count=2)])
    assert package_pricing_measure(unequal) == package_pricing_measure(equal) == (4000, 'ml')
    assert component_signature(unequal) != component_signature(equal)
    assert component_signature(unequal) == component_signature(package(list(reversed(unequal['attributes']['package_components']))))
    assert canonical_components([_component(2000), _component(2, 'l')]) == canonical_components([_component(2000, count=2)])
    assert component_signature(package([_component(2000, presentation='리필')])) != component_signature(package([_component(2000)]))
    assert canonical_components([_component(1, 'l', identity='Ａ', presentation='　리필　')])[0]['identity'] == 'A'
    scalar = {'package_quantity': 500, 'package_unit': 'g', 'bundle_count': 3}
    assert component_signature(scalar) is None and package_pricing_measure(scalar) == (1500, 'g')
    assert package_pricing_measure({'package_quantity': 3, 'package_unit': '개'}) is None
    for malformed in ({'attributes': []}, {'attributes': {'package_components': None}}):
        with pytest.raises(ValueError):
            component_signature(malformed)


@pytest.mark.parametrize('rows', [
    [], [_component(0)], [_component(float('nan'))], [_component(float('inf'))],
    [_component(1, count=1.5)], [_component(1, count=True)],
    [_component(1, identity='')], [_component(1, identity=None)],
    [_component(1), _component(1, identity='다른 세제')],
    [_component(1), _component(1, unit='g')], [_component(1, unit='개')],
    [{'quantity': 1}],
])
def test_component_family_rejects_malformed_and_mixed_contents(rows):
    from core.catalog_quantity import canonical_components
    with pytest.raises(ValueError):
        canonical_components(rows)


def test_component_source_boundary_checks_aliases_layers_and_composition():
    import copy
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_component_rules, uses_reviewed_quantity_rules
    title = 'SAFE 남극솔트 주방세제 480ml + 리필1L x 2'
    source = {'packQty': 1, 'packUnit': 'l', 'bundleCount': 2, 'unit': '1Lx2', 'unit_price_display': '100ml당 999원'}
    before = copy.deepcopy(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and source == before
    assert uses_reviewed_component_rules(title) and uses_reviewed_quantity_rules(title)
    assert package['display_unit'] == title and package['package_unit'] == '세트'
    assert package['attributes']['component_basis'] == 'reviewed_homogeneous_contents'
    corrected = {'package_quantity': 1, 'package_unit': '세트', 'bundle_count': 1, 'attributes': package['attributes']}
    assert normalize_catalog_package(corrected, {}, title) == (package, [])
    assert normalize_catalog_package({**source, 'unit_price_display': '100ml당 1,234원'}, {}, title)[1] == []
    rows = package['attributes']['package_components']
    changed = copy.deepcopy(rows)
    changed[0]['quantity'] += 100
    changed[1]['quantity'] -= 50
    # Equal aggregate content cannot conceal altered component sizes.
    for payload, attrs in (
        ({}, {}),
        ({**source, 'pack_quantity': 999, 'pack_unit': 'ml'}, {}),
        ({**source, 'pack_quantity': 1000}, {}),
        ({**source, 'packQuantity': 2}, {}),
        ({**source, 'bundle_count': 1.5}, {}),
        ({**source, 'bundle_count': 3}, {}),
        (source, {'attrs': {'package_quantity': 480, 'package_unit': 'ml'}}),
        ({**source, 'attributes': {'attrs': {'pack_qty': 1000, 'pack_unit': 'g'}}}, {}),
        ({**source, 'unit': '480ml'}, {}),
        ({**source, 'unit_price_basis_raw': '100g당 999원'}, {}),
        ({**source, 'package_components': changed}, {}),
        ({**source, 'package_components': [dict(row, presentation='') for row in rows]}, {}),
        ({**source, 'package_components': [dict(row, identity='다른 세제') for row in rows]}, {}),
        (source, {'package_quantity': 1, 'package_unit': '세트'}),
    ):
        assert normalize_catalog_package(payload, attrs, title)[1]
    assert not uses_reviewed_component_rules(title.replace('480', '500'))
    assert not uses_reviewed_component_rules('다른 세제 480ml + 리필1L x 2')
    for quantity_key, unit_key in (
        ('package_quantity', 'package_unit'), ('pack_qty', 'pack_unit'),
        ('packQty', 'packUnit'), ('pack_quantity', 'pack_unit'), ('packQuantity', 'packUnit'),
    ):
        assert normalize_catalog_package({quantity_key: 1000, unit_key: 'ml'}, {}, title) == (package, [])
    for bad_count in (True, 0, float('nan'), float('inf')):
        assert normalize_catalog_package({**source, 'bundleCount': bad_count}, {}, title)[1]


def test_single_complete_measured_factor_shared_runtime_parity():
    from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules
    title = '신라면5입600g(120gx5입)'
    source = {'package_quantity': 600, 'package_unit': 'g'}
    assert uses_reviewed_quantity_rules(title)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and (package['package_quantity'], package['bundle_count']) == (120, 5)
    for changed_title in (title + ' 혼합세트', title + ' 증정', title + ' 1+1',
                          '신라면120gx5입', '신라면600g(120gx5입 추가)', '신라면(120gx5입)600g'):
        assert not uses_reviewed_quantity_rules(changed_title)
    for changed in ({**source, 'package_quantity': 601}, {**source, 'unit': '601g'}):
        assert normalize_catalog_package(changed, {}, title)[1]


def test_sheet_components_keep_multiset_and_count_pricing_distinct():
    from copy import deepcopy
    from core.catalog_quantity import normalize_catalog_package, component_signature, package_pricing_measure, canonical_components
    title = '메르슈 건티슈 150매 x 3팩 + 15매 x 10 x 2팩'
    source = {'pack_qty': 2, 'pack_unit': '팩', 'bundle_count': 10, 'unit': '2팩×10', 'unit_price_basis': '10매'}
    before = deepcopy(source)
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and source == before and package['standard_unit'] == '매'
    assert package_pricing_measure(package) == (750, '매')
    rows = package['attributes']['package_components']
    assert canonical_components(list(reversed(rows))) == rows
    equal = deepcopy(package)
    equal['attributes']['package_components'] = [dict(rows[0], quantity=250, count=3)]
    assert package_pricing_measure(equal) == (750, '매') and component_signature(equal) != component_signature(package)
    for payload in ({**source, 'unit_price_basis': '10g'}, {**source, 'bundle_count': 2},
                    {**source, 'package_components': equal['attributes']['package_components']},
                    {**source, 'package_components': [dict(r, presentation='리필') for r in rows]}):
        assert normalize_catalog_package(payload, {}, title)[1]
    assert normalize_catalog_package({**source, 'unit_price_display': '10매당999원'}, {}, title)[0] == package
    with pytest.raises(ValueError):
        canonical_components([dict(rows[0], quantity=1.5)])
    assert package_pricing_measure({'package_quantity': 150, 'package_unit': '매', 'bundle_count': 5}) is None


def test_count_package_parser_handles_common_korean_non_weight_units() -> None:
    assert parse_package_quantity("황제 활 전복 특대 10마리") == {
        "raw_match": "10마리",
        "package_quantity": 10.0,
        "package_unit": "마리",
        "display_unit": "10마리",
    }
    assert parse_package_quantity("마스크팩 100매") == {
        "raw_match": "100매",
        "package_quantity": 100.0,
        "package_unit": "매",
        "display_unit": "100매",
    }
    assert parse_package_quantity("레몬즙 1박스 14포") == {
        "raw_match": "14포",
        "package_quantity": 14.0,
        "package_unit": "포",
        "display_unit": "14포",
    }


def test_count_package_parser_handles_parenthesized_single_count_units() -> None:
    assert parse_package_quantity("완도 전복(대) (마리)") == {
        "raw_match": "(마리)",
        "package_quantity": 1.0,
        "package_unit": "마리",
        "display_unit": "1마리",
    }
    assert parse_package_quantity("[농할할인가] 국내산 큰 양배추 (통)") == {
        "raw_match": "(통)",
        "package_quantity": 1.0,
        "package_unit": "통",
        "display_unit": "1통",
    }


def test_raw_unit_measure_is_used_when_title_has_no_package_but_reference_units_stay_display_only() -> None:
    parsed = normalize_unit_metadata(name="한글과자 초코맛 1봉지", raw_unit="10g", sale_price=1000)
    assert parsed["package_quantity"] == 1.0
    assert parsed["package_unit"] == "봉지"
    assert parsed["display_unit"] == "1봉지"

    parsed = normalize_unit_metadata(name="정육 1등급 윗등심살", raw_unit="100g", sale_price=4980)
    assert parsed["package_quantity"] is None
    assert parsed["package_unit"] is None
    assert parsed["display_unit"] is None

    parsed = normalize_unit_metadata(name="소용량 소스", raw_unit="80g", sale_price=1980)
    assert parsed["package_quantity"] == 80.0
    assert parsed["package_unit"] == "g"
    assert parsed["display_unit"] == "80g"

    # Explicit reference suffixes work for arbitrary measured denominators;
    # the published rate must not be converted into sold contents by division.
    for reference in ('10g 당 375원', '25ml 기준 100원', '0.5kg/1,250원',
                      '(10g)당 375원', '10g/375.50원'):
        parsed = normalize_unit_metadata(name='처음먹는 고구마 퓨레', sale_price=3000, raw_unit=reference)
        assert parsed['package_quantity'] is parsed['package_unit'] is parsed['price_per_100g'] is None
        assert parsed['display_unit'] == reference
        parsed = normalize_unit_metadata(name=f'퓨레 {reference}', sale_price=3000)
        assert parsed['package_quantity'] is parsed['package_unit'] is parsed['price_per_100g'] is None
        parsed = normalize_unit_metadata(name='퓨레 80g', sale_price=3000, raw_unit=reference)
        assert parsed['package_quantity'] == 80 and parsed['package_unit'] == 'g'
        assert parsed['price_per_100g'] == 3750
        parsed = normalize_unit_metadata(name=f'퓨레 80g {reference}', sale_price=3000)
        assert parsed['package_quantity'] == 80 and parsed['price_per_100g'] == 3750

    for raw in ('10g', '10g/봉'):
        parsed = normalize_unit_metadata(name='퓨레', sale_price=3000, raw_unit=raw)
        assert parsed['package_quantity'] == 10 and parsed['price_per_100g'] == 30000
    # The beginning of a product noun is not a price-per suffix.
    parsed = normalize_unit_metadata(name='10g 당근 퓨레', sale_price=3000)
    assert parsed['package_quantity'] == 10 and parsed['price_per_100g'] == 30000


def test_measure_bundle_parser_prefers_total_packaging_over_trailing_count_units() -> None:
    parsed = normalize_unit_metadata(name="[기획] 모짜렐라 치즈볼 360g*2입", sale_price=8980)
    assert parsed["raw_match"] == "360g*2입"
    assert parsed["package_quantity"] == 360.0
    assert parsed["package_unit"] == "g"
    assert parsed["display_unit"] == "360g×2"
    assert parsed["bundle_count"] == 2
    assert parsed["price_per_100g"] == 1247.22

    parsed = normalize_unit_metadata(name="렌즈세정액 355ML*3", sale_price=12900)
    assert parsed["package_quantity"] == 355.0
    assert parsed["package_unit"] == "ml"
    assert parsed["display_unit"] == "355ml×3"
    assert parsed["bundle_count"] == 3


def test_measure_bundle_parser_does_not_treat_plus_formula_as_count_multiplier() -> None:
    parsed = normalize_unit_metadata(name="샴푸 100ml+100ml 기획", sale_price=3000)
    assert parsed["raw_match"] == "100ml"
    assert parsed["package_quantity"] == 100.0
    assert parsed["package_unit"] == "ml"
    assert "bundle_count" not in parsed


def test_korean_measure_words_parse_as_canonical_package_units() -> None:
    assert parse_package_quantity("처음보는 쌀과자 300그램") == {
        "raw_match": "300그램",
        "package_quantity": 300.0,
        "package_unit": "g",
        "display_unit": "300g",
    }

    parsed = normalize_unit_metadata(name="마트 PB 생수 2리터×6입", sale_price=3600)
    assert parsed["raw_match"] == "2리터×6입"
    assert parsed["package_quantity"] == 2.0
    assert parsed["package_unit"] == "L"
    assert parsed["display_unit"] == "2L×6"
    assert parsed["bundle_count"] == 6


def test_compact_measure_bundle_without_space_before_x_is_parsed() -> None:
    assert parse_package_quantity("한우물 주먹밥100gx30") == {
        "raw_match": "100gx30",
        "package_quantity": 100.0,
        "package_unit": "g",
        "display_unit": "100g×30",
        "bundle_count": 30,
    }


def test_grouped_thousands_measure_is_not_truncated_to_suffix() -> None:
    for title, quantity in [("국 2,500g", 2500), ("샴푸 1,050ml", 1050), ("고기 (1,000g)", 1000)]:
        assert parse_package_quantity(title)["package_quantity"] == quantity
    assert parse_package_quantity("국 2,500g x 2")["bundle_count"] == 2
    assert normalize_unit_metadata(name="국 2,500g", sale_price=10000)["price_per_100g"] == 400
    assert parse_package_quantity("잘못된 중량 1,05g") is None
    assert parse_package_quantity("잘못된 중량 1,000,00g") is None


def test_single_measure_chain_multiplies_all_explicit_factors() -> None:
    for title, quantity, count in [
        ("잡채350g x 5 x 2pk", 350, 10),
        ("순대 500gx3x2", 500, 6),
        ("콤부차 5g x 30ct x 2", 5, 60),
        ("볶음밥300g x 7 x 2봉(4200g)", 300, 14),
    ]:
        parsed = parse_package_quantity(title)
        assert parsed["package_quantity"] == quantity
        assert parsed["bundle_count"] == count
    assert normalize_unit_metadata(name="잡채350g x 5 x 2pk", sale_price=35000)["price_per_100g"] == 1000


@pytest.mark.parametrize('title,quantity,count', [
    ('카누 라떼 커피 13.5g x 50스틱 x 2박스',13.5,100),
    ('티젠 레몬 콤부차 5g x 30ct x 2',5,60),
    ('델몬트 스퀴즈 사과/오렌지 에이드 240ml x 30 x 2팩',240,60),
    ('맥심 화이트 골드 커피믹스 11.7g x 210T x 2',11.7,420),
    ('녹차원 보이차 0.9g x 100티백 x 3',0.9,300),
    ('코카콜라제로제로190ml x 30can x 2',190,60),
])
def test_typed_measured_chain_counts_sticks_teabags_and_cans_not_tons(title,quantity,count):
    package = parse_package_quantity(title)
    assert package['package_quantity'] == quantity
    assert package['bundle_count'] == count
    assert package['package_unit'] in {'g','ml'}
    assert len(re.findall(r'[x×*]\s*\d+',package['raw_match'],re.I)) == 2


def test_trailing_unit_price_reference_does_not_override_package_quantity() -> None:
    parsed = normalize_unit_metadata(name="무항생제 한우 불고기 300g 100g당 4,950원", sale_price=14850)
    assert parsed["raw_match"] == "300g"
    assert parsed["package_quantity"] == 300.0
    assert parsed["package_unit"] == "g"
    assert parsed["price_per_100g"] == 4950

    parsed = normalize_unit_metadata(name="대용량 생수 2L 100ml당 25원", sale_price=500)
    assert parsed["raw_match"] == "2L"
    assert parsed["package_quantity"] == 2.0
    assert parsed["package_unit"] == "L"


def test_standalone_unit_price_reference_is_not_treated_as_package() -> None:
    parsed = normalize_unit_metadata(name="정육 행사 100g당 2,980원", sale_price=2980)
    assert parsed["package_quantity"] is None
    assert parsed["package_unit"] is None
    assert parsed["display_unit"] is None


def test_slash_package_and_count_bundle_patterns_parse_without_product_patches() -> None:
    parsed = parse_package_quantity("[생물][국산] 새꼬막 (1kg/봉)")
    assert parsed == {
        "raw_match": "1kg",
        "package_quantity": 1.0,
        "package_unit": "kg",
        "display_unit": "1kg",
    }

    parsed = parse_package_quantity("행복한 대란 30구 (15구 X 2ea)")
    assert parsed == {
        "raw_match": "15구 X 2ea",
        "package_quantity": 15.0,
        "package_unit": "구",
        "display_unit": "15구×2",
        "bundle_count": 2,
    }


def test_parenthesized_count_unit_with_descriptor_parses_as_single_unit() -> None:
    assert parse_package_quantity("[해동][국산] 국산 새우 (특, 마리)") == {
        "raw_match": "(특, 마리)",
        "package_quantity": 1.0,
        "package_unit": "마리",
        "display_unit": "1마리",
    }
    assert parse_package_quantity("싱크대배수관 세정제(1회분)") == {
        "raw_match": "1회분",
        "package_quantity": 1.0,
        "package_unit": "회분",
        "display_unit": "1회분",
    }


def test_dimension_and_device_capacity_numbers_are_not_package_units() -> None:
    assert parse_package_quantity("보쉬 V4 클리어비젼 400mm") is None
    assert parse_package_quantity("아이폰 17 프로 256GB 자급제") is None


@pytest.mark.parametrize('title,count',[('한스팜 유기농계란15ea x 2',30),('한스팜 자연을품은동물복지란20ea x 2',40),('풀무원 동물복지란 60 구 (30ea x 2)',60)])
def test_reviewed_count_only_eggs_have_individual_count_not_weight(title,count):
    from core.catalog_quantity import normalize_catalog_package
    package,issues=normalize_catalog_package({}, {}, title)
    assert issues==[]
    assert (package['package_quantity'],package['package_unit'],package['bundle_count'])==(float(count),'개',1)
    assert normalize_catalog_package({'pack_qty':1,'pack_unit':'kg'}, {}, title)[1]


def test_reviewed_corrupted_yogurt_measurement_is_exact_and_bounded():
    from core.catalog_quantity import normalize_catalog_package
    title='윌 오리지날 150mlX5개'
    package,issues=normalize_catalog_package({'package_quantity':5,'package_unit':'개','display_unit':'5개'}, {}, title)
    assert issues==[] and (package['package_quantity'],package['package_unit'],package['bundle_count'])==(150.0,'ml',5)
    for changed in ({'package_quantity':4,'package_unit':'개','display_unit':'5개'},{'package_quantity':5,'package_unit':'개','display_unit':'4개'}):
        assert normalize_catalog_package(changed,{},title)[1]


def test_estimated_mass_exact_sold_count_preserves_dimension_and_conflicts():
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure
    source = {'package_quantity': 1.4, 'package_unit': 'kg', 'display_unit': '1.4kg'}
    title = '영광 참굴비 2호 (20마리/1.4KG 내외)'
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and (package['package_quantity'], package['package_unit'], package['bundle_count']) == (20, '마리', 1)
    assert package_pricing_measure(package) is None
    for attrs in ({'package_quantity': 1.5, 'package_unit': 'kg'}, {'attrs': {'packQty': 21, 'packUnit': '마리'}},
                  {'bundleCount': 20}, {'display_unit': '1.5kg'}, {'unit_price_basis_raw': '100ml'}):
        assert normalize_catalog_package(source, attrs, title)[0] is None
    for quote in ('100g당 500원', '100g당 600원'):
        assert normalize_catalog_package({**source, 'unit_price_display': quote}, {}, title)[0] == package
    for title in ('수박2호 (6kg미만)', '포도3kg 내외(6~9송이)', '과일 6입(1kg내외)×2팩', '과일 6입+1입(1kg내외)', '과일 6입(1kg내외)X2팩', '과일 6-9개(1kg내외)', '과일 6–9개(1kg내외)'):
        assert normalize_catalog_package({'package_quantity': 1, 'package_unit': 'kg'}, {}, title)[0] is None
    for title, count in [('홍시 6입팩(360g내외)', 6), ('오이 2입/봉(360g내외)', 2), ('유정란 15개입(360g내외)', 15)]:
        package, issues = normalize_catalog_package({'package_quantity': 360, 'package_unit': 'g'}, {}, title)
        assert not issues and package['package_quantity'] == count and package['bundle_count'] == 1
    package, issues = normalize_catalog_package({'package_quantity': 1.8, 'package_unit': 'kg'}, {}, '보리굴비세트 3호 (10미 1.8kg 내외/미당 26~30cm 내외)')
    assert not issues and package['package_unit'] == '미' and package['package_quantity'] == 10


def test_estimated_mass_additional_sold_counts_and_price_basis_dimensions():
    from core.catalog_quantity import normalize_catalog_package
    source = {'package_quantity': 1, 'package_unit': 'kg', 'display_unit': '1kg'}
    title = '과일 6입(1kg내외)'
    package, issues = normalize_catalog_package(source, {}, title)
    assert not issues and (package['package_quantity'], package['package_unit'], package['bundle_count']) == (6, '개', 1)
    for extra in (' 2팩', ' / 2봉', ' 2박스', ' 2개입', ' 2세트'):
        assert normalize_catalog_package(source, {}, title + extra) == (None, ['approximate_measured_quantity_unresolved'])
    for field in ('display_unit', 'unit'):
        assert normalize_catalog_package({**source, field: '1kg / 2봉'}, {}, title)[0] is None
    for basis in ('1마리당 500원', '1미당500원', '100ml당 500원'):
        assert normalize_catalog_package({**source, 'unit_price_basis': basis}, {}, title)[0] is None
        assert normalize_catalog_package(source, {'attrs': {'unit_price_text': basis}}, title)[0] is None
    for basis in ('1개당 500원', '1개당 600원', '1입당 600원', '1EA당 600원', '100g당 500원', '100g당 600원'):
        assert normalize_catalog_package({**source, 'unit_price_display': basis}, {}, title) == (package, [])
    fish = '굴비 2호(20마리/1kg내외)'
    fish_package, issues = normalize_catalog_package(source, {'unit_price_basis_raw': '1개'}, fish)
    assert not issues and (fish_package['package_quantity'], fish_package['package_unit']) == (20, '마리')
    assert normalize_catalog_package(source, {'unit_price_basis_raw': '2개'}, fish)[0] is None
    assert normalize_catalog_package(source, {'unit_price_basis_raw': '1마리당 600원'}, fish)[0] == fish_package


@pytest.mark.parametrize('title,quantity,unit,leaf,count', [
    ('세탁기 DD모터 T19MX8A 19kg', 19, 'kg', 'appliances.laundry.washer.standard', None),
    ('냉장고 Fit & Max 189L', 189, 'L', 'appliances.kitchen.refrigerator.standard', None),
    ('과일 세척기 4L', 4, 'L', 'appliances.kitchen.produce_washer.ultrasonic', None),
    ('케틀 1.7L 2개입', 1.7, 'L', 'appliances.kitchen.kettle.electric', 2),
    ('세탁기 + 건조기 세트명[WF25DG8250BW2T]', 2, 'T', 'appliances.laundry.set.washer_dryer', None),
])
def test_classified_device_capacity_is_specification_not_sales_contents(title, quantity, unit, leaf, count):
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure, valid_physical_device_variant
    from types import MappingProxyType
    source = MappingProxyType({'pack_qty':quantity, 'pack_unit':unit, 'canonical_url':'https://example.test/appliance/123'})
    package, issues = normalize_catalog_package(source, {}, title, category_id=leaf)
    assert not issues and valid_physical_device_variant(package)
    assert package['package_quantity'] == count and package['package_unit'] == ('개' if count else None)
    assert package_pricing_measure(package) is None
    assert package['attributes']['physical_device_specification']['quantity_fields']['pack_qty'] == quantity
    assert normalize_catalog_package(dict(source), {}, title + ' x 2', category_id=leaf)[0] is None
    # Product role, not an appliance word, determines contents versus capacity.
    contents, issues = normalize_catalog_package({'pack_qty':500, 'pack_unit':'ml'}, {}, '세탁기 세제 500ml', category_id='household.cleaning.laundry.liquid')
    assert not issues and package_pricing_measure(contents) == (500, 'ml')
    beverage, issues = normalize_catalog_package({'pack_qty':350, 'pack_unit':'ml'}, {}, '과채 음료 350ml', category_id='food.drinks.juice.mixed')
    assert not issues and package_pricing_measure(beverage) == (350, 'ml')
    assert normalize_catalog_package(None, {}, title, category_id=leaf)[0] is None
    if unit == 'T':
        assert normalize_catalog_package(source, {}, '세탁기 2T', category_id=leaf)[0] is None
        assert normalize_catalog_package(source, {'pack_qty':3, 'pack_unit':'T'}, title, category_id=leaf)[0] is None
        assert normalize_catalog_package(source, {'pack_qty':2, 'pack_unit':'개'}, title, category_id=leaf)[0] is None
        # The same unit is a real declared tea-bag count in a food role.
        tea, issues = normalize_catalog_package({'pack_qty':2, 'pack_unit':'T'}, {}, '녹차 2T', category_id='food.drinks.tea.green')
        assert not issues and tea['package_quantity'] == 2 and tea['package_unit'] == 't'


@pytest.mark.parametrize('title,quantity,unit,leaf,count,sold_unit', [
    ('금고 40L',40,'L','household.security.storage.safe',None,None),
    ('토트 쿨러백 16L',16,'L','household.outdoor.bags.cooler_tote',None,None),
    ('문서세단기 12C 19L',19,'L','office.equipment.shredder.standard',None,None),
    ('타월 130g 5P',130,'g','household.bath.textiles.towel',5,'개'),
    ('타월 1P 그레이 150g',150,'g','household.bath.textiles.towel',1,'개'),
    ('A4 복사지 80g2500매',80,'g','stationery.office.paper.copy',2500,'매'),
])
def test_physical_item_specification_keeps_independent_sold_count(title,quantity,unit,leaf,count,sold_unit):
    from copy import deepcopy
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure, valid_physical_device_variant
    raw={'package_quantity':quantity,'package_unit':unit,'detail_url':'https://example.test/item/123'}
    package,issues=normalize_catalog_package(raw,{},title,category_id=leaf)
    assert not issues and valid_physical_device_variant(package)
    assert (package['package_quantity'],package['package_unit'],package['bundle_count'])==(count,sold_unit,1)
    assert package_pricing_measure(package) is None
    for suffix in (' x 2',' 2팩',' 2세트'):
        assert normalize_catalog_package(raw,{},title+suffix,category_id=leaf)[0] is None
    if sold_unit in {'개','매'}:
        counted,issues=normalize_catalog_package({**raw,'package_quantity':count,'package_unit':sold_unit},{},title,category_id=leaf)
        assert not issues and valid_physical_device_variant(counted)
        assert counted['package_quantity']==count and counted['package_unit']==sold_unit
        assert normalize_catalog_package({**raw,'package_quantity':count+1,'package_unit':sold_unit},{},title,category_id=leaf)[0] is None
    if sold_unit=='매':
        assert normalize_catalog_package(raw,{},'A4 복사지 80g',category_id=leaf)[0] is None
        forged=deepcopy(package)
        forged.update(package_quantity=None,package_unit=None)
        forged['attributes']['physical_device_specification']['sold_piece_count']=None
        assert not valid_physical_device_variant(forged)


@pytest.mark.parametrize('title,quantity,bundle,leaf,count', [
    ('빈 보틀950ml2PK', 950, 2, 'household.kitchen.drinkware.insulated_bottle', 2),
    ('빈 종이컵473ml x 180', 473, 180, 'household.kitchen.consumables.paper_cup', 180),
    ('유리잔270+380ml 8P', 380, 1, 'household.kitchen.drinkware.glass', 8),
    ('주전자3.5L', 3500, 1, 'household.kitchen.cookware.kettle', None),
    ('압축 휴지통10L', 10000, 1, 'household.cleaning.waste.bin', None),
    ('압축 휴지통20L 2개', 20000, 1, 'household.cleaning.waste.bin', 2),
])
def test_empty_vessel_capacity_uses_declared_primary_count_without_bundle_multiplication(title, quantity, bundle, leaf, count):
    from core.catalog_quantity import normalize_catalog_package, package_pricing_measure, valid_physical_device_variant
    raw = {'pack_qty': quantity, 'pack_unit': 'ml', 'bundle_count': bundle,
           'canonical_url': 'https://example.test/vessel/123'}
    package, issues = normalize_catalog_package(raw, {}, title, category_id=leaf)
    assert not issues and valid_physical_device_variant(package)
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == (count, '개' if count else None, 1)
    assert package_pricing_measure(package) is None
    assert normalize_catalog_package(raw, {}, title + ' x 2팩', category_id=leaf)[0] is None
    assert normalize_catalog_package(raw, {}, title + ' 2팩', category_id=leaf)[0] is None
    conflicting = {**raw, 'attributes': {'package_quantity': 1, 'package_unit': '개'}}
    assert normalize_catalog_package(conflicting, conflicting['attributes'], title, category_id=leaf)[0] is None
    if leaf == 'household.kitchen.consumables.paper_cup':
        # Existing independently exact piece counts retain their established
        # scalar representation and ID basis when physical roles are added.
        counted = {**raw, 'bundle_count': 1}
        counted_title = '검수 종이컵473ml*25개'
        prior, prior_issues = normalize_catalog_package(counted, {}, counted_title)
        current, current_issues = normalize_catalog_package(counted, {}, counted_title, category_id=leaf)
        assert not prior_issues and not current_issues and current == prior
        assert current['package_quantity'] == 25 and current['package_unit'] == '개'
        assert not current.get('attributes')


@pytest.mark.parametrize('review', [record for record in REVIEWED_EXPLICIT_LISTING_PACKAGES
                                    if any(isinstance(value, str) and '당' in value and '원' in value
                                           for key, value in record['quantity_fields'].items()
                                           if key in {'unit', 'display_unit'})])
def test_source_bound_contents_ignore_only_valid_quoted_display_money(review):
    from copy import deepcopy
    from core.catalog_quantity import normalize_catalog_package
    from core.reviewed_source_evidence import listing_quantity_evidence
    original_review = deepcopy(review)
    raw = {'name': review['title'], 'source_url': review['required_source']['source_urls'][0], 'attributes': {}}
    for fields in (review['required_source']['source_fields'], review['quantity_fields']):
        for key, value in fields.items():
            layer = raw['attributes'] if key.startswith('attributes.') else raw
            key = key.rsplit('.', 1)[-1]
            layer[key] = (str(value[0] or '') + value[1] + '당 1,618원'
                          if isinstance(value, list) else value)
    original = deepcopy(raw)
    package, issues = normalize_catalog_package(raw, raw['attributes'], review['title'])
    assert not issues
    assert (package['package_quantity'], package['package_unit'], package['bundle_count']) == tuple(review['normalized'])
    changed = deepcopy(raw)
    basis = review['quantity_fields']['attributes.unit_price_display']
    quote = str(basis[0]) + basis[1] + ' 당 2,222원'
    changed.update(unit=quote, display_unit=quote, sale_price=9999)
    changed['attributes']['unit_price_display'] = quote
    assert normalize_catalog_package(changed, changed['attributes'], review['title']) == (package, issues)
    assert listing_quantity_evidence(changed) != listing_quantity_evidence(raw)
    for bad in ('100개당2,222원', '200'+basis[1]+'당2,222원', '100.000000000000001'+basis[1]+'당2,222원', '100'+basis[1],
                '100'+basis[1]+'당0원', '100'+basis[1]+'당-1원', '100'+basis[1]+'당2,,222원',
                None, [], '수량 미확인'):
        rejected = deepcopy(changed); rejected['unit'] = rejected['display_unit'] = bad
        assert normalize_catalog_package(rejected, rejected['attributes'], review['title'])[1]
    for mutation in ({'bundle_count': 2}, {'package_quantity': 999, 'package_unit': 'g'},
                     {'source_url': 'https://retailer.example/wrong-native'}, {'category': '다른 문맥'}):
        rejected = {**deepcopy(changed), **mutation}
        assert normalize_catalog_package(rejected, rejected['attributes'], review['title'])[1]
    assert normalize_catalog_package({}, {}, review['title'])[1]
    assert raw == original and review == original_review
