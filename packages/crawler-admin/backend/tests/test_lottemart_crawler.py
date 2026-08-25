"""Lotte Mart parser contracts using saved source-shaped fixtures."""

from __future__ import annotations

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
