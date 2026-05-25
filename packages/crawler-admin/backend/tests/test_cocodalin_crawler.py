"""코코달인 크롤러 독립 테스트."""

from __future__ import annotations

import json
import pathlib

import pytest

from crawlers.marts.cocodalin.crawler import CocodalinCrawler


COCO_FIXTURE = (
    pathlib.Path(__file__).parent
    / "fixtures"
    / "costco"
    / "cocodalin_productlist_cat10.json"
)


@pytest.fixture
def coco_products() -> list:
    assert COCO_FIXTURE.exists(), f"missing cocodalin fixture: {COCO_FIXTURE}"
    return json.loads(COCO_FIXTURE.read_text(encoding="utf-8"))


def test_cocodalin_crawler_has_12_category_ids():
    from crawlers.marts.cocodalin.crawler import CATEGORY_IDS
    assert len(CATEGORY_IDS) == 12


def test_cocodalin_product_to_discount_item_parses_correctly(coco_products):
    crawler = CocodalinCrawler()
    items = [crawler._product_to_discount_item(p) for p in coco_products]
    valid = [i for i in items if i is not None]
    assert len(valid) >= 40, f"50건 중 최소 40건 파싱 기대 (실제 {len(valid)})"
    first = valid[0]
    assert first.store == "코스트코"
    assert first.sale_price > 0


@pytest.mark.asyncio
async def test_cocodalin_crawl_calls_all_12_categories(monkeypatch, coco_products):
    """12개 카테고리 productList를 모두 호출하는지 확인."""
    urls_hit = []

    class FakeBestResp:
        status_code = 200

        def json(self):
            return []

    class FakeCatResp:
        status_code = 200

        def json(self):
            return coco_products

    def fake_get(url, **kwargs):
        urls_hit.append(url)
        if "productList" in url:
            return FakeCatResp()
        return FakeBestResp()

    monkeypatch.setattr("crawlers.marts.cocodalin.crawler.requests.get", fake_get)
    crawler = CocodalinCrawler()
    crawler.SLEEP_SECONDS = 0
    result = await crawler.crawl()

    product_list_urls = [u for u in urls_hit if "productList" in u]
    assert len(product_list_urls) == 12, (
        f"12카테고리 호출 기대 (실제 {len(product_list_urls)})"
    )
    assert result.status.name == "SUCCESS"
    assert result.items_count >= 40, f"최소 40건 기대 (실제 {result.items_count})"


@pytest.mark.asyncio
async def test_cocodalin_standalone_392_plus_mock(monkeypatch, coco_products):
    """12카테고리 mock에서 중복 제거 후 392+ 건 수확."""
    base_products = coco_products  # 50 items

    def make_products_for_cat(cat_id: int):
        return [
            {**p, "product_id": p["product_id"] + cat_id * 10000, "category_id": cat_id}
            for p in base_products
        ]

    class FakeResp:
        def __init__(self, products):
            self._products = products
            self.status_code = 200

        def json(self):
            return self._products

    def fake_get(url, **kwargs):
        if "productList" in url:
            cat_id = int(url.rsplit("/productList/", 1)[-1])
            return FakeResp(make_products_for_cat(cat_id))
        return FakeResp([])

    monkeypatch.setattr("crawlers.marts.cocodalin.crawler.requests.get", fake_get)
    crawler = CocodalinCrawler()
    crawler.SLEEP_SECONDS = 0
    result = await crawler.crawl()
    assert result.items_count >= 392, f"392+ 기대 (실제 {result.items_count})"
