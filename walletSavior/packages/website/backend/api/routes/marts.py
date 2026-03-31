"""
마트 API — 프론트엔드 '마트 전단' 탭의 데이터 소스.

엔드포인트:
    GET /api/marts                    — 마트 목록
    GET /api/marts/{name}/promotions  — 마트별 프로모션
"""

from fastapi import APIRouter, Request, HTTPException
from api.schemas.common import ApiResponse

router = APIRouter()


@router.get("")
async def list_marts(request: Request):
    """마트 목록."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_MARTS, MOCK_MART_DATA
        result = []
        for mart in MOCK_MARTS:
            data = MOCK_MART_DATA.get(mart["key"], {})
            result.append({
                **mart,
                "deals_count": len(data.get("items", [])),
                "period": data.get("period", ""),
            })
        return ApiResponse(data=result)

    mart_data = storage.get_mart_deals()
    result = []
    for key, data in mart_data.items():
        result.append({
            "key": key,
            "name": data["name"],
            "color": data["color"],
            "deals_count": len(data.get("items", [])),
            "period": data.get("period", ""),
        })
    return ApiResponse(data=result)


# 프론트엔드 key → DB source 매핑 (프론트엔드는 "lotte", DB는 "lottemart")
_STORE_ALIAS = {"lotte": "lottemart"}


@router.get("/{store}/promotions")
async def get_mart_promotions(request: Request, store: str):
    """마트별 프로모션/세일."""
    db_store = _STORE_ALIAS.get(store, store)
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_MART_DATA
        data = MOCK_MART_DATA.get(store)
        if not data:
            raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
        return ApiResponse(data=data)

    mart_data = storage.get_mart_deals(store=db_store)
    if db_store not in mart_data:
        raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
    return ApiResponse(data=mart_data[db_store])
