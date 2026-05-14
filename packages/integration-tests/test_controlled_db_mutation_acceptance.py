"""Controlled DB mutation acceptance for AI-admin -> DB-admin publish.

This test uses an in-memory DB-admin app and a test API key. It proves the
mutation boundary writes real DB rows without using live crawler or AI network.
"""
from __future__ import annotations

import importlib
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent.parent
AI_BACKEND = ROOT / "packages" / "ai-admin" / "backend"
DB_BACKEND = ROOT / "packages" / "db-admin" / "backend"
SHARED = ROOT / "packages" / "shared"

for path in (str(SHARED), str(DB_BACKEND)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from api.routes import admin as admin_routes
from api.routes import ingestion as ingestion_routes
from config import settings
from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from services.normalized_price_read import get_normalized_price_comparison
import storage.models as db_models
from storage.models import (
    Base,
    DiscountHistory,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    PendingIngestion,
    Product,
)

_DB_MODELS = db_models


def _load_ai_admin_modules():
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "services"
        or name.startswith("services.")
        or name == "storage"
        or name.startswith("storage.")
        or name == "providers"
        or name.startswith("providers.")
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AI_BACKEND))
    sys.path.insert(0, str(SHARED))
    try:
        return (
            importlib.import_module("services.review_publish"),
            importlib.import_module("services.db_admin_adapter"),
        )
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == "services"
            or name.startswith("services.")
            or name == "storage"
            or name.startswith("storage.")
            or name == "providers"
            or name.startswith("providers.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


AI_REVIEW_PUBLISH, AI_DB_ADMIN_ADAPTER = _load_ai_admin_modules()


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _patch_db_admin_sessions(monkeypatch, Session) -> None:
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
    monkeypatch.setattr(admin_routes, "get_session", get_test_session)
    monkeypatch.setattr(admin_routes, "list_backups", lambda: [{"filename": "controlled-before-mutation.sqlite"}])


def _db_admin_client(monkeypatch, Session, api_key: str) -> TestClient:
    _patch_db_admin_sessions(monkeypatch, Session)
    original_require = settings.REQUIRE_AUTH
    original_keys = settings.SERVICE_API_KEYS
    settings.REQUIRE_AUTH = True
    settings.SERVICE_API_KEYS = {api_key: "admin"}

    app = FastAPI(title="controlled DB mutation acceptance")
    app.include_router(ingestion_routes.router)
    app.include_router(admin_routes.router, prefix="/api")
    client = TestClient(app)

    def _restore() -> None:
        settings.REQUIRE_AUTH = original_require
        settings.SERVICE_API_KEYS = original_keys

    client._walletsavior_restore_settings = _restore  # type: ignore[attr-defined]
    return client


def _proposal(raw_id: str, target: str, value: Any, *, proposal_type: ProposalType = ProposalType.NORMALIZED_FIELD) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target}",
        proposal_type=proposal_type,
        target_field=target,
        proposed_value=value,
        status=PipelineStatus.APPROVED,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="controlled-acceptance",
            evidence_text=f"controlled acceptance evidence for {target}",
            worker_role=AIWorkerRole.NORMALIZER,
            reviewed_by="controlled-acceptance",
            reviewed_at=datetime(2026, 5, 14, 10, 0, 0),
        ),
    )


