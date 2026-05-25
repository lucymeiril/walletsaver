"""Bulk archive 감사 DB 영속화 + multi-worker race-free undo 회귀 테스트."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.review import get_db as review_get_db
from api.routes.prompts import get_db as prompts_get_db
from storage import Database, create_database


@pytest.fixture()
def db(tmp_path) -> Database:
    # file-backed sqlite (서버 재기동 시나리오 시뮬레이션 대비)
    database = create_database(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


def _proposal(pid: str) -> dict:
    return {
        "proposal_id": pid,
        "proposal_type": "normalized_field",
        "target_field": "canonical_name",
        "proposed_value": "값",
        "status": "ai_proposed",
        "provenance": {
            "raw_record_id": f"raw-{pid}",
            "evidence_text": "evidence",
            "worker_role": "normalizer",
        },
        "alternatives": [],
    }


def _submit(client: TestClient, payload: dict) -> None:
    r = client.post("/api/review/proposals", json=payload)
    assert r.status_code == 201, r.text


def test_audit_row_is_persisted_in_db_after_archive(client: TestClient, db: Database) -> None:
    """bulk-archive 후 DB에 active 상태의 감사 행이 저장된다."""
    from storage.models import BulkArchiveAuditRow

    for i in range(3):
        _submit(client, _proposal(f"persist-{i}"))
    body = client.post(
        "/api/review/proposals/bulk-archive", json={"reviewer_id": "op-1", "reason": "test"}
    ).json()
    token = body["undo_token"]
    assert token

    with db.session_scope() as s:
        row = s.get(BulkArchiveAuditRow, token)
        assert row is not None
        assert row.status == "active"
        assert row.reviewer_id == "op-1"
        assert row.archived_count == 3
        assert len(row.snapshots) == 3


def test_undo_survives_in_process_dict_loss(client: TestClient, db: Database) -> None:
    """모듈 메모리에 의존하지 않음 — DB만으로 undo가 동작한다 (재기동 시뮬레이션)."""
    import api.routes.review as review_mod

    _submit(client, _proposal("survive-1"))
    body = client.post("/api/review/proposals/bulk-archive", json={"reviewer_id": "op"}).json()
    token = body["undo_token"]

    # 모듈에 in-memory 버퍼 dict이 잔존한다면 비우기 — DB 영속만 사용해야 함
    if hasattr(review_mod, "_BULK_ARCHIVE_UNDO_BUFFER"):
        review_mod._BULK_ARCHIVE_UNDO_BUFFER.clear()

    undo = client.post("/api/review/proposals/bulk-archive/undo", json={"undo_token": token})
    assert undo.status_code == 200
    assert undo.json()["restored"] == 1


def test_concurrent_undo_calls_only_one_succeeds(client: TestClient, db: Database) -> None:
    """동일 토큰에 대해 멀티스레드 동시 undo 호출 시 정확히 1개만 200, 나머지는 410."""
    for i in range(2):
        _submit(client, _proposal(f"race-{i}"))
    body = client.post("/api/review/proposals/bulk-archive", json={"reviewer_id": "op"}).json()
    token = body["undo_token"]
    assert token

    N = 12
    barrier = threading.Barrier(N)
    results: list[int] = []
    results_lock = threading.Lock()

    def _worker():
        # 모든 worker가 동시에 진입하도록 barrier로 정렬
        barrier.wait(timeout=10)
        r = client.post("/api/review/proposals/bulk-archive/undo", json={"undo_token": token})
        with results_lock:
            results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=N) as ex:
        futs = [ex.submit(_worker) for _ in range(N)]
        for f in as_completed(futs):
            f.result()

    success = [c for c in results if c == 200]
    gone = [c for c in results if c == 410]
    assert len(success) == 1, f"정확히 1개의 worker만 성공해야 함 — got {results}"
    assert len(gone) == N - 1, f"나머지는 410 이어야 함 — got {results}"

    # 복원 결과 확인 — 중복 복원이 일어나지 않았는지 (proposal 개수 == 원본 2)
    listing = client.get("/api/review/proposals").json()["items"]
    proposal_ids = [p["proposal_id"] for p in listing]
    assert sorted(proposal_ids) == ["race-0", "race-1"]


def test_expired_token_atomic_update_yields_410(client: TestClient, db: Database) -> None:
    """만료된 토큰의 undo는 atomic CAS 체크에 걸려 410 을 반환한다."""
    from datetime import datetime, timedelta
    from storage.models import BulkArchiveAuditRow

    _submit(client, _proposal("expire-1"))
    body = client.post("/api/review/proposals/bulk-archive", json={"reviewer_id": "op"}).json()
    token = body["undo_token"]

    # expires_at을 과거로 강제
    with db.session_scope() as s:
        row = s.get(BulkArchiveAuditRow, token)
        row.expires_at = datetime.now() - timedelta(seconds=1)

    r = client.post("/api/review/proposals/bulk-archive/undo", json={"undo_token": token})
    assert r.status_code == 410

    # 영속 상태가 expired 로 전이됐는지 (혹은 active 이지만 expires_at 과거)
    with db.session_scope() as s:
        row = s.get(BulkArchiveAuditRow, token)
        assert row.status in ("expired", "active")
