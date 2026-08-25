"""Explicit registry for crawler implementations that belong to the current runtime.

The original registry recursively discovered every ``plugin.yaml`` below
``crawlers/``. That made abandoned experiments (delivery, location, old hotdeal
sources, etc.) look like live product features merely because their folders had
not been deleted yet.

Current core crawlers are registered in code. Optional crawlers are opt-in via
``WALLETSAVIOR_OPTIONAL_CRAWLERS`` (comma-separated names). OPINET is deliberately
not exposed through this registry yet because its current implementation is
fixture-only and has no live ``crawl()`` contract; its production code is kept
for the planned fuel-price feature without pretending it is runnable today.
"""
from __future__ import annotations

import importlib
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _crawler_config(
    name: str,
    display_name: str,
    category: str,
    *,
    model: str = "DiscountItem",
    required_fields: list[str] | None = None,
    retry_count: int = 3,
) -> dict:
    return {
        "name": name,
        "display_name": display_name,
        "category": category,
        "difficulty": 1,
        "schedule": {"cron": "manual", "retry_count": retry_count},
        "output": {
            "model": model,
            "required_fields": required_fields or ["name", "sale_price"],
        },
    }


_CORE_CRAWLERS: dict[str, tuple[str, dict]] = {
    "emart": (
        "crawlers.marts.emart.crawler",
        _crawler_config("emart", "이마트", "mart"),
    ),
    "homeplus": (
        "crawlers.marts.homeplus.crawler",
        _crawler_config("homeplus", "홈플러스", "mart"),
    ),
    "lottemart": (
        "crawlers.marts.lottemart.crawler",
        _crawler_config("lottemart", "롯데마트", "mart"),
    ),
    "costco": (
        "crawlers.marts.costco.crawler",
        _crawler_config("costco", "코스트코", "mart"),
    ),
}

_OPTIONAL_CRAWLERS: dict[str, tuple[str, dict]] = {
    "musinsa": (
        "crawlers.shopping.musinsa.crawler",
        _crawler_config("musinsa", "무신사", "shopping", retry_count=2),
    ),
    "giordano": (
        "crawlers.shopping.giordano.crawler",
        _crawler_config("giordano", "지오다노", "shopping", retry_count=2),
    ),
    "uniqlo": (
        "crawlers.shopping.uniqlo.crawler",
        _crawler_config("uniqlo", "유니클로", "shopping", retry_count=2),
    ),
    "algumon": (
        "crawlers.hotdeals.algumon.crawler",
        _crawler_config(
            "algumon",
            "알구몬",
            "hotdeal",
            model="HotdealPost",
            required_fields=["title", "url", "price"],
            retry_count=1,
        ),
    ),
}


def _enabled_optional_names() -> set[str]:
    raw = os.getenv("WALLETSAVIOR_OPTIONAL_CRAWLERS", "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


class CrawlerRegistry:
    """Explicit crawler registry used by the ingestion-capable CrawlPipeline."""

    def __init__(self, crawlers_dir: Optional[Path] = None):
        self.crawlers_dir = crawlers_dir or Path(__file__).parent.parent
        self._registry: Dict[str, dict] = {}
        self._instance_cache: Dict[str, object] = {}
        self._metadata_cache: Optional[list[dict]] = None

    def discover(self) -> Dict[str, dict]:
        """Load only the current allowlist; filesystem/YAML contents are ignored."""
        self._metadata_cache = None
        self._instance_cache.clear()
        self._registry = {}

        for name, definition in _CORE_CRAWLERS.items():
            self._register_definition(name, definition)

        requested_optional = _enabled_optional_names()
        unknown = requested_optional - set(_OPTIONAL_CRAWLERS)
        if unknown:
            logger.warning(
                "[Registry] unknown optional crawlers ignored: %s",
                ", ".join(sorted(unknown)),
            )
        for name in sorted(requested_optional & set(_OPTIONAL_CRAWLERS)):
            self._register_definition(name, _OPTIONAL_CRAWLERS[name])

        return self._registry

    def _register_definition(self, name: str, definition: tuple[str, dict]) -> None:
        module_path, config = definition
        parts = module_path.split(".")
        relative_dir = Path(*parts[1:-1]) if len(parts) > 2 else Path(name)
        self._registry[name] = {
            "config": deepcopy(config),
            "path": str(self.crawlers_dir / relative_dir),
            "module_path": module_path,
        }

    def get_crawler(self, name: str):
        """Return a cached crawler instance from the explicit registry."""
        if name in self._instance_cache:
            return self._instance_cache[name]

        info = self._registry.get(name)
        if not info:
            raise KeyError(f"크롤러 '{name}' 을 찾을 수 없습니다")

        try:
            module = importlib.import_module(info["module_path"])
        except Exception as exc:
            logger.error(
                "[Registry] 모듈 임포트 실패 '%s': %s",
                info["module_path"],
                exc,
                exc_info=True,
            )
            raise ImportError(
                f"크롤러 모듈 로드 실패: {info['module_path']} — {exc}"
            ) from exc

        crawler_class = getattr(module, "Crawler", None)
        if not crawler_class:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Crawler"):
                    crawler_class = attr
                    break

        if not crawler_class:
            raise ImportError(f"크롤러 클래스를 찾을 수 없습니다: {info['module_path']}")

        instance = crawler_class()
        self._instance_cache[name] = instance
        return instance

    def list_crawlers(self) -> list[dict]:
        """Return metadata only for explicitly registered crawlers."""
        if self._metadata_cache is not None:
            return self._metadata_cache

        result = []
        for name, info in self._registry.items():
            config = info["config"]
            schedule = config.get("schedule", {})
            schedule_str = (
                schedule.get("cron", "manual")
                if isinstance(schedule, dict)
                else str(schedule or "manual")
            )
            result.append(
                {
                    "name": name,
                    "display_name": config.get("display_name", name),
                    "category": config.get("category", config.get("group", "unknown")),
                    "difficulty": config.get("difficulty", 1),
                    "schedule": schedule_str,
                }
            )
        self._metadata_cache = result
        return result
