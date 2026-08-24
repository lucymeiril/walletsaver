"""Offline parser contracts for the active fashion shopping crawlers.

Live source availability does not belong in the regression suite. OPINET has its
own focused test module, so this file only protects Musinsa, Giordano, and
Uniqlo parsing/validation behavior without network access.
"""
from __future__ import annotations

import asyncio

import pytest

from core.models import DiscountItem
from crawlers.shopping.giordano.crawler import GiordanoCrawler
from crawlers.shopping.musinsa.crawler import MusinsaCrawler
from crawlers.shopping.uniqlo.crawler import UniqloCrawler


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "crawler,expected_name",
    [
        (MusinsaCrawler(), "무신사"),
        (GiordanoCrawler(), "지오다노"),
        (UniqloCrawler(), "유니클로"),
    ],
)
def test_active_fashion_crawlers_expose_shopping_contract(crawler, expected_name):
    assert crawler.info.name == expected_name
    assert crawler.info.group.value == "shopping"
    assert callable(crawler.crawl)
    assert callable(crawler.parse)
    assert callable(crawler.validate)


def test_musinsa_converts_saved_api_product():
    crawler = MusinsaCrawler()
    payload = {
        "data": {
            "goods": [
                {
                    "goodsName": "오버핏 맨투맨",
                    "salePrice": 29900,
                    "normalPrice": 49900,
                    "saleRate": 40,
                    "brandName": "커버낫",
                    "imageUrl": "/img/test.jpg",
                    "goodsNo": 12345,
                }
            ]
        }
    }

    goods = crawler._extract_goods_from_api(payload)
    assert len(goods) == 1
    item = crawler._api_product_to_item(goods[0], "001")

    assert item is not None
    assert item.name == "오버핏 맨투맨"
    assert item.sale_price == 29900
    assert item.original_price == 49900
    assert item.store == "무신사"


def test_giordano_parses_saved_sale_html():
    crawler = GiordanoCrawler()
    html = """
    <html><body><ul>
      <li class="each_prd_box">
        <div class="box">
          <a href="/shop/detail.php?prdcode=123"><img src="https://example.test/shirt.jpg" /></a>
          <div class="info">
            <p class="name">린넨 셔츠</p>
            <div class="price">
              <span class="consumer">39,800원</span>
              <span class="sale_prc">50%</span>
              <span class="sell">19,800원</span>
            </div>
          </div>
        </div>
      </li>
    </ul></body></html>
    """

    items = _run(crawler.parse(html))

    assert len(items) == 1
    assert items[0].name == "린넨 셔츠"
    assert items[0].sale_price == 19800
    assert items[0].original_price == 39800
    assert items[0].store == "지오다노"


def test_giordano_price_text_parser():
    crawler = GiordanoCrawler()
    original, discount, sale = crawler._parse_price_text("19,800원\n20%\n15,800원")
    assert (original, discount, sale) == (19800, 20.0, 15800)


def test_uniqlo_converts_saved_api_product():
    crawler = UniqloCrawler()
    product = {
        "name": "에어리즘 코튼 반팔 T",
        "productId": "E466055",
        "prices": {
            "base": {"value": 14900},
            "original": {"value": 19900},
        },
        "images": {"main": {"image": "https://example.test/item.jpg"}},
        "genderName": "남성",
    }

    item = crawler._api_to_discount_item(product)

    assert item is not None
    assert item.name == "에어리즘 코튼 반팔 T"
    assert item.sale_price == 14900
    assert item.original_price == 19900
    assert item.store == "유니클로"


def test_uniqlo_extracts_supported_api_shapes():
    crawler = UniqloCrawler()
    assert len(crawler._extract_products_from_api({"result": {"items": [{"name": "A"}]}})) == 1
    assert len(crawler._extract_products_from_api({"data": {"products": [{"name": "B"}]}})) == 1
    assert len(crawler._extract_products_from_api({"items": [{"name": "C"}]})) == 1


@pytest.mark.parametrize(
    "crawler,store",
    [
        (MusinsaCrawler(), "무신사"),
        (GiordanoCrawler(), "지오다노"),
        (UniqloCrawler(), "유니클로"),
    ],
)
def test_fashion_validation_deduplicates_same_name_and_price(crawler, store):
    items = [
        DiscountItem(name="테스트 상품 A", store=store, sale_price=10000),
        DiscountItem(name="테스트 상품 A", store=store, sale_price=10000),
        DiscountItem(name="테스트 상품 B", store=store, sale_price=20000),
    ]

    valid = _run(crawler.validate(items))

    assert len(valid) == 2
