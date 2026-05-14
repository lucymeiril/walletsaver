"""Deterministic AI-admin → DB-admin normalized read-model contract harness."""
from __future__ import annotations

import copy
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent.parent
AI_BACKEND = ROOT / "packages" / "ai-admin" / "backend"
DB_BACKEND = ROOT / "packages" / "db-admin" / "backend"
SHARED = ROOT / "packages" / "shared"

for path in (str(SHARED), str(DB_BACKEND)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from api.routes.ingestion import _insert_items
from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from services.normalized_mart3 import publish_mart3_rows
from services.normalized_price_read import get_normalized_price_comparison
from storage.models import (
    Base,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
)


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
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _proposal(
    raw_id: str,
    target: str,
    value: Any,
    *,
    proposal_type: ProposalType = ProposalType.NORMALIZED_FIELD,
) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target}",
        proposal_type=proposal_type,
        target_field=target,
        proposed_value=value,
        status=PipelineStatus.APPROVED,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="integration-stub",
            evidence_text=f"integration evidence for {target}",
            worker_role=AIWorkerRole.NORMALIZER,
            reviewed_by="integration-test",
            reviewed_at=datetime(2026, 4, 6, 9, 0, 0),
        ),
    )


def _ai_reviewed_payload_item() -> dict[str, Any]:
    record = RawCrawlRecord(
        raw_record_id="ai-emart-tofu-300g",
        source_name="emart",
        source_record_key="emart-tofu-300",
        source_url="https://emart.example/source-tofu",
        raw_title="원천명 국산콩 두부 300g",
        raw_price=1980,
        crawled_at=datetime(2026, 4, 6, 9, 0, 0),
        raw_payload={
            "name": "원천명 국산콩 두부 300g",
            "source": "emart",
            "store": "이마트",
            "sale_price": 1980,
            "original_price": 2300,
            "discount_percent": 13,
            "unit": "300g",
            "source_url": "https://emart.example/source-tofu",
            "image_url": "https://emart.example/source-tofu.jpg",
            "promotion_type": "final_price",
            "event_name": "source weekly event",
            "valid_from": "2026-04-06T00:00:00",
            "valid_to": "2026-04-12T23:59:59",
        },
    )
    proposals = [
        _proposal(record.raw_record_id, "canonical_name", "풀무원 국산콩 두부"),
        _proposal(record.raw_record_id, "category_id", "processed.tofu", proposal_type=ProposalType.CATEGORY),
        _proposal(record.raw_record_id, "keywords", ["두부"], proposal_type=ProposalType.KEYWORD),
        _proposal(record.raw_record_id, "brand", "풀무원"),
        _proposal(record.raw_record_id, "sale_price", 777),
        _proposal(record.raw_record_id, "current_price", 777),
        _proposal(record.raw_record_id, "original_price", 9999),
        _proposal(record.raw_record_id, "source_url", "https://ai.example/wrong"),
        _proposal(record.raw_record_id, "image_url", "https://ai.example/wrong.jpg"),
        _proposal(record.raw_record_id, "event_name", "ai event"),
        _proposal(record.raw_record_id, "valid_from", "2030-01-01T00:00:00"),
        _proposal(record.raw_record_id, "valid_to", "2030-01-31T23:59:59"),
    ]
    item = AI_REVIEW_PUBLISH.db_item_from_review(record, proposals, {})
    payload = AI_DB_ADMIN_ADAPTER.build_db_admin_ingestion_payload(
        {
            "raw_record_id": record.raw_record_id,
            "batch_id": "batch-normalized-contract",
            "source_name": record.source_name,
            "proposal_ids": [proposal.proposal_id for proposal in proposals],
            "human_decision_ids": ["decision-normalized-contract"],
            "db_handoff_mode": "ai_safe_final_approve",
            "publication_kind": item["publication_kind"],
            "item": item,
        }
    )
    published_item = payload["items"][0]
    published_item["week_start"] = "2026-04-06T00:00:00"
    published_item["week_end"] = "2026-04-12T00:00:00"
    return published_item


