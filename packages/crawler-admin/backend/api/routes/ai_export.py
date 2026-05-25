"""AI 데이터 export 라우트 — 크롤 결과 → RawCrawlRecord 배치.

이 엔드포인트는 ai-admin이 받을 수 있는 형식의 record-safe DTO를 반환할 뿐
public/control DB의 product/offer 테이블에는 절대 쓰지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pipeline.ai_export import (
    RawExportError,
    build_raw_batch,
    fetch_ai_admin_providers,
    forward_raw_records_to_ai_admin,
    to_raw_records_with_invalid_rows,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-export", tags=["ai-export"])


class RawBatchRequest(BaseModel):
    source_name: str = Field(min_length=1, max_length=120)
    crawler_name: str = Field(min_length=1, max_length=120)
    schema_type: str = Field(min_length=1, max_length=60)
    items: list[dict[str, Any]] = Field(default_factory=list)
    source_url: Optional[str] = None
    raw_artifact_uri: Optional[str] = None
    batch_id: Optional[str] = Field(default=None, max_length=120)


class RawBatchResponse(BaseModel):
    batch: dict[str, Any]
    records: list[dict[str, Any]]
    skipped_count: int
    invalid_rows: list[dict[str, Any]] = Field(default_factory=list)


class ForwardToAIRequest(RawBatchRequest):
    ai_admin_base_url: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    ai_admin_api_key: Optional[str] = None
    # rd4-timeout-fix: ai-admin은 batch 당 N×Gemma 라이브 호출(~10-20s/call)을 직렬로 돌리므로
    # 30s 기본은 거의 항상 timeout → 422 가짜 분류된다. 600s 기본, 1800s 상한으로 확장.
    # 사용자 비판: "POST /api/ai-export/raw-records/label HTTP/1.1 422 ... timed out" 무한 반복.
    timeout_seconds: float = Field(default=600.0, gt=0, le=1800)


_ERROR_KIND_STATUS = {
    "timeout": 504,
    "connection": 502,
    "silent_drop": 502,
    "validation": 422,
}


def _status_for_export_error(exc: RawExportError) -> int:
    return _ERROR_KIND_STATUS.get(getattr(exc, "kind", "validation"), 422)


@router.post("/raw-batch", response_model=RawBatchResponse)
async def export_raw_batch(body: RawBatchRequest) -> RawBatchResponse:
    """크롤 item 묶음을 RawCrawlRecord 배치로 변환. 최종 DB 쓰기는 하지 않는다."""
    try:
        batch, records, skipped = build_raw_batch(
            body.items,
            source_name=body.source_name,
            crawler_name=body.crawler_name,
            schema_type=body.schema_type,
            source_url=body.source_url,
            raw_artifact_uri=body.raw_artifact_uri,
            batch_id=body.batch_id,
        )
        _, _, invalid_rows = to_raw_records_with_invalid_rows(
            body.items,
            source_name=body.source_name,
            batch_id=batch.batch_id,
        )
    except RawExportError as exc:
        raise HTTPException(status_code=_status_for_export_error(exc), detail=str(exc))

    return RawBatchResponse(
        batch=batch.model_dump(mode="json"),
        records=[r.model_dump(mode="json") for r in records],
        skipped_count=skipped,
        invalid_rows=invalid_rows,
    )


@router.post("/raw-records/label")
async def forward_raw_records_to_ai(body: ForwardToAIRequest) -> dict[str, Any]:
    """크롤 item 묶음을 변환/분할해 ai-admin labeling ingest API로 전달한다."""
    try:
        return forward_raw_records_to_ai_admin(
            body.items,
            ai_admin_base_url=body.ai_admin_base_url,
            provider_id=body.provider_id,
            source_name=body.source_name,
            crawler_name=body.crawler_name,
            schema_type=body.schema_type,
            source_url=body.source_url,
            raw_artifact_uri=body.raw_artifact_uri,
            batch_id=body.batch_id,
            api_key=body.ai_admin_api_key,
            timeout_seconds=body.timeout_seconds,
        )
    except RawExportError as exc:
        raise HTTPException(status_code=_status_for_export_error(exc), detail=str(exc))


@router.get("/providers")
async def list_ai_providers(
    ai_admin_base_url: str = Query(min_length=1),
    timeout_seconds: float = Query(default=10.0, gt=0, le=30),
) -> dict[str, Any]:
    """Proxy ai-admin provider lookup through crawler-admin to avoid browser CORS."""
    try:
        return fetch_ai_admin_providers(
            ai_admin_base_url=ai_admin_base_url,
            timeout_seconds=timeout_seconds,
        )
    except RawExportError as exc:
        raise HTTPException(status_code=_status_for_export_error(exc), detail=str(exc))
