"""Normalize existing MatchingEntry rows to the current match-key contract.

This migration is intentionally explicit instead of running at application
startup. Key collisions can reveal old duplicate knowledge, so operators should
preview the report before applying it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.match_key import NO_BRAND_SENTINEL, build_match_key
from storage.models import MatchingEntry

_SOURCE_TRUST = {
    "crawler-auto": 0,
    "rd8_c3_seed": 1,
    "external-ai": 2,
    "human": 3,
}


@dataclass
class CollisionSample:
    canonical_key: str
    kept_id: int
    kept_source: str
    removed_ids: list[int]
    removed_sources: list[str]


@dataclass
class MatchingKeyMigrationReport:
    dry_run: bool
    total_rows: int = 0
    canonicalizable_rows: int = 0
    unchanged_keys: int = 0
    key_updates: int = 0
    brand_sentinel_fills: int = 0
    collision_groups: int = 0
    duplicates_removed: int = 0
    skipped_missing_name: int = 0
    collision_samples: list[CollisionSample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["collision_samples"] = [asdict(sample) for sample in self.collision_samples]
        return payload


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _rank(entry: MatchingEntry) -> tuple[int, float, int, float, int]:
    """Higher trust wins, then confidence, usage, recency, and stable id."""
    return (
        _SOURCE_TRUST.get(entry.source, -1),
        float(entry.confidence or 0.0),
        int(entry.hit_count or 0),
        _timestamp(entry.updated_at or entry.created_at),
        int(entry.id or 0),
    )


def _canonical_key(entry: MatchingEntry) -> str | None:
    name = (entry.name_core or "").strip()
    if not name:
        return None
    return build_match_key(entry.brand, name, entry.pack_qty, entry.pack_unit)


def _latest_datetime(values: list[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    if not present:
        return None

    def normalized(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    return max(present, key=lambda value: normalized(value))


def normalize_matching_keys(
    session: Session,
    *,
    dry_run: bool = True,
    sample_limit: int = 30,
) -> MatchingKeyMigrationReport:
    """Preview or apply canonical MatchingEntry key normalization.

    Multiple legacy rows may collapse to one canonical key. The survivor is
    chosen with the same intent as import conflict handling: human knowledge
    outranks external AI, which outranks seeded/automatic data. Only usage
    metadata is merged across duplicates; semantic classification fields always
    come from the winning row.
    """
    entries = session.query(MatchingEntry).order_by(MatchingEntry.id.asc()).all()
    report = MatchingKeyMigrationReport(dry_run=dry_run, total_rows=len(entries))

    groups: dict[str, list[MatchingEntry]] = {}
    for entry in entries:
        key = _canonical_key(entry)
        if key is None:
            report.skipped_missing_name += 1
            continue
        report.canonicalizable_rows += 1
        groups.setdefault(key, []).append(entry)

    winners: list[tuple[str, MatchingEntry, list[MatchingEntry]]] = []
    for canonical_key, group in groups.items():
        winner = max(group, key=_rank)
        losers = [entry for entry in group if entry.id != winner.id]
        winners.append((canonical_key, winner, losers))

        if len(group) > 1:
            report.collision_groups += 1
            report.duplicates_removed += len(losers)
            if len(report.collision_samples) < sample_limit:
                report.collision_samples.append(
                    CollisionSample(
                        canonical_key=canonical_key,
                        kept_id=winner.id,
                        kept_source=winner.source,
                        removed_ids=[entry.id for entry in losers],
                        removed_sources=[entry.source for entry in losers],
                    )
                )

        if winner.match_key == canonical_key:
            report.unchanged_keys += 1
        else:
            report.key_updates += 1
        if not (winner.brand or "").strip():
            report.brand_sentinel_fills += 1

    if dry_run:
        return report

    # Delete colliding losers first so their legacy/current UNIQUE match_key
    # values cannot block a winner's canonical key update.
    for _canonical_key, _winner, losers in winners:
        for loser in losers:
            session.delete(loser)
    session.flush()

    for canonical_key, winner, losers in winners:
        all_rows = [winner, *losers]
        winner.match_key = canonical_key
        if not (winner.brand or "").strip():
            winner.brand = NO_BRAND_SENTINEL
        winner.hit_count = sum(int(entry.hit_count or 0) for entry in all_rows)
        winner.last_used_at = _latest_datetime([entry.last_used_at for entry in all_rows])
    session.flush()

    try:
        from services.matching_lookup import invalidate

        invalidate()
    except Exception:
        pass

    return report
