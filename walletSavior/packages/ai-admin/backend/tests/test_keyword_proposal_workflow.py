from __future__ import annotations

import re
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.control_plane import ProviderConfigContract
from services import ai_ingestion
from core.contracts.ai_pipeline import RawCrawlRecord
from services.keyword_catalog import KeywordCatalogAdapter, build_keyword_outputs
from storage import Database, ProviderConfigRepository, create_database


@pytest.fixture()
def control_db(tmp_path) -> Iterator[Database]:
    database = create_database(f"sqlite:///{(tmp_path / 'ai-control.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def db_admin_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{(tmp_path / 'db-admin.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE keywords ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "word VARCHAR(100) UNIQUE NOT NULL, "
                "synonyms JSON, "
                "category_id VARCHAR(100), "
                "search_count INTEGER DEFAULT 0, "
                "is_active BOOLEAN DEFAULT 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO keywords (word, synonyms, category_id, search_count, is_active) "
                "VALUES ('두부', '[\"국산콩두부\"]', 'processed.tofu.firm', 0, 1)"
            )
        )
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR(255))"))
        conn.execute(text("INSERT INTO products (id, name) VALUES (1, '양배추')"))
        conn.execute(
            text(
                "CREATE TABLE product_keywords ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "product_id INTEGER NOT NULL, "
                "keyword_id INTEGER NOT NULL, "
                "UNIQUE(product_id, keyword_id))"
            )
        )
    monkeypatch.setattr(KeywordCatalogAdapter, "__init__", lambda self, database_url=None: _init_adapter(self, url))
    return url


def _init_adapter(adapter: KeywordCatalogAdapter, url: str) -> None:
    adapter.database_url = url
    adapter.engine = create_engine(url, connect_args={"check_same_thread": False})


@pytest.fixture()
def client(
    control_db: Database,
    db_admin_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    app = create_app()

    def _override() -> Iterator[Session]:
        session = control_db.session()
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
            items = []
            for record_id, title, _price in records:
                is_existing = "existing" in record_id
                is_cabbage = "양배추" in title
                items.append(
                    {
                        "raw_record_id": record_id,
                        "canonical_name": title.strip(),
                        "brand": "테스트",
                        "category_id": (
                            "processed.tofu.firm"
                            if is_existing
                            else ("vegetable.cabbage" if is_cabbage else "processed.sauce.ssamjang")
                        ),
                        "keywords": (
                            ["국산두부"]
                            if is_existing
                            else (["양배추", "통", "cabbage"] if is_cabbage else ["쌈장"])
                        ),
                        "aliases": (
                            ["행사두부"]
                            if is_existing
                            else (["cabbage", "통"] if is_cabbage else ["고기쌈장", "행사쌈장"])
                        ),
                        "attributes": {"source": "test"},
                        "package_quantity": 1,
                        "package_unit": "개",
                        "bundle_count": 1,
                        "standard_unit": "개",
                        "standard_unit_price": 1000,
                        "confidence": 0.9,
                        "notes": "keyword workflow test",
                    }
                )
            return {"items": items}

    monkeypatch.setattr(ai_ingestion, "provider_from_config", lambda config: FakeProvider(config))
    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_review_db] = lambda: control_db
    with control_db.session_scope() as session:
        ProviderConfigRepository(session).save(
            ProviderConfigContract(
                provider_id="google-dev",
                provider_kind="gemini",
                display_name="Google Dev",
                default_model="gemma-3-27b-it",
                secret_alias="GOOGLE_API_KEY",
            )
        )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _label(
    client: TestClient,
    raw_record_id: str,
    title: str,
    *,
    raw_payload: dict | None = None,
) -> dict:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": raw_record_id,
                    "source_name": "emart",
                    "raw_title": title,
                    "raw_price": 1000,
                    "raw_payload": raw_payload or {},
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_existing_keyword_matched_without_new_proposal(client: TestClient) -> None:
    body = _label(client, "existing-tofu", "풀무원 국산두부 300g")
    assert body["keyword_proposals_stored"] == 0

    proposals = client.get("/api/review/proposals").json()["items"]
    keyword_values = [
        proposal
        for proposal in proposals
        if proposal["target_field"] == "keywords" and proposal["proposed_value"] == "두부"
    ]
    assert keyword_values
    assert keyword_values[0]["alternatives"][0]["matched_term"] == "국산두부"


