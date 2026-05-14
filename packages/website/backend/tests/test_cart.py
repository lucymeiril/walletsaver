"""장바구니 API 테스트 — 추가/삭제/병합/중복 처리/제한"""
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
    from api.routes.cart import router as cart_router
    from api.routes.auth import router as auth_router
    from api.middleware.rate_limit import limiter
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(auth_router)
    app.include_router(cart_router)
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
        "email": "cart@test.com", "password": "TestPass1", "nickname": "장바구니유저"
    })
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestCartAdd:
    def test_add_item(self, client):
        token = _register(client)
        resp = client.post("/api/cart", json={
            "item_name": "삼겹살 1kg", "item_price": 15000, "store_name": "이마트"
        }, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["item_name"] == "삼겹살 1kg"
        assert data["quantity"] == 1

    def test_add_requires_name(self, client):
        token = _register(client)
        resp = client.post("/api/cart", json={
            "item_price": 1000
        }, headers=_auth(token))
        assert resp.status_code == 400

    def test_add_requires_positive_price(self, client):
        token = _register(client)
        resp = client.post("/api/cart", json={
            "item_name": "테스트", "item_price": 0
        }, headers=_auth(token))
        assert resp.status_code == 400

    def test_add_unauthenticated(self, client):
        resp = client.post("/api/cart", json={
            "item_name": "테스트", "item_price": 1000
        })
        assert resp.status_code == 401


class TestCartDuplicate:
    def test_duplicate_increments_quantity(self, client):
        token = _register(client)
        headers = _auth(token)
        # 상품 직접 생성해서 product_id 사용
        from services.db import managed_session
        from storage.models import Product
        with managed_session() as session:
            p = Product(name="테스트상품", unit="개")
            session.add(p)
            session.flush()
            pid = p.id

        client.post("/api/cart", json={
            "product_id": pid, "item_name": "테스트상품", "item_price": 5000, "store_name": "마트A"
        }, headers=headers)

        resp = client.post("/api/cart", json={
            "product_id": pid, "item_name": "테스트상품", "item_price": 5000, "store_name": "마트A"
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["quantity"] == 2


class TestCartCRUD:
    def test_list_cart(self, client):
        token = _register(client)
        headers = _auth(token)
        client.post("/api/cart", json={"item_name": "A", "item_price": 1000}, headers=headers)
        client.post("/api/cart", json={"item_name": "B", "item_price": 2000}, headers=headers)
        resp = client.get("/api/cart", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_update_quantity(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/cart", json={"item_name": "A", "item_price": 1000}, headers=headers)
        item_id = add_resp.json()["data"]["id"]

        resp = client.put(f"/api/cart/{item_id}", json={"quantity": 5}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["quantity"] == 5

    def test_update_quantity_invalid(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/cart", json={"item_name": "A", "item_price": 1000}, headers=headers)
        item_id = add_resp.json()["data"]["id"]
        resp = client.put(f"/api/cart/{item_id}", json={"quantity": 0}, headers=headers)
        assert resp.status_code == 400

    def test_remove_item(self, client):
        token = _register(client)
        headers = _auth(token)
        add_resp = client.post("/api/cart", json={"item_name": "A", "item_price": 1000}, headers=headers)
        item_id = add_resp.json()["data"]["id"]

        resp = client.delete(f"/api/cart/{item_id}", headers=headers)
        assert resp.status_code == 200

        list_resp = client.get("/api/cart", headers=headers)
        assert len(list_resp.json()["data"]) == 0

    def test_remove_nonexistent(self, client):
        token = _register(client)
        resp = client.delete("/api/cart/99999", headers=_auth(token))
        assert resp.status_code == 404

    def test_clear_cart(self, client):
        token = _register(client)
        headers = _auth(token)
        client.post("/api/cart", json={"item_name": "A", "item_price": 1000}, headers=headers)
        client.post("/api/cart", json={"item_name": "B", "item_price": 2000}, headers=headers)

        resp = client.delete("/api/cart", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted_count"] == 2


class TestCartMerge:
    def test_merge_items(self, client):
        token = _register(client)
        headers = _auth(token)
        resp = client.post("/api/cart/merge", json={
            "items": [
                {"item_name": "A", "item_price": 1000, "quantity": 2},
                {"item_name": "B", "item_price": 3000},
            ]
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["merged"] == 2

        list_resp = client.get("/api/cart", headers=headers)
        assert len(list_resp.json()["data"]) == 2

    def test_merge_skips_invalid(self, client):
        token = _register(client)
        headers = _auth(token)
        resp = client.post("/api/cart/merge", json={
            "items": [
                {"item_name": "", "item_price": 0},
                {"item_name": "Valid", "item_price": 1000},
            ]
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["skipped"] == 1
        assert resp.json()["data"]["merged"] == 1


class TestCartLimit:
    def test_max_items_limit(self, client):
        token = _register(client)
        headers = _auth(token)
        # 장바구니 100개 직접 생성
        from services.db import managed_session
        from storage.models import CartItem
        with managed_session() as session:
            for i in range(100):
                session.add(CartItem(
                    user_id=1, item_name=f"item_{i}", item_price=1000, quantity=1
                ))

        resp = client.post("/api/cart", json={
            "item_name": "초과 아이템", "item_price": 1000
        }, headers=headers)
        assert resp.status_code == 400
        assert "100" in resp.json()["detail"]
