"""Homeplus parser contracts using representative saved mfront API responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawlers.marts.homeplus.crawler import HomeplusCrawler


FIXTURE_JSON = Path(__file__).parent / "fixtures" / "homeplus" / "sale_listing_3items.json"
DC_MIXED_FIXTURE = Path(__file__).parent / "fixtures" / "homeplus" / "sale_listing_5items_dc_mixed.json"


@pytest.fixture
def raw_json() -> str:
    return FIXTURE_JSON.read_text(encoding="utf-8")


@pytest.fixture
def parsed_envelope():
    return json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def dc_mixed_raw() -> str:
    return DC_MIXED_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def dc_mixed_envelope():
    return json.loads(DC_MIXED_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_json_envelope_maps_name_price_identity_and_detail_url(raw_json, parsed_envelope):
    items = await HomeplusCrawler().parse(raw_json)
    raw_first = parsed_envelope["data"]["dataList"][0]

    assert len(items) == len(parsed_envelope["data"]["dataList"])
    first = items[0]
    assert first.name == raw_first["itemNm"]
    assert first.sale_price == int(raw_first.get("dcPrice") or raw_first["salePrice"])
    assert first.detail_url.startswith("https://mfront.homeplus.co.kr/")
    assert first.attributes["mart_native_code"] == raw_first["itemNo"]
    assert first.attributes["source_record_key"]


@pytest.mark.asyncio
async def test_json_envelope_does_not_invent_non_positive_prices(raw_json):
    items = await HomeplusCrawler().parse(raw_json)
    assert items
    assert all(item.sale_price > 0 for item in items)


@pytest.mark.asyncio
async def test_parser_rejects_unrelated_payloads():
    crawler = HomeplusCrawler()
    assert await crawler.parse('{"returnStatus":500,"data":{}}') == []
    assert await crawler.parse("<html>not product data</html>") == []
    assert await crawler.parse("[]") == []


@pytest.mark.asyncio
async def test_dc_price_branch_maps_discount_and_regular_price_correctly(dc_mixed_raw, dc_mixed_envelope):
    items = await HomeplusCrawler().parse(dc_mixed_raw)
    by_no = {item.attributes["mart_native_code"]: item for item in items}

    discounted_rows = [row for row in dc_mixed_envelope["data"]["dataList"] if row.get("dcPrice") is not None]
    regular_rows = [row for row in dc_mixed_envelope["data"]["dataList"] if row.get("dcPrice") is None]
    assert discounted_rows
    assert regular_rows

    for raw in discounted_rows:
        item = by_no[raw["itemNo"]]
        assert item.sale_price == int(raw["dcPrice"])
        expected_original = int(raw.get("singlePrice") or raw["salePrice"])
        assert item.original_price == expected_original
        assert item.original_price > item.sale_price
        assert item.discount_percent is not None and item.discount_percent > 0

    for raw in regular_rows:
        item = by_no[raw["itemNo"]]
        assert item.sale_price == int(raw["salePrice"])
        assert item.original_price is None


@pytest.mark.asyncio
async def test_envelope_preserves_unit_price_and_category(raw_json, parsed_envelope):
    items = await HomeplusCrawler().parse(raw_json)
    raw_first = parsed_envelope["data"]["dataList"][0]
    first = items[0]
    expected_category = (
        raw_first.get("categoryNm")
        or raw_first.get("ctgNm")
        or raw_first.get("dcateNm")
        or raw_first.get("scateNm")
        or raw_first.get("mcateNm")
        or raw_first.get("lcateNm")
        or raw_first.get("rcateNm")
        or ""
    )

    assert first.attributes["unit_price_displayed"] == float(raw_first["unitPrice"])
    assert first.category == expected_category


@pytest.fixture
def native_detail_node():
    # Genuine saved product-only capture; wrapper/script tests below reconstruct
    # only its supplied data.item shape, not the discarded provider HTML.
    root = Path(__file__).resolve().parents[4]
    capture = json.loads((root / '.debug-artifacts/review-proposals/continuation222-homeplus-target-native-price-capture.json').read_text())
    return capture['retained_product_containers'][0]['product_container_before_semantic_conversion']


_DETAIL_URL = 'https://mfront.homeplus.co.kr/item?itemNo=059102628&storeType=HYPER'


@pytest.fixture
def disabled_display_detail_node():
    root = Path(__file__).resolve().parents[4]
    capture = json.loads((root / '.debug-artifacts/review-proposals/continuation227-homeplus-towel-real-source-evidence.json').read_text())
    return capture['product_containers'][0]['retained_raw_product_before_interpretation']


_DISABLED_DISPLAY_URL = 'https://mfront.homeplus.co.kr/item?itemNo=070914500&storeType=HYPER'


@pytest.mark.asyncio
async def test_disabled_display_keeps_source_quote_spec_and_conflicting_promotion_unknown(disabled_display_detail_node):
    import hashlib
    items = await HomeplusCrawler().parse(json.dumps({'data': {'item': disabled_display_detail_node}}), source_url=_DISABLED_DISPLAY_URL)
    assert len(items) == 1
    item = items[0]
    assert item.name == 'simplus 데일리 타월 1P 그레이 150g'
    assert item.sale_price == 2990 and item.detail_url == _DISABLED_DISPLAY_URL
    assert item.original_price is None and item.discount_percent is None and item.price_per_100g is None
    assert item.valid_from is None and item.valid_until is None
    assert item.promo_type is None and item.promo_label is None
    attrs = item.attributes
    assert attrs['source_minimum_purchase_quantity'] == 1
    assert attrs['source_quote_currency'] is None
    assert attrs['promotion_conditions'] == {
        'source_condition_kind': 'source_quote_purchase_conditions_unverified',
        'payable_price_unconfirmed': True, 'minimum_purchase_quantity_unconfirmed': True,
        'coupon_application_unconfirmed': True,
    }
    fields = attrs['homeplus_detail_source_fields']
    assert fields['basic']['itemNm'] == item.name
    assert fields['etc']['unitDispYn'] == 'N' and fields['etc']['totalUnitQty'] == 0
    assert not any(key in fields['sale'] for key in ('currency', 'currencyCode', 'priceCurrency'))
    assert fields['sale']['purchaseLimitQty'] == 10 and fields['sale']['purchaseLimitDay'] == 1
    event = fields['sale']['eventList'][0]
    assert event['buyItemCount'] == event['buyItemCnt'] == 5
    assert event['eventBenefitQty'] == 4 and event['changeAmount'] == 9990
    assert event['eventGiveType'] is None
    assert event['dispEventLabel'] == item.event_name == '4개 담으면, 9,990원에 구매 (최대 100개까지 행사/할인 적용)'
    assert [row['thresholdQty'] for row in event['thresholdIntervals']] == list(range(4, 101, 4))
    assert event['eventStartDt'] == '2026-10-01' and event['eventEndDt'] == '2026-10-14'
    promo = fields['promo']['eventInfo']
    assert promo['buyItemCnt'] == 5 and promo['thresholdQty'] == 4 and promo['changeAmount'] == 9990
    assert fields['promo']['couponList'][0]['issueEndDt'].startswith('2026-10-07')
    serialized = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert attrs['homeplus_detail_source_fields_sha256'] == hashlib.sha256(serialized.encode()).hexdigest()
    assert all(key not in serialized for key in ('itemList', 'currentItem', 'eventNo', 'thresholdId', 'review', 'stock'))
    assert 'final_price' not in attrs['promotion_conditions'] and 'buy_quantity' not in attrs['promotion_conditions']


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value,marker', [
    ('totalUnitQty', 150, 'N'), ('unitQty', 1, 'N'),
    ('unitPrice', 1, 'N'), ('cardUnitPrice', 1, 'N'),
    ('totalUnitQty', False, 'N'), ('unitQty', '0', 'N'),
    ('unitPrice', float('inf'), 'N'), ('cardUnitPrice', {'value': 0}, 'N'),
    ('totalUnitQty', 0, 'Y'), ('totalUnitQty', 0, None),
])
async def test_disabled_display_never_ignores_positive_malformed_or_active_metadata(disabled_display_detail_node, field, value, marker):
    disabled_display_detail_node['etc'][field] = value
    if marker is None:
        disabled_display_detail_node['etc'].pop('unitDispYn')
    else:
        disabled_display_detail_node['etc']['unitDispYn'] = marker
    assert await HomeplusCrawler().parse(json.dumps({'data': {'item': disabled_display_detail_node}}), source_url=_DISABLED_DISPLAY_URL) == []


@pytest.mark.asyncio
async def test_disabled_display_missing_metadata_does_not_default_minimum_or_currency(disabled_display_detail_node):
    for key in ('totalUnitQty', 'unitQty', 'unitPrice', 'cardUnitPrice'):
        disabled_display_detail_node['etc'][key] = None
    disabled_display_detail_node['sale'].pop('purchaseMinQty')
    item = (await HomeplusCrawler().parse(json.dumps({'data': {'item': disabled_display_detail_node}}), source_url=_DISABLED_DISPLAY_URL))[0]
    assert 'source_minimum_purchase_quantity' not in item.attributes
    assert item.attributes['source_quote_currency'] is None
    assert item.attributes['promotion_conditions']['minimum_purchase_quantity_unconfirmed'] is True
    assert item.sale_price == 2990 and item.price_per_100g is None


@pytest.mark.asyncio
async def test_disabled_display_currency_cannot_copy_unbounded_objects(disabled_display_detail_node):
    disabled_display_detail_node['sale']['currency'] = {'account': 'DO_NOT_COPY'}
    item = (await HomeplusCrawler().parse(json.dumps({'data': {'item': disabled_display_detail_node}}), source_url=_DISABLED_DISPLAY_URL))[0]
    assert item.attributes['source_quote_currency'] is None
    assert 'currency' not in item.attributes['homeplus_detail_source_fields']['sale']
    assert 'DO_NOT_COPY' not in json.dumps(item.model_dump(mode='json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['zero_quote', 'boolean_quote', 'threshold_overflow', 'long_promotion'])
async def test_disabled_display_cannot_turn_zero_quote_or_truncated_terms_into_source_facts(disabled_display_detail_node, boundary):
    if boundary == 'zero_quote': disabled_display_detail_node['sale']['salePrice'] = 0
    if boundary == 'boolean_quote': disabled_display_detail_node['sale']['salePrice'] = False
    if boundary == 'threshold_overflow':
        event = disabled_display_detail_node['sale']['eventList'][0]
        event['thresholdIntervals'] = event['thresholdIntervals'] * 2
    if boundary == 'long_promotion':
        disabled_display_detail_node['sale']['eventList'][0]['dispEventLabel'] = '4개 담으면, 9,990원 ' + ' ' * 256 + '5개'
    assert await HomeplusCrawler().parse(json.dumps({'data': {'item': disabled_display_detail_node}}), source_url=_DISABLED_DISPLAY_URL) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('script_wrapper', [False, True])
async def test_native_detail_preserves_actual_quote_contents_and_unknown_terms(native_detail_node, script_wrapper):
    import hashlib
    source = json.dumps({'data': {'item': native_detail_node}}, ensure_ascii=False)
    if script_wrapper:
        source = '<html><script type="application/json">' + source + '</script></html>'
    items = await HomeplusCrawler().parse(source, source_url=_DETAIL_URL)
    assert len(items) == 1
    item = items[0]
    assert item.name == native_detail_node['basic']['itemNm']
    assert item.sale_price == 2190
    assert item.original_price is None and item.discount_percent is None and item.price_per_100g is None
    assert item.detail_url == _DETAIL_URL
    assert item.package_quantity == 2 and item.package_unit == 'L'
    assert item.display_unit == '2L×6'
    assert item.attributes['bundle_count'] == 6
    assert item.attributes['mart_native_code'] == '059102628'
    assert item.event_name == '' and item.promo_type is None and item.promo_label is None
    assert item.attributes['source_event_absent'] is True
    assert item.attributes['promotion_conditions'] == {
        'source_condition_kind': 'source_quote_purchase_conditions_unverified',
        'payable_price_unconfirmed': True, 'minimum_purchase_quantity_unconfirmed': True,
        'coupon_application_unconfirmed': True,
    }
    fields = item.attributes['homeplus_detail_source_fields']
    assert fields['sale']['salePrice'] == 2190 and fields['sale']['dcPrice'] == 0
    assert 'purchaseMinQty' not in fields['sale']
    assert fields['etc']['totalUnitQty'] == 12000 and fields['etc']['unitMeasure'] == 'ML'
    assert [row['discount'] for row in fields['promo']['couponList']] == [4000, 2000]
    assert fields['promo']['couponList'][0]['issueEndDt'] == '2026-10-07 23:59:59'
    assert item.valid_from is None and item.valid_until is None
    assert item.attributes['homeplus_detail_source_fields_sha256'] == hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.mark.asyncio
async def test_native_detail_public_purchase_declarations_are_retained_not_private_or_payable(native_detail_node, parsed_envelope):
    source_row = parsed_envelope['data']['dataList'][0]
    purchase_keys = [key for key in source_row if key.startswith('purchaseMin') or key.startswith('purchaseLimit')]
    for key in purchase_keys: native_detail_node['sale'][key] = source_row[key]
    native_detail_node['promo']['couponList'][0]['purchaseMin'] = 70000
    native_detail_node['promo']['couponList'][0]['couponNo'] = 'OPAQUE_DO_NOT_COPY'
    native_detail_node['partner'] = {'phone': 'PRIVATE_DO_NOT_COPY', 'email': 'PRIVATE_DO_NOT_COPY'}
    native_detail_node['account'] = {'token': 'PRIVATE_DO_NOT_COPY'}
    item = (await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}})))[0]
    fields = item.attributes['homeplus_detail_source_fields']
    assert all(fields['sale'][key] == source_row[key] for key in purchase_keys)
    assert fields['promo']['couponList'][0]['purchaseMin'] == 70000
    assert 'OPAQUE_DO_NOT_COPY' not in json.dumps(item.model_dump(mode="json"))
    assert 'PRIVATE_DO_NOT_COPY' not in json.dumps(item.model_dump(mode="json"))
    assert item.attributes['promotion_conditions']['minimum_purchase_quantity_unconfirmed'] is True
    assert item.attributes['promotion_conditions']['payable_price_unconfirmed'] is True
    assert item.price_per_100g is None


@pytest.mark.asyncio
@pytest.mark.parametrize('conflict', ['native', 'store', 'notice_native', 'contents', 'url_native', 'url_store', 'options', 'missing_options', 'malformed_depth'])
async def test_native_detail_rejects_context_or_unselected_option_conflicts(native_detail_node, conflict):
    url = _DETAIL_URL
    if conflict == 'native': native_detail_node['basic']['itemNo'] = 'not-a-059102628'
    if conflict == 'store': native_detail_node['basic']['storeType'] = 'EXP'
    if conflict == 'notice_native':
        native_detail_node['prop']['notice_rows_original_pointers'][1]['raw_fields']['noticeDesc'] = '062752109 (상품코드)'
    if conflict == 'contents': native_detail_node['etc']['totalUnitQty'] = 72000
    if conflict == 'url_native': url = _DETAIL_URL.replace('059102628', '062752109')
    if conflict == 'url_store': url = _DETAIL_URL.replace('HYPER', 'EXP')
    if conflict == 'options': native_detail_node['opt']['optSelUseYn'] = 'Y'
    if conflict == 'missing_options': native_detail_node.pop('opt')
    if conflict == 'malformed_depth': native_detail_node['opt']['optTitleDepth'] = False
    assert await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=url) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('quote,expected', [(2190.5, 2190.5), ('₩ 2,190.50원', 2190.5), (True, None), (False, None), ('행사 2개 2190원', None), (-2190, None), (float('inf'), None), ({'amount': 2190}, None)])
async def test_native_detail_money_never_truncates_or_harvests_invalid_quotes(native_detail_node, quote, expected):
    native_detail_node['sale']['salePrice'] = quote
    items = await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}))
    if expected is None:
        assert items == []
    else:
        assert len(items) == 1 and items[0].sale_price == expected
        assert items[0].attributes['source_record_key'] == '059102628'
        assert items[0].attributes['promotion_conditions']['payable_price_unconfirmed'] is True


@pytest.mark.asyncio
async def test_native_detail_does_not_mix_siblings_or_absent_notice_with_other_products(native_detail_node):
    unrelated = {'basic': native_detail_node['basic'], 'sale': {'salePrice': 1}, 'opt': native_detail_node['opt']}
    source = json.dumps({'data': {'item': {'basic': native_detail_node['basic']}, 'products': [unrelated]}})
    assert await HomeplusCrawler().parse(source, source_url=_DETAIL_URL) == []
    source = '<script type="application/json">' + json.dumps({'data': {'item': native_detail_node}}) + '</script>'
    source += '<script type="application/json">' + json.dumps({'data': {'item': unrelated}}) + '</script>'
    assert await HomeplusCrawler().parse(source, source_url=_DETAIL_URL) == []
    # Name retains the actual multiplier when the source does not supply a notice.
    native_detail_node.pop('prop')
    items = await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL)
    assert len(items) == 1 and items[0].attributes['bundle_count'] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['absent_item', 'malformed_dc', 'unread_event'])
async def test_native_detail_partial_markers_do_not_turn_other_rows_or_unknown_events_into_facts(native_detail_node, boundary):
    if boundary == 'absent_item':
        source = {'data': {'item': None, 'products': [native_detail_node]}}
    else:
        if boundary == 'malformed_dc': native_detail_node['sale']['dcPrice'] = True
        if boundary == 'unread_event': native_detail_node['promo']['eventInfo'] = {'opaqueEventNo': 'DO_NOT_COPY'}
        source = {'data': {'item': native_detail_node}}
    items = await HomeplusCrawler().parse(json.dumps(source), source_url=_DETAIL_URL)
    if boundary != 'unread_event':
        assert items == []
    else:
        assert len(items) == 1 and items[0].event_name == ''
        assert items[0].attributes['source_event_absent'] is False
        fields = items[0].attributes['homeplus_detail_source_fields']
        assert fields['event_markers']['promo_eventInfo_type'] == 'dict'
        assert fields['event_texts'] == []
        assert 'DO_NOT_COPY' not in json.dumps(items[0].model_dump(mode='json'))


@pytest.mark.asyncio
async def test_native_detail_overlong_contents_cannot_hide_conflicting_suffix(native_detail_node):
    for row in native_detail_node['prop']['notice_rows_original_pointers']:
        if row['raw_fields']['noticeNm'] == '포장단위별 내용물의 용량(중량), 수량':
            row['raw_fields']['noticeDesc'] = '2L * 6입' + ' ' * 260 + ' + 7L * 7입'
    assert await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('role,field,value', [
    ('sale', 'itemNo', '062752109'), ('sale', 'storeType', 'EXP'),
    ('opt', 'itemNo', '062752109'), ('prop', 'storeType', 'EXP'),
    ('etc', 'itemNo', '062752109'), ('promo', 'storeType', 'EXP'),
])
async def test_native_detail_sibling_native_store_conflict_rejects_same_container(native_detail_node, role, field, value):
    native_detail_node[role][field] = value
    assert await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL) == []


@pytest.mark.asyncio
async def test_native_detail_curated_basic_sale_coupon_facts_remain_complete(native_detail_node):
    item = (await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL))[0]
    fields = item.attributes['homeplus_detail_source_fields']
    assert fields['basic'] == native_detail_node['basic']
    assert fields['sale'] == native_detail_node['sale']
    assert fields['promo']['couponInfo'] == native_detail_node['promo']['couponInfo']
    assert fields['promo']['couponList'] == native_detail_node['promo']['couponList']
    assert item.sale_price == 2190 and item.promo_type is None
    assert item.attributes['promotion_conditions']['payable_price_unconfirmed'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('declaration,location,accepted', [
    ('simplus 물 2L*6 2팩', 'name', False),
    ('simplus 물 2L*6 6팩', 'name', False),
    ('simplus 물 2L*6 + 500ml', 'name', False),
    ('simplus 물 2L*6 6병', 'name', True),
    ('simplus 물 2L*6 + 6팩', 'name', False),
    ('simplus 물 2L*6 6병 6팩', 'name', False),
    ('2L * 6입 2팩', 'contents', False),
    ('2L * 6입 6병', 'contents', True),
])
async def test_native_detail_unconsumed_sold_count_is_held_not_multiplied(native_detail_node, declaration, location, accepted):
    for row in native_detail_node['prop']['notice_rows_original_pointers']:
        fields = row['raw_fields']
        if location == 'name' and fields['noticeNm'] == '상품명':
            fields['noticeDesc'] = declaration
        if location == 'contents' and fields['noticeNm'] == '포장단위별 내용물의 용량(중량), 수량':
            fields['noticeDesc'] = declaration
    if location == 'name':
        native_detail_node['basic']['itemNm'] = declaration
    items = await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL)
    if not accepted:
        assert items == []
    else:
        assert len(items) == 1
        assert items[0].package_quantity == 2 and items[0].package_unit == 'L'
        assert items[0].attributes['bundle_count'] == 6
        assert items[0].sale_price == 2190 and items[0].price_per_100g is None


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['oversized', 'oversized_trailing_conflict', 'duplicate_conflict', 'other_list_conflict', 'duplicate_equivalent', 'unparsed_contents'])
async def test_native_detail_checks_all_bounded_capacity_notices(native_detail_node, boundary):
    prop = native_detail_node['prop']
    rows = prop['notice_rows_original_pointers']
    capacity_name = '포장단위별 내용물의 용량(중량), 수량'
    if boundary.startswith('oversized'):
        rows.extend({'raw_fields': {'noticeNm': '기타', 'noticeDesc': 'product-only'}} for _ in range(41 - len(rows)))
        if boundary == 'oversized_trailing_conflict':
            rows[-1] = {'raw_fields': {'noticeNm': capacity_name, 'noticeDesc': '2L * 7입'}}
    elif boundary == 'unparsed_contents':
        rows.append({'raw_fields': {'noticeNm': capacity_name, 'noticeDesc': '별도 표기'}})
    else:
        additional = {'noticeNm': capacity_name, 'noticeDesc': '2000ml * 6병' if boundary == 'duplicate_equivalent' else '2L * 7입'}
        if boundary == 'other_list_conflict':
            prop['noticeList'] = [additional]
        else:
            rows.append({'raw_fields': additional})
    items = await HomeplusCrawler().parse(json.dumps({'data': {'item': native_detail_node}}), source_url=_DETAIL_URL)
    if boundary == 'duplicate_equivalent':
        assert len(items) == 1 and items[0].attributes['bundle_count'] == 6
        assert items[0].package_quantity * (1000 if items[0].package_unit == 'L' else 1) == 2000
        capacities = [row for row in items[0].attributes['homeplus_detail_source_fields']['notice'] if row['noticeNm'] == capacity_name]
        assert [row['noticeDesc'] for row in capacities] == ['2L * 6입', '2000ml * 6병']
    else:
        assert items == []


@pytest.mark.asyncio
@pytest.mark.parametrize('denied_status', [401, 403, 429])
@pytest.mark.parametrize('keep_first', [False, True])
async def test_access_denial_stops_source_run_without_retry_or_next_query(monkeypatch, raw_json, denied_status, keep_first):
    from types import SimpleNamespace
    import crawlers.marts.homeplus.crawler as module
    from core.models import CrawlStatus
    crawler = HomeplusCrawler()
    plan = [{'request_type': 'search', 'query': q, 'max_pages': 1} for q in ('one', 'two', 'three')]
    monkeypatch.setattr(crawler, '_build_source_requests', lambda: plan)
    monkeypatch.setattr(crawler, '_headers', lambda: {})
    monkeypatch.setattr(crawler, '_polite_sleep', lambda: None)
    monkeypatch.setattr(module.time, 'sleep', lambda _: pytest.fail('Access denial must not sleep/retry'))
    calls = []
    class LocalSession:
        closed = False
        def get(self, url, **kwargs):
            calls.append(url)
            if keep_first and len(calls) == 1:
                return SimpleNamespace(status_code=200, text=raw_json)
            return SimpleNamespace(status_code=denied_status, text='access denied')
        def close(self):self.closed = True
    local = LocalSession()
    monkeypatch.setattr(module.requests, 'Session', lambda: local)
    result = await crawler.crawl()
    assert len(calls) == (2 if keep_first else 1)
    assert local.closed
    assert result.status == (CrawlStatus.PARTIAL if keep_first else CrawlStatus.FAILED)
    assert result.items_count == (3 if keep_first else 0)
    assert result.quality_details['fetch']['source_distribution']['access_stop']['http_status'] == denied_status
    assert f'HTTP {denied_status}' in result.error_msg
    if keep_first:
        first_source = json.loads(raw_json)['data']['dataList'][0]
        assert result.items[0]['sale_price'] == (first_source['dcPrice'] or first_source['salePrice'])


@pytest.mark.asyncio
@pytest.mark.parametrize('receipt_kind', ['complete', 'missing', 'naive'])
async def test_parser_preserves_safe_business_node_and_actual_receipt(raw_json, receipt_kind):
    from datetime import datetime, timezone
    import hashlib
    stamp = datetime(2026, 10, 6, 4, 15, 43, 32158, tzinfo=timezone.utc)
    product = json.loads(raw_json)['data']['dataList'][0]
    product.update(cartLimitMax=2, customerSession={'token': 'do-not-export'},
                   opt={'optSelUseYn': 'N'}, prop={'noticeList': [{'noticeNm': '테스트 내용물', 'noticeDesc': 'test schema only'}]})
    body = json.dumps({'data': {'dataList': [product]}}, ensure_ascii=False)
    receipt = None if receipt_kind == 'missing' else {
        'response_url': HomeplusCrawler.SEARCH_API,
        'response_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'received_at': stamp if receipt_kind == 'complete' else stamp.replace(tzinfo=None)}
    item, = await HomeplusCrawler().parse(body, capture_receipt=receipt)
    exported = item.model_dump(mode='json')
    evidence, = exported['attributes']['submission_business_evidence']
    node = evidence['raw_product_node']
    assert node['opt'] == product['opt'] and node['prop'] == product['prop']
    assert node['cartLimitMax'] == 2 and 'customerSession' not in node
    assert evidence['removed_fields'] == [
        {'path': '/reviewCnt', 'reason': 'noncommercial_private_branch'},
        {'path': '/customerSession', 'reason': 'noncommercial_private_branch'}]
    assert evidence['source_pointer_kind'] == 'parser_selected_product_projection'
    assert evidence['raw_product_node_sha256'] == hashlib.sha256(json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert item.sale_price == (product['dcPrice'] or product['salePrice'])
    assert exported['attributes']['mart_native_code'] == product['itemNo']
    if receipt_kind == 'complete':
        assert item.crawled_at == stamp and datetime.fromisoformat(exported['crawled_at']) == stamp
        assert evidence['source_response_url'] == HomeplusCrawler.SEARCH_API
        assert evidence['source_response_body_sha256'] == receipt['response_body_sha256']
        assert evidence['source_response_received_at'] == stamp.isoformat()
    else:
        assert evidence['source_response_received_at'] is None and evidence['http_receipt_status'] == 'not_recorded'


@pytest.mark.asyncio
@pytest.mark.parametrize('has_receipt', [True, False])
async def test_http_transport_receipt_survives_crawl_serializer_without_default_clock(monkeypatch, raw_json, has_receipt):
    from types import SimpleNamespace
    from datetime import datetime
    import hashlib
    import crawlers.marts.homeplus.crawler as module
    crawler = HomeplusCrawler()
    crawler.MAX_ITEMS = 1  # Early cap must also close its owned HTTP session.
    monkeypatch.setattr(crawler, '_build_source_requests', lambda: [{'request_type': 'search', 'query': 'one', 'max_pages': 1}])
    monkeypatch.setattr(crawler, '_headers', lambda: {})
    calls = []
    class LocalSession:
        closed = False
        def get(self, url, **kwargs):
            calls.append(url)
            fields = {'status_code': 200, 'text': raw_json}
            if has_receipt:
                fields.update(content=raw_json.encode(), url=url+'?keyword=one')
            return SimpleNamespace(**fields)
        def close(self): self.closed = True
    session = LocalSession()
    monkeypatch.setattr(module.requests, 'Session', lambda: session)
    result = await crawler.crawl()
    assert len(calls) == 1 and session.closed and result.items_count == 1
    row = result.items[0]
    evidence, = row['attributes']['submission_business_evidence']
    native = json.loads(raw_json)['data']['dataList'][0]
    assert evidence['raw_product_node'] == {key: value for key, value in native.items() if key != 'reviewCnt'}
    assert evidence['removed_fields'] == [{'path': '/reviewCnt', 'reason': 'noncommercial_private_branch'}]
    assert row['sale_price'] == (native['dcPrice'] or native['salePrice'])
    if has_receipt:
        assert datetime.fromisoformat(row['crawled_at']).tzinfo is not None
        assert datetime.fromisoformat(row['crawled_at']) == datetime.fromisoformat(evidence['source_response_received_at'])
        assert evidence['source_response_body_sha256'] == hashlib.sha256(raw_json.encode()).hexdigest()
        assert evidence['source_response_url'] == calls[0]+'?keyword=one'
    else:
        assert 'crawled_at' not in row and evidence['http_receipt_status'] == 'not_recorded'
