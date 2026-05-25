"""WalletSavior 사용자 피드백 포워딩 라우트.

클라이언트의 피드백을 ai-admin 백엔드로 전달한다.
AI_ADMIN_URL 환경변수로 ai-admin 주소를 설정 (기본: http://localhost:8001).
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["feedback"])

_AI_ADMIN_URL_DEFAULT = "http://localhost:8001"


def _ai_admin_url() -> str:
    return os.environ.get("AI_ADMIN_URL", _AI_ADMIN_URL_DEFAULT).rstrip("/")


class FeedbackPayload(BaseModel):
    proposal_id: str
    feedback_type: str
    reviewer_id: str = "user"
    details: dict[str, Any] = {}


@router.post("/feedback", status_code=201)
async def submit_feedback(payload: FeedbackPayload) -> dict[str, Any]:
    """사용자 피드백을 ai-admin의 /api/feedback 으로 전달한다."""
    target = f"{_ai_admin_url()}/api/feedback"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(target, json=payload.model_dump())
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"ai-admin 연결 실패: {exc}") from exc

    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"ai-admin 오류: {resp.text}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.json()
