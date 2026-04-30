"""DB integrity checks for the operational integrity dashboard.

Read-only diagnostics over the existing schema. Surfaces FK/orphan/zombie
data, expired discounts, source-side ingestion failures, crawl failures,
and placeholders for projection/DLQ checks (which are not yet wired up
in this codebase).

No destructive auto-repair runs from these functions. Caller-driven
recheck/repair hooks are exposed separately so the dashboard can
explicitly request a refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from storage.models import (
    Product,
    Category,
    BaselinePrice,
    DiscountHistory,
    HotdealPrice,
    CrawlLog,
    CrawlStatus,
    Keyword,
    ProductKeyword,
    PendingIngestion,
    IngestionStatus,
)

logger = logging.getLogger(__name__)


# ── Severity classification ────────────────────────────────────────────────
SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITY_NOT_CONFIGURED = "not_configured"


def _severity_for_count(count: int, *, warn_at: int = 1, critical_at: int = 100) -> str:
    if count <= 0:
        return SEVERITY_OK
    if count >= critical_at:
        return SEVERITY_CRITICAL
    if count >= warn_at:
        return SEVERITY_WARNING
    return SEVERITY_OK


# ── Individual checks ─────────────────────────────────────────────────────


def check_products_without_category(session: Session) -> dict:
    """Products missing a category_id (FK either NULL or pointing to a
    category that no longer exists)."""
    null_count = session.query(func.count(Product.id)).filter(
        Product.category_id.is_(None)
    ).scalar() or 0

    # Orphan: category_id set but no matching Category row
    orphan_q = (
        session.query(Product.id, Product.category_id)
        .outerjoin(Category, Product.category_id == Category.id)
        .filter(Product.category_id.isnot(None))
        .filter(Category.id.is_(None))
    )
    orphan_rows = orphan_q.limit(20).all()
    orphan_count = orphan_q.with_entities(func.count(Product.id)).scalar() or 0

    total = null_count + orphan_count
    return {
        "name": "products_without_category",
        "severity": _severity_for_count(total),
        "count": total,
        "null_category_count": null_count,
        "orphan_category_count": orphan_count,
        "samples": [{"product_id": pid, "category_id": cid} for pid, cid in orphan_rows],
    }


def check_invalid_product_prices(session: Session) -> dict:
    """Price rows with zero/negative values across all price tables."""
    counts: dict[str, int] = {}
    samples: list[dict] = []
    for label, Model in (
        ("baseline_prices", BaselinePrice),
        ("discount_history", DiscountHistory),
        ("hotdeal_prices", HotdealPrice),
    ):
        q = session.query(Model).filter(
            or_(Model.price.is_(None), Model.price <= 0)
        )
        cnt = q.with_entities(func.count(Model.id)).scalar() or 0
        counts[label] = cnt
        for row in q.limit(5).all():
            samples.append({
                "table": label,
                "id": row.id,
                "product_id": row.product_id,
                "price": row.price,
            })

    total = sum(counts.values())
    return {
        "name": "invalid_product_prices",
        "severity": _severity_for_count(total),
        "count": total,
        "by_table": counts,
        "samples": samples[:20],
    }


def check_orphan_product_keywords(session: Session) -> dict:
    """ProductKeyword rows where Product or Keyword no longer exists.

    The FK has ON DELETE CASCADE, but the SQLite default omits FK
    enforcement and historical data may still contain orphans.
    """
    missing_product_q = (
        session.query(ProductKeyword.id, ProductKeyword.product_id)
        .outerjoin(Product, ProductKeyword.product_id == Product.id)
        .filter(Product.id.is_(None))
    )
    missing_keyword_q = (
        session.query(ProductKeyword.id, ProductKeyword.keyword_id)
        .outerjoin(Keyword, ProductKeyword.keyword_id == Keyword.id)
        .filter(Keyword.id.is_(None))
    )

    mp_count = missing_product_q.with_entities(func.count(ProductKeyword.id)).scalar() or 0
    mk_count = missing_keyword_q.with_entities(func.count(ProductKeyword.id)).scalar() or 0

    samples = [
        {"product_keyword_id": pk_id, "missing": "product", "ref_id": ref}
        for pk_id, ref in missing_product_q.limit(10).all()
    ] + [
        {"product_keyword_id": pk_id, "missing": "keyword", "ref_id": ref}
        for pk_id, ref in missing_keyword_q.limit(10).all()
    ]

    total = mp_count + mk_count
    return {
        "name": "orphan_product_keywords",
        "severity": _severity_for_count(total),
        "count": total,
        "missing_product": mp_count,
        "missing_keyword": mk_count,
        "samples": samples,
    }


def check_zombie_price_rows(session: Session) -> dict:
    """Price rows pointing to a product that no longer exists."""
    counts: dict[str, int] = {}
    samples: list[dict] = []
    for label, Model in (
        ("baseline_prices", BaselinePrice),
        ("discount_history", DiscountHistory),
        ("hotdeal_prices", HotdealPrice),
    ):
        q = (
            session.query(Model.id, Model.product_id)
            .outerjoin(Product, Model.product_id == Product.id)
            .filter(Product.id.is_(None))
        )
        cnt = q.with_entities(func.count(Model.id)).scalar() or 0
        counts[label] = cnt
        for row_id, prod_id in q.limit(5).all():
            samples.append({"table": label, "id": row_id, "product_id": prod_id})

    total = sum(counts.values())
    return {
        "name": "zombie_price_rows",
        "severity": _severity_for_count(total),
        "count": total,
        "by_table": counts,
        "samples": samples[:20],
    }


def check_expired_discounts(session: Session, *, now: datetime | None = None) -> dict:
    """DiscountHistory rows where valid_to is in the past but the row
    is still present (eligible for archival or repair)."""
    now = now or datetime.utcnow()
    q = session.query(DiscountHistory).filter(
        and_(DiscountHistory.valid_to.isnot(None), DiscountHistory.valid_to < now)
    )
    cnt = q.with_entities(func.count(DiscountHistory.id)).scalar() or 0
    samples = [
        {
            "id": r.id,
            "product_id": r.product_id,
            "source": r.source,
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        }
        for r in q.order_by(DiscountHistory.valid_to.asc()).limit(10).all()
    ]

    # Expired-but-fresh: valid_to in the past yet crawled_at is recent.
    # Indicates likely stale-source bug (mart marketing window stale).
    recent_threshold = now - timedelta(days=7)
    fresh_expired = q.filter(DiscountHistory.crawled_at >= recent_threshold)
    fresh_cnt = fresh_expired.with_entities(func.count(DiscountHistory.id)).scalar() or 0

    return {
        "name": "expired_discounts",
        "severity": _severity_for_count(cnt, warn_at=1, critical_at=500),
        "count": cnt,
        "recently_crawled_but_expired": fresh_cnt,
        "samples": samples,
    }


def check_pending_ingestion_failures(session: Session) -> dict:
    """Summary of PendingIngestion entries by failure-relevant status."""
    rows = (
        session.query(PendingIngestion.status, func.count(PendingIngestion.id))
        .group_by(PendingIngestion.status)
        .all()
    )
    by_status: dict[str, int] = {}
    for status, cnt in rows:
        key = status.value if hasattr(status, "value") else str(status)
        by_status[key] = int(cnt)

    rejected = by_status.get(IngestionStatus.REJECTED.value, 0)
    partial = by_status.get(IngestionStatus.PARTIAL.value, 0)
    pending = by_status.get(IngestionStatus.PENDING.value, 0)

    # "Failed" insertion = items_count > 0 but quality_score is null/low
    # AND status still pending — proxy for source-side insertion failures.
    suspicious_q = session.query(PendingIngestion).filter(
        and_(
            PendingIngestion.status == IngestionStatus.PENDING,
            PendingIngestion.errors_json.isnot(None),
        )
    )
    suspicious = suspicious_q.with_entities(func.count(PendingIngestion.id)).scalar() or 0

    failure_total = rejected + partial + suspicious
    return {
        "name": "pending_ingestion_failures",
        "severity": _severity_for_count(failure_total),
        "count": failure_total,
        "by_status": by_status,
        "rejected": rejected,
        "partial": partial,
        "pending_with_errors": suspicious,
        "pending_total": pending,
    }


def check_crawl_log_failures(session: Session, *, window_hours: int = 24) -> dict:
    """Crawl failures over the last `window_hours`."""
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    base = session.query(CrawlLog).filter(CrawlLog.started_at >= cutoff)
    total = base.with_entities(func.count(CrawlLog.id)).scalar() or 0
    failed = base.filter(CrawlLog.status == CrawlStatus.FAILED).with_entities(
        func.count(CrawlLog.id)
    ).scalar() or 0
    partial = base.filter(CrawlLog.status == CrawlStatus.PARTIAL).with_entities(
        func.count(CrawlLog.id)
    ).scalar() or 0

    by_crawler = (
        base.filter(CrawlLog.status == CrawlStatus.FAILED)
        .with_entities(CrawlLog.crawler_name, func.count(CrawlLog.id))
        .group_by(CrawlLog.crawler_name)
        .all()
    )
    by_crawler_map = {name: int(cnt) for name, cnt in by_crawler}

    return {
        "name": "crawl_log_failures",
        "severity": _severity_for_count(failed, warn_at=1, critical_at=20),
        "count": failed,
        "window_hours": window_hours,
        "total_runs": total,
        "failed": failed,
        "partial": partial,
        "by_crawler": by_crawler_map,
    }


def check_backup_status(database_url: str | None = None) -> dict:
    """Most-recent backup metadata for ops visibility."""
    try:
        from services.backup import list_backups
        backups = list_backups()
    except Exception as e:
        logger.warning("integrity: backup status unavailable — %s", e)
        return {
            "name": "backup_status",
            "severity": SEVERITY_WARNING,
            "message": f"backup metadata unavailable: {e}",
            "latest": None,
            "count": 0,
        }

    latest = backups[0] if backups else None
    severity = SEVERITY_OK
    if not latest:
        severity = SEVERITY_WARNING
    else:
        try:
            created = datetime.fromisoformat(latest["created_at"])
            if datetime.utcnow() - created > timedelta(days=2):
                severity = SEVERITY_WARNING
        except Exception:
            severity = SEVERITY_WARNING

    return {
        "name": "backup_status",
        "severity": severity,
        "count": len(backups),
        "latest": latest,
    }


def check_projection_health() -> dict:
    """Placeholder: read-side projections / materialized views are not
    yet wired into this service. Surfaced as `not_configured` instead of
    silently `ok` so the dashboard makes the gap visible."""
    return {
        "name": "projection_health",
        "severity": SEVERITY_NOT_CONFIGURED,
        "count": 0,
        "message": "projection registry not configured",
    }


def check_dlq_summary() -> dict:
    """Placeholder: dead-letter queue is not yet wired in. Returned as
    `not_configured` so dashboards don't claim healthy state."""
    return {
        "name": "dlq_summary",
        "severity": SEVERITY_NOT_CONFIGURED,
        "count": 0,
        "message": "DLQ backend not configured",
    }


