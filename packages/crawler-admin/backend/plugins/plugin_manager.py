"""
플러그인 매니저 — 로드된 플러그인의 중앙 관리·상태 추적·이벤트 시스템.

왜 존재하는가:
    PluginLoader는 발견·로딩만 담당한다. 런타임에서 플러그인을
    활성화/비활성화하고, 설정을 오버라이드하고, 라이프사이클 이벤트를
    발행하는 것은 매니저의 책임이다.
어디서 쓰이나:
    API 서버, 스케줄러 등이 매니저를 통해 플러그인을 조회·제어한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .plugin_interface import PluginInterface, PluginStatus, PluginHealth, PluginMetrics
from .plugin_loader import PluginLoader

logger = logging.getLogger(__name__)

# 라이프사이클 이벤트 타입
PLUGIN_LOADED = "plugin.loaded"
PLUGIN_UNLOADED = "plugin.unloaded"
PLUGIN_ACTIVATED = "plugin.activated"
PLUGIN_DEACTIVATED = "plugin.deactivated"
PLUGIN_ERROR = "plugin.error"
PLUGIN_RELOADED = "plugin.reloaded"

# 이벤트 핸들러 타입
PluginEventHandler = Callable[[str, str, dict[str, Any]], None]


class PluginManager:
    """
    크롤러 플러그인 중앙 관리자.

    기능:
        - 플러그인 발견·로드·언로드 (PluginLoader 위임)
        - 런타임 활성화/비활성화
        - 상태 추적 및 조회
        - 설정 오버라이드
        - 라이프사이클 이벤트 발행
    """

    def __init__(self, plugin_dirs: Optional[list[Path]] = None):
        self._loader = PluginLoader(plugin_dirs or [])
        self._config_overrides: dict[str, dict[str, Any]] = {}
        self._disabled_plugins: set[str] = set()
        self._event_handlers: dict[str, list[PluginEventHandler]] = {}

    @property
    def loader(self) -> PluginLoader:
        return self._loader

    # --- 발견·로드 ---

    def discover_and_load(self) -> dict[str, PluginInterface]:
        """모든 플러그인을 발견하고 로드한다."""
        self._loader.discover()
        loaded = self._loader.load_all()

        # 로드 성공한 플러그인에 이벤트 발행
        for name, plugin in loaded.items():
            self._emit(PLUGIN_LOADED, name, {"version": plugin.get_version()})

        return loaded

    async def initialize_all(self) -> None:
        """로드된 모든 플러그인의 on_load()를 호출하고 활성 상태로 전환한다."""
        for name, plugin in self._loader.loaded.items():
            if name in self._disabled_plugins:
                continue
            try:
                await plugin.on_load()
                plugin.set_status(PluginStatus.ACTIVE)
                self._emit(PLUGIN_ACTIVATED, name, {})
            except Exception as e:
                plugin.set_status(PluginStatus.ERROR)
                await plugin.on_error(e)
                self._emit(PLUGIN_ERROR, name, {"error": str(e)})
                logger.error(f"플러그인 초기화 실패: {name}: {e}")

    # --- 활성화/비활성화 ---

    async def enable_plugin(self, name: str) -> bool:
        """플러그인을 활성화한다."""
        plugin = self._loader.loaded.get(name)
        if not plugin:
            logger.warning(f"플러그인 없음: {name}")
            return False

        self._disabled_plugins.discard(name)

        try:
            await plugin.on_load()
            plugin.set_status(PluginStatus.ACTIVE)
            self._emit(PLUGIN_ACTIVATED, name, {})
            return True
        except Exception as e:
            plugin.set_status(PluginStatus.ERROR)
            await plugin.on_error(e)
            self._emit(PLUGIN_ERROR, name, {"error": str(e)})
            return False

    async def disable_plugin(self, name: str) -> bool:
        """플러그인을 비활성화한다."""
        plugin = self._loader.loaded.get(name)
        if not plugin:
            return False

        self._disabled_plugins.add(name)

        try:
            await plugin.on_unload()
        except Exception as e:
            logger.warning(f"플러그인 언로드 중 에러: {name}: {e}")

        plugin.set_status(PluginStatus.DISABLED)
        self._emit(PLUGIN_DEACTIVATED, name, {})
        return True

    # --- 조회 ---

    def get_plugin(self, name: str) -> Optional[PluginInterface]:
        """이름으로 플러그인 인스턴스를 가져온다."""
        return self._loader.loaded.get(name)

    def get_active_plugins(self) -> dict[str, PluginInterface]:
        """활성 상태의 플러그인만 반환한다."""
        return {
            name: plugin
            for name, plugin in self._loader.loaded.items()
            if plugin.get_status() == PluginStatus.ACTIVE
        }

    def get_all_plugins(self) -> dict[str, PluginInterface]:
        """로드된 모든 플러그인을 반환한다."""
        return dict(self._loader.loaded)

    def get_plugin_status(self, name: str) -> Optional[PluginStatus]:
        """플러그인 상태를 반환한다."""
        plugin = self._loader.loaded.get(name)
        if plugin:
            return plugin.get_status()
        return None

    def get_plugin_health(self, name: str) -> Optional[PluginHealth]:
        """플러그인 건강 상태를 반환한다."""
        plugin = self._loader.loaded.get(name)
        if plugin:
            return plugin.get_health()
        return None

    def get_plugin_metrics(self, name: str) -> Optional[PluginMetrics]:
        """플러그인 메트릭을 반환한다."""
        plugin = self._loader.loaded.get(name)
        if plugin:
            return plugin.get_metrics()
        return None

    def list_plugins(self) -> list[dict[str, Any]]:
        """모든 플러그인의 요약 정보를 반환한다."""
        result = []
        for name, plugin in self._loader.loaded.items():
            config = plugin.get_config()
            result.append({
                "name": name,
                "display_name": config.get("display_name", name),
                "version": plugin.get_version(),
                "category": config.get("category", "unknown"),
                "status": plugin.get_status().value,
                "is_healthy": plugin.get_health().is_healthy,
            })

        # 발견되었지만 로드 실패한 것들도 포함
        for name, error in self._loader.errors.items():
            if name not in self._loader.loaded:
                result.append({
                    "name": name,
                    "display_name": name,
                    "version": "?",
                    "category": "unknown",
                    "status": PluginStatus.ERROR.value,
                    "is_healthy": False,
                    "error": error,
                })

        return result

    # --- 설정 오버라이드 ---

    def override_config(self, name: str, overrides: dict[str, Any]) -> bool:
        """플러그인 설정을 오버라이드한다."""
        plugin = self._loader.loaded.get(name)
        if not plugin:
            return False

        self._config_overrides.setdefault(name, {}).update(overrides)

        # 기존 설정에 오버라이드 병합
        config = plugin.get_config()
        config.update(overrides)
        plugin.set_config(config)

        return True

    def get_config_overrides(self, name: str) -> dict[str, Any]:
        """적용된 설정 오버라이드를 반환한다."""
        return dict(self._config_overrides.get(name, {}))

    # --- 핫 리로드 ---

    async def reload_plugin(self, name: str) -> Optional[PluginInterface]:
        """플러그인을 핫 리로드한다."""
        old_plugin = self._loader.loaded.get(name)
        if old_plugin:
            try:
                await old_plugin.on_unload()
            except Exception:
                pass

        plugin = self._loader.reload_plugin(name)

        if plugin:
            # 오버라이드 재적용
            overrides = self._config_overrides.get(name)
            if overrides:
                config = plugin.get_config()
                config.update(overrides)
                plugin.set_config(config)

            if name not in self._disabled_plugins:
                try:
                    await plugin.on_load()
                    plugin.set_status(PluginStatus.ACTIVE)
                except Exception as e:
                    plugin.set_status(PluginStatus.ERROR)
                    await plugin.on_error(e)

            self._emit(PLUGIN_RELOADED, name, {"version": plugin.get_version()})

        return plugin

    # --- 이벤트 시스템 ---

    def on(self, event_type: str, handler: PluginEventHandler) -> None:
        """라이프사이클 이벤트를 구독한다."""
        self._event_handlers.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: PluginEventHandler) -> None:
        """이벤트 구독을 해제한다."""
        handlers = self._event_handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def _emit(self, event_type: str, plugin_name: str, data: dict[str, Any]) -> None:
        """이벤트를 발행한다."""
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event_type, plugin_name, data)
            except Exception as e:
                logger.error(f"이벤트 핸들러 오류: {event_type}/{plugin_name}: {e}")

    # --- 정리 ---

    async def shutdown(self) -> None:
        """모든 플러그인을 정리하고 종료한다."""
        for name in list(self._loader.loaded.keys()):
            try:
                plugin = self._loader.loaded[name]
                await plugin.on_unload()
            except Exception as e:
                logger.warning(f"플러그인 종료 중 에러: {name}: {e}")

            self._loader.unload_plugin(name)
            self._emit(PLUGIN_UNLOADED, name, {})
