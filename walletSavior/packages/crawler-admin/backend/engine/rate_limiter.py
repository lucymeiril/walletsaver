"""
Per-domain outbound rate limiter.

Ensures crawlers respect a minimum interval between requests to the same domain.
Prevents IP bans and legal issues from aggressive crawling.
"""

import asyncio
import os
import time
from collections import defaultdict
from urllib.parse import urlparse

_DEFAULT_MIN_INTERVAL = float(os.getenv("CRAWL_MIN_DOMAIN_INTERVAL", "2.0"))


class DomainRateLimiter:
    """Enforces a per-domain minimum interval between outbound requests."""

    def __init__(self, min_interval: float = _DEFAULT_MIN_INTERVAL):
        self._min_interval = min_interval
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, url: str) -> None:
        """Block until the domain is available for a new request."""
        domain = urlparse(url).netloc.lower()
        if not domain:
            return

        async with self._locks[domain]:
            elapsed = time.monotonic() - self._last_request[domain]
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request[domain] = time.monotonic()

    def set_interval(self, domain: str, interval: float) -> None:
        """Override interval for a specific domain."""
        pass  # future enhancement


_limiter = DomainRateLimiter()


def get_domain_limiter() -> DomainRateLimiter:
    return _limiter
