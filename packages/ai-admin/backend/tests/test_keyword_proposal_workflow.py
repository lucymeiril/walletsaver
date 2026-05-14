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
from services.keyword_catalog import CatalogKeyword, KeywordCatalogAdapter, build_keyword_outputs, match_existing_keyword
from storage import (
    Database,
    LearnedKnowledgeRepository,
    ProviderConfigRepository,
    ReviewDecisionRepository,
    create_database,
)


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
                is_crunchball = "크런치볼" in title
                if is_existing:
                    category_id = "processed.tofu.firm"
                    keywords = ["국산두부"]
                    aliases = ["행사두부"]
                elif is_cabbage:
                    category_id = "vegetable.cabbage"
                    keywords = ["양배추", "통", "cabbage"]
                    aliases = ["cabbage", "통"]
                elif is_crunchball:
                    category_id = "ai.generated.crunchball"
                    keywords = ["크런치볼"]
                    aliases = ["말차크런치볼", "리뉴얼크런치볼"]
                else:
                    category_id = "processed.sauce.ssamjang"
                    keywords = ["쌈장"]
                    aliases = ["고기쌈장", "행사쌈장"]
                items.append(
                    {
                        "raw_record_id": record_id,
                        "canonical_name": title.strip(),
                        "brand": "테스트",
                        "category_id": category_id,
                        "keywords": keywords,
                        "aliases": aliases,
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
                default_model="gemma-4-26b-a4b-it",
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
    assert eligibility["keyword_proposals"][0]["status"] == "ai_proposed"
    assert any(flag["code"] == "db_keyword_proposal_unresolved" for flag in eligibility["post_publish_audit_flags"])

    detail = client.get(f"/api/review/keyword-proposals/{proposal_id}").json()
    assert detail["proposed_keyword"] == "쌈장"
    assert {record["raw_record_id"] for record in detail["triggering_records"]} == {"new-ssamjang"}
    assert "고기쌈장" in detail["match_terms"]
    triggering = detail["triggering_records"][0]
    assert triggering["raw_record_id"] == "new-ssamjang"
    assert triggering["raw_title"] == "고기쌈장 500g"
    assert triggering["raw_price"] == 1000
    assert triggering["raw_payload"] == {}

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


def test_second_batch_reuses_approved_keyword_alias_knowledge(
    client: TestClient,
    control_db: Database,
) -> None:
    first = _label(client, "emart-ssamjang-first", "고기쌈장 500g")
    assert first["keyword_proposals_stored"] == 1
    proposal_id = first["keyword_proposal_ids"][0]

    approve = client.post(
        f"/api/review/keyword-proposals/{proposal_id}/approve",
        json={
            "reviewer_id": "lucy",
            "proposed_keyword": "쌈장",
            "match_terms": ["고기쌈장", "행사쌈장", "쌈장"],
            "category_suggestion": "processed.sauce.ssamjang",
        },
    )
    assert approve.status_code == 200, approve.text

    second = _label(client, "emart-ssamjang-second", "행사 고기쌈장 1kg")
    assert second["keyword_proposals_stored"] == 0

    with control_db.session_scope() as session:
        decisions = ReviewDecisionRepository(session).list_for_proposal(proposal_id)
        learned = LearnedKnowledgeRepository(session).list(active_only=True)
    assert any(decision.decision.value == "approve" for decision in decisions)
    approved_patterns = {
        item.pattern
        for item in learned
        if item.knowledge_type == "keyword_alias_approved"
    }
    assert {"쌈장", "고기쌈장", "행사쌈장"}.issubset(approved_patterns)


def test_second_batch_reuses_rejected_keyword_knowledge(
    client: TestClient,
    control_db: Database,
) -> None:
    first = _label(client, "emart-noise-first", "고기쌈장 500g")
    proposal_id = first["keyword_proposal_ids"][0]

    rejected = client.post(
        f"/api/review/keyword-proposals/{proposal_id}/reject",
        json={"reviewer_id": "lucy", "reason": "marketing/source phrase, not a canonical keyword"},
    )
    assert rejected.status_code == 200, rejected.text

    second = _label(client, "emart-noise-second", "행사 고기쌈장 1kg")
    assert second["keyword_proposals_stored"] == 0

    with control_db.session_scope() as session:
        learned = LearnedKnowledgeRepository(session).list(active_only=True)
    rejected_patterns = {
        item.pattern
        for item in learned
        if item.knowledge_type == "keyword_rejected"
    }
    assert {"쌈장", "고기쌈장", "행사쌈장"}.issubset(rejected_patterns)


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


def test_keyword_outputs_keep_product_specific_kit_terms_but_drop_generic_aliases() -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="emart-ham-kimbap-kit",
            source_name="emart",
            raw_title="한돈으로 만든 햄꼬마김밥키트157g",
            raw_price=6980,
        )
    ]
    response_items = [
        {
            "raw_record_id": "emart-ham-kimbap-kit",
            "category_id": "prepared_food.meal_kit.kimbap",
            "keywords": ["키트", "세트", "팩", "햄꼬마김밥키트", "꼬마김밥키트"],
            "aliases": ["키트", "햄꼬마김밥키트"],
            "confidence": 0.86,
        }
    ]

    _matched, proposals = build_keyword_outputs(
        batch_id="specific-kit-keywords",
        records=records,
        response_items=response_items,
        catalog=[],
    )

    by_keyword = {proposal["proposed_keyword"]: proposal for proposal in proposals}
    assert set(by_keyword) == {"햄꼬마김밥키트", "꼬마김밥키트"}
    assert not {"키트", "세트", "팩"} & set(by_keyword)
    assert by_keyword["햄꼬마김밥키트"]["match_terms"] == ["햄꼬마김밥키트"]


