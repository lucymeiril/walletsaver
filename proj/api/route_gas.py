"""
주유소 API — 프론트엔드 '주유소' 탭의 데이터 소스.

엔드포인트:
    GET /api/gas — 주유소 목록 (연료별 최저가 정렬)
"""

from fastapi import APIRouter, Request, Query

router = APIRouter()


@router.get("")
async def list_gas_stations(
    request: Request,
    fuel: str = Query("gasoline", description="연료 종류 (gasoline, diesel, lpg)"),
    sort: str = Query("price", description="정렬 기준 (price, name)"),
):
    """
    주유소 목록 — 연료 종류별 가격 정렬.

    프론트엔드 GAS_STATIONS 배열과 동일 shape 반환.
    """
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_GAS_STATIONS
        stations = list(MOCK_GAS_STATIONS)

        if sort == "price":
            # 연료 종류에 따라 가격 정렬 (None은 뒤로)
            def sort_key(s):
                price = s.get(fuel)
                return price if price is not None else float("inf")
            stations.sort(key=sort_key)
        else:
            stations.sort(key=lambda s: s["name"])

        return stations

    return storage.get_gas_prices(fuel_type=fuel, sort_by=sort)
