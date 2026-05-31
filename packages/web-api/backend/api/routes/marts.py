"""
마트 API — 프론트엔드 '마트 전단' 탭의 데이터 소스.

엔드포인트:
    GET /api/marts                    — 마트 목록
    GET /api/marts/{name}/promotions  — 마트별 프로모션
    GET /api/marts/{store}/flyers     — 마트별 전단지 이미지/링크
    GET /api/marts/flyers             — 전체 마트 전단지 정보
"""

import logging
from fastapi import APIRouter, Request, HTTPException
from api.schemas.common import ApiResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_marts(request: Request):
    """마트 목록."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

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


@router.get("/flyers")
async def get_all_flyers():
    """전체 마트 전단지 정보."""
    from services.flyer_service import get_all_flyer_data
    try:
        data = await get_all_flyer_data()
        return ApiResponse(data=data)
    except Exception as e:
        logger.error("전단지 전체 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="전단지 데이터를 불러올 수 없습니다")


@router.get("/{store}/flyers")
async def get_store_flyers(store: str):
    """마트별 전단지 이미지/링크."""
    from services.flyer_service import get_flyer_data
    data = await get_flyer_data(store)
    if data is None:
        raise HTTPException(status_code=404, detail=f"마트 '{store}'의 전단지를 찾을 수 없습니다")
    return ApiResponse(data=data)


@router.get("/{store}/promotions")
async def get_mart_promotions(request: Request, store: str):
    """마트별 프로모션/세일."""
    db_store = _STORE_ALIAS.get(store, store)
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="마트 DB 연결이 없습니다")

    mart_data = storage.get_mart_deals(store=db_store)
    if db_store not in mart_data:
        raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
    return ApiResponse(data=mart_data[db_store])
