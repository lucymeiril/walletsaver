"""
Playwright 헬퍼 — SPA 사이트 크롤링을 위한 공유 유틸리티.

각 크롤러가 직접 Playwright를 관리하지 않고,
이 헬퍼를 통해 브라우저 인스턴스를 생성/관리한다.

핵심 기능:
  - headless Chromium 브라우저 관리
  - stealth 모드 자동 적용
  - 페이지 로딩 대기 (selector/timeout 기반)
  - API 응답 인터셉트 (XHR/Fetch 가로채기)
  - 안전한 리소스 정리 (context manager)

의존: playwright, playwright-stealth (선택)
"""

from __future__ import annotations

import asyncio
import json
import logging
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
    ):
        self._headless = headless
        self._locale = locale
        self._timezone = timezone
        self._viewport = viewport or {"width": 1920, "height": 1080}
        self._user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        ctx_options = {
            "locale": self._locale,
            "timezone_id": self._timezone,
            "viewport": self._viewport,
        }
        if self._user_agent:
            ctx_options["user_agent"] = self._user_agent

        self._context = await self._browser.new_context(**ctx_options)

        # stealth 모드 적용 — 봇 탐지 우회
        try:
            from playwright_stealth import stealth_async
            await stealth_async(self._context)
        except ImportError:
            logger.debug("playwright-stealth 미설치, 기본 모드로 진행")

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
