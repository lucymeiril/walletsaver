"""Build the replaceable external-hotdeal SQLite read replica.

Only HotdealPost is published. User votes/reports belong to web-api's
interactions.sqlite and are deliberately excluded so replacing this file can
never erase server-side interaction data.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from urllib.parse import urlparse
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, create_engine, insert, select, text

from services.base import get_engine
from storage.models import HotdealPost, HotdealSourceSite

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXTERNAL_HOTDEAL_SNAPSHOT_PATH = (
    _PROJECT_ROOT / ".walletsavior" / "external_hotdeals.sqlite"
)
_COPY_CHUNK_SIZE = 2_000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def external_hotdeal_snapshot_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_EXTERNAL_HOTDEAL_DB", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else DEFAULT_EXTERNAL_HOTDEAL_SNAPSHOT_PATH
    ).resolve()


def source_fingerprint() -> str:
    """Return a stable content fingerprint for the local HotdealPost table."""
    table = HotdealPost.__table__
    digest = hashlib.sha256()
    engine = get_engine()
    with engine.connect() as connection:
        rows = connection.execute(select(table).order_by(table.c.id))
        for row in rows:
            # repr(tuple(...)) is sufficient here because all SQLAlchemy values
            # are deterministic scalar/JSON values from one local DB row.
            digest.update(repr(tuple(row)).encode("utf-8", errors="replace"))
            digest.update(b"\n")
    return digest.hexdigest()


def _write_snapshot(next_path: Path, revision: int) -> int:
    if next_path.exists():
        next_path.unlink()
    next_path.parent.mkdir(parents=True, exist_ok=True)

    source_table = HotdealPost.__table__
    metadata = MetaData()
    target_table = source_table.to_metadata(metadata)
    target_engine = create_engine(f"sqlite:///{next_path.as_posix()}")
    source_engine = get_engine()
    copied = 0

    try:
        metadata.create_all(target_engine)
        with source_engine.connect() as source:
            source_tx = source.begin()
            try:
                result = source.execute(select(source_table).order_by(source_table.c.id))
                with target_engine.begin() as target:
                    while True:
                        rows = result.fetchmany(_COPY_CHUNK_SIZE)
                        if not rows:
                            break
                        mappings = [dict(row._mapping) for row in rows]
                        target.execute(insert(target_table), mappings)
                        copied += len(mappings)
                    target.execute(
                        text(
                            "CREATE TABLE snapshot_meta ("
                            "id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, "
                            "built_at TEXT NOT NULL)"
                        )
                    )
                    target.execute(
                        text(
                            "INSERT INTO snapshot_meta (id, revision, built_at) "
                            "VALUES (1, :revision, :built_at)"
                        ),
                        {"revision": revision, "built_at": _utc_iso()},
                    )
                source_tx.commit()
            except Exception:
                source_tx.rollback()
                raise
    finally:
        target_engine.dispose()

    fd = os.open(str(next_path), os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return copied


def build_external_hotdeal_snapshot(
    target_path: Path | str | None = None,
) -> dict:
    """Atomically replace the external-hotdeal read replica."""
    target = (
        Path(target_path).expanduser().resolve()
        if target_path is not None
        else external_hotdeal_snapshot_path()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    next_path = target.with_suffix(target.suffix + ".next")
    # Timestamp microseconds are only publication metadata; source identity is
    # tracked separately with source_fingerprint().
    revision = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

    try:
        copied = _write_snapshot(next_path, revision)
        os.replace(next_path, target)
    except Exception:
        if next_path.exists():
            next_path.unlink()
        raise

    return {
        "path": str(target),
        "revision": revision,
        "row_count": copied,
        "fingerprint": source_fingerprint(),
    }


def upsert_approved_hotdeal(session, item: dict) -> HotdealPost:
    """Keep approved source posts outside mart Product/price/matching tables.

    A source post identity is its namespaced native key plus canonical URL;
    quote changes update that post, and stale receipts cannot overwrite it.
    Failed collections call no writer and never replace another source's rows.
    Original source captures remain in the reviewed PendingIngestion record.
    """
    url = str(item.get("source_url") or item.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Hotdeal source requires an ordinary public URL")
    title = str(item.get("title") or "").strip()
    if not title or len(title) > 500:
        raise ValueError("Hotdeal source title missing or too long")
    key = str(item.get("source_record_key") or item.get("source_native_id") or url)
    identity = hashlib.sha256((key + "\n" + url).encode()).hexdigest()
    def moment(value):
        if value is None or value == "":
            return None
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result
    fetched = moment(item.get("crawled_at") or item.get("fetched_at"))
    if fetched is None:
        raise ValueError("Hotdeal source receipt time missing")
    def money(value):
        if value is None:
            return None
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError("Hotdeal source price must be positive finite or unknown")
        return float(value)
    tags = item.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(t, str) or len(t) > 1500 for t in tags) or len(tags) > 40:
        raise ValueError("Hotdeal source tags must be bounded text facts")
    site = str(item.get("source_site") or "other")
    if site not in {s.value for s in HotdealSourceSite}:
        site = "other"  # Namespace/source label retained in key and tags.
    row = session.execute(select(HotdealPost).where(HotdealPost.hash_dedup == identity)).scalar_one_or_none()
    price, original = money(item.get("price")), money(item.get("original_price"))
    posted, expires = moment(item.get("post_date") or item.get("posted_at")), moment(item.get("expires_at"))
    if row is not None and row.fetched_at and row.fetched_at > fetched:
        return row
    if row is None:
        row = HotdealPost(hash_dedup=identity)
    row.source_site = HotdealSourceSite(site)
    row.source_native_id = key[:100]
    row.title, row.url = title, url
    row.price, row.original_price = price, original
    rate = item.get("discount_rate")
    if rate is not None and (isinstance(rate, bool) or not math.isfinite(float(rate)) or not 0 <= float(rate) <= 100):
        raise ValueError("Invalid declared hotdeal discount rate")
    row.discount_rate = rate  # Literal source percent only; UI can label price-difference arithmetic separately.
    row.posted_at, row.expires_at = posted, expires
    row.shop_name = str(item.get("shop_name") or item.get("source_community") or "")[:200]
    row.category_raw = str(item.get("category") or item.get("category_raw") or "")[:200]
    row.tags, row.fetched_at = tags, fetched
    row.is_active = item.get("is_active") is not False
    session.add(row)
    return row
