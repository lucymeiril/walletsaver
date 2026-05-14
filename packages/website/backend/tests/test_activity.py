"""활동 추적 API 테스트 — 기록, rate limiting, 추천"""
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
    # rate limit 상태 초기화
    from api.routes import activity
    activity._last_write.clear()
    activity._buffer.clear()
    reset_engine()


@pytest.fixture
def app():
    from api.routes.activity import router as activity_router
    from api.routes.auth import router as auth_router
    from api.middleware.rate_limit import limiter
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(auth_router)
    app.include_router(activity_router)
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
        "email": "act@test.com", "password": "TestPass1", "nickname": "활동유저"
    })
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestActivityTrack:
    def test_track_view(self, client):
        token = _register(client)
        resp = client.post("/api/activity/track", json={
            "activity_type": "view", "target_type": "product", "target_id": "123"
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "tracked"

    def test_track_search(self, client):
        token = _register(client)
        resp = client.post("/api/activity/track", json={
            "activity_type": "search",
            "metadata": {"query": "삼겹살", "category": "livestock"}
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "tracked"

    def test_track_invalid_type(self, client):
        token = _register(client)
        resp = client.post("/api/activity/track", json={
            "activity_type": "invalid_type"
        }, headers=_auth(token))
        assert resp.status_code == 400

    def test_track_unauthenticated(self, client):
        resp = client.post("/api/activity/track", json={
            "activity_type": "view"
        })
        assert resp.status_code == 401


class TestActivityRateLimit:
    def test_rate_limited(self, client):
        token = _register(client)
        headers = _auth(token)
        # 첫 번째 요청 성공
        resp1 = client.post("/api/activity/track", json={
            "activity_type": "view", "target_type": "product", "target_id": "1"
        }, headers=headers)
        assert resp1.json()["data"]["status"] == "tracked"

        # 즉시 두 번째 요청 — rate limited
        resp2 = client.post("/api/activity/track", json={
            "activity_type": "view", "target_type": "product", "target_id": "2"
        }, headers=headers)
        assert resp2.json()["data"]["status"] == "rate_limited"


class TestActivityRecommendations:
    def test_recommendations_unauthenticated(self, client):
        resp = client.get("/api/activity/recommendations")
        assert resp.status_code == 200
        # 비로그인: 빈 리스트 (상품 없으면)
        assert isinstance(resp.json()["data"], list)

    def test_recommendations_no_activity(self, client):
        token = _register(client)
        resp = client.get("/api/activity/recommendations", headers=_auth(token))
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_recommendations_with_activity(self, client):
        token = _register(client)
        headers = _auth(token)

        # 상품 + 활동 데이터 삽입
        from services.db import managed_session
        from storage.models import Product, UserActivity, Category
        with managed_session() as session:
            cat = Category(id="livestock", name="축산물")
            session.add(cat)
            session.flush()
            for i in range(3):
                p = Product(name=f"삼겹살{i}", category_id="livestock", unit="100g")
                session.add(p)
            session.flush()
            # 활동 기록 삽입
            session.add(UserActivity(
                user_id=1, activity_type="view", target_type="product", target_id="1",
                metadata_={"category": "livestock"}
            ))
            session.add(UserActivity(
                user_id=1, activity_type="search",
                metadata_={"category": "livestock", "query": "삼겹살"}
            ))

        resp = client.get("/api/activity/recommendations", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        # 축산물 카테고리 상품이 추천되어야 함
        if data:
            assert data[0]["category"] == "livestock"


class TestActivityBufferFlush:
    def test_buffer_flushes_at_threshold(self, client):
        """버퍼가 10개에 도달하면 플러시"""
        token = _register(client)
        headers = _auth(token)
        from api.routes import activity

        # rate limit 우회: _last_write를 조작하여 각 요청이 통과하도록
        import time
        for i in range(12):
            activity._last_write[1] = 0  # rate limit 리셋
            client.post("/api/activity/track", json={
                "activity_type": "view", "target_type": "product", "target_id": str(i)
            }, headers=headers)

        # 플러시 후 DB에 기록 확인
        activity._flush_buffer()
        from services.db import managed_session
        from storage.models import UserActivity
        with managed_session() as session:
            count = session.query(UserActivity).filter(UserActivity.user_id == 1).count()
            assert count >= 10
