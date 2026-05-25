from typing import Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query

from services.snapshot_repo import SnapshotRepo, get_conn
from services.search import search_products
from services.grading_view import get_grade_label
from services.redirect_resolver import SnapshotRedirectService

router = APIRouter()


# web-FINAL §4-4: 마트 도메인 화이트리스트. 운영 분리를 위해 차후 env/config 로 이동 예정.
KOREAN_MART_DOMAINS: dict[str, list[str]] = {
    "EMART": ["emart.ssg.com", "emart.com", "shinsegae.com"],
    "HOMEPLUS": ["homeplus.co.kr"],
    "LOTTEMART": ["lotteon.com", "lottemart.com"],
    "COSTCO": ["costco.co.kr"],
    "COUPANG": ["coupang.com"],
}


def _domain_of(url: str) -> Optional[str]:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host or None
    except Exception:
        return None


def _matches(domain: str, candidates: list[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in candidates)


def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        # tolerate trailing Z or +00:00
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        return None



@router.get("/products/resolve/{stable_id}")
def resolve_stable_id(stable_id: str):
    """p1-web-api-resolver-contract: stable_id → terminal canonical_id 해소 엔드포인트.

    redirect 테이블이 없거나 stable_id에 redirect가 없으면 stable_id 자체를 반환.
    cycle / depth 초과는 422 에러로 처리.
    """
    try:
        conn = get_conn()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    svc = SnapshotRedirectService(conn)
    try:
        terminal_id = svc.resolve(stable_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"redirect 해소 실패: {exc}")

    redirected = terminal_id != stable_id
    return {
        "stable_id": stable_id,
        "resolved_id": terminal_id,
        "redirected": redirected,
    }


@router.get("/products/search")
def search(
    q: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="recent", pattern="^(hot_deal|price_asc|price_desc|recent)$"),
    include_pending: bool = Query(default=False),
):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return search_products(repo, q, category, page, page_size, sort, include_pending)


@router.get("/products/trust_badge")
def get_trust_badge(
    domain: Optional[str] = Query(default=None),
    url: Optional[str] = Query(default=None),
    mart: Optional[str] = Query(default=None),
):
    """web-FINAL §4-4: 도메인 + 마트명 매칭 → green/yellow/red."""
    d = domain.lower() if domain else _domain_of(url or "")
    expected_mart = (mart or "").upper()

    if not d:
        return {"level": "yellow", "card_label": "🟡 검증 중", "detail_label": "🟡 링크 없음", "domain": None}

    all_known = [host for hs in KOREAN_MART_DOMAINS.values() for host in hs]
    in_some = _matches(d, all_known)
    expected = KOREAN_MART_DOMAINS.get(expected_mart, [])

    if expected and _matches(d, expected):
        return {"level": "green", "card_label": "🟢 검증됨", "detail_label": "🟢 공식몰 링크 확인됨", "domain": d}
    if not in_some:
        return {"level": "yellow", "card_label": "🟡 검증 중", "detail_label": "🟡 외부 링크 — 공식몰 아님", "domain": d}
    return {"level": "red", "card_label": "🔴 불일치", "detail_label": "🔴 마트명/링크 불일치", "domain": d}


