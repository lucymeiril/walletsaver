"""대시보드 전용 API — 요약 카드, 긴급 알림, 신선도, 품질 점수"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, or_, literal

from services.base import get_session
from api.auth import require_viewer
from storage.models import (
    Product,
    BaselinePrice,
    DiscountHistory,
    HotdealPrice,
    Category,
    Keyword,
    CrawlLog,
    CrawlStatus,
    UnifiedCategory,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedSourceListing,
    PendingIngestion,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _utc_iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc)).isoformat()


def _normalized_dashboard_stats(session, now, total_products):
    """Admin graph statistics, not public projection or checkout eligibility."""
    active_products = session.scalar(select(func.count()).select_from(
        NormalizedCanonicalProduct).where(NormalizedCanonicalProduct.is_active.is_(True))) or 0
    total_offers = session.scalar(select(func.count()).select_from(NormalizedOfferEvent)) or 0
    states = dict(session.execute(select(NormalizedOfferEvent.offer_state, func.count()).group_by(
        NormalizedOfferEvent.offer_state)).all())
    last_observation = session.scalar(select(func.max(NormalizedOfferEvent.crawled_at)))
    last_crawl = session.scalar(select(func.max(CrawlLog.started_at)))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    observed_today = session.scalar(select(func.count()).select_from(NormalizedOfferEvent).where(
        NormalizedOfferEvent.crawled_at >= today, NormalizedOfferEvent.crawled_at <= now)) or 0
    source_rows = session.execute(select(NormalizedSourceListing.source_name,
        func.max(NormalizedOfferEvent.crawled_at), func.count(NormalizedOfferEvent.public_offer_event_id))
        .outerjoin(NormalizedOfferEvent, NormalizedOfferEvent.public_source_listing_id ==
                   NormalizedSourceListing.public_source_listing_id)
        .group_by(NormalizedSourceListing.source_name)).all()
    freshness = []
    for source, stamp, count in source_rows:
        hours = (now - stamp).total_seconds() / 3600 if stamp and stamp <= now else None
        status = ("unknown" if hours is None else "fresh" if hours <= 24 else
                  "warning" if hours <= 72 else "stale")
        freshness.append({"source": source, "lastUpdate": _utc_iso(stamp),
            "hoursSince": round(hours, 1) if hours is not None else None, "status": status,
            "observationCount": count, "timestampScope": "source_observation"})
    failures = session.scalars(select(CrawlLog).where(CrawlLog.status == CrawlStatus.FAILED,
        CrawlLog.started_at >= now - timedelta(hours=24)).order_by(CrawlLog.started_at.desc()).limit(10)).all()
    alerts = [{"id": row.id, "crawler": row.crawler_name,
        "message": row.error_message or f"{row.crawler_name} 크롤링 실패",
        "time": _utc_iso(row.started_at), "severity": "error"} for row in failures]
    activities = []
    for row in session.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(10)):
        state = {CrawlStatus.SUCCESS: "success", CrawlStatus.PARTIAL: "warning",
                 CrawlStatus.FAILED: "error"}.get(row.status, "unknown")
        activities.append((row.started_at, {"id": f"ri-{row.id}", "source": row.crawler_name,
            "count": row.items_saved, "itemsFound": row.items_found, "itemsSaved": row.items_saved,
            "date": row.started_at.strftime("%Y-%m-%d") if row.started_at else "",
            "status": state, "activityKind": "crawl", "countKind": "saved"}))
    for row in session.scalars(select(PendingIngestion).order_by(PendingIngestion.crawled_at.desc()).limit(10)):
        activities.append((row.crawled_at, {"id": f"intake-{row.id}", "source": row.crawler_name,
            "count": row.items_count, "date": row.crawled_at.strftime("%Y-%m-%d") if row.crawled_at else "",
            "status": row.status.value if row.status else "unknown", "activityKind": "ingestion_receipt",
            "countKind": "received"}))
    activities.sort(key=lambda row: row[0] or datetime.min, reverse=True)
    return {
        "source_scope": "admin_normalized_catalog",
        "snapshot_scope": "separate_public_projection_not_counted",
        "publicSnapshotCounts": None,
        "totalProducts": active_products, "totalPriceRecords": total_offers,
        "totalCategories": session.scalar(select(func.count()).select_from(UnifiedCategory)) or 0,
        "totalKeywords": session.scalar(select(func.count()).select_from(Keyword)) or 0,
        "catalogCounts": {"products": {"total": total_products, "active": active_products,
                                      "inactive": total_products - active_products}},
        "offerStates": states, "lastUpdated": _utc_iso(last_observation), "lastCrawlAt": _utc_iso(last_crawl),
        "qualityScore": None,
        "qualityDetails": {"status": "unavailable", "reason": "normalized_quality_not_assessed",
            "source_scope": "admin_normalized_catalog", "fillRate": None, "dupRate": None, "noCategoryRate": None},
        "freshness": freshness, "alerts": alerts, "recentIngestions": [row[1] for row in activities[:10]],
        "changes": {"products": None, "priceRecords": observed_today, "categories": None, "keywords": None},
    }


@router.get("/stats")
def dashboard_stats(identity: dict = Depends(require_viewer)):
    """대시보드 통합 통계 — 한 번의 호출로 모든 데이터 반환."""
    session = get_session()
    try:
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        normalized_products = session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct)) or 0
        if normalized_products:
            return _normalized_dashboard_stats(session, now, normalized_products)

        # ── 기본 카운트 ──
        total_products = (
            session.execute(select(func.count()).select_from(Product)).scalar() or 0
        )
        total_baseline = (
            session.execute(select(func.count()).select_from(BaselinePrice)).scalar()
            or 0
        )
        total_discount = (
            session.execute(select(func.count()).select_from(DiscountHistory)).scalar()
            or 0
        )
        total_hotdeal = (
            session.execute(select(func.count()).select_from(HotdealPrice)).scalar()
            or 0
        )
        total_price_records = total_baseline + total_discount + total_hotdeal
        total_categories = (
            session.execute(select(func.count()).select_from(Category)).scalar() or 0
        )
        total_keywords = (
            session.execute(select(func.count()).select_from(Keyword)).scalar() or 0
        )

        # ── 어제 대비 변화량 (오늘 추가된 건수) ──
        products_before_today = (
            session.execute(
                select(func.count())
                .select_from(Product)
                .where(Product.created_at < today_start)
            ).scalar()
            or 0
        )
        baseline_before_today = (
            session.execute(
                select(func.count())
                .select_from(BaselinePrice)
                .where(BaselinePrice.recorded_at < today_start)
            ).scalar()
            or 0
        )
        discount_before_today = (
            session.execute(
                select(func.count())
                .select_from(DiscountHistory)
                .where(DiscountHistory.crawled_at < today_start)
            ).scalar()
            or 0
        )
        hotdeal_before_today = (
            session.execute(
                select(func.count())
                .select_from(HotdealPrice)
                .where(HotdealPrice.crawled_at < today_start)
            ).scalar()
            or 0
        )

        changes = {
            "products": total_products - products_before_today,
            "priceRecords": total_price_records
            - (baseline_before_today + discount_before_today + hotdeal_before_today),
            "categories": 0,
            "keywords": 0,
        }

        # ── 마지막 업데이트 시간 ──
        last_crawl = session.execute(
            select(func.max(CrawlLog.started_at))
        ).scalar()

        # ── 긴급 알림 (최근 24시간 실패 크롤) ──
        alert_cutoff = now - timedelta(hours=24)
        failed_rows = (
            session.execute(
                select(CrawlLog)
                .where(
                    CrawlLog.status == CrawlStatus.FAILED,
                    CrawlLog.started_at >= alert_cutoff,
                )
                .order_by(CrawlLog.started_at.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )

        alerts = [
            {
                "id": r.id,
                "crawler": r.crawler_name,
                "message": r.error_message or f"{r.crawler_name} 크롤링 실패",
                "time": r.started_at.isoformat() if r.started_at else None,
                "severity": "error",
            }
            for r in failed_rows
        ]

        # ── 소스별 신선도 ──
        source_rows = session.execute(
            select(
                CrawlLog.crawler_name.label("source"),
                func.max(CrawlLog.started_at).label("last_update"),
                func.count().label("total"),
                func.sum(
                    case((CrawlLog.status == CrawlStatus.FAILED, 1), else_=0)
                ).label("failed"),
            )
            .group_by(CrawlLog.crawler_name)
            .order_by(func.max(CrawlLog.started_at).desc())
        ).all()

        freshness = []
        for r in source_rows:
            hours_since = (
                (now - r.last_update).total_seconds() / 3600
                if r.last_update
                else 999
            )
            if hours_since <= 24:
                status = "fresh"
            elif hours_since <= 72:
                status = "warning"
            else:
                status = "stale"
            freshness.append(
                {
                    "source": r.source,
                    "lastUpdate": r.last_update.isoformat() if r.last_update else None,
                    "hoursSince": round(hours_since, 1),
                    "status": status,
                }
            )

        # ── 품질 점수 (실데이터 기반) ──
        products_with_any_price = (
            session.execute(
                select(func.count())
                .select_from(Product)
                .where(
                    or_(
                        Product.id.in_(
                            select(BaselinePrice.product_id).distinct()
                        ),
                        Product.id.in_(
                            select(DiscountHistory.product_id).distinct()
                        ),
                    )
                )
            ).scalar()
            or 0
        )
        fill_rate = (products_with_any_price / max(total_products, 1)) * 100

        # Python 3.13 sqlite3에서 HAVING 절의 파라미터 바인딩 버그 회피:
        # count(*) > ? 대신 count(*) > 1 리터럴 사용
        dup_count = (
            session.execute(
                select(func.count()).select_from(
                    select(Product.name)
                    .group_by(Product.name)
                    .having(func.count() > literal(1))
                    .subquery()
                )
            ).scalar()
            or 0
        )
        unique_names = (
            session.execute(
                select(func.count(func.distinct(Product.name)))
            ).scalar()
            or 0
        )
        dup_rate = (dup_count / max(unique_names, 1)) * 100

        no_category = (
            session.execute(
                select(func.count())
                .select_from(Product)
                .where(Product.category_id.is_(None))
            ).scalar()
            or 0
        )
        no_category_rate = (no_category / max(total_products, 1)) * 100

        quality_score = round(
            fill_rate * 0.4 + (100 - dup_rate) * 0.3 + (100 - no_category_rate) * 0.3
        )
        quality_score = max(0, min(100, quality_score))

        quality_details = {
            "fillRate": round(fill_rate, 1),
            "dupRate": round(dup_rate, 1),
            "noCategoryRate": round(no_category_rate, 1),
        }

        # ── 최근 수집 활동 ──
        recent_rows = (
            session.execute(
                select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(10)
            )
            .scalars()
            .all()
        )

        recent_ingestions = []
        for r in recent_rows:
            st = "success"
            if r.status == CrawlStatus.FAILED:
                st = "error"
            elif r.status == CrawlStatus.PARTIAL:
                st = "warning"
            recent_ingestions.append(
                {
                    "id": f"ri-{r.id}",
                    "source": r.crawler_name,
                    "count": r.items_saved or r.items_found or 0,
                    "date": (
                        r.started_at.strftime("%Y-%m-%d") if r.started_at else ""
                    ),
                    "status": st,
                }
            )

        return {
            "totalProducts": total_products,
            "totalPriceRecords": total_price_records,
            "totalCategories": total_categories,
            "totalKeywords": total_keywords,
            "lastUpdated": last_crawl.isoformat() if last_crawl else None,
            "qualityScore": quality_score,
            "qualityDetails": quality_details,
            "recentIngestions": recent_ingestions,
            "alerts": alerts,
            "freshness": freshness,
            "changes": changes,
        }
    finally:
        session.close()
