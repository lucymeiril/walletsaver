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
