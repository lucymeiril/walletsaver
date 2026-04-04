"""
전략 ⑤ — Playwright + Stealth.

최고 수준의 봇 탐지 우회. 가장 무거운 전략.
difficulty: 5
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


class PlaywrightStrategy(BaseStrategy):
    """Playwright + playwright-stealth로 최고 수준 봇 우회."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        headless: bool = True,
        wait_timeout: int = 15,
    ) -> None:
        super().__init__(anti_detect)
        self._headless = headless
        self._wait_timeout = wait_timeout
        self._browser = None
        self._playwright = None

    @property
    def name(self) -> str:
        return "playwright"

    @property
    def difficulty(self) -> int:
        return 5

    async def _do_fetch(self, url: str, **options) -> str:
        wait_timeout = options.get("wait_timeout", self._wait_timeout)

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise CrawlError(
                "playwright가 설치되지 않았습니다. pip install playwright && playwright install",
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            )

        pw = await async_playwright().start()
        self._playwright = pw

        ua = self._anti_detect.get_random_user_agent()
        proxy = self._anti_detect.get_random_proxy()
        proxy_config = {"server": proxy} if proxy else None

        browser = await pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--js-flags=--max-old-space-size=256",
                "--disable-extensions",
                "--disable-gpu",
            ],
        )
        self._browser = browser

        context = await browser.new_context(
            user_agent=ua,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1920, "height": 1080},
            proxy=proxy_config,
        )

        # playwright-stealth 적용
        try:
            from playwright_stealth import stealth_async
            await stealth_async(context)
        except ImportError:
            logger.warning("playwright-stealth 미설치. 기본 Playwright로 진행.")

        page = await context.new_page()

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout * 1000)

            # 추가 렌더링 대기
            await page.wait_for_timeout(int(wait_timeout * 500))

            html = await page.content()

            if not html or len(html.strip()) < 100:
                raise CrawlError(
                    "빈 응답 (JS 렌더링 실패)",
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
                f"Playwright 오류: {e}",
                error_type=ErrorType.UNKNOWN,
                strategy_name=self.name,
            )
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            try:
                await pw.stop()
            except Exception:
                pass
            self._browser = None
            self._playwright = None

    async def cleanup(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
