"""Gas-price API backed by the dedicated OPINET SQLite database."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from api.schemas.common import ApiResponse

_SHARED = Path(__file__).resolve().parents[4] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_store import FuelStore, FuelStoreUnavailable

router = APIRouter()
_DEFAULT_NEARBY_RADIUS_M = 10_000


@router.get("/nearby")
async def nearby_gas_stations(
    lat: float | None = Query(None, ge=-90, le=90, description="위도"),
    lng: float | None = Query(None, ge=-180, le=180, description="경도"),
    radius: int | None = Query(None, ge=100, le=50000, description="반경 (미터)"),
    fuel_type: Literal["gasoline", "premium", "diesel", "kerosene", "lpg"] = Query(
        "gasoline",
        description="연료 종류",
    ),
    sort: Literal["price_asc", "distance"] = Query("price_asc", description="정렬"),
    sido: str | None = Query(None, max_length=50, description="시도"),
    sigungu: str | None = Query(None, max_length=80, description="시군구"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Return current OPINET prices, optionally filtered by region or distance.

    The deployed web-api is a read-only consumer of the crawler-owned OPINET
    snapshot. A missing/corrupt snapshot is therefore a deployment error (503),
    not an empty-but-healthy fuel database created on the server.

    Live crawler rows convert OPINET's KATEC GIS coordinates to WGS84 before
    they are written to the shared fuel snapshot. Legacy rows that still lack
    trustworthy WGS84 coordinates remain usable for price/region comparison,
    but are excluded whenever the caller supplies latitude/longitude. Because
    this endpoint is named ``nearby``, coordinates without an explicit radius
    use a conservative 10 km default instead of returning nationwide rows.
    """
    if (lat is None) != (lng is None):
        return ApiResponse(data=[], message="거리 조회에는 lat와 lng가 모두 필요합니다")
    if radius is not None and (lat is None or lng is None):
        return ApiResponse(data=[], message="반경 조회에는 lat와 lng가 필요합니다")

    effective_radius = radius
    if lat is not None and lng is not None and effective_radius is None:
        effective_radius = _DEFAULT_NEARBY_RADIUS_M

    try:
        store = FuelStore(readonly=True)
        data = store.current_prices(
            fuel_type=fuel_type,
            lat=lat,
            lng=lng,
            radius_m=effective_radius,
            sido=sido,
            sigungu=sigungu,
            sort_by=sort,
            limit=limit,
        )
    except FuelStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="오피넷 snapshot을 사용할 수 없습니다",
        ) from exc

    message = None
    if not data:
        if lat is not None and lng is not None:
            message = "현재 반경에서 위치가 확인된 오피넷 가격 정보가 없습니다"
        else:
            message = "저장된 오피넷 가격 정보가 없습니다"
    return ApiResponse(data=data, message=message)
