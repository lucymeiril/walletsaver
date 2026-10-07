"""Focused retry-idempotency regressions for PendingIngestion submission."""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from storage.models import Base, PendingIngestion, IngestionStatus
import api.routes.ingestion as ingestion_routes


@pytest.mark.parametrize("action", ["approve", "partial", "bulk"])
def test_matched_approval_uses_persisted_receipt_clock(ingestion_db, monkeypatch, action):
    receipt = datetime(2026, 10, 4, 11, 18, 13)
    with ingestion_db.begin() as session:
        row = PendingIngestion(crawler_name="홈플러스", crawl_status="success", schema_type="DiscountItem",
            items_count=1, items_json=json.dumps([{"public_product_id": "existing-product"}]),
            status=IngestionStatus.CRAWLER_APPROVED, crawled_at=receipt)
        session.add(row)
        session.flush()
        identity = row.id
    captured = []
    def insert(session, items, schema, *, observed_at):
        captured.append(observed_at)
        return len(items)
    monkeypatch.setattr(ingestion_routes, "_insert_items", insert)
    if action == "bulk":
        result = ingestion_routes.bulk_approve(ingestion_routes.BulkApproveRequest(ids=[identity]), {"role": "admin"})
    else:
        result = ingestion_routes._db_review_once(identity, ingestion_routes.ReviewRequest(
            action=action, approved_item_indices=[0] if action == "partial" else None))
        assert result["saved"] == 1
    assert captured == [receipt]


@pytest.mark.parametrize("action", ["approve", "partial", "bulk"])
def test_raw_approval_reports_pending_normalized_publication_without_erasing_source(ingestion_db, action):
    from sqlalchemy import select
    from storage.models import DiscountHistory, NormalizedCanonicalProduct
    source_json = json.dumps([{"name": "분류 미검토 라면120g*5", "source": "emart", "sale_price": 4150,
        "source_record_key": "test-native", "source_url": "https://emart.ssg.com/item/itemView.ssg?itemId=test-native",
        "crawled_at": "2026-10-07T08:00:00Z"}], ensure_ascii=False)
    with ingestion_db.begin() as session:
        row = PendingIngestion(crawler_name="emart", crawl_status="success", schema_type="DiscountItem",
            items_count=1, items_json=source_json, status=IngestionStatus.CRAWLER_APPROVED)
        session.add(row)
        session.flush()
        identity = row.id
    if action == "bulk":
        response = ingestion_routes.bulk_approve(ingestion_routes.BulkApproveRequest(ids=[identity], notes="원문 확인"), {"role": "admin"})["results"][0]
    else:
        response = ingestion_routes._db_review_once(identity, ingestion_routes.ReviewRequest(
            action=action, notes="원문 확인", approved_item_indices=[0] if action == "partial" else None))
    assert response["saved"] == 1 and response["normalized_pending_review"] == 1
    with ingestion_db() as session:
        row = session.get(PendingIngestion, identity)
        assert row.status in {IngestionStatus.APPROVED, IngestionStatus.PARTIAL}
        assert row.items_json == source_json
        assert "원문 확인" in row.db_reviewer_notes and "정규화 공개 반영 보류 1건" in row.db_reviewer_notes
        assert "unified_category_review_required" in row.db_reviewer_notes
        assert session.execute(select(DiscountHistory)).scalar_one().price == 4150
        assert session.execute(select(NormalizedCanonicalProduct)).scalars().all() == []


@pytest.fixture()
def ingestion_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(ingestion_routes, "get_session", get_test_session)
    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)
    yield Session
    engine.dispose()


def _body(run_id: str):
    return ingestion_routes.IngestionSubmit(
        crawler_name="emart_crawler",
        crawl_status="success",
        items=[
            {
                "name": "테스트 상품",
                "sale_price": 1200,
                "source": "emart",
            }
        ],
        schema_type="DiscountItem",
        quality_score=95.0,
        quality_details={
            "score": 95.0,
            "ingestion_run_id": run_id,
            "ingestion_chunk": {
                "index": 1,
                "offset": 0,
                "size": 1,
                "total_items": 1,
            },
        },
    )


def test_same_retry_identity_reuses_pending_ingestion(ingestion_db):
    first = ingestion_routes._submit_ingestion_idempotent_impl(
        _body("ingrun-retry-one"),
        {"role": "service"},
    )
    second = ingestion_routes._submit_ingestion_idempotent_impl(
        _body("ingrun-retry-one"),
        {"role": "service"},
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["id"] == first["id"]

    Session = ingestion_db
    with Session() as session:
        rows = session.query(PendingIngestion).all()
        assert len(rows) == 1
        details = rows[0].quality_details
        assert details["ingestion_submission_key"] == "ingrun-retry-one:chunk:1"
        assert json.loads(rows[0].items_json)[0]["name"] == "테스트 상품"


def test_reviewed_capture_retry_reports_persisted_state_without_reset(ingestion_db):
    body = _body("ingrun-reviewed-retry")
    first = ingestion_routes._submit_ingestion_idempotent_impl(body, {"role": "service"})
    assert first["current_status"] == "pending"
    with ingestion_db.begin() as session:
        row = session.get(PendingIngestion, first["id"])
        row.status = IngestionStatus.APPROVED
        row.db_reviewer_notes = "source-bound review retained"
        before = (row.items_json, row.crawled_at, dict(row.quality_details))

    replay = ingestion_routes._submit_ingestion_idempotent_impl(body, {"role": "service"})
    assert replay["id"] == first["id"]
    assert replay["idempotent"] is True
    assert replay["current_status"] == "approved"
    assert replay["status"] == "pending"  # Existing acknowledgement contract.
    with ingestion_db() as session:
        assert session.query(PendingIngestion).count() == 1
        row = session.get(PendingIngestion, first["id"])
        assert row.status == IngestionStatus.APPROVED
        assert row.db_reviewer_notes == "source-bound review retained"
        assert (row.items_json, row.crawled_at, row.quality_details) == before


def test_new_crawler_run_with_same_items_creates_new_submission(ingestion_db):
    first = ingestion_routes._submit_ingestion_idempotent_impl(
        _body("ingrun-first"),
        {"role": "service"},
    )
    second = ingestion_routes._submit_ingestion_idempotent_impl(
        _body("ingrun-second"),
        {"role": "service"},
    )

    assert first["id"] != second["id"]
    assert first["idempotent"] is False
    assert second["idempotent"] is False

    Session = ingestion_db
    with Session() as session:
        assert session.query(PendingIngestion).count() == 2
