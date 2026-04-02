"""가격 대량 저장 + 통계 + 티어설정 + 이상치 + 이력 라우트"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
import math

from sqlalchemy import select, func, and_

from services.base import get_session
from services.price_calc import calculate_baseline_average, get_price_history
from services.export import get_statistics_summary
from storage.models import BaselinePrice, DiscountHistory, Product

router = APIRouter(prefix="/prices", tags=["prices"])

TIER_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "tier_config.json"

DEFAULT_TIER_CONFIG = {
    "ultra": {"label": "초특가", "threshold": 70, "color": "var(--tier-ultra)"},
    "great": {"label": "특가",   "threshold": 85, "color": "var(--tier-great)"},
    "good":  {"label": "적정",   "threshold": 105, "color": "var(--tier-good)"},
    "wait":  {"label": "관망",   "threshold": 120, "color": "var(--tier-wait)"},
    "bad":   {"label": "비쌈",   "threshold": None, "color": "var(--tier-bad)"},
}


class PriceItem(BaseModel):
    product_id: int
    price: float
    source: str
    unit: str = "개"
    region: Optional[str] = None


class BulkPriceRequest(BaseModel):
    items: list[PriceItem]
    data_type: str = "baseline"


class TierConfigRequest(BaseModel):
    tiers: dict


@router.post("/bulk", status_code=201)
def bulk_save_prices(body: BulkPriceRequest):
    session = get_session()
    try:
        saved = 0
        for item in body.items:
            if body.data_type == "baseline":
                row = BaselinePrice(
                    product_id=item.product_id,
                    price=item.price,
                    source=item.source,
                    unit=item.unit,
                    recorded_at=datetime.utcnow(),
                    region=item.region,
                )
            else:
                row = DiscountHistory(
                    product_id=item.product_id,
                    price=item.price,
                    source=item.source,
                    crawled_at=datetime.utcnow(),
                )
            session.add(row)
            saved += 1
        session.commit()
        return {"saved": saved}
    finally:
        session.close()


@router.get("/stats")
def price_statistics():
    session = get_session()
    try:
        return get_statistics_summary(session)
    finally:
        session.close()


@router.get("/product/{product_id}")
def product_prices(product_id: int, days: int = 90):
    session = get_session()
    try:
        return calculate_baseline_average(session, product_id, days)
    finally:
        session.close()


# ── 티어 설정 ──

@router.get("/tier-config")
def get_tier_config():
    """저장된 티어 설정 로드 (없으면 기본값)"""
    if TIER_CONFIG_PATH.exists():
        try:
            return json.loads(TIER_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_TIER_CONFIG


@router.post("/tier-config")
def save_tier_config(body: TierConfigRequest):
    """티어 설정 저장"""
    TIER_CONFIG_PATH.write_text(
        json.dumps(body.tiers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"status": "ok", "saved": body.tiers}


# ── 글로벌 이상치 ──

@router.get("/outliers")
def global_outliers(limit: int = Query(20, ge=1, le=200)):
    """전체 상품에 대한 글로벌 이상치 탐지 (IQR)"""
    session = get_session()
    try:
        products = session.execute(select(Product.id, Product.name)).all()
        all_outliers = []

        for pid, pname in products:
            rows = session.execute(
                select(
                    BaselinePrice.id,
                    BaselinePrice.price,
                    BaselinePrice.recorded_at,
                    BaselinePrice.source,
                ).where(BaselinePrice.product_id == pid)
                .order_by(BaselinePrice.recorded_at.desc())
            ).all()

            prices = [r.price for r in rows]
            if len(prices) < 4:
                continue

            sorted_p = sorted(prices)
            q1 = sorted_p[len(sorted_p) // 4]
            q3 = sorted_p[3 * len(sorted_p) // 4]
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            avg_price = sum(prices) / len(prices)

            for r in rows:
                if r.price < lower or r.price > upper:
                    deviation = round((r.price - avg_price) / avg_price * 100, 1) if avg_price else 0
                    all_outliers.append({
                        "id": f"o-{r.id}",
                        "productId": pid,
                        "productName": pname,
                        "date": r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else "",
                        "price": r.price,
                        "avgPrice": round(avg_price),
                        "deviation": deviation,
                        "source": r.source or "",
                    })

        all_outliers.sort(key=lambda x: abs(x["deviation"]), reverse=True)
        return all_outliers[:limit]
    finally:
        session.close()


# ── 가격 이력 (페이징 + 필터) ──

@router.get("/history")
def price_history_list(
    source: Optional[str] = None,
    product_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    days: int = Query(90, ge=1),
):
    """페이지네이션 + 필터가 가능한 가격 이력 조회"""
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        conditions = [BaselinePrice.recorded_at >= since]
        if source:
            conditions.append(BaselinePrice.source == source)
        if product_id:
            conditions.append(BaselinePrice.product_id == product_id)

        total = session.execute(
            select(func.count()).select_from(BaselinePrice).where(and_(*conditions))
        ).scalar() or 0

        offset = (page - 1) * per_page
        rows = session.execute(
            select(
                BaselinePrice.id,
                BaselinePrice.product_id,
                BaselinePrice.price,
                BaselinePrice.source,
                BaselinePrice.recorded_at,
                Product.name.label("product_name"),
            )
            .join(Product, BaselinePrice.product_id == Product.id, isouter=True)
            .where(and_(*conditions))
            .order_by(BaselinePrice.recorded_at.desc())
            .offset(offset)
            .limit(per_page)
        ).all()

        items = []
        for r in rows:
            items.append({
                "id": r.id,
                "productId": r.product_id,
                "productName": r.product_name or "",
                "date": r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else "",
                "price": r.price,
                "source": r.source or "",
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if total else 0,
        }
    finally:
        session.close()
