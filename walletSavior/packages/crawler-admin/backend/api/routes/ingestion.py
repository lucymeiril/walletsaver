"""대기열(Pending Ingestion) 프록시 API — DB 관리 API로 요청을 전달."""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/ingestions", tags=["ingestions"])

DB_ADMIN_URL = os.getenv(
    "DB_ADMIN_INGESTION_URL", "http://localhost:8002/api/ingestions"
)


class ReviewRequest(BaseModel):
    action: str  # "approve", "reject"
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None
    rejected_reason: Optional[str] = None


@router.get("")
async def list_ingestions(
    status: Optional[str] = Query(None, description="상태 필터"),
    crawler_name: Optional[str] = Query(None, description="크롤러 필터"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """대기열 목록 — DB 관리 API 프록시."""
    params: dict = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if crawler_name:
        params["crawler_name"] = crawler_name
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(DB_ADMIN_URL, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")


@router.get("/{ingestion_id}")
async def get_ingestion(ingestion_id: int):
    """대기열 상세 — DB 관리 API 프록시."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{DB_ADMIN_URL}/{ingestion_id}")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")


@router.post("/{ingestion_id}/crawler-review")
async def crawler_review(ingestion_id: int, body: ReviewRequest):
    """크롤러 관리자 1차 검토 — DB 관리 API 프록시."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{DB_ADMIN_URL}/{ingestion_id}/crawler-review",
                json=body.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")


@router.post("/cleanup")
async def cleanup_ingestions(body: dict):
    """처리 완료 항목 정리 — DB 관리 API 프록시."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DB_ADMIN_URL}/cleanup",
                json=body,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except Exception as exc:
        raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")
