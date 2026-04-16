"""프로필 API 테스트 — CRUD, 소프트 삭제, 닉네임 검증"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.auth_service import create_token_pair


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
    from api.routes.profile import router as profile_router
    from api.routes.auth import router as auth_router
    from api.middleware.rate_limit import limiter
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(auth_router)
    app.include_router(profile_router)
    try:
        limiter.reset()
    except Exception:
        pass
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _register_and_get_token(client) -> str:
    resp = client.post("/api/auth/register", json={
        "email": "profile@test.com", "password": "TestPass1", "nickname": "프로필유저"
    })
    assert resp.status_code == 201
    return resp.json()["access_token"]


class TestProfileGet:
    def test_get_profile_authenticated(self, client):
        token = _register_and_get_token(client)
        resp = client.get("/api/profile", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["email"] == "profile@test.com"
        assert data["nickname"] == "프로필유저"

    def test_get_profile_unauthenticated(self, client):
        resp = client.get("/api/profile")
        assert resp.status_code == 401


class TestProfileUpdate:
    def test_update_nickname(self, client):
        token = _register_and_get_token(client)
        resp = client.put("/api/profile",
                          json={"nickname": "새닉네임"},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["nickname"] == "새닉네임"

    def test_update_bio(self, client):
        token = _register_and_get_token(client)
        resp = client.put("/api/profile",
                          json={"bio": "안녕하세요!"},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["bio"] == "안녕하세요!"

    def test_update_preferences(self, client):
        token = _register_and_get_token(client)
        resp = client.put("/api/profile",
                          json={"preferences": {"theme": "dark"}},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["preferences"]["theme"] == "dark"

    def test_nickname_too_short(self, client):
        token = _register_and_get_token(client)
        resp = client.put("/api/profile",
                          json={"nickname": "X"},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    def test_nickname_too_long(self, client):
        token = _register_and_get_token(client)
        resp = client.put("/api/profile",
                          json={"nickname": "A" * 21},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    def test_nickname_uniqueness(self, client):
        _register_and_get_token(client)
        # 두 번째 사용자 등록
        resp2 = client.post("/api/auth/register", json={
            "email": "other@test.com", "password": "TestPass1", "nickname": "다른유저"
        })
        token2 = resp2.json()["access_token"]
        # 첫 번째 사용자 닉네임으로 변경 시도
        resp = client.put("/api/profile",
                          json={"nickname": "프로필유저"},
                          headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 400
        assert "닉네임" in resp.json()["detail"]


class TestProfileDelete:
    def test_soft_delete(self, client):
        token = _register_and_get_token(client)
        resp = client.delete("/api/profile", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert "삭제" in resp.json()["data"]["message"]

        # 삭제 후 프로필 조회 실패
        resp = client.get("/api/profile", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_double_delete(self, client):
        token = _register_and_get_token(client)
        client.delete("/api/profile", headers={"Authorization": f"Bearer {token}"})
        resp = client.delete("/api/profile", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404


class TestProfileActivity:
    def test_activity_empty(self, client):
        token = _register_and_get_token(client)
        resp = client.get("/api/profile/activity", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert resp.json()["meta"]["total"] == 0

    def test_activity_pagination(self, client):
        token = _register_and_get_token(client)
        # 활동 데이터 직접 삽입
        from services.db import managed_session
        from storage.models import UserActivity
        with managed_session() as session:
            for i in range(5):
                session.add(UserActivity(user_id=1, activity_type="view", target_type="product", target_id=str(i)))

        resp = client.get("/api/profile/activity?page=1&per_page=2",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2
        assert resp.json()["meta"]["total"] == 5
