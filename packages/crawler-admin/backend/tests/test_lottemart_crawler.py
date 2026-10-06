"""Lotte Mart parser contracts using saved source-shaped fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from crawlers.marts.lottemart.crawler import LottemartCrawler


FIXTURE = Path(__file__).parent / "fixtures" / "lottemart" / "listing_3cards.html"
HYDRATED_FIXTURE = Path(__file__).parent / "fixtures" / "lottemart" / "hydrated_5cards.html"


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def hydrated_html() -> str:
    return HYDRATED_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def crawler() -> LottemartCrawler:
    return LottemartCrawler()


@pytest.fixture
def query_product():
    root = Path(__file__).resolve().parents[4]
    capture = json.loads((root / '.debug-artifacts/review-proposals/continuation224-lotte-source-product-capture.json').read_text())
    return capture['product_nodes'][1]['raw_product_before_interpretation']


def _query_html(products):
    payload = {'queries': [{'state': {'data': {'product': product}}} for product in products]}
    return '<script>window.__QUERY_INITIAL_STATE__ = ' + json.dumps(payload, ensure_ascii=False) + ';</script>'


_QUERY_TARGET = 'https://lottemartzetta.com/products/OS0000049320367/details'


@pytest.mark.asyncio
@pytest.mark.parametrize('amount', ['3900', '4100.5'])
async def test_query_detail_retains_source_quote_spec_and_conditional_terms(crawler, query_product, amount):
    import hashlib
    query_product['price']['amount'] = amount
    # User/basket/review state must not become a source context.
    query_product.update(quantityInBasket=9, basketLines=[{'token': 'PRIVATE'}], ratingSummary={'rating': 5})
    result = await crawler._crawl_saved_source_input(_query_html([query_product]), source_url=_QUERY_TARGET)
    assert result.items_count == 1
    item = result.items[0]
    assert item['name'] == query_product['name']
    assert item['sale_price'] == float(amount) and item['original_price'] is None
    assert item['package_quantity'] == 140 and item['package_unit'] == 'ml'
    assert item['detail_url'] == _QUERY_TARGET
    assert item['attributes']['source_record_key'] == '0000049320367'
    assert item['event_name'] == '3개씩 골라 담으면, 그 중 1개는 무료'
    assert item['promo_type'] is None and item['promo_label'] is None
    assert item['discount_percent'] is None and item['price_per_100g'] is None
    assert 'promotion_conditions' not in item['attributes'] and 'final_price' not in item
    source = item['attributes']['lottemart_detail_source_fields']
    assert source['price'] == query_product['price']
    assert source['promotions'] == query_product['promotions']
    assert source['quantityRestrictionGroup'] == query_product['quantityRestrictionGroup']
    assert source['unitPrice'] == query_product['unitPrice']
    assert 'PRIVATE' not in json.dumps(item) and 'ratingSummary' not in source
    assert item['attributes']['lottemart_detail_source_pointer'].endswith('/queries/0/state/data/product')
    assert item['attributes']['lottemart_detail_source_fields_sha256'] == hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['wrong_native', 'missing_native', 'wrong_href', 'currency', 'bool_money', 'malformed_money', 'missing_amount', 'conflicting_price_branch', 'pack_conflict', 'extra_count', 'extra_measure', 'overlong_spec', 'required_bool', 'required_float', 'required_conflict', 'duplicate_price_conflict', 'duplicate_spec_conflict'])
async def test_query_detail_rejects_unbound_or_conflicting_source_without_fallback(crawler, query_product, boundary):
    products = [query_product]
    if boundary == 'wrong_native': query_product['retailerProductId'] = 'OS8809251334528'
    if boundary == 'missing_native': query_product.pop('retailerProductId')
    if boundary == 'wrong_href': query_product['url'] = 'https://lottemartzetta.com/products/OS8809251334528/details'
    if boundary == 'currency': query_product['price']['currency'] = 'USD'
    if boundary == 'bool_money': query_product['price']['amount'] = True
    if boundary == 'malformed_money': query_product['price']['amount'] = '행사3900원'
    if boundary == 'missing_amount': query_product['price'].pop('amount')
    if boundary == 'conflicting_price_branch': query_product['price']['current'] = {'amount': '1'}
    if boundary == 'pack_conflict': query_product['packSizeDescription'] = '330ml'
    if boundary == 'extra_count': query_product['name'] += ' 2팩'
    if boundary == 'extra_measure': query_product['name'] += ' 500ml'
    if boundary == 'overlong_spec': query_product['packSizeDescription'] = '140ml' + ' ' * 256 + '*2'
    if boundary.startswith('required_'): query_product['promotions'][0]['requiredProductQuantity'] = {'required_bool': True, 'required_float': 3.0, 'required_conflict': 2}[boundary]
    if boundary.startswith('duplicate_'):
        second = deepcopy(query_product)
        if boundary == 'duplicate_price_conflict': second['price']['amount'] = '4100'
        else: second['packSizeDescription'] = '330ml'
        products.append(second)
    # A legacy/JSON-LD-style source cannot erase rejected modern conditions.
    fallback = '<script>window.__INITIAL_STATE__ = ' + json.dumps({'productEntities': {'x': _API_PRODUCT_SAMPLE}}) + ';</script>'
    result = await crawler._crawl_saved_source_input(_query_html(products) + fallback, source_url=_QUERY_TARGET)
    assert result.items == [] and result.items_count == 0
    assert json.loads(result.raw_data)['schema_marker'] == 'query_state_product'


@pytest.mark.asyncio
async def test_query_detail_preserves_original_name_and_extra_source_qualification(crawler, query_product):
    query_product['name'] = '[조건부행사] ' + query_product['name']
    promo = query_product['promotions'][0]
    promo.update(conditionText='동일 행사 상품 중 선택', membershipRequired=None, couponRequired=None, paymentCardText='조건 확인 필요')
    result = await crawler._crawl_saved_source_input(_query_html([query_product, deepcopy(query_product)]), source_url=_QUERY_TARGET)
    assert result.items_count == 1
    item = result.items[0]
    assert item['name'] == query_product['name']
    assert item['attributes']['lottemart_detail_source_fields']['promotions'][0] == promo
    assert 'promotion_conditions' not in item['attributes'] and item['promo_type'] is None


@pytest.mark.asyncio
async def test_parser_maps_price_category_and_stable_identity(crawler, html):
    items = await crawler.parse(html)
    assert items

    water = next(item for item in items if "생수" in item.name)
    assert water.sale_price == 2990
    assert water.original_price == 3990
    assert water.detail_url == "https://lottemartzetta.com/products/OS8801045440040/details"
    assert water.category == "생수/음료"
    assert water.event_name == "주간특가"
    assert water.attributes["source_record_key"] == "8801045440040"
    assert water.attributes["mart_native_code"] == "8801045440040"
    assert water.attributes["external_seller"] is False
    assert water.attributes["category_path"] == ["생수/음료", "생수"]


@pytest.mark.asyncio
async def test_parser_does_not_invent_invalid_prices_or_promo_prefixes(crawler, html):
    items = await crawler.parse(html)

    assert all(item.sale_price > 0 for item in items)
    assert all(item.original_price is None or item.original_price >= item.sale_price for item in items)
    laundry = next(item for item in items if "테크" in item.name)
    assert not laundry.name.startswith("[")


@pytest.mark.asyncio
async def test_hydrated_fixture_keeps_ean_identity_and_price_branches(crawler, hydrated_html):
    items = await crawler.parse(hydrated_html)
    assert items

    for item in items:
        code = item.attributes.get("source_record_key", "")
        assert code and code.isdigit() and len(code) == 13
        assert item.attributes.get("mart_native_code") == code
        assert item.detail_url == f"https://lottemartzetta.com/products/OS{code}/details"
        assert item.sale_price > 0
        assert item.attributes.get("category_path")

    discounted = [item for item in items if item.original_price and item.original_price > item.sale_price]
    sale_only = [item for item in items if item.original_price is None]
    assert discounted
    assert sale_only


@pytest.mark.asyncio
async def test_requests_waf_result_is_failed_without_fake_success(monkeypatch):
    import requests as requests_module

    waf_body = '<html><body>awswaf challenge awsWafCookieDomainList</body></html>'

    class WafResponse:
        status_code = 202
        text = waf_body
        content = waf_body.encode()

    monkeypatch.setattr(requests_module.Session, "get", lambda self, url, **kwargs: WafResponse())
    crawler = LottemartCrawler()
    crawler.SEARCH_QUERIES = ["할인"]
    crawler.CATEGORY_QUERIES = []
    crawler.MAX_PAGES = 1

    result = await crawler.crawl()

    assert result.status.name == "FAILED"
    assert result.quality_details["fetch"]["blocked"] is True
    assert result.quality_details["fetch"]["auth_bypass_attempted"] is False


_API_PRODUCT_SAMPLE = {
    "productId": "8660fc78-ce61-42f8-856e-645d9984ef30",
    "retailerProductId": "OS8809251334528",
    "type": "REGULAR",
    "name": "오늘좋은 닭가슴살 블랙페퍼 (110G)",
    "brand": "오늘좋은",
    "packSizeDescription": "110g",
    "price": {"amount": "3590", "currency": "KRW"},
    "promotions": [
        {
            "promoId": "4430dfd8-1295-4785-8181-cc352b3dd892",
            "description": "2개씩 골라 담으면, 그 중 1개는 무료",
            "type": "OFFER",
        }
    ],
    "image": {
        "src": "https://lottemartzetta.com/images-v3/932dcbc7/a5acf33b/300x300.jpg",
        "description": "오늘좋은 닭가슴살 블랙페퍼 (110G)",
    },
}


def test_xhr_product_shape_maps_to_discount_item():
    item = LottemartCrawler()._api_product_to_discount_item(_API_PRODUCT_SAMPLE)

    assert item is not None
    assert item.name == "오늘좋은 닭가슴살 블랙페퍼 (110G)"
    assert item.sale_price == 3590
    assert item.original_price is None
    assert "무료" in item.event_name
    assert item.detail_url == "https://lottemartzetta.com/products/OS8809251334528/details"
    assert item.attributes["source_record_key"] == "8809251334528"
    assert item.attributes["mart_native_code"] == "8809251334528"
    assert item.attributes["external_seller"] is False


def test_xhr_product_without_promotion_uses_neutral_default_label():
    product = dict(_API_PRODUCT_SAMPLE)
    product["promotions"] = []

    item = LottemartCrawler()._api_product_to_discount_item(product)

    assert item is not None
    assert item.event_name == "롯데마트 할인"


_TARGET_URL = "https://lottemartzetta.com/products/OS8801045440040/details"


@pytest.mark.asyncio
async def test_exact_product_capture_binds_native_before_conversion(crawler, html):
    import hashlib
    import json

    result = await crawler.crawl_incremental(source_input=html, source_url=_TARGET_URL)
    assert result.status.name == "SUCCESS"
    assert result.items_count == 1
    assert result.items[0]["attributes"]["source_record_key"] == "8801045440040"
    diagnostic = json.loads(result.raw_data)
    assert diagnostic["diagnostic_kind"] == "lottemart_exact_product_parse"
    assert diagnostic["source_candidate_count"] == 3
    assert diagnostic["exact_native_candidate_count"] == 1
    captured = diagnostic["matched_candidate_fields"]
    assert captured[0]["price.current.amount"] == "2,990"
    assert captured[0]["retailerProductId"] == "OS8801045440040"
    assert diagnostic["captured_fields_sha256"] == hashlib.sha256(json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert not {"products", "items", "raw_items"}.intersection(diagnostic)
    # The same listing remains unpartitioned when the request is not a product URL.
    category_result = await crawler.crawl_incremental(source_input=html, source_url="https://lottemartzetta.com/search?q=생수")
    assert category_result.items_count == 3
    assert category_result.raw_data is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["wrong_native", "missing_native", "wrong_href", "foreign_href", "conflicting_native", "private_namespace"])
async def test_exact_product_rejects_unbound_recommendation_and_private_rows(crawler, mutation):
    import json

    row = dict(_API_PRODUCT_SAMPLE)
    target = "https://lottemartzetta.com/products/OS8809251334528/details"
    if mutation == "wrong_native": row["retailerProductId"] = "OS8801045440040"
    if mutation == "missing_native": row.pop("retailerProductId")
    if mutation == "wrong_href": row["url"] = "/products/OS8801045440040/details"
    if mutation == "foreign_href": row["url"] = "https://unrelated.test/products/OS8809251334528/details"
    if mutation == "conflicting_native": row["stdGoodsCd"] = "8801045440040"
    payload = {"productGroups": [{"decoratedProducts": [row]}]}
    if mutation == "private_namespace": payload = {"cart": {"products": [row]}}
    result = await crawler.crawl_incremental(source_input=json.dumps(payload), source_url=target)
    assert result.status.name == "FAILED"
    assert result.items == []
    diagnostic = json.loads(result.raw_data)
    assert diagnostic["exact_native_candidate_count"] == 0
    assert "matched_candidate_fields" not in diagnostic
    assert "captured_fields_sha256" not in diagnostic
    assert "8809251334528" not in result.raw_data
    assert result.error_msg.startswith("LotteMart zero valid rows:")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["source_zero_raw_rows", "parse_filtered_all_raw_rows", "validation_rejected_all_rows"])
async def test_exact_product_zero_keeps_actual_quality_stage(crawler, monkeypatch, stage):
    import json

    row = dict(_API_PRODUCT_SAMPLE)
    if stage == "source_zero_raw_rows":
        source = '<html><head><title>Expected target name is not source evidence</title></head><body></body></html>'
    else:
        row["price"] = {"amount": True if stage == "parse_filtered_all_raw_rows" else "3590"}
        row["review"] = {"account": "DO_NOT_CAPTURE"}
        row["image"] = {"src": "https://example.test/image?token=DO_NOT_CAPTURE"}
        source = json.dumps({"productGroups": [{"decoratedProducts": [row]}]})
    if stage == "validation_rejected_all_rows":
        async def reject(_items): return []
        monkeypatch.setattr(crawler, "validate", reject)
    result = await crawler.crawl_incremental(source_input=source, source_url="https://lottemartzetta.com/products/OS8809251334528/details")
    assert result.status.name == "FAILED"
    assert result.quality_details["zero_result_diagnostic"]["stage"] == stage
    assert stage in result.error_msg
    assert "DO_NOT_CAPTURE" not in result.raw_data
    diagnostic = json.loads(result.raw_data)
    if stage == "parse_filtered_all_raw_rows":
        assert diagnostic["matched_candidate_fields"][0]["price.amount"] is True
        assert diagnostic["counts"]["parsed"] == 0
    if stage == "validation_rejected_all_rows":
        assert diagnostic["counts"]["parsed"] == 1
        assert diagnostic["counts"]["invalid_or_dropped"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["sdk_only", "visible_challenge", "zero", "http403", "http429"])
async def test_exact_product_http_boundary_is_one_normal_read(crawler, html, monkeypatch, kind):
    import requests

    body = html + '<script>awsWafCookieDomainList = []; captchaSDK = {};</script>' if kind == "sdk_only" else '<html><body>Verify you are human</body></html>' if kind == "visible_challenge" else '<html><body></body></html>'
    status = 403 if kind == "http403" else 429 if kind == "http429" else 200
    calls = []
    class Response:
        status_code = status
        text = body
        content = body.encode()
    def get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    def no_sleep(_seconds): raise AssertionError("single-read boundary must not back off/retry")
    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr("crawlers.marts.lottemart.crawler.time.sleep", no_sleep)
    result = await crawler.crawl_incremental(source_url=_TARGET_URL)
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False
    assert result.quality_details["fetch"]["auth_bypass_attempted"] is False
    if kind == "sdk_only":
        assert result.status.name == "SUCCESS"
        assert result.items_count == 1
        assert not result.quality_details["fetch"].get("blocked")
    else:
        assert result.status.name == "FAILED"
        assert result.items == []
        assert result.error_msg
        if kind == "zero":
            assert "source_zero_raw_rows" in result.error_msg
            assert not result.errors
            assert not result.quality_details["fetch"].get("blocked")
        elif kind == "visible_challenge":
            assert result.quality_details["fetch"]["blocked"] is True
        else:
            assert f"HTTP {status}" in result.error_msg


@pytest.mark.parametrize("quote", [True, False, {"amount": 3590}, "행사 2개 3590원", "2026-10-04", "3,59원", "NaN", float("inf")])
@pytest.mark.parametrize("shape", ["entity", "api", "generic"])
def test_source_money_rejects_malformed_quotes_before_conversion(crawler, quote, shape):
    row = dict(_API_PRODUCT_SAMPLE)
    if shape == "entity":
        row["price"] = {"current": {"amount": quote}}
        item = crawler._entity_to_discount_item(row)
    elif shape == "api":
        row["price"] = {"amount": quote}
        item = crawler._api_product_to_discount_item(row)
    else:
        row["price"] = quote
        item = crawler._json_to_discount_item(row)
    assert item is None


@pytest.mark.parametrize("quote,expected", [("₩ 3,590 원", 3590), ("4590", 4590), (3590, 3590), (3590.5, 3590.5), ("3,590.50원", 3590.5)])
def test_source_money_valid_quote_change_preserves_native_identity(crawler, quote, expected):
    row = dict(_API_PRODUCT_SAMPLE)
    row["price"] = {"amount": quote}
    item = crawler._api_product_to_discount_item(row)
    assert item is not None
    assert item.sale_price == expected
    assert item.attributes["source_record_key"] == "8809251334528"
    assert item.detail_url == "https://lottemartzetta.com/products/OS8809251334528/details"
    assert item.package_quantity == 110
    assert item.package_unit == "g"


@pytest.mark.asyncio
@pytest.mark.parametrize("quote,valid", [("₩ 3,590원", True), ("3590.50원", True), ("행사 2개 3590원", False)])
async def test_exact_product_existing_html_card_money_and_capture(crawler, quote, valid):
    import json

    source = f'''<div class="product-item" data-category="정육">
      <a href="/products/OS8809251334528/details?tracking=DO_NOT_CAPTURE"><h3>오늘좋은 닭가슴살 (110G)</h3></a>
      <span class="sale_price">{quote}</span></div>
      <div class="product-item"><a href="/products/OS8801045440040/details"><h3>추천 생수</h3></a><span class="sale_price">2990원</span></div>'''
    result = await crawler.crawl_incremental(source_input=source, source_url="https://lottemartzetta.com/products/OS8809251334528/details")
    assert result.items_count == int(valid)
    diagnostic = json.loads(result.raw_data)
    assert diagnostic["schema_marker"] == "html_cards"
    assert diagnostic["source_candidate_count"] == 2
    assert diagnostic["exact_native_candidate_count"] == 1
    assert diagnostic["matched_candidate_fields"][0]["salePrice"] == quote
    assert diagnostic["matched_candidate_fields"][0]["category"] == "정육"
    assert "DO_NOT_CAPTURE" not in result.raw_data
    assert diagnostic["counts"]["valid"] == int(valid)
    if valid: assert result.items[0]["sale_price"] == (3590.5 if ".50" in quote else 3590)


@pytest.mark.asyncio
async def test_exact_product_capture_is_bounded_and_handles_malformed_branch(crawler):
    import json

    row = dict(_API_PRODUCT_SAMPLE)
    row["price"] = {"current": "malformed 3590"}
    row["name"] = row["name"] + "x" * 300
    source = json.dumps({"productEntities": {str(index): row for index in range(8)}})
    result = await crawler.crawl_incremental(source_input=source, source_url="https://lottemartzetta.com/products/OS8809251334528/details")
    diagnostic = json.loads(result.raw_data)
    assert result.items_count == 0
    assert diagnostic["exact_native_candidate_count"] == 8
    assert diagnostic["capture_truncated"] is True
    assert len(diagnostic["matched_candidate_fields"]) == 5
    assert len(diagnostic["matched_candidate_fields"][0]["name"]) == 256
    assert diagnostic["matched_candidate_fields"][0]["price.current"] == "malformed 3590"
    assert diagnostic["conversion_exception_count"] == 0


@pytest.mark.parametrize("shape", ["api", "generic"])
def test_source_money_false_or_malformed_primary_does_not_fall_back(crawler, shape):
    row = dict(_API_PRODUCT_SAMPLE)
    if shape == "api":
        row["price"] = {"amount": False}
        row["salePrice"] = 3590
        assert crawler._api_product_to_discount_item(row) is None
    else:
        row["price"] = {"current": "invalid quote"}
        row["salePrice"] = False
        row["sellprc"] = 3590
        assert crawler._json_to_discount_item(row) is None


@pytest.mark.asyncio
async def test_exact_product_actual_href_is_native_evidence_without_map_key_injection(crawler):
    import hashlib
    import json

    row = dict(_API_PRODUCT_SAMPLE)
    row.pop("retailerProductId")
    row["url"] = "/products/OS8809251334528/details?tracking=DO_NOT_CAPTURE"
    source = json.dumps({"productGroups": [{"decoratedProducts": [row]}]})
    result = await crawler.crawl_incremental(source_input=source, source_url="https://lottemartzetta.com/products/OS8809251334528/details")
    assert result.items_count == 1
    assert result.items[0]["attributes"]["ean_source_key"] == "href"
    diagnostic = json.loads(result.raw_data)
    captured = diagnostic["matched_candidate_fields"]
    assert "retailerProductId" not in captured[0]
    assert "url" in captured[0]["field_names"]
    assert "DO_NOT_CAPTURE" not in result.raw_data
    assert diagnostic["counts"]["valid"] == 1
    assert diagnostic["captured_fields_sha256"] == hashlib.sha256(json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # A productEntities dictionary key alone is never a declared native reference.
    row.pop("url")
    row["price"] = {"current": {"amount": "3590"}}
    unbound = await crawler.crawl_incremental(source_input=json.dumps({"productEntities": {"OS8809251334528": row}}), source_url="https://lottemartzetta.com/products/OS8809251334528/details")
    assert unbound.items_count == 0
    assert json.loads(unbound.raw_data)["exact_native_candidate_count"] == 0
