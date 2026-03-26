"""
크롤링 전략의 공통 기반 — 모든 전략이 봇 탐지 회피와 에러 래핑을 자동으로 수행한다.

왜 존재하는가:
    각 전략(requests, cloudscraper, Selenium)마다 봇 탐지 딜레이를 삽입하고
    예외를 CrawlError로 래핑하는 코드를 중복 작성하면 버그 온상이 된다.
    BaseStrategy가 공통 흐름(딜레이 → fetch → 에러 래핑)을 Template Method로 제공하고,
    서브클래스는 _do_fetch()만 구현하면 된다.
어디서 쓰이는가:
    engine/strategies/ 하위의 모든 전략 클래스가 이것을 상속.
    executor가 strategy.fetch()를 호출하면 이 클래스의 fetch()가 실행된다.
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
    전략 베이스 클래스 — Template Method 패턴으로 공통 흐름을 강제한다.

    fetch() 흐름: 봇 탐지 회피 딜레이 → _do_fetch(서브클래스 구현) → 에러를 CrawlError로 래핑
    왜 에러를 래핑하는가: executor는 CrawlError만 catch하므로,
    requests.ConnectionError 같은 라이브러리 예외를 그대로 던지면 cascade가 깨진다.
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
        # 봇 탐지 회피: 인간처럼 불규칙한 간격을 둬야 차단 안 당함
        delay = self._anti_detect.get_random_delay()
        logger.debug(f"[{self.name}] 딜레이: {delay:.1f}초")
        await asyncio.sleep(delay)

        try:
            return await self._do_fetch(url, **options)
        except CrawlError:
            raise  # 이미 분류된 에러는 그대로 전파
        except Exception as e:
            # 미분류 예외를 CrawlError로 래핑 — executor가 일관되게 처리할 수 있도록
            raise CrawlError(
                str(e),
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            ) from e

    async def cleanup(self) -> None:
        """기본 cleanup — 서브클래스에서 오버라이드 가능."""
        pass
