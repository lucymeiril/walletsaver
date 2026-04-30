"""Job queue 라우트 — shared JobQueueService를 HTTP 표면으로 노출한다.

설계 원칙:
    * 상태 전이 정책(lease/heartbeat/retry/backoff)은 모두 shared `JobQueueService`가
      가지므로 라우트는 입력 검증 + 세션 관리 + 예외 매핑만 담당한다.
    * 안전한 기본값을 강제한다: lease_seconds 최소 5초. 0.1초 같은 위험한 값을 막아
      provider 폭주를 예방한다.
    * 다른 ai-admin 라우트 충돌을 줄이기 위해 별도 파일에 격리되어 있고
      `api.app`에서만 include 한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import AIWorkerRole
from core.contracts.control_plane import (
    ControlJobContract,
    ControlJobStatus,
    RetryPolicyContract,
)
from core.job_queue import JobQueueService

from storage.database import Database, get_default_database
from storage.repositories import JobQueueSqlRepository

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# 안전한 lease 최소값. 0.1초 같은 위험한 단기 lease를 막는다.
MIN_LEASE_SECONDS = 5
DEFAULT_LEASE_SECONDS = 120


def get_db() -> Database:
    """기본 control DB 의존성. 테스트는 dependency_overrides로 교체한다."""
    return get_default_database()


# --------------------------------------------------------------------------------------
# Request payloads
# --------------------------------------------------------------------------------------


class EnqueueJobRequest(BaseModel):
    """ControlJobContract에 들어갈 최소 필드. 서버가 created_at/updated_at을 채운다."""

    job_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    role: AIWorkerRole
    priority: int = Field(default=100, ge=0, le=1000)
    not_before: Optional[datetime] = None
    retry_policy: Optional[RetryPolicyContract] = None


class AcquireRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    lease_seconds: int = Field(default=DEFAULT_LEASE_SECONDS, ge=MIN_LEASE_SECONDS, le=3600)
    limit: int = Field(default=10, ge=1, le=100)


class HeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    lease_seconds: int = Field(default=DEFAULT_LEASE_SECONDS, ge=MIN_LEASE_SECONDS, le=3600)


class CompleteRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    partial: bool = False


class FailRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    error_summary: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _job_to_dict(job: ControlJobContract) -> dict[str, Any]:
    return job.model_dump(mode="json")


def _service(session) -> JobQueueService:
    return JobQueueService(JobQueueSqlRepository(session))


def _map_transition_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, TimeoutError):
        return HTTPException(status_code=409, detail=f"lease expired: {exc}")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="job transition failed")


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------


@router.get("")
def list_jobs(
    status: Optional[ControlJobStatus] = Query(default=None),
    role: Optional[AIWorkerRole] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """관리자 화면용 목록 조회.

    `status`/`role` 필터를 선택적으로 적용하며, 둘 다 없으면 모든 job을 priority/created_at 순으로 반환한다.
    """
    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        if status is not None:
            jobs = repo.list_by_status(status, limit=limit)
        else:
            from sqlalchemy import select
            from storage.models import AIJob

            stmt = select(AIJob).order_by(AIJob.priority.desc(), AIJob.created_at.asc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
            from storage.repositories import _job_to_contract

            jobs = [_job_to_contract(r) for r in rows]

        if role is not None:
            jobs = [j for j in jobs if j.role == role]

        return {"jobs": [_job_to_dict(j) for j in jobs], "count": len(jobs)}


@router.post("", status_code=201)
def enqueue_job(
    payload: EnqueueJobRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    job = ControlJobContract(
        job_id=payload.job_id,
        batch_id=payload.batch_id,
        role=payload.role,
        status=ControlJobStatus.QUEUED,
        priority=payload.priority,
        not_before=payload.not_before,
        retry_policy=payload.retry_policy or RetryPolicyContract(),
        created_at=now,
        updated_at=now,
    )
    with db.session_scope() as session:
        service = _service(session)
        existing = service.repository.get(job.job_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"job already exists: {job.job_id}")
        try:
            service.enqueue(job)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": _job_to_dict(job)}


@router.post("/acquire")
def acquire_next(
    payload: AcquireRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    with db.session_scope() as session:
        service = _service(session)
        leased = service.acquire_next(
            worker_id=payload.worker_id,
            now=now,
            lease_seconds=payload.lease_seconds,
            limit=payload.limit,
        )
    if leased is None:
        return {"job": None}
    return {"job": _job_to_dict(leased)}


@router.post("/{job_id}/heartbeat")
def heartbeat(
    job_id: str,
    payload: HeartbeatRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    try:
        with db.session_scope() as session:
            service = _service(session)
            updated = service.heartbeat(
                job_id=job_id,
                worker_id=payload.worker_id,
                now=now,
                lease_seconds=payload.lease_seconds,
            )
    except Exception as exc:
        raise _map_transition_error(exc) from exc
    return {"job": _job_to_dict(updated)}


@router.post("/{job_id}/complete")
def complete_job(
    job_id: str,
    payload: CompleteRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    try:
        with db.session_scope() as session:
            service = _service(session)
            updated = service.complete(
                job_id=job_id,
                worker_id=payload.worker_id,
                now=now,
                partial=payload.partial,
            )
    except Exception as exc:
        raise _map_transition_error(exc) from exc
    return {"job": _job_to_dict(updated)}


@router.post("/{job_id}/fail")
def fail_job(
    job_id: str,
    payload: FailRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    try:
        with db.session_scope() as session:
            service = _service(session)
            updated = service.fail(
                job_id=job_id,
                worker_id=payload.worker_id,
                now=now,
                error_summary=payload.error_summary,
            )
    except Exception as exc:
        raise _map_transition_error(exc) from exc
    return {"job": _job_to_dict(updated)}


@router.post("/{job_id}/pause")
def pause_job(
    job_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    try:
        with db.session_scope() as session:
            service = _service(session)
            updated = service.pause(job_id, now)
    except Exception as exc:
        raise _map_transition_error(exc) from exc
    return {"job": _job_to_dict(updated)}


@router.post("/{job_id}/resume")
def resume_job(
    job_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now()
    try:
        with db.session_scope() as session:
            service = _service(session)
            updated = service.resume(job_id, now)
    except Exception as exc:
        raise _map_transition_error(exc) from exc
    return {"job": _job_to_dict(updated)}
