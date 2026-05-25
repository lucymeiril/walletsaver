"""
tracked_urls subscription lifecycle — crawler-FINAL §5-D.

영구 등록 URL 의 6-상태 / 5-tier 모델.
워크밴치 / 신고큐 / 수동 yaml 등록 모두 본 저장소를 거친다.

저장소: SQLite (단일 파일). 본 패키지의 다른 SQLite 와 동일 경로 정책.
디스크 IO 는 본 모듈만. crawler / API / 워크밴치는 register/list/update 호출.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional


class TrackedUrlStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    REDIRECTED = "redirected"
    DISCONTINUED = "discontinued"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    REVIEW_REQUIRED = "review_required"


class RefreshTier(str, Enum):
    HOURLY = "1h"
    SIX_HOUR = "6h"
    DAILY = "daily"
    WEEKLY = "weekly"
    PAUSED = "paused"


class RegisteredBy(str, Enum):
    WORKBENCH = "workbench"
    REPORT_QUEUE = "report_queue"
    MANUAL_YAML = "manual_yaml"


@dataclass
class TrackedUrl:
    url: str
    source_id: str
    status: str = TrackedUrlStatus.ACTIVE.value
    refresh_tier: str = RefreshTier.DAILY.value
    registered_by: str = RegisteredBy.WORKBENCH.value
    register_capture_id: Optional[str] = None
    canonical_url_hash: Optional[str] = None
    last_seen_valid_at: Optional[float] = None
    last_price_change_at: Optional[float] = None
    consecutive_no_change: int = 0
    consecutive_failures: int = 0
    is_sponsored_suspicion: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    notes: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_urls (
    url TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    refresh_tier TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    register_capture_id TEXT,
    canonical_url_hash TEXT,
    last_seen_valid_at REAL,
    last_price_change_at REAL,
    consecutive_no_change INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    is_sponsored_suspicion INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tracked_urls_source ON tracked_urls(source_id);
CREATE INDEX IF NOT EXISTS idx_tracked_urls_status ON tracked_urls(status);
CREATE INDEX IF NOT EXISTS idx_tracked_urls_tier ON tracked_urls(refresh_tier);
"""


