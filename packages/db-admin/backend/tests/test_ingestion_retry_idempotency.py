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
