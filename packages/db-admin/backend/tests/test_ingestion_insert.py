import os
import sys
import json
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from api.routes.ingestion import (
    IngestionRowUpdateRequest,
    PublishedRowRollbackRequest,
    PublishedRowReReviewRequest,
    ReviewRequest,
    _calculate_quality,
    _find_problem_items,
    _insert_items,
    _retryable_lock_http_error,
    _with_sqlite_lock_retry,
    ai_safe_final_approve,
    db_review,
    remove_ingestion_item,
    queue_published_ingestion_item_for_re_review,
    rollback_published_ingestion_item,
    update_ingestion_item,
)
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
import api.routes.ingestion as ingestion_routes
from services.catalog_seed import seed_catalog_taxonomy
from storage.models import (
    Base,
    AuditLog,
    Category,
    DiscountHistory,
    HotdealPrice,
    IngestionStatus,
    Keyword,
    PendingCategorization,
    PendingIngestion,
    Product,
    ProductKeyword,
)


def test_sqlite_lock_retryable_error_payload_is_explicit():
    exc = OperationalError("database is locked", None, None)
    http_exc = _retryable_lock_http_error("bulk_approve_chunk", exc, {"ids": [1, 2]})

    assert isinstance(http_exc, HTTPException)
    assert http_exc.status_code == 503
    assert http_exc.detail["retryable"] is True
    assert http_exc.detail["operation"] == "bulk_approve_chunk"
    assert http_exc.detail["context"]["ids"] == [1, 2]


def test_sqlite_lock_retry_context_does_not_hide_final_lock(monkeypatch):
    monkeypatch.setattr(ingestion_routes.time, "sleep", lambda _seconds: None)
    attempts = 0

    def always_locked():
        nonlocal attempts
        attempts += 1
        raise OperationalError("database is locked", None, None)

    try:
        _with_sqlite_lock_retry(
            always_locked,
            operation_name="bulk_approve_chunk",
            context={"ids": [1]},
        )
    except OperationalError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected OperationalError")

    assert attempts == 7


def test_hotdeal_insert_keeps_valid_rows_when_one_price_is_missing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "title": "저장되는 알구몬 핫딜 19,900원",
                    "url": "https://www.algumon.com/l/d/ok",
                    "source_community": "알구몬",
                    "price": 19900,
                },
                {
                    "title": "가격 없는 알구몬 핫딜",
                    "url": "https://www.algumon.com/l/d/no-price",
                    "source_community": "알구몬",
                    "price": None,
                },
            ],
            "HotdealPost",
        )

    with Session() as session:
        rows = session.execute(select(HotdealPrice)).scalars().all()

    assert saved == 1
    assert len(rows) == 1
    assert rows[0].title == "저장되는 알구몬 핫딜 19,900원"
    assert rows[0].price == 19900
    assert rows[0].source == "algumon"
    with Session() as session:
        product = session.get(Product, rows[0].product_id)
        assert product.source_type == "algumon"


def test_emart_discount_insert_preserves_package_and_100g_price_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "name": "[냉장] 한우 불고기1+등급300g",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 14850,
                    "original_price": 19800,
                    "unit": "100g",
                },
                {
                    "name": "[냉동][베트남] 흰다리 새우살 (200g)",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 4488,
                    "unit": "100g",
                },
            ],
            "DiscountItem",
        )

    with Session() as session:
        rows = session.execute(select(DiscountHistory).order_by(DiscountHistory.price.desc())).scalars().all()

    assert saved == 2
    beef = rows[0]
    assert beef.price == 14850
    assert beef.raw_data["pack_price"] == 14850
    assert beef.raw_data["unit"] == "100g"
    assert beef.raw_data["display_unit"] == "300g"
    assert beef.raw_data["package_quantity"] == 300
    assert beef.raw_data["package_unit"] == "g"
    assert beef.raw_data["price_per_100g"] == 4950
    assert beef.raw_data["attributes"]["storage_type"] == "chilled"
    shrimp = rows[1]
    assert shrimp.raw_data["display_unit"] == "200g"
    assert shrimp.raw_data["price_per_100g"] == 2244
    assert shrimp.raw_data["attributes"]["origin"] == "vietnam"


def test_ai_reviewed_emart_cabbage_publish_preserves_offer_fields_and_links():
    Session = _make_session_factory()
    item = {
        "name": "한끼 양배추 800g 통",
        "sale_price": 2784,
        "current_price": 2784,
        "original_price": 3480,
        "discount_percent": 20,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/cabbage",
        "detail_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "event_name": "e머니 20% 할인",
        "valid_from": "2026-04-01T00:00:00",
        "valid_to": "2026-04-07T00:00:00",
        "unit": "800g",
        "category_id": "vegetable.cabbage",
        "category": "채소",
        "keywords": ["양배추"],
        "raw_record_id": "emart-cabbage-800g",
        "ai_review_audit": {"proposal_ids": ["cabbage-name", "cabbage-cat", "cabbage-kw"]},
        "raw_data": {
            "raw_payload": {
                "image_url": "https://emart.example/images/cabbage.jpg",
                "original_price": 3480,
                "sale_price": 2784,
                "discount_percent": 20,
                "source_url": "https://emart.example/products/cabbage",
            }
        },
    }
    with Session.begin() as session:
        session.add(Category(id="vegetable.cabbage", name="양배추", depth=1, is_active=True))
        session.add(Keyword(word="양배추", category_id="vegetable.cabbage", is_active=True))
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        product = session.query(Product).filter_by(name="한끼 양배추 800g 통").one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        link = session.query(ProductKeyword).filter_by(product_id=product.id).one()
        keyword = session.get(Keyword, link.keyword_id)

    assert saved == 1
    assert product.image_url == item["image_url"]
    assert product.category_id == "vegetable.cabbage"
    assert product.unit == "800g"
    assert history.price == 2784
    assert history.original_price == 3480
    assert history.discount_rate == 20
    assert history.source == "emart"
    assert history.source_url == item["source_url"]
    assert history.raw_data["raw_payload"]["original_price"] == 3480
    assert history.raw_data["published_item"]["image_url"] == item["image_url"]
    assert history.raw_data["observation_type"] == "price_observation"
    assert history.raw_data["claim_type"] == "verified_discount"
    assert history.raw_data["discount_claim_status"] == "source_declared"
    assert history.raw_data["published_item"]["claim_type"] == "verified_discount"
    assert history.raw_data["published_item"]["is_hotdeal_claim"] is False
    assert history.raw_data["source_title"] == "한끼 양배추 800g 통"
    assert history.raw_data["display_unit"] == "800g"
    assert history.raw_data["package_quantity"] == 800
    assert history.raw_data["price_per_100g"] == 348
    assert history.raw_data["ai_review_audit"]["proposal_ids"] == ["cabbage-name", "cabbage-cat", "cabbage-kw"]
    assert keyword.word == "양배추"


