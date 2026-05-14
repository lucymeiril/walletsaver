"""Lightweight async circuit breaker for external service calls.

States:
  CLOSED  — requests flow normally
  OPEN    — requests fast-fail with CircuitOpenError
  HALF_OPEN — one probe request allowed; success closes, failure re-opens
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

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
