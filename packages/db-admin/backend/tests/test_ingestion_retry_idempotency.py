"""Focused retry-idempotency regressions for PendingIngestion submission."""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from storage.models import Base, PendingIngestion
import api.routes.ingestion as ingestion_routes


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
