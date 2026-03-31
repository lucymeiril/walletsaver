"""
플러그인 인터페이스 — CrawlerContract를 확장하여 라이프사이클·상태·메트릭을 추가한다.

왜 존재하는가:
    CrawlerContract는 크롤링 로직만 정의한다.
    플러그인으로서 동작하려면 로드/언로드 훅, 상태 보고, 성능 메트릭,
    버전 관리, 의존성 선언 등 운영에 필요한 계약이 추가로 필요하다.
어디서 쓰이나:
    모든 크롤러 플러그인이 이 인터페이스를 구현한다.
    PluginLoader가 로드 시 on_load() 호출, PluginManager가 상태·메트릭 조회.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from core.contracts.crawler import CrawlerContract


class PluginStatus(str, Enum):
    """플러그인의 현재 상태."""
    DISCOVERED = "discovered"   # plugin.yaml 발견됨
    LOADED = "loaded"           # 모듈 로드 완료
    ACTIVE = "active"           # 크롤링 가능 상태
    ERROR = "error"             # 로드/실행 중 에러 발생
    DISABLED = "disabled"       # 관리자에 의해 비활성화
    UNLOADED = "unloaded"       # 언로드됨


@dataclass
class PluginHealth:
    """플러그인 건강 상태 정보."""
    status: PluginStatus
    is_healthy: bool = True
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    uptime_seconds: float = 0.0
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "is_healthy": self.is_healthy,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "error_message": self.error_message,
            "uptime_seconds": self.uptime_seconds,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class PluginMetrics:
    """플러그인 성능 메트릭."""
    total_runs: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_items_collected: int = 0
    avg_duration_seconds: float = 0.0
    last_run: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    _durations: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """성공률 (0.0 ~ 1.0)."""
        if self.total_runs == 0:
            return 0.0
        return self.success_count / self.total_runs

    def record_run(self, success: bool, duration: float, items_count: int = 0) -> None:
        """실행 결과를 기록한다."""
        self.total_runs += 1
        self.last_run = datetime.now()
        self._durations.append(duration)
        self.avg_duration_seconds = sum(self._durations) / len(self._durations)

        if success:
            self.success_count += 1
            self.last_success = datetime.now()
            self.total_items_collected += items_count
        else:
            self.failure_count += 1
            self.last_failure = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "total_items_collected": self.total_items_collected,
            "avg_duration_seconds": round(self.avg_duration_seconds, 3),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
        }


class PluginInterface(CrawlerContract):
    """
    크롤러 플러그인 인터페이스 — CrawlerContract + 라이프사이클 + 메트릭.

    모든 크롤러 플러그인은 이 인터페이스를 구현해야 한다.
    CrawlerContract의 crawl/parse/validate에 더해
    로드/언로드 훅, 설정·상태·메트릭 조회 기능을 제공한다.
    """

    def __init__(self) -> None:
        self._status: PluginStatus = PluginStatus.DISCOVERED
        self._config: dict[str, Any] = {}
        self._metrics: PluginMetrics = PluginMetrics()
        self._loaded_at: Optional[float] = None
        self._error_message: Optional[str] = None
        self._consecutive_failures: int = 0

    # --- 라이프사이클 훅 ---

    async def on_load(self) -> None:
        """
        플러그인이 로드될 때 호출된다.
        리소스 초기화, DB 연결 등을 수행한다.
        """
        self._loaded_at = time.time()
        self._status = PluginStatus.LOADED

    async def on_unload(self) -> None:
        """
        플러그인이 언로드될 때 호출된다.
        리소스 해제, 연결 종료 등을 수행한다.
        """
        self._status = PluginStatus.UNLOADED
        self._loaded_at = None

    async def on_error(self, error: Exception) -> None:
        """
        크롤링 실행 중 에러 발생 시 호출된다.
        에러 로깅, 알림 전송 등을 수행한다.
        """
        self._consecutive_failures += 1
        self._error_message = str(error)

    def on_success(self) -> None:
        """크롤링 성공 시 연속 실패 카운터를 초기화한다."""
        self._consecutive_failures = 0
        self._error_message = None

    # --- 설정/상태/메트릭 ---

    def get_config(self) -> dict[str, Any]:
        """plugin.yaml의 내용을 반환한다."""
        return dict(self._config)

    def set_config(self, config: dict[str, Any]) -> None:
        """plugin.yaml 내용을 설정한다 (PluginLoader가 호출)."""
        self._config = config

    def get_health(self) -> PluginHealth:
        """플러그인 건강 상태를 반환한다."""
        uptime = 0.0
        if self._loaded_at is not None:
            uptime = time.time() - self._loaded_at

        is_healthy = (
            self._status in (PluginStatus.LOADED, PluginStatus.ACTIVE)
            and self._consecutive_failures < 5
        )

        return PluginHealth(
            status=self._status,
            is_healthy=is_healthy,
            last_check=datetime.now(),
            error_message=self._error_message,
            uptime_seconds=uptime,
            consecutive_failures=self._consecutive_failures,
        )

    def get_metrics(self) -> PluginMetrics:
        """크롤링 성능 메트릭을 반환한다."""
        return self._metrics

    def get_status(self) -> PluginStatus:
        """현재 플러그인 상태를 반환한다."""
        return self._status

    def set_status(self, status: PluginStatus) -> None:
        """상태를 변경한다."""
        self._status = status

    # --- 버전/의존성 ---

    def get_version(self) -> str:
        """플러그인 버전을 반환한다."""
        return self._config.get("version", "0.0.0")

    def get_dependencies(self) -> list[str]:
        """의존하는 다른 플러그인 이름 목록을 반환한다."""
        return self._config.get("dependencies", [])
