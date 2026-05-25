"""weekly_diff.py — 주간 크롤 누적 비교 서비스.

공개 API:
    compute_weekly_diff(session, mart, since, until) -> WeeklyDiffReport
        previous window vs current window 의 raw_crawl_records 비교 후 리포트 반환.

    persist_alerts(session, report) -> int
        사라진 SKU를 alert_disappeared_skus 테이블에 삽입. 이미 open 상태인 alert는 중복 삽입하지 않음.
        삽입된 신규 row 수를 반환한다.

설계:
    - raw_crawl_records 쿼리는 sqlalchemy.text() 기반 raw SQL 사용
      (ai-admin 패키지 의존성 없이 동작)
    - alert_disappeared_skus 는 로컬 ORM 모델(AlertSkuBase / AlertDisappearedSkuModel)로 관리
    - 멱등 보장: 같은 mart+source_record_key 의 open alert(resolved_at IS NULL) 중복 삽입 방지
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, Index, text, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 로컬 ORM 모델 (weekly diff 전용 Base — db-admin Base와 독립적으로 사용 가능)
# ─────────────────────────────────────────────────────────────────────────────


class AlertSkuBase(DeclarativeBase):
    """weekly_diff 전용 declarative base.

    테스트에서는 이 base를 사용해 인메모리 SQLite에 테이블을 생성한다.
    운영에서는 db-admin alembic 마이그레이션으로 별도 생성됨.
    """


class AlertDisappearedSkuModel(AlertSkuBase):
    """alert_disappeared_skus ORM 모델."""

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


# ─────────────────────────────────────────────────────────────────────────────
# 리포트 데이터 클래스
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WeeklyDiffReport:
    """주간 diff 결과 리포트."""

    mart: str
    previous_window: tuple[datetime, datetime]  # (since_prev, until_prev)
    current_window: tuple[datetime, datetime]   # (since, until)

    # source_record_key 기준 분류
    disappeared: list[dict] = field(default_factory=list)
    """이전 주에만 있던 SKU. 필드: source_record_key, last_seen_title, last_seen_price, last_captured_at"""

    new_skus: list[dict] = field(default_factory=list)
    """이번 주에 처음 등장한 SKU. 필드: source_record_key, first_seen_title, first_seen_price, first_captured_at"""

    retained_count: int = 0
    """양쪽 window 모두에 존재한 SKU 수."""

    price_changes: list[dict] = field(default_factory=list)
    """가격이 변동된 SKU 목록. 필드: source_record_key, old_price, new_price, pct_change"""

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


# ─────────────────────────────────────────────────────────────────────────────
# 핵심 서비스 함수
# ─────────────────────────────────────────────────────────────────────────────


def _query_window(session: Session, mart: str, since: datetime, until: datetime) -> dict[str, dict]:
    """지정 기간에 크롤된 raw_crawl_records를 source_record_key → 레코드 dict 로 반환.

    같은 source_record_key가 여러 개 있으면 가장 최근 crawled_at 기준으로 하나만 유지.
    source_record_key가 NULL인 레코드는 제외.
    """
    sql = text(
        """
        SELECT
            r.source_record_key,
            r.raw_title,
            r.raw_price,
            r.crawled_at,
            r.source_name
        FROM raw_crawl_records r
        WHERE r.source_name = :mart
          AND r.source_record_key IS NOT NULL
          AND r.crawled_at >= :since
          AND r.crawled_at < :until
        ORDER BY r.crawled_at DESC
        """
    )
    rows = session.execute(sql, {"mart": mart, "since": since, "until": until}).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        key = row[0]
        if key not in result:
            result[key] = {
                "source_record_key": key,
                "raw_title": row[1],
                "raw_price": row[2],
                "crawled_at": row[3],
                "source_name": row[4],
            }
    return result


def compute_weekly_diff(
    session: Session,
    mart: str,
    since: datetime,
    until: datetime,
) -> WeeklyDiffReport:
    """previous window vs current window 비교 후 WeeklyDiffReport 반환.

    Args:
        session:  SQLAlchemy Session. raw_crawl_records 테이블에 접근 가능해야 한다.
        mart:     마트 식별자 (source_name 값과 동일). e.g. "emart"
        since:    current window 시작 (inclusive).
        until:    current window 종료 (exclusive). previous window = [since - duration, since).
    """
    duration = until - since
    prev_since = since - duration
    prev_until = since

    prev_window = _query_window(session, mart, prev_since, prev_until)
    curr_window = _query_window(session, mart, since, until)

    prev_keys = set(prev_window)
    curr_keys = set(curr_window)

    # 사라진 SKU
    disappeared_keys = prev_keys - curr_keys
    disappeared = []
    for key in sorted(disappeared_keys):
        rec = prev_window[key]
        disappeared.append(
            {
                "source_record_key": key,
                "last_seen_title": rec["raw_title"],
                "last_seen_price": rec["raw_price"],
                "last_captured_at": _iso(rec["crawled_at"]),
            }
        )

    # 신규 SKU
    new_keys = curr_keys - prev_keys
    new_skus = []
    for key in sorted(new_keys):
        rec = curr_window[key]
        new_skus.append(
            {
                "source_record_key": key,
                "first_seen_title": rec["raw_title"],
                "first_seen_price": rec["raw_price"],
                "first_captured_at": _iso(rec["crawled_at"]),
            }
        )

    # 유지 SKU & 가격 변동
    retained_keys = prev_keys & curr_keys
    retained_count = len(retained_keys)
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
        retained_count=retained_count,
        price_changes=price_changes,
    )

    logger.info(
        "[weekly_diff] mart=%s disappeared=%d new=%d retained=%d price_changed=%d",
        mart,
        len(disappeared),
        len(new_skus),
        retained_count,
        len(price_changes),
    )
    return report


def persist_alerts(session: Session, report: WeeklyDiffReport) -> int:
    """사라진 SKU를 alert_disappeared_skus에 삽입. 멱등 보장.

    이미 open 상태(resolved_at IS NULL)인 동일 mart+key alert는 중복 삽입하지 않는다.
    Returns:
        삽입된 신규 row 수.
    """
    if not report.disappeared:
        return 0

    # 현재 open alert 키 목록 조회 (중복 방지용)
    existing_open: set[str] = set()
    rows = session.execute(
        select(AlertDisappearedSkuModel.source_record_key).where(
            AlertDisappearedSkuModel.mart == report.mart,
            AlertDisappearedSkuModel.resolved_at.is_(None),
        )
    ).fetchall()
    for row in rows:
        existing_open.add(row[0])

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC
    inserted = 0
    for item in report.disappeared:
        key = item["source_record_key"]
        if key in existing_open:
            logger.debug("[weekly_diff] skip duplicate open alert mart=%s key=%s", report.mart, key)
            continue

        captured_at = item.get("last_captured_at")
        if isinstance(captured_at, str):
            try:
                captured_at = datetime.fromisoformat(captured_at)
            except ValueError:
                captured_at = None

        alert = AlertDisappearedSkuModel(
            mart=report.mart,
            source_record_key=key,
            last_seen_title=item.get("last_seen_title"),
            last_seen_price=item.get("last_seen_price"),
            last_captured_at=captured_at,
            detected_at=now,
            resolved_at=None,
        )
        session.add(alert)
        inserted += 1

    if inserted:
        session.flush()

    logger.info("[weekly_diff] persist_alerts mart=%s inserted=%d", report.mart, inserted)
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)
