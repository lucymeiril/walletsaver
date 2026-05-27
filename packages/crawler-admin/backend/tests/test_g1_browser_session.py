from __future__ import annotations

import asyncio

from crawlers._fetch.browser_session import goto_with_retry, scroll_until_stable


class _Response:
    def __init__(self, status: int):
        self.status = status


class _Locator:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return self.page.counts[min(self.page.count_index, len(self.page.counts) - 1)]


class _ScrollPage:
    def __init__(self):
        self.heights = [1000, 1500, 1500, 1500, 1500]
        self.counts = [1, 3, 3, 3, 3]
        self.height_index = 0
        self.count_index = 0
        self.scrolls = 0

    def locator(self, _selector: str):
        return _Locator(self)

    async def evaluate(self, script: str):
        if "scrollHeight" in script:
            value = self.heights[min(self.height_index, len(self.heights) - 1)]
            self.height_index += 1
            return value
        self.scrolls += 1
        self.count_index = min(self.count_index + 1, len(self.counts) - 1)
        return None

    async def wait_for_timeout(self, _ms: int):
        return None


class _RetryPage:
    def __init__(self):
        self.calls = 0
        self.contents = ["awswaf challenge", "<html><body>ok</body></html>"]

    async def goto(self, *_args, **_kwargs):
        self.calls += 1
        return _Response(202 if self.calls == 1 else 200)

    async def content(self):
        return self.contents[min(self.calls - 1, len(self.contents) - 1)]


class _FailThenSuccessPage:
    def __init__(self):
        self.calls = 0

    async def goto(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("boom")
        return _Response(200)

    async def content(self):
        return "ok"


def test_scroll_until_stable_stops_after_stable_rounds():
    page = _ScrollPage()
    result = asyncio.run(scroll_until_stable(page, max_scrolls=10, wait_ms=0, stable_rounds=2, selector=".unitItemInner"))
    assert result["stable"] is True
    assert result["final_count"] == 3
    assert page.scrolls < 10


def test_goto_with_retry_retries_block_status():
    page = _RetryPage()
    response = asyncio.run(goto_with_retry(page, "https://example.test", retries=2, backoff=0, timeout=1))
    assert response.status == 200
    assert page.calls == 2


def test_goto_with_retry_retries_navigation_error():
    page = _FailThenSuccessPage()
    response = asyncio.run(goto_with_retry(page, "https://example.test", retries=2, backoff=0, timeout=1))
    assert response.status == 200
    assert page.calls == 2
