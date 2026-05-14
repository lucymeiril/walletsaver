import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from storage.models import Base, DiscountHistory, IngestionStatus, PendingIngestion


SERVICE_KEY = "test-service-key"
PUBLISHER_KEY = "test-ai-publisher-key"


@pytest.fixture
def scoped_auth_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

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

    import api.routes.admin as admin_routes
    import api.routes.ingestion as ingestion_routes
    from config import settings

    original_require = settings.REQUIRE_AUTH
    original_keys = settings.SERVICE_API_KEYS
    settings.REQUIRE_AUTH = True
    settings.SERVICE_API_KEYS = {
        SERVICE_KEY: "service",
        PUBLISHER_KEY: "ai_publisher",
    }

    monkeypatch.setattr(ingestion_routes, "get_session", get_test_session)
    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)
    monkeypatch.setattr(admin_routes, "get_session", get_test_session)
    monkeypatch.setattr(admin_routes, "list_backups", lambda: [{"filename": "snapshot.sqlite", "size_bytes": 1}])

    from api.app import create_app

    try:
        yield TestClient(create_app()), Session
    finally:
        settings.REQUIRE_AUTH = original_require
        settings.SERVICE_API_KEYS = original_keys


def _publisher_headers():
    return {"X-API-Key": PUBLISHER_KEY}


def _service_headers():
    return {"X-API-Key": SERVICE_KEY}


def _valid_ai_reviewed_item():
    return {
        "name": "테스트 두부 300g",
        "source_title": "테스트 두부 300g",
        "sale_price": 1980,
        "current_price": 1980,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/test-tofu-300g",
        "detail_url": "https://emart.example/products/test-tofu-300g",
        "image_url": "https://emart.example/images/test-tofu-300g.jpg",
        "unit": "300g",
        "display_unit": "300g",
        "package_quantity": 300,
        "package_unit": "g",
        "raw_record_id": "test-tofu-300g",
        "source_record_key": "emart-sku-test-tofu-300g",
        "ai_review_audit": {
            "raw_record_id": "test-tofu-300g",
            "proposal_ids": ["name", "price"],
        },
        "raw_data": {
            "raw_record_id": "test-tofu-300g",
            "source_record_key": "emart-sku-test-tofu-300g",
            "raw_evidence": {"title": "테스트 두부 300g", "price": 1980},
        },
    }


def _create_pending_ai_ingestion(Session, item):
    with Session.begin() as session:
        row = PendingIngestion(
            crawler_name="ai-admin:emart",
            crawl_status="success",
            items_count=1,
            items_json=json.dumps([item], ensure_ascii=False),
            schema_type="DiscountItem",
            strategy_used="ai_review_publish",
            quality_score=100,
            quality_details={},
            status=IngestionStatus.PENDING,
        )
        session.add(row)
        session.flush()
        return row.id


def test_service_key_cannot_ai_safe_final_approve(scoped_auth_client):
    client, Session = scoped_auth_client
    ingestion_id = _create_pending_ai_ingestion(Session, _valid_ai_reviewed_item())

    response = client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve"},
        headers=_service_headers(),
    )

    assert response.status_code == 403


def test_service_key_cannot_read_backup_snapshots(scoped_auth_client):
    client, _ = scoped_auth_client

    response = client.get("/api/admin/backups", headers=_service_headers())

    assert response.status_code == 403


def test_scoped_publisher_can_final_approve_and_read_backup_snapshot_list(scoped_auth_client):
    client, Session = scoped_auth_client
    ingestion_id = _create_pending_ai_ingestion(Session, _valid_ai_reviewed_item())

    backup_response = client.get("/api/admin/backups", headers=_publisher_headers())
    assert backup_response.status_code == 200
    assert backup_response.json()["backups"][0]["filename"] == "snapshot.sqlite"

    approve_response = client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve", "notes": "scoped publish"},
        headers=_publisher_headers(),
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    with Session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        assert row.status == IngestionStatus.APPROVED
        assert session.query(DiscountHistory).count() == 1


def test_scoped_publisher_is_denied_unrelated_moderator_and_admin_endpoints(scoped_auth_client):
    client, Session = scoped_auth_client
    ingestion_id = _create_pending_ai_ingestion(Session, _valid_ai_reviewed_item())

    assert client.get("/api/admin/data-summary", headers=_publisher_headers()).status_code == 403
    assert client.post("/api/admin/backup", headers=_publisher_headers()).status_code == 403
    assert client.post(
        "/api/ingestions",
        json={"crawler_name": "test", "items": []},
        headers=_publisher_headers(),
    ).status_code == 403
    assert client.post(
        "/api/ingestions/bulk-approve",
        json={"ids": [ingestion_id]},
        headers=_publisher_headers(),
    ).status_code == 403
    assert client.delete(f"/api/ingestions/{ingestion_id}", headers=_publisher_headers()).status_code == 403


def test_scoped_publisher_still_cannot_bypass_ai_safe_validation_gates(scoped_auth_client):
    client, Session = scoped_auth_client
    bad_item = _valid_ai_reviewed_item()
    bad_item.pop("image_url")
    bad_item.pop("source_url")
    bad_item.pop("detail_url")
    ingestion_id = _create_pending_ai_ingestion(Session, bad_item)

    response = client.post(
        f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
        json={"action": "approve"},
        headers=_publisher_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert any("missing customer-visible fields" in blocker for blocker in body["blockers"])
    with Session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        assert row.status == IngestionStatus.PENDING
        assert session.query(DiscountHistory).count() == 0
