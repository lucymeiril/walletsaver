"""
Playwright 헬퍼 — SPA 사이트 크롤링을 위한 공유 유틸리티.

각 크롤러가 직접 Playwright를 관리하지 않고,
이 헬퍼를 통해 브라우저 인스턴스를 생성/관리한다.

핵심 기능:
  - headless Chromium 브라우저 관리
  - 페이지 로딩 대기 (selector/timeout 기반)
  - API 응답 인터셉트 (XHR/Fetch 가로채기)
  - 안전한 리소스 정리 (context manager)

의존: playwright
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class PlaywrightHelper:
    """SPA 크롤링을 위한 Playwright 브라우저 관리자.

    Usage:
        async with PlaywrightHelper() as helper:
            html = await helper.get_rendered_html(url, wait_selector=".product-list")
            # 또는
            data = await helper.intercept_api(url, api_pattern="*/api/products*")
    """

    def __init__(
        self,
        headless: bool = True,
        locale: str = "ko-KR",
        timezone: str = "Asia/Seoul",
        viewport: dict | None = None,
        user_agent: str | None = None,
        persistent_user_data_dir: str | Path | None = None,
        browser_channel: str | None = None,
    ):
        self._headless = headless
        self._locale = locale
        self._timezone = timezone
        self._viewport = viewport or {"width": 1920, "height": 1080}
        self._user_agent = user_agent
        self._browser_channel = browser_channel
        env_profile = os.getenv("CRAWLER_BROWSER_PROFILE_DIR")
        self._persistent_user_data_dir = Path(persistent_user_data_dir or env_profile) if (persistent_user_data_dir or env_profile) else None
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        ctx_options = {
            "locale": self._locale,
            "timezone_id": self._timezone,
            "viewport": self._viewport,
        }
        if self._user_agent:
            ctx_options["user_agent"] = self._user_agent

        if self._persistent_user_data_dir:
            self._persistent_user_data_dir.mkdir(parents=True, exist_ok=True)
            launch_options = {
                "headless": self._headless,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                **ctx_options,
            }
            if self._browser_channel:
                launch_options["channel"] = self._browser_channel
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self._persistent_user_data_dir),
                **launch_options,
            )
        else:
            launch_options = {
                "headless": self._headless,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            if self._browser_channel:
                launch_options["channel"] = self._browser_channel
            self._browser = await self._playwright.chromium.launch(**launch_options)
            self._context = await self._browser.new_context(**ctx_options)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    @property
    def context(self):
        """Return the active browser context while inside ``async with``."""
        if self._context is None:
            raise RuntimeError("PlaywrightHelper context is not active")
        return self._context

    async def get_rendered_html(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_timeout: int = 15000,
        extra_wait_ms: int = 2000,
        scroll_to_bottom: bool = False,
    ) -> str:
        """URL을 방문하고 JS 렌더링 완료 후 HTML을 반환한다.

        Args:
            url: 대상 URL
            wait_selector: 이 CSS 셀렉터가 나타날 때까지 대기 (없으면 domcontentloaded만)
            wait_timeout: 대기 타임아웃 (ms)
            extra_wait_ms: 추가 대기 시간 — 동적 콘텐츠 로딩용
            scroll_to_bottom: True면 페이지 끝까지 스크롤 (lazy-load 트리거)
        """
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=wait_timeout)
                except Exception:
                    logger.debug(f"셀렉터 '{wait_selector}' 대기 타임아웃, 현재 상태로 진행")

            if scroll_to_bottom:
                await self._scroll_to_bottom(page)

            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)

            return await page.content()
        finally:
            await page.close()

    async def get_rendered_html_with_diagnostics(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_timeout: int = 15000,
        extra_wait_ms: int = 2000,
        scroll_to_bottom: bool = False,
    ) -> dict:
        """Render a public page and return HTML plus ordinary browser diagnostics."""
        page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=wait_timeout)
                except Exception:
                    logger.debug(f"셀렉터 '{wait_selector}' 대기 타임아웃, 현재 상태로 진행")

            if scroll_to_bottom:
                await self._scroll_to_bottom(page)

            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)

            html = await page.content()
            final_url = page.url
            status = response.status if response else None
            lower = (html or "")[:20000].lower()
            challenge = any(marker in lower for marker in ("captcha", "recaptcha", "awswaf", "aws-waf", "access denied"))
            login_required = any(marker in lower for marker in ("로그인", "sign in", "login required"))
            return {
                "url": url,
                "final_url": final_url,
                "status_code": status,
                "html": html,
                "bytes": len((html or "").encode("utf-8")),
                "challenge_detected": challenge,
                "login_required": login_required,
                "persistent_context": bool(self._persistent_user_data_dir),
            }
        finally:
            await page.close()

    async def intercept_api(
        self,
        url: str,
        api_pattern: str,
        wait_timeout: int = 15000,
        max_responses: int = 10,
    ) -> list[dict]:
        """페이지 로딩 중 특정 API 호출을 가로채서 JSON 응답을 수집한다.

        SPA 사이트가 내부 API로 데이터를 로드하는 경우,
        네트워크 요청을 가로채면 HTML 파싱 없이 구조화된 데이터를 얻을 수 있다.

        Args:
            url: 방문할 페이지 URL
            api_pattern: 가로챌 API URL 패턴 (glob 형식, 예: "**/api/products*")
            wait_timeout: 페이지 로딩 타임아웃 (ms)
            max_responses: 수집할 최대 응답 수

        Returns:
            list[dict]: 가로챈 API 응답 JSON 리스트
        """
        page = await self._context.new_page()
        intercepted: list[dict] = []

        async def handle_response(response):
            if len(intercepted) >= max_responses:
                return
            try:
                if response.url and self._match_pattern(response.url, api_pattern):
                    if response.status == 200:
                        body = await response.json()
                        intercepted.append(body)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)
            # API 응답이 올 때까지 추가 대기
            await page.wait_for_timeout(3000)
            return intercepted
        finally:
            await page.close()

    async def _scroll_to_bottom(self, page, max_scrolls: int = 5):
        """페이지 끝까지 점진적으로 스크롤 — lazy-load 이미지/상품 트리거."""
        for i in range(max_scrolls):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(800)

    @staticmethod
    def _match_pattern(url: str, pattern: str) -> bool:
        """간단한 glob 패턴 매칭 (**/api/* 스타일)."""
        import fnmatch
        # ** → * 로 변환하여 fnmatch 사용
        simplified = pattern.replace("**", "*")
        return fnmatch.fnmatch(url, simplified)
