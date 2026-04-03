"""관리자 데이터 초기화 API

위험한 대량 삭제·리셋 작업을 수행한다.
모든 엔드포인트는 confirm 문자열을 요구해 사고를 방지한다.
"""

import logging
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from services.base import get_session
from storage.models import (
    Product, BaselinePrice, DiscountHistory, HotdealPrice,
    Category, Keyword, CrawlLog,
    PendingIngestion, PendingCategorization, CategoryCorrection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request 스키마 ──

class ResetSourceRequest(BaseModel):
    source: str
    confirm: str


class ResetProductsRequest(BaseModel):
    confirm: str


class ResetAllRequest(BaseModel):
    confirm: str


# ── GET /admin/data-summary ──

@router.get("/data-summary")
def data_summary():
    """소스별 상품·가격 건수를 반환한다."""
    session = get_session()
    try:
        from sqlalchemy import func, distinct

        # 소스별 DiscountHistory 집계
        discount_rows = (
            session.query(
                DiscountHistory.source,
                func.count(DiscountHistory.id),
                func.count(distinct(DiscountHistory.product_id)),
            )
            .group_by(DiscountHistory.source)
            .all()
        )

        # 소스별 BaselinePrice 집계
        baseline_rows = (
            session.query(
                BaselinePrice.source,
                func.count(BaselinePrice.id),
                func.count(distinct(BaselinePrice.product_id)),
            )
            .group_by(BaselinePrice.source)
            .all()
        )

        # 소스별 HotdealPrice 집계
        hotdeal_rows = (
            session.query(
                HotdealPrice.source,
                func.count(HotdealPrice.id),
                func.count(distinct(HotdealPrice.product_id)),
            )
            .group_by(HotdealPrice.source)
            .all()
        )

        # 합산
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


# ── POST /admin/reset-source ──

@router.post("/reset-source")
def reset_source(body: ResetSourceRequest):
    """특정 소스의 가격 데이터와 관련 상품을 삭제한다."""
    expected = f"DELETE_{body.source.upper()}"
    if body.confirm != expected:
        raise HTTPException(
            status_code=400,
            detail=f"확인 문자열이 올바르지 않습니다. '{expected}'를 입력하세요.",
        )

    session = get_session()
    try:
        src = body.source

        discount_del = (
            session.query(DiscountHistory)
            .filter(DiscountHistory.source == src)
            .delete(synchronize_session=False)
        )
        baseline_del = (
            session.query(BaselinePrice)
            .filter(BaselinePrice.source == src)
            .delete(synchronize_session=False)
        )
        hotdeal_del = (
            session.query(HotdealPrice)
            .filter(HotdealPrice.source == src)
            .delete(synchronize_session=False)
        )

        session.commit()

        total_deleted = discount_del + baseline_del + hotdeal_del
        logger.warning(
            "[ADMIN] reset-source: source=%s discount=%d baseline=%d hotdeal=%d",
            src, discount_del, baseline_del, hotdeal_del,
        )

        return {
            "action": "reset-source",
            "source": src,
            "deleted": {
                "discount_history": discount_del,
                "baseline_prices": baseline_del,
                "hotdeal_prices": hotdeal_del,
                "total": total_deleted,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── POST /admin/reset-products ──

@router.post("/reset-products")
def reset_products(body: ResetProductsRequest):
    """모든 상품·가격 데이터를 삭제한다. 카테고리·키워드는 보존."""
    if body.confirm != "DELETE_ALL_PRODUCTS":
        raise HTTPException(
            status_code=400,
            detail="확인 문자열이 올바르지 않습니다. 'DELETE_ALL_PRODUCTS'를 입력하세요.",
        )

    session = get_session()
    try:
        from sqlalchemy import func

        product_count = session.query(func.count(Product.id)).scalar() or 0
        discount_del = session.query(DiscountHistory).delete(synchronize_session=False)
        baseline_del = session.query(BaselinePrice).delete(synchronize_session=False)
        hotdeal_del = session.query(HotdealPrice).delete(synchronize_session=False)
        product_del = session.query(Product).delete(synchronize_session=False)
        crawllog_del = session.query(CrawlLog).delete(synchronize_session=False)
        pending_del = session.query(PendingIngestion).delete(synchronize_session=False)
        pending_cat_del = session.query(PendingCategorization).delete(synchronize_session=False)

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
                "pending_categorizations": pending_cat_del,
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


# ── POST /admin/reset-all ──

@router.post("/reset-all")
def reset_all(body: ResetAllRequest):
    """모든 데이터를 삭제하고 시드 데이터(카테고리·키워드)만 남긴다."""
    if body.confirm != "RESET_ALL_DATA":
        raise HTTPException(
            status_code=400,
            detail="확인 문자열이 올바르지 않습니다. 'RESET_ALL_DATA'를 입력하세요.",
        )

    session = get_session()
    try:
        discount_del = session.query(DiscountHistory).delete(synchronize_session=False)
        baseline_del = session.query(BaselinePrice).delete(synchronize_session=False)
        hotdeal_del = session.query(HotdealPrice).delete(synchronize_session=False)
        product_del = session.query(Product).delete(synchronize_session=False)
        crawllog_del = session.query(CrawlLog).delete(synchronize_session=False)
        pending_del = session.query(PendingIngestion).delete(synchronize_session=False)
        pending_cat_del = session.query(PendingCategorization).delete(synchronize_session=False)
        correction_del = session.query(CategoryCorrection).delete(synchronize_session=False)
        keyword_del = session.query(Keyword).delete(synchronize_session=False)
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
                "pending_categorizations": pending_cat_del,
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
