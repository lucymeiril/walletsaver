"""
사용자 API — 즐겨찾기, 가격 알림, 장바구니 최적화.

엔드포인트:
    GET    /api/users/{uid}/favorites                — 즐겨찾기 목록
    POST   /api/users/{uid}/favorites                — 즐겨찾기 추가
    DELETE /api/users/{uid}/favorites/{product_id}    — 즐겨찾기 제거
    POST   /api/users/{uid}/alerts                   — 가격 알림 설정
    GET    /api/users/{uid}/alerts                   — 알림 목록
    GET    /api/users/{uid}/shopping-list/optimize    — 장보기 최적화
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


class FavoriteRequest(BaseModel):
    """즐겨찾기 추가 요청."""
    product_id: int


class AlertRequest(BaseModel):
    """가격 알림 설정 요청."""
    product_id: int
    target_price: int


@router.get("/{uid}/favorites")
async def get_favorites(request: Request, uid: str):
    """사용자 즐겨찾기 목록."""
    storage = request.app.state.storage
    if storage is None:
        return []
    return storage.get_user_favorites(uid)


@router.post("/{uid}/favorites")
async def add_favorite(request: Request, uid: str, body: FavoriteRequest):
    """즐겨찾기 추가."""
    storage = request.app.state.storage
    if storage is None:
        return {"user_id": uid, "product_id": body.product_id, "status": "added (mock)"}
    return storage.add_user_favorite(uid, body.product_id)


@router.delete("/{uid}/favorites/{product_id}")
async def remove_favorite(request: Request, uid: str, product_id: int):
    """즐겨찾기 제거."""
    storage = request.app.state.storage
    if storage is None:
        return {"status": "removed (mock)"}
    return storage.remove_user_favorite(uid, product_id)


@router.post("/{uid}/alerts")
async def create_alert(request: Request, uid: str, body: AlertRequest):
    """가격 알림 설정 — 목표 가격 이하 시 알림."""
    storage = request.app.state.storage
    if storage is None:
        return {
            "id": 1,
            "product_id": body.product_id,
            "target_price": body.target_price,
            "status": "active (mock)",
        }
    return storage.add_price_alert(uid, body.product_id, body.target_price)


@router.get("/{uid}/alerts")
async def get_alerts(request: Request, uid: str):
    """사용자 가격 알림 목록."""
    storage = request.app.state.storage
    if storage is None:
        return []
    return storage.get_user_alerts(uid)


@router.get("/{uid}/shopping-list/optimize")
async def optimize_shopping(request: Request, uid: str):
    """
    장보기 최적화 — 즐겨찾기 품목들을 어느 마트에서 사면 최저인지 계산.

    알고리즘:
        1. 사용자 즐겨찾기 품목 조회
        2. 각 품목의 매장별 최저가 조회
        3. 매장별 총액 비교 → 최적 매장 추천
    """
    storage = request.app.state.storage
    if storage is None:
        # mock: 장보기 최적화 예시 응답
        from api.mock_responses import MOCK_PRODUCTS
        sample = MOCK_PRODUCTS[:5]
        stores = {"emart": 0, "homeplus": 0, "lotte": 0, "costco": 0}
        items = []
        for p in sample:
            best_store = min(p["stores"], key=p["stores"].get)
            best_price = p["stores"][best_store]
            items.append({
                "product_id": p["id"],
                "name": p["name"],
                "best_store": best_store,
                "best_price": best_price,
                "avg": p["avg"],
                "savings": p["avg"] - best_price,
            })
            for store, price in p["stores"].items():
                stores[store] += price

        best = min(stores, key=stores.get)
        return {
            "best_store": best,
            "total_by_store": stores,
            "items": items,
            "total_savings": sum(i["savings"] for i in items),
        }

    # 실제 DB 기반 최적화 (향후 구현)
    favorites = storage.get_user_favorites(uid)
    if not favorites:
        return {"message": "즐겨찾기 품목이 없습니다", "items": []}

    products = storage.get_products()
    fav_ids = {f["product_id"] for f in favorites}
    fav_products = [p for p in products if p["id"] in fav_ids]

    stores_total: dict[str, int] = {}
    items = []
    for p in fav_products:
        if not p.get("stores"):
            continue
        best_store = min(p["stores"], key=p["stores"].get)
        best_price = p["stores"][best_store]
        items.append({
            "product_id": p["id"],
            "name": p["name"],
            "best_store": best_store,
            "best_price": best_price,
            "avg": p["avg"],
            "savings": p["avg"] - best_price,
        })
        for store, price in p["stores"].items():
            stores_total[store] = stores_total.get(store, 0) + price

    best = min(stores_total, key=stores_total.get) if stores_total else ""
    return {
        "best_store": best,
        "total_by_store": stores_total,
        "items": items,
        "total_savings": sum(i["savings"] for i in items),
    }
