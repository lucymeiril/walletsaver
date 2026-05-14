"""Tests for concurrency control primitives."""

import asyncio
import pytest
from concurrency import (
    acquire_crawler_slot,
    release_crawler_slot,
    get_semaphore,
    active_count,
    MAX_CONCURRENT_CRAWLS,
    _running_crawlers,
)


@pytest.fixture(autouse=True)
async def cleanup_slots():
    """Ensure clean state for each test."""
    yield
    _running_crawlers.clear()


@pytest.mark.asyncio
async def test_duplicate_crawler_rejected():
    """Same crawler cannot run twice concurrently."""
    assert await acquire_crawler_slot("test-crawler") is True
    assert await acquire_crawler_slot("test-crawler") is False
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_different_crawlers_allowed():
    """Different crawlers can run concurrently."""
    assert await acquire_crawler_slot("crawler-a") is True
    assert await acquire_crawler_slot("crawler-b") is True
    await release_crawler_slot("crawler-a")
    await release_crawler_slot("crawler-b")


@pytest.mark.asyncio
async def test_release_allows_reacquire():
    """After release, the same crawler can be acquired again."""
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Global semaphore enforces MAX_CONCURRENT_CRAWLS."""
    sem = get_semaphore()
    acquired = 0

    async def try_acquire():
        nonlocal acquired
        async with sem:
            acquired += 1
            await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(try_acquire()) for _ in range(MAX_CONCURRENT_CRAWLS + 3)]
    await asyncio.sleep(0.1)
    assert acquired <= MAX_CONCURRENT_CRAWLS
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_active_count():
    """active_count reflects running crawlers."""
    assert active_count() == 0
    await acquire_crawler_slot("c1")
    assert active_count() == 1
    await acquire_crawler_slot("c2")
    assert active_count() == 2
    await release_crawler_slot("c1")
    assert active_count() == 1
    await release_crawler_slot("c2")
    assert active_count() == 0