class TrackedUrlStore:
    """SQLite-backed subscription lifecycle 저장소."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        cx = sqlite3.connect(self.db_path)
        cx.row_factory = sqlite3.Row
        return cx

    def register(self, entry: TrackedUrl) -> TrackedUrl:
        """upsert. 이미 있으면 source/status 등을 덮어쓰고 created_at 보존."""
        now = time.time()
        entry.updated_at = now
        with self._conn() as cx:
            existing = cx.execute(
                "SELECT created_at FROM tracked_urls WHERE url=?", (entry.url,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            cx.execute(
                """
                INSERT INTO tracked_urls(
                    url, source_id, status, refresh_tier, registered_by,
                    register_capture_id, canonical_url_hash,
                    last_seen_valid_at, last_price_change_at,
                    consecutive_no_change, consecutive_failures,
                    is_sponsored_suspicion, created_at, updated_at, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    source_id=excluded.source_id,
                    status=excluded.status,
                    refresh_tier=excluded.refresh_tier,
                    registered_by=excluded.registered_by,
                    register_capture_id=excluded.register_capture_id,
                    canonical_url_hash=excluded.canonical_url_hash,
                    last_seen_valid_at=excluded.last_seen_valid_at,
                    last_price_change_at=excluded.last_price_change_at,
                    consecutive_no_change=excluded.consecutive_no_change,
                    consecutive_failures=excluded.consecutive_failures,
                    is_sponsored_suspicion=excluded.is_sponsored_suspicion,
                    updated_at=excluded.updated_at,
                    notes=excluded.notes
                """,
                (
                    entry.url, entry.source_id, entry.status, entry.refresh_tier,
                    entry.registered_by, entry.register_capture_id,
                    entry.canonical_url_hash, entry.last_seen_valid_at,
                    entry.last_price_change_at, entry.consecutive_no_change,
                    entry.consecutive_failures, int(entry.is_sponsored_suspicion),
                    created_at, entry.updated_at, entry.notes,
                ),
            )
            cx.commit()
        entry.created_at = created_at
        return entry

    def get(self, url: str) -> Optional[TrackedUrl]:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM tracked_urls WHERE url=?", (url,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def list(
        self,
        *,
        source_id: Optional[str] = None,
        status: Optional[str] = None,
        refresh_tier: Optional[str] = None,
    ) -> list[TrackedUrl]:
        sql = "SELECT * FROM tracked_urls WHERE 1=1"
        args: list[Any] = []
        if source_id:
            sql += " AND source_id=?"
            args.append(source_id)
        if status:
            sql += " AND status=?"
            args.append(status)
        if refresh_tier:
            sql += " AND refresh_tier=?"
            args.append(refresh_tier)
        sql += " ORDER BY updated_at DESC"
        with self._conn() as cx:
            rows = cx.execute(sql, args).fetchall()
        return [_row_to_entry(r) for r in rows]

    def update_status(self, url: str, status: TrackedUrlStatus | str) -> bool:
        s = status.value if isinstance(status, TrackedUrlStatus) else status
        with self._conn() as cx:
            cur = cx.execute(
                "UPDATE tracked_urls SET status=?, updated_at=? WHERE url=?",
                (s, time.time(), url),
            )
            cx.commit()
            return cur.rowcount > 0

    def update_tier(self, url: str, tier: RefreshTier | str) -> bool:
        t = tier.value if isinstance(tier, RefreshTier) else tier
        with self._conn() as cx:
            cur = cx.execute(
                "UPDATE tracked_urls SET refresh_tier=?, updated_at=? WHERE url=?",
                (t, time.time(), url),
            )
            cx.commit()
            return cur.rowcount > 0

    def remove(self, url: str) -> bool:
        """삭제는 *운영자 명시* 호출만. 자동 stale 후 자동 삭제 금지 (FINAL §5-D)."""
        with self._conn() as cx:
            cur = cx.execute("DELETE FROM tracked_urls WHERE url=?", (url,))
            cx.commit()
            return cur.rowcount > 0


def _row_to_entry(row: sqlite3.Row) -> TrackedUrl:
    return TrackedUrl(
        url=row["url"],
        source_id=row["source_id"],
        status=row["status"],
        refresh_tier=row["refresh_tier"],
        registered_by=row["registered_by"],
        register_capture_id=row["register_capture_id"],
        canonical_url_hash=row["canonical_url_hash"],
        last_seen_valid_at=row["last_seen_valid_at"],
        last_price_change_at=row["last_price_change_at"],
        consecutive_no_change=int(row["consecutive_no_change"]),
        consecutive_failures=int(row["consecutive_failures"]),
        is_sponsored_suspicion=bool(row["is_sponsored_suspicion"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        notes=row["notes"] or "",
    )


# ── 자동 강등 규칙 (FINAL §5-D) ───────────────────────────────────
# 운영자 등록 URL 도 검토 큐에 들어가지만 자동 삭제 금지 — *표시* 까지만.

@dataclass
class DemotionRule:
    """auto_demote() 가 적용할 규칙. now 는 호출자가 주입 (테스트 가능)."""
    no_change_days_to_weekly: int = 30
    fail_days_to_stale: int = 14


def auto_demote(
    store: TrackedUrlStore,
    *,
    now: Optional[float] = None,
    rule: Optional[DemotionRule] = None,
) -> dict[str, int]:
    """자동 강등 1회 패스 — 카운터를 보고 status/tier 만 갱신.

    삭제 안 한다 (FINAL §5-D: '자동 삭제 X — 운영자 결정').
    호출자가 cron / scheduler 에서 주기 호출.
    """
    rule = rule or DemotionRule()
    now = now or time.time()
    demoted_to_weekly = 0
    moved_to_stale = 0
    for e in store.list():
        # 30일 가격 변화 없음 → weekly
        if e.last_price_change_at is not None:
            days_no_change = (now - e.last_price_change_at) / 86400
            if days_no_change >= rule.no_change_days_to_weekly and e.refresh_tier in (
                RefreshTier.HOURLY.value, RefreshTier.SIX_HOUR.value, RefreshTier.DAILY.value
            ):
                store.update_tier(e.url, RefreshTier.WEEKLY)
                demoted_to_weekly += 1
        # 14일 연속 실패 → stale (표시만)
        if e.consecutive_failures >= rule.fail_days_to_stale and e.status == TrackedUrlStatus.ACTIVE.value:
            store.update_status(e.url, TrackedUrlStatus.STALE)
            moved_to_stale += 1
    return {"demoted_to_weekly": demoted_to_weekly, "moved_to_stale": moved_to_stale}
