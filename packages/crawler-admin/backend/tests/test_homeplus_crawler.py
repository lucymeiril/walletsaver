"""Homeplus parser contracts using representative saved mfront API responses.

These tests protect field mapping and failure behaviour.  They intentionally do
not encode historical crawl-volume targets, project phases, or live-probe counts.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from crawlers.marts.entry_points import CollectionPath, CrawlIntent
from crawlers.marts.homeplus.entrypoints import (
    HomeplusEntrypoints,
    SALE_QUERY,
    _try_parse_mfront_envelope,
)


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


def test_envelope_maps_real_name_price_identity_and_detail_url(raw_json, parsed_envelope):
    items = _try_parse_mfront_envelope(raw_json)
    raw_first = parsed_envelope["data"]["dataList"][0]

    assert items is not None
    assert len(items) == len(parsed_envelope["data"]["dataList"])
    first = items[0]
    assert first.name == raw_first["itemNm"]
    assert first.sale_price == int(raw_first["salePrice"])
    assert first.detail_url.startswith("https://mfront.homeplus.co.kr/item?itemNo=")
    assert first.attributes["doc_id"] == raw_first["docId"]
    assert first.attributes["item_no"] == raw_first["itemNo"]
    assert first.attributes["source_record_key"]


def test_envelope_does_not_invent_discount_price(raw_json):
    items = _try_parse_mfront_envelope(raw_json)
    assert items is not None
    assert all(item.sale_price > 0 for item in items)
    assert all(item.original_price is None for item in items)


def test_envelope_rejects_unrelated_payloads():
    assert _try_parse_mfront_envelope('{"returnStatus":500,"data":{}}') is None
    assert _try_parse_mfront_envelope("<html>not json</html>") is None
    assert _try_parse_mfront_envelope("[]") is None


@pytest.mark.asyncio
async def test_sale_listing_marks_public_sale_source(raw_json):
    result = await HomeplusEntrypoints().crawl_sale_listing(fetch=lambda _url: raw_json)

    assert result.status.name == "SUCCESS"
    assert result.items
    assert quote(SALE_QUERY) in result.quality_details["entrypoint"]["source_url"]
    for item in result.items:
        assert item["attributes"]["collection_path"] == CollectionPath.PUBLIC_ENDPOINT.value
        assert item["attributes"]["crawl_intent"] == CrawlIntent.SALE.value


@pytest.mark.asyncio
async def test_catalog_and_single_product_entrypoints_keep_intent_and_identity(raw_json):
    entrypoints = HomeplusEntrypoints()
    catalog = await entrypoints.crawl_catalog_page("우유", page=2, fetch=lambda _url: raw_json)
    single = await entrypoints.fetch_single_product("068769294", fetch=lambda _url: raw_json)

    assert catalog.quality_details["query"] == "우유"
    assert catalog.quality_details["page"] == 2
    assert all(item["attributes"]["crawl_intent"] == "catalog" for item in catalog.items)
    assert "itemNo=068769294" in single.quality_details["entrypoint"]["source_url"]
    assert all(item["attributes"]["crawl_intent"] == "refresh" for item in single.items)


@pytest.mark.asyncio
async def test_operator_capture_keeps_capture_provenance(raw_json):
    result = await HomeplusEntrypoints().ingest_operator_capture(
        raw_json,
        source_url="https://mfront.homeplus.co.kr/search?keyword=할인",
        capture_id="op-homeplus-001",
    )

    assert result.quality_details["operator_capture"] is True
    assert result.quality_details["source_host"] == "mfront.homeplus.co.kr"
    assert all(item["attributes"]["operator_capture_id"] == "op-homeplus-001" for item in result.items)


@pytest.mark.asyncio
async def test_empty_or_spa_shell_payload_reports_failure_reason():
    entrypoints = HomeplusEntrypoints()
    empty = json.dumps({"returnStatus": 200, "data": {"dataList": []}})
    empty_result = await entrypoints.crawl_sale_listing(fetch=lambda _url: empty)
    shell_result = await entrypoints.crawl_catalog_page(
        "우유",
        fetch=lambda _url: "<html><body><div id='__next'></div></body></html>",
    )

    assert empty_result.items_count == 0
    assert empty_result.errors
    assert "empty_mfront_datalist" in empty_result.errors[0].error_msg
    assert shell_result.items_count == 0
    assert shell_result.errors
    assert any(
        marker in shell_result.errors[0].error_msg
        for marker in ("spa_shell_no_embedded_json", "no_recognised_payload")
    )


def test_dc_price_branch_maps_discount_and_regular_price_correctly(dc_mixed_raw, dc_mixed_envelope):
    items = _try_parse_mfront_envelope(dc_mixed_raw)
    assert items is not None
    by_no = {item.attributes["item_no"]: item for item in items}

    discounted_rows = [row for row in dc_mixed_envelope["data"]["dataList"] if row.get("dcPrice") is not None]
    regular_rows = [row for row in dc_mixed_envelope["data"]["dataList"] if row.get("dcPrice") is None]
    assert discounted_rows, "fixture must exercise the dcPrice branch"
    assert regular_rows, "fixture must exercise the regular-price branch"

    for raw in discounted_rows:
        item = by_no[raw["itemNo"]]
        assert item.sale_price == int(raw["dcPrice"])
        assert item.original_price == int(raw["salePrice"])
        assert item.original_price > item.sale_price
        assert item.discount_percent is not None and item.discount_percent > 0

    for raw in regular_rows:
        item = by_no[raw["itemNo"]]
        assert item.sale_price == int(raw["salePrice"])
        assert item.original_price is None


def test_envelope_preserves_unit_price_and_category(raw_json, parsed_envelope):
    items = _try_parse_mfront_envelope(raw_json)
    raw_first = parsed_envelope["data"]["dataList"][0]
    first = items[0]
    expected_category = (
        raw_first.get("scateNm")
        or raw_first.get("mcateNm")
        or raw_first.get("lcateNm")
        or ""
    )

    assert first.attributes["mfront_unit_price"] == raw_first["unitPrice"]
    assert first.category == expected_category


@pytest.mark.asyncio
async def test_crawl_result_has_completion_time_and_dict_items(raw_json):
    result = await HomeplusEntrypoints().crawl_sale_listing(fetch=lambda _url: raw_json)

    assert result.finished_at is not None
    assert all(isinstance(item, dict) for item in result.items)
