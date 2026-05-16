"""Costco 크롤러 단위 테스트 — 파서 + 운영자 캡처 인계 흐름."""

from __future__ import annotations

import pytest

from crawlers.marts.costco.crawler import (
    CostcoCrawler,
    cards_to_discount_items,
    parse_event_html,
)


SAMPLE_HTML = """
<html><body>
<ul class="eventList">
  <li>
    <a href="/product/123" title="코스트코 한우 등심 1kg">
      <img src="/img/123.jpg" alt="한우 등심" />
    </a>
    <div class="product-name">코스트코 한우 등심 1kg</div>
    <div class="price1"><del>89,900원</del></div>
    <div class="price">69,900원</div>
    <div class="period">2026.05.18 ~ 2026.05.31</div>
  </li>
  <li>
    <a href="https://www.costco.co.kr/product/456">
      <img data-src="//cdn.example/456.jpg" alt="우유 2.3L 2팩" />
    </a>
    <div class="product-name">서울우유 2.3L 2팩</div>
    <div class="salePrice">12,990원</div>
  </li>
</ul>
</body></html>
"""


def test_parse_event_html_extracts_cards():
    cards = parse_event_html(SAMPLE_HTML)
    assert len(cards) == 2
    first = cards[0]
    assert "한우 등심" in first.name
    assert first.sale_price == 69900.0
    assert first.original_price == 89900.0
    assert first.detail_url == "https://www.costco.co.kr/product/123"
    assert first.image_url == "https://www.costco.co.kr/img/123.jpg"
    assert first.period_text and "2026.05.18" in first.period_text

    second = cards[1]
    assert second.sale_price == 12990.0
    assert second.original_price is None
    assert second.image_url == "https://cdn.example/456.jpg"


def test_parse_event_html_empty():
    assert parse_event_html("<html><body><p>no items</p></body></html>") == []


def test_cards_to_discount_items_includes_source_evidence():
    cards = parse_event_html(SAMPLE_HTML)
    items = cards_to_discount_items(cards, source_url="https://www.costco.co.kr/specialEventList.ec")
    assert len(items) == 2
    item = items[0]
    assert item.store == "코스트코"
    assert item.sale_price == 69900.0
    assert item.detail_url.endswith("/product/123")
    attrs = item.attributes
    assert attrs["source_name"] == "costco"
    assert attrs["source_record_key"]
    assert attrs["source_url"].endswith("/product/123")
    assert attrs["collection_path"] == "public_endpoint"
    assert attrs["original_price"] == 89900.0


def test_cards_to_discount_items_marks_operator_capture():
    cards = parse_event_html(SAMPLE_HTML)
    items = cards_to_discount_items(
        cards,
        source_url="https://www.costco.co.kr/member-inventory",
        operator_capture_id="capture-abc",
    )
    assert items[0].attributes["collection_path"] == "operator_capture"
    assert items[0].attributes["operator_capture_id"] == "capture-abc"


def test_ingest_operator_capture_returns_items():
    crawler = CostcoCrawler()
    items = crawler.ingest_operator_capture(
        SAMPLE_HTML,
        source_url="https://www.costco.co.kr/member-inventory",
        capture_id="cap-1",
    )
    assert len(items) == 2
    assert all(i.attributes["operator_capture_id"] == "cap-1" for i in items)


def test_costco_crawler_info():
    crawler = CostcoCrawler()
    info = crawler.info
    assert info.name == "코스트코"
    assert "operator_workbench" in info.strategies


def test_costco_crawler_registry_discovers_plugin():
    """plugin.yaml이 레지스트리에 자동 등록되는지 확인."""
    from crawlers.registry.registry import CrawlerRegistry

    reg = CrawlerRegistry()
    reg.discover()
    assert "costco" in reg._registry
    assert reg._registry["costco"]["config"]["display_name"] == "코스트코"


@pytest.mark.asyncio
async def test_costco_crawl_handles_network_failure_gracefully(monkeypatch):
    """공개 엔드포인트 호출이 실패해도 크롤러는 PARTIAL_FAILURE/NO_DATA로 종료한다."""
    import requests as _requests

    def _boom(*args, **kwargs):
        raise _requests.ConnectionError("blocked in test")

    monkeypatch.setattr("crawlers.marts.costco.crawler.requests.get", _boom)

    crawler = CostcoCrawler()
    crawler.MAX_REQUESTS = 1
    result = await crawler.crawl()
    assert result.status.name in ("PARTIAL", "FAILED")
    assert result.items == []
    assert result.errors
