"""Debounced publisher for the derived public SQLite snapshot.

The source DB remains the source of truth. Public-data writes only mark the
snapshot dirty; this background loop waits until writes have been quiet for a
short settle window, then rebuilds the snapshot once. Large imports therefore
coalesce into one publication instead of rebuilding on every commit.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from services.base import get_engine
from services.public_snapshot_state import get_snapshot_state
from services.public_snapshot_v2 import (
    DEFAULT_PUBLIC_SNAPSHOT_PATH,
    build_public_snapshot,
)

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 1.0
DEFAULT_SETTLE_SECONDS = 5.0


def public_snapshot_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_PUBLIC_DB")
    return Path(configured) if configured else DEFAULT_PUBLIC_SNAPSHOT_PATH


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_status() -> dict:
    engine = get_engine()
    with engine.begin() as connection:
        return get_snapshot_state(connection)


def _ready_to_publish(state: dict, target: Path, settle_seconds: float) -> bool:
    if not target.exists():
        return True
    if not state.get("dirty"):
        return False
    updated_at = _parse_utc(state.get("updated_at"))
    if updated_at is None:
        return True
    quiet_for = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return quiet_for >= settle_seconds


async def run_public_snapshot_publisher(
    stop_event: asyncio.Event,
    *,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
) -> None:
    """Publish dirty snapshots until ``stop_event`` is set.

    Snapshot building is synchronous SQLite/file IO, so it runs in a worker
    thread and never blocks the FastAPI event loop. If source data changes while
    a build is in progress, public_snapshot_v2 leaves the state dirty and the
    loop publishes again after the next quiet period.
    """
    target = public_snapshot_path()
    logger.info("Public snapshot publisher started: %s", target)

    while not stop_event.is_set():
        try:
            state = await asyncio.to_thread(_snapshot_status)
            if _ready_to_publish(state, target, settle_seconds):
                result = await asyncio.to_thread(build_public_snapshot, target)
                logger.info(
                    "Public snapshot published: revision=%s rows=%s dirty=%s",
                    result.get("snapshot_revision"),
                    sum(result.get("row_counts", {}).values()),
                    result.get("dirty_after_build"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Public snapshot publish failed; will retry")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass

    logger.info("Public snapshot publisher stopped")
