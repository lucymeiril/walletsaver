"""Costco parser and crawl contracts for the current first-party source."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawlers.marts.costco.crawler import (
    BASE_URL,
    CATEGORY_CODES,
    CostcoCrawler,
    _occ_pagination,
    cards_to_discount_items,
    parse_costco_listing,
    parse_costco_occ_response,
)


HTML_FIXTURE = Path(__file__).parent / "fixtures" / "costco" / "special_offers_5cards.html"
OCC_FIXTURE = Path(__file__).parent / "fixtures" / "costco" / "occ_products_3items.json"


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
    assert item.attributes["collection_path"] == "public_endpoint"


def test_operator_capture_keeps_capture_provenance(fixture_html):
    items = CostcoCrawler().ingest_operator_capture(
        fixture_html,
        source_url="https://www.costco.co.kr/member-area",
        capture_id="op-1",
    )

    assert items
    assert all(item.attributes["collection_path"] == "operator_capture" for item in items)
    assert items[0].attributes["operator_capture_id"] == "op-1"


def test_registry_contains_current_costco_source():
    from crawlers.registry.registry import CrawlerRegistry

    registry = CrawlerRegistry()
    registry.discover()

    assert "costco" in registry._registry
    assert registry._registry["costco"]["config"]["display_name"] == "코스트코"


def test_costco_first_party_crawler_does_not_depend_on_removed_cocodalin():
    import inspect
    from crawlers.marts.costco import crawler as module

    assert "cocodalin" not in inspect.getsource(module).lower()


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
    assert all(item.attributes["collection_path"] == "public_endpoint" for item in items)


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
