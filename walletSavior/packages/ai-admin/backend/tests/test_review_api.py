"""검수 큐 라우트 테스트.

shared `ReviewQueueService`의 submit -> start -> approve/correct/reject 흐름을
HTTP 경계에서 검증한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.prompts import get_db as prompts_get_db
import api.routes.review as review_routes
from api.routes.review import get_db as review_get_db
from core.contracts.ai_pipeline import PipelineStatus, RawCrawlRecord
from core.contracts.control_plane import RawCrawlBatchContract
from storage import Database, KeywordProposalRepository, RawCrawlBatchRepository, create_database


@pytest.fixture()
def db(tmp_path) -> Database:
    database = create_database(f"sqlite:///{(tmp_path / 'review.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


def _proposal(proposal_id: str = "p-1", target_field: str = "name") -> dict:
    return {
        "proposal_id": proposal_id,
        "proposal_type": "normalized_field",
        "target_field": target_field,
        "proposed_value": "Coca-Cola 500ml",
        "status": "ai_proposed",
        "provenance": {
            "raw_record_id": "raw-1",
            "evidence_text": "코카콜라 500ml",
            "worker_role": "normalizer",
        },
        "alternatives": ["Coca Cola 500ml"],
    }


def _proposal_for_record(
    proposal_id: str,
    raw_record_id: str,
    target_field: str,
    proposed_value,
    *,
    proposal_type: str = "normalized_field",
) -> dict:
    proposal = _proposal(proposal_id, target_field)
    proposal["proposal_type"] = proposal_type
    proposal["proposed_value"] = proposed_value
    proposal["provenance"]["raw_record_id"] = raw_record_id
    proposal["provenance"]["evidence_text"] = f"evidence for {raw_record_id}"
    return proposal


def _submit(client: TestClient, proposal_id: str = "p-1") -> None:
    res = client.post("/api/review/proposals", json=_proposal(proposal_id))
    assert res.status_code == 201, res.text


def _seed_raw_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="raw-good",
            source_name="emart",
            raw_title="오리온 오징어 땅콩 98g",
            raw_price=1980,
            source_url="https://emart.example/products/squid-peanut",
            raw_payload={
                "image_url": "https://emart.example/images/squid-peanut.jpg",
                "original_price": 2480,
                "sale_price": 1980,
                "discount_percent": 20,
                "source_url": "https://emart.example/products/squid-peanut",
                "expected_ai": {
                    "canonical_name": "오리온 오징어 땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩"],
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="raw-missing",
            source_name="emart",
            raw_title="서울우유 1L",
            raw_price=2800,
        ),
        RawCrawlRecord(
            raw_record_id="raw-wrong",
            source_name="emart",
            raw_title="국내산 삼겹살 500g",
            raw_price=9900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "국내산 삼겹살 500g",
                    "category_id": "meat.pork",
                    "package_unit": "g",
                    "keywords": ["삼겹살"],
                }
            },
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-review",
                source_name="emart",
                crawler_name="seeded-test",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-review", records)


def _seed_quality_audit_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="qa-good-chilled-pork",
            source_name="emart",
            raw_title="국내산 냉장 삼겹살 500g",
            raw_price=9900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "국내산 냉장 삼겹살 500g",
                    "category_id": "meat.pork",
                    "package_unit": "g",
                    "keywords": ["삼겹살"],
                    "price": 9900,
                    "attributes": {"storage_type": "냉장"},
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-price-wrong",
            source_name="emart",
            raw_title="서울우유 1L",
            raw_price=2800,
            source_url="https://emart.example/products/milk",
            raw_payload={
                "image_url": "https://emart.example/images/milk.jpg",
                "original_price": 3500,
                "sale_price": 2800,
                "discount_percent": 20,
                "source_url": "https://emart.example/products/milk",
                "expected_ai": {
                    "canonical_name": "서울우유 1L",
                    "category_id": "dairy.milk",
                    "package_unit": "L",
                    "keywords": ["서울우유", "우유"],
                    "price": 2800,
                    "storage_type": "냉장",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-snack-seafood-confused",
            source_name="emart",
            raw_title="오리온 오징어땅콩 98g",
            raw_price=1980,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "오리온 오징어땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩", "과자"],
                    "price": 1980,
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-frozen-seafood-missing-storage",
            source_name="emart",
            raw_title="냉동 손질 오징어 500g",
            raw_price=7900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "냉동 손질 오징어 500g",
                    "category_id": "seafood.squid",
                    "package_unit": "g",
                    "keywords": ["오징어"],
                    "price": 7900,
                    "storage_type": "냉동",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-keyword-category-wrong",
            source_name="emart",
            raw_title="제주 감귤 1.5kg",
            raw_price=12900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "제주 감귤 1.5kg",
                    "category_id": "fruit.citrus",
                    "package_unit": "kg",
                    "keywords": ["감귤"],
                    "price": 12900,
                    "attributes": {"storage_type": "fresh"},
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-missing-product",
            source_name="emart",
            raw_title="풀무원 국산콩 두부 300g",
            raw_price=3480,
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-quality-audit",
                source_name="emart",
                crawler_name="seeded-quality-audit",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-quality-audit", records)


def _seed_publish_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="pub-1",
            source_name="emart",
            source_url="https://emart.example/products/pub-1",
            raw_title="오리온 오징어땅콩 98g",
            raw_price=1980,
            raw_payload={
                "source_url": "https://emart.example/products/pub-1",
                "image_url": "https://emart.example/images/pub-1.jpg",
                "original_price": 2480,
                "discount_percent": 20,
                "expected_ai": {
                    "canonical_name": "오리온 오징어땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩"],
                    "price": 1980,
                    "storage_type": "상온",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="pub-2",
            source_name="emart",
            source_url="https://emart.example/products/pub-2",
            raw_title="서울우유 1L",
            raw_price=2800,
            raw_payload={
                "source_url": "https://emart.example/products/pub-2",
                "image_url": "https://emart.example/images/pub-2.jpg",
                "original_price": 3200,
                "discount_percent": 12,
                "expected_ai": {
                    "canonical_name": "서울우유 1L",
                    "category_id": "dairy.milk",
                    "package_unit": "L",
                    "keywords": ["서울우유"],
                    "price": 2800,
                    "storage_type": "냉장",
                }
            },
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-publish",
                source_name="emart",
                crawler_name="seeded-publish",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-publish", records)


def _approve_publish_proposals(client: TestClient, raw_id: str, *, approve_keyword: bool = True) -> None:
    values = [
        ("name", "canonical_name", "오리온 오징어땅콩 98g" if raw_id == "pub-1" else "서울우유 1L", "normalized_field"),
        ("category", "category_id", "snack.nut" if raw_id == "pub-1" else "dairy.milk", "category"),
        ("unit", "package_unit", "g" if raw_id == "pub-1" else "L", "normalized_field"),
        ("price", "sale_price", 1980 if raw_id == "pub-1" else 2800, "normalized_field"),
        ("keyword", "keywords", ["오징어땅콩"] if raw_id == "pub-1" else ["서울우유"], "keyword"),
    ]
    values.append(("storage", "attributes.storage_type", "상온" if raw_id == "pub-1" else "냉장", "attribute_value"))
    for suffix, target, value, proposal_type in values:
        proposal_id = f"{raw_id}-{suffix}"
        res = client.post(
            "/api/review/proposals",
            json=_proposal_for_record(
                proposal_id,
                raw_id,
                target,
                value,
                proposal_type=proposal_type,
            ),
        )
        assert res.status_code == 201, res.text
        if proposal_type != "keyword" or approve_keyword:
            approved = client.post(
                f"/api/review/proposals/{proposal_id}/approve",
                json={"reviewer_id": "lucy"},
            )
            assert approved.status_code == 200, approved.text


def _quality_gate_raw_payload(index: int, name: str, price: int) -> dict:
    return {
        "expected_ai": {
            "canonical_name": name,
            "category_id": "snack.test",
            "package_unit": "개",
            "keywords": [f"테스트 상품 {index}"],
            "price": price,
            "storage_type": "상온",
        },
        "source_url": f"https://emart.example/items/{index}",
        "image_url": f"https://emart.example/images/{index}.jpg",
        "original_price": price + 500,
        "discount_percent": 10,
        "store": "emart",
    }


def _seed_partial_quality_gate_batch(client: TestClient, db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id=f"gate-{idx}",
            source_name="emart",
            source_url=f"https://emart.example/items/{idx}",
            raw_title=f"테스트 상품 {idx}",
            raw_price=1000 + idx,
            raw_payload=_quality_gate_raw_payload(idx, f"테스트 상품 {idx}", 1000 + idx),
        )
        for idx in range(1, 6)
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-quality-gate-partial",
                source_name="emart",
                crawler_name="seeded-quality-gate",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-quality-gate-partial", records)

    approved_values = [
        ("name", "canonical_name", "테스트 상품 1", "normalized_field"),
        ("category", "category_id", "snack.test", "category"),
        ("unit", "package_unit", "개", "normalized_field"),
        ("price", "sale_price", 1001, "normalized_field"),
        ("keyword", "keywords", ["테스트 상품 1"], "keyword"),
        ("storage", "attributes.storage_type", "상온", "attribute_value"),
    ]
    for suffix, target, value, proposal_type in approved_values:
        proposal_id = f"gate-1-{suffix}"
        res = client.post(
            "/api/review/proposals",
            json=_proposal_for_record(
                proposal_id,
                "gate-1",
                target,
                value,
                proposal_type=proposal_type,
            ),
        )
        assert res.status_code == 201, res.text
        approved = client.post(
            f"/api/review/proposals/{proposal_id}/approve",
            json={"reviewer_id": "qa"},
        )
        assert approved.status_code == 200, approved.text

    pending_fields = [
        ("canonical_name", "normalized_field"),
        ("category_id", "category"),
        ("package_unit", "normalized_field"),
        ("sale_price", "normalized_field"),
        ("keywords", "keyword"),
        ("attributes.storage_type", "attribute_value"),
        ("image_url", "normalized_field"),
        ("source_url", "normalized_field"),
        ("discount_percent", "normalized_field"),
    ]
    created = 0
    for raw_idx in range(2, 6):
        limit = 8 if raw_idx in {2, 3} else 9
        for field, proposal_type in pending_fields[:limit]:
            created += 1
            value = [f"테스트{raw_idx}"] if field == "keywords" else (
                1000 + raw_idx if field == "sale_price" else records[raw_idx - 1].raw_payload.get(field, field)
            )
            res = client.post(
                "/api/review/proposals",
                json=_proposal_for_record(
                    f"gate-{raw_idx}-pending-{created}",
                    f"gate-{raw_idx}",
                    field,
                    value,
                    proposal_type=proposal_type,
                ),
            )
            assert res.status_code == 201, res.text
    assert created == 34

    with db.session_scope() as session:
        keyword_repo = KeywordProposalRepository(session)
        for idx in range(7):
            raw_idx = 2 + (idx % 4)
            keyword_repo.save({
                "proposal_id": f"gate-keyword-{idx}",
                "proposed_keyword": f"미해결키워드{idx}",
                "match_terms": [f"테스트{raw_idx}"],
                "category_suggestion": "snack.test",
                "confidence": 0.7,
                "reason": "quality gate regression fixture",
                "triggering_records": [
                    {"raw_record_id": f"gate-{raw_idx}", "raw_title": f"테스트 상품 {raw_idx}"}
                ],
                "source_values": [f"테스트 상품 {raw_idx}"],
                "status": PipelineStatus.AI_PROPOSED.value,
            })


def test_submit_and_start_review(client: TestClient) -> None:
    _submit(client)

    listed = client.get(
        "/api/review/proposals", params={"status": "ai_proposed"}
    ).json()
    assert len(listed["items"]) == 1

    res = client.post("/api/review/proposals/p-1/start")
    assert res.status_code == 200
    assert res.json()["status"] == "human_reviewing"


def test_approve_records_decision(client: TestClient) -> None:
    _submit(client)

    res = client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy", "create_learning_rule": True},
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "approve"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "approved"
    assert len(detail["decisions"]) == 1
    assert detail["decisions"][0]["create_learning_rule"] is True


def test_publish_eligibility_requires_human_approval_and_clear_keywords(client: TestClient, db: Database) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    _approve_publish_proposals(client, "pub-2", approve_keyword=False)

    res = client.get("/api/review/publish-eligibility")
    assert res.status_code == 200, res.text
    rows = {row["raw_record_id"]: row for row in res.json()["items"]}
    assert rows["pub-1"]["eligible"] is True
    assert rows["pub-1"]["status"] == "approved"
    assert rows["pub-2"]["eligible"] is False
    assert any("keyword" in blocker for blocker in rows["pub-2"]["blockers"])


def test_publish_eligibility_marks_partial_batch_not_safe_with_unresolved_counts(
    client: TestClient, db: Database
) -> None:
    _seed_partial_quality_gate_batch(client, db)

    res = client.get(
        "/api/review/publish-eligibility",
        params={"batch_id": "batch-quality-gate-partial"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    summary = body["summary"]
    rows = {row["raw_record_id"]: row for row in body["items"]}

    assert summary["raw_count"] == 5
    assert summary["ai_record_count"] == 5
    assert summary["eligible_count"] == 1
    assert summary["blocked_count"] == 4
    assert summary["held_count"] == 4
    assert summary["field_proposal_count"] == 40
    assert summary["unresolved_field_proposal_count"] == 34
    assert summary["keyword_proposal_count"] == 7
    assert summary["unresolved_keyword_proposal_count"] == 7
    assert summary["batch_status"] == "partial_only"
    assert "배치 전체 발행은 안전하지 않습니다" in summary["quality_verdict"]
    assert rows["gate-1"]["eligible"] is True
    assert all(rows[f"gate-{idx}"]["eligible"] is False for idx in range(2, 6))
    blocker_codes = {blocker["code"] for blocker in summary["blockers"]}
    assert {"unresolved_field_proposals", "unresolved_keyword_proposals", "blocked_rows"} <= blocker_codes


def test_publish_success_marks_row_and_proposals_published(client: TestClient, db: Database, monkeypatch) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 777, "status": "pending", "quality_score": 100}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 1
    assert calls[0]["items"][0]["raw_record_id"] == "pub-1"

    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "published"
    assert rows["pub-1"]["db_ingestion_id"] == "777"
    detail = client.get("/api/review/proposals/pub-1-name").json()
    assert detail["proposal"]["status"] == "published"


def test_emart_cabbage_publish_payload_preserves_offer_metadata(
    client: TestClient, db: Database, monkeypatch
) -> None:
    raw_id = "emart-cabbage-800g"
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "한끼 양배추 800g 통",
        "unit": "800g",
        "category_id": "vegetable.cabbage",
        "category": "채소",
        "storage_type": "냉장",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "original_price": 3480,
        "sale_price": 2784,
        "discount_percent": 20,
        "event_name": "e머니 20% 할인",
        "source_url": "https://emart.example/products/cabbage",
        "valid_from": "2026-04-01T00:00:00",
        "valid_to": "2026-04-07T00:00:00",
    }
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-cabbage",
                source_name="emart",
                crawler_name="seeded-cabbage",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-cabbage",
            [
                RawCrawlRecord(
                    raw_record_id=raw_id,
                    source_name="emart",
                    source_record_key="cabbage",
                    source_url=raw_payload["source_url"],
                    raw_title="한끼 양배추 800g 통",
                    raw_price=2784,
                    raw_payload=raw_payload,
                )
            ],
        )

    proposals = [
        _proposal_for_record("cabbage-name", raw_id, "canonical_name", "한끼 양배추 800g 통"),
        _proposal_for_record("cabbage-cat", raw_id, "category_id", "vegetable.cabbage", proposal_type="category"),
        _proposal_for_record("cabbage-unit", raw_id, "package_unit", "800g"),
        _proposal_for_record("cabbage-price", raw_id, "sale_price", 2784),
        _proposal_for_record("cabbage-kw", raw_id, "keywords", ["양배추"], proposal_type="keyword"),
        _proposal_for_record("cabbage-storage", raw_id, "attributes.storage_type", "냉장", proposal_type="attribute_value"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text
        approved = client.post(
            f"/api/review/proposals/{proposal['proposal_id']}/approve",
            json={"reviewer_id": "lucy"},
        )
        assert approved.status_code == 200, approved.text

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 778, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": [raw_id], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 1
    item = calls[0]["items"][0]
    assert item["name"] == "한끼 양배추 800g 통"
    assert item["image_url"] == raw_payload["image_url"]
    assert item["original_price"] == 3480
    assert item["sale_price"] == 2784
    assert item["discount_percent"] == 20
    assert item["event_name"] == raw_payload["event_name"]
    assert item["source_url"] == raw_payload["source_url"]
    assert item["display_unit"] == "800g"
    assert item["package_quantity"] == 800
    assert item["package_unit"] == "g"
    assert item["price_per_100g"] == 348
    assert item["category_id"] == "vegetable.cabbage"
    assert item["keywords"] == ["양배추"]
    assert item["raw_data"]["raw_payload"]["original_price"] == 3480
    assert item["raw_data"]["display_unit"] == "800g"


def test_emart_publish_payload_keeps_pack_unit_when_raw_unit_is_100g_reference(
    client: TestClient, db: Database, monkeypatch
) -> None:
    raw_id = "emart-hanwoo-bulgogi-300g"
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "[냉장] 한우 불고기1+등급300g",
        "unit": "100g",
        "category_id": "meat.beef.bulgogi",
        "image_url": "https://emart.example/images/beef.jpg",
        "original_price": 19800,
        "sale_price": 14850,
        "discount_percent": 25,
        "source_url": "https://emart.example/products/beef",
    }
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-beef",
                source_name="emart",
                crawler_name="seeded-beef",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-beef",
            [
                RawCrawlRecord(
                    raw_record_id=raw_id,
                    source_name="emart",
                    source_record_key="beef",
                    source_url=raw_payload["source_url"],
                    raw_title=raw_payload["name"],
                    raw_price=14850,
                    raw_payload=raw_payload,
                )
            ],
        )

    proposals = [
        _proposal_for_record("beef-name", raw_id, "canonical_name", "한우 불고기"),
        _proposal_for_record("beef-cat", raw_id, "category_id", "meat.beef.bulgogi", proposal_type="category"),
        _proposal_for_record("beef-unit", raw_id, "package_unit", "g"),
        _proposal_for_record("beef-qty", raw_id, "package_quantity", 300),
        _proposal_for_record("beef-display", raw_id, "display_unit", "300g"),
        _proposal_for_record("beef-price", raw_id, "sale_price", 14850),
        _proposal_for_record("beef-kw", raw_id, "keywords", ["한우", "불고기"], proposal_type="keyword"),
        _proposal_for_record("beef-storage", raw_id, "attributes.storage_type", "chilled", proposal_type="attribute_value"),
    ]
    for proposal in proposals:
        assert client.post("/api/review/proposals", json=proposal).status_code == 201
        approved = client.post(
            f"/api/review/proposals/{proposal['proposal_id']}/approve",
            json={"reviewer_id": "lucy"},
        )
        assert approved.status_code == 200, approved.text

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 779, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": [raw_id], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    item = calls[0]["items"][0]
    assert item["name"] == "한우 불고기"
    assert item["raw_unit"] == "100g"
    assert item["unit"] == "300g"
    assert item["display_unit"] == "300g"
    assert item["package_quantity"] == 300
    assert item["package_unit"] == "g"
    assert item["price_per_100g"] == 4950
    assert item["raw_data"]["raw_payload"]["unit"] == "100g"
    assert item["raw_data"]["display_unit"] == "300g"


def test_publish_partial_failure_keeps_retryable_error(client: TestClient, db: Database, monkeypatch) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    _approve_publish_proposals(client, "pub-2")

    async def fake_submit(payload):
        raw_id = payload["items"][0]["raw_record_id"]
        if raw_id == "pub-2":
            raise RuntimeError("DB-admin validation failed")
        return {"id": 700, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={
            "raw_record_ids": ["pub-1", "pub-2"],
            "reviewer_id": "lucy",
            "confirm_count": 2,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 1
    assert body["failed"] == 1
    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "published"
    assert rows["pub-2"]["status"] == "publish_failed"
    assert rows["pub-2"]["retryable"] is True
    assert "DB-admin validation failed" in rows["pub-2"]["last_error"]


def test_publish_does_not_call_db_when_keyword_or_quality_blocked(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-2", approve_keyword=False)
    called = False

    async def fake_submit(payload):
        nonlocal called
        called = True
        return {"id": 1}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-2"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 0
    assert called is False

    _seed_raw_batch(db)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["raw-missing"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 0
    assert called is False


def test_correct_requires_reason(client: TestClient) -> None:
    _submit(client)

    bad = client.post(
        "/api/review/proposals/p-1/correct",
        json={"reviewer_id": "lucy", "corrected_value": "Coca-Cola", "reason": ""},
    )
    # pydantic 검증으로 422 (min_length=1)
    assert bad.status_code == 422

    ok = client.post(
        "/api/review/proposals/p-1/correct",
        json={
            "reviewer_id": "lucy",
            "corrected_value": "Coca-Cola",
            "reason": "정규화 규칙 보정",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["decision"] == "correct"
    assert body["corrected_value"] == "Coca-Cola"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "approved"


def test_reject_marks_proposal_rejected(client: TestClient) -> None:
    _submit(client)

    res = client.post(
        "/api/review/proposals/p-1/reject",
        json={"reviewer_id": "lucy", "reason": "신뢰도 부족"},
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "reject"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "rejected"
    assert detail["decisions"][0]["create_learning_rule"] is False


def test_double_decision_is_blocked(client: TestClient) -> None:
    _submit(client)
    client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy"},
    )
    again = client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy"},
    )
    assert again.status_code == 400


def test_unknown_proposal_returns_404(client: TestClient) -> None:
    res = client.post(
        "/api/review/proposals/missing/approve",
        json={"reviewer_id": "lucy"},
    )
    assert res.status_code == 404


def test_filter_by_proposal_type(client: TestClient) -> None:
    _submit(client, "p-1")
    _submit(client, "p-2")

    listed = client.get(
        "/api/review/proposals",
        params={"proposal_type": "normalized_field"},
    ).json()
    assert len(listed["items"]) == 2

    listed_other = client.get(
        "/api/review/proposals", params={"proposal_type": "category"}
    ).json()
    assert listed_other["items"] == []


def test_update_and_delete_staged_proposal(client: TestClient) -> None:
    _submit(client)

    updated = client.put(
        "/api/review/proposals/p-1",
        json={
            "target_field": "canonical_name",
            "proposed_value": "제주삼다수 2L",
            "alternatives": ["삼다수 2L"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["target_field"] == "canonical_name"
    assert updated.json()["proposed_value"] == "제주삼다수 2L"

    deleted = client.delete("/api/review/proposals/p-1")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert client.get("/api/review/proposals/p-1").status_code == 404


def test_raw_records_endpoint_lists_records_with_proposals(
    client: TestClient,
    db: Database,
) -> None:
    _seed_raw_batch(db)
    res = client.post(
        "/api/review/proposals",
        json=_proposal_for_record(
            "p-raw-good-name",
            "raw-good",
            "canonical_name",
            "오리온 오징어 땅콩 98g",
        ),
    )
    assert res.status_code == 201, res.text

    listed = client.get(
        "/api/review/raw-records",
        params={"batch_id": "batch-review", "include_proposals": "true"},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 3
    raw_good = next(item for item in items if item["raw_record_id"] == "raw-good")
    assert raw_good["proposals"][0]["proposal_id"] == "p-raw-good-name"


def test_raw_vs_ai_audit_detects_missing_and_misclassified_data(
    client: TestClient,
    db: Database,
) -> None:
    _seed_raw_batch(db)
    proposals = [
        _proposal_for_record("good-name", "raw-good", "canonical_name", "오리온 오징어 땅콩 98g"),
        _proposal_for_record("good-cat", "raw-good", "category_id", "snack.nut", proposal_type="category"),
        _proposal_for_record("good-unit", "raw-good", "package_unit", "g"),
        _proposal_for_record("good-kw", "raw-good", "keywords", "오징어땅콩", proposal_type="keyword"),
        _proposal_for_record("missing-name", "raw-missing", "canonical_name", "서울우유 1L"),
        _proposal_for_record("wrong-name", "raw-wrong", "canonical_name", "바나나 1송이"),
        _proposal_for_record("wrong-cat", "raw-wrong", "category_id", "fruit.banana", proposal_type="category"),
        _proposal_for_record("wrong-unit", "raw-wrong", "package_unit", "kg"),
        _proposal_for_record("wrong-kw", "raw-wrong", "keywords", "바나나", proposal_type="keyword"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text

    audit = client.get("/api/review/audit", params={"batch_id": "batch-review"})
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["raw_record_count"] == 3
    assert body["covered_record_count"] == 3
    assert body["status"] == "warning"

    issue_codes = {(issue["raw_record_id"], issue["code"]) for issue in body["issues"]}
    assert ("raw-missing", "missing_category_id_signal") in issue_codes
    assert ("raw-missing", "missing_unit_signal") in issue_codes
    assert ("raw-missing", "missing_keywords_signal") in issue_codes
    assert ("raw-wrong", "mismatched_category_id") in issue_codes
    assert ("raw-wrong", "mismatched_package_unit") in issue_codes
    assert ("raw-wrong", "name_signal_mismatch") in issue_codes


def test_raw_vs_ai_audit_flags_seeded_korean_data_that_exists_but_is_not_serviceable(
    client: TestClient,
    db: Database,
) -> None:
    _seed_quality_audit_batch(db)
    proposals = [
        _proposal_for_record("qa-good-name", "qa-good-chilled-pork", "canonical_name", "국내산 냉장 삼겹살 500g"),
        _proposal_for_record("qa-good-cat", "qa-good-chilled-pork", "category_id", "meat.pork", proposal_type="category"),
        _proposal_for_record("qa-good-unit", "qa-good-chilled-pork", "package_unit", "g"),
        _proposal_for_record("qa-good-kw", "qa-good-chilled-pork", "keywords", "삼겹살", proposal_type="keyword"),
        _proposal_for_record("qa-good-price", "qa-good-chilled-pork", "price", 9900),
        _proposal_for_record("qa-good-storage", "qa-good-chilled-pork", "attributes.storage_type", "냉장", proposal_type="attribute_value"),
        _proposal_for_record("qa-price-name", "qa-price-wrong", "canonical_name", "서울우유 1L"),
        _proposal_for_record("qa-price-cat", "qa-price-wrong", "category_id", "dairy.milk", proposal_type="category"),
        _proposal_for_record("qa-price-unit", "qa-price-wrong", "package_unit", "L"),
        _proposal_for_record("qa-price-kw", "qa-price-wrong", "keywords", ["서울우유", "우유"], proposal_type="keyword"),
        _proposal_for_record("qa-price-price", "qa-price-wrong", "price", "3,800원"),
        _proposal_for_record("qa-snack-name", "qa-snack-seafood-confused", "canonical_name", "오리온 오징어땅콩 98g"),
        _proposal_for_record("qa-snack-cat", "qa-snack-seafood-confused", "category_id", "seafood.squid", proposal_type="category"),
        _proposal_for_record("qa-snack-unit", "qa-snack-seafood-confused", "package_unit", "g"),
        _proposal_for_record("qa-snack-kw", "qa-snack-seafood-confused", "keywords", "오징어", proposal_type="keyword"),
        _proposal_for_record("qa-snack-price", "qa-snack-seafood-confused", "price", 1980),
        _proposal_for_record("qa-seafood-name", "qa-frozen-seafood-missing-storage", "canonical_name", "냉동 손질 오징어 500g"),
        _proposal_for_record("qa-seafood-cat", "qa-frozen-seafood-missing-storage", "category_id", "seafood.squid", proposal_type="category"),
        _proposal_for_record("qa-seafood-unit", "qa-frozen-seafood-missing-storage", "package_unit", "g"),
        _proposal_for_record("qa-seafood-kw", "qa-frozen-seafood-missing-storage", "keywords", "오징어", proposal_type="keyword"),
        _proposal_for_record("qa-seafood-price", "qa-frozen-seafood-missing-storage", "price", 7900),
        _proposal_for_record("qa-citrus-name", "qa-keyword-category-wrong", "canonical_name", "제주 감귤 1.5kg"),
        _proposal_for_record("qa-citrus-cat", "qa-keyword-category-wrong", "category_id", "fruit.apple", proposal_type="category"),
        _proposal_for_record("qa-citrus-unit", "qa-keyword-category-wrong", "package_unit", "kg"),
        _proposal_for_record("qa-citrus-kw", "qa-keyword-category-wrong", "keywords", "사과", proposal_type="keyword"),
        _proposal_for_record("qa-citrus-price", "qa-keyword-category-wrong", "price", 12900),
        _proposal_for_record("qa-citrus-storage", "qa-keyword-category-wrong", "attributes.storage_type", "ambient", proposal_type="attribute_value"),
        _proposal_for_record("qa-orphan-name", "qa-not-in-raw", "canonical_name", "없는 상품"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text

    audit = client.get("/api/review/audit", params={"batch_id": "batch-quality-audit"})
    assert audit.status_code == 200, audit.text
    body = audit.json()

    assert body["raw_record_count"] == 6
    assert body["covered_record_count"] == 5
    assert body["missing_record_count"] == 1
    assert body["status"] == "warning"

    issue_codes = {(issue["raw_record_id"], issue["code"]) for issue in body["issues"]}
    assert ("qa-missing-product", "missing_all_proposals") in issue_codes
    assert ("qa-not-in-raw", "orphan_ai_proposals") in issue_codes
    assert ("qa-price-wrong", "price_mismatch_raw") in issue_codes
    assert ("qa-price-wrong", "mismatched_price") in issue_codes
    assert ("qa-price-wrong", "missing_storage_attribute") in issue_codes
    assert ("qa-snack-seafood-confused", "mismatched_category_id") in issue_codes
    assert ("qa-snack-seafood-confused", "mismatched_keywords") in issue_codes
    assert ("qa-snack-seafood-confused", "snack_seafood_confusion") in issue_codes
    assert ("qa-frozen-seafood-missing-storage", "missing_storage_attribute") in issue_codes
    assert ("qa-frozen-seafood-missing-storage", "mismatched_storage_attribute") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_category_id") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_keywords") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_storage_attribute") in issue_codes
    assert not any(issue[0] == "qa-good-chilled-pork" for issue in issue_codes)
