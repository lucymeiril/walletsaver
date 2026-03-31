"""크롤러 레지스트리 — 플러그인 자동 발견 및 등록."""

import importlib
import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class CrawlerRegistry:
    """폴더 스캔 기반 크롤러 자동 등록."""

    def __init__(self, crawlers_dir: Optional[Path] = None):
        self.crawlers_dir = crawlers_dir or Path(__file__).parent.parent
        self._registry: Dict[str, dict] = {}

    def discover(self) -> Dict[str, dict]:
        """crawlers/ 디렉토리에서 plugin.yaml을 가진 크롤러 자동 발견."""
        for plugin_yaml in self.crawlers_dir.rglob("plugin.yaml"):
            try:
                with open(plugin_yaml, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                crawler_dir = plugin_yaml.parent
                module_path = self._resolve_module_path(crawler_dir)

                self._registry[config["name"]] = {
                    "config": config,
                    "path": str(crawler_dir),
                    "module_path": module_path,
                }
            except Exception as e:
                logger.warning(f"[Registry] {plugin_yaml} 로드 실패: {e}")

        return self._registry

    def get_crawler(self, name: str):
        """이름으로 크롤러 인스턴스 가져오기."""
        info = self._registry.get(name)
        if not info:
            raise KeyError(f"크롤러 '{name}' 을 찾을 수 없습니다")

        module = importlib.import_module(info["module_path"])
        crawler_class = getattr(module, "Crawler", None)
        if not crawler_class:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Crawler"):
                    crawler_class = attr
                    break

        if not crawler_class:
            raise ImportError(f"크롤러 클래스를 찾을 수 없습니다: {info['module_path']}")

        return crawler_class()

    def list_crawlers(self) -> list[dict]:
        """등록된 모든 크롤러 목록."""
        result = []
        for name, info in self._registry.items():
            sched = info["config"].get("schedule", {})
            if isinstance(sched, str):
                schedule_str = sched
            elif isinstance(sched, dict):
                schedule_str = sched.get("cron", "manual")
            else:
                schedule_str = "manual"

            difficulty = info["config"].get("difficulty", 1)
            if isinstance(difficulty, dict):
                difficulty = 1
            target = info["config"].get("target", {})
            if isinstance(target, dict):
                difficulty = target.get("difficulty", difficulty)

            result.append({
                "name": name,
                "display_name": info["config"].get("display_name", name),
                "category": info["config"].get("category",
                             info["config"].get("group", "unknown")),
                "difficulty": difficulty,
                "schedule": schedule_str,
            })
        return result

    def _resolve_module_path(self, crawler_dir: Path) -> str:
        """크롤러 디렉토리를 Python 모듈 경로로 변환."""
        relative = crawler_dir.relative_to(self.crawlers_dir.parent)
        parts = list(relative.parts)
        return ".".join(parts) + ".crawler"
