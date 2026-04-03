"""
PluginTestFramework 자체에 대한 테스트 — 준수 검사, 스키마 검증, Mock, 벤치마킹.
"""

from __future__ import annotations

import asyncio

import pytest

from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus
from plugins.plugin_interface import PluginInterface, PluginStatus
from plugins.test_framework import (
    PluginTestFramework,
    BenchmarkResult,
    ComplianceResult,
    MOCK_HTML_SIMPLE,
    MOCK_HTML_EMPTY,
    MOCK_HTML_MALFORMED,
    MOCK_JSON_RESPONSE,
)


# --- 테스트용 구현 ---

class CompliantPlugin(PluginInterface):
    """인터페이스를 완전히 준수하는 플러그인."""

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="compliant",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
        )

    async def crawl(self) -> CrawlResult:
        return CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="compliant",
            strategy_used="requests",
            items_count=1,
            items=[{"title": "test"}],
        )

    async def parse(self, raw_data: str) -> list[dict]:
        return [{"title": line.strip()} for line in raw_data.split("\n") if line.strip()]

    async def validate(self, items: list[dict]) -> list[dict]:
        return [i for i in items if i.get("title")]


class MinimalContract:
    """CrawlerContract도 PluginInterface도 아닌 최소 구현 (비준수)."""
    pass


# --- 테스트 ---

class TestComplianceCheck:
    """인터페이스 준수 검사 테스트."""

    def test_compliant_plugin_passes(self):
        plugin = CompliantPlugin()
        fw = PluginTestFramework(plugin)
        result = fw.check_compliance()
        assert result.is_compliant
        assert len(result.failed) == 0
        assert len(result.passed) > 0

    def test_compliance_result_has_plugin_name(self):
        plugin = CompliantPlugin()
        fw = PluginTestFramework(plugin)
        result = fw.check_compliance()
        assert result.plugin_name == "compliant"

    def test_compliance_to_dict(self):
        plugin = CompliantPlugin()
        fw = PluginTestFramework(plugin)
        result = fw.check_compliance()
        d = result.to_dict()
        assert d["is_compliant"] is True
        assert d["total_checks"] > 0

    def test_no_plugin_raises(self):
        fw = PluginTestFramework()
        with pytest.raises(ValueError):
            fw.check_compliance()

    def test_set_plugin(self):
        fw = PluginTestFramework()
        plugin = CompliantPlugin()
        fw.set_plugin(plugin)
        result = fw.check_compliance()
        assert result.is_compliant


class TestCrawlResultValidation:
    """CrawlResult 스키마 검증 테스트."""

    def test_valid_success_result(self):
        result = CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="test",
            strategy_used="requests",
            items_count=2,
            items=[{"a": 1}, {"b": 2}],
            duration_seconds=1.0,
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert errors == []

    def test_success_without_strategy(self):
        result = CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="test",
            strategy_used=None,
            items_count=0,
            items=[],
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert any("strategy_used" in e for e in errors)

    def test_items_count_mismatch(self):
        result = CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="test",
            strategy_used="requests",
            items_count=5,
            items=[{"a": 1}],
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert any("불일치" in e or "mismatch" in e.lower() for e in errors)

    def test_failed_without_error_info(self):
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="test",
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert any("에러" in e or "error" in e.lower() for e in errors)

    def test_failed_with_error_msg_is_ok(self):
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="test",
            error_msg="timeout",
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert not any("에러" in e or "error" in e.lower() for e in errors)

    def test_empty_crawler_name(self):
        result = CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="",
            strategy_used="requests",
            items_count=0,
            items=[],
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert any("crawler_name" in e for e in errors)

    def test_negative_duration(self):
        result = CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="test",
            strategy_used="requests",
            items_count=0,
            items=[],
            duration_seconds=-1.0,
        )
        errors = PluginTestFramework.validate_crawl_result(result)
        assert any("duration" in e for e in errors)


class TestMockData:
    """Mock 데이터 테스트."""

    def test_get_mock_html_simple(self):
        html = PluginTestFramework.get_mock_html("simple")
        assert "deal-item" in html
        assert "테스트 상품 1" in html

    def test_get_mock_html_empty(self):
        html = PluginTestFramework.get_mock_html("empty")
        assert "deal-list" in html
        assert "deal-item" not in html

    def test_get_mock_html_malformed(self):
        html = PluginTestFramework.get_mock_html("malformed")
        assert "잘못된 구조" in html

    def test_get_mock_html_default(self):
        html = PluginTestFramework.get_mock_html("unknown_variant")
        assert html == MOCK_HTML_SIMPLE

    def test_get_mock_json(self):
        data = PluginTestFramework.get_mock_json()
        assert data["status"] == "success"
        assert len(data["data"]) == 2

    def test_create_mock_crawl_result(self):
        result = PluginTestFramework.create_mock_crawl_result(
            crawler_name="mock-crawler",
            items_count=5,
        )
        assert result.status == CrawlStatus.SUCCESS
        assert result.crawler_name == "mock-crawler"
        assert result.items_count == 5
        assert len(result.items) == 5

    def test_create_mock_crawl_result_failed(self):
        result = PluginTestFramework.create_mock_crawl_result(
            status=CrawlStatus.FAILED,
            items_count=0,
        )
        assert result.status == CrawlStatus.FAILED
        assert result.strategy_used is None


class TestBenchmark:
    """벤치마킹 테스트."""

    @pytest.mark.asyncio
    async def test_benchmark_parse(self):
        plugin = CompliantPlugin()
        fw = PluginTestFramework(plugin)
        result = await fw.benchmark_parse("line1\nline2\nline3", iterations=3)
        assert isinstance(result, BenchmarkResult)
        assert result.operation == "parse"
        assert result.iterations == 3
        assert result.avg_seconds > 0
        assert result.min_seconds <= result.avg_seconds <= result.max_seconds

    @pytest.mark.asyncio
    async def test_benchmark_validate(self):
        plugin = CompliantPlugin()
        fw = PluginTestFramework(plugin)
        items = [{"title": "a"}, {"title": "b"}, {}]
        result = await fw.benchmark_validate(items, iterations=3)
        assert result.operation == "validate"
        assert result.iterations == 3

    @pytest.mark.asyncio
    async def test_benchmark_no_plugin_raises(self):
        fw = PluginTestFramework()
        with pytest.raises(ValueError):
            await fw.benchmark_parse("test")

    def test_benchmark_result_to_dict(self):
        br = BenchmarkResult(
            operation="parse",
            iterations=10,
            total_seconds=1.0,
            avg_seconds=0.1,
            min_seconds=0.05,
            max_seconds=0.2,
            items_per_second=50.0,
        )
        d = br.to_dict()
        assert d["operation"] == "parse"
        assert d["iterations"] == 10


class TestHealthCheck:
    """건강 상태 검사 테스트."""

    def test_health_check_compliant(self):
        plugin = CompliantPlugin()
        plugin.set_config({"name": "compliant", "version": "1.0.0"})
        plugin.set_status(PluginStatus.ACTIVE)
        fw = PluginTestFramework(plugin)
        result = fw.check_health()
        assert result["all_passed"]

    def test_health_check_non_plugin_interface(self):
        """PluginInterface를 구현하지 않은 객체."""
        from core.contracts.crawler import CrawlerContract

        fw = PluginTestFramework()
        fw.set_plugin(MinimalContract())
        result = fw.check_health()
        assert "error" in result
