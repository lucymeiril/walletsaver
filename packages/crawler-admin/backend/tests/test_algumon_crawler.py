"""
알구몬 핫딜 크롤러 TDD 테스트 — F3.1
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from crawlers.hotdeals.algumon.crawler import AlgumonCrawler
from core.models import HotdealPost, CrawlerGroup


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "algumon"
FIXTURE_HTML = FIXTURES_DIR / "algumon_deal_list.html"


class TestAlgumonParse:
    @pytest.fixture
    def crawler(self):
        return AlgumonCrawler()

    @pytest.fixture
    def fixture_html(self):
        assert FIXTURE_HTML.exists(), f"fixture 없음: {FIXTURE_HTML}"
        return FIXTURE_HTML.read_text(encoding="utf-8")

    def test_parse_returns_at_least_two_items(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        assert len(items) >= 2, f"parse 결과 부족: {len(items)}"

    def test_parse_items_have_required_fields(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        for item in items:
            assert isinstance(item, HotdealPost)
            assert len(item.title) >= 3, f"제목 너무 짧음: '{item.title}'"
            assert item.url.startswith("http"), f"URL 절대경로 아님: {item.url}"

    def test_parse_extracts_price(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        prices_with_value = [i for i in items if i.price is not None and i.price > 0]
        assert len(prices_with_value) >= 1, "가격 추출 실패"

    def test_parse_free_item_price_zero(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        free_items = [i for i in items if i.price == 0]
        assert len(free_items) >= 1, "무료 상품 price=0 변환 실패"

    def test_no_duplicate_urls(self, crawler, fixture_html):
        items = asyncio.run(crawler.parse(fixture_html))
        validated = asyncio.run(crawler.validate(items))
        urls = [i.url for i in validated]
        assert len(urls) == len(set(urls)), f"중복 URL 발견: {len(urls) - len(set(urls))}개"


class TestAlgumonPriceExtraction:
    @pytest.fixture
    def crawler(self):
        return AlgumonCrawler()

    @pytest.mark.parametrize("text,expected", [
        ("79,000원", 79000),
        ("1,299,000원", 1299000),
        ("무료", 0),
        ("", None),
        (None, None),
        ("가격 없음", None),
        ("3,990원 배송", 3990),
    ])
    def test_extract_price(self, crawler, text, expected):
        assert crawler._extract_price(text) == expected


class TestCanonicalizeAlgumon:
    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from core.product_canonicalize import canonicalize_algumon
            self.fn = canonicalize_algumon
        except ImportError as e:
            pytest.skip(f"product_canonicalize import 실패: {e}")

    def test_same_input_same_canonical_id(self):
        raw = {
            "title": "로지텍 MX Master 3S 무선 마우스",
            "url": "https://www.algumon.com/l/d/111111",
            "price": 79000,
            "source_record_key": "algumon:post:111111",
            "category_hints": ["전자제품"],
        }
        now = datetime(2026, 1, 15, 12, 0, 0)
        r1 = self.fn(raw, now)
        r2 = self.fn(raw, now)
        assert r1.canonical is not None
        assert r2.canonical is not None
        assert r1.canonical.id == r2.canonical.id, "canonical_id 비결정적"

    def test_category_mapped_correctly(self):
        raw = {
            "title": "삼성 갤럭시 버즈2 프로",
            "url": "https://www.algumon.com/l/d/222222",
            "price": 89900,
            "source_record_key": "algumon:post:222222",
            "category_hints": ["전자제품"],
        }
        r = self.fn(raw, datetime.now())
        assert r.canonical is not None
        assert r.canonical.category_path_internal is not None
        assert "electronics" in r.canonical.category_path_internal

    def test_no_price_creates_queue_entry(self):
        raw = {
            "title": "가격 미상 상품",
            "url": "https://www.algumon.com/l/d/000001",
            "price": None,
            "source_record_key": "algumon:post:000001",
            "category_hints": [],
        }
        r = self.fn(raw, datetime.now())
        assert "PRICE_INVALID" in r.reasons
        assert r.queue_entry is not None

    def test_unmapped_category_creates_queue_entry(self):
        raw = {
            "title": "미분류 상품",
            "url": "https://www.algumon.com/l/d/000002",
            "price": 10000,
            "source_record_key": "algumon:post:000002",
            "category_hints": ["알수없는카테고리"],
        }
        r = self.fn(raw, datetime.now())
        assert "CATEGORY_UNMAPPED" in r.reasons
        assert r.queue_entry is not None


class TestAlgumonPlugin:
    def test_plugin_imports_without_error(self):
        import importlib
        try:
            importlib.import_module("crawlers.hotdeals.algumon.plugin")
        except ImportError as e:
            pytest.fail(f"plugin.py import 실패: {e}")

    def test_plugin_crawler_class_accessible(self):
        from crawlers.hotdeals.algumon.plugin import AlgumonCrawler as _Crawler
        assert _Crawler is not None
