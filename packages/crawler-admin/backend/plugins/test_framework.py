"""
플러그인 테스트 프레임워크 — 크롤러 플러그인 개발자용 테스트 유틸리티.

왜 존재하는가:
    모든 플러그인이 동일한 계약을 준수하는지 자동으로 검증하고,
    오프라인 환경에서도 크롤러를 테스트할 수 있어야 한다.
어디서 쓰이나:
    플러그인 개발자가 자신의 크롤러 테스트에 사용한다.
    CI/CD에서 플러그인 품질 게이트로도 사용할 수 있다.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock

from core.contracts.crawler import CrawlerContract
from core.models import CrawlResult, CrawlStatus

from .plugin_interface import PluginInterface, PluginStatus


# --- Mock 크롤 타겟 ---

MOCK_HTML_SIMPLE = """
<html>
<body>
  <div class="deal-list">
    <div class="deal-item">
      <a href="/deal/1" class="title">테스트 상품 1</a>
      <span class="price">10,000원</span>
      <span class="original-price">15,000원</span>
    </div>
    <div class="deal-item">
      <a href="/deal/2" class="title">테스트 상품 2</a>
      <span class="price">25,000원</span>
      <span class="original-price">30,000원</span>
    </div>
    <div class="deal-item">
      <a href="/deal/3" class="title">테스트 상품 3</a>
      <span class="price">5,000원</span>
    </div>
  </div>
</body>
</html>
"""

MOCK_HTML_EMPTY = """
<html><body><div class="deal-list"></div></body></html>
"""

MOCK_HTML_MALFORMED = """
<html><body><div class="deal-list">
  <div class="deal-item"><span>잘못된 구조
