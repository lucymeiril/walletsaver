import json
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from storage.models import (
    Base, Category, DiscountHistory, HotdealPrice, IngestionStatus, PendingIngestion,
    Product, User, Post, PostType, UserRole,
)


@pytest.fixture
def db_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    session.add(Category(id="food", name="식품", depth=0, is_active=True))
    session.add(Product(
        id=1,
        name="알구몬 테스트 상품",
        category_id="food",
        unit="개",
        source_type="algumon",
        attributes={"brand": "test"},
        is_active=True,
    ))
    session.add(User(id=1, email="mod@example.com", nickname="moderator", role=UserRole.ADMIN))
    session.add(Post(
        id=1,
        author_id=1,
        post_type=PostType.HOTDEAL,
        title="관리 대상 게시글",
        content="삭제 가능한 커뮤니티 게시글",
        created_at=datetime.utcnow(),
    ))
    session.commit()
    session.close()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import api.routes.products as products_routes
    import api.routes.analytics as analytics_routes
    import api.routes.community as community_routes
    import api.routes.ingestion as ingestion_routes

    monkeypatch.setattr(products_routes, "get_session", get_test_session)
    monkeypatch.setattr(analytics_routes, "get_session", get_test_session)
    monkeypatch.setattr(community_routes, "get_session", get_test_session)
    monkeypatch.setattr(ingestion_routes, "get_session", get_test_session)
    monkeypatch.setattr(products_routes, "managed_session", managed_test_session)
    monkeypatch.setattr(community_routes, "managed_session", managed_test_session)
    monkeypatch.setattr(ingestion_routes, "managed_session", managed_test_session)

    return Session


@pytest.fixture
def client(db_session_factory):
    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    return TestClient(create_app())


