"""
DB-backed job queue 서비스 로직.

왜 shared에 두는가:
    lease, heartbeat, retry/backoff, dead-letter 같은 큐 정책은 ai-admin 구현체가
    SQLite/Postgres 중 무엇을 쓰든 같아야 한다. 이 모듈은 저장소를 Protocol로만 알고,
    실제 DB 접근은 각 관리자 패키지의 repository가 담당한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .contracts.control_plane import ControlJobContract, ControlJobStatus


class JobQueueRepository(Protocol):
    """DB repository가 구현해야 하는 최소 계약."""

    def list_ready(self, now: datetime, limit: int) -> list[ControlJobContract]:
        """실행 가능한 queued job을 priority 순으로 반환한다."""

    def get(self, job_id: str) -> ControlJobContract | None:
        """job_id로 job을 조회한다."""

    def save(self, job: ControlJobContract) -> None:
        """job 상태를 저장한다."""


class JobQueueService:
    """DB-backed queue의 상태 전이와 안전장치를 담당한다."""

    def __init__(self, repository: JobQueueRepository):
        self.repository = repository

    def enqueue(self, job: ControlJobContract) -> None:
        if job.status != ControlJobStatus.QUEUED:
            raise ValueError("Only queued jobs can be enqueued")
        self.repository.save(job)

    def acquire_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 120,
        limit: int = 10,
    ) -> ControlJobContract | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        for job in self.repository.list_ready(now, limit):
            if job.not_before and job.not_before > now:
                continue
            leased = job.model_copy(
                update={
                    "status": ControlJobStatus.RUNNING,
                    "lease_owner": worker_id,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "heartbeat_at": now,
                    "updated_at": now,
                },
            )
            self.repository.save(leased)
            return leased
        return None

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 120,
    ) -> ControlJobContract:
        job = self._require_job(job_id)
        self._require_lease(job, worker_id, now)
        updated = job.model_copy(
            update={
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            },
        )
        self.repository.save(updated)
        return updated

    def complete(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        partial: bool = False,
    ) -> ControlJobContract:
        job = self._require_job(job_id)
        self._require_lease(job, worker_id, now)
        updated = job.model_copy(
            update={
                "status": ControlJobStatus.PARTIAL if partial else ControlJobStatus.COMPLETED,
                "lease_owner": None,
                "lease_expires_at": None,
                "heartbeat_at": now,
                "updated_at": now,
            },
        )
        self.repository.save(updated)
        return updated

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        error_summary: str,
    ) -> ControlJobContract:
        job = self._require_job(job_id)
        self._require_lease(job, worker_id, now)
        attempts = job.attempts + 1
        if attempts >= job.retry_policy.dead_letter_after_attempts:
            status = ControlJobStatus.DEAD_LETTER
            not_before = None
        elif attempts >= job.retry_policy.max_attempts:
            status = ControlJobStatus.FAILED
            not_before = None
        else:
            status = ControlJobStatus.QUEUED
            delay = self._backoff_seconds(job, attempts)
            not_before = now + timedelta(seconds=delay)

        updated = job.model_copy(
            update={
                "status": status,
                "attempts": attempts,
                "error_summary": error_summary,
                "lease_owner": None,
                "lease_expires_at": None,
                "not_before": not_before,
                "updated_at": now,
            },
        )
        self.repository.save(updated)
        return updated

    def pause(self, job_id: str, now: datetime) -> ControlJobContract:
        job = self._require_job(job_id)
        if job.status == ControlJobStatus.RUNNING:
            raise ValueError("Running jobs must be cancelled or allowed to finish before pausing")
        updated = job.model_copy(update={"status": ControlJobStatus.PAUSED, "updated_at": now})
        self.repository.save(updated)
        return updated

    def resume(self, job_id: str, now: datetime) -> ControlJobContract:
        job = self._require_job(job_id)
        if job.status != ControlJobStatus.PAUSED:
            raise ValueError("Only paused jobs can be resumed")
        updated = job.model_copy(
            update={
                "status": ControlJobStatus.QUEUED,
                "not_before": None,
                "updated_at": now,
            },
        )
        self.repository.save(updated)
        return updated

    def _require_job(self, job_id: str) -> ControlJobContract:
        job = self.repository.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def _require_lease(self, job: ControlJobContract, worker_id: str, now: datetime) -> None:
        if job.status != ControlJobStatus.RUNNING:
            raise ValueError("Job is not running")
        if job.lease_owner != worker_id:
            raise PermissionError("Job lease is owned by another worker")
        if job.lease_expires_at and job.lease_expires_at < now:
            raise TimeoutError("Job lease expired")

    def _backoff_seconds(self, job: ControlJobContract, attempts: int) -> float:
        policy = job.retry_policy
        delay = policy.min_delay_seconds * (policy.backoff_multiplier ** max(0, attempts - 1))
        delay = min(delay, policy.max_delay_seconds)
        return delay + policy.provider_cooldown_seconds
