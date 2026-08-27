"""Central freshness tracking for the derived public product snapshot.

The public SQLite snapshot is a read model, not a source of truth. Any write to
models that affect public product/category/price results marks the snapshot
dirty in the same database transaction. Callers do not need to remember to
invoke a snapshot-specific hook.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from storage.models import (
    BaselinePrice,
    Category,
    DiscountHistory,
    Keyword,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    PriceHistory,
    Product,
    ProductKeyword,
    UnifiedCategory,
)

_TRACKED_MODELS = (
    Product,
    Category,
    UnifiedCategory,
    BaselinePrice,
    DiscountHistory,
    PriceHistory,
    Keyword,
    ProductKeyword,
    NormalizedCanonicalProduct,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedOfferEvent,
    NormalizedWeekBucket,
    NormalizedOfferWeekLink,
)

_INSTALLED = False
_PENDING = "_public_snapshot_dirty_pending"
_MARKED = "_public_snapshot_dirty_marked"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_state_table(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS public_snapshot_state ("
            "id INTEGER PRIMARY KEY, "
            "data_revision INTEGER NOT NULL DEFAULT 0, "
            "snapshot_revision INTEGER NOT NULL DEFAULT 0, "
            "dirty INTEGER NOT NULL DEFAULT 1, "
            "updated_at TEXT, "
            "built_at TEXT, "
            "CHECK (id = 1)"
            ")"
        )
    )


def mark_public_snapshot_dirty(connection) -> None:
    """Mark the public read model stale using the caller's transaction."""
    _ensure_state_table(connection)
    now = _utc_iso()
    connection.execute(
        text(
            "INSERT INTO public_snapshot_state "
            "(id, data_revision, snapshot_revision, dirty, updated_at) "
            "VALUES (1, 1, 0, 1, :now) "
            "ON CONFLICT(id) DO UPDATE SET "
            "data_revision = public_snapshot_state.data_revision + 1, "
            "dirty = 1, updated_at = :now"
        ),
        {"now": now},
    )


def get_snapshot_state(connection) -> dict:
    _ensure_state_table(connection)
    row = connection.execute(
        text(
            "SELECT data_revision, snapshot_revision, dirty, updated_at, built_at "
            "FROM public_snapshot_state WHERE id = 1"
        )
    ).fetchone()
    if row is None:
        return {
            "data_revision": 0,
            "snapshot_revision": 0,
            "dirty": True,
            "updated_at": None,
            "built_at": None,
        }
    return {
        "data_revision": int(row[0] or 0),
        "snapshot_revision": int(row[1] or 0),
        "dirty": bool(row[2]),
        "updated_at": row[3],
        "built_at": row[4],
    }


def mark_public_snapshot_clean(connection, *, snapshot_revision: int) -> None:
    _ensure_state_table(connection)
    now = _utc_iso()
    connection.execute(
        text(
            "INSERT INTO public_snapshot_state "
            "(id, data_revision, snapshot_revision, dirty, updated_at, built_at) "
            "VALUES (1, :revision, :revision, 0, :now, :now) "
            "ON CONFLICT(id) DO UPDATE SET "
            "snapshot_revision = :revision, "
            "dirty = CASE WHEN public_snapshot_state.data_revision > :revision THEN 1 ELSE 0 END, "
            "built_at = :now"
        ),
        {"revision": int(snapshot_revision), "now": now},
    )


def _bulk_query_affects_public(query) -> bool:
    """Return whether a legacy Query.update/delete targets a public model.

    SQLAlchemy bulk Query operations bypass Session.new/dirty/deleted, so the
    normal flush hooks below cannot see them. ``column_descriptions`` gives us
    the mapped entity for the current db-admin bulk routes. If SQLAlchemy cannot
    expose an entity, fail safe by marking the snapshot dirty rather than
    risking a stale server snapshot.
    """
    descriptions = getattr(query, "column_descriptions", None) or ()
    entities = {
        description.get("entity")
        for description in descriptions
        if isinstance(description, dict) and description.get("entity") is not None
    }
    if not entities:
        return True
    return any(entity in _TRACKED_MODELS for entity in entities)


def install_public_snapshot_tracking() -> None:
    """Install process-wide SQLAlchemy Session hooks exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Session, "before_flush")
    def _before_flush(session: Session, _flush_context, _instances) -> None:
        if session.info.get(_MARKED):
            return
        candidates = list(session.new) + list(session.dirty) + list(session.deleted)
        if any(isinstance(obj, _TRACKED_MODELS) for obj in candidates):
            session.info[_PENDING] = True

    @event.listens_for(Session, "after_flush_postexec")
    def _after_flush(session: Session, _flush_context) -> None:
        if not session.info.pop(_PENDING, False) or session.info.get(_MARKED):
            return
        mark_public_snapshot_dirty(session.connection())
        session.info[_MARKED] = True

    @event.listens_for(Session, "after_bulk_update")
    def _after_bulk_update(update_context) -> None:
        session = update_context.session
        if session.info.get(_MARKED):
            return
        if _bulk_query_affects_public(update_context.query):
            mark_public_snapshot_dirty(session.connection())
            session.info[_MARKED] = True

    @event.listens_for(Session, "after_bulk_delete")
    def _after_bulk_delete(delete_context) -> None:
        session = delete_context.session
        if session.info.get(_MARKED):
            return
        if _bulk_query_affects_public(delete_context.query):
            mark_public_snapshot_dirty(session.connection())
            session.info[_MARKED] = True

    def _clear(session: Session) -> None:
        session.info.pop(_PENDING, None)
        session.info.pop(_MARKED, None)

    event.listen(Session, "after_commit", _clear)
    event.listen(Session, "after_rollback", _clear)
