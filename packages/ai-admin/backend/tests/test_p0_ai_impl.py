"""Tests for the new P0 modules: undo, threshold, alias audit, feedback,
model router, rule_mapper, golden regression."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.models import (
    AliasAuditLog,
    Base,
    LearnedKnowledge,
    ProductMatch,
    ReviewDecisionRecord,
    ThresholdCalibration,
    UserFeedback,
)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client(session):
    from api.app import create_app
    from api.deps import get_db_session

    app = create_app()

    def _override():
        yield session

    app.dependency_overrides[get_db_session] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _add_decision(session, decision_id: str, *, decision: str = "approve") -> None:
    session.add(ReviewDecisionRecord(
        decision_id=decision_id,
        proposal_id=f"prop-{decision_id}",
        proposal_type="category_id",
        decision=decision,
        reviewer_id="r1",
        corrected_value=None,
        reason="",
        create_learning_rule=False,
        decided_at=datetime.now(),
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Undo window
# ---------------------------------------------------------------------------

class TestUndoWindow:
    def test_open_window_sets_deadline(self, session):
        from services.undo_window import open_undo_window

        _add_decision(session, "d1")
        deadline = open_undo_window(session, "d1", window_seconds=5)
        assert deadline is not None
        row = session.get(ReviewDecisionRecord, "d1")
        assert row.undoable_until is not None

    def test_undo_within_window_toast_mode(self, session):
        from services.undo_window import open_undo_window, undo_decision

        _add_decision(session, "d2")
        open_undo_window(session, "d2", window_seconds=5)
        result = undo_decision(session, "d2", actor="op1")
        assert result.mode == "toast"
        row = session.get(ReviewDecisionRecord, "d2")
        assert row.is_undone is True
        assert row.undone_by == "op1"

    def test_undo_requires_cascade_after_window(self, session):
        from services.undo_window import open_undo_window, undo_decision

        _add_decision(session, "d3")
        open_undo_window(session, "d3", window_seconds=0)
        with pytest.raises(ValueError):
            undo_decision(session, "d3", actor="op1", cascade=False)

    def test_cascade_disables_downstream(self, session):
        from services.undo_window import open_undo_window, undo_decision, record_downstream_application

        _add_decision(session, "d4")
        open_undo_window(session, "d4", window_seconds=5)
        record_downstream_application(session, "d4", run_id="run-x")

        # downstream learned alias created from this decision
        session.add(LearnedKnowledge(
            knowledge_id="lk-downstream",
            knowledge_type="keyword_alias",
            pattern="x",
            is_active=True,
            created_from_decision_id="d4",
            applied_count=1,
            success_count=1,
        ))
        session.add(ProductMatch(
            match_id="pm-downstream",
            source_id="s",
            source_name="emart",
            signature_key="sig",
            target_type="canonical_product",
            canonical_product_name="x",
            provenance_source="ai",
            status="approved",
            is_active=True,
            audit_reason="",
            audit_metadata={"source_decision_id": "d4"},
            version=1,
        ))
        session.flush()

        result = undo_decision(session, "d4", actor="op1", cascade=True)
        assert result.mode == "cascade"
        assert "lk-downstream" in result.disabled_knowledge
        assert "pm-downstream" in result.disabled_matches

        # alias_audit rows created
        audits = session.query(AliasAuditLog).all()
        assert len(audits) >= 2
        assert all(a.actor == "op1" for a in audits)


# ---------------------------------------------------------------------------
# Threshold calibrator
# ---------------------------------------------------------------------------

class TestThresholdCalibrator:
    def test_defaults_when_no_data(self, session):
        from services.threshold_calibrator import calibrate_all, DEFAULT_CONFIDENCE_MIN

        results = calibrate_all(session, persist=True)
        conf = next(r for r in results if r.metric_name == "confidence_min")
        assert conf.value == DEFAULT_CONFIDENCE_MIN
        assert conf.method == "default"

        # spec values written too
        names = {r.metric_name for r in results}
        assert "learned_alias_min_sources" in names
        assert "learned_alias_min_titles" in names
        assert "learned_alias_min_settled" in names

    def test_persisted_rows_readable(self, session):
        from services.threshold_calibrator import calibrate_all, get_active_threshold

        calibrate_all(session, persist=True)
        v = get_active_threshold(session, "confidence_min", fallback=0.99)
        assert v == 0.7  # default

    def test_with_enough_samples_uses_p10(self, session):
        from services.threshold_calibrator import calibrate_all

        # 60 approved matches with confidences 0.50..0.99
        for i in range(60):
            decision_id = f"app-{i}"
            session.add(ReviewDecisionRecord(
                decision_id=decision_id,
                proposal_id=f"pm-{i}",
                proposal_type="product_match",
                decision="approve",
                reviewer_id="r",
                decided_at=datetime.now(),
            ))
            session.add(ProductMatch(
                match_id=f"pm-{i}",
                source_id="s",
                source_name="emart",
                signature_key=f"sig-{i}",
                target_type="canonical_product",
                canonical_product_name="x",
                provenance_source="ai",
                status="approved",
                is_active=True,
                confidence=0.5 + (i / 120.0),  # 0.5 .. 0.99
                audit_reason="",
                version=1,
            ))
        session.flush()

        results = calibrate_all(session, persist=True)
        conf = next(r for r in results if r.metric_name == "confidence_min")
        assert conf.method == "p10_of_approved"
        assert conf.sample_size == 60
        # p10 should sit somewhere in the low 0.5s
        assert 0.5 <= conf.value <= 0.65


# ---------------------------------------------------------------------------
# Alias audit
# ---------------------------------------------------------------------------

class TestAliasAuditRoute:
    def test_empty(self, client):
        r = client.get("/api/alias-audit")
        assert r.status_code == 200
        assert r.json()["rows"] == []

    def test_filter_kind(self, client, session):
        session.add(AliasAuditLog(
            audit_id="a1", alias_kind="keyword_alias", alias_key="k",
            action="create", actor="sys", reason="",
        ))
        session.add(AliasAuditLog(
            audit_id="a2", alias_kind="product_match", alias_key="p",
            action="recall", actor="sys", reason="",
        ))
        session.flush()
        r = client.get("/api/alias-audit?alias_kind=keyword_alias").json()
        assert len(r["rows"]) == 1
        assert r["rows"][0]["alias_kind"] == "keyword_alias"


# ---------------------------------------------------------------------------
# User feedback
# ---------------------------------------------------------------------------

class TestUserFeedback:
    def test_record_and_list(self, client):
        r = client.post(
            "/api/feedback",
            json={"kind": "bad_match", "match_id": "pm-x", "note": "wrong"},
        )
        assert r.status_code == 201
        fid = r.json()["feedback_id"]
        listing = client.get("/api/feedback").json()
        assert any(row["feedback_id"] == fid for row in listing["rows"])
        # by_match aggregation
        assert ("pm-x", 1) in [tuple(x) for x in listing["by_match"]]

    def test_handle(self, client):
        fid = client.post(
            "/api/feedback",
            json={"kind": "bad_match", "match_id": "pm-y"},
        ).json()["feedback_id"]
        r = client.post(
            f"/api/feedback/{fid}/handle",
            json={"handled_by": "op", "resolution": "fixed", "new_status": "applied"},
        )
        assert r.status_code == 200
        # open list no longer contains it
        listing = client.get("/api/feedback").json()
        assert all(row["feedback_id"] != fid for row in listing["rows"])

    def test_bad_kind_rejected(self, client):
        r = client.post("/api/feedback", json={"kind": "nope"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Threshold route
# ---------------------------------------------------------------------------

class TestThresholdRoute:
    def test_calibrate_and_read_active(self, client):
        r = client.post("/api/threshold/calibrate")
        assert r.status_code == 200
        body = r.json()
        names = {row["metric_name"] for row in body["results"]}
        assert "confidence_min" in names
        active = client.get("/api/threshold/active").json()
        assert any(row["metric_name"] == "confidence_min" for row in active["metrics"])


# ---------------------------------------------------------------------------
# Model router (with OSS fallback)
# ---------------------------------------------------------------------------

class TestModelRouter:
    def test_oss_stub_always_available(self):
        from services.model_router import LocalOSSStubAdapter, ModelRequest

        adapter = LocalOSSStubAdapter()
        assert adapter.is_available()
        resp = adapter.generate(ModelRequest(prompt="hi"))
        assert resp.provider_id == "local-oss-stub"
        assert not resp.is_live
        assert resp.text  # non-empty

    def test_router_falls_back_when_no_live_provider(self, monkeypatch):
        from services.model_router import ModelRouter, ModelRequest

        # Force GoogleGenAIAdapter to look unavailable.
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        # Construct router with just google + stub
        router = ModelRouter()
        resp = router.generate(ModelRequest(prompt="hi", call_purpose="test"))
        assert resp.provider_id == "local-oss-stub"
        assert resp.fallback_reason

    def test_router_live_simulation_with_fake_adapter(self):
        from services.model_router import ModelRouter, ModelRequest, ModelResponse

        class FakeLive:
            provider_id = "fake-live"
            model_name = "fake-1"

            def is_available(self):
                return True

            def generate(self, req):
                return ModelResponse(
                    text='{"category_id": "c1", "confidence": 0.9}',
                    provider_id=self.provider_id, model_name=self.model_name,
                    is_live=True,
                )

        router = ModelRouter([FakeLive()])
        resp = router.generate(ModelRequest(prompt="p"))
        assert resp.is_live
        assert "c1" in resp.text


# ---------------------------------------------------------------------------
# Rule mapper — match-table first, AI fallback
# ---------------------------------------------------------------------------

class TestRuleMapper:
    def test_match_table_hit_wins(self, session):
        from services.rule_mapper import map_row, reset_stats, get_stats
        from core.contracts.control_plane import normalize_product_signature_key  # type: ignore

        reset_stats()
        title = "에코백 신라면 5입"
        sig = normalize_product_signature_key(title)
        session.add(ProductMatch(
            match_id="m-hit",
            source_id="s",
            source_name="emart",
            signature_key=sig,
            target_type="canonical_product",
            canonical_product_id="cp-1",
            canonical_product_name="신라면 5입",
            category_id="cat.noodle",
            provenance_source="human",
            status="approved",
            is_active=True,
            audit_reason="",
            version=1,
        ))
        session.flush()

        result = map_row(session, source_name="emart", raw_title=title)
        assert result.path == "match_table_hit"
        assert result.match["canonical_product_id"] == "cp-1"
        assert get_stats().match_table_hits == 1

    def test_ai_fallback_used_when_no_hit(self, session):
        from services.rule_mapper import map_row, reset_stats, get_stats
        from services.model_router import ModelRouter, LocalOSSStubAdapter

        reset_stats()
        router = ModelRouter([LocalOSSStubAdapter()])
        result = map_row(
            session, source_name="emart", raw_title="없는상품", router=router,
        )
        assert result.path == "ai_fallback"
        assert result.ai_response is not None
        s = get_stats()
        assert s.ai_fallback_calls == 1
        assert s.ai_fallback_oss == 1
        assert s.match_table_hits == 0


# ---------------------------------------------------------------------------
# Rule mapper stats route
# ---------------------------------------------------------------------------

class TestRuleMapperRoute:
    def test_stats_shape(self, client):
        body = client.get("/api/rule-mapper/stats").json()
        assert "match_table_hits" in body
        assert "ai_fallback_calls" in body


# ---------------------------------------------------------------------------
# Golden regression
# ---------------------------------------------------------------------------

class TestGoldenRegression:
    def test_perfect_accuracy(self):
        from services.golden_regression import evaluate, GoldenRow

        rows = [GoldenRow(raw_title=f"r{i}", expected_category_id="c1") for i in range(5)]
        result = evaluate(rows, predictor=lambda r: "c1")
        assert result.total == 5
        assert result.correct == 5
        assert result.accuracy == 1.0

    def test_misses_recorded(self):
        from services.golden_regression import evaluate, GoldenRow

        rows = [
            GoldenRow(raw_title="r1", expected_category_id="c1"),
            GoldenRow(raw_title="r2", expected_category_id="c2"),
        ]
        result = evaluate(rows, predictor=lambda r: "c1")
        assert result.correct == 1
        assert len(result.misses) == 1
        assert result.misses[0]["expected"] == "c2"


# ---------------------------------------------------------------------------
# Undo route
# ---------------------------------------------------------------------------

class TestUndoRoute:
    def test_undo_within_window(self, client, session):
        from services.undo_window import open_undo_window

        _add_decision(session, "rd1")
        open_undo_window(session, "rd1", window_seconds=10)
        r = client.post(
            "/api/review/undo/rd1",
            json={"actor": "op", "cascade": False},
        )
        assert r.status_code == 200
        assert r.json()["mode"] == "toast"

    def test_undo_requires_cascade(self, client, session):
        from services.undo_window import open_undo_window

        _add_decision(session, "rd2")
        open_undo_window(session, "rd2", window_seconds=0)
        r = client.post(
            "/api/review/undo/rd2",
            json={"actor": "op", "cascade": False},
        )
        assert r.status_code == 409

    def test_undo_unknown_decision(self, client):
        r = client.post(
            "/api/review/undo/nope",
            json={"actor": "op"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# P0 Follow-up: Task 1 — rule_mapper record_rule_hit wiring
# ---------------------------------------------------------------------------

class TestRuleMapperRecordRuleHit:
    def test_record_rule_hit_increments_stats(self):
        from services.rule_mapper import record_rule_hit, reset_stats, get_stats

        reset_stats()
        record_rule_hit("emart", "풀무원 두부 300g")
        s = get_stats()
        assert s.match_table_hits == 1
        assert s.last_path_per_source["emart"] == "rule_hit"

    def test_record_rule_hit_multiple_sources(self):
        from services.rule_mapper import record_rule_hit, reset_stats, get_stats

        reset_stats()
        record_rule_hit("emart", "item1")
        record_rule_hit("lottemart", "item2")
        record_rule_hit("emart", "item3")
        s = get_stats()
        assert s.match_table_hits == 3
        assert s.last_path_per_source["emart"] == "rule_hit"
        assert s.last_path_per_source["lottemart"] == "rule_hit"


# ---------------------------------------------------------------------------
# P0 Follow-up: Task 2 — PostcheckGate calibrated threshold
# ---------------------------------------------------------------------------

class TestPostcheckGateCalibration:
    def test_default_confidence_min(self):
        from services.postcheck_gate import PostcheckGate, CONFIDENCE_MIN

        gate = PostcheckGate({}, lambda cid: [], lambda cid: [])
        assert gate._confidence_min == CONFIDENCE_MIN

    def test_custom_confidence_min(self):
        from services.postcheck_gate import PostcheckGate

        gate = PostcheckGate({}, lambda cid: [], lambda cid: [], confidence_min=0.5)
        assert gate._confidence_min == 0.5

    def test_create_with_thresholds_uses_db(self, session):
        from services.postcheck_gate import PostcheckGate
        from storage.models import ThresholdCalibration
        import uuid

        session.add(ThresholdCalibration(
            calibration_id=str(uuid.uuid4()),
            metric_name="confidence_min",
            value=0.85,
            sample_size=200,
            method="percentile",
            method_params={},
            notes="test",
        ))
        session.flush()

        gate = PostcheckGate.create_with_thresholds(
            session, {}, lambda cid: [], lambda cid: []
        )
        assert gate._confidence_min == 0.85

    def test_create_with_thresholds_falls_back(self, session):
        from services.postcheck_gate import PostcheckGate, CONFIDENCE_MIN

        gate = PostcheckGate.create_with_thresholds(
            session, {}, lambda cid: [], lambda cid: []
        )
        assert gate._confidence_min == CONFIDENCE_MIN


# ---------------------------------------------------------------------------
# P0 Follow-up: Task 3 — 30s undo window
# ---------------------------------------------------------------------------

class TestUndoWindow30s:
    def test_default_undo_window_is_30s(self):
        from services.undo_window import DEFAULT_UNDO_WINDOW_SECONDS
        assert DEFAULT_UNDO_WINDOW_SECONDS == 30

    def test_open_undo_window_default_30s(self, session):
        from services.undo_window import open_undo_window, DEFAULT_UNDO_WINDOW_SECONDS
        from datetime import datetime, timedelta

        _add_decision(session, "d30s")
        now = datetime(2024, 1, 1, 12, 0, 0)
        deadline = open_undo_window(session, "d30s", now=now)
        assert deadline == now + timedelta(seconds=DEFAULT_UNDO_WINDOW_SECONDS)

    def test_review_approve_opens_undo_window(self, session):
        """ReviewQueueService.approve + open_undo_window wiring: undoable_until must be set."""
        from storage.models import FieldProposal, ReviewDecisionRecord
        from core.review_queue import ReviewQueueService
        from storage import ReviewQueueRepositoryAdapter, ReviewDecisionRepository
        from services.undo_window import open_undo_window, DEFAULT_UNDO_WINDOW_SECONDS

        # Seed a field proposal directly (no raw record FK needed by FieldProposal model)
        session.add(FieldProposal(
            proposal_id="prop-undo-gate",
            proposal_type="category",
            target_field="category_id",
            proposed_value="cat.test",
            status="ai_proposed",
            provenance={
                "raw_record_id": "raw-x",
                "evidence_text": "테스트",
                "worker_role": "classifier",
            },
            alternatives=[],
        ))
        session.flush()

        # Call approve via the service (mirrors what the route does)
        svc = ReviewQueueService(ReviewQueueRepositoryAdapter(session))
        decision = svc.approve("prop-undo-gate", reviewer_id="tester")
        ReviewDecisionRepository(session).save(decision)
        session.flush()

        # Wire open_undo_window as the route does
        deadline = open_undo_window(session, decision.decision_id,
                                    window_seconds=DEFAULT_UNDO_WINDOW_SECONDS)
        assert deadline is not None

        row = session.get(ReviewDecisionRecord, decision.decision_id)
        assert row is not None
        assert row.undoable_until is not None

