"""
StrategyExecutor — 다중 전략 실행기.

크롤링 전략을 difficulty 순으로 시도하고,
실패 시 다음 전략으로 자동 cascade한다.
모든 전략 실패 시 에러 리포트를 생성한다.

의존: core/ 만 (contracts, events, models, exceptions)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from core.contracts.engine import StrategyContract
from core.events import (
    EventBus,
    CRAWL_STARTED,
    CRAWL_COMPLETED,
    CRAWL_FAILED,
    STRATEGY_SWITCHED,
    STRATEGY_FAILED,
)
from core.models import (
    CrawlResult,
    CrawlStatus,
    StrategyFailure,
    ErrorType,
    Event,
)
from core.exceptions import CrawlError

logger = logging.getLogger(__name__)


class StrategyExecutor:
    """
    다중 전략 실행기.

    전략을 difficulty 순으로 정렬하여 가벼운 것부터 시도한다.
    하나가 성공하면 즉시 반환, 실패하면 다음으로 cascade.
    모든 전략 실패 시 실패 결과를 반환한다.

    Args:
        strategies: 사용할 전략 리스트
        event_bus: 이벤트 발행용 버스
    """

    def __init__(
        self,
        strategies: list,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        # difficulty 순으로 정렬 (낮을수록 먼저)
        self._strategies = sorted(strategies, key=lambda s: s.difficulty)
        self._event_bus = event_bus or EventBus()

    async def execute(
        self,
        url: str,
        force_strategy: Optional[str] = None,
        **options,
    ) -> CrawlResult:
        """
        URL에 대해 전략을 cascade하며 크롤링을 수행한다.

        Args:
            url: 대상 URL
            force_strategy: 특정 전략만 강제 사용 (None이면 전체 cascade)
            **options: 전략별 추가 옵션

        Returns:
            CrawlResult: 성공 또는 실패 결과
        """
        started_at = datetime.now()
        start_time = time.monotonic()

        # 시작 이벤트 발행
        await self._event_bus.publish(Event(
            event_type=CRAWL_STARTED,
            data={"url": url, "force_strategy": force_strategy},
            source="engine.executor",
        ))

        # 강제 전략 지정
        if force_strategy:
            strategies = [s for s in self._strategies if s.name == force_strategy]
            if not strategies:
                return self._build_failed_result(
                    url=url,
                    errors=[StrategyFailure(
                        strategy_name=force_strategy,
                        error_type=ErrorType.UNKNOWN,
                        error_msg=f"전략 '{force_strategy}'을(를) 찾을 수 없습니다.",
                    )],
                    started_at=started_at,
                    start_time=start_time,
                )
        else:
            strategies = self._strategies

        # 전략 cascade 실행
        errors: list[StrategyFailure] = []
        prev_strategy_name: Optional[str] = None

        for strategy in strategies:
            # 전략 전환 이벤트
            if prev_strategy_name is not None:
                await self._event_bus.publish(Event(
                    event_type=STRATEGY_SWITCHED,
                    data={
                        "from_strategy": prev_strategy_name,
                        "to_strategy": strategy.name,
                        "url": url,
                    },
                    source="engine.executor",
                ))

            try:
                raw_data = await strategy.fetch(url, **options)

                # 성공
                result = CrawlResult(
                    status=CrawlStatus.SUCCESS,
                    crawler_name="",
                    strategy_used=strategy.name,
                    raw_data=raw_data,
                    started_at=started_at,
                    finished_at=datetime.now(),
                    duration_seconds=time.monotonic() - start_time,
                    errors=errors,
                )

                await self._event_bus.publish(Event(
                    event_type=CRAWL_COMPLETED,
                    data={
                        "status": CrawlStatus.SUCCESS,
                        "strategy_used": strategy.name,
                        "url": url,
                    },
                    source="engine.executor",
                ))

                return result

            except CrawlError as e:
                failure = StrategyFailure(
                    strategy_name=strategy.name,
                    error_type=e.error_type,
                    error_msg=str(e),
                    status_code=e.status_code,
                )
                errors.append(failure)
                prev_strategy_name = strategy.name

                await self._event_bus.publish(Event(
                    event_type=STRATEGY_FAILED,
                    data={
                        "strategy": strategy.name,
                        "error_type": e.error_type.value,
                        "error_msg": str(e),
                    },
                    source="engine.executor",
                ))

                logger.warning(
                    f"전략 실패: {strategy.name} — {e.error_type.value}: {e}"
                )

            except Exception as e:
                failure = StrategyFailure(
                    strategy_name=strategy.name,
                    error_type=ErrorType.UNKNOWN,
                    error_msg=str(e),
                )
                errors.append(failure)
                prev_strategy_name = strategy.name
                logger.error(f"전략 예상치 못한 오류: {strategy.name} — {e}", exc_info=True)

            finally:
                await strategy.cleanup()

        # 모든 전략 실패
        return await self._build_failed_result_async(
            url=url,
            errors=errors,
            started_at=started_at,
            start_time=start_time,
        )

    def _build_failed_result(
        self,
        url: str,
        errors: list[StrategyFailure],
        started_at: datetime,
        start_time: float,
    ) -> CrawlResult:
        """동기 실패 결과 생성."""
        return CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="",
            strategy_used=None,
            started_at=started_at,
            finished_at=datetime.now(),
            duration_seconds=time.monotonic() - start_time,
            errors=errors,
            error_msg=f"모든 전략 실패 ({len(errors)}개 시도)",
        )

    async def _build_failed_result_async(
        self,
        url: str,
        errors: list[StrategyFailure],
        started_at: datetime,
        start_time: float,
    ) -> CrawlResult:
        """비동기 실패 결과 생성 + 이벤트 발행."""
        result = self._build_failed_result(url, errors, started_at, start_time)

        await self._event_bus.publish(Event(
            event_type=CRAWL_FAILED,
            data={
                "url": url,
                "errors_count": len(errors),
                "error_types": [e.error_type.value for e in errors],
            },
            source="engine.executor",
        ))

        return result

    @property
    def strategies(self) -> list:
        """등록된 전략 목록 (difficulty 순)."""
        return list(self._strategies)

    @property
    def strategy_names(self) -> list[str]:
        """등록된 전략 이름 목록."""
        return [s.name for s in self._strategies]
