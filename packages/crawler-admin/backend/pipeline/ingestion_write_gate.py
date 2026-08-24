"""Process-wide write gate for db-admin PendingIngestion submissions.

Crawlers may run concurrently, but the db-admin development database is SQLite
and therefore still has a single-writer bottleneck even in WAL mode.  The
crawler pipeline already sleeps between chunks; that delay is per crawler and
does not prevent two independent crawlers from posting at the same time.

This module serializes only ``POST /api/ingestions`` calls and enforces a global
minimum interval between attempts.  Crawl/network concurrency and unrelated
HTTP traffic remain untouched.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL_SECONDS = 3.0
_TARGET_SUFFIX = "/api/ingestions"


@dataclass
class _LoopGateState:
    lock: asyncio.Lock
    last_attempt_finished_at: float = 0.0


_loop_states: dict[asyncio.AbstractEventLoop, _LoopGateState] = {}


def _min_interval_seconds() -> float:
    raw = os.getenv("INGESTION_WRITE_MIN_INTERVAL_SECONDS", str(_DEFAULT_MIN_INTERVAL_SECONDS))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid INGESTION_WRITE_MIN_INTERVAL_SECONDS=%r; using %.1fs",
            raw,
            _DEFAULT_MIN_INTERVAL_SECONDS,
        )
        return _DEFAULT_MIN_INTERVAL_SECONDS


def _is_ingestion_submit_url(url: Any) -> bool:
    text = str(url).split("?", 1)[0].rstrip("/")
    return text.endswith(_TARGET_SUFFIX)


def _state_for_running_loop() -> _LoopGateState:
    loop = asyncio.get_running_loop()
    state = _loop_states.get(loop)
    if state is None:
        state = _LoopGateState(lock=asyncio.Lock())
        _loop_states[loop] = state
    return state


async def run_ingestion_post(
    post_call: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run one ingestion POST behind the process-wide single-writer gate."""
    state = _state_for_running_loop()
    async with state.lock:
        interval = _min_interval_seconds()
        if state.last_attempt_finished_at:
            remaining = interval - (time.monotonic() - state.last_attempt_finished_at)
            if remaining > 0:
                logger.debug("Waiting %.3fs for global ingestion write spacing", remaining)
                await asyncio.sleep(remaining)

        try:
            return await post_call(*args, **kwargs)
        finally:
            # Record failed/time-out attempts too.  A timed-out request may have
            # committed server-side, and the retry-idempotency contract handles
            # the logical duplicate while this spacing protects SQLite.
            state.last_attempt_finished_at = time.monotonic()


def install_httpx_ingestion_write_gate() -> None:
    """Install the gate once on ``httpx.AsyncClient.post``.

    Only the exact ingestion collection endpoint is gated.  Other crawler HTTP
    traffic, including the crawl itself, is left fully concurrent.
    """
    client_cls = httpx.AsyncClient
    if getattr(client_cls, "_walletsavior_ingestion_write_gate_installed", False):
        return

    original_post = client_cls.post

    async def gated_post(self, url, *args, **kwargs):
        if not _is_ingestion_submit_url(url):
            return await original_post(self, url, *args, **kwargs)
        return await run_ingestion_post(
            original_post,
            self,
            url,
            *args,
            **kwargs,
        )

    client_cls.post = gated_post
    client_cls._walletsavior_ingestion_write_gate_installed = True
