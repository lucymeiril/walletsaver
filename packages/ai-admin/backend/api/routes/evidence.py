"""p1-ai-admin-evidence-schema — brand_alias evidence 적재 endpoint.

AI가 suggested한 brand_alias 근거를 적재하고 운영자가 승인/거절하는 API.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.deps import get_db_session
from storage.repositories import BrandAliasEvidenceRepository

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


class BrandAliasEvidenceIngest(BaseModel):
    brand_alias: str = Field(min_length=1, max_length=200)
    canonical_brand: str = Field(min_length=1, max_length=200)
    source_batch_id: str = Field(min_length=1, max_length=120)
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class BrandAliasEvidenceDecision(BaseModel):
    approved_by: str = Field(default="operator", min_length=1)
    reason: str = Field(default="")


@router.post("/brand-alias", status_code=status.HTTP_200_OK)
def ingest_brand_alias_evidence(
    payload: BrandAliasEvidenceIngest,
    session: Session = Depends(get_db_session),
) -> dict:
    """brand_alias evidence를 적재 (upsert). AI 파이프라인이 배치 처리 중 호출."""
    repo = BrandAliasEvidenceRepository(session)
    result = repo.upsert(
        brand_alias=payload.brand_alias,
        canonical_brand=payload.canonical_brand,
        source_batch_id=payload.source_batch_id,
        evidence_score=payload.evidence_score,
    )
    session.commit()
    return result


@router.get("/brand-alias", status_code=status.HTTP_200_OK)
def list_brand_alias_evidence(
    min_score: float = 0.0,
    session: Session = Depends(get_db_session),
) -> dict:
    """suggested 상태 brand_alias evidence 목록 반환."""
    repo = BrandAliasEvidenceRepository(session)
    items = repo.list_suggested(min_score=min_score)
    return {"items": items, "count": len(items)}


@router.post("/brand-alias/{evidence_id}/approve", status_code=status.HTTP_200_OK)
def approve_brand_alias_evidence(
    evidence_id: str,
    payload: BrandAliasEvidenceDecision,
    session: Session = Depends(get_db_session),
) -> dict:
    """운영자 승인 — status를 approved로 전환."""
    repo = BrandAliasEvidenceRepository(session)
    result = repo.approve(evidence_id, approved_by=payload.approved_by)
    if result is None:
        raise HTTPException(status_code=404, detail=f"evidence {evidence_id} not found")
    session.commit()
    return result


@router.post("/brand-alias/{evidence_id}/reject", status_code=status.HTTP_200_OK)
def reject_brand_alias_evidence(
    evidence_id: str,
    payload: BrandAliasEvidenceDecision,
    session: Session = Depends(get_db_session),
) -> dict:
    """운영자 거절 — status를 rejected로 전환."""
    repo = BrandAliasEvidenceRepository(session)
    result = repo.reject(evidence_id, reason=payload.reason)
    if result is None:
        raise HTTPException(status_code=404, detail=f"evidence {evidence_id} not found")
    session.commit()
    return result
