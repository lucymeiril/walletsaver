"""/api/jobs 라우트 통합 테스트.

JobQueueService 정책을 그대로 노출하는지를 라우트 레벨에서 검증한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.jobs import get_db
from storage.database import Database, create_database


@pytest.fixture()
def db(tmp_path) -> Database:
    # 파일 기반 sqlite로 TestClient의 worker thread에서도 동일 DB가 보이도록 한다.
    database = create_database(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c


def _enqueue(client: TestClient, job_id: str = "job-1", batch_id: str = "batch-1") -> dict:
    res = client.post(
        "/api/jobs",
        json={
            "job_id": job_id,
            "batch_id": batch_id,
            "role": "normalizer",
            "priority": 200,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["job"]


def test_enqueue_then_list(client: TestClient) -> None:
    job = _enqueue(client)
    assert job["status"] == "queued"

    res = client.get("/api/jobs")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["jobs"][0]["job_id"] == "job-1"


def test_enqueue_duplicate_returns_409(client: TestClient) -> None:
    _enqueue(client)
    res = client.post(
        "/api/jobs",
        json={"job_id": "job-1", "batch_id": "batch-1", "role": "normalizer"},
    )
    assert res.status_code == 409


def test_acquire_returns_job_and_marks_running(client: TestClient) -> None:
    _enqueue(client)
    res = client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    assert res.status_code == 200
    job = res.json()["job"]
    assert job is not None
    assert job["status"] == "running"
    assert job["lease_owner"] == "w-1"

    # 두 번째 호출은 빈 결과
    res2 = client.post("/api/jobs/acquire", json={"worker_id": "w-2", "lease_seconds": 60})
    assert res2.status_code == 200
    assert res2.json()["job"] is None


def test_acquire_rejects_unsafe_lease(client: TestClient) -> None:
    res = client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 1})
    # lease_seconds < MIN_LEASE_SECONDS → 422
    assert res.status_code == 422


def test_heartbeat_extends_lease(client: TestClient) -> None:
    _enqueue(client)
    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post(
        "/api/jobs/job-1/heartbeat",
        json={"worker_id": "w-1", "lease_seconds": 60},
    )
    assert res.status_code == 200
    assert res.json()["job"]["lease_owner"] == "w-1"


def test_heartbeat_wrong_owner_returns_403(client: TestClient) -> None:
    _enqueue(client)
    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post(
        "/api/jobs/job-1/heartbeat",
        json={"worker_id": "intruder", "lease_seconds": 60},
    )
    assert res.status_code == 403


def test_complete_marks_completed(client: TestClient) -> None:
    _enqueue(client)
    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post("/api/jobs/job-1/complete", json={"worker_id": "w-1"})
    assert res.status_code == 200
    assert res.json()["job"]["status"] == "completed"


def test_fail_requeues_with_backoff_until_max(client: TestClient) -> None:
    """첫 실패는 다시 queued + not_before 미래로, 마지막 실패는 dead_letter."""
    client.post(
        "/api/jobs",
        json={
            "job_id": "j-fail",
            "batch_id": "b",
            "role": "normalizer",
            "retry_policy": {
                "max_attempts": 2,
                "min_delay_seconds": 1.0,
                "max_delay_seconds": 5.0,
                "backoff_multiplier": 2.0,
                "provider_cooldown_seconds": 0.0,
                "dead_letter_after_attempts": 2,
            },
        },
    )
    # 1st attempt
    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post(
        "/api/jobs/j-fail/fail",
        json={"worker_id": "w-1", "error_summary": "boom"},
    )
    assert res.status_code == 200
    body = res.json()["job"]
    # attempts=1, max_attempts=2, dead_letter=2 → queued로 환원
    assert body["status"] == "queued"
    assert body["attempts"] == 1
    assert body["not_before"] is not None

    # 2nd attempt → dead_letter
    # not_before 무시: list_ready는 not_before 적용. 직접 다시 lease가 어렵다.
    # not_before 우회를 위해 raw하게 not_before 클리어
    from storage.repositories import JobQueueSqlRepository
    db = client.app.dependency_overrides[get_db]()
    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        job = repo.get("j-fail")
        repo.save(job.model_copy(update={"not_before": None}))

    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post(
        "/api/jobs/j-fail/fail",
        json={"worker_id": "w-1", "error_summary": "boom2"},
    )
    body = res.json()["job"]
    assert body["status"] == "dead_letter"
    assert body["attempts"] == 2


def test_pause_and_resume(client: TestClient) -> None:
    _enqueue(client, job_id="j-p")
    res = client.post("/api/jobs/j-p/pause")
    assert res.status_code == 200
    assert res.json()["job"]["status"] == "paused"

    # paused 상태에서 acquire는 빈 결과
    res = client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    assert res.json()["job"] is None

    # resume
    res = client.post("/api/jobs/j-p/resume")
    assert res.status_code == 200
    assert res.json()["job"]["status"] == "queued"

    res = client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    assert res.json()["job"]["job_id"] == "j-p"


def test_pause_running_job_rejected(client: TestClient) -> None:
    _enqueue(client, job_id="j-r")
    client.post("/api/jobs/acquire", json={"worker_id": "w-1", "lease_seconds": 60})
    res = client.post("/api/jobs/j-r/pause")
    # JobQueueService.pause는 running일 때 ValueError → 409
    assert res.status_code == 409


def test_resume_non_paused_rejected(client: TestClient) -> None:
    _enqueue(client, job_id="j-x")
    res = client.post("/api/jobs/j-x/resume")
    assert res.status_code == 409


def test_list_filters_by_status_and_role(client: TestClient) -> None:
    _enqueue(client, job_id="j-a", batch_id="b1")
    client.post(
        "/api/jobs",
        json={
            "job_id": "j-b",
            "batch_id": "b2",
            "role": "classifier",
            "priority": 50,
        },
    )

    res = client.get("/api/jobs", params={"role": "classifier"})
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["jobs"][0]["job_id"] == "j-b"

    res = client.get("/api/jobs", params={"status": "queued"})
    assert res.status_code == 200
    assert res.json()["count"] == 2


def test_heartbeat_unknown_job_returns_404(client: TestClient) -> None:
    res = client.post(
        "/api/jobs/missing/heartbeat",
        json={"worker_id": "w-1", "lease_seconds": 60},
    )
    assert res.status_code == 404
