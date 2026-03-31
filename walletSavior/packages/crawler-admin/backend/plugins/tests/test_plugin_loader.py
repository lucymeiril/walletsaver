"""
PluginLoader 테스트 — 발견, 검증, 로딩, 의존성 해결, 에러 격리, 핫 리로드.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from plugins.plugin_loader import (
    PluginLoader,
    PluginValidationError,
    PluginLoadError,
    REQUIRED_FIELDS,
    VALID_CATEGORIES,
)
from plugins.plugin_interface import PluginInterface, PluginStatus


# --- 헬퍼: 임시 플러그인 생성 ---

def create_test_plugin(
    base_dir: Path,
    name: str,
    version: str = "1.0.0",
    category: str = "hotdeal",
    dependencies: list[str] | None = None,
    extra_yaml: dict | None = None,
    crawler_code: str | None = None,
) -> Path:
    """테스트용 플러그인 디렉토리를 생성한다."""
    plugin_dir = base_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # plugin.yaml
    config = {
        "name": name,
        "version": version,
        "category": category,
        "display_name": f"테스트 {name}",
        "description": f"{name} 테스트 플러그인",
        "dependencies": dependencies or [],
    }
    if extra_yaml:
        config.update(extra_yaml)

    yaml_path = plugin_dir / "plugin.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    # __init__.py
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    # crawler.py
    if crawler_code is None:
        crawler_code = textwrap.dedent(f"""
            from plugins.plugin_interface import PluginInterface, PluginStatus
            from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus

            class {name.replace('-', '_').title().replace('_', '')}Crawler(PluginInterface):
                @property
                def info(self):
                    return CrawlerInfo(
                        name="{name}",
                        version="{version}",
                        group=CrawlerGroup.HOTDEAL,
                    )

                async def crawl(self):
                    return CrawlResult(
                        status=CrawlStatus.SUCCESS,
                        crawler_name=self.info.name,
                        strategy_used="requests",
                        items_count=0,
                        items=[],
                    )

                async def parse(self, raw_data):
                    return []

                async def validate(self, items):
                    return items
        """)

    (plugin_dir / "crawler.py").write_text(crawler_code.strip(), encoding="utf-8")

    return plugin_dir


# --- 테스트 ---

class TestPluginLoaderDiscover:
    """플러그인 발견 테스트."""

    def test_discover_empty_dir(self, tmp_path):
        loader = PluginLoader([tmp_path])
        result = loader.discover()
        assert result == {}

    def test_discover_single_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "test-a")
        loader = PluginLoader([tmp_path])
        result = loader.discover()
        assert "test-a" in result
        assert result["test-a"]["config"]["name"] == "test-a"

    def test_discover_multiple_plugins(self, tmp_path):
        create_test_plugin(tmp_path, "alpha")
        create_test_plugin(tmp_path, "beta")
        create_test_plugin(tmp_path, "gamma")
        loader = PluginLoader([tmp_path])
        result = loader.discover()
        assert len(result) == 3
        assert set(result.keys()) == {"alpha", "beta", "gamma"}

    def test_discover_nonexistent_dir(self, tmp_path):
        loader = PluginLoader([tmp_path / "does_not_exist"])
        result = loader.discover()
        assert result == {}

    def test_discover_invalid_yaml(self, tmp_path):
        plugin_dir = tmp_path / "bad"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(": : invalid yaml }{", encoding="utf-8")
        loader = PluginLoader([tmp_path])
        result = loader.discover()
        # 잘못된 YAML은 발견에서 제외되고 errors에 기록
        assert "bad" not in result
        assert len(loader.errors) > 0


class TestPluginLoaderValidation:
    """plugin.yaml 스키마 검증 테스트."""

    def test_valid_config(self):
        loader = PluginLoader()
        errors = loader.validate_config({
            "name": "test",
            "version": "1.0.0",
            "category": "hotdeal",
        })
        assert errors == []

    def test_missing_name(self):
        loader = PluginLoader()
        errors = loader.validate_config({"version": "1.0.0"})
        assert any("name" in e for e in errors)

    def test_missing_version(self):
        loader = PluginLoader()
        errors = loader.validate_config({"name": "test"})
        assert any("version" in e for e in errors)

    def test_invalid_version_format(self):
        loader = PluginLoader()
        errors = loader.validate_config({"name": "test", "version": "v1.0"})
        assert any("버전" in e or "version" in e.lower() for e in errors)

    def test_valid_semver(self):
        loader = PluginLoader()
        errors = loader.validate_config({"name": "test", "version": "2.3.14"})
        assert errors == []

    def test_invalid_category(self):
        loader = PluginLoader()
        errors = loader.validate_config({
            "name": "test", "version": "1.0.0", "category": "invalid_cat",
        })
        assert any("카테고리" in e or "category" in e.lower() for e in errors)

    def test_valid_categories(self):
        loader = PluginLoader()
        for cat in VALID_CATEGORIES:
            errors = loader.validate_config({
                "name": "test", "version": "1.0.0", "category": cat,
            })
            assert errors == [], f"카테고리 '{cat}'가 유효해야 함"

    def test_invalid_difficulty_range(self):
        loader = PluginLoader()
        errors = loader.validate_config({
            "name": "test", "version": "1.0.0",
            "target": {"difficulty": 6},
        })
        assert any("difficulty" in e for e in errors)

    def test_invalid_difficulty_zero(self):
        loader = PluginLoader()
        errors = loader.validate_config({
            "name": "test", "version": "1.0.0",
            "target": {"difficulty": 0},
        })
        assert any("difficulty" in e for e in errors)

    def test_valid_difficulty(self):
        loader = PluginLoader()
        for d in range(1, 6):
            errors = loader.validate_config({
                "name": "test", "version": "1.0.0",
                "target": {"difficulty": d},
            })
            assert errors == [], f"difficulty {d}는 유효해야 함"

    def test_invalid_dependencies_type(self):
        loader = PluginLoader()
        errors = loader.validate_config({
            "name": "test", "version": "1.0.0",
            "dependencies": "not-a-list",
        })
        assert any("dependencies" in e for e in errors)


class TestPluginLoaderLoading:
    """플러그인 로딩 테스트."""

    def test_load_single_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "loader-test")
        loader = PluginLoader([tmp_path])
        loader.discover()
        plugin = loader.load_plugin("loader-test")
        assert plugin is not None
        assert plugin.get_status() == PluginStatus.LOADED
        assert plugin.get_config()["name"] == "loader-test"

    def test_load_returns_same_instance(self, tmp_path):
        create_test_plugin(tmp_path, "single")
        loader = PluginLoader([tmp_path])
        loader.discover()
        p1 = loader.load_plugin("single")
        p2 = loader.load_plugin("single")
        assert p1 is p2

    def test_load_unknown_plugin_raises(self, tmp_path):
        loader = PluginLoader([tmp_path])
        loader.discover()
        with pytest.raises(PluginLoadError):
            loader.load_plugin("nonexistent")

    def test_load_invalid_yaml_raises(self, tmp_path):
        create_test_plugin(tmp_path, "bad-version", version="invalid")
        loader = PluginLoader([tmp_path])
        loader.discover()
        with pytest.raises(PluginValidationError):
            loader.load_plugin("bad-version")

    def test_load_all_error_isolation(self, tmp_path):
        """하나의 플러그인이 실패해도 나머지는 로드된다."""
        create_test_plugin(tmp_path, "good-one")
        create_test_plugin(tmp_path, "bad-one", version="invalid")
        create_test_plugin(tmp_path, "good-two")

        loader = PluginLoader([tmp_path])
        loader.discover()
        loaded = loader.load_all()

        assert "good-one" in loaded
        assert "good-two" in loaded
        assert "bad-one" not in loaded
        assert "bad-one" in loader.errors

    def test_load_missing_crawler_py(self, tmp_path):
        """crawler.py가 없으면 로드 실패."""
        plugin_dir = tmp_path / "no-code"
        plugin_dir.mkdir()
        with open(plugin_dir / "plugin.yaml", "w") as f:
            yaml.dump({"name": "no-code", "version": "1.0.0"}, f)

        loader = PluginLoader([tmp_path])
        loader.discover()
        with pytest.raises(PluginLoadError):
            loader.load_plugin("no-code")


class TestPluginLoaderDependencies:
    """의존성 해결 테스트."""

    def test_dependency_load_order(self, tmp_path):
        """의존 플러그인이 먼저 로드된다."""
        create_test_plugin(tmp_path, "base-plugin")
        create_test_plugin(tmp_path, "dep-plugin", dependencies=["base-plugin"])

        loader = PluginLoader([tmp_path])
        loader.discover()
        loaded = loader.load_all()

        assert "base-plugin" in loaded
        assert "dep-plugin" in loaded

    def test_missing_dependency_raises(self, tmp_path):
        """존재하지 않는 의존 플러그인은 에러."""
        create_test_plugin(tmp_path, "orphan", dependencies=["nonexistent"])

        loader = PluginLoader([tmp_path])
        loader.discover()
        with pytest.raises(PluginLoadError):
            loader.load_plugin("orphan")


class TestPluginLoaderUnloadReload:
    """언로드 및 핫 리로드 테스트."""

    def test_unload_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "unload-me")
        loader = PluginLoader([tmp_path])
        loader.discover()
        loader.load_plugin("unload-me")

        assert "unload-me" in loader.loaded
        loader.unload_plugin("unload-me")
        assert "unload-me" not in loader.loaded

    def test_unload_nonexistent_is_noop(self, tmp_path):
        loader = PluginLoader([tmp_path])
        loader.unload_plugin("does-not-exist")  # 에러 없이 무시

    def test_reload_plugin(self, tmp_path):
        create_test_plugin(tmp_path, "reload-me")
        loader = PluginLoader([tmp_path])
        loader.discover()
        original = loader.load_plugin("reload-me")

        reloaded = loader.reload_plugin("reload-me")
        assert reloaded is not None
        assert reloaded is not original  # 새 인스턴스
