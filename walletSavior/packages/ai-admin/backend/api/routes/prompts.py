"""prompt/rulepack 거버넌스 라우트.

shared `PromptGovernanceService`의 상태 전이를 그대로 노출한다. 라우트는
HTTP 입출력과 세션 관리에만 책임이 있고, draft/review/activate/rollback 정책은
서비스 쪽에 둔다.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import AIWorkerRole
from core.contracts.control_plane import PromptPackContract, PromptPackStatus
from core.prompt_governance import PromptGovernanceService

from storage import Database, PromptPackRepository, get_default_database

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def get_db() -> Database:
    return get_default_database()


class DraftSubmitRequest(BaseModel):
    pack_id: str = Field(min_length=1)
    role: AIWorkerRole
    version: str = Field(min_length=1)
    content: str = Field(min_length=1)
    changelog: str = ""
    created_by: str = Field(min_length=1)


class ActivateRequest(BaseModel):
    approved_by: str = Field(min_length=1)


class RollbackRequest(BaseModel):
    requested_by: str = Field(min_length=1)


def _service(session) -> PromptGovernanceService:
    return PromptGovernanceService(PromptPackRepository(session))


def _to_dict(pack: PromptPackContract) -> dict[str, Any]:
    return pack.model_dump(mode="json")


@router.get("")
def list_prompt_packs(
    role: Optional[AIWorkerRole] = None,
    pack_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = PromptPackRepository(session)
        if pack_id is not None:
            packs = repo.list_versions(pack_id)
        else:
            packs = repo.list(role=role)
        return {"items": [_to_dict(p) for p in packs]}


@router.post("", status_code=201)
def submit_draft(
    payload: DraftSubmitRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    pack = PromptPackContract(
        pack_id=payload.pack_id,
        role=payload.role,
        version=payload.version,
        status=PromptPackStatus.DRAFT,
        content=payload.content,
        changelog=payload.changelog,
        created_by=payload.created_by,
    )
    with db.session_scope() as session:
        try:
            _service(session).submit_draft(pack)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_dict(pack)


@router.post("/{pack_id}/{version}/request-review")
def request_review(
    pack_id: str,
    version: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            updated = _service(session).request_review(pack_id, version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_dict(updated)


@router.post("/{pack_id}/{version}/activate")
def activate(
    pack_id: str,
    version: str,
    payload: ActivateRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            updated = _service(session).activate(
                pack_id, version, approved_by=payload.approved_by
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_dict(updated)


@router.post("/{pack_id}/{version}/rollback")
def rollback(
    pack_id: str,
    version: str,
    payload: RollbackRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            updated = _service(session).rollback(
                pack_id, version, requested_by=payload.requested_by
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_dict(updated)


@router.get("/{pack_id}/diff")
def diff(
    pack_id: str,
    from_version: str,
    to_version: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            d = _service(session).diff(pack_id, from_version, to_version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "pack_id": d.pack_id,
        "from_version": d.from_version,
        "to_version": d.to_version,
        "added_lines": d.added_lines,
        "removed_lines": d.removed_lines,
    }
