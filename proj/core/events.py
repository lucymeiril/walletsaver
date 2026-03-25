"""
이벤트 버스.

모듈 간 느슨한 결합을 위한 pub/sub 이벤트 시스템.
발행자와 구독자는 서로의 존재를 모른다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

from core.models import Event

logger = logging.getLogger(__name__)

# 이벤트 타입 상수
CRAWL_STARTED = "crawl.started"
CRAWL_COMPLETED = "crawl.completed"
CRAWL_FAILED = "crawl.failed"
CRAWL_PROGRESS = "crawl.progress"
STRATEGY_SWITCHED = "strategy.switched"
STRATEGY_FAILED = "strategy.failed"
DATA_SAVED = "data.saved"
JOB_SCHEDULED = "job.scheduled"
JOB_REMOVED = "job.removed"
DIAGNOSIS_GENERATED = "diagnosis.generated"

# Handler 타입
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    비동기 이벤트 버스.

    사용법:
        bus = EventBus()
        bus.subscribe("crawl.completed", my_handler)
        await bus.publish(Event(event_type="crawl.completed", data={...}))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """특정 이벤트 타입을 구독한다."""
        self._handlers[event_type].append(handler)
        logger.debug(f"구독 등록: {event_type} -> {handler.__name__}")

    def subscribe_all(self, handler: EventHandler) -> None:
        """모든 이벤트를 구독한다 (로깅, 디버깅 용)."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """구독 해제."""
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def publish(self, event: Event) -> None:
        """이벤트를 발행한다. 등록된 모든 핸들러에 비동기로 전달."""
        handlers = self._handlers.get(event.event_type, []) + self._global_handlers

        if not handlers:
            logger.debug(f"이벤트 수신자 없음: {event.event_type}")
            return

        tasks = []
        for handler in handlers:
            tasks.append(self._safe_call(handler, event))

        await asyncio.gather(*tasks)

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """핸들러 호출 시 예외가 전파되지 않도록 보호."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"이벤트 핸들러 오류: {handler.__name__} for {event.event_type}: {e}",
                exc_info=True,
            )

    def clear(self) -> None:
        """모든 구독 해제 (테스트용)."""
        self._handlers.clear()
        self._global_handlers.clear()
