"""
아카라이브 핫딜 크롤러 TDD 테스트 — F3.3
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from crawlers.hotdeals.arca.crawler import ArcaCrawler
from core.models import HotdealPost, CrawlerGroup


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "arcalive"
FIXTURE_HTML = FIXTURES_DIR / "arcalive_hotdeal_list.html"


class TestArcaliveParse:
    @pytest.fixture
    def crawler(self):
        return ArcaCrawler()

    @pytest.fixture
    def fixture_html(self):
        assert FIXTURE_HTML.exists(), f"fixture 없음: {FIXTURE_HTML}"
        return FIXTURE_HTML.read_text(encoding="utf-8")

    def test_parse_returns_hotdeal_items(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        assert len(items) >= 2, f"parse 결과 부족: {len(items)}"

    def test_parse_items_have_required_fields(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        for item in items:
            assert isinstance(item, HotdealPost)
            assert len(item.title) >= 3
            assert item.url.startswith("http")

    def test_notice_items_excluded(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        titles = [i.title for i in items]
        assert not any("공지" in t for t in titles), "공지 항목이 포함됨"

    def test_price_extracted(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        items_with_price = [i for i in items if i.price is not None and i.price > 0]
        assert len(items_with_price) >= 1

    def test_store_in_category(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        stores = [i.category for i in items if i.category]
        assert len(stores) >= 1, "store 카테고리 추출 실패"

    def test_crawl_from_file_via_plugin(self, fixture_html, tmp_path):
        html_path = tmp_path / "capture.html"
        html_path.write_text(fixture_html, encoding="utf-8")
        try:
            from crawlers.hotdeals.arca.plugin import ArcaliveHotdealPlugin
            plugin = ArcaliveHotdealPlugin()
            result = plugin.crawl_from_file(str(html_path))
            assert result.items_count >= 2
            assert result.strategy_used == "operator_capture"
        except ImportError:
            pytest.skip("plugin import 실패 (F1 미완성)")


class TestCanonicalizeArcalive:
    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from core.product_canonicalize import canonicalize_arcalive
            self.fn = canonicalize_arcalive
        except ImportError as e:
            pytest.skip(f"product_canonicalize import 실패: {e}")

    def test_same_input_same_canonical_id(self):
        raw = {
            "title": "삼성 SSD 870 EVO 500GB 특가",
            "url": "https://arca.live/b/hotdeal/10001",
            "price": 49900,
            "source_record_key": "arca_hotdeal:post:10001",
            "category": "G마켓",
            "category_hints": ["G마켓", "PC/하드웨어"],
        }
        now = datetime(2026, 1, 15, 12, 0, 0)
        r1 = self.fn(raw, now)
        r2 = self.fn(raw, now)
        assert r1.canonical is not None
        assert r2.canonical is not None
        assert r1.canonical.id == r2.canonical.id

    def test_no_price_creates_queue_entry(self):
        raw = {
            "title": "가격 없는 게시글",
            "url": "https://arca.live/b/hotdeal/99999",
            "price": None,
            "source_record_key": "arca_hotdeal:post:99999",
            "category_hints": [],
        }
        r = self.fn(raw, datetime.now())
        assert "PRICE_INVALID" in r.reasons
        assert r.queue_entry is not None


class TestArcalivePlugin:
    def test_plugin_imports_without_error(self):
        import importlib
        try:
            importlib.import_module("crawlers.hotdeals.arca.plugin")
        except ImportError as e:
            pytest.fail(f"plugin.py import 실패: {e}")

    def test_plugin_manual_only_true(self):
        try:
            from crawlers.hotdeals.arca.plugin import ArcaliveHotdealPlugin
            plugin = ArcaliveHotdealPlugin()
            assert plugin.manual_only is True
        except ImportError:
            pytest.skip("plugin import 실패 (F1 미완성)")

    def test_plugin_crawler_info(self):
        crawler = ArcaCrawler()
        assert crawler.info.name == "아카라이브"
        assert crawler.info.group == CrawlerGroup.HOTDEAL
        assert "arca" in crawler.info.target_url
