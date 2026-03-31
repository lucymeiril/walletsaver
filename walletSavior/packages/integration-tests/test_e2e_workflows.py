"""
End-to-End Workflow Tests — 완전한 사용자 시나리오 검증.

실제 사용자 행동 패턴을 모사하여 전체 워크플로가 올바르게 동작하는지 테스트한다.
"""

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SHARED = ROOT / "packages" / "shared"
WEBSITE = ROOT / "packages" / "website" / "backend"
for p in [str(SHARED), str(WEBSITE)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.models import CrawlResult, CrawlStatus, DiscountItem, DataSource


class TestHotDealDiscoveryWorkflow:
    """핫딜 발견 워크플로: 검색 → 가격확인 → 마트비교 → 커뮤니티 → 투표."""

    def test_search_product(self, website_client):
        """Step 1: 상품 검색."""
        resp = website_client.get("/api/products/search?q=삼겹살")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        products = data["data"]
        assert any("삼겹살" in p["name"] for p in products)

    def test_view_prices(self, website_client):
        """Step 2: 상품 가격 확인."""
        resp = website_client.get("/api/products/2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        product = data["data"]
        assert product["name"] == "삼겹살"
        assert "cur" in product
        assert "avg" in product

    def test_compare_marts(self, website_client):
        """Step 3: 마트 가격 비교."""
        resp = website_client.get("/api/products/2/price-compare")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        compare = data["data"]
        assert isinstance(compare, list)
        if compare:
            prices = [c["price"] for c in compare]
            assert prices == sorted(prices), "가격이 오름차순으로 정렬되어야 함"

    def test_check_community_hotdeals(self, website_client):
        """Step 4: 커뮤니티 핫딜 확인."""
        resp = website_client.get("/api/hotdeals?category=food")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)

    def test_vote_on_hotdeal(self, website_client, auth_headers):
        """Step 5: 핫딜 투표."""
        # 게시글 목록 조회
        list_resp = website_client.get("/api/posts")
        posts = list_resp.json()["data"]

        if posts:
            post_id = posts[0]["id"]
            vote_resp = website_client.post(
                f"/api/posts/{post_id}/vote",
                json={"vote_type": "hot"},
                headers=auth_headers,
            )
            assert vote_resp.status_code == 200
            vote_data = vote_resp.json()
            assert vote_data["success"] is True
            assert vote_data["data"]["user_vote"] == "hot"

    def test_full_discovery_workflow(self, website_client, auth_headers):
        """전체 핫딜 발견 워크플로 통합 실행."""
        # 1. 검색
        search = website_client.get("/api/products/search?q=양파")
        assert search.status_code == 200
        products = search.json()["data"]
        assert len(products) > 0

        # 2. 상세 조회
        pid = products[0]["id"]
        detail = website_client.get(f"/api/products/{pid}")
        assert detail.status_code == 200

        # 3. 가격 비교
        compare = website_client.get(f"/api/products/{pid}/price-compare")
        assert compare.status_code == 200

        # 4. 핫딜 확인
        hotdeals = website_client.get("/api/hotdeals")
        assert hotdeals.status_code == 200

        # 5. 커뮤니티 확인
        posts = website_client.get("/api/posts")
        assert posts.status_code == 200


class TestCommunityPostingWorkflow:
    """커뮤니티 게시 워크플로: 작성 → 카테고리 → 가격제안 → 댓글 → 투표."""

    def test_create_post(self, website_client, auth_headers):
        """Step 1: 게시글 작성."""
        post_data = {
            "title": "이마트 삼겹살 특가!",
            "content": "삼겹살 100g에 1,100원입니다.",
            "post_type": "hotdeal",
            "category": "food",
            "price": 1100,
            "original_price": 1850,
            "url": "https://example.com/deal",
        }
        resp = website_client.post("/api/posts", json=post_data, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["title"] == post_data["title"]
        assert data["data"]["price"] == 1100
        return data["data"]["id"]

    def test_get_price_suggestion(self, website_client, auth_headers):
        """Step 2: 가격 제안 조회."""
        # 먼저 게시글 생성
        post_data = {
            "title": "테스트 핫딜",
            "content": "테스트 내용",
            "post_type": "hotdeal",
            "price": 1100,
            "original_price": 1850,
        }
        create_resp = website_client.post("/api/posts", json=post_data, headers=auth_headers)
        post_id = create_resp.json()["data"]["id"]

        # 가격 제안
        tier_resp = website_client.get(f"/api/posts/{post_id}/suggested-tier")
        assert tier_resp.status_code == 200
        tier_data = tier_resp.json()
        assert tier_data["success"] is True
        assert tier_data["data"]["suggested_tier"] in ("ultra", "great", "good", "wait", "unknown")
        assert tier_data["data"]["discount_rate"] is not None

    def test_add_comment(self, website_client, auth_headers):
        """Step 3: 댓글 작성."""
        # 게시글 생성
        post_resp = website_client.post(
            "/api/posts",
            json={"title": "댓글테스트", "content": "내용", "post_type": "free"},
            headers=auth_headers,
        )
        post_id = post_resp.json()["data"]["id"]

        # 댓글 작성
        comment_resp = website_client.post(
            f"/api/posts/{post_id}/comments",
            json={"content": "좋은 정보 감사합니다!"},
            headers=auth_headers,
        )
        assert comment_resp.status_code == 200
        comment = comment_resp.json()["data"]
        assert comment["content"] == "좋은 정보 감사합니다!"

    def test_vote_toggle(self, website_client, auth_headers):
        """Step 4: 투표 토글 (같은 투표 다시 클릭 → 취소)."""
        post_resp = website_client.post(
            "/api/posts",
            json={"title": "투표테스트", "content": "내용", "post_type": "hotdeal",
                   "price": 5000, "original_price": 10000},
            headers=auth_headers,
        )
        post_id = post_resp.json()["data"]["id"]

        # 첫 번째 투표 (hot)
        v1 = website_client.post(
            f"/api/posts/{post_id}/vote",
            json={"vote_type": "hot"},
            headers=auth_headers,
        )
        assert v1.json()["data"]["user_vote"] == "hot"
        hot_votes = v1.json()["data"]["hot_votes"]

        # 같은 투표 → 취소
        v2 = website_client.post(
            f"/api/posts/{post_id}/vote",
            json={"vote_type": "hot"},
            headers=auth_headers,
        )
        assert v2.json()["data"]["user_vote"] is None
        assert v2.json()["data"]["hot_votes"] == hot_votes - 1

    def test_full_community_workflow(self, website_client, auth_headers):
        """전체 커뮤니티 게시 워크플로."""
        # 1. 게시글 작성
        create = website_client.post(
            "/api/posts",
            json={
                "title": "코스트코 양파 특가",
                "content": "코스트코에서 양파 1.5kg 2,190원에 판매 중입니다.",
                "post_type": "hotdeal",
                "category": "food",
                "price": 2190,
                "original_price": 3500,
            },
            headers=auth_headers,
        )
        assert create.status_code == 200
        post = create.json()["data"]
        post_id = post["id"]

        # 2. 가격 제안
        tier = website_client.get(f"/api/posts/{post_id}/suggested-tier")
        assert tier.status_code == 200
        tier_info = tier.json()["data"]
        assert tier_info["suggested_tier"] in ("ultra", "great", "good", "wait")

        # 3. 댓글
        comment = website_client.post(
            f"/api/posts/{post_id}/comments",
            json={"content": "좋은 가격이네요!"},
            headers=auth_headers,
        )
        assert comment.status_code == 200

        # 4. 투표
        vote = website_client.post(
            f"/api/posts/{post_id}/vote",
            json={"vote_type": "hot"},
            headers=auth_headers,
        )
        assert vote.status_code == 200

        # 5. 조회수 증가 확인
        detail = website_client.get(f"/api/posts/{post_id}")
        assert detail.json()["data"]["views"] > 0


class TestPriceTrackingWorkflow:
    """가격 추적 워크플로: 검색 → 기준가 → 이력 → 알림 설정."""

    def test_search_and_view_baseline(self, website_client):
        """Step 1-2: 검색 후 기준가 확인."""
        resp = website_client.get("/api/products/search?q=양파")
        products = resp.json()["data"]
        assert len(products) > 0

        product = products[0]
        assert "avg" in product  # 평균가(기준가)
        assert "cur" in product  # 현재가
        assert "price_tier" in product

    def test_view_price_history(self, website_client):
        """Step 3: 가격 이력(차트) 조회."""
        resp = website_client.get("/api/products/1/price-history?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_set_price_alert(self, website_client, auth_headers):
        """Step 4: 가격 알림 설정."""
        resp = website_client.post(
            "/api/users/me/alerts",
            json={"product_id": 1, "target_price": 2000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["target_price"] == 2000
        assert data["data"]["status"] == "active"

    def test_view_favorites(self, website_client, auth_headers):
        """즐겨찾기 관리."""
        # 추가
        add_resp = website_client.post(
            "/api/users/me/favorites",
            json={"product_id": 1},
            headers=auth_headers,
        )
        assert add_resp.status_code == 200
        assert add_resp.json()["data"]["status"] == "added"

        # 목록 조회
        list_resp = website_client.get("/api/users/me/favorites", headers=auth_headers)
        assert list_resp.status_code == 200


class TestCrawlerAdminWorkflow:
    """크롤러 관리 워크플로: 목록 → 실행 → 로그 → 결과확인."""

    def test_view_crawlers(self, crawler_admin_client):
        """Step 1: 크롤러 목록 조회."""
        resp = crawler_admin_client.get("/api/crawlers")
        assert resp.status_code == 200
        data = resp.json()
        assert "crawlers" in data

    def test_run_crawler(self, crawler_admin_client):
        """Step 2: 크롤러 실행."""
        resp = crawler_admin_client.post("/api/crawlers/emart/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["crawler_id"] == "emart"
        assert data["status"] == "queued"

    def test_check_crawler_status(self, crawler_admin_client):
        """Step 3: 크롤러 상태 확인."""
        resp = crawler_admin_client.get("/api/crawlers/emart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["crawler_id"] == "emart"

    def test_view_logs(self, crawler_admin_client):
        """Step 4: 실행 로그 조회."""
        resp = crawler_admin_client.get("/api/logs?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "total" in data

    def test_schedule_management(self, crawler_admin_client):
        """스케줄 관리 (목록 조회)."""
        resp = crawler_admin_client.get("/api/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert "schedules" in data


class TestMartPromotionWorkflow:
    """마트 전단 워크플로: 마트목록 → 프로모션 조회."""

    def test_list_marts(self, website_client):
        """마트 목록."""
        resp = website_client.get("/api/marts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        marts = data["data"]
        assert len(marts) > 0
        mart_names = [m["name"] for m in marts]
        assert "이마트" in mart_names

    def test_mart_promotions(self, website_client):
        """마트별 프로모션 조회."""
        resp = website_client.get("/api/marts/emart/promotions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        promo_data = data["data"]
        assert "items" in promo_data
        assert len(promo_data["items"]) > 0

    def test_invalid_mart_404(self, website_client):
        """존재하지 않는 마트."""
        resp = website_client.get("/api/marts/nonexistent/promotions")
        assert resp.status_code == 404
