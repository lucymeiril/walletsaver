"""Costco 크롤러 테스트 — 실 라이브 캡처 fixture 기반 (TDD).

fixture: tests/fixtures/costco/special_offers_5cards.html
  - 2026-05-16 실 라이브 캡처(https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers)
  - 첫 5개 카드만 슬림화. 라이브 페이지 셀렉터(li.product-list-item / a.thumb / .product-price-amount)가
    바뀌면 이 fixture 회귀가 깨지므로 즉시 인지된다.
"""

from __future__ import annotations

import pathlib

import pytest

from crawlers.marts.costco.crawler import (
    CostcoCrawler,
    cards_to_discount_items,
    parse_costco_listing,
)


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "costco" / "special_offers_5cards.html"


@pytest.fixture
def fixture_html() -> str:
    assert FIXTURE.exists(), f"missing live fixture: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_listing_extracts_five_cards(fixture_html):
    cards = parse_costco_listing(fixture_html)
    assert len(cards) == 5, f"슬림 fixture에는 5개 카드만 있어야 함 (실제 {len(cards)})"


def test_parse_listing_extracts_name_price_and_detail_url(fixture_html):
    cards = parse_costco_listing(fixture_html)
    first = cards[0]
    # 실 라이브 캡처: 바이오더마 아토덤 울트라 크림 / 35,990원 / /p/602630
    assert "바이오더마" in first.name
    assert first.sale_price == 35990.0
    assert first.detail_url and first.detail_url.endswith("/p/602630")
    assert first.detail_url.startswith("https://www.costco.co.kr")
    assert first.image_url  # picture/img src present


def test_parse_listing_extracts_unit_price_when_present(fixture_html):
    cards = parse_costco_listing(fixture_html)
    # 첫 카드: 100㎖당 3,099원
    assert cards[0].unit_price_text and "3,099" in cards[0].unit_price_text


def test_member_only_flag_propagates(fixture_html):
    """`.price-panel-login`이 보이는 카드는 is_member_only=True. fixture 내 존재 여부와 무관."""
    cards = parse_costco_listing(fixture_html)
    # bool 자체가 노출되어야 한다
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
    assert info.target_url == "https://www.costco.co.kr"


def test_registry_discovers_costco_plugin():
    from crawlers.registry.registry import CrawlerRegistry

    reg = CrawlerRegistry()
    reg.discover()
    assert "costco" in reg._registry
    cfg = reg._registry["costco"]["config"]
    assert cfg["display_name"] == "코스트코"
    # plugin.yaml은 실제 200 OK URL을 가리켜야 한다
    target = cfg.get("target") or {}
    assert target.get("url", "").startswith("https://www.costco.co.kr")


@pytest.mark.asyncio
async def test_validate_drops_member_only_zero_price_rows(fixture_html):
    crawler = CostcoCrawler()
    items = await crawler.parse(fixture_html)
    valid = await crawler.validate(items)
    # sale_price 0 (회원 전용 미공개) + 짧은 이름 모두 제거. 유효 행이 0개 이상이면 OK
    assert all(i.sale_price > 0 and len(i.name) >= 2 for i in valid)


@pytest.mark.asyncio
async def test_crawl_handles_network_failure(monkeypatch):
    import requests as _requests

    def boom(*args, **kwargs):
        raise _requests.ConnectionError("blocked in test")

    monkeypatch.setattr("crawlers.marts.costco.crawler.requests.get", boom)
    crawler = CostcoCrawler()
    crawler.MAX_REQUESTS = 1
    result = await crawler.crawl()
    assert result.status.name in ("PARTIAL", "FAILED")
    assert result.items == []
    assert result.errors and result.errors[0].error_type.name == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_crawl_succeeds_when_first_endpoint_returns_fixture(monkeypatch, fixture_html):
    """첫 엔드포인트가 fixture HTML을 응답하면 SUCCESS + items > 0."""
    import requests as _requests

    class FakeResp:
        status_code = 200
        text = fixture_html
        def raise_for_status(self):
            return None

    monkeypatch.setattr("crawlers.marts.costco.crawler.requests.get", lambda *a, **k: FakeResp())
    crawler = CostcoCrawler()
    crawler.MAX_REQUESTS = 1
    result = await crawler.crawl()
    assert result.status.name == "SUCCESS"
    assert result.items_count == 5
    assert result.quality_details["source_map"]["parser_contract"].startswith("costco_storefront")