def test_ai_reviewed_price_observation_preserves_official_category_without_fake_discount():
    Session = _make_session_factory()
    item = {
        "name": "풀무원 국산콩 두부 300g",
        "sale_price": 1980,
        "current_price": 1980,
        "original_price": None,
        "discount_percent": None,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/tofu-300g",
        "image_url": "https://emart.example/images/tofu-300g.jpg",
        "unit": "300g",
        "display_unit": "300g",
        "package_quantity": 300,
        "package_unit": "g",
        "price_per_100g": 660,
        "standard_unit": "kg",
        "standard_unit_price": 6600,
        "category_id": "processed.tofu.firm",
        "keywords": ["두부"],
        "raw_record_id": "emart-tofu-300g-observation",
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "has_discount_metadata": False,
        "ai_review_audit": {"proposal_ids": ["tofu-name", "tofu-cat", "tofu-kw"]},
        "raw_data": {
            "publication": {
                "publication_kind": "price_observation",
                "price_observation_only": True,
                "discount_claim_status": "hotdeal_claim_blocked",
                "claim_basis": "current_price_observation",
            }
        },
    }
    with Session.begin() as session:
        session.add(Category(id="processed.tofu.firm", name="두부", depth=2, is_active=True))
        session.add(Keyword(word="두부", category_id="processed.tofu.firm", is_active=True))
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        product = session.query(Product).filter_by(name="풀무원 국산콩 두부 300g").one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        link = session.query(ProductKeyword).filter_by(product_id=product.id).one()
        keyword = session.get(Keyword, link.keyword_id)

    assert saved == 1
    assert product.category_id == "processed.tofu.firm"
    assert product.unit == "300g"
    assert history.price == 1980
    assert history.original_price is None
    assert history.discount_rate is None
    assert history.raw_data["publication"]["publication_kind"] == "price_observation"
    assert history.raw_data["publication"]["price_observation_only"] is True
    assert history.raw_data["publication"]["discount_claim_status"] == "hotdeal_claim_blocked"
    assert history.raw_data["standard_unit_price"] == 6600
    assert history.raw_data["price_per_100g"] == 660
    assert keyword.word == "두부"


def test_catalog_taxonomy_seed_is_idempotent_without_sample_products():
    Session = _make_session_factory()

    with Session.begin() as session:
        first = seed_catalog_taxonomy(session)
        second = seed_catalog_taxonomy(session)

    with Session() as session:
        tofu_category = session.get(Category, "processed.tofu.firm")
        tofu_keyword = session.execute(select(Keyword).where(Keyword.word == "두부")).scalar_one()
        product_count = session.query(Product).count()
        history_count = session.query(DiscountHistory).count()

    assert first["categories"] > 0
    assert first["keywords"] > 0
    assert second == {"categories": 0, "keywords": 0, "repaired_keywords": 0}
    assert tofu_category.name == "두부"
    assert tofu_keyword.category_id == "processed.tofu.firm"
    assert product_count == 0
    assert history_count == 0


def test_catalog_taxonomy_seed_repairs_stale_keyword_category():
    Session = _make_session_factory()

    with Session.begin() as session:
        session.add(Category(id="food.tofu", name="legacy tofu", depth=1, is_active=True))
        session.add(Keyword(word="두부", synonyms=[], category_id="food.tofu", is_active=False))
        result = seed_catalog_taxonomy(session)

    with Session() as session:
        keyword = session.execute(select(Keyword).where(Keyword.word == "두부")).scalar_one()

    assert result["repaired_keywords"] >= 1
    assert keyword.category_id == "processed.tofu.firm"
    assert keyword.synonyms == ["풀무원두부", "CJ두부"]
    assert keyword.is_active is True


def test_ai_reviewed_unknown_category_stays_pending_without_public_category_pollution():
    Session = _make_session_factory()
    item = {
        "name": "한끼 양배추 800g 통",
        "sale_price": 2784,
        "original_price": 3480,
        "discount_percent": 20,
        "source": "emart",
        "source_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "category_id": "ai.suggested.cabbage",
        "keywords": ["양배추"],
        "raw_record_id": "emart-cabbage-800g",
        "ai_review_audit": {"proposal_ids": ["cabbage-cat"]},
    }
    with Session.begin() as session:
        session.add(Keyword(word="양배추", is_active=True))
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        product = session.query(Product).filter_by(name="한끼 양배추 800g 통").one()
        categories = session.query(Category).filter_by(id="ai.suggested.cabbage").all()
        pending = session.query(PendingCategorization).filter_by(
            product_id=product.id,
            suggested_category_id="ai.suggested.cabbage",
        ).one()

    assert saved == 1
    assert product.category_id is None
    assert categories == []
    assert pending.suggested_category_id == "ai.suggested.cabbage"
    assert pending.status == "pending"


def test_empty_db_ai_review_price_only_observation_insert_preserves_raw_vs_final(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_item = {
        "name": "한끼 양배추 800g 통",
        "source_title": "원천명 양배추 800g",
        "sale_price": 2784,
        "current_price": 2784,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/cabbage",
        "detail_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "unit": "800g",
        "display_unit": "800g",
        "package_quantity": 800,
        "package_unit": "g",
        "price_per_100g": 348,
        "category_id": "vegetable.cabbage",
        "keywords": ["양배추"],
        "attributes": {"storage_type": "chilled", "origin": "korea"},
        "raw_record_id": "emart-cabbage-price-only",
        "source_record_key": "emart-sku-cabbage-price-only",
        "ai_review_audit": {
            "raw_record_id": "emart-cabbage-price-only",
            "proposal_ids": ["cabbage-name", "cabbage-cat"],
            "approved_fields": {
                "canonical_name": "한끼 양배추 800g 통",
                "category_id": "vegetable.cabbage",
            },
        },
        "raw_data": {
            "raw_payload": {
                "name": "원천명 양배추 800g",
                "sale_price": 2784,
                "source_url": "https://emart.example/products/cabbage",
                "image_url": "https://emart.example/images/cabbage.jpg",
                "unit": "800g",
            },
            "raw_evidence": {
                "raw_title": "원천명 양배추 800g",
                "raw_price": 2784,
                "raw_unit": "800g",
            },
        },
    }
    ingestion_id = _create_discount_pending_ingestion(Session, [raw_item])

    with Session.begin() as session:
        session.add(Category(id="vegetable.cabbage", name="양배추", depth=1, is_active=True))
        session.add(Keyword(word="양배추", category_id="vegetable.cabbage", is_active=True))

    result = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="price observation approval"),
        identity={"email": "db-admin@example.com"},
    )

    assert result["status"] == "approved"
    assert result["saved"] == 1
    with Session() as session:
        product = session.query(Product).filter_by(name=raw_item["name"]).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        ingestion = session.get(PendingIngestion, ingestion_id)

    assert ingestion.status == IngestionStatus.APPROVED
    assert product.category_id == "vegetable.cabbage"
    assert history.price == 2784
    assert history.original_price is None
    assert history.discount_rate is None
    assert history.source_url == raw_item["source_url"]
    assert history.raw_data["raw_payload"]["name"] == "원천명 양배추 800g"
    assert history.raw_data["published_item"]["name"] == "한끼 양배추 800g 통"
    assert "original_price" not in history.raw_data["published_item"]
    assert "discount_percent" not in history.raw_data["published_item"]
    assert history.raw_data["observation_type"] == "price_observation"
    assert history.raw_data["claim_type"] == "price_observation"
    assert history.raw_data["discount_claim_status"] == "unknown"
    assert history.raw_data["has_discount_metadata"] is False
    assert history.raw_data["is_hotdeal_claim"] is False
    assert history.raw_data["discount_claim"]["claim_type"] == "price_observation"
    assert history.raw_data["price_observation"]["raw_record_id"] == raw_item["raw_record_id"]
    assert history.raw_data["raw_evidence"] == raw_item["raw_data"]["raw_evidence"]


