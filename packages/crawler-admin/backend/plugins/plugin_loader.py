"""
플러그인 로더 — plugin.yaml 기반 크롤러 자동 발견·검증·로딩.

왜 존재하는가:
    기존 CrawlerRegistry는 발견만 했다. 이 로더는 스키마 검증, 의존성 해결,
    에러 격리, 핫 리로드까지 지원하여 프로덕션 수준의 플러그인 관리를 제공한다.
어디서 쓰이나:
    PluginManager가 내부적으로 사용하여 플러그인을 로드한다.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from .plugin_interface import PluginInterface, PluginStatus

logger = logging.getLogger(__name__)

# plugin.yaml 필수 필드
REQUIRED_FIELDS = {"name", "version"}

# 지원하는 카테고리
VALID_CATEGORIES = {"mart", "hotdeal", "food", "delivery", "shopping", "government", "location", "public"}

# 버전 형식: semver (major.minor.patch)
VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


class PluginValidationError(Exception):
    """plugin.yaml 검증 실패."""

    def __init__(self, plugin_name: str, message: str):
        self.plugin_name = plugin_name
        super().__init__(f"[{plugin_name}] {message}")


class PluginLoadError(Exception):
    """플러그인 모듈 로드 실패."""

    def __init__(self, plugin_name: str, message: str):
        self.plugin_name = plugin_name
        super().__init__(f"[{plugin_name}] {message}")


class PluginLoader:
    """
    플러그인 자동 발견·검증·로딩 엔진.

    1) 지정 디렉토리에서 plugin.yaml 스캔
    2) 스키마 검증 (필수 필드, 버전 형식 등)
    3) 의존성 해결 (의존 플러그인을 먼저 로드)
    4) 동적 임포트 및 인스턴스 생성
    5) 에러 격리 — 하나가 실패해도 나머지는 정상 로드
    """

    def __init__(self, plugin_dirs: Optional[list[Path]] = None):
        self._plugin_dirs: list[Path] = plugin_dirs or []
        self._discovered: dict[str, dict[str, Any]] = {}
        self._loaded: dict[str, PluginInterface] = {}
        self._errors: dict[str, str] = {}

    @property
    def discovered(self) -> dict[str, dict[str, Any]]:
        return dict(self._discovered)

    @property
    def loaded(self) -> dict[str, PluginInterface]:
        return dict(self._loaded)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    def discover(self) -> dict[str, dict[str, Any]]:
        """모든 플러그인 디렉토리를 스캔하여 plugin.yaml을 발견한다."""
        self._discovered.clear()

        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                logger.warning(f"플러그인 디렉토리 없음: {plugin_dir}")
                continue

            for yaml_path in plugin_dir.rglob("plugin.yaml"):
                try:
                    config = self._load_yaml(yaml_path)
                    name = config.get("name", yaml_path.parent.name)
                    config.setdefault("name", name)

                    self._discovered[name] = {
                        "config": config,
                        "path": str(yaml_path.parent),
                        "yaml_path": str(yaml_path),
                    }
                    logger.info(f"플러그인 발견: {name} ({yaml_path.parent})")
                except Exception as e:
                    logger.warning(f"plugin.yaml 읽기 실패: {yaml_path}: {e}")
                    self._errors[str(yaml_path)] = str(e)

        return self._discovered

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """plugin.yaml 설정을 검증하여 오류 목록을 반환한다."""
        errors: list[str] = []
        name = config.get("name", "unknown")

        # 필수 필드 확인
        for field_name in REQUIRED_FIELDS:
            if field_name not in config:
                errors.append(f"필수 필드 누락: {field_name}")

        # 버전 형식 검증
        version = config.get("version", "")
        if version:
            import re
            if not re.match(VERSION_PATTERN, version):
                errors.append(f"잘못된 버전 형식: '{version}' (expected: X.Y.Z)")

        # 카테고리 검증 (있으면)
        category = config.get("category")
        if category and category not in VALID_CATEGORIES:
            errors.append(f"알 수 없는 카테고리: '{category}' (지원: {VALID_CATEGORIES})")

        # target 섹션 검증
        target = config.get("target", {})
        if target:
            difficulty = target.get("difficulty")
            if difficulty is not None:
                if not isinstance(difficulty, int) or difficulty < 1 or difficulty > 5:
                    errors.append(f"difficulty는 1~5 사이 정수여야 한다: {difficulty}")

        # dependencies 검증
        deps = config.get("dependencies", [])
        if not isinstance(deps, list):
            errors.append("dependencies는 리스트여야 한다")

        return errors

    def load_plugin(self, name: str) -> PluginInterface:
        """이름으로 단일 플러그인을 로드한다."""
        if name in self._loaded:
            return self._loaded[name]

        info = self._discovered.get(name)
        if not info:
            raise PluginLoadError(name, "발견되지 않은 플러그인")

        config = info["config"]

        # 스키마 검증
        validation_errors = self.validate_config(config)
        if validation_errors:
            error_msg = "; ".join(validation_errors)
            self._errors[name] = error_msg
            raise PluginValidationError(name, error_msg)

        # 의존성 먼저 로드
        dependencies = config.get("dependencies", [])
        for dep_name in dependencies:
            if dep_name not in self._loaded:
                try:
                    self.load_plugin(dep_name)
                except Exception as e:
                    raise PluginLoadError(
                        name, f"의존 플러그인 '{dep_name}' 로드 실패: {e}"
                    )

        # 모듈 동적 임포트
        plugin_dir = Path(info["path"])
        instance = self._import_plugin(name, plugin_dir)

        # 설정 주입
        instance.set_config(config)
        instance.set_status(PluginStatus.LOADED)
        self._loaded[name] = instance

        logger.info(f"플러그인 로드 완료: {name} v{config.get('version', '?')}")
        return instance

    def load_all(self) -> dict[str, PluginInterface]:
        """
        발견된 모든 플러그인을 로드한다.

        의존성 순서를 고려하여 로드하며,
        하나가 실패해도 나머지는 계속 로드한다 (에러 격리).
        """
        load_order = self._resolve_dependencies()

        for name in load_order:
            try:
                self.load_plugin(name)
            except Exception as e:
                logger.error(f"플러그인 로드 실패: {name}: {e}")
                self._errors[name] = str(e)

        return dict(self._loaded)

    def unload_plugin(self, name: str) -> None:
        """플러그인을 언로드한다."""
        if name not in self._loaded:
            return

        plugin = self._loaded.pop(name)
        plugin.set_status(PluginStatus.UNLOADED)
        logger.info(f"플러그인 언로드: {name}")

    def reload_plugin(self, name: str) -> Optional[PluginInterface]:
        """플러그인을 핫 리로드한다 (언로드 → YAML 재로드 → 로드)."""
        self.unload_plugin(name)

        # plugin.yaml 재로드
        info = self._discovered.get(name)
        if info:
            yaml_path = Path(info["yaml_path"])
            if yaml_path.exists():
                config = self._load_yaml(yaml_path)
                config.setdefault("name", name)
                self._discovered[name]["config"] = config

        # 모듈 캐시에서 제거 (진짜 리로드를 위해)
        if info:
            plugin_dir = Path(info["path"])
            module_name = self._make_module_name(name, plugin_dir)
            if module_name in sys.modules:
                del sys.modules[module_name]

        try:
            return self.load_plugin(name)
        except Exception as e:
            logger.error(f"플러그인 리로드 실패: {name}: {e}")
            self._errors[name] = str(e)
            return None

    def _load_yaml(self, yaml_path: Path) -> dict[str, Any]:
        """YAML 파일을 읽어 dict로 반환한다."""
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _import_plugin(self, name: str, plugin_dir: Path) -> PluginInterface:
        """플러그인 디렉토리에서 크롤러 모듈을 동적으로 임포트한다."""
        crawler_file = plugin_dir / "crawler.py"
        if not crawler_file.exists():
            raise PluginLoadError(name, f"crawler.py 없음: {plugin_dir}")

        module_name = self._make_module_name(name, plugin_dir)

        try:
            spec = importlib.util.spec_from_file_location(module_name, str(crawler_file))
            if spec is None or spec.loader is None:
                raise PluginLoadError(name, f"모듈 스펙 생성 실패: {crawler_file}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except PluginLoadError:
            raise
        except Exception as e:
            raise PluginLoadError(name, f"모듈 임포트 실패: {e}")

        # 크롤러 클래스 탐색
        crawler_class = self._find_crawler_class(module, name)
        if crawler_class is None:
            raise PluginLoadError(name, "PluginInterface/CrawlerContract 구현 클래스를 찾을 수 없음")

        try:
            instance = crawler_class()
        except Exception as e:
            raise PluginLoadError(name, f"인스턴스 생성 실패: {e}")

        return instance

    def _find_crawler_class(self, module: Any, name: str) -> Optional[type]:
        """모듈에서 PluginInterface 또는 CrawlerContract 구현 클래스를 찾는다."""
        from core.contracts.crawler import CrawlerContract

        # 1) 'Crawler'라는 이름의 클래스
        crawler_class = getattr(module, "Crawler", None)
        if crawler_class and isinstance(crawler_class, type):
            return crawler_class

        # 2) *Crawler로 끝나는 클래스
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and attr_name.endswith("Crawler")
                and issubclass(attr, (PluginInterface, CrawlerContract))
                and attr not in (PluginInterface, CrawlerContract)
            ):
                return attr

        # 3) CrawlerContract의 서브클래스 아무거나
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, (PluginInterface, CrawlerContract))
                and attr not in (PluginInterface, CrawlerContract)
            ):
                return attr

        return None

    def _make_module_name(self, plugin_name: str, plugin_dir: Path) -> str:
        """플러그인 이름과 경로로 고유 모듈명을 생성한다."""
        safe_name = plugin_name.replace("-", "_").replace(" ", "_")
        return f"_plugin_{safe_name}"

    def _resolve_dependencies(self) -> list[str]:
        """
        의존성 그래프를 토폴로지 정렬하여 로드 순서를 결정한다.
        순환 의존성이 있으면 순환에 속한 플러그인을 건너뛴다.
        """
        # 그래프 구성
        in_degree: dict[str, int] = {}
        graph: dict[str, list[str]] = {}
        all_names = set(self._discovered.keys())

        for name in all_names:
            in_degree.setdefault(name, 0)
            graph.setdefault(name, [])

        for name, info in self._discovered.items():
            deps = info["config"].get("dependencies", [])
            for dep in deps:
                if dep in all_names:
                    graph.setdefault(dep, []).append(name)
                    in_degree[name] = in_degree.get(name, 0) + 1

        # 위상 정렬 (Kahn's algorithm)
        queue = [n for n in all_names if in_degree.get(n, 0) == 0]
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in graph.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 순환 의존성에 속한 플러그인은 마지막에 추가 (에러 처리)
        remaining = [n for n in all_names if n not in result]
        for name in remaining:
            logger.warning(f"순환 의존성 감지: {name}")
            self._errors[name] = "순환 의존성"
        result.extend(remaining)

        return result
