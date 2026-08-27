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


# Public UI keys are stable even when the catalog has no recent rows for a mart.
# The DB uses "lottemart" while the frontend uses "lotte".
_SUPPORTED_MARTS = (
    ("emart", "emart", "이마트", "#FFD700"),
    ("homeplus", "homeplus", "홈플러스", "#FF6B35"),
    ("lotte", "lottemart", "롯데마트", "#E4002B"),
    ("costco", "costco", "코스트코", "#E31837"),
)

# 프론트엔드 key → DB source 매핑 (프론트엔드는 "lotte", DB는 "lottemart")
_STORE_ALIAS = {public_key: db_key for public_key, db_key, _, _ in _SUPPORTED_MARTS}


@router.get("")
async def list_marts(request: Request):
    """지원 마트 목록과 각 마트의 최근 프로모션 개수를 반환한다.

    예전 구현은 모든 마트를 합쳐 최신 50개 기록을 먼저 자른 뒤 그룹화해서,
    최근 50개에 들지 못한 마트 자체가 목록에서 사라질 수 있었다. 각 마트를
    개별 조회해 지원하는 네 마트는 데이터 유무와 상관없이 항상 노출한다.
    """
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    result = []
    for public_key, db_key, fallback_name, fallback_color in _SUPPORTED_MARTS:
        mart_data = storage.get_mart_deals(store=db_key)
        data = mart_data.get(db_key, {})
        items = data.get("items", [])
        result.append({
            "key": public_key,
            "name": data.get("name") or fallback_name,
            "color": data.get("color") or fallback_color,
            "deals_count": len(items),
            "period": data.get("period", ""),
            "last_crawled_at": data.get("last_crawled_at", ""),
        })
    return ApiResponse(data=result)


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
        # A supported mart with no recent discount rows is still a valid mart.
        supported = next(
            (item for item in _SUPPORTED_MARTS if item[1] == db_store),
            None,
        )
        if supported is None:
            raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
        _, _, name, color = supported
        return ApiResponse(data={
            "name": name,
            "color": color,
            "items": [],
            "last_crawled_at": "",
        })
    return ApiResponse(data=mart_data[db_store])
