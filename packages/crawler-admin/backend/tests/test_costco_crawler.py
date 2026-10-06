"""Costco parser and crawl contracts for the current first-party source."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawlers.marts.costco.crawler import (
    BASE_URL,
    CATEGORY_CODES,
    CostcoCrawler,
    CostcoCard,
    _card_to_record,
    _occ_pagination,
    cards_to_discount_items,
    parse_costco_listing,
    parse_costco_occ_response,
)


HTML_FIXTURE = Path(__file__).parent / "fixtures" / "costco" / "special_offers_5cards.html"
OCC_FIXTURE = Path(__file__).parent / "fixtures" / "costco" / "occ_products_3items.json"


@pytest.mark.parametrize(("title", "quantity", "count"), [
    ("순댓국 2,500g", 2500, None),
    ("국 1,060g x 2ea", 1060, 2),
    ("음료 240ml x 30 x 2팩", 240, 60),
    ("볶음밥300g x 7 x 2봉(4200g)", 300, 14),
])
def test_collection_preserves_complete_package_not_last_numeric_suffix(title, quantity, count):
    card = CostcoCard(name=title, sale_price=10000, original_price=None,
        unit_price_text=None, detail_url=BASE_URL + "/p/123", image_url=None,
        is_member_only=False, raw_html="", mart_native_code="123")
    record = _card_to_record(card)
    assert record["pack_qty"] == quantity
    assert record["bundle_count"] == count
    item = cards_to_discount_items([card], source_url=BASE_URL)[0]
    assert item.package_quantity == quantity
    assert item.attributes["bundle_count"] == count
    assert item.display_unit == record["display_unit"]
    exported = CostcoCrawler()._discount_item_to_product_record(item)
    assert exported["bundle_count"] == count
    assert exported["display_unit"] == record["display_unit"]


@pytest.fixture
def fixture_html() -> str:
    return HTML_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def occ_fixture() -> dict:
    return json.loads(OCC_FIXTURE.read_text(encoding="utf-8"))


def test_listing_maps_real_product_price_url_and_unit_evidence(fixture_html):
    cards = parse_costco_listing(fixture_html)
    assert cards

    first = cards[0]
    assert "바이오더마" in first.name
    assert first.sale_price == 35990.0
    assert first.detail_url and first.detail_url.startswith("https://www.costco.co.kr")
    assert first.image_url
    assert first.unit_price_text and "3,099" in first.unit_price_text
    assert isinstance(first.is_member_only, bool)


def test_listing_conversion_keeps_costco_source_identity(fixture_html):
    cards = parse_costco_listing(fixture_html)
    items = cards_to_discount_items(
        cards,
        source_url="https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers",
    )
    assert items

    item = items[0]
    assert item.store == "코스트코"
    assert item.sale_price == 35990.0
    assert item.attributes["source_name"] == "costco"
    assert item.attributes["source_record_key"]
    assert item.attributes["source_url"].startswith("https://www.costco.co.kr")


def test_registry_contains_current_costco_source():
    from crawlers.registry.registry import CrawlerRegistry

    registry = CrawlerRegistry()
    registry.discover()

    assert "costco" in registry._registry
    assert registry._registry["costco"]["config"]["display_name"] == "코스트코"


@pytest.mark.asyncio
async def test_validate_rejects_non_positive_price_rows(fixture_html):
    crawler = CostcoCrawler()
    items = await crawler.parse(fixture_html)
    valid = await crawler.validate(items)

    assert valid
    assert all(item.sale_price > 0 and len(item.name) >= 2 for item in valid)


def test_occ_response_maps_price_identity_and_original_price(occ_fixture):
    cards = parse_costco_occ_response(occ_fixture)
    assert cards

    first = cards[0]
    assert "바이오더마" in first.name
    assert first.sale_price == 35990.0
    assert first.detail_url and first.detail_url.startswith("https://www.costco.co.kr")

    discounted = next(card for card in cards if card.original_price is not None)
    assert discounted.original_price > discounted.sale_price


def test_occ_empty_payload_and_pagination_are_safe(occ_fixture):
    assert parse_costco_occ_response({}) == []
    assert parse_costco_occ_response({"products": []}) == []

    current, total = _occ_pagination(occ_fixture)
    assert current >= 0
    assert total >= 1
    assert _occ_pagination({}) == (0, 1)


def test_occ_conversion_keeps_public_costco_source(occ_fixture):
    items = cards_to_discount_items(
        parse_costco_occ_response(occ_fixture),
        source_url="https://www.costco.co.kr/c/FoodandBeverage",
    )

    assert items
    assert all(item.store == "코스트코" for item in items)
    assert all(item.attributes["source_name"] == "costco" for item in items)


@pytest.mark.asyncio
async def test_crawl_with_saved_html_exercises_current_source_path(fixture_html):
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0
    first_path, _first_code = CATEGORY_CODES[0]
    crawler._mock_html_map = {f"{BASE_URL}/{first_path}": fixture_html}
    crawler.MAX_REQUESTS = 1

    result = await crawler.crawl()

    assert result.status.name == "SUCCESS"
    assert result.items_count > 0
    assert result.quality_details["source_map"]["parser_contract"].startswith("costco_storefront")


@pytest.mark.asyncio
async def test_crawl_with_no_source_rows_is_not_reported_as_success():
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0
    crawler._mock_occ_responses = {}

    result = await crawler.crawl()

    assert result.status.name in {"PARTIAL", "FAILED"}
    assert result.items_count == 0


@pytest.mark.asyncio
async def test_live_occ_request_budget_prevents_unbounded_fallback(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"products": [], "pagination": {"currentPage": 0, "totalPages": 1}}

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return Response()

    monkeypatch.setattr("requests.Session.get", fake_get)
    crawler = CostcoCrawler()
    crawler.MAX_REQUESTS = 2

    result = await crawler.crawl()

    assert len(calls) == 2
    assert result.items_count == 0
    assert result.quality_details["public_endpoints_attempted"] == 2
    assert result.quality_details["fetch"]["pages_attempted"] == 2


def test_source_child_skus_survive_html_occ_dedup_and_export_without_parent_alias():
    from crawlers.marts.source_utils import source_dedup_key
    codes = ['641176','641176-K2','641176-K6','780235-FP','697186-PG','697186-TL','642459-CHE4','642459-PPR4']
    # Exact native suffix families published by the source. Equal names/prices
    # must not collapse distinct options, and suffix digits are not quantities.
    products = [{'code':code,'url':f'/Foods/Selection/p/{code}','name':'검수 선택 상품',
                 'price':{'value':10000}} for code in codes]
    occ = parse_costco_occ_response({'products':products})
    html = ''.join(f'<li class="product-list-item"><a href="/Foods/Selection/p/{code}?utm=source">검수 선택 상품</a><span class="product-price-amount">10,000원</span></li>' for code in codes)
    cards = parse_costco_listing(html)
    assert [card.mart_native_code for card in occ] == codes
    assert [card.mart_native_code for card in cards] == codes
    for group in [occ,cards]:
        items = cards_to_discount_items(group,source_url=BASE_URL)
        assert len({source_dedup_key(item) for item in items}) == len(codes)
        for code,item in zip(codes,items):
            exported = CostcoCrawler()._discount_item_to_product_record(item)
            assert exported['mart_native_code'] == code
            assert exported['source_record_key'] == code
            assert exported['canonical_url'] == f'{BASE_URL}/Foods/Selection/p/{code}'
            assert exported['pack_qty'] is None and exported['pack_unit'] is None
    changed = [{**product,'price':{'value':12000}} for product in products]
    assert [card.mart_native_code for card in parse_costco_occ_response({'products':changed})] == codes


@pytest.mark.parametrize('code,url,expected', [
    ('641176-K2','/Foods/p/641176-K2','641176-K2'),
    ('','/Foods/p/641176-K2','641176-K2'),
    ('641176-K2','','641176-K2'),
    ('641176','/Foods/p/641176-K2',None),
    ('641176-K2','/Foods/p/641176-K6',None),
    ('junk641176-K2','/Foods/p/641176-K2',None),
    ('641176-K2','https://other.example/Foods/p/641176-K2',None),
    ('','/Foods/p/641176-K2.txt',None),
    ('641176-K2','/Foods/p/641176-K2/another',None),
])
def test_occ_native_code_and_url_are_concordant_or_rejected(code,url,expected):
    cards = parse_costco_occ_response({'products':[{'code':code,'url':url,'name':'검수 선택 상품','price':{'value':10000}}]})
    assert [card.mart_native_code for card in cards] == ([] if expected is None else [expected])
