"""
마트 전단 API — 프론트엔드 '마트 전단' 탭의 데이터 소스.

엔드포인트:
    GET /api/marts              — 마트 목록 + 현재 할인 건수
    GET /api/marts/{store}/deals — 특정 마트의 할인 상품 목록
"""

from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.get("")
async def list_marts(request: Request):
    """
    마트 목록 — 각 마트의 메타 정보 + 현재 진행 중인 할인 건수.

    프론트엔드 MARTS 배열과 동일 shape + deals_count 추가.
    """
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
        return result

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
    return result


@router.get("/{store}/deals")
async def get_mart_deals(request: Request, store: str):
    """
    특정 마트의 할인 상품 — 전단 이미지 + 할인 아이템 목록.

    프론트엔드 MART_DATA[store]와 동일 shape 반환.
    """
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_MART_DATA
        data = MOCK_MART_DATA.get(store)
        if not data:
            raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
        return data

    mart_data = storage.get_mart_deals(store=store)
    if store not in mart_data:
        raise HTTPException(status_code=404, detail=f"마트 '{store}'를 찾을 수 없습니다")
    return mart_data[store]
