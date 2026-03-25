"""
core.events.EventBus 테스트 (TDD).

이벤트 발행/구독, 에러 격리, 글로벌 핸들러 등을 검증한다.
"""

import pytest
from core.events import EventBus, CRAWL_STARTED, CRAWL_COMPLETED, CRAWL_FAILED
from core.models import Event


class TestEventBus:
    """EventBus 단위 테스트."""

    # --- 구독 & 발행 ---

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, event_bus: EventBus):
        """구독한 핸들러가 이벤트를 수신한다."""
        received = []

        async def handler(event: Event):
            received.append(event)

        event_bus.subscribe(CRAWL_COMPLETED, handler)
        event = Event(event_type=CRAWL_COMPLETED, data={"items": 5})
        await event_bus.publish(event)

        assert len(received) == 1
        assert received[0].event_type == CRAWL_COMPLETED
        assert received[0].data["items"] == 5

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, event_bus: EventBus):
        """같은 이벤트에 여러 핸들러가 모두 호출된다."""
        call_count = {"a": 0, "b": 0}

        async def handler_a(event: Event):
            call_count["a"] += 1

        async def handler_b(event: Event):
            call_count["b"] += 1

        event_bus.subscribe(CRAWL_STARTED, handler_a)
        event_bus.subscribe(CRAWL_STARTED, handler_b)
        await event_bus.publish(Event(event_type=CRAWL_STARTED))

        assert call_count["a"] == 1
        assert call_count["b"] == 1

    @pytest.mark.asyncio
    async def test_no_cross_event_delivery(self, event_bus: EventBus):
        """다른 타입의 이벤트는 수신하지 않는다."""
        received = []

        async def handler(event: Event):
            received.append(event)

        event_bus.subscribe(CRAWL_COMPLETED, handler)
        await event_bus.publish(Event(event_type=CRAWL_FAILED))

        assert len(received) == 0

    # --- 글로벌 핸들러 ---

    @pytest.mark.asyncio
    async def test_global_subscriber(self, event_bus: EventBus):
        """글로벌 핸들러는 모든 이벤트를 수신한다."""
        received = []

        async def global_handler(event: Event):
            received.append(event.event_type)

        event_bus.subscribe_all(global_handler)
        await event_bus.publish(Event(event_type=CRAWL_STARTED))
        await event_bus.publish(Event(event_type=CRAWL_COMPLETED))
        await event_bus.publish(Event(event_type=CRAWL_FAILED))

        assert len(received) == 3
        assert CRAWL_STARTED in received
        assert CRAWL_COMPLETED in received
        assert CRAWL_FAILED in received

    # --- 에러 격리 ---

    @pytest.mark.asyncio
    async def test_handler_error_does_not_propagate(self, event_bus: EventBus):
        """핸들러에서 예외가 발생해도 다른 핸들러에 영향 없다."""
        results = []

        async def bad_handler(event: Event):
            raise RuntimeError("핸들러 오류!")

        async def good_handler(event: Event):
            results.append("ok")

        event_bus.subscribe(CRAWL_COMPLETED, bad_handler)
        event_bus.subscribe(CRAWL_COMPLETED, good_handler)

        # 예외가 전파되지 않아야 한다
        await event_bus.publish(Event(event_type=CRAWL_COMPLETED))
        assert results == ["ok"]

    # --- 구독 해제 ---

    @pytest.mark.asyncio
    async def test_unsubscribe(self, event_bus: EventBus):
        """구독을 해제하면 더 이상 이벤트를 수신하지 않는다."""
        received = []

        async def handler(event: Event):
            received.append(event)

        event_bus.subscribe(CRAWL_COMPLETED, handler)
        event_bus.unsubscribe(CRAWL_COMPLETED, handler)
        await event_bus.publish(Event(event_type=CRAWL_COMPLETED))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_clear(self, event_bus: EventBus):
        """clear()하면 모든 구독이 해제된다."""
        received = []

        async def handler(event: Event):
            received.append(event)

        event_bus.subscribe(CRAWL_COMPLETED, handler)
        event_bus.subscribe_all(handler)
        event_bus.clear()

        await event_bus.publish(Event(event_type=CRAWL_COMPLETED))
        assert len(received) == 0

    # --- 수신자 없는 이벤트 ---

    @pytest.mark.asyncio
    async def test_publish_with_no_subscribers(self, event_bus: EventBus):
        """구독자 없이 발행해도 에러 없이 무시된다."""
        # 예외 없이 정상 종료되어야 함
        await event_bus.publish(Event(event_type="nonexistent.event"))
