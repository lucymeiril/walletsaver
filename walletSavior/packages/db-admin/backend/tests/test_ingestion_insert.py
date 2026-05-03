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
    ReviewRequest,
    _calculate_quality,
    _find_problem_items,
    _insert_items,
    db_review,
    remove_ingestion_item,
    update_ingestion_item,
)
from storage.models import (
    Base,
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
    assert keyword.word == "양배추"


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
