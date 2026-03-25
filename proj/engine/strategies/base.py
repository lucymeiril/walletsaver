"""
전략 베이스 클래스.

StrategyContract의 공통 구현을 제공한다.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

from core.contracts.engine import StrategyContract
from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    전략 베이스 클래스.

    공통 기능: AntiDetect 연동, 딜레이, 에러 래핑.
    """

    def __init__(self, anti_detect: Optional[AntiDetect] = None) -> None:
        self._anti_detect = anti_detect or AntiDetect()

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def difficulty(self) -> int:
        ...

    @abstractmethod
    async def _do_fetch(self, url: str, **options) -> str:
        """서브클래스가 구현할 실제 fetch 로직."""
        ...

    async def fetch(self, url: str, **options) -> str:
        """
        URL에서 콘텐츠를 가져온다.
        AntiDetect 딜레이를 적용하고, 에러를 CrawlError로 래핑한다.
        """
        # 딜레이 적용
        delay = self._anti_detect.get_random_delay()
        logger.debug(f"[{self.name}] 딜레이: {delay:.1f}초")
        await asyncio.sleep(delay)

        try:
            return await self._do_fetch(url, **options)
        except CrawlError:
            raise  # 이미 CrawlError면 그대로
        except Exception as e:
            raise CrawlError(
                str(e),
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            ) from e

    async def cleanup(self) -> None:
        """기본 cleanup — 서브클래스에서 오버라이드 가능."""
        pass
