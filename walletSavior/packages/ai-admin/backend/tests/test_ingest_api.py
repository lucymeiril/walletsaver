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
from providers.google_genai import ProviderResponseError
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
            records = re.findall(r"- id=([^;]+); source=[^;]+; title=([^;]+); price=([^\n]+)", prompt)
            if not records:
                records = [(record_id, "", "") for record_id in re.findall(r"- id=([^;]+);", prompt)]

            def _label(record_id: str, title: str) -> dict:
                if "두부" in title or "tofu" in record_id:
                    canonical_name = "풀무원 국산콩 두부 300g"
                    brand = "풀무원"
                    category_id = "fresh.tofu"
                    keywords = ["두부", "국산콩", "마트특가"]
                    aliases = ["국산콩두부"]
                    attributes = {"food_type": "tofu"}
                    package_quantity = 300
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 9966.67
                elif "삼겹살" in title or "meat" in record_id:
                    canonical_name = "국내산 삼겹살 600g"
                    brand = "정육"
                    category_id = "fresh.meat"
                    keywords = ["삼겹살", "돼지고기", "핫딜"]
                    aliases = ["국내산삼겹살"]
                    attributes = {"meat_cut": "pork_belly"}
                    package_quantity = 600
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 19800
                elif "orion" in record_id or record_id == "r1":
                    canonical_name = "오리온 오징어 땅콩 98g"
                    brand = "오리온"
                    category_id = "snack.nut"
                    keywords = ["오징어땅콩", "과자"]
                    aliases = ["오징어땅콩"]
                    attributes = {"snack_type": "nut"}
                    package_quantity = 98
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 20204.08
                else:
                    canonical_name = "이마트 테스트 상품"
                    brand = "이마트"
                    category_id = "mart.test"
                    keywords = ["테스트"]
                    aliases = ["테스트상품"]
                    attributes = {"source": "mart"}
                    package_quantity = 1
                    package_unit = "ea"
                    standard_unit = "ea"
                    standard_unit_price = 1000
                return {
                    "raw_record_id": record_id,
                    "canonical_name": canonical_name,
                    "brand": brand,
                    "category_id": category_id,
                    "keywords": keywords,
                    "aliases": aliases,
                    "attributes": attributes,
                    "package_quantity": package_quantity,
                    "package_unit": package_unit,
                    "bundle_count": 1,
                    "standard_unit": standard_unit,
                    "standard_unit_price": standard_unit_price,
                    "confidence": 0.91,
                    "notes": "real-shaped hotdeal/mart product",
                }

            return {
                "items": [_label(record_id, title) for record_id, title, _price in records]
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


def test_ingest_label_handles_realistic_hotdeal_food_records(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "ppomppu",
            "crawler_name": "ppomppu_hotdeal",
            "schema_type": "hotdeal",
            "records": [
                {
                    "raw_record_id": "hotdeal:tofu-300g",
                    "source_name": "ppomppu",
                    "source_url": "https://ppomppu.example/post/tofu",
                    "raw_title": "[이마트] 풀무원 국산콩 두부 300g 2,990원",
                    "raw_price": 2990,
                    "raw_payload": {"mall": "이마트", "discount": "행사"},
                },
                {
                    "raw_record_id": "hotdeal:meat-600g",
                    "source_name": "ppomppu",
                    "source_url": "https://ppomppu.example/post/meat",
                    "raw_title": "[마트] 국내산 삼겹살 600g 11,880원",
                    "raw_price": 11880,
                    "raw_payload": {"mall": "동네마트", "shipping": "매장픽업"},
                },
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["records_stored"] == 2
    assert body["provider_calls"] == 1
    assert body["proposals_stored"] >= 16

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "fresh.tofu") in values
    assert ("category_id", "fresh.meat") in values
    assert ("keywords", "두부") in values


def test_labeling_response_overrides_emart_100g_hint_with_package_metadata() -> None:
    provider = ai_ingestion._provider_ref(
        ProviderConfigContract(
            provider_id="local",
            provider_kind="gemini",
            display_name="Local",
            default_model="fake",
            secret_alias="NONE",
        )
    )
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="emart-beef",
            source_name="emart",
            raw_title="[냉장] 한우 불고기1+등급300g",
            raw_price=14850,
            raw_payload={"unit": "100g"},
        )
    ]

    proposals = ai_ingestion.proposals_from_labeling_response(
        batch_id="b-emart",
        provider=provider,
        records=records,
        response={
            "items": [
                {
                    "raw_record_id": "emart-beef",
                    "canonical_name": "한우 불고기",
                    "keywords": ["냉장", "한우", "불고기"],
                    "attributes": {},
                    "package_quantity": 100,
                    "package_unit": "g",
                    "display_unit": "100g",
                    "standard_unit_price": 14850,
                }
            ]
        },
    )
    values = {(p.target_field, p.proposed_value) for p in proposals}

    assert ("package_quantity", 300.0) in values
    assert ("package_unit", "g") in values
    assert ("display_unit", "300g") in values
    assert ("price_per_100g", 4950.0) in values
    assert ("attributes.storage_type", "chilled") in values
    assert ("attributes.quality_grade", "1+") in values
    assert ("keywords", "냉장") not in values


def test_ingest_provider_validation_error_returns_actionable_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            return {"items": []}

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: BrokenProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "ppomppu",
            "crawler_name": "ppomppu_hotdeal",
            "schema_type": "hotdeal",
            "records": [
                {
                    "raw_record_id": "hotdeal:tofu-300g",
                    "source_name": "ppomppu",
                    "raw_title": "[이마트] 풀무원 국산콩 두부 300g 2,990원",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail["provider_id"] == "google-dev"
    assert detail["model"] == "gemma-3-27b-it"
    assert detail["stage"] == "provider_response_validation"
    assert detail["row_count"] == 1
    assert detail["raw_batch_id"].startswith("raw-")
    assert ":ai:" in detail["ai_batch_id"]
    assert "missing labels" in detail["message"]


def test_ingest_provider_call_failure_returns_safe_actionable_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            raise ProviderResponseError(
                "Google GenAI provider call failed: quota exhausted for request; key=[REDACTED]",
                provider_id="google-dev",
                model="gemma-3-27b-it",
            )

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: FailingProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "emart:8801111111111",
                    "source_name": "emart",
                    "source_record_key": "8801111111111",
                    "source_url": "https://emart.example/products/8801111111111",
                    "raw_title": "서울우유 나100% 1L 2입",
                    "raw_price": 5980,
                    "raw_payload": {
                        "source": "emart",
                        "name": "서울우유 나100% 1L 2입",
                        "unit": "1L",
                        "quantity": "2개",
                        "category_hint": "우유/유제품",
                        "image_url": "https://emart.example/images/milk.jpg",
                    },
                }
            ],
        },
    )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail["error"] == "ai_ingestion_error"
    assert detail["stage"] == "provider_call"
    assert detail["provider_id"] == "google-dev"
    assert detail["model"] == "gemma-3-27b-it"
    assert detail["row_count"] == 1
    assert detail["raw_batch_id"].startswith("raw-")
    assert ":ai:" in detail["ai_batch_id"]
    assert "quota exhausted" in detail["message"]
    assert "AIza" not in detail["message"]


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
