"""DB-backed job queue 서비스 로직 테스트."""

from datetime import datetime, timedelta

import pytest

from shared.core.contracts.ai_pipeline import AIWorkerRole
from shared.core.contracts.control_plane import (
    ControlJobContract,
    ControlJobStatus,
    RetryPolicyContract,
)
from shared.core.job_queue import JobQueueService


class InMemoryJobRepo:
    def __init__(self):
        self.jobs = {}

    def list_ready(self, now: datetime, limit: int) -> list[ControlJobContract]:
        ready = [
            job
            for job in self.jobs.values()
            if job.status == ControlJobStatus.QUEUED
            and (job.not_before is None or job.not_before <= now)
        ]
        return sorted(ready, key=lambda job: job.priority)[:limit]

    def get(self, job_id: str) -> ControlJobContract | None:
        return self.jobs.get(job_id)

    def save(self, job: ControlJobContract) -> None:
        self.jobs[job.job_id] = job


def make_job(job_id: str = "job-1") -> ControlJobContract:
    return ControlJobContract(
        job_id=job_id,
        batch_id="batch-1",
        role=AIWorkerRole.CLASSIFIER,
        retry_policy=RetryPolicyContract(
            max_attempts=3,
            min_delay_seconds=5,
            max_delay_seconds=60,
            backoff_multiplier=2,
            dead_letter_after_attempts=3,
        ),
    )


def test_acquire_next_sets_lease_and_heartbeat():
    now = datetime(2026, 4, 30, 9, 0, 0)
    repo = InMemoryJobRepo()
    service = JobQueueService(repo)
    service.enqueue(make_job())

    leased = service.acquire_next(worker_id="worker-a", now=now, lease_seconds=30)

    assert leased is not None
    assert leased.status == ControlJobStatus.RUNNING
    assert leased.lease_owner == "worker-a"
    assert leased.lease_expires_at == now + timedelta(seconds=30)


def test_heartbeat_requires_current_lease_owner():
    now = datetime(2026, 4, 30, 9, 0, 0)
    repo = InMemoryJobRepo()
    service = JobQueueService(repo)
    service.enqueue(make_job())
    leased = service.acquire_next(worker_id="worker-a", now=now)

    with pytest.raises(PermissionError):
        service.heartbeat(job_id=leased.job_id, worker_id="worker-b", now=now)


def test_fail_requeues_with_backoff_before_dead_letter():
    now = datetime(2026, 4, 30, 9, 0, 0)
    repo = InMemoryJobRepo()
    service = JobQueueService(repo)
    service.enqueue(make_job())
    leased = service.acquire_next(worker_id="worker-a", now=now)

    failed = service.fail(
        job_id=leased.job_id,
        worker_id="worker-a",
        now=now,
        error_summary="provider timeout",
    )

    assert failed.status == ControlJobStatus.QUEUED
    assert failed.attempts == 1
    assert failed.not_before == now + timedelta(seconds=5)
    assert service.acquire_next(worker_id="worker-a", now=now) is None


def test_fail_moves_to_dead_letter_after_configured_attempts():
    now = datetime(2026, 4, 30, 9, 0, 0)
    repo = InMemoryJobRepo()
    service = JobQueueService(repo)
    service.enqueue(make_job())

    for index in range(3):
        leased = service.acquire_next(
            worker_id="worker-a",
            now=now + timedelta(seconds=120 * index),
        )
        service.fail(
            job_id=leased.job_id,
            worker_id="worker-a",
            now=now + timedelta(seconds=120 * index),
            error_summary="bad json",
        )

    assert repo.get("job-1").status == ControlJobStatus.DEAD_LETTER


def test_pause_and_resume_are_manual_controls():
    now = datetime(2026, 4, 30, 9, 0, 0)
    repo = InMemoryJobRepo()
    service = JobQueueService(repo)
    service.enqueue(make_job())

    paused = service.pause("job-1", now)
    assert paused.status == ControlJobStatus.PAUSED

    resumed = service.resume("job-1", now)
    assert resumed.status == ControlJobStatus.QUEUED
