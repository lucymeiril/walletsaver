"""Emart parser contracts using a representative saved first-party fixture."""

from __future__ import annotations

import json
import pathlib

import pytest

from crawlers.marts.emart.crawler import EmartCrawler


FIXTURE_HTML = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.html"
FIXTURE_JSON = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.json"


@pytest.fixture
def html() -> str:
    assert FIXTURE_HTML.exists(), f"missing slim live fixture: {FIXTURE_HTML}"
    return FIXTURE_HTML.read_text(encoding="utf-8")


@pytest.fixture
def crawler() -> EmartCrawler:
    return EmartCrawler()


@pytest.mark.asyncio
async def test_parse_extracts_five_real_items_from_next_data(crawler, html):
    items = await crawler.parse(html)
    assert len(items) == 5


@pytest.mark.asyncio
async def test_parse_first_item_has_real_name_price_and_detail_url(crawler, html):
    items = await crawler.parse(html)
    first = next(i for i in items if "양배추" in i.name)
    assert first.sale_price == 2784
    assert first.original_price == 3480
    assert first.detail_url.endswith("itemId=1000641687348&siteNo=7009&salestrNo=2551")
    assert first.image_url.startswith("https://sitem.ssgcdn.com/")


@pytest.mark.asyncio
async def test_parse_emits_source_record_key_for_dedupe(crawler, html):
    items = await crawler.parse(html)
    keys = [i.attributes.get("source_record_key") for i in items]
    assert all(keys)
    assert len(set(keys)) == len(keys)


@pytest.mark.asyncio
async def test_parse_no_phantom_zero_prices(crawler, html):
    items = await crawler.parse(html)
    raw = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    fixture_prices = {
        int(p["finalPrice"].replace(",", ""))
        for p in raw["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["areaList"][0]["dataList"]
    }
    assert {i.sale_price for i in items} == fixture_prices


@pytest.mark.asyncio
async def test_validate_does_not_pad_with_zero_or_short_names(crawler, html):
    items = await crawler.parse(html)
    valid = await crawler.validate(items)
    assert all(i.sale_price > 0 for i in valid)
    assert all(len(i.name) >= 2 for i in valid)
    assert len(valid) <= len(items)


@pytest.mark.asyncio
async def test_pagination_signal_preserved_in_saved_source(crawler, html):
    assert '"hasNext": true' in html
    assert "/api/item/all" in html
    items = await crawler.parse(html)
    assert len(items) == 5