@router.get("/products/{canonical_id}")
def get_product(canonical_id: str):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    product = repo.product_by_id(canonical_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    grade = repo.grade_by_id(canonical_id)
    aliases = repo.aliases_by_canonical(canonical_id)

    grade_label = get_grade_label(
        grade.p50 if grade else None,
        grade.p10 if grade else None,
        grade.p25 if grade else None,
        grade.p75 if grade else None,
        grade.sufficient if grade else False,
    )

    return {
        "canonical_id": product.id,
        "name_core": product.name_core,
        "brand": product.brand,
        "pack_quantity": product.pack_quantity,
        "pack_unit": product.pack_unit,
        "category_id": product.category_id,
        "image_url": product.representative_image_url,
        "price_grade": {
            "p10": grade.p10 if grade else None,
            "p25": grade.p25 if grade else None,
            "p50": grade.p50 if grade else None,
            "p75": grade.p75 if grade else None,
            "sufficient": grade.sufficient if grade else False,
            "sample_size": grade.sample_size if grade else 0,
            "grade_label": grade_label,
        },
        "mart_aliases": [
            {
                "mart": a.mart,
                "mart_item_id": a.mart_item_id,
                "mart_item_name_raw": a.mart_item_name_raw,
                "source_url": a.source_url,
                "last_seen_at": a.last_seen_at,
            }
            for a in aliases
        ],
    }


# ─────────────────────────── web-FINAL §13-2 신규 엔드포인트 ───────────────────────────
# price_observations 시계열 테이블이 DB 영역에서 들어오기 전까지는 mart_sku_alias.last_seen_at 만으로
# sparse stub 응답. 응답 shape 은 정식 데이터 도착해도 호환 유지.

@router.get("/products/{canonical_id}/history")
def get_product_history(
    canonical_id: str,
    mart: Optional[str] = Query(default=None),
    days: int = Query(default=180, ge=7, le=365),
):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not repo.product_by_id(canonical_id):
        raise HTTPException(status_code=404, detail="Product not found")

    aliases = repo.aliases_by_canonical(canonical_id)
    if mart:
        aliases = [a for a in aliases if a.mart == mart.upper()]

    grade = repo.grade_by_id(canonical_id)
    points = []
    for a in aliases:
        if a.last_seen_at:
            points.append({
                "date": a.last_seen_at,
                "price": grade.p50 if grade else None,
                "mart": a.mart,
                "source": "stub",
            })

    return {
        "canonical_id": canonical_id,
        "window_days": days,
        "source": "stub",
        "points": points,
        "note": "price_observations 미설치 — last_seen_at + p50 으로 임시 시각화",
    }


@router.get("/products/{canonical_id}/current_low")
def get_product_current_low(canonical_id: str):
    """7→14→30 자동 확장. 데이터 없으면 p10 fallback."""
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not repo.product_by_id(canonical_id):
        raise HTTPException(status_code=404, detail="Product not found")

    grade = repo.grade_by_id(canonical_id)
    aliases = repo.aliases_by_canonical(canonical_id)
    last_seen_days = None
    for a in aliases:
        d = _days_since(a.last_seen_at)
        if d is not None and (last_seen_days is None or d < last_seen_days):
            last_seen_days = d

    if grade is None or grade.p10 is None:
        return {
            "canonical_id": canonical_id,
            "price": None,
            "window_days": None,
            "label": "데이터 없음",
            "source": "none",
            "last_seen_days": last_seen_days,
        }

    if last_seen_days is not None and last_seen_days <= 7:
        window = 7
    elif last_seen_days is not None and last_seen_days <= 14:
        window = 14
    elif last_seen_days is not None and last_seen_days <= 30:
        window = 30
    else:
        window = 30

    return {
        "canonical_id": canonical_id,
        "price": grade.p10,
        "window_days": window,
        "label": f"최근 {window}일 최저가 (P10 fallback)",
        "source": "grade_fallback",
        "last_seen_days": last_seen_days,
    }


@router.get("/products/{canonical_id}/grade_detail")
def get_product_grade_detail(canonical_id: str):
    """핫딜러 lazy: P10/P25/P50/P75 + unit_price + sample_size."""
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    product = repo.product_by_id(canonical_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    grade = repo.grade_by_id(canonical_id)
    if not grade:
        return {
            "canonical_id": canonical_id,
            "p10": None, "p25": None, "p50": None, "p75": None,
            "sample_size": 0, "sufficient": False,
            "unit_price": None, "pack_quantity": product.pack_quantity, "pack_unit": product.pack_unit,
        }

    unit_price = None
    if grade.p50 and product.pack_quantity and product.pack_quantity > 0:
        unit_price = round(grade.p50 / product.pack_quantity, 2)

    return {
        "canonical_id": canonical_id,
        "p10": grade.p10,
        "p25": grade.p25,
        "p50": grade.p50,
        "p75": grade.p75,
        "sample_size": grade.sample_size,
        "sufficient": grade.sufficient,
        "unit_price": unit_price,
        "pack_quantity": product.pack_quantity,
        "pack_unit": product.pack_unit,
    }
