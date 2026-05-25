"""Raw crawl -> provider labeling -> review proposals API."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from core.contracts.ai_pipeline import MAX_AI_BATCH_ITEMS, RawCrawlRecord
from api.deps import get_db_session
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from services.ai_ingestion import AIIngestionError, WALLETSAVIOR_LIVE_AI_ENABLED, ingest_and_label_records
from storage.models import (
    FieldProposal as FieldProposalModel,
    KeywordProposal as KeywordProposalModel,
    RawCrawlBatch as RawCrawlBatchModel,
    RawCrawlRecord as RawCrawlRecordModel,
)

_logger = logging.getLogger("walletsavior.ai_admin.ingest")

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestLabelPayload(BaseModel):
    provider_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    crawler_name: str = Field(default="manual-ai-smoke", min_length=1)
    schema_type: str = Field(default="product_offer", min_length=1)
    records: list[RawCrawlRecord] = Field(min_length=1, max_length=30)
    max_ai_batch_items: int | None = Field(default=None, ge=1, le=MAX_AI_BATCH_ITEMS)
    max_ai_batch_prompt_chars: int | None = Field(default=None, ge=1, le=60_000)
    max_provider_calls: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Per-request cap for live provider attempts, including retries.",
    )


@router.post("/raw-records/label", status_code=status.HTTP_200_OK)
def label_raw_records(
    payload: IngestLabelPayload,
    session: Session = Depends(get_db_session),
) -> dict:
    try:
        return ingest_and_label_records(
            session=session,
            provider_id=payload.provider_id,
            source_name=payload.source_name,
            crawler_name=payload.crawler_name,
            schema_type=payload.schema_type,
            records=payload.records,
            max_ai_batch_items=payload.max_ai_batch_items,
            max_ai_batch_prompt_chars=payload.max_ai_batch_prompt_chars,
            max_provider_calls=payload.max_provider_calls,
        )
    except AIIngestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.to_detail(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# rd5-process-missing: 사용자 헌법 — "AI 처리 가동 (E)" 버튼이 422 나지 않도록
# 라벨링 워커를 동기로 한 번에 실행한다. POST /api/jobs 의 단순 enqueue 는 워커
# 자동 가동을 보장하지 않아 사용자가 "961건 그대로" 라며 직격했다.
# ---------------------------------------------------------------------------


class ProcessMissingPayload(BaseModel):
    provider_id: str = Field(min_length=1)
    limit: int = Field(default=30, ge=1, le=MAX_AI_BATCH_ITEMS)
    dry_run: bool = Field(default=False)
    max_ai_batch_items: int | None = Field(default=None, ge=1, le=MAX_AI_BATCH_ITEMS)
    max_ai_batch_prompt_chars: int | None = Field(default=None, ge=1, le=60_000)
    max_provider_calls: int | None = Field(default=None, ge=1, le=100)


def _select_missing_raw_records(
    session: Session, limit: int
) -> list[RawCrawlRecordModel]:
    """raw_crawl_records 중 활성 FieldProposal 이 하나도 없는 행을 ``limit`` 만큼."""
    active_raw_ids: set[str] = set()
    for row in session.execute(select(FieldProposalModel.provenance)).all():
        prov = row[0] or {}
        raw_id = prov.get("raw_record_id") if isinstance(prov, dict) else None
        if raw_id:
            active_raw_ids.add(str(raw_id))
    stmt = select(RawCrawlRecordModel).order_by(RawCrawlRecordModel.crawled_at.asc())
    rows: list[RawCrawlRecordModel] = []
    for row in session.execute(stmt).scalars():
        if row.raw_record_id in active_raw_ids:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _resolve_batch_metadata(
    session: Session, raw_records: list[RawCrawlRecordModel]
) -> tuple[str, str, str]:
    """raw 행들의 원본 배치에서 source_name/crawler_name/schema_type 을 추론."""
    if not raw_records:
        return ("missing-backfill", "missing-backfill", "product_offer")
    batch_ids = {r.batch_id for r in raw_records if r.batch_id}
    if not batch_ids:
        first = raw_records[0]
        return (first.source_name or "missing-backfill", "missing-backfill", "product_offer")
    pick = next(iter(batch_ids))
    batch = session.get(RawCrawlBatchModel, pick)
    if batch is None:
        first = raw_records[0]
        return (first.source_name or "missing-backfill", "missing-backfill", "product_offer")
    return (
        batch.source_name or raw_records[0].source_name or "missing-backfill",
        batch.crawler_name or "missing-backfill",
        batch.schema_type or "product_offer",
    )


@router.post("/process-missing", status_code=status.HTTP_200_OK)
def process_missing_proposals(
    payload: ProcessMissingPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    if not WALLETSAVIOR_LIVE_AI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "deprecated",
                "detail": "live AI pipeline disabled; export to external classifier",
            },
        )
    
    started_at = time.monotonic()
    missing_rows = _select_missing_raw_records(session, payload.limit)
    if not missing_rows:
        return {
            "ok": True,
            "processed": 0,
            "proposals_created": 0,
            "errors": [],
            "provider_id": payload.provider_id,
            "dry_run": payload.dry_run,
            "missing_remaining": 0,
            "latency_ms": int((time.monotonic() - started_at) * 1000),
        }

    if payload.dry_run:
        # 추가로 남아있는 missing 행 개수도 같이 보고해서 UI 가 "딸깍" 반복 호출 여부를 결정할 수 있게.
        # 아래 fast path: 전체 missing 카운트 가벼운 추정 (provider lookup 없이).
        total_missing = _count_missing(session)
        return {
            "ok": True,
            "processed": 0,
            "proposals_created": 0,
            "errors": [],
            "provider_id": payload.provider_id,
            "dry_run": True,
            "would_process": [r.raw_record_id for r in missing_rows],
            "missing_remaining": total_missing,
            "latency_ms": int((time.monotonic() - started_at) * 1000),
        }

    source_name, crawler_name, schema_type = _resolve_batch_metadata(session, missing_rows)
    records: list[RawCrawlRecord] = [
        RawCrawlRecord(
            raw_record_id=row.raw_record_id,
            source_name=row.source_name,
            source_record_key=row.source_record_key,
            source_url=row.source_url,
            raw_title=row.raw_title,
            raw_price=row.raw_price,
            raw_payload=row.raw_payload or {},
            crawled_at=row.crawled_at or datetime.now(),
        )
        for row in missing_rows
    ]
    errors: list[dict[str, Any]] = []
    try:
        result = ingest_and_label_records(
            session=session,
            provider_id=payload.provider_id,
            source_name=source_name,
            crawler_name=crawler_name,
            schema_type=schema_type,
            records=records,
            max_ai_batch_items=payload.max_ai_batch_items,
            max_ai_batch_prompt_chars=payload.max_ai_batch_prompt_chars,
            max_provider_calls=payload.max_provider_calls,
        )
    except AIIngestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.to_detail()
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    proposals_created = int(result.get("proposals_stored", 0))
    processed = int(result.get("records_stored", len(records)))
    missing_label_ids = list(result.get("missing_label_raw_record_ids") or [])
    for raw_id in missing_label_ids:
        errors.append({"raw_record_id": raw_id, "reason": "provider returned no usable item"})
    remaining = _count_missing(session)
    latency_ms = int((time.monotonic() - started_at) * 1000)
    _logger.info(
        "process_missing provider=%s processed=%d proposals=%d remaining=%d latency_ms=%d",
        payload.provider_id,
        processed,
        proposals_created,
        remaining,
        latency_ms,
    )
    return {
        "ok": True,
        "processed": processed,
        "proposals_created": proposals_created,
        "errors": errors,
        "provider_id": payload.provider_id,
        "dry_run": False,
        "missing_remaining": remaining,
        "raw_batch_id": result.get("raw_batch_id"),
        "status": result.get("status"),
        "latency_ms": latency_ms,
    }


def _count_missing(session: Session) -> int:
    active_raw_ids: set[str] = set()
    for row in session.execute(select(FieldProposalModel.provenance)).all():
        prov = row[0] or {}
        raw_id = prov.get("raw_record_id") if isinstance(prov, dict) else None
        if raw_id:
            active_raw_ids.add(str(raw_id))
    total = 0
    for row in session.execute(select(RawCrawlRecordModel.raw_record_id)).all():
        if row[0] not in active_raw_ids:
            total += 1
    return total


# ---------------------------------------------------------------------------
# rd5-raw-clear-all: "raw 레코드 비우기 (위험)" — DB 를 처음부터 다시 시작할 때.
# 기본 dry_run=true 라 실수로 날아가지 않는다. include_proposed=false 이면
# 이미 AI 가 제안을 만든 raw 행은 보호한다 (= proposal 이 있는 raw_record_id 는 skip).
# ---------------------------------------------------------------------------


class RawClearAllPayload(BaseModel):
    include_proposed: bool = Field(default=False)
    dry_run: bool = Field(default=True)
    reviewer_id: str = Field(default="operator", min_length=1)
    reason: str = Field(default="manual raw reset", min_length=1, max_length=500)


@router.post("/raw-records/clear-all", status_code=status.HTTP_200_OK)
def clear_all_raw_records(
    payload: RawClearAllPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    started_at = time.monotonic()
    proposed_ids: set[str] = set()
    if not payload.include_proposed:
        for row in session.execute(select(FieldProposalModel.provenance)).all():
            prov = row[0] or {}
            raw_id = prov.get("raw_record_id") if isinstance(prov, dict) else None
            if raw_id:
                proposed_ids.add(str(raw_id))
    target_rows = [
        rid
        for (rid,) in session.execute(select(RawCrawlRecordModel.raw_record_id)).all()
        if rid not in proposed_ids
    ]
    protected = sum(
        1 for (rid,) in session.execute(select(RawCrawlRecordModel.raw_record_id)).all()
        if rid in proposed_ids
    )
    if payload.dry_run:
        _logger.info(
            "raw_records.clear_all dry_run reviewer=%s would_delete=%d protected=%d",
            payload.reviewer_id, len(target_rows), protected,
        )
        return {
            "ok": True,
            "dry_run": True,
            "would_delete": len(target_rows),
            "protected_with_proposals": protected,
            "include_proposed": payload.include_proposed,
            "latency_ms": int((time.monotonic() - started_at) * 1000),
        }

    deleted_records = 0
    if target_rows:
        deleted_records = session.execute(
            sa_delete(RawCrawlRecordModel).where(
                RawCrawlRecordModel.raw_record_id.in_(target_rows)
            )
        ).rowcount or 0
    # 비어버린 batch 도 함께 청소 (cascade 가 child 만 처리하므로 부모 row 는 명시 삭제).
    batches_to_check = session.execute(select(RawCrawlBatchModel.batch_id)).all()
    deleted_batches = 0
    for (bid,) in batches_to_check:
        remaining = session.execute(
            select(RawCrawlRecordModel.raw_record_id).where(
                RawCrawlRecordModel.batch_id == bid
            ).limit(1)
        ).first()
        if remaining is None:
            session.execute(
                sa_delete(RawCrawlBatchModel).where(RawCrawlBatchModel.batch_id == bid)
            )
            deleted_batches += 1
    if payload.include_proposed:
        # proposal 도 같이 비우는 게 안전 (raw 가 사라지면 orphan).
        session.execute(sa_delete(FieldProposalModel))
        session.execute(sa_delete(KeywordProposalModel))
    session.flush()
    _logger.warning(
        "raw_records.clear_all EXECUTED reviewer=%s reason=%s deleted_records=%d deleted_batches=%d include_proposed=%s",
        payload.reviewer_id, payload.reason, deleted_records, deleted_batches, payload.include_proposed,
    )
    return {
        "ok": True,
        "dry_run": False,
        "deleted_records": deleted_records,
        "deleted_batches": deleted_batches,
        "protected_with_proposals": protected,
        "include_proposed": payload.include_proposed,
        "reviewer_id": payload.reviewer_id,
        "reason": payload.reason,
        "latency_ms": int((time.monotonic() - started_at) * 1000),
    }
