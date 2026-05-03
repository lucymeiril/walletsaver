"""Raw ingest -> AI proposal persistence tests."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.control_plane import ProviderConfigContract
from services import ai_ingestion
from storage import Database, ProviderConfigRepository, RawCrawlBatchRepository, create_database


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
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            return {
                "items": [
                    {
                        "raw_record_id": record_id,
                        "canonical_name": (
                            "오리온 오징어 땅콩 98g"
                            if "orion" in record_id or record_id == "r1"
                            else "이마트 테스트 상품"
                        ),
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
                    for record_id in record_ids
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


def _load_crawler_ai_export():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "packages" / "crawler-admin" / "backend" / "pipeline" / "ai_export.py"
    spec = importlib.util.spec_from_file_location("crawler_ai_export_for_e2e", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_emart_crawler_batches_ingest_and_persist_ai_proposals(
    client: TestClient,
    db: Database,
) -> None:
    crawler_ai_export = _load_crawler_ai_export()
    items = [
        {
            "product_id": "orion-squid-peanut",
            "name": "오리온 오징어 땅콩 98g",
            "sale_price": "1,980원",
            "detail_url": "https://emart.example/products/orion-squid-peanut",
            "category": "과자",
        },
        *[
            {
                "product_id": f"emart-test-{i}",
                "name": f"이마트 테스트 상품 {i}",
                "sale_price": f"{1000 + i}원",
                "detail_url": f"https://emart.example/products/{i}",
                "category": "테스트",
            }
            for i in range(31)
        ],
    ]
    _, record_batches, skipped = crawler_ai_export.build_raw_batches(
        items,
        source_name="emart",
        crawler_name="emart_crawler",
        schema_type="mart_discount",
        batch_id="raw-emart-e2e",
    )
    assert skipped == 0
    assert [len(records) for records in record_batches] == [30, 2]

    raw_batch_ids = []
    for records in record_batches:
        assert len(records) <= 30
        assert sum(len(record.prompt_text()) for record in records) <= 2000
        response = client.post(
            "/api/ingest/raw-records/label",
            json={
                "provider_id": "google-dev",
                "source_name": "emart",
                "crawler_name": "emart_crawler",
                "schema_type": "mart_discount",
                "records": [record.model_dump(mode="json") for record in records],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["records_stored"] == len(records)
        assert body["proposals_stored"] >= len(records) * 8
        raw_batch_ids.append(body["raw_batch_id"])

    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        persisted_records = [
            record
            for batch_id in raw_batch_ids
            for record in raw_repo.list_records(batch_id)
        ]
    assert len(persisted_records) == 32
    assert any(record.raw_title == "오리온 오징어 땅콩 98g" for record in persisted_records)

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "snack.nut") in values
    assert ("package_unit", "g") in values
    assert ("keywords", "오징어땅콩") in values
