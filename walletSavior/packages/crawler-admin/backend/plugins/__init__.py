"""
플러그인 시스템 — 크롤러 플러그인의 발견·로딩·관리·테스트를 담당한다.

구성:
    plugin_interface.py  — 플러그인 인터페이스 (CrawlerContract 확장)
    plugin_loader.py     — 플러그인 자동 발견 및 로딩
    plugin_manager.py    — 플러그인 중앙 관리자
    test_framework.py    — 플러그인 개발자용 테스트 프레임워크
"""

from .plugin_interface import PluginInterface, PluginStatus, PluginHealth, PluginMetrics
from .plugin_loader import PluginLoader, PluginValidationError
from .plugin_manager import PluginManager

__all__ = [
    "PluginInterface",
    "PluginStatus",
    "PluginHealth",
    "PluginMetrics",
    "PluginLoader",
    "PluginValidationError",
    "PluginManager",
]
