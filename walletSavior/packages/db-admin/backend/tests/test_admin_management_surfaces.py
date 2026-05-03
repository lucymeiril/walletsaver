from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from storage.models import Base, Category, Product, User, Post, PostType, UserRole


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

    monkeypatch.setattr(products_routes, "get_session", get_test_session)
    monkeypatch.setattr(analytics_routes, "get_session", get_test_session)
    monkeypatch.setattr(community_routes, "get_session", get_test_session)
    monkeypatch.setattr(products_routes, "managed_session", managed_test_session)
    monkeypatch.setattr(community_routes, "managed_session", managed_test_session)

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
