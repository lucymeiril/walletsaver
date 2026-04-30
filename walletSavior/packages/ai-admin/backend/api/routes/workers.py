"""Workers dry-run 라우트.

POST /api/workers/{role}/dry-run — body로 받은 AIJobBatch를 해당 role worker에
넣고 AIWorkerOutput을 반환한다. 실제 provider 호출은 일어나지 않으며,
결정론적 placeholder 결과만 만든다. batch.role이 path role과 일치하지 않으면
shared `ensure_batch_role`이 ValueError를 던지고 400으로 매핑된다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.ai_workers import ensure_batch_role
from core.contracts.ai_pipeline import AIJobBatch, AIWorkerRole

from workers import build_default_registry

router = APIRouter(prefix="/api/workers", tags=["workers"])

# 모든 worker는 stateless이므로 모듈 수준에서 한 번만 만들어 재사용한다.
_REGISTRY = build_default_registry()


@router.get("")
def list_workers() -> dict:
    """등록된 worker 역할 목록 (검수/디버그용)."""
    return {"roles": [role.value for role in _REGISTRY.list_roles()]}


@router.post("/{role}/dry-run")
def dry_run(role: AIWorkerRole, batch: AIJobBatch) -> dict:
    if batch.role != role:
        raise HTTPException(
            status_code=400,
            detail=(
                f"batch.role '{batch.role.value}' does not match path role "
                f"'{role.value}'"
            ),
        )
    try:
        worker = _REGISTRY.get(role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        # 방어적 한 번 더 검사 — worker 내부에서도 ensure_batch_role 호출됨.
        ensure_batch_role(batch, role)
        output = worker.run(batch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return output.model_dump(mode="json")
