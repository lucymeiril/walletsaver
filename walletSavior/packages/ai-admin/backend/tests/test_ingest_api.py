"""Raw ingest -> AI proposal persistence tests."""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.control_plane import ProviderConfigContract
from services import ai_ingestion
from storage import Database, ProviderConfigRepository, create_database


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = create_database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = create_app()

    def _override() -> Iterator[Session]:
        session = db.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    class FakeProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            assert "오리온 오징어 땅콩" in prompt
            return {
                "items": [
                    {
                        "raw_record_id": "r1",
                        "canonical_name": "오리온 오징어 땅콩 98g",
                        "brand": "오리온",
                        "category_id": "snack.nut",
                        "keywords": ["오징어땅콩", "과자"],
                        "aliases": ["오징어땅콩"],
                        "attributes": {"snack_type": "nut"},
                        "package_quantity": 98,
                        "package_unit": "g",
                        "bundle_count": 1,
                        "standard_unit": "kg",
                        "standard_unit_price": 20204.08,
                        "confidence": 0.91,
                        "notes": "과자 브랜드 제품",
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: FakeProvider(config),
    )

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_review_db] = lambda: db
    try:
        with db.session_scope() as session:
            ProviderConfigRepository(session).save(
                ProviderConfigContract(
                    provider_id="google-dev",
                    provider_kind="gemini",
                    display_name="Google Dev",
                    default_model="gemma-3-27b-it",
                    secret_alias="GOOGLE_API_KEY",
                )
            )
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_ingest_label_stores_raw_batch_and_proposals(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "r1",
                    "source_name": "emart",
                    "raw_title": "오리온 오징어 땅콩 98g",
                    "raw_price": 1980,
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["records_stored"] == 1
    assert body["ai_batches"] == 1
    assert body["provider_calls"] == 1
    assert body["proposals_stored"] >= 8

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "snack.nut") in values
    assert ("brand", "오리온") in values


def test_ingest_rejects_more_than_30_records(client: TestClient) -> None:
    records = [
        {
            "raw_record_id": f"r{i}",
            "source_name": "emart",
            "raw_title": f"상품 {i}",
            "raw_price": 1000,
        }
        for i in range(31)
    ]
    res = client.post(
        "/api/ingest/raw-records/label",
        json={"provider_id": "google-dev", "source_name": "emart", "records": records},
    )
    assert res.status_code == 422