def test_keyword_outputs_drop_standalone_ham_for_non_prepared_snack_context() -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="emart-ham-flavor-chip",
            source_name="emart",
            raw_title="햄맛 감자칩 120g",
            raw_price=1980,
        )
    ]
    response_items = [
        {
            "raw_record_id": "emart-ham-flavor-chip",
            "category_id": "snack.chip",
            "keywords": ["햄", "햄맛감자칩"],
            "aliases": ["햄"],
            "confidence": 0.87,
        }
    ]

    _matched, proposals = build_keyword_outputs(
        batch_id="ham-flavor-chip-keywords",
        records=records,
        response_items=response_items,
        catalog=[],
    )

    by_keyword = {proposal["proposed_keyword"]: proposal for proposal in proposals}
    assert "햄" not in by_keyword
    assert set(by_keyword) == {"햄맛감자칩"}


def test_keyword_catalog_substring_is_similar_not_exact_reuse() -> None:
    catalog = [CatalogKeyword(id=1, word="새우", synonyms=(), category_id="seafood.shrimp")]

    existing, similar = match_existing_keyword("새우깡", catalog)

    assert existing is None
    assert [keyword.word for keyword in similar] == ["새우"]


def test_build_keyword_outputs_does_not_count_new_compound_as_exact_catalog() -> None:
    records = [
        RawCrawlRecord(raw_record_id="snack", source_name="emart", raw_title="오리온 새우깡 90g", raw_price=1980)
    ]
    response_items = [
        {
            "raw_record_id": "snack",
            "category_id": "snack.chip",
            "keywords": ["새우깡"],
            "aliases": [],
            "confidence": 0.91,
        }
    ]
    catalog = [CatalogKeyword(id=1, word="새우", synonyms=(), category_id="seafood.shrimp")]

    matched, proposals = build_keyword_outputs(
        batch_id="compound-holdout",
        records=records,
        response_items=response_items,
        catalog=catalog,
    )

    assert matched == {}
    assert proposals[0]["proposed_keyword"] == "새우깡"
    assert proposals[0]["evidence_class"] == "new_keyword_candidate"
    assert proposals[0]["trust_label"] == "human_review_required"
    assert proposals[0]["similar_existing"] == [{"id": 1, "word": "새우", "category_id": "seafood.shrimp"}]


