"""가격 대량 저장 + 통계 + 티어설정 + 이상치 + 이력 + CSV 내보내기 라우트"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
import math
import csv
import io
import statistics as pystats

from sqlalchemy import select, func, and_

from services.base import get_session
from services.price_calc import calculate_baseline_average, get_price_history
from services.export import get_statistics_summary
from storage.models import BaselinePrice, DiscountHistory, Product, Category

router = APIRouter(prefix="/prices", tags=["prices"])


# ── 가격 목록 (기본 페이징) ──

@router.get("/")
def list_prices(
    product_id: Optional[int] = None,
    source: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """가격 목록 — 기본 페이징 + 필터."""
    session = get_session()
    try:
        conditions = []
        if product_id:
            conditions.append(BaselinePrice.product_id == product_id)
        if source:
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))

        total = session.execute(
            select(func.count()).select_from(BaselinePrice).where(and_(*conditions)) if conditions
            else select(func.count()).select_from(BaselinePrice)
        ).scalar() or 0

        offset = (page - 1) * per_page
        q = (
            select(
                BaselinePrice.id,
                BaselinePrice.product_id,
                BaselinePrice.price,
                BaselinePrice.source,
                BaselinePrice.unit,
                BaselinePrice.recorded_at,
                Product.name.label("product_name"),
            )
            .join(Product, BaselinePrice.product_id == Product.id, isouter=True)
            .order_by(BaselinePrice.recorded_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        if conditions:
            q = q.where(and_(*conditions))

        rows = session.execute(q).all()
        items = [
            {
                "id": r.id,
                "product_id": r.product_id,
                "product_name": r.product_name or "",
                "price": r.price,
                "source": r.source or "",
                "unit": r.unit or "",
                "recorded_at": r.recorded_at.strftime("%Y-%m-%d %H:%M") if r.recorded_at else "",
            }
            for r in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if total else 0,
        }
    finally:
        session.close()

TIER_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "tier_config.json"
WHITELIST_PATH = Path(__file__).resolve().parent.parent.parent / "outlier_whitelist.json"

DEFAULT_TIER_CONFIG = {
    "ultra": {"label": "초특가", "threshold": 70, "color": "var(--tier-ultra)"},
    "great": {"label": "특가",   "threshold": 85, "color": "var(--tier-great)"},
    "good":  {"label": "적정",   "threshold": 105, "color": "var(--tier-good)"},
    "wait":  {"label": "관망",   "threshold": 120, "color": "var(--tier-wait)"},
    "bad":   {"label": "비쌈",   "threshold": None, "color": "var(--tier-bad)"},
}


def _load_whitelist() -> set:
    """화이트리스트 로드"""
    if WHITELIST_PATH.exists():
        try:
            data = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
            return set(data)
        except Exception:
            pass
    return set()


def _save_whitelist(ids: set):
    """화이트리스트 저장"""
    WHITELIST_PATH.write_text(
        json.dumps(sorted(ids), ensure_ascii=False),
        encoding="utf-8",
    )


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


# ── 대량 저장 ──

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


# ── 통계 ──

@router.get("/stats")
def price_statistics():
    """실제 DB 기반 전체 가격 통계 (median, std_dev, min, max, 소스별, 카테고리별)"""
    session = get_session()
    try:
        base = get_statistics_summary(session)

        all_prices = session.execute(
            select(BaselinePrice.price)
        ).scalars().all()

        if all_prices:
            prices = [float(p) for p in all_prices]
            base["avg_baseline_price"] = round(pystats.mean(prices), 1)
            base["median"] = round(pystats.median(prices), 1)
            base["std_dev"] = round(pystats.stdev(prices), 1) if len(prices) > 1 else 0
            base["min_price"] = round(min(prices), 1)
            base["max_price"] = round(max(prices), 1)
        else:
            base.setdefault("avg_baseline_price", 0)
            base["median"] = 0
            base["std_dev"] = 0
            base["min_price"] = 0
            base["max_price"] = 0

        source_rows = session.execute(
            select(
                BaselinePrice.source,
                func.avg(BaselinePrice.price).label("avg_price"),
                func.count().label("count"),
            ).group_by(BaselinePrice.source)
        ).all()
        base["source_averages"] = [
            {"source": r.source or "unknown", "avgPrice": round(float(r.avg_price), 1), "count": r.count}
            for r in source_rows
        ]

        cat_rows = session.execute(
            select(
                Category.name.label("category_name"),
                func.avg(BaselinePrice.price).label("avg_price"),
                func.count(BaselinePrice.id).label("count"),
            )
            .join(Product, BaselinePrice.product_id == Product.id)
            .join(Category, Product.category_id == Category.id, isouter=True)
            .group_by(Category.name)
        ).all()
        base["category_prices"] = [
            {"category": r.category_name or "미분류", "avgPrice": round(float(r.avg_price), 1), "count": r.count}
            for r in cat_rows
        ]

        return base
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


@router.get("/tier-preview")
def tier_preview(
    ultra: float = Query(70),
    great: float = Query(85),
    good: float = Query(105),
    wait: float = Query(120),
):
    """티어 기준값 변경 시 각 등급에 해당하는 상품 수 미리보기"""
    session = get_session()
    try:
        products = session.execute(select(Product.id)).all()
        counts = {"ultra": 0, "great": 0, "good": 0, "wait": 0, "bad": 0, "no_data": 0}

        for (pid,) in products:
            avg_baseline = session.execute(
                select(func.avg(BaselinePrice.price)).where(
                    BaselinePrice.product_id == pid
                )
            ).scalar()
            if not avg_baseline or avg_baseline == 0:
                counts["no_data"] += 1
                continue

            avg_discount = session.execute(
                select(func.avg(DiscountHistory.price)).where(
                    DiscountHistory.product_id == pid,
                    DiscountHistory.crawled_at >= datetime.utcnow() - timedelta(days=30),
                )
            ).scalar()
            if not avg_discount:
                counts["no_data"] += 1
                continue

            ratio = (avg_discount / avg_baseline) * 100
            if ratio <= ultra:
                counts["ultra"] += 1
            elif ratio <= great:
                counts["great"] += 1
            elif ratio <= good:
                counts["good"] += 1
            elif ratio <= wait:
                counts["wait"] += 1
            else:
                counts["bad"] += 1

        return counts
    finally:
        session.close()


# ── 글로벌 이상치 ──

@router.get("/outliers")
def global_outliers(limit: int = Query(20, ge=1, le=200)):
    """전체 상품에 대한 글로벌 이상치 탐지 (IQR), 화이트리스트 제외"""
    session = get_session()
    try:
        whitelist = _load_whitelist()
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
                if r.id in whitelist:
                    continue
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


@router.post("/outliers/{outlier_id}/whitelist")
def whitelist_outlier(outlier_id: str):
    """이상치를 정상으로 표시 (화이트리스트 추가)"""
    raw_id = outlier_id.replace("o-", "") if outlier_id.startswith("o-") else outlier_id
    try:
        bp_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 이상치 ID입니다")

    whitelist = _load_whitelist()
    whitelist.add(bp_id)
    _save_whitelist(whitelist)
    return {"status": "ok", "whitelisted": outlier_id}


@router.get("/outliers/{product_id}/distribution")
def outlier_distribution(product_id: int, days: int = Query(90, ge=1)):
    """특정 상품의 가격 분포 (이상치 상세 미니차트용)"""
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = session.execute(
            select(BaselinePrice.price, BaselinePrice.recorded_at)
            .where(
                BaselinePrice.product_id == product_id,
                BaselinePrice.recorded_at >= since,
            )
            .order_by(BaselinePrice.recorded_at)
        ).all()

        return [
            {"date": r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else "", "price": r.price}
            for r in rows
        ]
    finally:
        session.close()


# ── 가격 이력 (페이징 + 필터) ──

def _build_date_conditions(date_from, date_to, days):
    """날짜 필터 조건 생성 헬퍼"""
    conditions = []
    date_filter_added = False

    if date_from:
        try:
            conditions.append(BaselinePrice.recorded_at >= datetime.fromisoformat(date_from))
            date_filter_added = True
        except ValueError:
            pass
    if date_to:
        try:
            conditions.append(BaselinePrice.recorded_at <= datetime.fromisoformat(date_to + "T23:59:59"))
            date_filter_added = True
        except ValueError:
            pass

    if not date_filter_added:
        since = datetime.utcnow() - timedelta(days=days)
        conditions.append(BaselinePrice.recorded_at >= since)

    return conditions


@router.get("/history")
def price_history_list(
    source: Optional[str] = None,
    product_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    days: int = Query(90, ge=1),
):
    """페이지네이션 + 필터가 가능한 가격 이력 조회"""
    session = get_session()
    try:
        conditions = _build_date_conditions(date_from, date_to, days)

        if source:
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))
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


# ── CSV 내보내기 ──

@router.get("/export")
def export_csv(
    source: Optional[str] = None,
    product_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    days: int = Query(90, ge=1),
):
    """가격 데이터 CSV 내보내기"""
    session = get_session()
    try:
        conditions = _build_date_conditions(date_from, date_to, days)

        if source:
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))
        if product_id:
            conditions.append(BaselinePrice.product_id == product_id)

        rows = session.execute(
            select(
                BaselinePrice.id,
                BaselinePrice.product_id,
                BaselinePrice.price,
                BaselinePrice.source,
                BaselinePrice.unit,
                BaselinePrice.recorded_at,
                Product.name.label("product_name"),
            )
            .join(Product, BaselinePrice.product_id == Product.id, isouter=True)
            .where(and_(*conditions))
            .order_by(BaselinePrice.recorded_at.desc())
        ).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "상품ID", "상품명", "가격", "출처", "단위", "날짜"])
        for r in rows:
            writer.writerow([
                r.id, r.product_id, r.product_name or "",
                r.price, r.source or "", r.unit or "",
                r.recorded_at.strftime("%Y-%m-%d %H:%M") if r.recorded_at else "",
            ])

        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=prices_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            },
        )
    finally:
        session.close()
