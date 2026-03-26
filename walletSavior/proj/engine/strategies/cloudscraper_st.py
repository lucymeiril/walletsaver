"""
전략 ② — cloudscraper.

Cloudflare 기본 보호(JS Challenge)를 우회하는 전략.
difficulty: 2
"""

from __future__ import annotations

import logging
from typing import Optional

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class CloudscraperStrategy(BaseStrategy):
    """cloudscraper로 Cloudflare 기본 보호 우회."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        timeout: int = 30,
    ) -> None:
        super().__init__(anti_detect)
        self._timeout = timeout
        self._scraper = None

    @property
    def name(self) -> str:
        return "cloudscraper"

    @property
    def difficulty(self) -> int:
        return 2

    def _get_scraper(self):
        """cloudscraper 인스턴스를 지연 생성한다."""
        if self._scraper is None:
            try:
                import cloudscraper
                self._scraper = cloudscraper.create_scraper(
                    browser={
                        "browser": "chrome",
                        "platform": "windows",
                        "desktop": True,
                    }
                )
            except ImportError:
                raise CrawlError(
                    "cloudscraper 패키지가 설치되지 않았습니다. pip install cloudscraper",
                    error_type=ErrorType.UNKNOWN,
                    strategy_name=self.name,
                )
        return self._scraper

    async def _do_fetch(self, url: str, **options) -> str:
        scraper = self._get_scraper()
        headers = options.get("headers") or self._anti_detect.get_random_headers()
        proxy = self._anti_detect.get_random_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        timeout = options.get("timeout", self._timeout)

        try:
            response = scraper.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "cloudflare" in error_msg or "challenge" in error_msg:
                raise CrawlError(
                    f"Cloudflare 우회 실패: {e}",
                    error_type=ErrorType.JS_CHALLENGE,
                    strategy_name=self.name,
                )
            raise CrawlError(
                str(e),
                error_type=ErrorType.NETWORK_ERROR,
                strategy_name=self.name,
            )

        if response.status_code == 403:
            raise CrawlError(
                "403 Forbidden",
                error_type=ErrorType.IP_BANNED,
                status_code=403,
                strategy_name=self.name,
            )

        if response.status_code >= 400:
            raise CrawlError(
                f"HTTP {response.status_code}",
                error_type=ErrorType.HTTP_ERROR,
                status_code=response.status_code,
                strategy_name=self.name,
            )

        if not response.text or len(response.text.strip()) < 10:
            raise CrawlError(
                "빈 응답",
                error_type=ErrorType.EMPTY_RESPONSE,
                strategy_name=self.name,
            )

        return response.text

    async def cleanup(self) -> None:
        self._scraper = None
