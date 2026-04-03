"""
PluginInterface 테스트 — 라이프사이클 훅, 상태, 메트릭, 설정 관리.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus

from plugins.plugin_interface import (
    PluginInterface,
    PluginStatus,
    PluginHealth,
    PluginMetrics,
)


# --- 테스트용 구현 클래스 ---

class SamplePlugin(PluginInterface):
    """테스트용 최소 PluginInterface 구현."""

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="sample-plugin",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="테스트용 샘플 플러그인",
            target_url="https://example.com",
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        return CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name=self.info.name,
            strategy_used="requests",
            items_count=0,
            items=[],
        )

    async def parse(self, raw_data: str) -> list[dict]:
        return [{"title": "test", "url": "https://example.com/1"}]

    async def validate(self, items: list[dict]) -> list[dict]:
        return [item for item in items if item.get("title")]


class FailingPlugin(PluginInterface):
    """에러 시나리오 테스트용."""

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="failing-plugin",
            version="0.1.0",
            group=CrawlerGroup.MART,
        )

    async def crawl(self) -> CrawlResult:
        raise RuntimeError("의도적 실패")

    async def parse(self, raw_data: str) -> list[dict]:
        return []

    async def validate(self, items: list[dict]) -> list[dict]:
        return items


# --- 테스트 ---

class TestPluginStatus:
    """PluginStatus 열거형 테스트."""

    def test_status_values(self):
        assert PluginStatus.DISCOVERED == "discovered"
        assert PluginStatus.LOADED == "loaded"
        assert PluginStatus.ACTIVE == "active"
        assert PluginStatus.ERROR == "error"
        assert PluginStatus.DISABLED == "disabled"
        assert PluginStatus.UNLOADED == "unloaded"

    def test_status_is_string(self):
        assert isinstance(PluginStatus.ACTIVE, str)
        assert PluginStatus.ACTIVE == "active"


class TestPluginHealth:
    """PluginHealth 데이터 클래스 테스트."""

    def test_default_values(self):
        health = PluginHealth(status=PluginStatus.LOADED)
        assert health.is_healthy is True
        assert health.error_message is None
        assert health.consecutive_failures == 0

    def test_to_dict(self):
        health = PluginHealth(
            status=PluginStatus.ACTIVE,
            is_healthy=True,
            uptime_seconds=120.5,
        )
        d = health.to_dict()
        assert d["status"] == "active"
        assert d["is_healthy"] is True
        assert d["uptime_seconds"] == 120.5

    def test_unhealthy_state(self):
        health = PluginHealth(
            status=PluginStatus.ERROR,
            is_healthy=False,
            error_message="connection failed",
            consecutive_failures=3,
        )
        assert health.is_healthy is False
        assert health.error_message == "connection failed"


class TestPluginMetrics:
    """PluginMetrics 테스트."""

    def test_initial_state(self):
        m = PluginMetrics()
        assert m.total_runs == 0
        assert m.success_rate == 0.0
        assert m.last_run is None

    def test_record_success(self):
        m = PluginMetrics()
        m.record_run(success=True, duration=1.5, items_count=10)
        assert m.total_runs == 1
        assert m.success_count == 1
        assert m.failure_count == 0
        assert m.success_rate == 1.0
        assert m.total_items_collected == 10
        assert m.avg_duration_seconds == 1.5
        assert m.last_success is not None

    def test_record_failure(self):
        m = PluginMetrics()
        m.record_run(success=False, duration=0.5)
        assert m.total_runs == 1
        assert m.failure_count == 1
        assert m.success_rate == 0.0
        assert m.last_failure is not None

    def test_mixed_runs(self):
        m = PluginMetrics()
        m.record_run(success=True, duration=1.0, items_count=5)
        m.record_run(success=True, duration=2.0, items_count=10)
        m.record_run(success=False, duration=0.5)
        assert m.total_runs == 3
        assert m.success_count == 2
        assert m.failure_count == 1
        assert abs(m.success_rate - 2 / 3) < 0.01
        assert m.total_items_collected == 15

    def test_to_dict(self):
        m = PluginMetrics()
        m.record_run(success=True, duration=1.0, items_count=5)
        d = m.to_dict()
        assert d["total_runs"] == 1
        assert d["success_rate"] == 1.0
        assert d["total_items_collected"] == 5
        assert d["last_run"] is not None


class TestPluginInterface:
    """PluginInterface 라이프사이클 훅 테스트."""

    def test_initial_status_is_discovered(self):
        plugin = SamplePlugin()
        assert plugin.get_status() == PluginStatus.DISCOVERED

    @pytest.mark.asyncio
    async def test_on_load_changes_status(self):
        plugin = SamplePlugin()
        await plugin.on_load()
        assert plugin.get_status() == PluginStatus.LOADED
        assert plugin._loaded_at is not None

    @pytest.mark.asyncio
    async def test_on_unload_changes_status(self):
        plugin = SamplePlugin()
        await plugin.on_load()
        await plugin.on_unload()
        assert plugin.get_status() == PluginStatus.UNLOADED
        assert plugin._loaded_at is None

    @pytest.mark.asyncio
    async def test_on_error_increments_failures(self):
        plugin = SamplePlugin()
        await plugin.on_error(RuntimeError("test error"))
        assert plugin._consecutive_failures == 1
        assert plugin._error_message == "test error"

        await plugin.on_error(RuntimeError("another"))
        assert plugin._consecutive_failures == 2

    def test_on_success_resets_failures(self):
        plugin = SamplePlugin()
        plugin._consecutive_failures = 3
        plugin._error_message = "old error"
        plugin.on_success()
        assert plugin._consecutive_failures == 0
        assert plugin._error_message is None

    def test_get_config_default_empty(self):
        plugin = SamplePlugin()
        assert plugin.get_config() == {}

    def test_set_and_get_config(self):
        plugin = SamplePlugin()
        config = {"name": "test", "version": "1.0.0"}
        plugin.set_config(config)
        assert plugin.get_config() == config
        # 원본 dict 변경이 영향을 주지 않는지 확인
        result = plugin.get_config()
        result["extra"] = True
        assert "extra" not in plugin.get_config()

    @pytest.mark.asyncio
    async def test_get_health_after_load(self):
        plugin = SamplePlugin()
        await plugin.on_load()
        health = plugin.get_health()
        assert health.is_healthy is True
        assert health.status == PluginStatus.LOADED
        assert health.uptime_seconds >= 0

    def test_get_health_unhealthy_after_failures(self):
        plugin = SamplePlugin()
        plugin._status = PluginStatus.ACTIVE
        plugin._consecutive_failures = 5
        health = plugin.get_health()
        assert health.is_healthy is False

    def test_get_version_from_config(self):
        plugin = SamplePlugin()
        plugin.set_config({"version": "2.3.1"})
        assert plugin.get_version() == "2.3.1"

    def test_get_version_default(self):
        plugin = SamplePlugin()
        assert plugin.get_version() == "0.0.0"

    def test_get_dependencies(self):
        plugin = SamplePlugin()
        plugin.set_config({"dependencies": ["dep-a", "dep-b"]})
        assert plugin.get_dependencies() == ["dep-a", "dep-b"]

    def test_get_dependencies_default_empty(self):
        plugin = SamplePlugin()
        assert plugin.get_dependencies() == []

    def test_set_status(self):
        plugin = SamplePlugin()
        plugin.set_status(PluginStatus.ACTIVE)
        assert plugin.get_status() == PluginStatus.ACTIVE

    def test_is_subclass_of_crawler_contract(self):
        assert issubclass(PluginInterface, CrawlerContract)
        plugin = SamplePlugin()
        assert isinstance(plugin, CrawlerContract)
