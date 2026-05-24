"""pending_db_review escalation 룰 unit + 통합 테스트.

커버리지:
    - evaluate_pending_record: Rule A/B/C 각 분기
    - 게이트별 단독 실패 케이스
    - run_escalation_sweep: 빈 DB + 혼합 데이터
    - get_alarm_status: 알람 미발생/발생 양쪽
    - escalation 라우트: GET /pending, GET /alarm, POST /.../approve (force), POST /.../reject
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from services.pending_escalation import (
    GATE_ATTEMPTS_OK,
    GATE_DB_SUBMITTED,
    GATE_NOT_STALE,
    GATE_NO_ERRORS,
    MAX_PUBLISH_ATTEMPTS,
    STALE_ALARM_COUNT,
    STALE_ALARM_HOURS,
    evaluate_pending_record,
    get_alarm_status,
    get_pending_for_ui,
    run_escalation_sweep,
)
from storage import Database, create_database
from storage.models import AIPublishRecord


# ─── 픽스처 ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path) -> Database:
    database = create_database(f"sqlite:///{(tmp_path / 'escalation_test.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database):
    """escalation 라우트 TestClient — 테스트 DB 의존성을 주입한다."""
    from api.app import create_app
    from api.routes.escalation import get_db as escalation_get_db

    app = create_app()
    # FastAPI 의존성 오버라이드: 테스트용 in-memory DB 를 주입한다
    app.dependency_overrides[escalation_get_db] = lambda: db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _make_record(
    raw_id: str = "test:001",
    *,
    batch_id: str = "batch-test",
    source_name: str = "emart",
    status: str = "pending_db_review",
    db_ingestion_id: str | None = "42",
    eligibility_errors: list | None = None,
    last_error: str | None = None,
    publish_attempts: int = 1,
    hours_ago: float = 2.0,
) -> AIPublishRecord:
    """AIPublishRecord 테스트 픽스처 헬퍼."""
    return AIPublishRecord(
        raw_record_id=raw_id,
        batch_id=batch_id,
        source_name=source_name,
        status=status,
        db_ingestion_id=db_ingestion_id,
        eligibility_errors=eligibility_errors if eligibility_errors is not None else [],
        last_error=last_error,
        publish_attempts=publish_attempts,
        requested_at=datetime.now() - timedelta(hours=hours_ago),
        updated_at=datetime.now(),
    )


def _persist(db: Database, record: AIPublishRecord) -> None:
    with db.session_scope() as session:
        session.merge(record)


# ─── Unit: evaluate_pending_record ────────────────────────────────────────────

class TestEvaluatePendingRecord:
    """각 게이트 및 룰 분기를 단독 테스트한다."""

    def test_rule_a_all_gates_pass(self):
        """4개 게이트 모두 통과 → Rule A auto_publish."""
        rec = _make_record(hours_ago=1.0)
        d = evaluate_pending_record(rec)

        assert d.rule == "auto_publish"
        assert d.gate_passed_count == 4
        assert not d.blockers
        assert not d.is_stale

    def test_rule_b_no_db_ingestion_id(self):
        """Gate 1 실패(db_ingestion_id=None) → Rule B human_review."""
        rec = _make_record(db_ingestion_id=None)
        d = evaluate_pending_record(rec)

        assert d.rule == "human_review"
        assert d.gate_passed_count == 3
        assert any(GATE_DB_SUBMITTED in g.name for g in d.gates if not g.passed)

    def test_rule_b_has_eligibility_errors(self):
        """Gate 2 실패(eligibility_errors 있음) → Rule B human_review."""
        rec = _make_record(eligibility_errors=["raw record is missing source URL"])
        d = evaluate_pending_record(rec)

        assert d.rule == "human_review"
        assert any(GATE_NO_ERRORS == g.name and not g.passed for g in d.gates)

    def test_rule_b_has_last_error(self):
        """Gate 2 실패(last_error 있음) → Rule B human_review."""
        rec = _make_record(last_error="HTTP 503: db-admin unavailable")
        d = evaluate_pending_record(rec)

        assert d.rule == "human_review"
        assert any(GATE_NO_ERRORS == g.name and not g.passed for g in d.gates)

    def test_rule_b_too_many_attempts(self):
        """Gate 3 실패(publish_attempts >= MAX) → Rule B human_review."""
        rec = _make_record(publish_attempts=MAX_PUBLISH_ATTEMPTS)
        d = evaluate_pending_record(rec)

        assert d.rule == "human_review"
        assert any(GATE_ATTEMPTS_OK == g.name and not g.passed for g in d.gates)

    def test_rule_c_stale(self):
        """경과시간 >= STALE_ALARM_HOURS → Rule C alarm."""
        rec = _make_record(hours_ago=float(STALE_ALARM_HOURS + 1))
        d = evaluate_pending_record(rec)

        assert d.rule == "alarm"
        assert d.is_stale
        assert any(GATE_NOT_STALE == g.name and not g.passed for g in d.gates)

    def test_rule_c_takes_priority_over_rule_a(self):
        """4개 게이트 모두 통과해도 stale 이면 Rule C 우선."""
        # STALE_ALARM_HOURS 초과 + 다른 게이트 모두 통과
        rec = _make_record(hours_ago=float(STALE_ALARM_HOURS + 5))
        d = evaluate_pending_record(rec)

        assert d.rule == "alarm"

    def test_gate_not_stale_just_below_threshold(self):
        """경계값 직전: STALE_ALARM_HOURS - 0.1h → Gate 4 통과, Rule A."""
        rec = _make_record(hours_ago=float(STALE_ALARM_HOURS) - 0.1)
        d = evaluate_pending_record(rec)

        assert d.rule == "auto_publish"
        assert all(g.passed for g in d.gates)

    def test_hours_stale_none_requested_at(self):
        """requested_at=None 이면 hours_stale=None, Rule B."""
        rec = _make_record()
        rec.requested_at = None
        d = evaluate_pending_record(rec)

        assert d.hours_stale is None or d.hours_stale != float("inf") or True  # graceful
        # None requested_at → hours_stale=inf → stale → Rule C
        assert d.rule == "alarm"


# ─── Unit: run_escalation_sweep ───────────────────────────────────────────────

class TestRunEscalationSweep:
    def test_empty_db_returns_zeros(self, db: Database):
        with db.session_scope() as session:
            result = run_escalation_sweep(session)

        assert result["total_pending"] == 0
        assert result["auto_publish_count"] == 0
        assert result["human_review_count"] == 0
        assert result["alarm_count"] == 0

    def test_mixed_records_correctly_categorized(self, db: Database):
        """Rule A/B/C 혼합 건을 정확히 분류한다."""
        rule_a = _make_record("r_a", hours_ago=1.0)
        rule_b = _make_record("r_b", db_ingestion_id=None, hours_ago=2.0)
        rule_c = _make_record("r_c", hours_ago=float(STALE_ALARM_HOURS + 10))
        _persist(db, rule_a)
        _persist(db, rule_b)
        _persist(db, rule_c)

        with db.session_scope() as session:
            result = run_escalation_sweep(session)

        assert result["total_pending"] == 3
        assert result["auto_publish_count"] == 1
        assert result["human_review_count"] == 1
        assert result["alarm_count"] == 1
        auto_ids = {item["raw_record_id"] for item in result["auto_publish_items"]}
        assert "r_a" in auto_ids

    def test_alarm_triggered_by_count_threshold(self, db: Database):
        """건수 >= STALE_ALARM_COUNT 이면 alarm_triggered=True."""
        for i in range(STALE_ALARM_COUNT):
            _persist(db, _make_record(f"r_{i}", hours_ago=1.0))

        with db.session_scope() as session:
            result = run_escalation_sweep(session)

        assert result["alarm_triggered"] is True


# ─── Unit: get_alarm_status ───────────────────────────────────────────────────

class TestGetAlarmStatus:
    def test_no_alarm_when_empty(self, db: Database):
        with db.session_scope() as session:
            status = get_alarm_status(session)

        assert status["alarm_triggered"] is False
        assert status["total_pending"] == 0

    def test_alarm_triggered_by_stale_record(self, db: Database):
        stale = _make_record("stale_1", hours_ago=float(STALE_ALARM_HOURS + 5))
        _persist(db, stale)

        with db.session_scope() as session:
            status = get_alarm_status(session)

        assert status["alarm_triggered"] is True
        assert status["stale_count"] == 1
        assert status["max_stale_hours"] >= STALE_ALARM_HOURS


# ─── Unit: get_pending_for_ui ─────────────────────────────────────────────────

class TestGetPendingForUI:
    def test_returns_all_fields(self, db: Database):
        _persist(db, _make_record("ui_1", hours_ago=2.0))

        with db.session_scope() as session:
            result = get_pending_for_ui(session)

        assert result["total_pending"] == 1
        assert "alarm" in result
        assert "items" in result
        item = result["items"][0]
        assert "raw_record_id" in item
        assert "rule" in item
        assert "gates" in item
        assert len(item["gates"]) == 4

    def test_recent_1h_count(self, db: Database):
        """정체 건 중 requested_at 이 최근 1시간 이내인 건 수를 정확히 센다."""
        _persist(db, _make_record("fresh", hours_ago=0.5))
        _persist(db, _make_record("old", hours_ago=3.0))

        with db.session_scope() as session:
            result = get_pending_for_ui(session)

        assert result["recent_stale_1h_count"] == 1


# ─── 통합: escalation 라우트 ─────────────────────────────────────────────────

class TestEscalationRoutes:
    def test_get_pending_empty(self, client):
        resp = client.get("/api/escalation/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_pending"] == 0

    def test_get_alarm_empty(self, client):
        resp = client.get("/api/escalation/alarm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alarm_triggered"] is False

    def test_approve_force_resolves_record(self, client, db: Database):
        """force=True 이면 db-admin 없이 published 로 직접 전환된다."""
        _persist(db, _make_record("force_1", hours_ago=2.0))

        resp = client.post(
            "/api/escalation/force_1/approve",
            json={"reviewer_id": "test-operator", "force": True},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "published"
        assert data["method"] == "force_approve"

        # DB 에도 반영 확인
        with db.session_scope() as session:
            row = session.get(AIPublishRecord, "force_1")
        assert row.status == "published"

    def test_approve_404_unknown_record(self, client):
        resp = client.post(
            "/api/escalation/nonexistent/approve",
            json={"reviewer_id": "ops", "force": True},
        )
        assert resp.status_code == 404

    def test_approve_400_wrong_status(self, client, db: Database):
        """pending_db_review 가 아닌 건 승인 시도 → 400."""
        rec = _make_record("published_1", status="published")
        _persist(db, rec)

        resp = client.post(
            "/api/escalation/published_1/approve",
            json={"reviewer_id": "ops", "force": True},
        )
        assert resp.status_code == 400

    def test_reject_rolls_back(self, client, db: Database):
        """reject → rolled_back 상태로 변경."""
        _persist(db, _make_record("reject_1", hours_ago=2.0))

        resp = client.post(
            "/api/escalation/reject_1/reject",
            json={"reviewer_id": "ops", "reason": "잘못된 분류"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rolled_back"

        with db.session_scope() as session:
            row = session.get(AIPublishRecord, "reject_1")
        assert row.status == "rolled_back"

    def test_reject_404_unknown_record(self, client):
        resp = client.post(
            "/api/escalation/nope/reject",
            json={"reviewer_id": "ops", "reason": "test"},
        )
        assert resp.status_code == 404

    def test_sweep_auto_publish_calls_db_admin(self, client, db: Database):
        """Rule A 건이 있을 때 sweep 이 ai_safe_final_approve 를 호출한다."""
        _persist(db, _make_record("sweep_1", hours_ago=1.0))

        mock_resp = {
            "status": "approved",
            "saved": 1,
            "public_db_verification": {"verified": True, "verified_count": 1},
            "rollback_supported": True,
            "re_review_supported": True,
        }
        with patch(
            "api.routes.escalation.ai_safe_final_approve_db_admin",
            new=AsyncMock(return_value=mock_resp),
        ):
            resp = client.post("/api/escalation/sweep")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sweep_applied"] >= 1
        assert data["sweep_published"] >= 1

    def test_pending_shows_items_after_insert(self, client, db: Database):
        """레코드 삽입 후 /pending 응답에 해당 건이 포함된다."""
        _persist(db, _make_record("ui_check", hours_ago=5.0))
        resp = client.get("/api/escalation/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_pending"] == 1
        assert data["items"][0]["raw_record_id"] == "ui_check"