def test_repeated_ai_reviewed_source_signature_reuses_product_and_appends_history_without_overwrite():
    Session = _make_session_factory()
    base_item = {
        "name": "연속 누적 검증 상품 300g",
        "source_title": "source sku stable 300g",
        "sale_price": 3000,
        "current_price": 3000,
        "original_price": None,
        "discount_percent": None,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/stable-300g",
        "image_url": "https://emart.example/images/stable-first.jpg",
        "unit": "300g",
        "display_unit": "300g",
        "package_quantity": 300,
        "package_unit": "g",
        "price_per_100g": 1000,
        "standard_unit": "kg",
        "standard_unit_price": 10000,
        "category_id": "processed.test.accumulation",
        "keywords": ["누적검증"],
        "raw_record_id": "emart-stable-300g",
        "source_record_key": "emart-sku-stable-300g",
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "has_discount_metadata": False,
        "ai_review_audit": {
            "raw_record_id": "emart-stable-300g",
            "proposal_ids": ["stable-name", "stable-price"],
        },
        "raw_data": {
            "raw_record_id": "emart-stable-300g",
            "source_record_key": "emart-sku-stable-300g",
            "raw_payload": {
                "name": "source sku stable 300g",
                "sale_price": 3000,
                "source_signature": "emart-sku-stable-300g",
            },
        },
    }
    second_item = {
        **base_item,
        "sale_price": 2700,
        "current_price": 2700,
        "price_per_100g": 900,
        "standard_unit_price": 9000,
        "source_url": "https://emart.example/products/stable-300g?crawl=next",
        "image_url": "https://emart.example/images/stable-second.jpg",
        "raw_data": {
            **base_item["raw_data"],
            "raw_payload": {
                **base_item["raw_data"]["raw_payload"],
                "sale_price": 2700,
            },
        },
    }

    with Session.begin() as session:
        session.add(
            Category(
                id="processed.test.accumulation",
                name="누적 검증",
                depth=1,
                is_active=True,
            )
        )
        session.add(
            Keyword(
                word="누적검증",
                category_id="processed.test.accumulation",
                is_active=True,
            )
        )
        assert _insert_items(session, [base_item], "DiscountItem") == 1
        assert _insert_items(session, [second_item], "DiscountItem") == 1

    with Session() as session:
        products = session.query(Product).filter_by(name=base_item["name"]).all()
        histories = (
            session.query(DiscountHistory)
            .join(Product, Product.id == DiscountHistory.product_id)
            .filter(Product.name == base_item["name"])
            .order_by(DiscountHistory.id)
            .all()
        )

    assert len(products) == 1
    assert products[0].image_url == base_item["image_url"]
    assert len(histories) == 2
    assert [history.price for history in histories] == [3000, 2700]
    assert histories[0].raw_data["price_observation"]["price"] == 3000
    assert histories[0].raw_data["published_item"]["image_url"] == base_item["image_url"]
    assert histories[0].raw_data["source_url"] == base_item["source_url"]
    assert histories[1].raw_data["price_observation"]["price"] == 2700
    assert histories[1].raw_data["published_item"]["image_url"] == second_item["image_url"]


def test_cold_start_ai_reviewed_tofu_price_observation_replays_with_seeded_taxonomy(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_crawl_facts = {
        "raw_title": "풀무원 국산콩 두부 300g",
        "raw_price": 1980,
        "raw_unit": "300g",
        "source_url": "https://emart.example/products/tofu-300g",
        "image_url": "https://emart.example/images/tofu-300g.jpg",
    }
    reviewed_item = {
        "name": "풀무원 국산콩 두부 300g",
        "source_title": raw_crawl_facts["raw_title"],
        "sale_price": raw_crawl_facts["raw_price"],
        "current_price": raw_crawl_facts["raw_price"],
        "source": "emart",
        "store": "이마트",
        "source_url": raw_crawl_facts["source_url"],
        "detail_url": raw_crawl_facts["source_url"],
        "image_url": raw_crawl_facts["image_url"],
        "unit": raw_crawl_facts["raw_unit"],
        "display_unit": raw_crawl_facts["raw_unit"],
        "package_quantity": 300,
        "package_unit": "g",
        "price_per_100g": 660,
        "standard_unit": "kg",
        "standard_unit_price": 6600,
        "category_id": "processed.tofu.firm",
        "keywords": ["두부"],
        "raw_record_id": "emart-tofu-300g-price-observation",
        "source_record_key": "emart-sku-tofu-300g",
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "claim_basis": "current_price_observation",
        "claim_blockers": ["hotdeal_claim_blocked"],
        "ai_review_audit": {
            "raw_record_id": "emart-tofu-300g-price-observation",
            "proposal_ids": ["tofu-name", "tofu-cat", "tofu-kw", "tofu-price"],
            "approved_fields": {
                "canonical_name": "풀무원 국산콩 두부 300g",
                "category_id": "processed.tofu.firm",
                "keywords": ["두부"],
                "sale_price": 1980,
            },
        },
        "raw_data": {
            "raw_payload": {
                "name": raw_crawl_facts["raw_title"],
                "sale_price": raw_crawl_facts["raw_price"],
                "source_url": raw_crawl_facts["source_url"],
                "image_url": raw_crawl_facts["image_url"],
                "unit": raw_crawl_facts["raw_unit"],
            },
            "raw_evidence": raw_crawl_facts,
            "publication": {
                "publication_kind": "price_observation",
                "price_observation_only": True,
                "discount_claim_status": "hotdeal_claim_blocked",
                "claim_basis": "current_price_observation",
            },
        },
    }

    with Session.begin() as session:
        seed_catalog_taxonomy(session)
        assert session.query(Product).count() == 0
        assert session.query(DiscountHistory).count() == 0
    ingestion_id = _create_discount_pending_ingestion(Session, [reviewed_item])

    result = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="cold-start tofu price observation replay"),
        identity={"email": "db-admin@example.com"},
    )

    assert result["status"] == "approved"
    assert result["saved"] == 1
    with Session() as session:
        product = session.query(Product).filter_by(name=reviewed_item["name"]).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        keyword_link = session.query(ProductKeyword).filter_by(product_id=product.id).one()
        keyword = session.get(Keyword, keyword_link.keyword_id)
        ingestion = session.get(PendingIngestion, ingestion_id)
        persisted_facts = {
            "product_category_id": product.category_id,
            "keyword": keyword.word,
            "price": history.price,
            "original_price": history.original_price,
            "discount_rate": history.discount_rate,
            "raw_title": history.raw_data["raw_evidence"]["raw_title"],
            "raw_price": history.raw_data["raw_evidence"]["raw_price"],
            "raw_unit": history.raw_data["raw_evidence"]["raw_unit"],
            "source_url": history.source_url,
            "publication_kind": history.raw_data["published_item"]["publication_kind"],
            "price_observation_only": history.raw_data["published_item"]["price_observation_only"],
        }

    assert ingestion.status == IngestionStatus.APPROVED
    assert persisted_facts == {
        "product_category_id": "processed.tofu.firm",
        "keyword": "두부",
        "price": 1980,
        "original_price": None,
        "discount_rate": None,
        "raw_title": raw_crawl_facts["raw_title"],
        "raw_price": raw_crawl_facts["raw_price"],
        "raw_unit": raw_crawl_facts["raw_unit"],
        "source_url": raw_crawl_facts["source_url"],
        "publication_kind": "price_observation",
        "price_observation_only": True,
    }


