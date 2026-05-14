"""Tests for outbound domain rate limiter."""

import asyncio
import time
import pytest
from engine.rate_limiter import DomainRateLimiter


@pytest.mark.asyncio
async def test_first_request_immediate():
    """First request to a domain should not block."""
    limiter = DomainRateLimiter(min_interval=1.0)
    start = time.monotonic()
    await limiter.wait("https://example.com/page1")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_second_request_delayed():
    """Second request to same domain should wait min_interval."""
    limiter = DomainRateLimiter(min_interval=0.5)
    await limiter.wait("https://example.com/page1")
    start = time.monotonic()
    await limiter.wait("https://example.com/page2")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.4  # Allow small timing margin


@pytest.mark.asyncio
async def test_different_domains_independent():
    """Different domains should not block each other."""
    limiter = DomainRateLimiter(min_interval=1.0)
    await limiter.wait("https://example.com/page1")
    start = time.monotonic()
    await limiter.wait("https://other-site.com/page1")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1