def test_unknown_and_package_renamed_products_create_reviewable_keyword_proposals() -> None:
    records = [
        RawCrawlRecord(raw_record_id="new-cracker", source_name="emart", raw_title="바다친구 새우크래커 90g", raw_price=1980),
        RawCrawlRecord(raw_record_id="renamed-nuts", source_name="emart", raw_title="라라 너츠믹스 리뉴얼 20g 10입", raw_price=9980),
    ]
    response_items = [
        {
            "raw_record_id": "new-cracker",
            "category_id": "snack.chip",
            "keywords": ["새우크래커"],
            "aliases": ["바다친구새우크래커"],
            "confidence": 0.89,
        },
        {
            "raw_record_id": "renamed-nuts",
            "category_id": "snack.nut",
            "keywords": ["너츠믹스"],
            "aliases": ["라라너츠믹스", "리뉴얼너츠믹스"],
            "confidence": 0.87,
        },
    ]
    catalog = [
        CatalogKeyword(id=1, word="새우", synonyms=(), category_id="seafood.shrimp"),
        CatalogKeyword(id=2, word="견과", synonyms=("하루견과",), category_id="snack.nut"),
    ]

    matched, proposals = build_keyword_outputs(
        batch_id="unknown-renamed-holdout",
        records=records,
        response_items=response_items,
        catalog=catalog,
    )

    assert matched == {}
    by_keyword = {proposal["proposed_keyword"]: proposal for proposal in proposals}
    assert {"새우크래커", "바다친구새우크래커", "너츠믹스", "라라너츠믹스", "리뉴얼너츠믹스"} == set(by_keyword)
    assert by_keyword["새우크래커"]["similar_existing"] == [
        {"id": 1, "word": "새우", "category_id": "seafood.shrimp"}
    ]
    for keyword in ("새우크래커", "너츠믹스"):
        proposal = by_keyword[keyword]
        assert proposal["status"] == "ai_proposed"
        assert proposal["evidence_class"] == "new_keyword_candidate"
        assert proposal["trust_label"] == "human_review_required"
        assert proposal["triggering_records"][0]["raw_title"] in {record.raw_title for record in records}


def test_ambiguous_existing_keyword_candidates_need_human_merge_decision() -> None:
    records = [
        RawCrawlRecord(raw_record_id="ambiguous-protein", source_name="emart", raw_title="초코 프로틴바 50g", raw_price=2500)
    ]
    response_items = [
        {
            "raw_record_id": "ambiguous-protein",
            "category_id": "snack.energy_bar",
            "keywords": ["프로틴바"],
            "aliases": [],
            "confidence": 0.92,
        }
    ]
    catalog = [
        CatalogKeyword(id=10, word="프로틴바", synonyms=(), category_id="health.protein"),
        CatalogKeyword(id=11, word="프로틴바", synonyms=(), category_id="snack.energy_bar"),
    ]

    matched, proposals = build_keyword_outputs(
        batch_id="ambiguous-category-candidates",
        records=records,
        response_items=response_items,
        catalog=catalog,
    )

    assert matched == {}
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["proposed_keyword"] == "프로틴바"
    assert "ambiguous" in proposal["reason"]
    assert {item["category_id"] for item in proposal["similar_existing"]} == {
        "health.protein",
        "snack.energy_bar",
    }


def test_new_keyword_proposal_triggering_records_keep_full_raw_fields() -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="cold-start-dragonfruit",
            source_name="emart",
            source_record_key="sku-dragonfruit",
            source_url="https://emart.example/dragonfruit",
            raw_title="레드 용과 1개",
            raw_price=4980,
            raw_payload={
                "store": "이마트",
                "image_url": "https://emart.example/dragonfruit.jpg",
                "original_price": 5980,
            },
        )
    ]
    response_items = [
        {
            "raw_record_id": "cold-start-dragonfruit",
            "category_id": "produce.fruit",
            "keywords": ["용과"],
            "aliases": [],
            "confidence": 0.88,
        }
    ]

    _matched, proposals = build_keyword_outputs(
        batch_id="empty-keyword-db",
        records=records,
        response_items=response_items,
        catalog=[],
    )

    assert proposals[0]["proposed_keyword"] == "용과"
    assert proposals[0]["status"] == "ai_proposed"
    triggering = proposals[0]["triggering_records"][0]
    assert triggering["raw_record_id"] == "cold-start-dragonfruit"
    assert triggering["source_record_key"] == "sku-dragonfruit"
    assert triggering["source_url"] == "https://emart.example/dragonfruit"
    assert triggering["raw_title"] == "레드 용과 1개"
    assert triggering["raw_price"] == 4980
    assert triggering["raw_payload"]["image_url"].endswith("dragonfruit.jpg")


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
    assert eligibility["keyword_proposals"][0]["status"] == "rejected"
    assert any(flag["code"] == "db_keyword_proposal_unresolved" for flag in eligibility["post_publish_audit_flags"])