def test_empty_db_acceptance_replays_raw_ai_publish_to_db_admin_without_warmed_state(monkeypatch):
    first = _run_empty_db_acceptance_flow(monkeypatch)
    second = _run_empty_db_acceptance_flow(monkeypatch)

    assert first == second
    assert first["started_empty"] is True
    assert first["ids"] == {"ingestion_id": 1, "product_id": 1, "history_id": 1}
    assert first["counts"] == {
        "products": 1,
        "discount_histories": 1,
        "product_keywords": 1,
        "pending_ingestions": 1,
    }
    assert first["persisted_product"] == {
        "name": "풀무원 국산콩 두부 300g",
        "category_id": "processed.tofu.firm",
        "keyword": "두부",
        "unit": "300g",
    }
    assert first["persisted_history"] == {
        "price": 1980,
        "original_price": None,
        "discount_rate": None,
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
    }
    assert first["raw_vs_final"] == {
        "raw_title": "원천명 국산콩 두부 300g",
        "final_name": "풀무원 국산콩 두부 300g",
        "raw_price": 1980,
        "final_sale_price": 1980,
        "raw_category_id": None,
        "final_category_id": "processed.tofu.firm",
        "raw_keywords": [],
        "final_keywords": ["두부"],
        "publication_kind": "price_observation",
        "price_observation_only": True,
    }
    assert first["post_publish_audit_codes"] == [
        "ai_suggested_category_id",
        "ai_suggested_keywords",
    ]
    assert first["anomaly_audit"]["status"] == "warning"
    assert first["anomaly_audit"]["review_queue"][0]["recommended_action"].startswith("Review relaxed")


def test_empty_db_ai_review_pending_ingestion_approval_preserves_raw_vs_final(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_item = {
        "name": "한끼 양배추 800g 통",
        "source_title": "한끼 양배추 800g 통",
        "sale_price": 2784,
        "current_price": 2784,
        "original_price": 3480,
        "discount_percent": 20,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/cabbage",
        "detail_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "event_name": "e머니 20% 할인",
        "unit": "800g",
        "display_unit": "800g",
        "package_quantity": 800,
        "package_unit": "g",
        "price_per_100g": 348,
        "category_id": "vegetable.cabbage",
        "category": "채소",
        "keywords": ["양배추"],
        "attributes": {"storage_type": "chilled", "origin": "korea"},
        "raw_record_id": "emart-cabbage-800g",
        "source_record_key": "emart-sku-cabbage",
        "ai_review_audit": {
            "raw_record_id": "emart-cabbage-800g",
            "proposal_ids": ["cabbage-name", "cabbage-cat", "cabbage-kw"],
            "approved_fields": {
                "canonical_name": "한끼 양배추 800g 통",
                "category_id": "vegetable.cabbage",
                "keywords": ["양배추"],
            },
        },
        "raw_data": {
            "raw_payload": {
                "name": "한끼 양배추 800g 통",
                "source_url": "https://emart.example/products/cabbage",
                "image_url": "https://emart.example/images/cabbage.jpg",
                "sale_price": 2784,
                "original_price": 3480,
                "discount_percent": 20,
                "unit": "800g",
                "category_id": "vegetable.cabbage",
                "keywords": ["양배추"],
                "attributes": {"storage_type": "chilled", "origin": "korea"},
            },
            "raw_evidence": {
                "raw_title": "한끼 양배추 800g 통",
                "raw_price": 2784,
                "raw_unit": "800g",
            },
        },
    }
    ingestion_id = _create_discount_pending_ingestion(Session, [raw_item])

    with Session.begin() as session:
        session.add(Category(id="vegetable.cabbage", name="양배추", depth=1, is_active=True))
        session.add(Keyword(word="양배추", category_id="vegetable.cabbage", is_active=True))

    result = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="empty DB sandbox approval"),
        identity={"email": "db-admin@example.com"},
    )

    assert result["status"] == "approved"
    assert result["saved"] == 1
    with Session() as session:
        ingestion = session.get(PendingIngestion, ingestion_id)
        product = session.query(Product).filter_by(name=raw_item["name"]).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        keyword_link = session.query(ProductKeyword).filter_by(product_id=product.id).one()
        keyword = session.get(Keyword, keyword_link.keyword_id)

    assert ingestion.status == IngestionStatus.APPROVED
    assert product.category_id == raw_item["category_id"]
    assert product.image_url == raw_item["image_url"]
    assert product.unit == raw_item["unit"]
    assert product.attributes["origin"] == "korea"
    assert history.price == raw_item["sale_price"]
    assert history.original_price == raw_item["original_price"]
    assert history.discount_rate == raw_item["discount_percent"]
    assert history.source_url == raw_item["source_url"]
    assert history.raw_data["source_title"] == raw_item["source_title"]
    assert history.raw_data["image_url"] == raw_item["image_url"]
    assert history.raw_data["raw_sale_price"] == raw_item["sale_price"]
    assert history.raw_data["raw_original_price"] == raw_item["original_price"]
    assert history.raw_data["display_unit"] == raw_item["display_unit"]
    assert history.raw_data["package_quantity"] == raw_item["package_quantity"]
    assert history.raw_data["package_unit"] == raw_item["package_unit"]
    assert history.raw_data["price_per_100g"] == raw_item["price_per_100g"]
    assert history.raw_data["category_id"] == raw_item["category_id"]
    assert history.raw_data["keywords"] == raw_item["keywords"]
    assert history.raw_data["attributes"]["storage_type"] == "chilled"
    assert history.raw_data["ai_review_audit"]["raw_record_id"] == raw_item["raw_record_id"]
    assert history.raw_data["ai_review_audit"]["proposal_ids"] == raw_item["ai_review_audit"]["proposal_ids"]
    assert history.raw_data["raw_evidence"] == raw_item["raw_data"]["raw_evidence"]
    assert history.raw_data["published_item"]["raw_record_id"] == raw_item["raw_record_id"]
    assert keyword.word == "양배추"


