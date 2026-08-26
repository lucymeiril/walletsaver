"""주간 마트 상품 변화 비교 서비스.

현재 정본 경로인 db-admin ``discount_history`` + ``products``는 읽기 전용 입력이다.
사라진 SKU alert는 crawler-admin 소유의 별도 SQLite 상태 DB에 저장한다.
폐기된 내부 ``raw_crawl_records`` 테이블에는 의존하지 않는다.

공개 API:
    compute_weekly_diff(session, mart, since, until) -> WeeklyDiffReport
    create_weekly_alert_engine(db_path) -> Engine
    persist_alerts(session, report) -> int
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)


class AlertSkuBase(DeclarativeBase):
    """crawler-admin weekly alert 상태 DB metadata."""


class AlertDisappearedSkuModel(AlertSkuBase):
    __tablename__ = "alert_disappeared_skus"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mart: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_alert_sku_mart_key", "mart", "source_record_key"),
        Index("ix_alert_sku_detected", "detected_at"),
        Index("ix_alert_sku_resolved", "resolved_at"),
    )


def create_weekly_alert_engine(db_path: str | Path) -> Engine:
    """Create the crawler-owned SQLite engine used only for weekly alert state."""
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"timeout": 30, "check_same_thread": False},
        pool_pre_ping=True,
    )
    AlertSkuBase.metadata.create_all(engine, checkfirst=True)
    return engine


@dataclass
class WeeklyDiffReport:
    mart: str
    previous_window: tuple[datetime, datetime]
    current_window: tuple[datetime, datetime]
    disappeared: list[dict] = field(default_factory=list)
    new_skus: list[dict] = field(default_factory=list)
    retained_count: int = 0
    price_changes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mart": self.mart,
            "previous_window": {
                "since": self.previous_window[0].isoformat(),
                "until": self.previous_window[1].isoformat(),
            },
            "current_window": {
                "since": self.current_window[0].isoformat(),
                "until": self.current_window[1].isoformat(),
            },
            "disappeared_count": len(self.disappeared),
            "new_skus_count": len(self.new_skus),
            "retained_count": self.retained_count,
            "price_changes_count": len(self.price_changes),
            "disappeared": self.disappeared,
            "new_skus": self.new_skus,
            "price_changes": self.price_changes,
        }


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _stable_source_key(
    *,
    raw_data: dict,
    mart_native_code,
    canon_hash,
    product_id,
) -> str:
    observation = (
        raw_data.get("price_observation")
        if isinstance(raw_data.get("price_observation"), dict)
        else {}
    )
    key = (
        raw_data.get("source_record_key")
        or observation.get("source_record_key")
        or mart_native_code
        or canon_hash
    )
    if key not in (None, ""):
        return str(key)
    # Product id is stable across weeks once MatchingEntry reuse is working and
    # is a safer fallback than dropping a row from weekly comparison entirely.
    return f"product:{product_id}"


def _query_window(
    session: Session,
    mart: str,
    since: datetime,
    until: datetime,
) -> dict[str, dict]:
    """Return the latest observation per stable source/product key in a window."""
    rows = session.execute(
        text(
            "SELECT d.product_id, d.price, d.crawled_at, d.raw_data, "
            "p.name, p.display_name, p.mart_native_code, p.canon_hash "
            "FROM discount_history d "
            "JOIN products p ON p.id = d.product_id "
            "WHERE d.source = :mart "
            "AND d.crawled_at >= :since AND d.crawled_at < :until "
            "ORDER BY d.crawled_at DESC, d.id DESC"
        ),
        {"mart": mart, "since": since, "until": until},
    ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        product_id, price, crawled_at, raw_value, name, display_name, mart_native_code, canon_hash = row
        raw_data = _json_dict(raw_value)
        key = _stable_source_key(
            raw_data=raw_data,
            mart_native_code=mart_native_code,
            canon_hash=canon_hash,
            product_id=product_id,
        )
        if key in result:
            continue
        result[key] = {
            "source_record_key": key,
            "raw_title": display_name or name,
            "raw_price": price,
            "crawled_at": crawled_at,
            "source_name": mart,
            "product_id": product_id,
        }
    return result


def compute_weekly_diff(
    session: Session,
    mart: str,
    since: datetime,
    until: datetime,
) -> WeeklyDiffReport:
    duration = until - since
    prev_since = since - duration
    prev_until = since

    prev_window = _query_window(session, mart, prev_since, prev_until)
    curr_window = _query_window(session, mart, since, until)

    prev_keys = set(prev_window)
    curr_keys = set(curr_window)

    disappeared = []
    for key in sorted(prev_keys - curr_keys):
        rec = prev_window[key]
        disappeared.append(
            {
                "source_record_key": key,
                "last_seen_title": rec["raw_title"],
                "last_seen_price": rec["raw_price"],
                "last_captured_at": _iso(rec["crawled_at"]),
            }
        )

    new_skus = []
    for key in sorted(curr_keys - prev_keys):
        rec = curr_window[key]
        new_skus.append(
            {
                "source_record_key": key,
                "first_seen_title": rec["raw_title"],
                "first_seen_price": rec["raw_price"],
                "first_captured_at": _iso(rec["crawled_at"]),
            }
        )

    retained_keys = prev_keys & curr_keys
    price_changes = []
    for key in sorted(retained_keys):
        old_price = prev_window[key]["raw_price"]
        new_price = curr_window[key]["raw_price"]
        if old_price is not None and new_price is not None and old_price != new_price:
            pct = round((new_price - old_price) / old_price * 100, 2) if old_price else None
            price_changes.append(
                {
                    "source_record_key": key,
                    "old_price": old_price,
                    "new_price": new_price,
                    "pct_change": pct,
                }
            )

    report = WeeklyDiffReport(
        mart=mart,
        previous_window=(prev_since, prev_until),
        current_window=(since, until),
        disappeared=disappeared,
        new_skus=new_skus,
        retained_count=len(retained_keys),
        price_changes=price_changes,
    )
    logger.info(
        "[weekly_diff] mart=%s disappeared=%d new=%d retained=%d price_changed=%d",
        mart,
        len(disappeared),
        len(new_skus),
        report.retained_count,
        len(price_changes),
    )
    return report


def persist_alerts(session: Session, report: WeeklyDiffReport) -> int:
    """Persist disappeared SKU alerts in crawler-owned state; open alerts are idempotent."""
    if not report.disappeared:
        return 0

    existing_open = {
        row[0]
        for row in session.execute(
            select(AlertDisappearedSkuModel.source_record_key).where(
                AlertDisappearedSkuModel.mart == report.mart,
                AlertDisappearedSkuModel.resolved_at.is_(None),
            )
        ).fetchall()
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    inserted = 0
    for item in report.disappeared:
        key = item["source_record_key"]
        if key in existing_open:
            continue
        captured_at = item.get("last_captured_at")
        if isinstance(captured_at, str):
            try:
                captured_at = datetime.fromisoformat(captured_at)
            except ValueError:
                captured_at = None
        session.add(
            AlertDisappearedSkuModel(
                mart=report.mart,
                source_record_key=key,
                last_seen_title=item.get("last_seen_title"),
                last_seen_price=item.get("last_seen_price"),
                last_captured_at=captured_at,
                detected_at=now,
                resolved_at=None,
            )
        )
        inserted += 1

    if inserted:
        session.flush()
    return inserted


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)
