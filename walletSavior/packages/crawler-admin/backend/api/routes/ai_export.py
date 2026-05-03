"""AI 데이터 export 라우트 — 크롤 결과 → RawCrawlRecord 배치.

이 엔드포인트는 ai-admin이 받을 수 있는 형식의 record-safe DTO를 반환할 뿐
public/control DB의 product/offer 테이블에는 절대 쓰지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pipeline.ai_export import (
    RawExportError,
    build_raw_batch,
    forward_raw_records_to_ai_admin,
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


class ForwardToAIRequest(RawBatchRequest):
    ai_admin_base_url: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    ai_admin_api_key: Optional[str] = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)


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
    except RawExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return RawBatchResponse(
        batch=batch.model_dump(mode="json"),
        records=[r.model_dump(mode="json") for r in records],
        skipped_count=skipped,
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
        raise HTTPException(status_code=422, detail=str(exc))
