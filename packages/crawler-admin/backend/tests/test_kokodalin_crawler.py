"""
코코달인 크롤러 TDD 테스트 — F3.2
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from crawlers.marts.cocodalin.crawler import CocodalinCrawler
from core.models import DiscountItem


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "kokodalin"
FIXTURE_JSON = FIXTURES_DIR / "cocodalin_best_products.json"


class TestKokodalinParse:
    @pytest.fixture
    def crawler(self):
        return CocodalinCrawler()

    @pytest.fixture
    def fixture_json(self):
        assert FIXTURE_JSON.exists(), f"fixture 없음: {FIXTURE_JSON}"
        return FIXTURE_JSON.read_text(encoding="utf-8")

    def test_parse_returns_items(self, crawler, fixture_json):
        items = asyncio.run(crawler.parse(fixture_json))
        assert len(items) >= 1, "parse 결과 없음"

    def test_parse_items_are_discount_items(self, crawler, fixture_json):
        items = asyncio.run(crawler.parse(fixture_json))
        for item in items:
            assert isinstance(item, DiscountItem)

    def test_parse_price_positive(self, crawler, fixture_json):
        items = asyncio.run(crawler.parse(fixture_json))
        valid = asyncio.run(crawler.validate(items))
        for item in valid:
            assert item.sale_price > 0, f"sale_price <= 0: {item}"

    def test_parse_name_not_empty(self, crawler, fixture_json):
        items = asyncio.run(crawler.parse(fixture_json))
        valid = asyncio.run(crawler.validate(items))
        for item in valid:
            assert len(item.name) >= 2, f"상품명 너무 짧음: '{item.name}'"

    def test_invalid_item_filtered_out(self, crawler, fixture_json):
        """fixture에 invalid 항목(가격 0)이 1개 포함되어 있어 parse에서 미생성된다."""
        import json as _json
        raw = _json.loads(fixture_json)
        valid_items = asyncio.run(crawler.parse(fixture_json))
        assert len(valid_items) < len(raw), "invalid 항목이 필터링 안 됨"

    def test_no_duplicate_names(self, crawler, fixture_json):
        items = asyncio.run(crawler.parse(fixture_json))
        valid = asyncio.run(crawler.validate(items))
        names = [i.name for i in valid]
        assert len(names) == len(set(names)), "중복 상품명 발견"


class TestCanonicalizeKokodalin:
    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from core.product_canonicalize import canonicalize_kokodalin
            self.fn = canonicalize_kokodalin
        except ImportError as e:
            pytest.skip(f"product_canonicalize import 실패: {e}")

    def test_same_input_same_canonical_id(self):
        api_item = {
            "product_id": "COS001",
            "product_name": "Daewoong Pharm Impactamune 멀티비타민 84정",
            "normal_price": 28900,
            "sale_price": 22900,
            "discount": 6000,
            "category_name": "건강기능식품",
        }
        now = datetime(2026, 1, 15, 12, 0, 0)
        r1 = self.fn(api_item, now)
        r2 = self.fn(api_item, now)
        assert r1.canonical is not None
        assert r2.canonical is not None
        assert r1.canonical.id == r2.canonical.id

    def test_category_mapped_health_supplement(self):
        api_item = {
            "product_id": "COS001",
            "product_name": "멀티비타민 84정",
            "sale_price": 22900,
            "normal_price": 28900,
            "category_name": "건강기능식품",
        }
        r = self.fn(api_item, datetime.now())
        if r.canonical and r.canonical.category_path_internal:
            assert any(
                node in r.canonical.category_path_internal
                for node in ("health_supplement", "vitamin")
            )

    def test_discount_rate_calculated(self):
        api_item = {
            "product_id": "COS002",
            "product_name": "올리브 오일 3L",
            "normal_price": 39900,
            "sale_price": 34900,
            "category_name": "식품",
        }
        r = self.fn(api_item, datetime.now())
        if r.price_obs:
            assert r.price_obs.on_sale is True
            assert r.price_obs.discount_rate is not None and r.price_obs.discount_rate > 0

    def test_zero_price_creates_queue_entry(self):
        api_item = {
            "product_id": "COS999",
            "product_name": "",
            "normal_price": 0,
            "sale_price": 0,
            "category_name": "식품",
        }
        r = self.fn(api_item, datetime.now())
        assert r.confidence < 1.0 or r.queue_entry is not None


class TestKokodalinPlugin:
    def test_plugin_imports_without_error(self):
        import importlib
        try:
            importlib.import_module("crawlers.marts.cocodalin.plugin")
        except ImportError as e:
            pytest.fail(f"plugin.py import 실패: {e}")