def test_ai_reviewed_price_observation_unknown_category_stays_pending_without_pollution():
    Session = _make_session_factory()
    item = {
        "name": "한끼 양배추 800g 통",
        "sale_price": 2784,
        "source": "emart",
        "source_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "unit": "800g",
        "display_unit": "800g",
        "package_quantity": 800,
        "package_unit": "g",
        "category_id": "ai.suggested.cabbage",
        "keywords": ["양배추"],
        "raw_record_id": "emart-cabbage-observation",
        "ai_review_audit": {"proposal_ids": ["cabbage-cat"]},
    }
    with Session.begin() as session:
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        product = session.query(Product).filter_by(name="한끼 양배추 800g 통").one()
        categories = session.query(Category).filter_by(id="ai.suggested.cabbage").all()
        pending = session.query(PendingCategorization).filter_by(
            product_id=product.id,
            suggested_category_id="ai.suggested.cabbage",
        ).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()

    assert saved == 1
    assert product.category_id is None
    assert categories == []
    assert pending.status == "pending"
    assert history.original_price is None
    assert history.discount_rate is None
    assert history.raw_data["claim_type"] == "price_observation"


def test_ai_reviewed_shrimp_and_daily_goods_keep_variant_offer_semantics():
    Session = _make_session_factory()
    items = [
        {
            "name": "흰다리 새우살",
            "source_title": "[냉동][베트남] 흰다리 새우살 (200g)",
            "sale_price": 4488,
            "original_price": 5980,
            "discount_percent": 25,
            "source": "emart",
            "store": "이마트",
            "source_url": "https://emart.example/shrimp",
            "image_url": "https://emart.example/shrimp.jpg",
            "unit": "100g",
            "display_unit": "200g",
            "package_quantity": 200,
            "package_unit": "g",
            "standard_unit": "kg",
            "standard_unit_price": 22440,
            "price_per_100g": 2244,
            "category_id": "seafood.shrimp",
            "attributes": {"storage_type": "frozen", "origin": "vietnam", "cut": "shrimp_meat"},
            "keywords": ["새우"],
            "raw_record_id": "raw-shrimp",
            "ai_review_audit": {"proposal_ids": ["shrimp"]},
        },
        {
            "name": "세탁세제 리필",
            "source_title": "세탁세제 리필 2L",
            "sale_price": 6900,
            "original_price": 9900,
            "discount_percent": 30,
            "source": "emart",
            "store": "이마트",
            "source_url": "https://emart.example/detergent",
            "image_url": "https://emart.example/detergent.jpg",
            "display_unit": "2L",
            "package_quantity": 2,
            "package_unit": "L",
            "category_id": "daily.detergent",
            "keywords": ["세탁세제"],
            "raw_record_id": "raw-detergent",
            "ai_review_audit": {"proposal_ids": ["detergent"]},
        },
    ]
    with Session.begin() as session:
        session.add(Category(id="seafood.shrimp", name="새우", depth=1, is_active=True))
        session.add(Category(id="daily.detergent", name="세탁세제", depth=1, is_active=True))
        session.add(Keyword(word="새우", category_id="seafood.shrimp", is_active=True))
        session.add(Keyword(word="세탁세제", category_id="daily.detergent", is_active=True))
        saved = _insert_items(session, items, "DiscountItem")

    with Session() as session:
        rows = session.execute(select(DiscountHistory).order_by(DiscountHistory.price)).scalars().all()
        products = {product.name: product for product in session.query(Product).all()}

    assert saved == 2
    shrimp = rows[0]
    detergent = rows[1]
    assert products["흰다리 새우살"].category_id == "seafood.shrimp"
    assert shrimp.raw_data["source_title"].startswith("[냉동]")
    assert shrimp.raw_data["standard_unit_price"] == 22440
    assert shrimp.raw_data["attributes"]["origin"] == "vietnam"
    assert detergent.raw_data["display_unit"] == "2L"
    assert detergent.raw_data["package_unit"] == "L"
    assert products["세탁세제 리필"].image_url.endswith("detergent.jpg")


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _patch_managed_session(monkeypatch, Session):
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

    import api.routes.ingestion as ingestion_routes

    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)


def _create_pending_ingestion(Session, items):
    quality_score, quality_details = _calculate_quality(items, "HotdealPost")
    with Session.begin() as session:
        row = PendingIngestion(
            crawler_name="algumon",
            crawl_status="success",
            items_count=len(items),
            items_json=json.dumps(items, ensure_ascii=False),
            schema_type="HotdealPost",
            quality_score=quality_score,
            quality_details=quality_details,
            status=IngestionStatus.PENDING,
        )
        session.add(row)
        session.flush()
        return row.id


def _create_discount_pending_ingestion(Session, items):
    quality_score, quality_details = _calculate_quality(items, "DiscountItem")
    with Session.begin() as session:
        row = PendingIngestion(
            crawler_name="ai-admin:emart",
            crawl_status="success",
            items_count=len(items),
            items_json=json.dumps(items, ensure_ascii=False),
            schema_type="DiscountItem",
            strategy_used="ai_review_publish",
            quality_score=quality_score,
            quality_details=quality_details,
            status=IngestionStatus.CRAWLER_APPROVED,
        )
        session.add(row)
        session.flush()
        return row.id


def _create_pending_ai_discount_ingestion(Session, items):
    quality_score, quality_details = _calculate_quality(items, "DiscountItem")
    with Session.begin() as session:
        row = PendingIngestion(
            crawler_name="ai-admin:emart",
            crawl_status="success",
            items_count=len(items),
            items_json=json.dumps(items, ensure_ascii=False),
            schema_type="DiscountItem",
            strategy_used="ai_review_publish",
            quality_score=quality_score,
            quality_details=quality_details,
            status=IngestionStatus.PENDING,
        )
        session.add(row)
        session.flush()
        return row.id


