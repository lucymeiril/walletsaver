"""Tests for match-monitor API routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.models import Base, LabelingRunLog, LearnedKnowledge, ProductMatch
from storage.repositories import (
    LabelingRunLogRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
)


@pytest.fixture()
def db_session(tmp_path):
    # SQLite ":memory:" is per-connection; FastAPI's threadpool uses a different
    # connection than the test fixture. Use a tmp file so all connections share tables.
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    from api.app import create_app
    from api.deps import get_db_session

    app = create_app()

    def _override():
        # Reuse the same session; do not close it here (the db_session fixture owns it).
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── Cumulative endpoint ─────────────────────────────────────────────────────


class TestCumulativeEmpty:
    def test_schema_present(self, client):
        r = client.get("/api/match-monitor/cumulative")
        assert r.status_code == 200
        body = r.json()
        assert "product_match" in body
        assert "learned_knowledge" in body

    def test_empty_totals_are_zero(self, client):
        body = client.get("/api/match-monitor/cumulative").json()
        assert body["product_match"]["total"] == 0
        assert body["learned_knowledge"]["total"] == 0

    def test_empty_dicts_present(self, client):
        body = client.get("/api/match-monitor/cumulative").json()
        assert isinstance(body["product_match"]["by_status"], dict)
        assert isinstance(body["learned_knowledge"]["by_type"], dict)


class TestCumulativeWithData:
    def test_product_match_count(self, client, db_session):
        pm = ProductMatch(
            match_id="pm-test-001",
            source_id="s1",
            source_name="emart",
            signature_key="sig-001",
            target_type="canonical_product",
            canonical_product_name="테스트 상품",
            provenance_source="human",
            status="approved",
            is_active=True,
            audit_reason="test",
            version=1,
        )
        db_session.add(pm)
        db_session.flush()

        body = client.get("/api/match-monitor/cumulative").json()
        assert body["product_match"]["total"] == 1
        assert body["product_match"]["by_status"].get("approved") == 1

    def test_learned_knowledge_by_type(self, client, db_session):
        for i in range(3):
            lk = LearnedKnowledge(
                knowledge_id=f"lk-{i}",
                knowledge_type="keyword_alias",
                pattern=f"패턴{i}",
                is_active=True,
                applied_count=i * 2,
                success_count=i,
            )
            db_session.add(lk)
        db_session.flush()

        body = client.get("/api/match-monitor/cumulative").json()
        assert body["learned_knowledge"]["total"] == 3
        assert body["learned_knowledge"]["by_type"].get("keyword_alias") == 3

    def test_idempotent(self, client, db_session):
        body1 = client.get("/api/match-monitor/cumulative").json()
        body2 = client.get("/api/match-monitor/cumulative").json()
        assert body1 == body2


# ── Runs endpoint ───────────────────────────────────────────────────────────


class TestRunsEmpty:
    def test_schema(self, client):
        r = client.get("/api/match-monitor/runs")
        assert r.status_code == 200
        body = r.json()
        assert "runs" in body
        assert "total" in body

    def test_empty_runs(self, client):
        body = client.get("/api/match-monitor/runs").json()
        assert body["runs"] == []
        assert body["total"] == 0


class TestRunsWithData:
    def _insert_run(self, session, run_id, total_input, queue_initial, ai_resolved, ai_escalated, pm_total, lk_total):
        from datetime import datetime
        session.add(LabelingRunLog(
            run_id=run_id,
            run_at=datetime.now(),
            mode="commit",
            ai_provider_kind="mock",
            total_input=total_input,
            queue_initial=queue_initial,
            ai_called=queue_initial,
            ai_resolved=ai_resolved,
            ai_escalated=ai_escalated,
            gate_passed=ai_resolved,
            gate_escalated=ai_escalated,
            canonical_created=total_input,
            product_match_total_snapshot=pm_total,
            learned_knowledge_total_snapshot=lk_total,
            by_mart={},
        ))
        session.flush()

    def test_run_schema(self, client, db_session):
        self._insert_run(db_session, "run-001", 10, 10, 8, 2, 0, 0)
        body = client.get("/api/match-monitor/runs").json()
        run = body["runs"][0]
        assert "run_id" in run
        assert "ai_call_rate" in run
        assert "total_input" in run
        assert "ai_resolved" in run

    def test_ai_call_rate_100(self, client, db_session):
        self._insert_run(db_session, "run-rate-100", 10, 10, 10, 0, 0, 0)
        body = client.get("/api/match-monitor/runs").json()
        assert body["runs"][0]["ai_call_rate"] == 100.0

    def test_ai_call_rate_zero_with_no_input(self, client, db_session):
        self._insert_run(db_session, "run-rate-zero", 0, 0, 0, 0, 0, 0)
        body = client.get("/api/match-monitor/runs").json()
        assert body["runs"][0]["ai_call_rate"] == 0.0

    def test_cycle_simulation(self, client, db_session):
        self._insert_run(db_session, "run-cycle1", 10, 10, 8, 2, 0, 0)
        self._insert_run(db_session, "run-cycle2", 10, 3, 3, 0, 8, 2)
        body = client.get("/api/match-monitor/runs").json()
        runs = body["runs"]
        assert len(runs) == 2
        cycle2_rate = next(r["ai_call_rate"] for r in runs if r["run_id"] == "run-cycle2")
        cycle1_rate = next(r["ai_call_rate"] for r in runs if r["run_id"] == "run-cycle1")
        assert cycle2_rate < cycle1_rate
        assert cycle1_rate == 100.0
        assert cycle2_rate == 30.0

    def test_idempotent_runs(self, client, db_session):
        self._insert_run(db_session, "run-idem", 5, 5, 5, 0, 1, 1)
        body1 = client.get("/api/match-monitor/runs").json()
        body2 = client.get("/api/match-monitor/runs").json()
        assert body1 == body2
        assert len(body1["runs"]) == 1

    def test_n_param(self, client, db_session):
        for i in range(5):
            self._insert_run(db_session, f"run-n-{i}", 5, 5, 5, 0, 0, 0)
        body = client.get("/api/match-monitor/runs?n=3").json()
        assert len(body["runs"]) == 3


# ── Repository unit tests ────────────────────────────────────────────────────


class TestRepositoryCountMethods:
    def test_pm_count_all_empty(self, db_session):
        repo = ProductMatchStoreRepository(db_session)
        assert repo.count_all() == 0

    def test_lk_count_all_empty(self, db_session):
        repo = LearnedKnowledgeRepository(db_session)
        assert repo.count_all() == 0

    def test_lk_count_by_type(self, db_session):
        repo = LearnedKnowledgeRepository(db_session)
        db_session.add(LearnedKnowledge(
            knowledge_id="lk-t1", knowledge_type="keyword_alias",
            pattern="p1", is_active=True, applied_count=0, success_count=0,
        ))
        db_session.add(LearnedKnowledge(
            knowledge_id="lk-t2", knowledge_type="category_rule",
            pattern="p2", is_active=True, applied_count=0, success_count=0,
        ))
        db_session.flush()
        by_type = repo.count_by_type()
        assert by_type.get("keyword_alias") == 1
        assert by_type.get("category_rule") == 1

    def test_run_log_repo_save_and_list(self, db_session):
        from datetime import datetime
        repo = LabelingRunLogRepository(db_session)
        repo.save(
            "run-test",
            run_at=datetime.now(),
            mode="dry_run",
            ai_provider_kind="mock",
            total_input=10,
            queue_initial=10,
            ai_called=10,
            ai_resolved=8,
            ai_escalated=2,
            gate_passed=8,
            gate_escalated=2,
            canonical_created=10,
            product_match_total_snapshot=0,
            learned_knowledge_total_snapshot=0,
            by_mart={},
        )
        db_session.flush()
        runs = repo.list_recent()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-test"
        assert "ai_call_rate" in runs[0]
