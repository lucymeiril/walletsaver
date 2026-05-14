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


_ALL_MARTS = {
    "emart": {"name": "이마트", "color": "#FFD700"},
    "homeplus": {"name": "홈플러스", "color": "#FF6B35"},
    "lottemart": {"name": "롯데마트", "color": "#E4002B"},
    "costco": {"name": "코스트코", "color": "#E31837"},
}


@router.get("")
async def list_marts(request: Request):
    """마트 목록 — 항상 4개 마트를 반환 (데이터 없는 마트는 deals_count=0)."""
    storage = request.app.state.storage
    mart_data = storage.get_mart_deals() if storage else {}

    result = []
    for key, meta in _ALL_MARTS.items():
        data = mart_data.get(key, {})
        result.append({
            "key": key,
            "name": data.get("name", meta["name"]),
            "color": data.get("color", meta["color"]),
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
    """마트별 프로모션/세일 — DB에서 조회."""
    db_store = _STORE_ALIAS.get(store, store)
    storage = request.app.state.storage
    if storage is None:
        # DB 미연결 시 빈 결과 반환
        mart_meta = {
            "emart": {"name": "이마트", "color": "#FFD700"},
            "homeplus": {"name": "홈플러스", "color": "#FF6B35"},
            "lotte": {"name": "롯데마트", "color": "#E4002B"},
            "costco": {"name": "코스트코", "color": "#E31837"},
        }
        meta = mart_meta.get(store, {"name": store, "color": "#666"})
        return ApiResponse(data={"name": meta["name"], "color": meta["color"], "items": [], "last_crawled_at": ""})

    # DB 조회 — 데이터가 없으면 빈 items 반환 (404 대신)
    mart_meta = {
        "emart": {"name": "이마트", "color": "#FFD700"},
        "homeplus": {"name": "홈플러스", "color": "#FF6B35"},
        "lottemart": {"name": "롯데마트", "color": "#E4002B"},
        "costco": {"name": "코스트코", "color": "#E31837"},
    }
    mart_data = storage.get_mart_deals(store=db_store)
    if db_store not in mart_data:
        if db_store not in mart_meta:
            raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다.")
        meta = mart_meta.get(db_store, {"name": store, "color": "#666"})
        return ApiResponse(data={
            "name": meta["name"],
            "color": meta["color"],
            "items": [],
            "last_crawled_at": "",
        })
    return ApiResponse(data=mart_data[db_store])
