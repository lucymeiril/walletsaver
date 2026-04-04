"""
전략 ④ — undetected-chromedriver.

강화된 봇 탐지 우회 (Selenium ChromeDriver 패치 버전).
difficulty: 4
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class UndetectedStrategy(BaseStrategy):
    """undetected-chromedriver로 강화된 봇 탐지 우회."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        headless: bool = True,
        wait_timeout: int = 15,
    ) -> None:
        super().__init__(anti_detect)
        self._headless = headless
        self._wait_timeout = wait_timeout
        self._driver = None

    @property
    def name(self) -> str:
        return "undetected"

    @property
    def difficulty(self) -> int:
        return 4

    async def _do_fetch(self, url: str, **options) -> str:
        wait_timeout = options.get("wait_timeout", self._wait_timeout)
        loop = asyncio.get_event_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
        return html

    def _fetch_sync(self, url: str, wait_timeout: int) -> str:
        """동기 undetected-chromedriver fetch."""
        try:
            import undetected_chromedriver as uc
        except ImportError:
            raise CrawlError(
                "undetected-chromedriver가 설치되지 않았습니다. pip install undetected-chromedriver",
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            )

        options = uc.ChromeOptions()
        if self._headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument(f"--user-agent={self._anti_detect.get_random_user_agent()}")

        proxy = self._anti_detect.get_random_proxy()
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        driver = uc.Chrome(options=options)
        self._driver = driver

        try:
            driver.get(url)
            import time
            time.sleep(wait_timeout * 0.5)

            html = driver.page_source

            if not html or len(html.strip()) < 100:
                raise CrawlError(
                    "빈 응답",
                    error_type=ErrorType.EMPTY_RESPONSE,
                    strategy_name=self.name,
                )

            html_lower = html.lower()
            if "captcha" in html_lower or "recaptcha" in html_lower:
                raise CrawlError(
                    "CAPTCHA 감지",
                    error_type=ErrorType.CAPTCHA_DETECTED,
                    strategy_name=self.name,
                )

            return html

        except CrawlError:
            raise
        except Exception as e:
            raise CrawlError(
                f"undetected-chromedriver 오류: {e}",
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            )
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            self._driver = None

    async def cleanup(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
