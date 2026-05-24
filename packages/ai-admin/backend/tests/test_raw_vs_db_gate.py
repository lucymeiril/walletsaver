"""rd3-rawvsdb-gate 단위 테스트.

테스트 케이스:
    1. test_costco_occ_silent_gap  — 코스트코 OCC 995×3 raw → 0 ai_raw → status=fail (회귀 차단)
    2. test_normal_pass            — 정상 케이스 (drop < 5%) → status=pass
    3. test_exact_threshold_fail   — drop = threshold + epsilon → status=fail
    4. test_exact_threshold_pass   — drop = threshold - epsilon → status=pass
    5. test_no_data                — 존재하지 않는 run_id → status=no_data
    6. test_multi_batch_prefix     — root_batch_id 접두어로 멀티-배치 합산
    7. test_env_threshold_override — ENV 오버라이드 (10%) 동작 확인
    8. test_stages_keys            — stages 리스트에 필수 키 포함 확인
    9. test_by_mart_dynamic        — by_mart가 source_name을 코드 수정 없이 열거
    10. test_summary_endpoint      — /api/raw_vs_db_gate/summary 응답 구조 확인
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 보정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from storage.models import Base, RawCrawlBatch, RawCrawlRecord, ProductMatch, AIPublishRecord
from services.raw_vs_db_gate import compare, get_threshold, _THRESHOLD_ENV


# ── 픽스처 ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_session() -> Iterator[Session]:
    """In-memory SQLite 세션 — 테스트 격리."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def _make_batch(
    session: Session,
    batch_id: str,
    source_name: str,
    item_count: int,
) -> RawCrawlBatch:
    """RawCrawlBatch 행을 생성해 session에 추가한다."""
    batch = RawCrawlBatch(
        batch_id=batch_id,
        source_name=source_name,
        crawler_name="test_crawler",
        item_count=item_count,
        schema_type="mart_discount",
        status="raw_ingested",
        created_at=datetime.now(),
    )
    session.add(batch)
    session.flush()
    return batch


def _make_record(
    session: Session,
    batch_id: str,
    source_name: str,
    raw_record_id: str | None = None,
) -> RawCrawlRecord:
    """RawCrawlRecord 행을 생성한다."""
    record = RawCrawlRecord(
        raw_record_id=raw_record_id or f"rec-{uuid.uuid4().hex[:12]}",
        batch_id=batch_id,
        source_name=source_name,
        raw_title=f"상품-{uuid.uuid4().hex[:4]}",
        raw_payload={},
        crawled_at=datetime.now(),
    )
    session.add(record)
    session.flush()
    return record