# ── Aggregate report ──────────────────────────────────────────────────────


_SEVERITY_RANK = {
    SEVERITY_OK: 0,
    SEVERITY_NOT_CONFIGURED: 1,
    SEVERITY_WARNING: 2,
    SEVERITY_CRITICAL: 3,
}


def _overall_severity(checks: list[dict]) -> str:
    worst = SEVERITY_OK
    for c in checks:
        sev = c.get("severity", SEVERITY_OK)
        if _SEVERITY_RANK.get(sev, 0) > _SEVERITY_RANK.get(worst, 0):
            worst = sev
    return worst


def scan_integrity(session: Session, *, database_url: str | None = None) -> dict:
    """Run the full integrity scan. Read-only — safe to call on demand."""
    checks: list[dict] = [
        check_products_without_category(session),
        check_invalid_product_prices(session),
        check_orphan_product_keywords(session),
        check_zombie_price_rows(session),
        check_expired_discounts(session),
        check_pending_ingestion_failures(session),
        check_crawl_log_failures(session),
        check_backup_status(database_url),
        check_projection_health(),
        check_dlq_summary(),
    ]

    issue_total = sum(int(c.get("count", 0)) for c in checks
                      if c.get("severity") not in (SEVERITY_OK, SEVERITY_NOT_CONFIGURED))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "overall_severity": _overall_severity(checks),
        "issue_total": issue_total,
        "checks": checks,
    }