def _run_empty_db_acceptance_flow(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_record_id = "acceptance-tofu-price-observation"
    raw_crawl_item = {
        "raw_record_id": raw_record_id,
        "name": "원천명 국산콩 두부 300g",
        "sale_price": 1980,
        "source": "emart",
        "source_url": "https://emart.example/products/tofu-300g",
        "image_url": "https://emart.example/images/tofu-300g.jpg",
        "unit": "300g",
        "category_id": None,
        "keywords": [],
    }
    ai_proposals = [
        {
            "proposal_id": "acceptance-tofu-name",
            "target_field": "canonical_name",
            "proposed_value": "풀무원 국산콩 두부 300g",
            "status": "approved",
        },
        {
            "proposal_id": "acceptance-tofu-category",
            "target_field": "category_id",
            "proposed_value": "processed.tofu.firm",
            "status": "ai_proposed",
        },
        {
            "proposal_id": "acceptance-tofu-keywords",
            "target_field": "keywords",
            "proposed_value": ["두부"],
            "status": "ai_proposed",
        },
        {
            "proposal_id": "acceptance-tofu-price",
            "target_field": "sale_price",
            "proposed_value": 1980,
            "status": "approved",
        },
    ]
    post_publish_audit_flags = [
        {
            "code": "ai_suggested_category_id",
            "source": "field_proposal",
            "proposal_id": "acceptance-tofu-category",
            "status": "ai_proposed",
            "severity": "post_publish_audit",
        },
        {
            "code": "ai_suggested_keywords",
            "source": "field_proposal",
            "proposal_id": "acceptance-tofu-keywords",
            "status": "ai_proposed",
            "severity": "post_publish_audit",
        },
    ]
    anomaly_audit = {
        "status": "warning",
        "scope": "ready_or_published",
        "review_queue": [
            {
                "type": "post_publish_audit_flags",
                "severity": "warning",
                "raw_record_id": raw_record_id,
                "message": "Relaxed taxonomy/keyword AI proposals moved through publish for DB-admin visibility.",
                "recommended_action": "Review relaxed taxonomy/keyword flags after DB-admin approval; correct or roll back if final catalog placement is wrong.",
            }
        ],
    }
    reviewed_item = {
        "name": "풀무원 국산콩 두부 300g",
        "source_title": raw_crawl_item["name"],
        "sale_price": raw_crawl_item["sale_price"],
        "current_price": raw_crawl_item["sale_price"],
        "original_price": None,
        "discount_percent": None,
        "source": raw_crawl_item["source"],
        "store": "이마트",
        "source_url": raw_crawl_item["source_url"],
        "detail_url": raw_crawl_item["source_url"],
        "image_url": raw_crawl_item["image_url"],
        "unit": raw_crawl_item["unit"],
        "display_unit": raw_crawl_item["unit"],
        "package_quantity": 300,
        "package_unit": "g",
        "price_per_100g": 660,
        "standard_unit": "kg",
        "standard_unit_price": 6600,
        "category_id": "processed.tofu.firm",
        "keywords": ["두부"],
        "raw_record_id": raw_record_id,
        "source_record_key": "emart-sku-acceptance-tofu-300g",
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": "hotdeal_claim_blocked",
        "claim_basis": "current_price_observation",
        "claim_blockers": ["hotdeal_claim_blocked"],
        "post_publish_audit_flags": post_publish_audit_flags,
        "ai_review_audit": {
            "raw_record_id": raw_record_id,
            "proposal_ids": [proposal["proposal_id"] for proposal in ai_proposals],
            "proposals": ai_proposals,
            "approved_fields": {
                "canonical_name": "풀무원 국산콩 두부 300g",
                "category_id": "processed.tofu.firm",
                "keywords": ["두부"],
                "sale_price": 1980,
            },
        },
        "raw_data": {
            "raw_payload": raw_crawl_item,
            "raw_evidence": {
                "raw_title": raw_crawl_item["name"],
                "raw_price": raw_crawl_item["sale_price"],
                "raw_unit": raw_crawl_item["unit"],
                "source_url": raw_crawl_item["source_url"],
            },
            "publication": {
                "publication_kind": "price_observation",
                "price_observation_only": True,
                "discount_claim_status": "hotdeal_claim_blocked",
                "claim_basis": "current_price_observation",
            },
            "post_publish_audit_flags": post_publish_audit_flags,
            "anomaly_audit": anomaly_audit,
        },
    }

    with Session.begin() as session:
        started_empty = (
            session.query(Product).count() == 0
            and session.query(DiscountHistory).count() == 0
            and session.query(ProductKeyword).count() == 0
        )
        seed_catalog_taxonomy(session)
        assert session.query(Product).count() == 0
        assert session.query(DiscountHistory).count() == 0
    ingestion_id = _create_discount_pending_ingestion(Session, [reviewed_item])

    result = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="empty DB acceptance publish-approved replay"),
        identity={"email": "db-admin@example.com"},
    )
    assert result["status"] == "approved"
    assert result["saved"] == 1

    with Session() as session:
        product = session.query(Product).filter_by(name=reviewed_item["name"]).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        keyword_link = session.query(ProductKeyword).filter_by(product_id=product.id).one()
        keyword = session.get(Keyword, keyword_link.keyword_id)
        ingestion = session.get(PendingIngestion, ingestion_id)
        raw_data = history.raw_data
        raw_payload = raw_data["raw_payload"]
        published_item = raw_data["published_item"]
        summary = {
            "started_empty": started_empty,
            "ids": {
                "ingestion_id": ingestion.id,
                "product_id": product.id,
                "history_id": history.id,
            },
            "counts": {
                "products": session.query(Product).count(),
                "discount_histories": session.query(DiscountHistory).count(),
                "product_keywords": session.query(ProductKeyword).count(),
                "pending_ingestions": session.query(PendingIngestion).count(),
            },
            "persisted_product": {
                "name": product.name,
                "category_id": product.category_id,
                "keyword": keyword.word,
                "unit": product.unit,
            },
            "persisted_history": {
                "price": history.price,
                "original_price": history.original_price,
                "discount_rate": history.discount_rate,
                "publication_kind": published_item["publication_kind"],
                "price_observation_only": published_item["price_observation_only"],
                "discount_claim_status": raw_data["publication"]["discount_claim_status"],
            },
            "raw_vs_final": {
                "raw_title": raw_payload["name"],
                "final_name": published_item["name"],
                "raw_price": raw_payload["sale_price"],
                "final_sale_price": published_item["sale_price"],
                "raw_category_id": raw_payload["category_id"],
                "final_category_id": published_item["category_id"],
                "raw_keywords": raw_payload["keywords"],
                "final_keywords": published_item["keywords"],
                "publication_kind": published_item["publication_kind"],
                "price_observation_only": published_item["price_observation_only"],
            },
            "post_publish_audit_codes": [
                flag["code"] for flag in raw_data["post_publish_audit_flags"]
            ],
            "anomaly_audit": raw_data["anomaly_audit"],
        }
    return summary


