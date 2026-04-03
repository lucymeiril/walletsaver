"""Website API 종합 라우트 테스트"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api.app import create_app
from services.auth_service import create_token_pair


@pytest.fixture(autouse=True)
def reset_community_state():
    """각 테스트 전에 커뮤니티 인메모리 상태 리셋."""
    import api.routes.community as cm
    cm._initialized = False
    cm._posts_db = []
    cm._comments_db = {}
    cm._votes_db = {}
    cm._next_post_id = 100
    cm._next_comment_id = 100
    yield


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """인증된 사용자의 헤더."""
    tokens = create_token_pair(1, "test@example.com", "user")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin_headers():
    """관리자 헤더."""
    tokens = create_token_pair(99, "admin@example.com", "admin")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ── Health ───────────────────────────────────────────────────────

class TestHealth:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ── Products ─────────────────────────────────────────────────────

class TestProducts:
    def test_search_all(self, client):
        resp = client.get("/api/products/search")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        assert body["meta"] is not None
        assert body["meta"]["total"] > 0

    def test_search_with_query(self, client):
        resp = client.get("/api/products/search?q=삼겹살")
        body = resp.json()
        assert body["success"] is True
        assert any("삼겹살" in p["name"] for p in body["data"])

    def test_search_pagination(self, client):
        resp = client.get("/api/products/search?per_page=3&page=1")
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) <= 3
        assert body["meta"]["page"] == 1
        assert body["meta"]["per_page"] == 3
        assert body["meta"]["total_pages"] > 0

    def test_get_product(self, client):
        resp = client.get("/api/products/1")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == 1

    def test_get_product_not_found(self, client):
        resp = client.get("/api/products/99999")
        assert resp.status_code == 404

    def test_price_history(self, client):
        resp = client.get("/api/products/1/price-history?days=7")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        assert "date" in body["data"][0]
        assert "price" in body["data"][0]
        assert "source" in body["data"][0]

    def test_price_history_not_found(self, client):
        resp = client.get("/api/products/99999/price-history")
        assert resp.status_code == 404

    def test_price_compare(self, client):
        resp = client.get("/api/products/1/price-compare")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        assert "source" in body["data"][0]
        assert "price" in body["data"][0]

    def test_price_compare_not_found(self, client):
        resp = client.get("/api/products/99999/price-compare")
        assert resp.status_code == 404


# ── Hotdeals ─────────────────────────────────────────────────────

class TestHotdeals:
    def test_list_hotdeals(self, client):
        resp = client.get("/api/hotdeals")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        assert body["meta"]["total"] > 0

    def test_list_hotdeals_filter_category(self, client):
        resp = client.get("/api/hotdeals?category=food")
        body = resp.json()
        assert body["success"] is True
        for h in body["data"]:
            assert h["cat"] == "food"

    def test_list_hotdeals_sort_popular(self, client):
        resp = client.get("/api/hotdeals?sort=popular")
        body = resp.json()
        assert body["success"] is True
        views = [h["views"] for h in body["data"]]
        assert views == sorted(views, reverse=True)

    def test_list_hotdeals_pagination(self, client):
        resp = client.get("/api/hotdeals?per_page=5&page=1")
        body = resp.json()
        assert len(body["data"]) <= 5

    def test_get_hotdeal(self, client):
        resp = client.get("/api/hotdeals/1")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == 1

    def test_get_hotdeal_not_found(self, client):
        resp = client.get("/api/hotdeals/99999")
        assert resp.status_code == 404


# ── Marts ────────────────────────────────────────────────────────

class TestMarts:
    def test_list_marts(self, client):
        resp = client.get("/api/marts")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) == 4
        names = [m["name"] for m in body["data"]]
        assert "이마트" in names

    def test_get_mart_promotions(self, client):
        resp = client.get("/api/marts/emart/promotions")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["name"] == "이마트"
        assert "items" in body["data"]
        assert len(body["data"]["items"]) > 0

    def test_get_mart_promotions_not_found(self, client):
        resp = client.get("/api/marts/unknown/promotions")
        assert resp.status_code == 404


# ── Gas ──────────────────────────────────────────────────────────

class TestGas:
    def test_nearby_gas_stations(self, client):
        resp = client.get("/api/gas/nearby?lat=37.5&lng=127.04")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        for s in body["data"]:
            assert "distance" in s

    def test_nearby_gas_sort_price(self, client):
        resp = client.get("/api/gas/nearby?sort=price_asc&fuel_type=gasoline")
        body = resp.json()
        prices = [s["gasoline"] for s in body["data"] if s["gasoline"] is not None]
        assert prices == sorted(prices)

    def test_nearby_gas_sort_distance(self, client):
        resp = client.get("/api/gas/nearby?sort=distance")
        body = resp.json()
        distances = [s["distance"] for s in body["data"]]
        assert distances == sorted(distances)


# ── Community ────────────────────────────────────────────────────

class TestCommunity:
    def test_list_posts(self, client):
        resp = client.get("/api/posts")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert body["meta"]["total"] > 0

    def test_list_posts_filter_type(self, client):
        resp = client.get("/api/posts?post_type=hotdeal")
        body = resp.json()
        for p in body["data"]:
            assert p["post_type"] == "hotdeal"

    def test_create_post_requires_auth(self, client):
        resp = client.post("/api/posts", json={
            "title": "테스트", "content": "내용", "post_type": "free"
        })
        assert resp.status_code == 401

    def test_create_post(self, client, auth_headers):
        resp = client.post("/api/posts", json={
            "title": "새 게시글",
            "content": "테스트 내용입니다",
            "post_type": "free",
            "category": "food",
        }, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["title"] == "새 게시글"
        assert body["data"]["author_id"] == 1

    def test_get_post_increments_views(self, client):
        # Get initial views
        resp1 = client.get("/api/posts/1")
        views1 = resp1.json()["data"]["views"]
        # Get again
        resp2 = client.get("/api/posts/1")
        views2 = resp2.json()["data"]["views"]
        assert views2 == views1 + 1

    def test_get_post_not_found(self, client):
        resp = client.get("/api/posts/99999")
        assert resp.status_code == 404

    def test_update_post_author_only(self, client, auth_headers):
        # Create a post first
        create_resp = client.post("/api/posts", json={
            "title": "수정 테스트", "content": "원본 내용", "post_type": "free"
        }, headers=auth_headers)
        post_id = create_resp.json()["data"]["id"]

        # Update
        resp = client.put(f"/api/posts/{post_id}", json={
            "title": "수정된 제목"
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "수정된 제목"

    def test_update_post_forbidden(self, client, admin_headers):
        """다른 사용자가 수정 시도 → 403."""
        # Post ID 1 is authored by user 1, admin is user 99
        resp = client.put("/api/posts/1", json={
            "title": "해킹!"
        }, headers=admin_headers)
        assert resp.status_code == 403

    def test_delete_post_author(self, client, auth_headers):
        create_resp = client.post("/api/posts", json={
            "title": "삭제 테스트", "content": "삭제할 글", "post_type": "free"
        }, headers=auth_headers)
        post_id = create_resp.json()["data"]["id"]
        resp = client.delete(f"/api/posts/{post_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "deleted"

    def test_delete_post_admin(self, client, admin_headers):
        """관리자는 다른 사람의 글도 삭제 가능."""
        resp = client.delete("/api/posts/1", headers=admin_headers)
        assert resp.status_code == 200

    def test_delete_post_forbidden(self, client):
        """다른 일반 유저가 삭제 시도 → 403."""
        other_tokens = create_token_pair(999, "other@example.com", "user")
        headers = {"Authorization": f"Bearer {other_tokens['access_token']}"}
        resp = client.delete("/api/posts/1", headers=headers)
        assert resp.status_code == 403

    def test_create_comment(self, client, auth_headers):
        resp = client.post("/api/posts/1/comments", json={
            "content": "테스트 댓글"
        }, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["content"] == "테스트 댓글"

    def test_create_comment_requires_auth(self, client):
        resp = client.post("/api/posts/1/comments", json={
            "content": "댓글"
        })
        assert resp.status_code == 401

    def test_list_comments(self, client):
        resp = client.get("/api/posts/1/comments")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_vote_post(self, client, auth_headers):
        resp = client.post("/api/posts/1/vote", json={
            "vote_type": "hot"
        }, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["user_vote"] == "hot"
        assert body["data"]["hot_votes"] > 0

    def test_vote_toggle(self, client, auth_headers):
        """같은 투표 두 번 → 취소."""
        client.post("/api/posts/1/vote", json={"vote_type": "hot"}, headers=auth_headers)
        resp = client.post("/api/posts/1/vote", json={"vote_type": "hot"}, headers=auth_headers)
        body = resp.json()
        assert body["data"]["user_vote"] is None

    def test_vote_requires_auth(self, client):
        resp = client.post("/api/posts/1/vote", json={"vote_type": "hot"})
        assert resp.status_code == 401

    def test_vote_invalid_type(self, client, auth_headers):
        resp = client.post("/api/posts/1/vote", json={"vote_type": "invalid"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_suggested_tier(self, client):
        resp = client.get("/api/posts/1/suggested-tier")
        body = resp.json()
        assert body["success"] is True
        assert "suggested_tier" in body["data"]

    def test_community_crud_flow(self, client, auth_headers):
        """CRUD 전체 흐름: 작성 → 조회 → 댓글 → 투표 → 삭제."""
        # Create
        r1 = client.post("/api/posts", json={
            "title": "흐름 테스트",
            "content": "CRUD 테스트",
            "post_type": "hotdeal",
            "price": 10000,
            "original_price": 20000,
        }, headers=auth_headers)
        assert r1.status_code == 200
        post_id = r1.json()["data"]["id"]

        # Read
        r2 = client.get(f"/api/posts/{post_id}")
        assert r2.json()["data"]["title"] == "흐름 테스트"

        # Comment
        r3 = client.post(f"/api/posts/{post_id}/comments", json={
            "content": "좋은 정보!"
        }, headers=auth_headers)
        assert r3.status_code == 200

        # Vote
        r4 = client.post(f"/api/posts/{post_id}/vote", json={
            "vote_type": "hot"
        }, headers=auth_headers)
        assert r4.json()["data"]["hot_votes"] > 0

        # Suggested tier
        r5 = client.get(f"/api/posts/{post_id}/suggested-tier")
        assert r5.json()["data"]["suggested_tier"] in ("ultra", "great", "good", "wait", "unknown")

        # Delete
        r6 = client.delete(f"/api/posts/{post_id}", headers=auth_headers)
        assert r6.status_code == 200

        # Verify deleted
        r7 = client.get(f"/api/posts/{post_id}")
        assert r7.status_code == 404


# ── Search ───────────────────────────────────────────────────────

class TestSearch:
    def test_search_all(self, client):
        resp = client.get("/api/search?q=삼겹살")
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) > 0
        assert body["meta"]["total"] > 0

    def test_search_by_type(self, client):
        resp = client.get("/api/search?q=삼겹살&type=product")
        body = resp.json()
        for item in body["data"]:
            assert item["type"] == "product"

    def test_search_pagination(self, client):
        resp = client.get("/api/search?per_page=2&page=1")
        body = resp.json()
        assert len(body["data"]) <= 2

    def test_autocomplete(self, client):
        resp = client.get("/api/search/autocomplete?q=삼")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_autocomplete_empty(self, client):
        resp = client.get("/api/search/autocomplete?q=")
        body = resp.json()
        assert body["data"] == []


# ── Restaurants ──────────────────────────────────────────────────

class TestRestaurants:
    def test_nearby_restaurants(self, client):
        resp = client.get("/api/restaurants/nearby?lat=37.5&lng=127.04")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        for r in body["data"]:
            assert "distance" in r

    def test_nearby_restaurants_category_filter(self, client):
        resp = client.get("/api/restaurants/nearby?category=한식")
        body = resp.json()
        for r in body["data"]:
            assert r["category"] == "한식"

    def test_recipes_compare(self, client):
        resp = client.get("/api/recipes/compare")
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0
        for recipe in body["data"]:
            assert "recipe_name" in recipe
            assert "cook_cost" in recipe
            assert "delivery_cost" in recipe
            assert "savings_vs_delivery" in recipe


# ── Users (Auth-required) ───────────────────────────────────────

class TestUsers:
    def test_get_profile_requires_auth(self, client):
        resp = client.get("/api/users/me")
        assert resp.status_code == 401

    def test_get_profile(self, client, auth_headers):
        resp = client.get("/api/users/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == 1
        assert body["data"]["email"] == "test@example.com"

    def test_update_profile(self, client, auth_headers):
        resp = client.put("/api/users/me", json={
            "nickname": "새닉네임"
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["nickname"] == "새닉네임"

    def test_get_favorites(self, client, auth_headers):
        resp = client.get("/api/users/me/favorites", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_add_favorite(self, client, auth_headers):
        resp = client.post("/api/users/me/favorites", json={
            "product_id": 5
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["product_id"] == 5

    def test_remove_favorite(self, client, auth_headers):
        resp = client.delete("/api/users/me/favorites/1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "removed"

    def test_get_alerts(self, client, auth_headers):
        resp = client.get("/api/users/me/alerts", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_create_alert(self, client, auth_headers):
        resp = client.post("/api/users/me/alerts", json={
            "product_id": 2,
            "target_price": 1500,
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["target_price"] == 1500


# ── Response Format ──────────────────────────────────────────────

class TestResponseFormat:
    """모든 엔드포인트가 ApiResponse 형식을 반환하는지 확인."""

    def _check_api_response(self, resp):
        body = resp.json()
        assert "success" in body
        assert "data" in body

    def test_products_format(self, client):
        self._check_api_response(client.get("/api/products/search"))
        self._check_api_response(client.get("/api/products/1"))
        self._check_api_response(client.get("/api/products/1/price-history"))
        self._check_api_response(client.get("/api/products/1/price-compare"))

    def test_hotdeals_format(self, client):
        self._check_api_response(client.get("/api/hotdeals"))
        self._check_api_response(client.get("/api/hotdeals/1"))

    def test_marts_format(self, client):
        self._check_api_response(client.get("/api/marts"))
        self._check_api_response(client.get("/api/marts/emart/promotions"))

    def test_gas_format(self, client):
        self._check_api_response(client.get("/api/gas/nearby"))

    def test_community_format(self, client):
        self._check_api_response(client.get("/api/posts"))
        self._check_api_response(client.get("/api/posts/1"))
        self._check_api_response(client.get("/api/posts/1/comments"))

    def test_search_format(self, client):
        self._check_api_response(client.get("/api/search?q=test"))
        self._check_api_response(client.get("/api/search/autocomplete?q=삼"))

    def test_restaurants_format(self, client):
        self._check_api_response(client.get("/api/restaurants/nearby"))
        self._check_api_response(client.get("/api/recipes/compare"))
