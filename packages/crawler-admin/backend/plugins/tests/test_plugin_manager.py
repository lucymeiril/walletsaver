"""
PluginManager 테스트 — 활성화/비활성화, 상태 추적, 설정 오버라이드, 이벤트.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from plugins.plugin_interface import PluginInterface, PluginStatus
from plugins.plugin_manager import (
    PluginManager,
    PLUGIN_LOADED,
    PLUGIN_ACTIVATED,
    PLUGIN_DEACTIVATED,
    PLUGIN_ERROR,
    PLUGIN_RELOADED,
    PLUGIN_UNLOADED,
)
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus

# 테스트 헬퍼 — test_plugin_loader.py의 것을 재활용
from plugins.tests.test_plugin_loader import create_test_plugin


class TestPluginManagerDiscoverAndLoad:
    """발견·로드 통합 테스트."""

    def test_discover_and_load(self, tmp_path):
        create_test_plugin(tmp_path, "mgr-a")
        create_test_plugin(tmp_path, "mgr-b")

        manager = PluginManager([tmp_path])
        loaded = manager.discover_and_load()

        assert "mgr-a" in loaded
        assert "mgr-b" in loaded

    def test_empty_dir_no_error(self, tmp_path):
        manager = PluginManager([tmp_path])
        loaded = manager.discover_and_load()
        assert loaded == {}


class TestPluginManagerEnableDisable:
    """런타임 활성화/비활성화 테스트."""

    @pytest.mark.asyncio
    async def test_initialize_all_activates(self, tmp_path):
        create_test_plugin(tmp_path, "init-test")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()
        await manager.initialize_all()

        plugin = manager.get_plugin("init-test")
        assert plugin is not None
        assert plugin.get_status() == PluginStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_disable_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "disable-me")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()
        await manager.initialize_all()

        result = await manager.disable_plugin("disable-me")
        assert result is True
        assert manager.get_plugin_status("disable-me") == PluginStatus.DISABLED

    @pytest.mark.asyncio
    async def test_enable_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "enable-me")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        await manager.disable_plugin("enable-me")
        result = await manager.enable_plugin("enable-me")
        assert result is True
        assert manager.get_plugin_status("enable-me") == PluginStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, tmp_path):
        manager = PluginManager([tmp_path])
        result = await manager.disable_plugin("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, tmp_path):
        manager = PluginManager([tmp_path])
        result = await manager.enable_plugin("nonexistent")
        assert result is False


class TestPluginManagerQuery:
    """조회 테스트."""

    @pytest.mark.asyncio
    async def test_get_active_plugins(self, tmp_path):
        create_test_plugin(tmp_path, "active-a")
        create_test_plugin(tmp_path, "active-b")

        manager = PluginManager([tmp_path])
        manager.discover_and_load()
        await manager.initialize_all()

        await manager.disable_plugin("active-b")

        active = manager.get_active_plugins()
        assert "active-a" in active
        assert "active-b" not in active

    def test_get_all_plugins(self, tmp_path):
        create_test_plugin(tmp_path, "all-a")
        create_test_plugin(tmp_path, "all-b")

        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        all_plugins = manager.get_all_plugins()
        assert len(all_plugins) == 2

    def test_get_plugin_status_none(self, tmp_path):
        manager = PluginManager([tmp_path])
        assert manager.get_plugin_status("nonexistent") is None

    def test_get_plugin_health(self, tmp_path):
        create_test_plugin(tmp_path, "health-check")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        health = manager.get_plugin_health("health-check")
        assert health is not None
        assert health.status == PluginStatus.LOADED

    def test_get_plugin_metrics(self, tmp_path):
        create_test_plugin(tmp_path, "metrics-check")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        metrics = manager.get_plugin_metrics("metrics-check")
        assert metrics is not None
        assert metrics.total_runs == 0

    def test_list_plugins(self, tmp_path):
        create_test_plugin(tmp_path, "list-a")
        create_test_plugin(tmp_path, "list-b")

        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        listing = manager.list_plugins()
        assert len(listing) == 2
        names = {p["name"] for p in listing}
        assert "list-a" in names
        assert "list-b" in names

    def test_list_includes_errors(self, tmp_path):
        create_test_plugin(tmp_path, "good-list")
        create_test_plugin(tmp_path, "bad-list", version="invalid")

        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        listing = manager.list_plugins()
        error_items = [p for p in listing if p.get("status") == "error"]
        assert len(error_items) >= 1


class TestPluginManagerConfigOverride:
    """설정 오버라이드 테스트."""

    def test_override_config(self, tmp_path):
        create_test_plugin(tmp_path, "override-test")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        result = manager.override_config("override-test", {"schedule": {"cron": "0 12 * * *"}})
        assert result is True

        plugin = manager.get_plugin("override-test")
        config = plugin.get_config()
        assert config["schedule"]["cron"] == "0 12 * * *"

    def test_override_nonexistent(self, tmp_path):
        manager = PluginManager([tmp_path])
        result = manager.override_config("nonexistent", {"key": "value"})
        assert result is False

    def test_get_config_overrides(self, tmp_path):
        create_test_plugin(tmp_path, "overrides-get")
        manager = PluginManager([tmp_path])
        manager.discover_and_load()

        manager.override_config("overrides-get", {"custom_key": "custom_value"})
        overrides = manager.get_config_overrides("overrides-get")
        assert overrides == {"custom_key": "custom_value"}


class TestPluginManagerEvents:
    """이벤트 시스템 테스트."""

    def test_event_on_load(self, tmp_path):
        create_test_plugin(tmp_path, "event-test")

        events_received: list[tuple] = []

        def handler(event_type: str, name: str, data: dict):
            events_received.append((event_type, name, data))

        manager = PluginManager([tmp_path])
        manager.on(PLUGIN_LOADED, handler)
        manager.discover_and_load()

        assert len(events_received) >= 1
        assert events_received[0][0] == PLUGIN_LOADED
        assert events_received[0][1] == "event-test"

    @pytest.mark.asyncio
    async def test_event_on_activate(self, tmp_path):
        create_test_plugin(tmp_path, "activate-event")

        events: list[str] = []

        def handler(event_type: str, name: str, data: dict):
            events.append(event_type)

        manager = PluginManager([tmp_path])
        manager.on(PLUGIN_ACTIVATED, handler)
        manager.discover_and_load()
        await manager.initialize_all()

        assert PLUGIN_ACTIVATED in events

    @pytest.mark.asyncio
    async def test_event_on_deactivate(self, tmp_path):
        create_test_plugin(tmp_path, "deactivate-event")

        events: list[str] = []

        def handler(event_type: str, name: str, data: dict):
            events.append(event_type)

        manager = PluginManager([tmp_path])
        manager.on(PLUGIN_DEACTIVATED, handler)
        manager.discover_and_load()
        await manager.initialize_all()
        await manager.disable_plugin("deactivate-event")

        assert PLUGIN_DEACTIVATED in events

    def test_unsubscribe_event(self, tmp_path):
        events: list[str] = []

        def handler(event_type: str, name: str, data: dict):
            events.append(event_type)

        manager = PluginManager([tmp_path])
        manager.on(PLUGIN_LOADED, handler)
        manager.off(PLUGIN_LOADED, handler)

        create_test_plugin(tmp_path, "unsub-test")
        manager.discover_and_load()

        assert len(events) == 0


class TestPluginManagerReloadAndShutdown:
    """핫 리로드 및 종료 테스트."""

    @pytest.mark.asyncio
    async def test_reload_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "reload-mgr")

        events: list[str] = []

        def handler(event_type: str, name: str, data: dict):
            events.append(event_type)

        manager = PluginManager([tmp_path])
        manager.on(PLUGIN_RELOADED, handler)
        manager.discover_and_load()

        plugin = await manager.reload_plugin("reload-mgr")
        assert plugin is not None
        assert PLUGIN_RELOADED in events

    @pytest.mark.asyncio
    async def test_shutdown(self, tmp_path):
        create_test_plugin(tmp_path, "shutdown-a")
        create_test_plugin(tmp_path, "shutdown-b")

        manager = PluginManager([tmp_path])
        manager.discover_and_load()
        await manager.initialize_all()

        await manager.shutdown()

        assert len(manager.get_all_plugins()) == 0
