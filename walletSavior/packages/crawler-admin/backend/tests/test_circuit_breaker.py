"""Circuit breaker tests."""

import asyncio
import pytest
from pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_by_default(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        for _ in range(2):
            await cb.on_failure()
        assert cb.state == "open"

    @pytest.mark.asyncio
    async def test_open_circuit_raises(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        await cb.on_failure()
        with pytest.raises(CircuitOpenError):
            await cb.before_request()

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        await cb.on_failure()
        await cb.on_failure()
        await cb.on_success()  # reset
        await cb.on_failure()  # count = 1 again
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        await cb.on_failure()
        assert cb.state == "half_open"  # recovery_timeout=0 → immediate

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0, success_threshold=1)
        await cb.on_failure()
        assert cb.state == "half_open"
        cb._state = cb.HALF_OPEN  # force for test
        await cb.on_success()
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        async with cb:
            pass  # no exception → on_success
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_context_manager_failure(self):
        cb = CircuitBreaker(failure_threshold=3)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("test")
        assert cb._failure_count == 1
