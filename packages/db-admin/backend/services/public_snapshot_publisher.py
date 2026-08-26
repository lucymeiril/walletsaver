"""Debounced publisher for the derived public SQLite snapshot.

The source DB remains the source of truth. Public-data writes only mark the
snapshot dirty; this background loop waits until writes have been quiet for a
short settle window, then rebuilds the snapshot once. Large imports therefore
coalesce into one publication instead of rebuilding on every commit.

If WALLETSAVIOR_REMOTE_ADMIN_TOKEN is configured, the local catalog snapshot is
also deployed to web-api after a successful build. The upload is independent
from snapshot generation so a temporary network failure never dirties or
rebuilds the local source data.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
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
REMOTE_RETRY_SECONDS = 30.0


def _sqlite_source_path() -> Path | None:
    try:
        from config import settings

        url = settings.DATABASE_URL
    except Exception:
        url = os.getenv("DATABASE_URL", "")
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///")).resolve()


def public_snapshot_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_PUBLIC_DB")
    candidate = Path(configured) if configured else DEFAULT_PUBLIC_SNAPSHOT_PATH
    candidate = candidate.resolve()
    source = _sqlite_source_path()
    if source is not None and candidate == source:
        safe_default = DEFAULT_PUBLIC_SNAPSHOT_PATH.resolve()
        logger.error(
            "Refusing to publish public snapshot over source DB %s; using %s",
            source,
            safe_default,
        )
        return safe_default
    return candidate


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


def _remote_publish_enabled() -> bool:
    return bool(os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip())


def _snapshot_revision(path: Path) -> int | None:
    if not path.exists():
        return None
    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row = connection.execute(
                "SELECT revision FROM snapshot_meta WHERE id=1"
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            connection.close()
    except Exception:
        return None


def _upload_catalog_snapshot(path: Path) -> dict:
    from services.remote_web_admin import upload_snapshot

    return upload_snapshot("catalog", path)


async def run_public_snapshot_publisher(
    stop_event: asyncio.Event,
    *,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
) -> None:
    """Publish dirty snapshots and optionally deploy them to web-api."""
    target = public_snapshot_path()
    uploaded_revision: int | None = None
    next_remote_attempt = 0.0
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
            logger.exception("Public snapshot build failed; will retry")

        if (
            _remote_publish_enabled()
            and target.exists()
            and time.monotonic() >= next_remote_attempt
        ):
            local_revision = await asyncio.to_thread(_snapshot_revision, target)
            if local_revision is not None and local_revision != uploaded_revision:
                try:
                    deploy_result = await asyncio.to_thread(_upload_catalog_snapshot, target)
                    uploaded_revision = local_revision
                    next_remote_attempt = 0.0
                    logger.info(
                        "Public snapshot deployed to web-api: revision=%s bytes=%s",
                        local_revision,
                        deploy_result.get("bytes"),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    next_remote_attempt = time.monotonic() + REMOTE_RETRY_SECONDS
                    logger.exception(
                        "Public snapshot deploy failed; retrying in %.0fs",
                        REMOTE_RETRY_SECONDS,
                    )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass

    logger.info("Public snapshot publisher stopped")
