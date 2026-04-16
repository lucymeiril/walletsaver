"""활동 추적 API — 사용자 행동 기록 + 추천

엔드포인트:
    POST /api/activity/track           — 활동 기록 (fire-and-forget)
    GET  /api/activity/recommendations — 카테고리 기반 추천
"""

import logging
import time
import threading
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc

from api.schemas.common import ApiResponse
from api.middleware.auth import require_auth, get_current_user
from services.db import managed_session
from storage.models import UserActivity, Product

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/activity", tags=["활동 추적"])


# ── 인메모리 rate limit + 배치 버퍼 ──

_last_write: dict[int, float] = {}
_RATE_LIMIT_SECONDS = 5

_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_BUFFER_MAX = 10
_BUFFER_FLUSH_INTERVAL = 30
_last_flush = time.time()


def _flush_buffer():
    """버퍼의 활동 데이터를 DB에 일괄 저장"""
    global _last_flush
    with _buffer_lock:
        if not _buffer:
            return
        items = _buffer.copy()
        _buffer.clear()
        _last_flush = time.time()

    try:
        with managed_session() as session:
            for item in items:
                activity = UserActivity(
                    user_id=item["user_id"],
                    activity_type=item["activity_type"],
                    target_type=item.get("target_type"),
                    target_id=item.get("target_id"),
                    metadata_=item.get("metadata"),
                )
                session.add(activity)
    except Exception:
        logger.exception("활동 버퍼 플러시 실패")


def _maybe_flush():
    """버퍼 크기 또는 시간 조건 충족 시 플러시"""
    should_flush = False
    with _buffer_lock:
        if len(_buffer) >= _BUFFER_MAX:
            should_flush = True
        elif time.time() - _last_flush >= _BUFFER_FLUSH_INTERVAL and _buffer:
            should_flush = True
    if should_flush:
        _flush_buffer()


# ── Pydantic 스키마 ──

class ActivityTrack(BaseModel):
    activity_type: str  # view / search / cart_add / wishlist_add / vote
    target_type: Optional[str] = None  # product / post / hotdeal
    target_id: Optional[str] = None
    metadata: Optional[dict] = None


# ── 엔드포인트 ──

@router.post("/track")
async def track_activity(body: ActivityTrack, user: dict = Depends(require_auth)):
    """활동 기록 — rate limit: 사용자당 5초에 1회"""
    valid_types = {"view", "search", "cart_add", "wishlist_add", "vote"}
    if body.activity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"activity_type은 {valid_types} 중 하나여야 합니다")

    now = time.time()
    last = _last_write.get(user["id"], 0)
    if now - last < _RATE_LIMIT_SECONDS:
        return ApiResponse(data={"status": "rate_limited"})

    _last_write[user["id"]] = now

    with _buffer_lock:
        _buffer.append({
            "user_id": user["id"],
            "activity_type": body.activity_type,
            "target_type": body.target_type,
            "target_id": body.target_id,
            "metadata": body.metadata,
        })

    _maybe_flush()
    return ApiResponse(data={"status": "tracked"})


@router.get("/recommendations")
async def get_recommendations(
    user: Optional[dict] = Depends(get_current_user),
    limit: int = Query(10, ge=1, le=50),
):
    """카테고리 빈도 기반 추천 — 비로그인 시 인기 상품 반환"""
    with managed_session() as session:
        if not user:
            # 비로그인: 전체 인기 상품
            products = session.execute(
                select(Product).where(Product.is_active == True).limit(limit)
            ).scalars().all()
            return ApiResponse(data=[
                {"id": p.id, "name": p.name, "category": p.category_id, "image_url": p.image_url}
                for p in products
            ])

        # 버퍼 플러시 (최신 데이터 반영)
        _flush_buffer()

        # 사용자 활동에서 카테고리 빈도 집계
        activities = session.execute(
            select(UserActivity)
            .where(UserActivity.user_id == user["id"])
            .order_by(desc(UserActivity.created_at))
            .limit(100)
        ).scalars().all()

        category_freq: dict[str, int] = defaultdict(int)
        for a in activities:
            meta = a.metadata_ or {}
            cat = meta.get("category")
            if cat:
                category_freq[cat] += 1

            # target이 product면 카테고리 조회
            if a.target_type == "product" and a.target_id:
                try:
                    product = session.get(Product, int(a.target_id))
                    if product and product.category_id:
                        category_freq[product.category_id] += 1
                except (ValueError, TypeError):
                    pass

        if not category_freq:
            products = session.execute(
                select(Product).where(Product.is_active == True).limit(limit)
            ).scalars().all()
            return ApiResponse(data=[
                {"id": p.id, "name": p.name, "category": p.category_id, "image_url": p.image_url}
                for p in products
            ])

        # 빈도 높은 카테고리 상품 추천
        top_categories = sorted(category_freq, key=category_freq.get, reverse=True)[:5]
        recommended = []
        for cat in top_categories:
            products = session.execute(
                select(Product)
                .where(Product.category_id == cat, Product.is_active == True)
                .limit(limit // len(top_categories) + 1)
            ).scalars().all()
            for p in products:
                if len(recommended) >= limit:
                    break
                recommended.append({
                    "id": p.id,
                    "name": p.name,
                    "category": p.category_id,
                    "image_url": p.image_url,
                })
            if len(recommended) >= limit:
                break

        return ApiResponse(data=recommended[:limit])
