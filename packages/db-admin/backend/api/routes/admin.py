"""관리자 데이터 초기화 API

위험한 대량 삭제·리셋 작업을 수행한다.
모든 엔드포인트는 confirm 문자열을 요구해 사고를 방지한다.
"""

import logging
from datetime import datetime

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Depends
from starlette.requests import Request

from services.base import get_session
from api.auth import require_admin, require_moderator, require_backup_snapshot_reader
from api.security import MAX_SOURCE_LEN
from services.backup import create_backup, list_backups
from api.middleware.rate_limit import limiter, DESTRUCTIVE_LIMIT, ADMIN_LIMIT
from config import settings
from storage.models import (
    Product, BaselinePrice, DiscountHistory, HotdealPrice,
    Category, Keyword, CrawlLog,
    PendingIngestion, PendingCategorization, CategoryCorrection,
    Post, Favorite, PriceAlert, CartItem, WishlistItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _cleanup_product_refs(session, product_ids=None):
    """products 삭제 전 FK 참조를 정리한다.

    product_ids=None  → 전체 정리 (reset-products, reset-all).
    product_ids=[...]  → 지정 상품만 정리 (reset-source 좀비 삭제).
    Returns dict of deletion counts.
    """
    if product_ids is not None and not product_ids:
        return {}

    counts: dict[str, int] = {}

    if product_ids is None:
        counts["price_alerts"] = session.query(PriceAlert).delete(
            synchronize_session=False)
        counts["pending_categorizations"] = session.query(
            PendingCategorization).delete(synchronize_session=False)
        for Model in (Post, Favorite, CartItem, WishlistItem):
            session.query(Model).filter(
                Model.product_id.isnot(None)
            ).update({"product_id": None}, synchronize_session=False)
    else:
        counts["price_alerts"] = session.query(PriceAlert).filter(
            PriceAlert.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
        counts["pending_categorizations"] = session.query(
            PendingCategorization).filter(
                PendingCategorization.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
        for Model in (Post, Favorite, CartItem, WishlistItem):
            session.query(Model).filter(
                Model.product_id.in_(product_ids)
            ).update({"product_id": None}, synchronize_session=False)

    return counts


class ResetSourceRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=MAX_SOURCE_LEN)
    confirm: str = Field(..., min_length=1, max_length=100)


class ResetProductsRequest(BaseModel):
    confirm: str = Field(..., min_length=1, max_length=100)


class ResetAllRequest(BaseModel):
    confirm: str = Field(..., min_length=1, max_length=100)


@router.get("/data-summary")
@limiter.limit(ADMIN_LIMIT)
def data_summary(request: Request, identity: dict = Depends(require_moderator)):
    """소스별 상품·가격 건수를 반환한다."""
    session = get_session()
    try:
        from sqlalchemy import func, distinct

        discount_rows = (
            session.query(
                DiscountHistory.source,
                func.count(DiscountHistory.id),
                func.count(distinct(DiscountHistory.product_id)),
            )
            .group_by(DiscountHistory.source)
            .all()
        )
        baseline_rows = (
            session.query(
                BaselinePrice.source,
                func.count(BaselinePrice.id),
                func.count(distinct(BaselinePrice.product_id)),
            )
            .group_by(BaselinePrice.source)
            .all()
        )
        hotdeal_rows = (
            session.query(
                HotdealPrice.source,
                func.count(HotdealPrice.id),
                func.count(distinct(HotdealPrice.product_id)),
            )
            .group_by(HotdealPrice.source)
            .all()
        )

        source_map: dict[str, dict] = {}
        for src, cnt, prod_cnt in discount_rows:
            entry = source_map.setdefault(src, {"source": src, "product_count": 0, "price_count": 0})
            entry["price_count"] += cnt
            entry["product_count"] = max(entry["product_count"], prod_cnt)
        for src, cnt, prod_cnt in baseline_rows:
            entry = source_map.setdefault(src, {"source": src, "product_count": 0, "price_count": 0})
            entry["price_count"] += cnt
            entry["product_count"] = max(entry["product_count"], prod_cnt)
        for src, cnt, prod_cnt in hotdeal_rows:
            entry = source_map.setdefault(src, {"source": src, "product_count": 0, "price_count": 0})
            entry["price_count"] += cnt
            entry["product_count"] = max(entry["product_count"], prod_cnt)

        total_products = session.query(func.count(Product.id)).scalar() or 0
        total_categories = session.query(func.count(Category.id)).scalar() or 0
        total_keywords = session.query(func.count(Keyword.id)).scalar() or 0

        return {
            "sources": sorted(source_map.values(), key=lambda x: x["price_count"], reverse=True),
            "total_products": total_products,
            "total_categories": total_categories,
            "total_keywords": total_keywords,
        }
    finally:
        session.close()


@router.post("/reset-source")
@limiter.limit(DESTRUCTIVE_LIMIT)
def reset_source(request: Request, body: ResetSourceRequest, identity: dict = Depends(require_admin)):
    """특정 소스의 가격 데이터와 관련 상품을 삭제한다."""
    expected = f"DELETE_{body.source.upper()}"
    if body.confirm != expected:
        raise HTTPException(status_code=400, detail="확인 문자열이 올바르지 않습니다.")

    try:
        backup_path = create_backup(settings.DATABASE_URL, reason="pre_reset_source")
        logger.warning("Pre-reset backup created: %s", backup_path)
    except Exception as e:
        logger.error("Backup failed, aborting reset: %s", e)
        raise HTTPException(status_code=500, detail="백업 실패로 리셋이 중단되었습니다.")

    session = get_session()
    try:
        src = body.source
        discount_del = session.query(DiscountHistory).filter(
            DiscountHistory.source == src
        ).delete(synchronize_session=False)
        baseline_del = session.query(BaselinePrice).filter(
            BaselinePrice.source == src
        ).delete(synchronize_session=False)
        hotdeal_del = session.query(HotdealPrice).filter(
            HotdealPrice.source == src
        ).delete(synchronize_session=False)

        from sqlalchemy import exists
        orphan_ids = [r[0] for r in session.query(Product.id).filter(
            ~exists().where(BaselinePrice.product_id == Product.id),
            ~exists().where(DiscountHistory.product_id == Product.id),
            ~exists().where(HotdealPrice.product_id == Product.id),
        ).all()]

        orphan_del = 0
        if orphan_ids:
            _cleanup_product_refs(session, orphan_ids)
            orphan_del = session.query(Product).filter(
                Product.id.in_(orphan_ids)
            ).delete(synchronize_session=False)

        session.commit()
        total_deleted = discount_del + baseline_del + hotdeal_del
        logger.warning(
            "[ADMIN] reset-source: source=%s discount=%d baseline=%d hotdeal=%d orphans=%d",
            src, discount_del, baseline_del, hotdeal_del, orphan_del,
        )
        return {
            "action": "reset-source",
            "source": src,
            "deleted": {
                "discount_history": discount_del,
                "baseline_prices": baseline_del,
                "hotdeal_prices": hotdeal_del,
                "orphan_products": orphan_del,
                "total": total_deleted + orphan_del,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/reset-products")
@limiter.limit(DESTRUCTIVE_LIMIT)
def reset_products(request: Request, body: ResetProductsRequest, identity: dict = Depends(require_admin)):
    """모든 상품·가격 데이터를 삭제한다. 카테고리·키워드는 보존."""
    if body.confirm != "DELETE_ALL_PRODUCTS":
        raise HTTPException(status_code=400, detail="확인 문자열이 올바르지 않습니다.")

    try:
        backup_path = create_backup(settings.DATABASE_URL, reason="pre_reset_products")
        logger.warning("Pre-reset backup created: %s", backup_path)
    except Exception as e:
        logger.error("Backup failed, aborting reset: %s", e)
        raise HTTPException(status_code=500, detail="백업 실패로 리셋이 중단되었습니다.")

    session = get_session()
    try:
        ref_counts = _cleanup_product_refs(session)
        discount_del = session.query(DiscountHistory).delete(synchronize_session=False)
        baseline_del = session.query(BaselinePrice).delete(synchronize_session=False)
        hotdeal_del = session.query(HotdealPrice).delete(synchronize_session=False)
        product_del = session.query(Product).delete(synchronize_session=False)
        crawllog_del = session.query(CrawlLog).delete(synchronize_session=False)
        pending_del = session.query(PendingIngestion).delete(synchronize_session=False)
        session.commit()

        logger.warning(
            "[ADMIN] reset-products: products=%d prices=%d",
            product_del, discount_del + baseline_del + hotdeal_del,
        )
        return {
            "action": "reset-products",
            "deleted": {
                "products": product_del,
                "discount_history": discount_del,
                "baseline_prices": baseline_del,
                "hotdeal_prices": hotdeal_del,
                "crawl_logs": crawllog_del,
                "pending_ingestions": pending_del,
                "pending_categorizations": ref_counts.get("pending_categorizations", 0),
                "price_alerts": ref_counts.get("price_alerts", 0),
                "total": product_del + discount_del + baseline_del + hotdeal_del,
            },
            "preserved": ["categories", "keywords"],
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/reset-all")
@limiter.limit(DESTRUCTIVE_LIMIT)
def reset_all(request: Request, body: ResetAllRequest, identity: dict = Depends(require_admin)):
    """모든 데이터를 삭제하고 시드 데이터(카테고리·키워드)만 남긴다."""
    if body.confirm != "RESET_ALL_DATA":
        raise HTTPException(status_code=400, detail="확인 문자열이 올바르지 않습니다.")

    try:
        backup_path = create_backup(settings.DATABASE_URL, reason="pre_reset_all")
        logger.warning("Pre-reset backup created: %s", backup_path)
    except Exception as e:
        logger.error("Backup failed, aborting reset: %s", e)
        raise HTTPException(status_code=500, detail="백업 실패로 리셋이 중단되었습니다.")

    session = get_session()
    try:
        ref_counts = _cleanup_product_refs(session)
        discount_del = session.query(DiscountHistory).delete(synchronize_session=False)
        baseline_del = session.query(BaselinePrice).delete(synchronize_session=False)
        hotdeal_del = session.query(HotdealPrice).delete(synchronize_session=False)
        product_del = session.query(Product).delete(synchronize_session=False)
        crawllog_del = session.query(CrawlLog).delete(synchronize_session=False)
        pending_del = session.query(PendingIngestion).delete(synchronize_session=False)
        correction_del = session.query(CategoryCorrection).delete(synchronize_session=False)

        keyword_del = session.query(Keyword).delete(synchronize_session=False)
        session.query(Category).filter(
            Category.parent_id.isnot(None)
        ).update({"parent_id": None}, synchronize_session=False)
        for Model in (Post, Favorite):
            session.query(Model).filter(
                Model.category_id.isnot(None)
            ).update({"category_id": None}, synchronize_session=False)
        category_del = session.query(Category).delete(synchronize_session=False)

        session.commit()
        logger.warning(
            "[ADMIN] reset-all: products=%d categories=%d keywords=%d",
            product_del, category_del, keyword_del,
        )
        return {
            "action": "reset-all",
            "deleted": {
                "products": product_del,
                "discount_history": discount_del,
                "baseline_prices": baseline_del,
                "hotdeal_prices": hotdeal_del,
                "crawl_logs": crawllog_del,
                "pending_ingestions": pending_del,
                "pending_categorizations": ref_counts.get("pending_categorizations", 0),
                "price_alerts": ref_counts.get("price_alerts", 0),
                "category_corrections": correction_del,
                "keywords": keyword_del,
                "categories": category_del,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/backup")
@limiter.limit(ADMIN_LIMIT)
def create_manual_backup(request: Request, identity: dict = Depends(require_admin)):
    """Create an on-demand database backup."""
    backup_path = create_backup(settings.DATABASE_URL, reason="manual")
    return {"status": "ok", "backup": backup_path}


@router.get("/backups")
@limiter.limit(ADMIN_LIMIT)
def get_backups(request: Request, identity: dict = Depends(require_backup_snapshot_reader)):
    """List all available backups."""
    return {"backups": list_backups()}
