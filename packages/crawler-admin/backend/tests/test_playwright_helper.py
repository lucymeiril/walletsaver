from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engine.playwright_helper import PlaywrightHelper


@pytest.mark.asyncio
async def test_helper_passes_stable_browser_channel_to_playwright(monkeypatch):
    monkeypatch.delenv("CRAWLER_BROWSER_EXECUTABLE_PATH", raising=False)
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


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("proxy_variable", ["HTTPS_PROXY", "HTTP_PROXY"])
@pytest.mark.asyncio
async def test_helper_uses_explicit_browser_and_normal_proxy(monkeypatch, tmp_path, persistent, proxy_variable):
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CRAWLER_BROWSER_EXECUTABLE_PATH", "/operator/browser/chrome")
    monkeypatch.setenv(proxy_variable, "http://operator:test%40value@proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,.internal.example")
    context = SimpleNamespace(close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    chromium = SimpleNamespace(launch=AsyncMock(return_value=browser),
                               launch_persistent_context=AsyncMock(return_value=context))
    playwright = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    monkeypatch.setattr("playwright.async_api.async_playwright",
                        lambda: SimpleNamespace(start=AsyncMock(return_value=playwright)))
    async with PlaywrightHelper(browser_channel="chrome", persistent_user_data_dir=tmp_path if persistent else None):
        pass
    launch = chromium.launch_persistent_context if persistent else chromium.launch
    options = launch.await_args.kwargs
    assert options["executable_path"] == "/operator/browser/chrome"
    assert "channel" not in options
    assert options["proxy"] == {"server": "http://proxy.example:8080", "username": "operator",
                                "password": "test@value", "bypass": "localhost,127.0.0.1,.internal.example"}
    assert "ignore_https_errors" not in options
    if not persistent:
        assert "ignore_https_errors" not in browser.new_context.await_args.kwargs
    context.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


@pytest.mark.parametrize("visible_text,widget_visible,expected", [
    ("상품 목록", None, False),
    ("Access denied", None, True),
    ("로봇이 아닙니다", None, True),
    ("상품 목록", False, False),
    ("", True, True),
])
@pytest.mark.asyncio
async def test_rendered_diagnostics_ignores_sdk_and_requires_visible_challenge(visible_text, widget_visible, expected):
    html = '<script src="awswaf/captcha-sdk.js"></script><script>const msg="access denied";</script><body>상품 목록</body>'
    widgets = [] if widget_visible is None else [SimpleNamespace(is_visible=AsyncMock(return_value=widget_visible))]
    page = SimpleNamespace(goto=AsyncMock(return_value=SimpleNamespace(status=200)),
        content=AsyncMock(return_value=html), inner_text=AsyncMock(return_value=visible_text),
        query_selector_all=AsyncMock(return_value=widgets), close=AsyncMock(), url="https://public.example/product")
    helper = PlaywrightHelper()
    helper._context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    result = await helper.get_rendered_html_with_diagnostics(page.url, extra_wait_ms=0)
    assert result["challenge_detected"] is expected
    assert result["html"] == html
    assert result["status_code"] == 200
    page.close.assert_awaited_once()
