"""Disabled cloudscraper strategy.

Cloudflare/WAF challenge solvers are not safe source-collection paths for this
project. Blocked public responses must be reported, not bypassed.
"""

from __future__ import annotations

from typing import Optional

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy


class CloudscraperStrategy(BaseStrategy):
    """Disabled: do not use challenge-solving fetchers for collection."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        timeout: int = 30,
    ) -> None:
        super().__init__(anti_detect)
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "cloudscraper"

    @property
    def difficulty(self) -> int:
        return 2

    async def _do_fetch(self, url: str, **options) -> str:
        raise CrawlError(
            "cloudscraper challenge-solving is disabled; report the blocker and use "
            "ordinary HTTP/browser rendering, saved-source input, or an official/public feed/API.",
            error_type=ErrorType.JS_CHALLENGE,
            strategy_name=self.name,
        )
