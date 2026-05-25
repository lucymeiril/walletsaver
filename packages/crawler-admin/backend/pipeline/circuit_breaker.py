"""Lightweight async circuit breaker for external service calls.

States:
  CLOSED  — requests flow normally
  OPEN    — requests fast-fail with CircuitOpenError
  HALF_OPEN — one probe request allowed; success closes, failure re-opens

crawler-FINAL §4-A 확장:
- 4-튜플 키 (source_id, domain, egress_ip, blocker_signature) 별 인스턴스 관리
- yaml waf_strategy.escalation 깊이 (depth, 상한) 와 런타임 attempt_cost (가변 게이트) 분리
- attempt_cost = domain_pressure + worker_pressure + profile_age + blocker_severity + shard_scope
  cost > source_max_cost 이면 같은 cycle 내 다음 단계 진입 보류 (다음 cron 으로 이월)
- 무한 핑퐁 차단: 한 방향만 (escalation 은 always-forward)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open (service assumed down)."""

    def __init__(self, service: str, retry_after: float):
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"circuit open for {service}, retry after {retry_after:.0f}s")


class CircuitBreaker:
    """Async-safe circuit breaker.

    Args:
        service_name: Human-readable service name for logging.
        failure_threshold: Consecutive failures before opening.
        recovery_timeout: Seconds to wait before entering half-open state.
        success_threshold: Consecutive successes in half-open to close.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        service_name: str = "external",
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                return self.HALF_OPEN
        return self._state

    async def __aenter__(self):
        await self.before_request()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self.on_success()
        elif exc_type is not CircuitOpenError:
            await self.on_failure()
        return False  # don't suppress

    async def before_request(self) -> None:
        """Call before making a request. Raises CircuitOpenError if open."""
        current = self.state
        if current == self.OPEN:
            remaining = self.recovery_timeout - (time.monotonic() - self._opened_at)
            raise CircuitOpenError(self.service_name, max(remaining, 0))
        # HALF_OPEN and CLOSED: allow the request

    async def on_success(self) -> None:
        async with self._lock:
            if self._state == self.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = self.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("[CircuitBreaker] %s: CLOSED (recovered)", self.service_name)
            else:
                self._failure_count = 0

    async def on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[CircuitBreaker] %s: OPEN after %d failures (cooldown %.0fs)",
                    self.service_name, self._failure_count, self.recovery_timeout,
                )
            elif self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[CircuitBreaker] %s: re-OPENED from half-open",
                    self.service_name,
                )


# ── crawler-FINAL §4-A 확장 — 4-튜플 키 / attempt_cost 게이트 ──────────────

@dataclass(frozen=True)
class BreakerKey:
    """circuit breaker 4-튜플 식별 키. blocker_signature 가 비면 generic 으로 표시."""
    source_id: str
    domain: str
    egress_ip: str = "default"
    blocker_signature: str = "none"

    def as_label(self) -> str:
        return f"{self.source_id}|{self.domain}|{self.egress_ip}|{self.blocker_signature}"


@dataclass
class AttemptCostInputs:
    """런타임 attempt_cost 입력 — 5개 신호 합 (FINAL §4-A 공식)."""
    domain_pressure: float = 0.0   # 0.0~1.0 도메인 토큰버킷 압박도
    worker_pressure: float = 0.0   # 0.0~1.0 worker pool 사용률
    profile_age: float = 0.0       # 0.0~1.0 (만료 임박 = 1.0)
    blocker_severity: float = 0.0  # 0.0~1.0 (WAF 202 = 0.6, Akamai 403 = 0.8, ...)
    shard_scope: float = 0.0       # 0.0~1.0 (전체 사이트 진입 = 1.0)

    def total(self) -> float:
        return (
            self.domain_pressure
            + self.worker_pressure
            + self.profile_age
            + self.blocker_severity
            + self.shard_scope
        )


def attempt_cost_allows(inputs: AttemptCostInputs, source_max_cost: float = 2.5) -> bool:
    """cost <= source_max_cost 이면 진행, 아니면 cycle 이월.

    기본 상한 2.5 — 5개 신호의 평균이 0.5 이하 (FINAL §4-A 의도: 압박/세션/blocker 가
    모두 절반 이하일 때만 다음 단계로 진입).
    """
    return inputs.total() <= source_max_cost


class CircuitBreakerRegistry:
    """4-튜플 키 별 CircuitBreaker 풀.

    crawler-FINAL §4-A — pipeline/circuit_breaker.py 가 *strategy loop 에 연결 안 됨* 이슈를
    풀기 위한 진입점. crawler 가 BreakerKey 와 함께 acquire() 호출하면 인스턴스 보장.
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        key: BreakerKey,
        *,
        failure_threshold: int = 2,   # FINAL §4-A: 같은 blocker 연속 2회
        recovery_timeout: float = 1800.0,  # WAF/Akamai 기본 30분
    ) -> CircuitBreaker:
        label = key.as_label()
        async with self._lock:
            br = self._breakers.get(label)
            if br is None:
                br = CircuitBreaker(
                    service_name=label,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
                self._breakers[label] = br
            return br

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """모니터 / 진단용 — 현재 모든 breaker 의 상태."""
        return {
            label: {
                "state": br.state,
                "failure_count": br._failure_count,
            }
            for label, br in self._breakers.items()
        }


_global_registry: Optional[CircuitBreakerRegistry] = None


def get_global_registry() -> CircuitBreakerRegistry:
    """프로세스 단일 registry. crawler / orchestrator 가 동일 인스턴스 공유."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CircuitBreakerRegistry()
    return _global_registry
