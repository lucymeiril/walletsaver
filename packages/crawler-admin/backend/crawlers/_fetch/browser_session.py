"""Shared Playwright browser session helpers for live crawler fetches.

The mart crawlers use this module for the fetch layer only; parser/business
logic stays in each crawler.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_HEADERS = {
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
BLOCKED_STATUSES = {202, 401, 403, 429, 503}
BLOCK_MARKERS = (
    "captcha",
    "recaptcha",
    "access denied",
    "awswaf",
    "aws-waf",
    "aws waf",
    "cloudflare",
    "비정상",
    "자동화",
    "보안문자",
    "접근이 제한",
)


def default_storage_state_path() -> Path:
    configured = os.getenv("CRAWLER_BROWSER_STORAGE_STATE")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / ".browser-state" / "storage_state.json"


@asynccontextmanager
async def get_browser_context(
    *,
    headless: bool = False,
    storage_state_path: str | Path | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    viewport: dict[str, int] | None = None,
    locale: str = "ko-KR",
    timezone_id: str = "Asia/Seoul",
    extra_http_headers: dict[str, str] | None = None,
) -> AsyncIterator[Any]:
    """Open a Playwright Chromium context with legacy crawler defaults.

    Defaults intentionally match the previously working headed browser layer:
    Korean locale, desktop viewport, realistic Chrome UA, common headers, and
    storage-state persistence so cookies survive repeated live smoke runs.
    """
    from playwright.async_api import async_playwright

    state_path = Path(storage_state_path) if storage_state_path is not None else default_storage_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {**DEFAULT_HEADERS, **(extra_http_headers or {})}
    browser = None
    context = None
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )
        options: dict[str, Any] = {
            "locale": locale,
            "timezone_id": timezone_id,
            "viewport": viewport or DEFAULT_VIEWPORT,
            "user_agent": user_agent,
            "extra_http_headers": headers,
        }
        if state_path.exists():
            options["storage_state"] = str(state_path)
        context = await browser.new_context(**options)
        yield context
        try:
            await context.storage_state(path=str(state_path))
        except Exception as exc:  # pragma: no cover - best-effort cache
            logger.debug("failed to save browser storage state %s: %s", state_path, exc)
    finally:
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        await playwright.stop()


async def is_blocked_page(page: Any, response: Any | None = None) -> bool:
    status = getattr(response, "status", None)
    if status in BLOCKED_STATUSES:
        return True
    try:
        html = (await page.content())[:20000].lower()
    except Exception:
        return False
    return any(marker in html for marker in BLOCK_MARKERS)


async def goto_with_retry(
    page: Any,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.5,
    wait_until: str = "domcontentloaded",
    timeout: int = 30_000,
) -> Any | None:
    """Navigate with exponential backoff for transient block/network signals."""
    last_exc: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        response = None
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout)
            if not await is_blocked_page(page, response):
                return response
            logger.warning("blocked response while fetching %s (attempt %s/%s)", url, attempt, retries)
        except Exception as exc:
            last_exc = exc
            logger.warning("navigation failed for %s (attempt %s/%s): %s", url, attempt, retries, exc)
        if attempt < retries:
            await asyncio.sleep(backoff * attempt)
    if last_exc is not None:
        raise last_exc
    return response


async def scroll_until_stable(
    page: Any,
    *,
    max_scrolls: int = 20,
    wait_ms: int = 800,
    stable_rounds: int = 3,
    selector: str | None = None,
) -> dict[str, int | bool]:
    """Scroll until document height/card count is stable for lazy-loaded pages."""
    previous_height = -1
    previous_count = -1
    stable = 0
    final_count = 0
    final_height = 0
    attempts = 0
    for attempts in range(1, max(1, max_scrolls) + 1):
        if selector:
            try:
                final_count = await page.locator(selector).count()
            except Exception:
                final_count = 0
        try:
            final_height = int(await page.evaluate("document.body.scrollHeight"))
        except Exception:
            final_height = 0
        if final_height == previous_height and (not selector or final_count == previous_count):
            stable += 1
        else:
            stable = 0
        if stable >= stable_rounds:
            break
        previous_height = final_height
        previous_count = final_count
        await page.evaluate("window.scrollBy(0, Math.max(window.innerHeight || 900, 900))")
        await page.wait_for_timeout(wait_ms)
    return {
        "attempts": attempts,
        "stable": stable >= stable_rounds,
        "final_height": final_height,
        "final_count": final_count,
    }


async def render_html(
    url: str,
    *,
    wait_selector: str | None = None,
    scroll_selector: str | None = None,
    scroll: bool = False,
    headless: bool = False,
    timeout: int = 30_000,
    extra_wait_ms: int = 1500,
    extra_http_headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch one URL through the shared browser context and return HTML + diagnostics."""
    async with get_browser_context(headless=headless, extra_http_headers=extra_http_headers) as context:
        page = await context.new_page()
        try:
            response = await goto_with_retry(page, url, timeout=timeout)
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    logger.debug("selector wait timed out: %s", wait_selector)
            scroll_info: dict[str, Any] = {}
            if scroll:
                scroll_info = await scroll_until_stable(page, selector=scroll_selector or wait_selector)
            if extra_wait_ms:
                await page.wait_for_timeout(extra_wait_ms)
            html = await page.content()
            return html, {
                "url": url,
                "final_url": getattr(page, "url", url),
                "status_code": getattr(response, "status", None),
                "bytes": len(html.encode("utf-8")),
                "scroll": scroll_info,
            }
        finally:
            await page.close()
