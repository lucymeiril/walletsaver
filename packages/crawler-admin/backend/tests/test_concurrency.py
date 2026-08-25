"""Tests for concurrency control primitives."""

import asyncio

import pytest

from concurrency import (
    MAX_CONCURRENT_CRAWLS,
    _running_crawlers,
    acquire_crawler_slot,
    active_count,
    clear_running_crawlers,
    get_semaphore,
    release_crawler_slot,
)


@pytest.fixture(autouse=True)
async def cleanup_slots():
    yield
    _running_crawlers.clear()


@pytest.mark.asyncio
async def test_duplicate_crawler_rejected():
    assert await acquire_crawler_slot("test-crawler") is True
    assert await acquire_crawler_slot("test-crawler") is False
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_different_crawlers_allowed():
    assert await acquire_crawler_slot("crawler-a") is True
    assert await acquire_crawler_slot("crawler-b") is True
    await release_crawler_slot("crawler-a")
    await release_crawler_slot("crawler-b")


@pytest.mark.asyncio
async def test_release_allows_reacquire():
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    semaphore = get_semaphore()
    acquired = 0

    async def try_acquire():
        nonlocal acquired
        async with semaphore:
            acquired += 1
            await asyncio.sleep(0.05)

    tasks = [asyncio.create_task(try_acquire()) for _ in range(MAX_CONCURRENT_CRAWLS + 3)]
    await asyncio.sleep(0.01)
    assert acquired <= MAX_CONCURRENT_CRAWLS
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_active_count_tracks_running_crawlers():
    assert active_count() == 0
    await acquire_crawler_slot("c1")
    await acquire_crawler_slot("c2")
    assert active_count() == 2
    await release_crawler_slot("c1")
    assert active_count() == 1
    await release_crawler_slot("c2")
    assert active_count() == 0


@pytest.mark.asyncio
async def test_clear_running_crawlers_clears_shutdown_state():
    await acquire_crawler_slot("crawler-a")
    await acquire_crawler_slot("crawler-b")

    cleared = await clear_running_crawlers()

    assert cleared == 2
    assert active_count() == 0
