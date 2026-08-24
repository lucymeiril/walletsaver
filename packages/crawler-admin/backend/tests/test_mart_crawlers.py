"""Shared smoke contracts for the three primary mart crawlers.

Detailed parser and source-specific regressions live in the focused Emart,
Homeplus, and Lottemart test modules.  This file intentionally avoids copying
large HTML fixtures, source-readiness plans, or live/network diagnostic policy.
"""
from __future__ import annotations

import pytest

from core.models import CrawlerGroup, DiscountItem
from crawlers.marts.emart.crawler import EmartCrawler
from crawlers.marts.homeplus.crawler import HomeplusCrawler
from crawlers.marts.lottemart.crawler import LottemartCrawler


MARTS = [
    (EmartCrawler, "이마트"),
    (HomeplusCrawler, "홈플러스"),
    (LottemartCrawler, "롯데마트"),
]


@pytest.mark.parametrize("crawler_cls,display_name", MARTS)
def test_primary_mart_crawlers_expose_shared_contract(crawler_cls, display_name):
    crawler = crawler_cls()
    assert crawler.info.name == display_name
    assert crawler.info.group == CrawlerGroup.MART
    assert crawler.info.strategies
    assert callable(crawler.crawl)
    assert callable(crawler.parse)
    assert callable(crawler.validate)


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler_cls,display_name", MARTS)
async def test_primary_mart_validation_keeps_valid_rows(crawler_cls, display_name):
    crawler = crawler_cls()
    row = DiscountItem(
        name="테스트 상품 1kg",
        store=display_name,
        sale_price=3980,
        detail_url="https://example.test/product/1",
    )
    valid = await crawler.validate([row])
    assert len(valid) == 1
    assert valid[0].name == "테스트 상품 1kg"
    assert valid[0].sale_price == 3980


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler_cls,display_name", MARTS)
async def test_primary_mart_validation_rejects_non_positive_price(crawler_cls, display_name):
    crawler = crawler_cls()
    rows = [
        DiscountItem(name="정상 상품", store=display_name, sale_price=1000),
        DiscountItem(name="가격 오류", store=display_name, sale_price=0),
    ]
    valid = await crawler.validate(rows)
    assert [row.name for row in valid] == ["정상 상품"]


def test_discount_item_product_price_conversion_preserves_price_facts():
    item = DiscountItem(
        name="양파 1kg",
        store="이마트",
        original_price=5000,
        sale_price=3000,
        discount_percent=40.0,
        category="채소류",
    )
    price = item.to_product_price()
    assert price.product_name == "양파 1kg"
    assert price.store == "이마트"
    assert price.price == 3000
    assert price.original_price == 5000
    assert price.discount_rate == pytest.approx(0.4)