def test_algumon_is_source_type_and_product_filter(client):
    source_types = client.get("/api/analytics/source-types").json()
    assert "algumon" in source_types

    stats = client.get("/api/products/stats").json()
    assert stats["by_source"]["algumon"] == 1

    filtered = client.get("/api/products/", params={"source": "algumon"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["source_type"] == "algumon"


def test_algumon_ingestion_approval_is_manageable_by_source(client, db_session_factory):
    items = [
        {
            "title": "승인된 알구몬 핫딜",
            "url": "https://www.algumon.com/l/deal/123",
            "source_community": "알구몬",
            "price": 19900,
        },
        {
            "title": "가격 없는 알구몬 핫딜",
            "url": "https://www.algumon.com/l/deal/missing-price",
            "source_community": "알구몬",
            "price": None,
        },
    ]
    session = db_session_factory()
    try:
        row = PendingIngestion(
            crawler_name="algumon",
            crawl_status="success",
            items_count=len(items),
            items_json=json.dumps(items, ensure_ascii=False),
            schema_type="HotdealPost",
            quality_score=0.5,
            quality_details={},
            status=IngestionStatus.PENDING,
            source_url="https://www.algumon.com/n/deal",
        )
        session.add(row)
        session.commit()
        ingestion_id = row.id
    finally:
        session.close()

    crawler_review = client.post(f"/api/ingestions/{ingestion_id}/crawler-review", json={"action": "approve"})
    assert crawler_review.status_code == 200
    db_review = client.post(f"/api/ingestions/{ingestion_id}/db-review", json={"action": "approve"})
    assert db_review.status_code == 200
    assert db_review.json()["saved"] == 1

    filtered = client.get("/api/products/", params={"source": "algumon", "search": "승인된 알구몬"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["source_type"] == "algumon"
    assert "algumon" in filtered["items"][0]["sources"]

    source_types = client.get("/api/analytics/source-types").json()
    assert "algumon" in source_types

    session = db_session_factory()
    try:
        hotdeals = session.query(HotdealPrice).filter_by(source="algumon").all()
        assert len(hotdeals) == 1
        assert hotdeals[0].price == 19900
        assert session.query(HotdealPrice).filter_by(title="가격 없는 알구몬 핫딜").count() == 0
    finally:
        session.close()


def test_legacy_algumon_alias_sources_filter_as_algumon(client, db_session_factory):
    session = db_session_factory()
    try:
        product = Product(name="레거시 알구몬 상품", unit="개", source_type="unknown", is_active=True)
        session.add(product)
        session.flush()
        session.add(HotdealPrice(
            product_id=product.id,
            price=9900,
            source="https://www.algumon.com/l/deal/legacy",
            source_url="https://www.algumon.com/l/deal/legacy",
            title=product.name,
            crawled_at=datetime.utcnow(),
        ))
        session.commit()
    finally:
        session.close()

    filtered = client.get("/api/products/", params={"source": "algumon", "search": "레거시 알구몬"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["sources"] == ["algumon"]


def test_product_update_accepts_admin_form_fields(client):
    payload = {
        "description": "관리자가 편집한 설명",
        "image_url": "https://example.com/image.jpg",
        "source_type": "user_submitted",
        "attributes": {"origin": "KR"},
        "is_active": False,
    }
    response = client.put("/api/products/1", json=payload)
    assert response.status_code == 200

    product = client.get("/api/products/1").json()
    assert product["description"] == payload["description"]
    assert product["image_url"] == payload["image_url"]
    assert product["source_type"] == "user_submitted"
    assert product["attributes"] == {"origin": "KR"}
    assert product["is_active"] is False


def test_product_create_persists_current_offer_fields(client, db_session_factory):
    payload = {
        "name": "오프라인 행사 양파",
        "unit": "2kg",
        "category_id": "food",
        "image_url": "https://example.com/onion.jpg",
        "source_type": "user_submitted",
        "offer_source": "이마트 성수점",
        "channel": "offline",
        "current_price": 3980,
        "original_price": 5980,
        "valid_from": "2026-04-01T00:00:00",
        "valid_to": "2026-04-07T00:00:00",
        "source_url": "https://example.com/flyer",
        "quantity": "1망",
        "offer_notes": "전단 확인",
    }
    response = client.post("/api/products/", json=payload)
    assert response.status_code == 201
    product = response.json()
    assert product["current_price"] == 3980
    assert product["original_price"] == 5980
    assert product["discount_rate"] == 33.4
    assert product["source"] == "이마트 성수점"
    assert product["channel"] == "offline"
    assert product["source_url"] == payload["source_url"]

    session = db_session_factory()
    try:
        history = session.query(DiscountHistory).filter_by(product_id=product["id"]).one()
        assert history.price == 3980
        assert history.raw_data["quantity"] == "1망"
        assert history.raw_data["notes"] == "전단 확인"
        assert history.raw_data["admin_managed"] is True
    finally:
        session.close()


def test_product_update_replaces_current_offer_without_zero_price(client, db_session_factory):
    response = client.put("/api/products/1", json={
        "offer_source": "algumon",
        "channel": "online",
        "current_price": 9900,
        "original_price": 12000,
        "discount_rate": 17.5,
        "discount_rate_manual": True,
        "source_url": "https://example.com/deal",
        "offer_raw_data": {"store": "web"},
    })
    assert response.status_code == 200
    product = client.get("/api/products/1").json()
    assert product["current_price"] == 9900
    assert product["discount_rate"] == 17.5
    assert product["discount_rate_manual"] is True
    assert product["channel"] == "online"

    zero_response = client.put("/api/products/1", json={
        "offer_source": "algumon",
        "current_price": 0,
    })
    assert zero_response.status_code == 422

    session = db_session_factory()
    try:
        histories = session.query(DiscountHistory).filter_by(product_id=1).all()
        assert len(histories) == 1
        assert histories[0].price == 9900
        assert histories[0].raw_data["store"] == "web"
    finally:
        session.close()


def test_community_moderation_list_delete_restore_and_reported_placeholder(client):
    active = client.get("/api/community/posts", params={"status": "active"}).json()
    assert active["total"] == 1
    assert active["items"][0]["title"] == "관리 대상 게시글"

    deleted = client.delete("/api/community/posts/1")
    assert deleted.status_code == 200

    deleted_list = client.get("/api/community/posts", params={"status": "deleted"}).json()
    assert deleted_list["total"] == 1
    assert deleted_list["items"][0]["is_deleted"] is True

    restored = client.post("/api/community/posts/1/restore")
    assert restored.status_code == 200
    assert client.get("/api/community/posts", params={"status": "active"}).json()["total"] == 1

    reported = client.get("/api/community/posts", params={"status": "reported"}).json()
    assert reported["items"] == []
    assert "신고 테이블" in reported["note"]