def _row_from_item(item: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    normalized = item["raw_data"]["normalized"]
    row = {
        "raw_record_id": overrides.pop("raw_record_id", item["raw_record_id"]),
        "source": overrides.pop("source", item["source"]),
        "source_name": overrides.pop("source_name", item["source"]),
        "source_record_key": overrides.pop("source_record_key", item["source_record_key"]),
        "source_title": overrides.pop("source_title", item["source_title"]),
        "canonical_name": overrides.pop("canonical_name", item["name"]),
        "category_id": overrides.pop("category_id", item["category_id"]),
        "category_name": overrides.pop("category_name", item["category"]),
        "image_url": overrides.pop("image_url", item["image_url"]),
        "source_url": overrides.pop("source_url", item["source_url"]),
        "package_quantity": overrides.pop("package_quantity", item["package_quantity"]),
        "package_unit": overrides.pop("package_unit", item["package_unit"]),
        "display_unit": overrides.pop("display_unit", item["display_unit"]),
        "unit": overrides.pop("unit", item["unit"]),
        "price": overrides.pop("price", item["price"]),
        "current_price": overrides.pop("current_price", item["current_price"]),
        "original_price": overrides.pop("original_price", item["original_price"]),
        "discount_rate": overrides.pop("discount_rate", item["discount_percent"]),
        "price_state": overrides.pop("price_state", item["price_state"]),
        "promotion_type": overrides.pop("promotion_type", item["promotion_type"]),
        "event_name": overrides.pop("event_name", item["event_name"]),
        "valid_from": overrides.pop("valid_from", item["valid_from"]),
        "valid_to": overrides.pop("valid_to", item["valid_to"]),
        "week_start": overrides.pop("week_start", "2026-04-06T00:00:00"),
        "week_end": overrides.pop("week_end", "2026-04-12T00:00:00"),
        "raw_evidence": overrides.pop("raw_evidence", normalized["offer_event"]["raw_evidence"]),
        "audit_provenance": overrides.pop("audit_provenance", normalized["offer_event"]["audit_provenance"]),
        "keywords": overrides.pop("keywords", item["keywords"]),
        "attributes": overrides.pop("attributes", item.get("attributes", {})),
    }
    row.update(overrides)
    return row


def _flatten_events(model: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (listing, event)
        for product in model["products"]
        for variant in product["variants"]
        for listing in variant["source_listings"]
        for event in listing["offer_events"]
    ]


def test_ai_admin_db_admin_normalized_contract_persists_and_reads_comparable_prices():
    item = _ai_reviewed_payload_item()
    normalized = item["raw_data"]["normalized"]

    assert normalized["contract_version"] == "normalized-mart3-v1"
    assert item["raw_data"]["normalized_metadata"] == normalized
    assert item["raw_data"]["raw_record"]["raw_record_id"] == "ai-emart-tofu-300g"
    assert normalized["canonical_product"]["canonical_name"] == "풀무원 국산콩 두부"
    assert normalized["source_listing"]["source_url"] == "https://emart.example/source-tofu"
    assert normalized["source_listing"]["image_url"] == "https://emart.example/source-tofu.jpg"
    assert normalized["offer_event"]["price"] == 1980
    assert normalized["offer_event"]["original_price"] == 2300
    assert normalized["offer_event"]["valid_from"] == "2026-04-06T00:00:00"
    assert normalized["source_owned_fields"]["price"] == 1980
    ignored = normalized["offer_event"]["audit_provenance"]["ignored_source_owned_ai_fields"]
    assert ignored["sale_price"] == 777
    assert ignored["source_url"] == "https://ai.example/wrong"
    assert ignored["image_url"] == "https://ai.example/wrong.jpg"

    Session = _session_factory()
    with Session.begin() as session:
        http_serialized_item = json.loads(json.dumps(copy.deepcopy(item), ensure_ascii=False, default=str))
        saved = _insert_items(session, [http_serialized_item], "DiscountItem")
        publish_mart3_rows(
            session,
            [
                _row_from_item(
                    item,
                    raw_record_id="lotte-tofu-300g",
                    source="lottemart",
                    source_name="lottemart",
                    source_record_key="lotte-tofu-300",
                    source_url="https://lotte.example/tofu",
                    image_url="https://lotte.example/tofu.jpg",
                    price=1780,
                    current_price=1780,
                    original_price=None,
                    discount_rate=None,
                    promotion_type="final_price",
                    event_name="상시가",
                ),
                _row_from_item(
                    item,
                    raw_record_id="homeplus-tofu-hidden",
                    source="homeplus",
                    source_name="homeplus",
                    source_record_key="homeplus-tofu-300",
                    source_url="https://homeplus.example/tofu",
                    image_url="https://homeplus.example/tofu.jpg",
                    price=None,
                    current_price=None,
                    original_price=None,
                    discount_rate=None,
                    price_state="price_hidden",
                    promotion_type="unknown",
                    event_name="앱에서 가격 확인",
                ),
                _row_from_item(
                    item,
                    raw_record_id="card-tofu-conditional",
                    source="cardmart",
                    source_name="cardmart",
                    source_record_key="card-tofu-300",
                    source_url="https://card.example/tofu",
                    image_url="https://card.example/tofu.jpg",
                    price=None,
                    current_price=None,
                    original_price=None,
                    discount_rate=0.2,
                    price_state="discount_rate_only",
                    promotion_type="checkout_discount",
                    event_name="카드 20% 할인",
                ),
                _row_from_item(
                    item,
                    raw_record_id="unknown-tofu-price",
                    source="unknownmart",
                    source_name="unknownmart",
                    source_record_key="unknown-tofu-300",
                    source_url="https://unknown.example/tofu",
                    image_url="https://unknown.example/tofu.jpg",
                    price=None,
                    current_price=None,
                    discount_rate=None,
                    price_state="original_price_only",
                    promotion_type="unknown",
                    original_price=3000,
                    event_name="가격 확인 필요",
                ),
            ],
        )

    assert saved == 1
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct)) == 1
        assert session.scalar(select(func.count()).select_from(NormalizedProductVariant)) == 1
        assert session.scalar(select(func.count()).select_from(NormalizedSourceListing)) == 5
        assert session.scalar(select(func.count()).select_from(NormalizedOfferEvent)) == 5
        assert session.scalar(select(func.count()).select_from(NormalizedWeekBucket)) == 1
        assert session.scalar(select(func.count()).select_from(NormalizedOfferWeekLink)) == 5

        model = get_normalized_price_comparison(session, category_id=item["category_id"])

    assert len(model["products"]) == 1
    product = model["products"][0]
    assert product["canonical_name"] == "풀무원 국산콩 두부"
    listings = product["variants"][0]["source_listings"]
    assert [listing["source_name"] for listing in listings] == [
        "lottemart",
        "emart",
        "cardmart",
        "homeplus",
        "unknownmart",
    ]
    assert [listing["best_comparable_price"] for listing in listings] == [
        1780,
        1980,
        None,
        None,
        None,
    ]

    events_by_listing = {
        listing["source_name"]: event for listing, event in _flatten_events(model)
    }
    by_state = {event["price_state"]: event for event in events_by_listing.values()}
    assert by_state["price_hidden"]["display_state"] == "hidden"
    assert by_state["price_hidden"]["comparable_price"] is None
    assert by_state["price_hidden"]["is_default_sortable"] is False
    assert by_state["discount_rate_only"]["display_state"] == "rate_only"
    assert by_state["discount_rate_only"]["discount_rate"] == 0.2
    assert by_state["discount_rate_only"]["comparable_price_available"] is False
    assert events_by_listing["unknownmart"]["price_state"] == "original_price_only"
    assert events_by_listing["unknownmart"]["promotion_type"] == "unknown"
    assert events_by_listing["unknownmart"]["display_state"] == "non_comparable"
    assert events_by_listing["unknownmart"]["comparable_price"] is None
