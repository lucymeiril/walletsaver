"""WalletSavior Phase F4 — /fuels API 엔드포인트.

GET /api/v1/fuels/stations  — 주유소 검색 (지역/브랜드/유종/정렬/거리)
GET /api/v1/fuels/stations/{id}  — 주유소 상세
GET /api/v1/fuels/regions   — 시도/시군구/브랜드 드롭다운 데이터
"""

from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services.snapshot_repo import SnapshotRepo, get_conn

router = APIRouter()

_VALID_FUEL_KINDS = {"gasoline_regular", "gasoline_premium", "diesel", "lpg"}
_VALID_SORTS = {"price_asc", "name_asc", "distance"}

_FUEL_KIND_KR = {
    "gasoline_regular": "휘발유",
    "gasoline_premium": "고급휘발유",
    "diesel": "경유",
    "lpg": "LPG",
}

_GRADE_LABEL_MAP = {
    True: {
        "CHEAP": "CHEAP",
        "NORMAL": "NORMAL",
        "EXPENSIVE": "EXPENSIVE",
    },
    False: "INSUFFICIENT_DATA",
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 Haversine 거리 (km)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _classify_fuel_grade(price: int, grade: Optional[dict]) -> str:
    """가격 + 등급 dict → CHEAP/NORMAL/EXPENSIVE/INSUFFICIENT_DATA."""
    if grade is None or not grade.get("sufficient"):
        return "INSUFFICIENT_DATA"
    p25 = grade.get("p25")
    p75 = grade.get("p75")
    if p25 is None or p75 is None:
        return "INSUFFICIENT_DATA"
    if price <= p25:
        return "CHEAP"
    if price <= p75:
        return "NORMAL"
    return "EXPENSIVE"


def _get_repo() -> SnapshotRepo:
    try:
        conn = get_conn()
        return SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


def _check_fuel_available(repo: SnapshotRepo) -> None:
    if not repo.has_fuel_tables():
        raise HTTPException(
            status_code=503,
            detail="주유소 데이터가 아직 준비되지 않았습니다. 스냅샷에 fuel 테이블이 없습니다.",
        )


@router.get("/fuels/regions")
def get_fuel_regions(
    sido: Optional[str] = Query(default=None, description="시도 필터 (시군구 목록 조회용)"),
):
    """시도 목록, 시군구 목록, 브랜드 목록 반환 (드롭다운용).

    sido 파라미터가 있으면 해당 시도의 시군구 목록만 반환.
    """
    repo = _get_repo()
    _check_fuel_available(repo)

    sido_list = repo.fuel_sido_list()
    sigungu_list = repo.fuel_sigungu_list(sido=sido)
    brand_list = repo.fuel_brand_list()

    return {
        "sido_list": sido_list,
        "sigungu_list": sigungu_list,
        "brand_list": brand_list,
        "fuel_kinds": [
            {"value": k, "label": v} for k, v in _FUEL_KIND_KR.items()
        ],
    }


@router.get("/fuels/stations")
def search_fuel_stations(
    sido: Optional[str] = Query(default=None),
    sigungu: Optional[str] = Query(default=None),
    brand: Optional[str] = Query(default=None),
    fuel_kind: str = Query(default="gasoline_regular"),
    sort: str = Query(default="price_asc"),
    lat: Optional[float] = Query(default=None, description="현재 위도 (거리 정렬/필터용)"),
    lng: Optional[float] = Query(default=None, description="현재 경도"),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=50.0, description="반경 필터 (km)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """주유소 검색.

    필터: sido, sigungu, brand, fuel_kind (기본: gasoline_regular)
    정렬: price_asc (가격 오름차순), name_asc (이름순), distance (거리순, lat/lng 필요)
    거리 필터: radius_km + lat + lng 지정 시 반경 내 주유소만 반환
    """
    if fuel_kind not in _VALID_FUEL_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"fuel_kind는 {sorted(_VALID_FUEL_KINDS)} 중 하나여야 합니다.",
        )
    if sort not in _VALID_SORTS:
        raise HTTPException(
            status_code=422,
            detail=f"sort는 {sorted(_VALID_SORTS)} 중 하나여야 합니다.",
        )
    if sort == "distance" and (lat is None or lng is None):
        raise HTTPException(
            status_code=422,
            detail="distance 정렬을 사용하려면 lat, lng 파라미터가 필요합니다.",
        )

    repo = _get_repo()
    _check_fuel_available(repo)

    stations = repo.fuel_stations(sido=sido, sigungu=sigungu, brand=brand)

    # 가격 조인
    prices_by_station: dict[str, int] = {}
    for price_row in repo.fuel_prices_by_kind(fuel_kind):
        prices_by_station[price_row["station_id"]] = price_row["price"]

    # 등급 캐시: (sido, sigungu, fuel_kind)
    grade_cache: dict[tuple[str, str], Optional[dict]] = {}

    def _get_grade(s_sido: str, s_sigungu: str) -> Optional[dict]:
        key = (s_sido, s_sigungu)
        if key not in grade_cache:
            grade_cache[key] = repo.fuel_grade(s_sido, s_sigungu, fuel_kind)
        return grade_cache[key]

    # 거리 계산 + 반경 필터
    items = []
    for s in stations:
        price = prices_by_station.get(s["id"])
        if price is None and sort == "price_asc":
            # 가격 없는 주유소는 목록 뒤로
            pass

        distance_km: Optional[float] = None
        if lat is not None and lng is not None and s["lat"] is not None and s["lng"] is not None:
            distance_km = _haversine_km(lat, lng, s["lat"], s["lng"])
            if radius_km is not None and distance_km > radius_km:
                continue
        elif radius_km is not None and (s["lat"] is None or s["lng"] is None):
            # 좌표 없는 주유소는 반경 필터 통과 불가
            continue

        grade = _get_grade(s["sido"], s["sigungu"]) if price is not None else None
        grade_label = _classify_fuel_grade(price, grade) if price is not None else "INSUFFICIENT_DATA"

        items.append({
            **s,
            "price": price,
            "fuel_kind": fuel_kind,
            "fuel_kind_label": _FUEL_KIND_KR.get(fuel_kind, fuel_kind),
            "grade_label": grade_label,
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
        })

    # 정렬
    if sort == "price_asc":
        items.sort(key=lambda x: (x["price"] is None, x["price"] or 0))
    elif sort == "name_asc":
        items.sort(key=lambda x: x["name"])
    elif sort == "distance":
        items.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 0))

    # 페이지네이션
    total = len(items)
    total_pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    paged = items[start : start + page_size]

    # 요약 통계 (현재 필터 기준)
    prices_with_value = [x["price"] for x in items if x["price"] is not None]
    summary = {
        "region": f"{sido or ''} {sigungu or ''}".strip() or "전체",
        "fuel_kind": fuel_kind,
        "fuel_kind_label": _FUEL_KIND_KR.get(fuel_kind, fuel_kind),
        "avg_price": round(sum(prices_with_value) / len(prices_with_value)) if prices_with_value else None,
        "min_price": min(prices_with_value) if prices_with_value else None,
        "station_count": total,
    }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "summary": summary,
        "items": paged,
    }


@router.get("/fuels/stations/{station_id}")
def get_fuel_station(station_id: str):
    """주유소 상세 — 현재 유종별 가격 + 등급 포함."""
    repo = _get_repo()
    _check_fuel_available(repo)

    station = repo.fuel_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="주유소를 찾을 수 없습니다.")

    prices = repo.fuel_prices_for_station(station_id)

    price_details = []
    for p in prices:
        grade = repo.fuel_grade(station["sido"], station["sigungu"], p["fuel_kind"])
        grade_label = _classify_fuel_grade(p["price"], grade)
        price_details.append({
            "fuel_kind": p["fuel_kind"],
            "fuel_kind_label": _FUEL_KIND_KR.get(p["fuel_kind"], p["fuel_kind"]),
            "price": p["price"],
            "observed_at": p["observed_at"],
            "grade_label": grade_label,
            "grade": {
                "p25": grade["p25"] if grade else None,
                "p50": grade["p50"] if grade else None,
                "p75": grade["p75"] if grade else None,
                "sufficient": grade["sufficient"] if grade else False,
            },
        })

    return {
        **station,
        "prices": price_details,
    }
