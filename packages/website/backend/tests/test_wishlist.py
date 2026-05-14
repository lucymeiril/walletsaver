"""찜 목록 API 테스트 — 추가/삭제/목표가 변경"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_db():
    from services.db import get_engine, reset_engine
    from storage.models import Base
    reset_engine()
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield
    reset_engine()


@pytest.fixture
def app():
    from api.routes.wishlist import router as wishlist_router
    from api.routes.auth import router as auth_router
    from api.middleware.rate_limit import limiter
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(auth_router)
    app.include_router(wishlist_router)
    try:
        limiter.reset()
    except Exception:
        pass
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _register(client) -> str:
    resp = client.post("/api/auth/register", json={
        "email": "wish@test.com", "password": "TestPass1", "nickname": "찜유저"
    })
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestWishlistAdd:
    def test_add_item(self, client):
        token = _register(client)
        resp = client.post("/api/wishlist", json={
            "item_name": "사과 10kg", "target_price": 25000, "store_name": "이마트"
        }, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["item_name"] == "사과 10kg"
        assert data["target_price"] == 25000

    def test_add_requires_name(self, client):
        token = _register(client)
        resp = client.post("/api/wishlist", json={
            "target_price": 10000
        }, headers=_auth(token))
        assert resp.status_code == 400

    def test_add_unauthenticated(self, client):
        resp = client.post("/api/wishlist", json={"item_name": "테스트"})
        assert resp.status_code == 401

    def test_add_duplicate_product(self, client):
        token = _register(client)
        headers = _auth(token)
        from services.db import managed_session
        from storage.models import Product
        with managed_session() as session:
            p = Product(name="중복테스트", unit="개")
            session.add(p)
            session.flush()
            pid = p.id

        client.post("/api/wishlist", json={
            "product_id": pid, "item_name": "중복테스트"
        }, headers=headers)
        resp = client.post("/api/wishlist", json={
            "product_id": pid, "item_name": "중복테스트"
        }, headers=headers)
        assert resp.status_code == 400
        assert "이미 찜한" in resp.json()["detail"]


class TestWishlistCRUD:
    def test_list_wishlist(self, client):
        token = _register(client)
        headers = _auth(token)
        client.post("/api/wishlist", json={"item_name": "A"}, headers=headers)
        client.post("/api/wishlist", json={"item_name": "B"}, headers=headers)
        resp = client.get("/api/wishlist", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_remove_item(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/wishlist", json={"item_name": "A"}, headers=headers)
        item_id = add_resp.json()["data"]["id"]

        resp = client.delete(f"/api/wishlist/{item_id}", headers=headers)
        assert resp.status_code == 200

        list_resp = client.get("/api/wishlist", headers=headers)
        assert len(list_resp.json()["data"]) == 0

    def test_remove_nonexistent(self, client):
        token = _register(client)
        resp = client.delete("/api/wishlist/99999", headers=_auth(token))
        assert resp.status_code == 404


class TestWishlistUpdate:
    def test_update_target_price(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/wishlist", json={
            "item_name": "사과", "target_price": 30000
        }, headers=headers)
        item_id = add_resp.json()["data"]["id"]

        resp = client.put(f"/api/wishlist/{item_id}", json={
            "target_price": 25000
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["target_price"] == 25000

    def test_update_notify_on_drop(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/wishlist", json={"item_name": "사과"}, headers=headers)
        item_id = add_resp.json()["data"]["id"]

        resp = client.put(f"/api/wishlist/{item_id}", json={
            "notify_on_drop": True
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["notify_on_drop"] is True

    def test_update_nonexistent(self, client):
        token = _register(client)
        resp = client.put("/api/wishlist/99999", json={"target_price": 1000}, headers=_auth(token))
        assert resp.status_code == 404
