"""
Concurrency primitives for crawler execution.

Provides:
- A global semaphore limiting total concurrent crawler tasks.
- A per-crawler lock set preventing duplicate runs of the same crawler.
"""

import asyncio
import os
import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))

_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

_running_crawlers: set[str] = set()
_lock = asyncio.Lock()


async def acquire_crawler_slot(crawler_id: str) -> bool:
    """Try to mark a crawler as running. Returns False if already running."""
    async with _lock:
        if crawler_id in _running_crawlers:
            return False
        _running_crawlers.add(crawler_id)
    return True


async def release_crawler_slot(crawler_id: str) -> None:
    """Mark a crawler as no longer running."""
    async with _lock:
        _running_crawlers.discard(crawler_id)


def get_semaphore() -> asyncio.Semaphore:
    return _semaphore


def active_count() -> int:
    return len(_running_crawlers)
