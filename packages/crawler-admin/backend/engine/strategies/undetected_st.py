"""Disabled undetected browser strategy.

Undetected browser automation is not a safe source-collection path for this
project because it can be interpreted as bot/WAF challenge evasion.
"""

from __future__ import annotations

from typing import Optional

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy


class UndetectedStrategy(BaseStrategy):
    """Disabled: do not use undetected browser automation for collection."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        headless: bool = True,
        wait_timeout: int = 15,
    ) -> None:
        super().__init__(anti_detect)
        self._headless = headless
        self._wait_timeout = wait_timeout

    @property
    def name(self) -> str:
        return "undetected"

    @property
    def difficulty(self) -> int:
        return 4

    async def _do_fetch(self, url: str, **options) -> str:
        raise CrawlError(
            "undetected browser automation is disabled; use ordinary Playwright/Selenium, "
            "saved-source input, or an official/public feed/API instead.",
            error_type=ErrorType.UNKNOWN,
            strategy_name=self.name,
        )
