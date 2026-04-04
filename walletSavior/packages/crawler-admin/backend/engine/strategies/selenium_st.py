"""
전략 ③ — Selenium + Stealth.

JavaScript 렌더링이 필요한 동적 SPA 사이트용.
difficulty: 3
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


class SeleniumStrategy(BaseStrategy):
    """Selenium + selenium-stealth로 JS 렌더링 크롤링."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        headless: bool = True,
        wait_timeout: int = 10,
    ) -> None:
        super().__init__(anti_detect)
        self._headless = headless
        self._wait_timeout = wait_timeout
        self._driver = None

    @property
    def name(self) -> str:
        return "selenium"

    @property
    def difficulty(self) -> int:
        return 3

    def _create_driver(self):
        """Selenium WebDriver를 생성한다."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
        except ImportError:
            raise CrawlError(
                "selenium이 설치되지 않았습니다. pip install selenium",
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            )

        options = Options()
        if self._headless:
            options.add_argument("--headless=new")

        # 안티봇 탐지 회피 옵션
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument("--single-process")
        options.add_argument("--disable-extensions")
        options.add_argument(f"--user-agent={self._anti_detect.get_random_user_agent()}")

        # 프록시 설정
        proxy = self._anti_detect.get_random_proxy()
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=options)

        # selenium-stealth 적용
        try:
            from selenium_stealth import stealth
            stealth(
                driver,
                languages=["ko-KR", "ko", "en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )
        except ImportError:
            logger.warning("selenium-stealth 미설치. 기본 Selenium으로 진행.")

        driver.set_page_load_timeout(self._wait_timeout * 3)
        return driver

    async def _do_fetch(self, url: str, **options) -> str:
        wait_timeout = options.get("wait_timeout", self._wait_timeout)

        # 브라우저 실행은 blocking이므로 executor에서 실행
        loop = asyncio.get_event_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
        return html

    def _fetch_sync(self, url: str, wait_timeout: int) -> str:
        """동기 Selenium fetch."""
        driver = self._create_driver()
        self._driver = driver

        try:
            driver.get(url)

            # 페이지 로딩 대기
            import time
            time.sleep(wait_timeout * 0.5)

            html = driver.page_source

            # 응답 검증
            if not html or len(html.strip()) < 100:
                raise CrawlError(
                    "빈 응답 (JS 렌더링 실패 가능)",
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
                f"Selenium 오류: {e}",
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
