from __future__ import annotations

import pathlib

import pytest

from crawlers.marts.homeplus.crawler import HomeplusCrawler


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_hyper_and_exp_store_types_have_matching_canonical_urls():
    crawler = HomeplusCrawler()
    hyper_html = (FIXTURES / "homeplus_list_sample.html").read_text(encoding="utf-8")
    exp_html = (FIXTURES / "homeplus_express_list_sample.html").read_text(encoding="utf-8")

    hyper_items = await crawler.parse(hyper_html, store_type="HYPER")
    exp_items = await crawler.parse(exp_html, store_type="EXP")

    assert hyper_items
    assert exp_items
    assert all(item.attributes["storeType"] == "HYPER" for item in hyper_items)
    assert exp_items[0].attributes["storeType"] == "EXP"
    assert hyper_items[0].attributes["canonical_url"] == "https://mfront.homeplus.co.kr/item?itemNo=123456789&storeType=HYPER"
    assert exp_items[0].attributes["canonical_url"] == "https://mfront.homeplus.co.kr/item?itemNo=222333444&storeType=EXP"
    assert hyper_items[0].attributes["mart_native_code"] == "123456789"
    assert exp_items[0].attributes["mart_native_code"] == "222333444"


@pytest.mark.asyncio
async def test_internal_routing_hrefs_are_never_used_as_canonical_url():
    crawler = HomeplusCrawler()
    html = (FIXTURES / "homeplus_list_sample.html").read_text(encoding="utf-8")
    items = await crawler.parse(html, store_type="HYPER")

    canonicals = [item.attributes["canonical_url"] for item in items]
    assert "https://mfront.homeplus.co.kr/p/expfreedlvr" not in canonicals
    assert all("/item?itemNo=" in url for url in canonicals)
    assert all("/p/" not in item.detail_url and "/exhibit" not in item.detail_url for item in items)


@pytest.mark.asyncio
async def test_external_seller_flag_uses_homeplus_delivery_badge_text():
    crawler = HomeplusCrawler()
    html = (FIXTURES / "homeplus_list_sample.html").read_text(encoding="utf-8")
    items = await crawler.parse(html, store_type="HYPER")
    by_code = {item.attributes["mart_native_code"]: item for item in items}

    assert by_code["123456789"].attributes["external_seller"] is False
    assert by_code["987654321"].attributes["external_seller"] is True


@pytest.mark.asyncio
async def test_unit_price_is_parsed_from_homeplus_display_text():
    crawler = HomeplusCrawler()
    html = (FIXTURES / "homeplus_list_sample.html").read_text(encoding="utf-8")
    items = await crawler.parse(html, store_type="HYPER")
    first = next(item for item in items if item.attributes["mart_native_code"] == "123456789")

    assert first.attributes["unit_price_displayed"] == 200
    assert first.attributes["unit_price_basis_raw"] == "10G"


def test_source_requests_include_hyper_and_exp_category_lists():
    crawler = HomeplusCrawler()
    requests = crawler._build_source_requests()
    urls = {req["url"] for req in requests}

    assert "https://mfront.homeplus.co.kr/list?categoryDepth=0&categoryId=1&delivery=HYPER_DRCT" in urls
    assert "https://mfront.homeplus.co.kr/express/list?categoryDepth=0&categoryId=1" in urls
    assert {req["store_type"] for req in requests} == {"HYPER", "EXP"}
