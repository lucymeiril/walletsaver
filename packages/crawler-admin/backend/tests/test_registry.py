"""Registry contracts for the current explicit crawler allowlist."""
from __future__ import annotations

from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry


def test_default_registry_contains_only_four_core_marts(monkeypatch):
    monkeypatch.delenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", raising=False)
    registry = CrawlerRegistry()
    registry.discover()

    names = {row["name"] for row in registry.list_crawlers()}
    assert names == {"emart", "homeplus", "lottemart", "costco"}
    assert {row["category"] for row in registry.list_crawlers()} == {"mart"}


def test_optional_crawlers_are_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", "musinsa,algumon")
    registry = CrawlerRegistry()
    registry.discover()

    names = {row["name"] for row in registry.list_crawlers()}
    assert names == {"emart", "homeplus", "lottemart", "costco", "musinsa", "algumon"}

    config = registry._registry["algumon"]["config"]
    assert config["output"]["model"] == "HotdealPost"
    assert config["schedule"]["cron"] == "manual"


def test_plugin_yaml_files_do_not_create_runtime_crawlers(tmp_path, monkeypatch):
    monkeypatch.delenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", raising=False)
    ghost = tmp_path / "delivery" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "plugin.yaml").write_text(
        "name: ghost\ndisplay_name: Ghost\ncategory: delivery\n",
        encoding="utf-8",
    )

    registry = CrawlerRegistry(crawlers_dir=Path(tmp_path))
    registry.discover()

    assert "ghost" not in registry._registry
    assert {row["name"] for row in registry.list_crawlers()} == {
        "emart",
        "homeplus",
        "lottemart",
        "costco",
    }


def test_unknown_optional_name_is_ignored(monkeypatch):
    monkeypatch.setenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", "ghost,musinsa")
    registry = CrawlerRegistry()
    registry.discover()

    assert "ghost" not in registry._registry
    assert "musinsa" in registry._registry