def _make_match(
    session: Session,
    batch_id: str,
    canonical_product_id: str | None = "cid-001",
) -> ProductMatch:
    """ProductMatch 행을 생성한다."""
    match = ProductMatch(
        match_id=f"match-{uuid.uuid4().hex[:12]}",
        source_id=f"src-{uuid.uuid4().hex[:8]}",
        source_name="costco",
        signature_key=f"sig-{uuid.uuid4().hex[:8]}",
        canonical_product_name="테스트 상품",
        canonical_product_id=canonical_product_id,
        provenance_source="ai",
        status="approved",
        audit_reason="test",
        batch_id=batch_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(match)
    session.flush()
    return match


def _make_publish(
    session: Session,
    batch_id: str,
    raw_record_id: str,
    status: str = "published",
) -> AIPublishRecord:
    """AIPublishRecord 행을 생성한다."""
    record = AIPublishRecord(
        raw_record_id=raw_record_id,
        batch_id=batch_id,
        source_name="costco",
        status=status,
        updated_at=datetime.now(),
    )
    session.add(record)
    session.flush()
    return record


# ── 테스트 ──────────────────────────────────────────────────────────────────────

class TestCostcoSilentGap:
    """코스트코 OCC 995×3 → 0 ai_raw 회귀 차단 케이스."""

    def test_costco_occ_silent_gap(self, db_session: Session) -> None:
        """995×3 raw → 0 ai_raw → drop_pct=1.0 → status=fail."""
        run_id = "source-20240601T120000Z-costco01"
        # 3개 배치 (멀티-배치 split 시뮬레이션)
        for i in range(1, 4):
            _make_batch(db_session, f"{run_id}-{i:03d}", "costco", 995)
        # RawCrawlRecord 0건 — silent gap

        result = compare(run_id, db_session)

        assert result["raw_count"] == 2985, f"raw_count 오류: {result['raw_count']}"
        assert result["ai_raw_count"] == 0, f"ai_raw_count 오류: {result['ai_raw_count']}"
        assert result["drop_pct"] == 1.0
        assert result["status"] == "fail", f"status가 fail이어야 함: {result['status']}"
        # stages[0]에 alert가 켜져야 함
        assert result["stages"][0]["alert"] is True


class TestNormalPass:
    """drop < 5% → pass 케이스."""

    def test_normal_pass(self, db_session: Session) -> None:
        """100개 전송 → 98개 저장 (drop=2%) → pass."""
        run_id = "source-20240601T120000Z-normal"
        _make_batch(db_session, f"{run_id}-001", "emart", 100)
        for _ in range(98):
            _make_record(db_session, f"{run_id}-001", "emart")

        result = compare(run_id, db_session)

        assert result["raw_count"] == 100
        assert result["ai_raw_count"] == 98
        assert result["drop_pct"] == pytest.approx(0.02, abs=0.0001)
        assert result["status"] == "pass"
        assert result["stages"][0]["alert"] is False


class TestThresholdBoundary:
    """임계치 경계 케이스."""

    def test_exact_threshold_fail(self, db_session: Session) -> None:
        """drop = 0.06 (threshold 0.05 초과) → fail."""
        run_id = f"batch-threshold-fail-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, run_id, "lotte", 100)
        for _ in range(94):  # 94/100 → drop=0.06
            _make_record(db_session, run_id, "lotte")

        result = compare(run_id, db_session)
        assert result["status"] == "fail"

    def test_exact_threshold_pass(self, db_session: Session) -> None:
        """drop = 0.04 (threshold 0.05 이하) → pass."""
        run_id = f"batch-threshold-pass-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, run_id, "homeplus", 100)
        for _ in range(96):  # 96/100 → drop=0.04
            _make_record(db_session, run_id, "homeplus")

        result = compare(run_id, db_session)
        assert result["status"] == "pass"


class TestNoData:
    """데이터 없음 케이스."""

    def test_no_data(self, db_session: Session) -> None:
        """존재하지 않는 run_id → status=no_data, raw_count=0."""
        result = compare("nonexistent-run-id", db_session)

        assert result["status"] == "no_data"
        assert result["raw_count"] == 0
        assert result["ai_raw_count"] == 0
        assert result["drop_pct"] is None


class TestMultiBatch:
    """멀티-배치 prefix 매칭 케이스."""

    def test_multi_batch_prefix(self, db_session: Session) -> None:
        """root_batch_id 접두어로 멀티-배치 합산이 동작한다."""
        run_id = f"source-20240601T120000Z-{uuid.uuid4().hex[:8]}"
        # 3개 배치, 각 30개 = 총 90개
        for i in range(1, 4):
            _make_batch(db_session, f"{run_id}-{i:03d}", "costco", 30)
        # 85개 저장 → drop = 5/90 ≈ 5.6% > 5% → fail
        for j in range(85):
            _make_record(db_session, f"{run_id}-{(j % 3) + 1:03d}", "costco")

        result = compare(run_id, db_session)

        assert result["raw_count"] == 90
        assert result["ai_raw_count"] == 85
        assert result["status"] == "fail"

    def test_exact_batch_still_matched(self, db_session: Session) -> None:
        """단일 배치 batch_id가 정확히 일치하는 경우도 동작한다."""
        bid = f"raw-{uuid.uuid4().hex[:16]}"
        _make_batch(db_session, bid, "coupang", 10)
        for _ in range(10):
            _make_record(db_session, bid, "coupang")

        result = compare(bid, db_session)

        assert result["raw_count"] == 10
        assert result["ai_raw_count"] == 10
        assert result["drop_pct"] == 0.0
        assert result["status"] == "pass"


class TestEnvThreshold:
    """ENV 오버라이드 케이스."""

    def test_env_threshold_override(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """WALLETSAVIOR_RAWVSDB_DROP_THRESHOLD=0.10 → 7% drop 시 pass."""
        monkeypatch.setenv(_THRESHOLD_ENV, "0.10")
        run_id = f"batch-env-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, run_id, "emart", 100)
        for _ in range(93):  # 7% drop
            _make_record(db_session, run_id, "emart")

        result = compare(run_id, db_session)

        assert result["threshold"] == pytest.approx(0.10, abs=0.001)
        assert result["status"] == "pass"

    def test_env_threshold_invalid_ignored(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENV 값이 유효하지 않으면 기본값(5%) 사용."""
        monkeypatch.setenv(_THRESHOLD_ENV, "not_a_number")
        assert get_threshold() == pytest.approx(0.05, abs=0.001)


class TestStagesKeys:
    """stages 구조 검증."""

    def test_stages_keys(self, db_session: Session) -> None:
        """stages 리스트에 필수 키가 포함되어야 한다."""
        run_id = f"batch-stages-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, run_id, "costco", 10)

        result = compare(run_id, db_session)

        required_keys = {"stage", "in", "out", "drop_pct", "alert"}
        for stage in result["stages"]:
            assert required_keys <= stage.keys(), f"stage 키 누락: {stage}"
        assert len(result["stages"]) == 3

    def test_result_keys(self, db_session: Session) -> None:
        """반환 dict에 필수 최상위 키가 모두 포함되어야 한다."""
        run_id = f"batch-keys-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, run_id, "costco", 5)

        result = compare(run_id, db_session)

        required = {
            "source_run_id", "raw_count", "ai_raw_count",
            "match_count", "canonical_count", "publish_count",
            "drop_pct", "threshold", "status", "stages", "by_mart",
        }
        assert required <= result.keys()


class TestByMartDynamic:
    """by_mart 동적 마트 열거 케이스."""

    def test_by_mart_dynamic(self, db_session: Session) -> None:
        """by_mart가 source_name을 코드 수정 없이 자동 열거한다."""
        run_id = f"batch-mart-{uuid.uuid4().hex[:8]}"
        # 두 개 마트
        _make_batch(db_session, f"{run_id}-001", "costco", 50)
        _make_batch(db_session, f"{run_id}-002", "emart", 30)
        for _ in range(50):
            _make_record(db_session, f"{run_id}-001", "costco")
        for _ in range(25):
            _make_record(db_session, f"{run_id}-002", "emart")

        result = compare(run_id, db_session)

        assert "costco" in result["by_mart"]
        assert "emart" in result["by_mart"]
        assert result["by_mart"]["costco"]["raw_count"] == 50
        assert result["by_mart"]["costco"]["ai_raw_count"] == 50
        assert result["by_mart"]["emart"]["raw_count"] == 30
        assert result["by_mart"]["emart"]["ai_raw_count"] == 25

    def test_by_mart_silent_gap_costco(self, db_session: Session) -> None:
        """코스트코만 silent gap → by_mart에 drop_pct=1.0."""
        run_id = f"batch-mart-gap-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, f"{run_id}-001", "costco", 995)
        # 0 records for costco

        result = compare(run_id, db_session)

        assert result["by_mart"]["costco"]["drop_pct"] == 1.0


class TestMatchAndPublish:
    """match/publish 단계 카운트 검증."""

    def test_match_publish_counts(self, db_session: Session) -> None:
        """match_count, canonical_count, publish_count가 올바르게 집계된다."""
        run_id = f"batch-full-{uuid.uuid4().hex[:8]}"
        _make_batch(db_session, f"{run_id}-001", "costco", 10)
        recs = [_make_record(db_session, f"{run_id}-001", "costco") for _ in range(10)]

        # 5개 match, 3개 canonical
        for i in range(5):
            cid = f"cid-{i % 3:03d}"
            _make_match(db_session, f"{run_id}-001", canonical_product_id=cid)

        # 3개 publish
        for rec in recs[:3]:
            _make_publish(db_session, f"{run_id}-001", rec.raw_record_id, status="published")
        # 2개 pending
        for rec in recs[3:5]:
            _make_publish(db_session, f"{run_id}-001", rec.raw_record_id, status="pending_review")

        result = compare(run_id, db_session)

        assert result["match_count"] == 5
        assert result["canonical_count"] == 3
        assert result["publish_count"] == 3