def test_update_ingestion_row_persists_items_and_recomputes_quality(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_pending_ingestion(
        Session,
        [
            {"title": "정상 핫딜", "url": "https://example.com/ok", "price": 1000},
            {"title": "가격 누락", "url": "https://example.com/missing", "price": None},
        ],
    )

    detail = update_ingestion_item(
        ingestion_id,
        1,
        IngestionRowUpdateRequest(
            item={"title": "가격 보정", "url": "https://example.com/missing", "price": 2500},
            notes="가격 보정",
        ),
        request=None,
        identity={"email": "admin@example.com"},
    )

    assert detail["items"][1]["price"] == 2500
    assert detail["items_count"] == 2
    assert detail["quality_details"]["missing_fields"] == 0
    assert detail["problem_indices"] == []
    assert "가격 보정" in detail["crawler_reviewer_notes"]

    with Session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        saved_items = json.loads(row.items_json)
        assert saved_items[1]["title"] == "가격 보정"
        assert row.items_count == 2
        assert row.quality_details["missing_fields"] == 0


def test_ai_reviewed_offer_missing_visible_fields_remains_pending(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_discount_pending_ingestion(
        Session,
        [
            {
                "name": "한끼 양배추 800g 통",
                "sale_price": 2784,
                "original_price": 3480,
                "discount_percent": 20,
                "source": "emart",
                "source_url": "https://emart.example/products/cabbage",
                "keywords": ["양배추"],
                "raw_record_id": "emart-cabbage-800g",
                "ai_review_audit": {"proposal_ids": ["cabbage-name"]},
            }
        ],
    )

    result = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="최종 승인"),
        identity={"email": "admin@example.com"},
    )

    assert result["status"] == "crawler_approved"
    assert result["saved"] == 0
    assert result["failed"] == 1
    with Session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        products = session.query(Product).all()
        histories = session.query(DiscountHistory).all()

    assert row.status == IngestionStatus.CRAWLER_APPROVED
    assert "필수 공개 메타데이터" in row.db_reviewer_notes
    assert products == []
    assert histories == []


def test_ai_safe_final_approve_publishes_pending_ai_row_with_audit_and_re_review_evidence(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_item = {
        "name": "한끼 양배추 800g 통",
        "source_title": "원천명 양배추 800g",
        "sale_price": 2784,
        "current_price": 2784,
        "original_price": 3480,
        "discount_percent": 20,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/cabbage",
        "detail_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "unit": "800g",
        "display_unit": "800g",
        "package_quantity": 800,
        "package_unit": "g",
        "price_per_100g": 348,
        "category_id": "vegetable.cabbage",
        "keywords": ["양배추"],
        "raw_record_id": "emart-cabbage-one-action",
        "source_record_key": "emart-sku-cabbage-one-action",
        "ai_review_audit": {"raw_record_id": "emart-cabbage-one-action", "proposal_ids": ["name", "cat", "price"]},
        "raw_data": {
            "raw_payload": {"name": "원천명 양배추 800g", "sale_price": 2784},
            "raw_evidence": {"raw_title": "원천명 양배추 800g", "raw_price": 2784, "raw_unit": "800g"},
        },
    }
    ingestion_id = _create_pending_ai_discount_ingestion(Session, [raw_item])
    with Session.begin() as session:
        session.add(Category(id="vegetable.cabbage", name="양배추", depth=1, is_active=True))
        session.add(Keyword(word="양배추", category_id="vegetable.cabbage", is_active=True))

    approved = ai_safe_final_approve(
        ingestion_id,
        ReviewRequest(action="approve", notes="one final action"),
        request=None,
        identity={"email": "db-admin@example.com"},
    )

    assert approved["status"] == "approved"
    assert approved["saved"] == 1
    assert approved["raw_evidence_retained"] is True
    assert approved["rollback_supported"] is True
    assert approved["re_review_supported"] is True
    assert approved["public_db_verification"]["verified"] is True
    assert approved["public_db_verification"]["verified_count"] == 1
    assert approved["operator_next_action"]
    with Session() as session:
        ingestion = session.get(PendingIngestion, ingestion_id)
        product = session.query(Product).filter_by(name=raw_item["name"]).one()
        history = session.query(DiscountHistory).filter_by(product_id=product.id).one()
        publish_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_ai_safe_final_approve")
        ).scalar_one()

    assert ingestion.status == IngestionStatus.APPROVED
    assert ingestion.crawler_reviewed_at is not None
    assert ingestion.db_reviewed_at is not None
    assert "one-final-action" in ingestion.crawler_reviewer_notes
    assert "one final action" in ingestion.db_reviewer_notes
    assert history.raw_data["raw_evidence"]["raw_price"] == 2784
    assert history.raw_data["published_item"]["raw_record_id"] == raw_item["raw_record_id"]
    assert publish_audit.old_value["items"][0]["raw_data"]["raw_evidence"]["raw_title"] == "원천명 양배추 800g"
    assert publish_audit.new_value["rollback_supported"] is True
    assert publish_audit.new_value["public_db_verification"]["verified"] is True

    queued = queue_published_ingestion_item_for_re_review(
        ingestion_id,
        0,
        PublishedRowReReviewRequest(reason="verify one-action evidence"),
        request=None,
        identity={"email": "db-admin@example.com"},
    )
    rolled_back = rollback_published_ingestion_item(
        ingestion_id,
        0,
        PublishedRowRollbackRequest(reason="operator rollback check"),
        request=None,
        identity={"email": "db-admin@example.com"},
    )

    assert queued["re_review_status"] == "crawler_approved"
    assert queued["raw_evidence_retained"] is True
    assert rolled_back["raw_evidence_retained"] is True
    with Session() as session:
        re_review = session.get(PendingIngestion, queued["re_review_ingestion_id"])
        re_review_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_published_row_re_review")
        ).scalar_one()
        rollback_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_published_row_rollback")
        ).scalar_one()

    assert json.loads(re_review.items_json)[0]["raw_data"]["re_review_source"]["original_item"]["raw_record_id"] == raw_item["raw_record_id"]
    assert re_review_audit.old_value["item"]["raw_data"]["raw_evidence"]["raw_price"] == 2784
    assert rollback_audit.old_value["raw_data"]["raw_evidence"]["raw_unit"] == "800g"


