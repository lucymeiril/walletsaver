"""Debounced publisher for replaceable web-api SQLite read replicas.

Two local-derived files are maintained independently:
- public catalog snapshot (products/categories/prices)
- external hotdeal snapshot (crawler-origin HotdealPost rows)

Server-owned users, community content, votes and reports are never copied into
these files. If remote snapshot deployment is enabled, each completed snapshot
is uploaded to web-api through its authenticated remote-admin endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from services.base import get_engine
from services.external_hotdeal_snapshot import (
    build_external_hotdeal_snapshot,
    external_hotdeal_snapshot_path,
    source_fingerprint as external_hotdeal_fingerprint,
)
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


def _catalog_snapshot_status() -> dict:
    engine = get_engine()
    with engine.begin() as connection:
        return get_snapshot_state(connection)


def _catalog_ready_to_publish(state: dict, target: Path, settle_seconds: float) -> bool:
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
    token = os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip()
    flag = os.getenv("WALLETSAVIOR_REMOTE_SNAPSHOT_UPLOAD", "true").strip().lower()
    return bool(token) and flag not in {"0", "false", "no", "off"}


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


def _upload_snapshot(kind: str, path: Path) -> dict:
    from services.remote_web_admin import upload_snapshot

    return upload_snapshot(kind, path)


async def run_public_snapshot_publisher(
    stop_event: asyncio.Event,
    *,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
) -> None:
    """Maintain catalog and external-hotdeal snapshots until stopped."""
    catalog_target = public_snapshot_path()
    hotdeal_target = external_hotdeal_snapshot_path()

    catalog_uploaded_revision: int | None = None
    hotdeal_uploaded_revision: int | None = None
    next_catalog_remote_attempt = 0.0
    next_hotdeal_remote_attempt = 0.0

    hotdeal_seen_fingerprint: str | None = None
    hotdeal_published_fingerprint: str | None = None
    hotdeal_changed_at = time.monotonic()

    logger.info("Catalog snapshot publisher started: %s", catalog_target)
    logger.info("External hotdeal snapshot publisher started: %s", hotdeal_target)

    while not stop_event.is_set():
        # Product/category/price snapshot uses explicit dirty/revision state.
        try:
            state = await asyncio.to_thread(_catalog_snapshot_status)
            if _catalog_ready_to_publish(state, catalog_target, settle_seconds):
                result = await asyncio.to_thread(build_public_snapshot, catalog_target)
                logger.info(
                    "Catalog snapshot published: revision=%s rows=%s dirty=%s",
                    result.get("snapshot_revision"),
                    sum(result.get("row_counts", {}).values()),
                    result.get("dirty_after_build"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Catalog snapshot build failed; will retry")

        # External hotdeals do not share the catalog dirty-state table. Detect
        # actual HotdealPost content changes and debounce bursts from crawlers.
        try:
            fingerprint = await asyncio.to_thread(external_hotdeal_fingerprint)
            now = time.monotonic()
            if fingerprint != hotdeal_seen_fingerprint:
                hotdeal_seen_fingerprint = fingerprint
                hotdeal_changed_at = now

            should_build = not hotdeal_target.exists() or (
                fingerprint != hotdeal_published_fingerprint
                and (now - hotdeal_changed_at) >= settle_seconds
            )
            if should_build:
                result = await asyncio.to_thread(
                    build_external_hotdeal_snapshot,
                    hotdeal_target,
                )
                # Use the fingerprint observed before the copy. If source rows
                # change while copying, the next loop sees a different value
                # and schedules another build instead of missing that update.
                hotdeal_published_fingerprint = fingerprint
                logger.info(
                    "External hotdeal snapshot published: revision=%s rows=%s",
                    result.get("revision"),
                    result.get("row_count"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("External hotdeal snapshot build failed; will retry")

        if _remote_publish_enabled():
            now = time.monotonic()

            if catalog_target.exists() and now >= next_catalog_remote_attempt:
                revision = await asyncio.to_thread(_snapshot_revision, catalog_target)
                if revision is not None and revision != catalog_uploaded_revision:
                    try:
                        result = await asyncio.to_thread(
                            _upload_snapshot,
                            "catalog",
                            catalog_target,
                        )
                        catalog_uploaded_revision = revision
                        next_catalog_remote_attempt = 0.0
                        logger.info(
                            "Catalog snapshot deployed to web-api: revision=%s bytes=%s",
                            revision,
                            result.get("bytes"),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        next_catalog_remote_attempt = now + REMOTE_RETRY_SECONDS
                        logger.exception(
                            "Catalog snapshot deploy failed; retrying in %.0fs",
                            REMOTE_RETRY_SECONDS,
                        )

            if hotdeal_target.exists() and now >= next_hotdeal_remote_attempt:
                revision = await asyncio.to_thread(_snapshot_revision, hotdeal_target)
                if revision is not None and revision != hotdeal_uploaded_revision:
                    try:
                        result = await asyncio.to_thread(
                            _upload_snapshot,
                            "external-hotdeals",
                            hotdeal_target,
                        )
                        hotdeal_uploaded_revision = revision
                        next_hotdeal_remote_attempt = 0.0
                        logger.info(
                            "External hotdeal snapshot deployed to web-api: revision=%s bytes=%s",
                            revision,
                            result.get("bytes"),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        next_hotdeal_remote_attempt = now + REMOTE_RETRY_SECONDS
                        logger.exception(
                            "External hotdeal snapshot deploy failed; retrying in %.0fs",
                            REMOTE_RETRY_SECONDS,
                        )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass

    logger.info("Snapshot publisher stopped")
