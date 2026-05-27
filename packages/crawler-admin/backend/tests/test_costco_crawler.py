"""Costco 크롤러 테스트 — 본 사이트(costco.co.kr) 전용 (TDD). v0.5.0

fixtures:
  - tests/fixtures/costco/special_offers_5cards.html — 실 HTML 파싱 회귀
  - tests/fixtures/costco/occ_products_3items.json  — OCC API JSON 파싱
"""

from __future__ import annotations

import json
import pathlib

import pytest

from crawlers.marts.costco.crawler import (
    CATEGORY_CODES,
    CATEGORY_ENDPOINTS,
    CostcoCrawler,
    cards_to_discount_items,
    parse_costco_listing,
    parse_costco_occ_response,
    _occ_pagination,
)


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "costco" / "special_offers_5cards.html"
OCC_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "costco" / "occ_products_3items.json"


@pytest.fixture
def fixture_html() -> str:
    assert FIXTURE.exists(), f"missing live fixture: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def occ_fixture() -> dict:
    assert OCC_FIXTURE.exists(), f"missing occ fixture: {OCC_FIXTURE}"
    return json.loads(OCC_FIXTURE.read_text(encoding="utf-8"))


def test_parse_listing_extracts_five_cards(fixture_html):
    cards = parse_costco_listing(fixture_html)
    assert len(cards) == 5


def test_parse_listing_extracts_name_price_and_detail_url(fixture_html):
    cards = parse_costco_listing(fixture_html)
    first = cards[0]
    assert "바이오더마" in first.name
    assert first.sale_price == 35990.0
    assert first.detail_url and first.detail_url.endswith("/p/602630")
    assert first.detail_url.startswith("https://www.costco.co.kr")
    assert first.image_url


def test_parse_listing_extracts_unit_price_when_present(fixture_html):
    cards = parse_costco_listing(fixture_html)
    assert cards[0].unit_price_text and "3,099" in cards[0].unit_price_text


def test_member_only_flag_propagates(fixture_html):
    cards = parse_costco_listing(fixture_html)
    assert all(isinstance(c.is_member_only, bool) for c in cards)


def test_cards_to_discount_items_emit_source_evidence(fixture_html):
    cards = parse_costco_listing(fixture_html)
    items = cards_to_discount_items(
        cards,
        source_url="https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers",
    )
    assert len(items) == 5
    item = items[0]
    assert item.store == "코스트코"
    assert item.sale_price == 35990.0
    attrs = item.attributes
    assert attrs["source_name"] == "costco"
    assert attrs["source_record_key"]
    assert attrs["source_url"].endswith("/p/602630")
    assert attrs["collection_path"] == "public_endpoint"
    assert attrs["unit_price_text"] and "3,099" in attrs["unit_price_text"]


def test_operator_capture_path_marks_collection_correctly(fixture_html):
    crawler = CostcoCrawler()
    items = crawler.ingest_operator_capture(
        fixture_html,
        source_url="https://www.costco.co.kr/member-area",
        capture_id="op-1",
    )
    assert items and all(i.attributes["collection_path"] == "operator_capture" for i in items)
    assert items[0].attributes["operator_capture_id"] == "op-1"


def test_costco_crawler_info_advertises_workbench():
    info = CostcoCrawler().info
    assert info.name == "코스트코"
    assert "operator_workbench" in info.strategies
    assert "playwright" in info.strategies
    assert info.target_url == "https://www.costco.co.kr"
    assert info.version == "0.6.0"


def test_registry_discovers_costco_plugin():
    from crawlers.registry.registry import CrawlerRegistry

    reg = CrawlerRegistry()
    reg.discover()
    assert "costco" in reg._registry
    cfg = reg._registry["costco"]["config"]
    assert cfg["display_name"] == "코스트코"
    target = cfg.get("target") or {}
    assert target.get("url", "").startswith("https://www.costco.co.kr")


def test_no_cocodalin_in_costco_crawler_source():
    """costco crawler 소스코드에 cocodalin 호출 코드가 없어야 한다."""
    import inspect
    from crawlers.marts.costco import crawler as costco_crawler_module
    source = inspect.getsource(costco_crawler_module)
    assert "cocodalin" not in source.lower(), "costco crawler에 cocodalin 코드가 남아 있음"


def test_category_endpoints_count():
    """발표용 크롤러는 식품/생활 필수 카테고리만 제한 수집한다."""
    from crawlers.marts.costco.crawler import CATEGORY_ENDPOINTS
    assert len(CATEGORY_ENDPOINTS) >= 2


def test_category_codes_match_endpoints():
    """CATEGORY_CODES와 CATEGORY_ENDPOINTS 수가 일치해야 한다."""
    assert len(CATEGORY_CODES) == len(CATEGORY_ENDPOINTS)


def test_search_keywords_count():
    """15개 이상의 검색 키워드가 정의되어 있어야 한다."""
    from crawlers.marts.costco.crawler import SEARCH_KEYWORDS
    assert len(SEARCH_KEYWORDS) >= 15
    assert "우유" in SEARCH_KEYWORDS
    assert "계란" in SEARCH_KEYWORDS
    assert "휴지" in SEARCH_KEYWORDS


def test_build_all_urls_includes_categories_search_pagination():
    """URL 목록이 카테고리 + 검색 + 페이지네이션을 포함해야 한다."""
    crawler = CostcoCrawler()
    urls = crawler._build_all_urls()
    url_strs = [u for u, _ in urls]

    category_urls = [u for u in url_strs if "/c/" in u]
    assert len(category_urls) >= len(CATEGORY_ENDPOINTS)

    search_urls = [u for u in url_strs if "search?" in u]
    assert len(search_urls) >= 15

    page_urls = [u for u in url_strs if "currentPage=" in u]
    assert len(page_urls) >= 7


