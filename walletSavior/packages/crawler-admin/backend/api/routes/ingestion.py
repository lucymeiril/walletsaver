"""대기열(Pending Ingestion) 프록시 API — DB 관리 API로 요청을 전달."""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.app import limiter
from api.security.input_schemas import CleanupRequest
from audit import audit_log, AuditEventType
from pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError
from pipeline.db_admin_auth import get_db_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingestions", tags=["ingestions"])

DB_ADMIN_URL = os.getenv(
    "DB_ADMIN_INGESTION_URL", "http://localhost:8002/api/ingestions"
)

# Circuit breaker: fast-fail after 3 consecutive failures, 30s cooldown
_cb = CircuitBreaker(service_name="db-admin", failure_threshold=3, recovery_timeout=30.0)


class ReviewRequest(BaseModel):
    action: str  # "approve", "reject"
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None
    rejected_reason: Optional[str] = None


class RowUpdateRequest(BaseModel):
    item: dict
    notes: Optional[str] = None


async def _proxy(method: str, url: str, **kwargs):
    """Execute a proxied HTTP request with circuit breaker + JWT auth."""
    try:
        auth = get_db_admin_auth()
        auth_headers = await auth.get_headers()
        hdrs = kwargs.pop("headers", {}) or {}
        hdrs.update(auth_headers)
        async with _cb:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await getattr(client, method)(url, headers=hdrs, **kwargs)
                if resp.status_code == 401:
                    hdrs.update(await auth.handle_401())
                    resp = await getattr(client, method)(url, headers=hdrs, **kwargs)
                resp.raise_for_status()
                return resp.json()
    except CircuitOpenError:
        raise HTTPException(
            status_code=503,
            detail="DB 관리 서비스가 일시적으로 사용 불가합니다. 잠시 후 다시 시도해 주세요.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("DB 관리 API 연결 실패: %s", exc)
        raise HTTPException(502, "DB 관리 API에 연결할 수 없습니다.")


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
    return await _proxy("get", DB_ADMIN_URL, params=params)


@router.get("/{ingestion_id}")
async def get_ingestion(ingestion_id: int):
    """대기열 상세 — DB 관리 API 프록시."""
    return await _proxy("get", f"{DB_ADMIN_URL}/{ingestion_id}")


@router.post("/{ingestion_id}/crawler-review")
async def crawler_review(ingestion_id: int, request: Request, body: ReviewRequest):
    """크롤러 관리자 1차 검토 — DB 관리 API 프록시."""
    audit_log(
        AuditEventType.DATA_INGESTION,
        request=request,
        detail={"ingestion_id": ingestion_id, "action": body.action},
    )
    return await _proxy(
        "post",
        f"{DB_ADMIN_URL}/{ingestion_id}/crawler-review",
        json=body.model_dump(),
    )


@router.put("/{ingestion_id}/items/{item_index}")
async def update_ingestion_item(
    ingestion_id: int,
    item_index: int,
    request: Request,
    body: RowUpdateRequest,
):
    """대기열 상세 행 수정 — DB 관리 API 프록시."""
    audit_log(
        AuditEventType.DATA_INGESTION,
        request=request,
        detail={"ingestion_id": ingestion_id, "item_index": item_index, "action": "row_update"},
    )
    return await _proxy(
        "put",
        f"{DB_ADMIN_URL}/{ingestion_id}/items/{item_index}",
        json=body.model_dump(),
    )


@router.delete("/{ingestion_id}/items/{item_index}")
async def remove_ingestion_item(
    ingestion_id: int,
    item_index: int,
    request: Request,
    notes: Optional[str] = Query(None),
):
    """대기열 상세 행 제외/삭제 — DB 관리 API 프록시."""
    audit_log(
        AuditEventType.DATA_INGESTION,
        request=request,
        detail={"ingestion_id": ingestion_id, "item_index": item_index, "action": "row_remove"},
    )
    params = {"notes": notes} if notes else None
    return await _proxy(
        "delete",
        f"{DB_ADMIN_URL}/{ingestion_id}/items/{item_index}",
        params=params,
    )


@router.post("/cleanup")
async def cleanup_ingestions(body: CleanupRequest):
    """처리 완료 항목 정리 — DB 관리 API 프록시."""
    return await _proxy(
        "post",
        f"{DB_ADMIN_URL}/cleanup",
        json=body.model_dump(exclude_none=True),
    )


@router.delete("/{ingestion_id}")
async def delete_ingestion(ingestion_id: int, request: Request):
    """개별 대기열 항목 삭제 — DB 관리 API 프록시."""
    audit_log(
        AuditEventType.DATA_INGESTION,
        request=request,
        detail={"ingestion_id": ingestion_id, "action": "delete"},
    )
    return await _proxy("delete", f"{DB_ADMIN_URL}/{ingestion_id}")