def test_ai_safe_final_approve_blocks_missing_critical_ai_fields_without_publishing(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_pending_ai_discount_ingestion(
        Session,
        [
            {
                "name": "테스트 상품",
                "sale_price": 1200,
                "source": "emart",
                "source_url": "https://emart.example/products/test",
                "raw_record_id": "emart-test-missing-fields",
                "ai_review_audit": {"proposal_ids": ["test"]},
            }
        ],
    )

    result = ai_safe_final_approve(
        ingestion_id,
        ReviewRequest(action="approve", notes="try one final action"),
        request=None,
        identity={"email": "db-admin@example.com"},
    )

    assert result["status"] == "pending"
    assert result["blocked"] is True
    assert any("image_url" in blocker for blocker in result["blockers"])
    with Session() as session:
        ingestion = session.get(PendingIngestion, ingestion_id)
        products = session.query(Product).all()
        histories = session.query(DiscountHistory).all()
        blocked_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_ai_safe_final_blocked")
        ).scalar_one()

    assert ingestion.status == IngestionStatus.PENDING
    assert "try one final action" in ingestion.db_reviewer_notes
    assert products == []
    assert histories == []
    assert any("image_url" in blocker for blocker in blocked_audit.new_value["blockers"])


def test_published_ai_row_can_be_rereviewed_corrected_and_rolled_back_with_evidence(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    raw_item = {
        "name": "한끼 양배추 800g 통",
        "source_title": "원천명 양배추 800g",
        "sale_price": 2784,
        "current_price": 2784,
        "original_price": 3480,
        "discount_percent": 20,
        "source": "emart",
        "store": "이마트",
        "source_url": "https://emart.example/products/cabbage",
        "detail_url": "https://emart.example/products/cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "unit": "800g",
        "display_unit": "800g",
        "package_quantity": 800,
        "package_unit": "g",
        "category_id": "wrong.category",
        "keywords": ["잘못된키워드"],
        "raw_record_id": "emart-cabbage-rollback",
        "source_record_key": "emart-sku-cabbage-rollback",
        "ai_review_audit": {"raw_record_id": "emart-cabbage-rollback", "proposal_ids": ["bad-cat", "bad-kw"]},
        "raw_data": {
            "raw_payload": {"name": "원천명 양배추 800g", "sale_price": 2784},
            "raw_evidence": {"raw_title": "원천명 양배추 800g", "raw_price": 2784},
        },
    }
    ingestion_id = _create_discount_pending_ingestion(Session, [raw_item])
    with Session.begin() as session:
        session.add(Category(id="wrong.category", name="오분류", depth=1, is_active=True))
        session.add(Category(id="vegetable.cabbage", name="양배추", depth=1, is_active=True))
        session.add(Keyword(word="잘못된키워드", category_id="wrong.category", is_active=True))
        session.add(Keyword(word="양배추", category_id="vegetable.cabbage", is_active=True))

    approved = db_review(
        ingestion_id,
        ReviewRequest(action="approve", notes="bad publish"),
        identity={"email": "db-admin@example.com"},
    )
    assert approved["status"] == "approved"

    corrected_item = raw_item | {
        "category_id": "vegetable.cabbage",
        "keywords": ["양배추"],
        "sale_price": 2680,
        "current_price": 2680,
        "raw_record_id": "emart-cabbage-corrected",
        "source_record_key": "emart-sku-cabbage-corrected",
    }
    queued = queue_published_ingestion_item_for_re_review(
        ingestion_id,
        0,
        PublishedRowReReviewRequest(reason="wrong category and keyword", corrected_item=corrected_item),
        request=None,
        identity={"email": "db-admin@example.com"},
    )
    assert queued["re_review_status"] == "crawler_approved"

    corrected = db_review(
        queued["re_review_ingestion_id"],
        ReviewRequest(action="approve", notes="corrected publish"),
        identity={"email": "db-admin@example.com"},
    )
    assert corrected["status"] == "approved"

    rolled_back = rollback_published_ingestion_item(
        ingestion_id,
        0,
        PublishedRowRollbackRequest(reason="superseded by corrected re-review"),
        request=None,
        identity={"email": "db-admin@example.com"},
    )
    assert rolled_back["rollback"]["status"] == "rolled_back"
    assert rolled_back["raw_evidence_retained"] is True

    with Session() as session:
        product = session.query(Product).filter_by(name="한끼 양배추 800g 통").one()
        histories = session.execute(
            select(DiscountHistory).where(DiscountHistory.product_id == product.id)
        ).scalars().all()
        original = session.get(PendingIngestion, ingestion_id)
        re_review = session.get(PendingIngestion, queued["re_review_ingestion_id"])
        rollback_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_published_row_rollback")
        ).scalar_one()
        re_review_audit = session.execute(
            select(AuditLog).where(AuditLog.action == "ingestion_published_row_re_review")
        ).scalar_one()

    assert product.category_id == "vegetable.cabbage"
    assert product.is_active is True
    assert len(histories) == 1
    assert histories[0].price == 2680
    assert histories[0].raw_data["re_review_source"]["original_item"]["raw_record_id"] == "emart-cabbage-rollback"
    assert "rolled back" in original.db_reviewer_notes
    assert json.loads(original.items_json)[0]["_db_admin_rollback"]["status"] == "rolled_back"
    assert json.loads(re_review.items_json)[0]["_db_admin_re_review"]["source_ingestion_id"] == ingestion_id
    assert rollback_audit.old_value["raw_data"]["raw_evidence"]["raw_price"] == 2784
    assert re_review_audit.old_value["item"]["raw_data"]["raw_evidence"]["raw_title"] == "원천명 양배추 800g"


def test_remove_ingestion_row_recomputes_indices_and_approve_uses_corrected_rows(monkeypatch):
    Session = _make_session_factory()
    _patch_managed_session(monkeypatch, Session)
    ingestion_id = _create_pending_ingestion(
        Session,
        [
            {"title": "저장 A", "url": "https://example.com/a", "price": 1000},
            {"title": "삭제 대상", "url": "https://example.com/b", "price": None},
            {"title": "저장 C", "url": "https://example.com/c", "price": 3000},
        ],
    )

    detail = remove_ingestion_item(
        ingestion_id,
        1,
        request=None,
        notes="누락 행 제외",
        identity={"email": "admin@example.com"},
    )

    assert [item["title"] for item in detail["items"]] == ["저장 A", "저장 C"]
    assert detail["items_count"] == 2
    assert detail["quality_details"]["missing_fields"] == 0
    assert _find_problem_items(detail["items"], "HotdealPost") == []

    with Session.begin() as session:
        row = session.get(PendingIngestion, ingestion_id)
        row.status = IngestionStatus.CRAWLER_APPROVED
        corrected_items = json.loads(row.items_json)
        saved = _insert_items(session, corrected_items, row.schema_type)
        row.status = IngestionStatus.APPROVED

    with Session() as session:
        rows = session.execute(select(HotdealPrice).order_by(HotdealPrice.title)).scalars().all()
        assert saved == 2
        assert [row.title for row in rows] == ["저장 A", "저장 C"]