def _ai_admin_payload() -> dict[str, Any]:
    record = RawCrawlRecord(
        raw_record_id="controlled-emart-tofu-300g",
        source_name="emart",
        source_record_key="controlled-emart-tofu-300g",
        source_url="https://emart.example/controlled/tofu",
        raw_title="원천명 국산콩 두부 300g",
        raw_price=1980,
        crawled_at=datetime(2026, 5, 14, 10, 0, 0),
        raw_payload={
            "name": "원천명 국산콩 두부 300g",
            "source": "emart",
            "store": "이마트",
            "sale_price": 1980,
            "original_price": 2300,
            "discount_percent": 13,
            "unit": "300g",
            "source_url": "https://emart.example/controlled/tofu",
            "image_url": "https://emart.example/controlled/tofu.jpg",
            "promotion_type": "final_price",
            "event_name": "controlled acceptance event",
            "valid_from": "2026-05-14T00:00:00",
            "valid_to": "2026-05-20T23:59:59",
        },
    )
    proposals = [
        _proposal(record.raw_record_id, "canonical_name", "풀무원 국산콩 두부"),
        _proposal(record.raw_record_id, "category_id", "processed.tofu", proposal_type=ProposalType.CATEGORY),
        _proposal(record.raw_record_id, "keywords", ["두부"], proposal_type=ProposalType.KEYWORD),
        _proposal(record.raw_record_id, "brand", "풀무원"),
        _proposal(record.raw_record_id, "sale_price", 777),
        _proposal(record.raw_record_id, "source_url", "https://ai.example/wrong"),
        _proposal(record.raw_record_id, "image_url", "https://ai.example/wrong.jpg"),
    ]
    item = AI_REVIEW_PUBLISH.db_item_from_review(record, proposals, {})
    return AI_DB_ADMIN_ADAPTER.build_db_admin_ingestion_payload(
        {
            "raw_record_id": record.raw_record_id,
            "batch_id": "controlled-db-mutation-acceptance",
            "source_name": record.source_name,
            "proposal_ids": [proposal.proposal_id for proposal in proposals],
            "human_decision_ids": ["controlled-acceptance-decision"],
            "db_handoff_mode": "ai_safe_final_approve",
            "publication_kind": item["publication_kind"],
            "item": item,
        }
    )


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def test_controlled_ai_admin_payload_mutates_db_admin_and_reads_normalized_model(monkeypatch):
    Session = _session_factory()
    api_key = "controlled-test-admin-key"
    client = _db_admin_client(monkeypatch, Session, api_key)
    try:
        with Session() as session:
            assert session.scalar(select(func.count()).select_from(Product)) == 0
            assert session.scalar(select(func.count()).select_from(DiscountHistory)) == 0
            assert session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct)) == 0

        stats_response = client.get("/api/ingestions/stats", headers=_headers(api_key))
        assert stats_response.status_code == 200, stats_response.text
        backup_response = client.get("/api/admin/backups", headers=_headers(api_key))
        assert backup_response.status_code == 200, backup_response.text
        assert backup_response.json()["backups"][0]["filename"] == "controlled-before-mutation.sqlite"

        payload = _ai_admin_payload()
        item = payload["items"][0]
        normalized = item["raw_data"]["normalized"]
        assert normalized["source_owned_fields"]["price"] == 1980
        assert normalized["offer_event"]["price"] == 1980
        assert normalized["source_listing"]["source_url"] == "https://emart.example/controlled/tofu"
        assert normalized["offer_event"]["audit_provenance"]["ignored_source_owned_ai_fields"]["sale_price"] == 777

        http_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        submit_response = client.post("/api/ingestions", json=http_payload, headers=_headers(api_key))
        assert submit_response.status_code == 200, submit_response.text
        ingestion_id = submit_response.json()["id"]

        with Session() as session:
            queued = session.get(PendingIngestion, ingestion_id)
            assert queued is not None
            assert queued.status.value == "pending"
            assert session.scalar(select(func.count()).select_from(Product)) == 0

        approve_response = client.post(
            f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
            json={"action": "approve", "notes": "controlled DB mutation acceptance"},
            headers=_headers(api_key),
        )
        assert approve_response.status_code == 200, approve_response.text
        approved = approve_response.json()
        assert approved["status"] == "approved"
        assert approved["saved"] == 1
        assert approved["public_db_verification"]["verified"] is True
        assert approved["rollback_supported"] is True
        assert approved["re_review_supported"] is True

        with Session() as session:
            assert session.scalar(select(func.count()).select_from(Product)) == 1
            assert session.scalar(select(func.count()).select_from(DiscountHistory)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedProductVariant)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedSourceListing)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedOfferEvent)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedWeekBucket)) == 1
            assert session.scalar(select(func.count()).select_from(NormalizedOfferWeekLink)) == 1

            history = session.execute(select(DiscountHistory)).scalar_one()
            assert history.price == 1980
            assert history.source_url == "https://emart.example/controlled/tofu"
            assert history.raw_data["normalized"]["source_listing"]["image_url"] == "https://emart.example/controlled/tofu.jpg"

            model = get_normalized_price_comparison(session, category_id=item["category_id"])

        assert model["products"][0]["canonical_name"] == "풀무원 국산콩 두부"
        listing = model["products"][0]["variants"][0]["source_listings"][0]
        assert listing["source_name"] == "emart"
        assert listing["best_comparable_price"] == 1980
        assert listing["offer_events"][0]["comparable_price"] == 1980
        assert listing["offer_events"][0]["display_state"] == "comparable"
    finally:
        client._walletsavior_restore_settings()  # type: ignore[attr-defined]
