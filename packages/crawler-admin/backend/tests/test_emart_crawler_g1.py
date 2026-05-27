from __future__ import annotations

import pathlib

import pytest

from crawlers.marts.emart.crawler import EmartCrawler


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "emart_category_sample.html"


@pytest.mark.asyncio
async def test_g1_category_fixture_extracts_product_columns():
    crawler = EmartCrawler()
    records = crawler.parse_product_records(FIXTURE.read_text(encoding="utf-8"), category_id="6000095494", category_path="과일/채소")

    assert len(records) == 4
    first = records[0]
    assert first["mart"] == "emart"
    assert first["source"] == "emart"
    assert first["mart_native_code"] == "1001234567890"
    assert first["mart_native_category_id"] == "6000095494"
    assert first["mart_native_category_path"] == "과일/채소"


@pytest.mark.asyncio
async def test_g1_card_fields_are_normalized_from_href_badge_and_unit_price():
    crawler = EmartCrawler()
    items = await crawler.parse(FIXTURE.read_text(encoding="utf-8"), category_id="6000095494", category_path="과일/채소")
    by_code = {item.attributes["mart_native_code"]: item for item in items}

    tofu = by_code["1001234567890"]
    attrs = tofu.attributes
    assert attrs["mart_internal_seller_id"] == "2551"
    assert attrs["external_seller"] is False
    assert attrs["unit_price_displayed"] == "10g 당 99원"
    assert attrs["unit_price_basis_raw"] == "10g"
    assert attrs["canonical_url"] == "https://emart.ssg.com/item/itemView.ssg?itemId=1001234567890&siteNo=7009&salestrNo=2551"
    assert attrs["brand"] == "피코크"
    assert attrs["pack_qty"] == 300
    assert attrs["pack_unit"] == "g"
    assert tofu.promo_label == "1+1"
    assert tofu.promo_type == "buy_x_get_y"
    assert tofu.event_name == "1+1"


@pytest.mark.asyncio
async def test_g1_fixture_parses_bogo_promo_label():
    crawler = EmartCrawler()
    items = await crawler.parse(FIXTURE.read_text(encoding="utf-8"))
    by_code = {item.attributes["mart_native_code"]: item for item in items}

    tofu = by_code["1001234567890"]
    assert tofu.promo_label == "1+1"
    assert tofu.promo_type == "buy_x_get_y"
    assert tofu.attributes["promo_label"] == "1+1"


@pytest.mark.asyncio
async def test_g1_external_seller_uses_badge_and_salestr_no():
    crawler = EmartCrawler()
    items = await crawler.parse(FIXTURE.read_text(encoding="utf-8"))
    attrs = {item.attributes["mart_native_code"]: item.attributes for item in items}

    assert "1002222222222" not in attrs
    assert attrs["1003333333333"]["external_seller"] is False


@pytest.mark.asyncio
async def test_g1_crawl_uses_fixture_without_network_when_fetch_mocked():
    crawler = EmartCrawler()
    html = FIXTURE.read_text(encoding="utf-8")
    async def fake_fetch():
        return [{"html": html, "category_id": "6000095494", "category_path": "과일/채소"}]

    crawler._fetch_category_pages = fake_fetch
    result = await crawler.crawl()

    assert result.status.name == "SUCCESS"
    assert result.items_count == 4
    assert result.items[0]["mart_native_code"] == "1001234567890"
    assert result.items[0]["source"] == "emart"
