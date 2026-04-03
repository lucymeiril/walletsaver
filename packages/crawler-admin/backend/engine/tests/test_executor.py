"""
StrategyExecutor 테스트 (TDD).

다중 전략 cascade, 실패 시 다음 전략 전환, 이벤트 발행, 진단 연동을 검증한다.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.events import EventBus, CRAWL_STARTED, CRAWL_COMPLETED, CRAWL_FAILED, STRATEGY_SWITCHED, STRATEGY_FAILED
from core.models import (
    CrawlRequest, CrawlResult, CrawlStatus,
    StrategyFailure, ErrorType, Event,
)
from core.exceptions import CrawlError, AllStrategiesFailedError

from engine.executor import StrategyExecutor


# --- Fixture ---

class FakeStrategy:
    """테스트용 가짜 전략."""

    def __init__(self, name: str, difficulty: int, should_fail: bool = False, error_type: ErrorType = ErrorType.UNKNOWN):
        self._name = name
        self._difficulty = difficulty
        self._should_fail = should_fail
        self._error_type = error_type
        self._cleaned_up = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def difficulty(self) -> int:
        return self._difficulty

    async def fetch(self, url: str, **options) -> str:
        if self._should_fail:
            raise CrawlError(f"{self._name} failed", error_type=self._error_type, strategy_name=self._name)
        return f"<html>data from {self._name}</html>"

    async def cleanup(self) -> None:
        self._cleaned_up = True


@pytest.fixture
def event_bus():
    bus = EventBus()
    yield bus
    bus.clear()


@pytest.fixture
def success_strategy():
    return FakeStrategy("requests", difficulty=1)


@pytest.fixture
def fail_then_success():
    """첫 번째 실패, 두 번째 성공하는 전략 리스트."""
    return [
        FakeStrategy("requests", 1, should_fail=True, error_type=ErrorType.HTTP_ERROR),
        FakeStrategy("selenium", 3, should_fail=False),
    ]


@pytest.fixture
def all_fail():
    """모두 실패하는 전략 리스트."""
    return [
        FakeStrategy("requests", 1, should_fail=True, error_type=ErrorType.HTTP_ERROR),
        FakeStrategy("cloudscraper", 2, should_fail=True, error_type=ErrorType.JS_CHALLENGE),
        FakeStrategy("selenium", 3, should_fail=True, error_type=ErrorType.CAPTCHA_DETECTED),
    ]


# --- 테스트 ---

class TestStrategyExecutor:

    @pytest.mark.asyncio
    async def test_execute_first_strategy_success(self, event_bus, success_strategy):
        """첫 번째 전략이 성공하면 바로 결과를 반환한다."""
        executor = StrategyExecutor(
            strategies=[success_strategy],
            event_bus=event_bus,
        )
        result = await executor.execute("https://example.com")

        assert result.status == CrawlStatus.SUCCESS
        assert result.strategy_used == "requests"
        assert result.raw_data is not None
        assert "data from requests" in result.raw_data

    @pytest.mark.asyncio
    async def test_cascade_to_next_strategy(self, event_bus, fail_then_success):
        """첫 전략 실패 시 다음 전략으로 cascade한다."""
        executor = StrategyExecutor(
            strategies=fail_then_success,
            event_bus=event_bus,
        )
        result = await executor.execute("https://example.com")

        assert result.status == CrawlStatus.SUCCESS
        assert result.strategy_used == "selenium"
        assert len(result.errors) == 1  # 실패한 전략 1개 기록
        assert result.errors[0].strategy_name == "requests"

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self, event_bus, all_fail):
        """모든 전략이 실패하면 FAILED 결과를 반환한다."""
        executor = StrategyExecutor(
            strategies=all_fail,
            event_bus=event_bus,
        )
        result = await executor.execute("https://example.com")

        assert result.status == CrawlStatus.FAILED
        assert len(result.errors) == 3
        assert result.strategy_used is None

    @pytest.mark.asyncio
    async def test_strategies_sorted_by_difficulty(self, event_bus):
        """전략은 difficulty 낮은 순으로 시도된다."""
        order = []

        class TrackingStrategy(FakeStrategy):
            async def fetch(self, url: str, **options) -> str:
                order.append(self.name)
                raise CrawlError("fail", strategy_name=self.name)

        strategies = [
            TrackingStrategy("playwright", 5, should_fail=True),
            TrackingStrategy("requests", 1, should_fail=True),
            TrackingStrategy("selenium", 3, should_fail=True),
        ]

        executor = StrategyExecutor(strategies=strategies, event_bus=event_bus)
        await executor.execute("https://example.com")

        assert order == ["requests", "selenium", "playwright"]

    @pytest.mark.asyncio
    async def test_force_strategy(self, event_bus):
        """force_strategy 옵션으로 특정 전략만 사용한다."""
        strategies = [
            FakeStrategy("requests", 1, should_fail=True),
            FakeStrategy("selenium", 3, should_fail=False),
        ]
        executor = StrategyExecutor(strategies=strategies, event_bus=event_bus)

        result = await executor.execute(
            "https://example.com",
            force_strategy="selenium",
        )

        assert result.status == CrawlStatus.SUCCESS
        assert result.strategy_used == "selenium"

    @pytest.mark.asyncio
    async def test_force_strategy_not_found(self, event_bus, success_strategy):
        """존재하지 않는 전략을 강제하면 FAILED."""
        executor = StrategyExecutor(
            strategies=[success_strategy],
            event_bus=event_bus,
        )
        result = await executor.execute(
            "https://example.com",
            force_strategy="nonexistent",
        )

        assert result.status == CrawlStatus.FAILED

    @pytest.mark.asyncio
    async def test_duration_recorded(self, event_bus, success_strategy):
        """실행 시간이 기록된다."""
        executor = StrategyExecutor(
            strategies=[success_strategy],
            event_bus=event_bus,
        )
        result = await executor.execute("https://example.com")

        assert result.duration_seconds >= 0
        assert result.started_at is not None
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_cleanup_called(self, event_bus):
        """실행 후 전략의 cleanup이 호출된다."""
        strategy = FakeStrategy("requests", 1)
        executor = StrategyExecutor(strategies=[strategy], event_bus=event_bus)

        await executor.execute("https://example.com")
        assert strategy._cleaned_up is True

    @pytest.mark.asyncio
    async def test_cleanup_called_on_failure(self, event_bus, all_fail):
        """실패해도 cleanup이 호출된다."""
        executor = StrategyExecutor(strategies=all_fail, event_bus=event_bus)
        await executor.execute("https://example.com")

        for s in all_fail:
            assert s._cleaned_up is True


class TestStrategyExecutorEvents:
    """StrategyExecutor 이벤트 발행 테스트."""

    @pytest.mark.asyncio
    async def test_crawl_started_event(self, event_bus, success_strategy):
        """크롤링 시작 시 CRAWL_STARTED 이벤트 발행."""
        events = []
        event_bus.subscribe(CRAWL_STARTED, lambda e: events.append(e) or asyncio.sleep(0))

        import asyncio

        async def capture(e):
            events.append(e)

        event_bus.subscribe(CRAWL_STARTED, capture)
        executor = StrategyExecutor(strategies=[success_strategy], event_bus=event_bus)
        await executor.execute("https://example.com")

        started = [e for e in events if e.event_type == CRAWL_STARTED]
        assert len(started) >= 1

    @pytest.mark.asyncio
    async def test_crawl_completed_event(self, event_bus, success_strategy):
        """성공 시 CRAWL_COMPLETED 이벤트 발행."""
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe(CRAWL_COMPLETED, capture)
        executor = StrategyExecutor(strategies=[success_strategy], event_bus=event_bus)
        await executor.execute("https://example.com")

        assert len(events) == 1
        assert events[0].data.get("status") == CrawlStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_crawl_failed_event(self, event_bus, all_fail):
        """전체 실패 시 CRAWL_FAILED 이벤트 발행."""
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe(CRAWL_FAILED, capture)
        executor = StrategyExecutor(strategies=all_fail, event_bus=event_bus)
        await executor.execute("https://example.com")

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_strategy_switched_event(self, event_bus, fail_then_success):
        """전략 전환 시 STRATEGY_SWITCHED 이벤트 발행."""
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe(STRATEGY_SWITCHED, capture)
        executor = StrategyExecutor(strategies=fail_then_success, event_bus=event_bus)
        await executor.execute("https://example.com")

        assert len(events) == 1
        assert events[0].data.get("from_strategy") == "requests"
        assert events[0].data.get("to_strategy") == "selenium"
