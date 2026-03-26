"""
모듈 간 결합을 끊는 비동기 이벤트 버스.

왜 존재하는가:
    크롤링 엔진이 "완료됐다"고 저장소·대시보드·스케줄러에 직접 알리면 순환 의존이 생긴다.
    이벤트 버스를 두면 발행자(엔진)와 구독자(저장소, 진단, 스케줄러)가 서로의 존재를 몰라도 되고,
    새 구독자를 추가할 때 발행자 코드를 건드릴 필요가 없다.
어디서 쓰이는가:
    container.py에서 단일 인스턴스 생성 → executor·storage·scheduler에 주입.
    executor가 CRAWL_STARTED/COMPLETED/FAILED 발행, storage가 DATA_SAVED 발행,
    diagnostics가 DIAGNOSIS_GENERATED 구독 등.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

from core.models import Event

logger = logging.getLogger(__name__)

# 이벤트 타입 상수
# 발행처 → 구독처 형태로 정리
CRAWL_STARTED = "crawl.started"           # executor → 대시보드 (실시간 상태 표시)
CRAWL_COMPLETED = "crawl.completed"       # executor → storage (데이터 저장), scheduler (다음 작업)
CRAWL_FAILED = "crawl.failed"             # executor → diagnostics (자동 진단 시작)
CRAWL_PROGRESS = "crawl.progress"         # executor → 대시보드 (진행률 업데이트)
STRATEGY_SWITCHED = "strategy.switched"   # executor → 대시보드 (cascade 진행 표시)
STRATEGY_FAILED = "strategy.failed"       # executor → diagnostics (전략별 실패 수집)
DATA_SAVED = "data.saved"                 # storage → 대시보드 (저장 완료 알림)
JOB_SCHEDULED = "job.scheduled"           # scheduler → 대시보드 (예약 작업 등록)
JOB_REMOVED = "job.removed"              # scheduler → 대시보드 (예약 작업 삭제)
DIAGNOSIS_GENERATED = "diagnosis.generated"  # diagnostics → 대시보드·알림 (진단 리포트 생성)

# Handler 타입
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    비동기 pub/sub 이벤트 버스 — 프로젝트의 중추 신경계.

    왜 이 구조인가:
        핸들러 예외가 다른 핸들러에 전파되지 않도록 _safe_call로 격리한다.
        asyncio.gather로 병렬 발행하여 핸들러가 많아져도 지연이 누적되지 않는다.
    어디서 쓰이나:
        container.py에서 단일 인스턴스 생성 → 각 모듈에 주입.
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
        """핸들러 하나가 터져도 나머지 핸들러·발행자에 영향을 주지 않도록 격리."""
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
