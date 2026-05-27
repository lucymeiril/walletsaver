from __future__ import annotations

import pytest

from crawlers.marts.costco.crawler import (
    BASE_URL,
    CostcoCrawler,
    leaf_costco_categories,
    parse_costco_category_tree,
    parse_costco_listing,
)


HOME_HTML = """
<nav>
  <a href="/c/cos_10">식품</a>
  <a href="/c/cos_10.1">쌀/잡곡</a>
  <a href="/c/cos_10.1.1">쌀</a>
  <a href="/c/cos_1">디지털</a>
  <a href="/c/cos_23">기프트</a>
</nav>
"""

LIST_HTML = """
<html><body>
<ul>
  <li class="product-list-item">
    <a class="thumb" title="테스트 쌀 10kg" href="/Foods/RiceGrains/Rice/Test-Rice-10kg/p/686497">
      <img src="/medias/rice.jpg" alt="테스트 쌀 10kg" />
    </a>
    <span class="original-price">39,990원</span>
    <span class="product-price-amount">34,990원</span>
    <span class="product-price-pre-unit-amount">100g당 350원</span>
  </li>
  <li class="product-list-item">
    <a class="thumb" title="테스트 우유 2L" href="https://www.costco.co.kr/Foods/Milk/Test-Milk/p/123456?foo=bar"></a>
    <span class="product-price-amount">5,990원</span>
    <span class="product-price-pre-unit-amount">100ml당 300원</span>
  </li>
  <li class="product-list-item duplicate">
    <a class="thumb" title="중복 쌀" href="/Foods/RiceGrains/Rice/Test-Rice-10kg/p/686497"></a>
    <span class="product-price-amount">34,990원</span>
  </li>
</ul>
<a class="pagination-next" href="/c/cos_10.1.1?currentPage=1">다음</a>
</body></html>
"""


NEXT_HTML = """
<li class="product-list-item">
  <a class="thumb" title="테스트 생수 2L" href="/Foods/Water/Test-Water/p/777888"></a>
  <span class="product-price-amount">2,990원</span>
  <span class="product-price-pre-unit-amount">100ml당 15원</span>
</li>
"""


def test_g1_category_tree_extraction_and_leaf_paths():
    categories = parse_costco_category_tree(HOME_HTML)
    by_id = {cat.mart_native_category_id: cat for cat in categories}

    assert by_id["cos_10"].mart_native_category_path == "식품"
    assert by_id["cos_10.1"].parent_id == "cos_10"
    assert by_id["cos_10.1.1"].mart_native_category_path == "식품 > 쌀/잡곡 > 쌀"
    assert {cat.mart_native_category_id for cat in leaf_costco_categories(categories)} == {"cos_10.1.1", "cos_1", "cos_23"}


def test_g1_listing_extracts_p_code_canonical_unit_and_false_external_seller():
    cards = parse_costco_listing(LIST_HTML, category_id="cos_10.1.1", category_path="식품 > 쌀/잡곡 > 쌀")
    assert [card.mart_native_code for card in cards] == ["686497", "123456"]
    assert cards[0].canonical_url == "https://www.costco.co.kr/Foods/RiceGrains/Rice/Test-Rice-10kg/p/686497"
    assert cards[0].unit_price == 350
    assert cards[0].unit_price_basis == "100g"

    items = __import__("crawlers.marts.costco.crawler", fromlist=["cards_to_discount_items"]).cards_to_discount_items(cards, source_url=f"{BASE_URL}/c/cos_10.1.1")
    attrs = items[0].attributes
    assert attrs["source"] == "costco"
    assert attrs["mart_native_code"] == "686497"
    assert attrs["source_record_key"] == "686497"
    assert attrs["cocodalin_join_key"] == "686497"
    assert attrs["external_seller"] is False
    assert attrs["mart_native_category_id"] == "cos_10.1.1"
    assert attrs["mart_native_category_path"] == "식품 > 쌀/잡곡 > 쌀"
    assert attrs["canon_hash"]


@pytest.mark.asyncio
async def test_g1_crawl_harvests_homepage_leaf_category_and_paginates():
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0
    crawler.MAX_PAGES_PER_CATEGORY = 2
    crawler._mock_html_map = {
        f"{BASE_URL}/": HOME_HTML,
        f"{BASE_URL}/c/cos_10.1.1": LIST_HTML,
        f"{BASE_URL}/c/cos_10.1.1?currentPage=1": NEXT_HTML,
        f"{BASE_URL}/c/cos_1": "",
        f"{BASE_URL}/c/cos_23": "",
    }

    result = await crawler.crawl()

    assert result.status.name == "SUCCESS"
    assert result.items_count == 3
    by_code = {row["mart_native_code"]: row for row in result.items}
    assert by_code["686497"]["canonical_url"].endswith("/p/686497")
    assert by_code["686497"]["unit_price_basis"] == "100g"
    assert by_code["777888"]["mart_native_category_id"] == "cos_10.1.1"
    assert result.quality_details["product_schema"] == "round_r_g1_product_columns"
