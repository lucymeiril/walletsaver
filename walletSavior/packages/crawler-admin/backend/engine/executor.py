"""
다중 전략 cascade 실행기 — 사이트마다 다른 봇 방어를 자동으로 돌파한다.

왜 존재하는가:
    이마트는 단순 requests로 되지만, 쿠팡은 Cloudflare JS 챌린지가 있고,
    SSG는 캡챠를 띄운다. 하나의 전략으로는 모든 사이트를 크롤링할 수 없으므로
    가벼운 전략(requests)부터 시도하고, 실패하면 무거운 전략(Selenium/Playwright)으로
    자동 escalation하는 cascade 패턴이 필요하다.
    difficulty 순 정렬 이유: 가벼운 전략이 성공하면 리소스를 아끼고 속도도 빠르다.
어디서 쓰이는가:
    container.py에서 전략 리스트 + EventBus를 주입받아 생성.
    크롤러 플러그인이 execute()를 호출하면 cascade가 시작된다.
    의존: core/ 만 (contracts, events, models, exceptions)
"""

from __future__ import annotations

import asyncio
import logging
import os
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
from engine.rate_limiter import get_domain_limiter

logger = logging.getLogger(__name__)

_DEFAULT_STRATEGY_TIMEOUT = 60
_MAX_CUMULATIVE_TIMEOUT = int(os.getenv("CRAWL_CUMULATIVE_TIMEOUT", "180"))


class StrategyExecutor:
    """
    다중 전략 cascade 실행기 — 가벼운 전략부터 시도하여 리소스를 최소화한다.

    왜 이 구조인가:
        difficulty 순 정렬로 requests(빠름/가벼움) → cloudscraper → Selenium(느림/무거움)
        순서로 시도한다. 첫 번째 성공 시 즉시 반환하므로,
        대부분의 사이트에서는 가장 가벼운 전략으로 충분하다.
        모든 전략 실패 시 각 실패 기록(StrategyFailure)을 모아
        DiagnosticsEngine이 자동 진단할 수 있는 CrawlResult를 반환한다.
    """

    def __init__(
        self,
        strategies: list,
        event_bus: Optional[EventBus] = None,
        strategy_timeout: Optional[int] = None,
        cumulative_timeout: Optional[int] = None,
    ) -> None:
        # difficulty 순 정렬: 낮을수록 가벼운 전략 → 리소스 절약
        self._strategies = sorted(strategies, key=lambda s: s.difficulty)
        self._event_bus = event_bus or EventBus()
        self._strategy_timeout = strategy_timeout or _DEFAULT_STRATEGY_TIMEOUT
        self._cumulative_timeout = cumulative_timeout or _MAX_CUMULATIVE_TIMEOUT

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
        try:
            return await asyncio.wait_for(
                self._execute_cascade(url, force_strategy=force_strategy, **options),
                timeout=self._cumulative_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Cumulative timeout ({self._cumulative_timeout}s) exceeded for {url}")
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name="",
                strategy_used=None,
                started_at=datetime.now(),
                finished_at=datetime.now(),
                duration_seconds=self._cumulative_timeout,
                errors=[],
                error_msg=f"Cumulative timeout ({self._cumulative_timeout}s) exceeded",
            )

    async def _execute_cascade(
        self,
        url: str,
        force_strategy: Optional[str] = None,
        **options,
    ) -> CrawlResult:
        """전략 cascade 실행 (cumulative timeout에 의해 래핑됨)."""
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
                await get_domain_limiter().wait(url)
                raw_data = await asyncio.wait_for(
                    strategy.fetch(url, **options),
                    timeout=self._strategy_timeout,
                )

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