@pytest.mark.asyncio
async def test_validate_drops_member_only_zero_price_rows(fixture_html):
    crawler = CostcoCrawler()
    items = await crawler.parse(fixture_html)
    valid = await crawler.validate(items)
    assert all(i.sale_price > 0 and len(i.name) >= 2 for i in valid)


# --- OCC API JSON 파싱 테스트 ---

def test_parse_occ_response_extracts_three_cards(occ_fixture):
    """OCC JSON에서 3개 카드를 추출해야 한다."""
    cards = parse_costco_occ_response(occ_fixture)
    assert len(cards) == 3


def test_parse_occ_response_extracts_name_price_url(occ_fixture):
    """OCC 카드에서 이름, 가격, URL이 올바르게 추출돼야 한다."""
    cards = parse_costco_occ_response(occ_fixture)
    first = cards[0]
    assert "바이오더마" in first.name
    assert first.sale_price == 35990.0
    assert first.detail_url and first.detail_url.startswith("https://www.costco.co.kr")


def test_parse_occ_response_extracts_original_price(occ_fixture):
    """OCC wasPrice가 있으면 original_price로 추출돼야 한다."""
    cards = parse_costco_occ_response(occ_fixture)
    third = cards[2]
    assert third.original_price == 28000.0
    assert third.sale_price == 24900.0


def test_parse_occ_response_empty_input():
    """빈 입력에서 빈 리스트를 반환해야 한다."""
    assert parse_costco_occ_response({}) == []
    assert parse_costco_occ_response({"products": []}) == []


def test_occ_pagination_reads_total_pages(occ_fixture):
    """OCC 페이지네이션에서 (0, 3)을 반환해야 한다."""
    current, total = _occ_pagination(occ_fixture)
    assert current == 0
    assert total == 3


def test_occ_pagination_defaults_to_one():
    """pagination 키 없으면 totalPages=1 기본값."""
    assert _occ_pagination({}) == (0, 1)
    assert _occ_pagination({"pagination": {}}) == (0, 1)


def test_occ_cards_to_discount_items(occ_fixture):
    """OCC 카드 → DiscountItem 변환: store, sale_price, attributes 검증."""
    cards = parse_costco_occ_response(occ_fixture)
    items = cards_to_discount_items(cards, source_url="https://www.costco.co.kr/c/FoodandBeverage")
    assert len(items) == 3
    assert all(i.store == "코스트코" for i in items)
    assert items[0].sale_price == 35990
    assert items[0].attributes["source_name"] == "costco"
    assert items[0].attributes["collection_path"] == "public_endpoint"


# --- Playwright mock 기반 crawl() 테스트 ---

@pytest.mark.asyncio
async def test_crawl_with_mock_html_returns_items(fixture_html):
    """mock_html_map 주입 시 crawl()이 SUCCESS + items >= 5를 반환해야 한다."""
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0
    # 첫 번째 카테고리 URL에만 fixture 주입
    from crawlers.marts.costco.crawler import CATEGORY_CODES, BASE_URL
    first_path, first_code = CATEGORY_CODES[0]
    first_url = f"{BASE_URL}/{first_path}"
    crawler._mock_html_map = {first_url: fixture_html}
    # MAX_REQUESTS=1 → 첫 카테고리만 처리
    crawler.MAX_REQUESTS = 1
    result = await crawler.crawl()
    assert result.status.name == "SUCCESS"
    assert result.items_count >= 5
    assert result.quality_details["source_map"]["parser_contract"].startswith("costco_storefront")


@pytest.mark.asyncio
async def test_crawl_occ_api_empty_returns_failed(monkeypatch):
    """OCC mock 응답이 빈 dict이면 crawl()이 FAILED를 반환해야 한다."""
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0
    crawler._mock_occ_responses = {}  # 카테고리 없음 → 0건
    result = await crawler.crawl()
    assert result.status.name in ("PARTIAL", "FAILED")
    assert result.items_count == 0


@pytest.mark.asyncio
async def test_crawl_food_categories_mock_html(fixture_html):
    """식품/생활필수 범위 mock fixture 주입 시 중복 없이 수집돼야 한다."""
    from crawlers.marts.costco.crawler import CATEGORY_CODES, BASE_URL
    import re

    # fixture_html은 5개 카드이고 현재 코스트코 크롤러는 발표용 식품/생활필수 범위만 돈다.
    # 각 카테고리마다 다른 product ID를 가지도록 카드 URL 패치
    crawler = CostcoCrawler()
    crawler.PAGE_SLEEP_SECONDS = 0

    mock_map: dict[str, str] = {}
    for idx, (path, code) in enumerate(CATEGORY_CODES):
        url = f"{BASE_URL}/{path}"
        # product ID를 카테고리별로 다르게 만들어 dedup 통과
        patched = re.sub(r"/p/(\d+)", lambda m: f"/p/{int(m.group(1)) + idx * 100000}", fixture_html)
        mock_map[url] = patched

    crawler._mock_html_map = mock_map
    result = await crawler.crawl()
    assert result.items_count >= 10, f"mock 주입 후 식품/생활필수 카테고리가 수집되어야 함 (실제 {result.items_count})"
    assert result.quality_details.get("category_breakdown") is not None