def test_new_keyword_blocks_until_approval_and_persists(client: TestClient) -> None:
    body = _label(client, "new-ssamjang", "고기쌈장 500g")
    assert body["keyword_proposals_stored"] == 1
    proposal_id = body["keyword_proposal_ids"][0]

    eligibility = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert eligibility["eligible"] is False
    assert any("pending DB keyword proposal" in blocker for blocker in eligibility["blockers"])

    detail = client.get(f"/api/review/keyword-proposals/{proposal_id}").json()
    assert detail["proposed_keyword"] == "쌈장"
    assert {record["raw_record_id"] for record in detail["triggering_records"]} == {"new-ssamjang"}
    assert "고기쌈장" in detail["match_terms"]

    approve = client.post(
        f"/api/review/keyword-proposals/{proposal_id}/approve",
        json={
            "reviewer_id": "lucy",
            "proposed_keyword": "쌈장",
            "match_terms": ["고기쌈장", "쌈장"],
            "category_suggestion": "processed.sauce.ssamjang",
        },
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["proposal"]["status"] == "approved"

    catalog = KeywordCatalogAdapter().list_keywords()
    ssamjang = next(keyword for keyword in catalog if keyword.word == "쌈장")
    assert "고기쌈장" in ssamjang.synonyms

    after = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert not any("DB keyword proposal" in blocker for blocker in after["blockers"])
    approved_keyword_fields = [
        proposal
        for proposal in client.get("/api/review/proposals").json()["items"]
        if proposal["target_field"] == "keywords"
        and proposal["proposed_value"] == "쌈장"
        and proposal["status"] == "approved"
    ]
    assert approved_keyword_fields


def test_emart_five_record_keyword_noise_is_grouped_before_review() -> None:
    records = [
        RawCrawlRecord(raw_record_id="emart-kimbap-kit", source_name="emart", raw_title="김밥 키트 1팩", raw_price=9980),
        RawCrawlRecord(raw_record_id="emart-hanwoo-bulgogi", source_name="emart", raw_title="한우 불고기 300g", raw_price=12980),
        RawCrawlRecord(raw_record_id="emart-shrimp", source_name="emart", raw_title="새우 500g", raw_price=15980),
        RawCrawlRecord(raw_record_id="emart-cabbage", source_name="emart", raw_title="양배추 1통", raw_price=2980),
        RawCrawlRecord(raw_record_id="emart-soup-cut-beef", source_name="emart", raw_title="소고기 국거리 300g", raw_price=11980),
    ]
    response_items = [
        {
            "raw_record_id": "emart-kimbap-kit",
            "category_id": "processed.meal.kimbap",
            "keywords": ["김밥", "키트"],
            "aliases": ["키트", "김밥"],
            "confidence": 0.9,
        },
        {
            "raw_record_id": "emart-hanwoo-bulgogi",
            "category_id": "meat.beef.bulgogi",
            "keywords": ["한우", "불고기", "소", "불", "beef"],
            "aliases": ["beef", "불고기"],
            "confidence": 0.9,
        },
        {
            "raw_record_id": "emart-shrimp",
            "category_id": "seafood.shrimp",
            "keywords": ["새우", "shrimp"],
            "aliases": ["shrimp", "새우"],
            "confidence": 0.9,
        },
        {
            "raw_record_id": "emart-cabbage",
            "category_id": "vegetable.cabbage",
            "keywords": ["양배추", "통", "cabbage"],
            "aliases": ["cabbage", "통"],
            "confidence": 0.9,
        },
        {
            "raw_record_id": "emart-soup-cut-beef",
            "category_id": "meat.beef.soup_cut",
            "keywords": ["소고기", "국거리", "beef", "소"],
            "aliases": ["beef"],
            "confidence": 0.9,
        },
    ]

    _matched, proposals = build_keyword_outputs(
        batch_id="emart-five",
        records=records,
        response_items=response_items,
        catalog=[],
    )

    by_keyword = {proposal["proposed_keyword"]: proposal for proposal in proposals}
    assert set(by_keyword) == {"김밥", "한우", "불고기", "소고기", "새우", "양배추", "국거리"}
    assert not {"통", "개", "팩", "키트", "beef", "shrimp", "cabbage", "소", "불"} & set(by_keyword)
    assert by_keyword["양배추"]["match_terms"] == ["양배추", "cabbage"]
    assert by_keyword["새우"]["match_terms"] == ["새우", "shrimp"]
    assert by_keyword["소고기"]["match_terms"] == ["beef", "소고기"]
    assert {
        record["raw_record_id"]
        for record in by_keyword["소고기"]["triggering_records"]
    } == {"emart-hanwoo-bulgogi", "emart-soup-cut-beef"}


def test_approved_cabbage_alias_persists_synonym_and_product_link(
    client: TestClient,
    db_admin_url: str,
) -> None:
    body = _label(
        client,
        "new-cabbage",
        "양배추 1통 cabbage",
        raw_payload={"product_id": 1},
    )
    assert body["keyword_proposals_stored"] == 1
    proposal_id = body["keyword_proposal_ids"][0]

    detail = client.get(f"/api/review/keyword-proposals/{proposal_id}").json()
    assert detail["proposed_keyword"] == "양배추"
    assert detail["match_terms"] == ["양배추", "cabbage"]

    approve = client.post(
        f"/api/review/keyword-proposals/{proposal_id}/approve",
        json={"reviewer_id": "lucy"},
    )
    assert approve.status_code == 200, approve.text
    persisted = approve.json()["persisted_keyword"]
    assert persisted["synonyms"] == ["cabbage"]
    assert persisted["linked_product_ids"] == [1]

    catalog = KeywordCatalogAdapter().list_keywords()
    cabbage = next(keyword for keyword in catalog if keyword.word == "양배추")
    assert cabbage.synonyms == ("cabbage",)

    engine = create_engine(db_admin_url)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM product_keywords "
                "WHERE product_id = 1 AND keyword_id = :keyword_id"
            ),
            {"keyword_id": cabbage.id},
        ).first()
    assert row is not None


def test_rejection_keeps_product_pending_needs_edit(client: TestClient) -> None:
    body = _label(client, "new-ssamjang-reject", "고기쌈장 500g")
    proposal_id = body["keyword_proposal_ids"][0]

    rejected = client.post(
        f"/api/review/keyword-proposals/{proposal_id}/reject",
        json={"reviewer_id": "lucy", "reason": "too broad"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    eligibility = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert eligibility["eligible"] is False
    assert any("rejected DB keyword proposal" in blocker for blocker in eligibility["blockers"])