</html>
"""

MOCK_JSON_RESPONSE = {
    "status": "success",
    "data": [
        {"name": "테스트 상품 A", "price": 12000, "original_price": 18000},
        {"name": "테스트 상품 B", "price": 8000, "original_price": 10000},
    ],
}


@dataclass
class BenchmarkResult:
    """성능 벤치마크 결과."""
    operation: str
    iterations: int
    total_seconds: float
    avg_seconds: float
    min_seconds: float
    max_seconds: float
    items_per_second: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "iterations": self.iterations,
            "total_seconds": round(self.total_seconds, 4),
            "avg_seconds": round(self.avg_seconds, 4),
            "min_seconds": round(self.min_seconds, 4),
            "max_seconds": round(self.max_seconds, 4),
            "items_per_second": round(self.items_per_second, 2),
        }


@dataclass
class ComplianceResult:
    """인터페이스 준수 검사 결과."""
    plugin_name: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return len(self.failed) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "is_compliant": self.is_compliant,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "total_checks": len(self.passed) + len(self.failed),
        }


class PluginTestFramework:
    """
    플러그인 테스트 프레임워크.

    기능:
        1) 인터페이스 준수 검사 (CrawlerContract/PluginInterface 메서드 존재 확인)
        2) CrawlResult 스키마 검증
        3) 오프라인 테스트용 Mock HTML/JSON 제공
        4) 성능 벤치마킹
        5) 건강 상태 검사
    """

    def __init__(self, plugin: Optional[CrawlerContract] = None):
        self._plugin = plugin

    def set_plugin(self, plugin: CrawlerContract) -> None:
        """테스트 대상 플러그인을 설정한다."""
        self._plugin = plugin

    # --- 인터페이스 준수 검사 ---

    def check_compliance(self, plugin: Optional[CrawlerContract] = None) -> ComplianceResult:
        """CrawlerContract/PluginInterface 인터페이스 준수 여부를 검사한다."""
        target = plugin or self._plugin
        if target is None:
            raise ValueError("테스트 대상 플러그인이 설정되지 않음")

        name = getattr(target, "info", None)
        plugin_name = name.name if name else type(target).__name__

        result = ComplianceResult(plugin_name=plugin_name)

        # CrawlerContract 필수 메서드 검사
        self._check_method(target, "crawl", result, is_async=True)
        self._check_method(target, "parse", result, is_async=True)
        self._check_method(target, "validate", result, is_async=True)
        self._check_property(target, "info", result)

        # PluginInterface 추가 검사
        if isinstance(target, PluginInterface):
            self._check_method(target, "on_load", result, is_async=True)
            self._check_method(target, "on_unload", result, is_async=True)
            self._check_method(target, "on_error", result, is_async=True)
            self._check_method(target, "get_config", result)
            self._check_method(target, "get_health", result)
            self._check_method(target, "get_metrics", result)
            self._check_method(target, "get_version", result)
            self._check_method(target, "get_dependencies", result)
        else:
            result.warnings.append("PluginInterface를 구현하지 않음 (CrawlerContract만 구현)")

        return result

    def _check_method(
        self,
        target: Any,
        method_name: str,
        result: ComplianceResult,
        is_async: bool = False,
    ) -> None:
        """메서드 존재 및 타입을 검사한다."""
        method = getattr(target, method_name, None)
        if method is None:
            result.failed.append(f"메서드 누락: {method_name}")
            return

        if not callable(method):
            result.failed.append(f"호출 불가: {method_name}")
            return

        if is_async and not asyncio.iscoroutinefunction(method):
            result.warnings.append(f"비동기가 아님: {method_name} (async 권장)")

        result.passed.append(f"메서드 확인: {method_name}")

    def _check_property(self, target: Any, prop_name: str, result: ComplianceResult) -> None:
        """프로퍼티 존재를 검사한다."""
        try:
            value = getattr(target, prop_name, None)
            if value is None:
                result.failed.append(f"프로퍼티 누락: {prop_name}")
            else:
                result.passed.append(f"프로퍼티 확인: {prop_name}")
        except Exception as e:
            result.failed.append(f"프로퍼티 접근 오류: {prop_name}: {e}")

    # --- CrawlResult 스키마 검증 ---

    @staticmethod
    def validate_crawl_result(result: CrawlResult) -> list[str]:
        """CrawlResult가 스키마를 준수하는지 검증한다."""
        errors: list[str] = []

        if not isinstance(result.status, CrawlStatus):
            errors.append(f"status가 CrawlStatus가 아님: {type(result.status)}")

        if not result.crawler_name:
            errors.append("crawler_name이 비어있음")

        if result.status == CrawlStatus.SUCCESS:
            if result.items_count < 0:
                errors.append(f"items_count가 음수: {result.items_count}")

            if result.items_count != len(result.items):
                errors.append(
                    f"items_count({result.items_count})와 "
                    f"items 길이({len(result.items)})가 불일치"
                )

            if result.strategy_used is None:
                errors.append("성공했지만 strategy_used가 없음")

        if result.status == CrawlStatus.FAILED:
            if not result.error_msg and not result.errors:
                errors.append("실패했지만 에러 정보가 없음")

        if result.duration_seconds < 0:
            errors.append(f"duration_seconds가 음수: {result.duration_seconds}")

        return errors

    # --- Mock 데이터 ---

    @staticmethod
    def get_mock_html(variant: str = "simple") -> str:
        """테스트용 Mock HTML을 반환한다."""
        variants = {
            "simple": MOCK_HTML_SIMPLE,
            "empty": MOCK_HTML_EMPTY,
            "malformed": MOCK_HTML_MALFORMED,
        }
        return variants.get(variant, MOCK_HTML_SIMPLE)

    @staticmethod
    def get_mock_json() -> dict[str, Any]:
        """테스트용 Mock JSON을 반환한다."""
        return dict(MOCK_JSON_RESPONSE)

    @staticmethod
    def create_mock_crawl_result(
        crawler_name: str = "test_crawler",
        status: CrawlStatus = CrawlStatus.SUCCESS,
        items_count: int = 3,
        strategy: str = "requests",
    ) -> CrawlResult:
        """테스트용 CrawlResult를 생성한다."""
        items = [
            {"name": f"테스트 상품 {i}", "price": 1000 * (i + 1)}
            for i in range(items_count)
        ]
        now = datetime.now()
        return CrawlResult(
            status=status,
            crawler_name=crawler_name,
            strategy_used=strategy if status == CrawlStatus.SUCCESS else None,
            items_count=items_count,
            items=items,
            started_at=now,
            finished_at=now,
            duration_seconds=1.5,
        )

    # --- 벤치마킹 ---

    async def benchmark_parse(
        self,
        html: str,
        iterations: int = 10,
        plugin: Optional[CrawlerContract] = None,
    ) -> BenchmarkResult:
        """parse() 메서드의 성능을 벤치마킹한다."""
        target = plugin or self._plugin
        if target is None:
            raise ValueError("테스트 대상 플러그인이 설정되지 않음")

        durations: list[float] = []
        total_items = 0

        for _ in range(iterations):
            start = time.perf_counter()
            items = await target.parse(html)
            elapsed = time.perf_counter() - start
            durations.append(elapsed)
            total_items += len(items)

        total = sum(durations)
        avg_items = total_items / iterations if iterations > 0 else 0

        return BenchmarkResult(
            operation="parse",
            iterations=iterations,
            total_seconds=total,
            avg_seconds=total / iterations,
            min_seconds=min(durations),
            max_seconds=max(durations),
            items_per_second=avg_items / (total / iterations) if total > 0 else 0,
        )

    async def benchmark_validate(
        self,
        items: list[dict],
        iterations: int = 10,
        plugin: Optional[CrawlerContract] = None,
    ) -> BenchmarkResult:
        """validate() 메서드의 성능을 벤치마킹한다."""
        target = plugin or self._plugin
        if target is None:
            raise ValueError("테스트 대상 플러그인이 설정되지 않음")

        durations: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()
            await target.validate(items)
            elapsed = time.perf_counter() - start
            durations.append(elapsed)

        total = sum(durations)

        return BenchmarkResult(
            operation="validate",
            iterations=iterations,
            total_seconds=total,
            avg_seconds=total / iterations,
            min_seconds=min(durations),
            max_seconds=max(durations),
        )

    # --- 건강 상태 검사 ---

    def check_health(self, plugin: Optional[PluginInterface] = None) -> dict[str, Any]:
        """플러그인 건강 상태를 종합적으로 검사한다."""
        target = plugin or self._plugin
        if not isinstance(target, PluginInterface):
            return {"error": "PluginInterface를 구현하지 않음"}

        health = target.get_health()
        metrics = target.get_metrics()
        config = target.get_config()

        checks: dict[str, bool] = {
            "has_name": bool(config.get("name")),
            "has_version": bool(config.get("version")),
            "status_ok": health.status in (PluginStatus.LOADED, PluginStatus.ACTIVE),
            "no_consecutive_failures": health.consecutive_failures < 5,
            "success_rate_ok": metrics.success_rate >= 0.5 if metrics.total_runs > 0 else True,
        }

        return {
            "plugin_name": config.get("name", "unknown"),
            "health": health.to_dict(),
            "metrics": metrics.to_dict(),
            "checks": checks,
            "all_passed": all(checks.values()),
        }
