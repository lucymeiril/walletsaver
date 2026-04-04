"""Thread-safe TTL cache and request deduplication utilities."""

import asyncio
import time
import threading
from typing import Any, Optional


class TTLCache:
    """In-memory cache with per-key TTL expiration. Thread-safe."""

    def __init__(self, ttl_seconds: int = 60, max_size: int = 256):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl_seconds
        self._max_size = max_size

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            val, ts = entry
            if time.time() - ts < self.ttl:
                return val
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._cache) >= self._max_size:
                self._evict_expired()
            self._cache[key] = (value, time.time())

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
        for k in expired:
            del self._cache[k]
        # If still over limit, remove oldest entries
        if len(self._cache) >= self._max_size:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][1])
            for k in sorted_keys[: len(self._cache) - self._max_size + 1]:
                del self._cache[k]


class RequestDeduplicator:
    """Deduplicates concurrent identical async requests.

    If the same key is already being processed, subsequent callers wait for
    the first result instead of spawning a duplicate operation.
    """

    def __init__(self):
        self._in_flight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def deduplicate(self, key: str, coro_factory):
        """Run coro_factory() or wait for an in-flight result with the same key.

        Args:
            key: Unique identifier for this request.
            coro_factory: A zero-arg callable that returns a coroutine.
        """
        async with self._lock:
            if key in self._in_flight:
                future = self._in_flight[key]
            else:
                future = asyncio.get_event_loop().create_future()
                self._in_flight[key] = future
                # We are the first caller — schedule execution
                asyncio.ensure_future(self._execute(key, coro_factory, future))

        return await asyncio.shield(future)

    async def _execute(self, key: str, coro_factory, future: asyncio.Future):
        try:
            result = await coro_factory()
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)


class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    States: CLOSED (normal), OPEN (failing, reject fast), HALF_OPEN (probe).
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self._state = self.CLOSED
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time >= self._recovery_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def allow_request(self) -> bool:
        s = self.state
        return s in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = self.OPEN
