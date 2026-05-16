"""
전략 ⑤ — Playwright rendering.

운영자 워크밴치 정책(``pipeline.operator_workbench_policy``)에 따라
**캡챠 발견 시 즉시 raise하지 않고 운영자에게 인계할 수 있다**.
``captcha_handoff`` 콜러블 옵션을 받으면 캡챠가 발견됐을 때 호출하고,
콜러블이 (해결됨, 최종 HTML)을 돌려주면 그것을 결과로 사용한다.
콜러블이 None을 돌려주거나 None이면 기존처럼 CAPTCHA_DETECTED 에러를 던진다.

또한 헤드풀(headed) 옵션을 외부에서 주입할 수 있다 — 운영자 워크밴치의
헤드풀 브라우저 세션에서 사용한다.
difficulty: 5
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Union

from core.exceptions import CrawlError
from core.models import ErrorType
from engine.anti_detect import AntiDetect
from engine.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


CaptchaHandoff = Callable[[Any], Union[Optional[str], Awaitable[Optional[str]]]]


class PlaywrightStrategy(BaseStrategy):
    """Playwright Chromium 렌더러. 헤드풀/캡챠 인계 옵션을 지원한다."""

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        headless: bool = True,
        wait_timeout: int = 15,
        captcha_handoff: Optional[CaptchaHandoff] = None,
    ) -> None:
        super().__init__(anti_detect)
        self._headless = headless
        self._wait_timeout = wait_timeout
        self._captcha_handoff = captcha_handoff
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
        headless = options.get("headless", self._headless)
        captcha_handoff = options.get("captcha_handoff", self._captcha_handoff)

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

        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--js-flags=--max-old-space-size=256",
                "--disable-extensions",
                "--disable-gpu",
            ],
        )
        self._browser = browser

        context = await browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1920, "height": 1080},
            user_agent=self._anti_detect.get_random_user_agent(),
        )

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout * 1000)
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
                # 운영자 워크밴치 정책: 캡챠는 자동 시도/사람 인계가 우선. 즉시 raise는 폴백.
                if captcha_handoff is not None:
                    result = captcha_handoff(page)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if isinstance(result, str) and result.strip():
                        return result
                    # 인계 후 다시 페이지 콘텐츠를 시도.
                    refreshed = await page.content()
                    if "captcha" not in refreshed.lower() and "recaptcha" not in refreshed.lower():
                        return refreshed
                raise CrawlError(
                    "CAPTCHA 감지 (운영자 인계가 등록되지 않았거나 미해결)",
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
