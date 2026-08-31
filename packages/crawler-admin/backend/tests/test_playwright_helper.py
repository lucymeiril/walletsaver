from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engine.playwright_helper import PlaywrightHelper


@pytest.mark.asyncio
async def test_helper_passes_stable_browser_channel_to_playwright(monkeypatch):
    context = SimpleNamespace(close=AsyncMock())
    browser = SimpleNamespace(
        new_context=AsyncMock(return_value=context),
        close=AsyncMock(),
    )
    chromium = SimpleNamespace(launch=AsyncMock(return_value=browser))
    playwright = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    starter = SimpleNamespace(start=AsyncMock(return_value=playwright))

    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: starter,
    )

    async with PlaywrightHelper(
        headless=False,
        browser_channel="chrome",
    ) as helper:
        assert helper.context is context

    launch_options = chromium.launch.await_args.kwargs
    assert launch_options["headless"] is False
    assert launch_options["channel"] == "chrome"
    browser.new_context.assert_awaited_once()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
