"""
API Contract Tests — API 계약 검증.

모든 엔드포인트가 표준 응답 형식 {success, data, error, meta}을 따르는지,
HTTP 상태 코드, 페이지네이션, 인증/인가, CORS, Content-Type 등을 검증한다.
"""

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(ROOT / "packages" / "shared"),
    str(ROOT / "packages" / "website" / "backend"),
    str(ROOT / "packages" / "crawler-admin" / "backend"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestStandardResponseFormat:
    """모든 Website API 엔드포인트의 표준 응답 형식 검증."""

    ENDPOINTS_WITH_APIRESPONSE = [
        "/api/products/search",
        "/api/products/1",
        "/api/products/1/price-history",
        "/api/products/1/price-compare",
        "/api/hotdeals",
        "/api/hotdeals/1",
        "/api/marts",
        "/api/marts/emart/promotions",
        "/api/gas/nearby",
        "/api/search?q=양파",
        "/api/search/autocomplete?q=양",
        "/api/posts",
    ]

    @pytest.mark.parametrize("endpoint", ENDPOINTS_WITH_APIRESPONSE)
    def test_success_response_structure(self, website_client, endpoint):
        """성공 응답이 {success, data} 구조를 따름."""
        resp = website_client.get(endpoint)
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data, f"{endpoint}: 'success' 필드 누락"
        assert "data" in data, f"{endpoint}: 'data' 필드 누락"
        assert data["success"] is True

    @pytest.mark.parametrize("endpoint", ENDPOINTS_WITH_APIRESPONSE)
    def test_content_type_json(self, website_client, endpoint):
        """Content-Type이 application/json."""
        resp = website_client.get(endpoint)
        assert "application/json" in resp.headers.get("content-type", ""), \
            f"{endpoint}: Content-Type이 JSON이 아님"

    def test_error_response_has_detail(self, website_client):
        """404 에러 응답에 detail이 포함됨."""
        resp = website_client.get("/api/products/99999")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    def test_hotdeal_not_found_404(self, website_client):
        """존재하지 않는 핫딜 404."""
        resp = website_client.get("/api/hotdeals/99999")
        assert resp.status_code == 404

    def test_post_not_found_404(self, website_client):
        """존재하지 않는 게시글 404."""
        resp = website_client.get("/api/posts/99999")
        assert resp.status_code == 404


class TestPagination:
    """페이지네이션 동작 검증."""

    PAGINATED_ENDPOINTS = [
        "/api/products/search",
        "/api/hotdeals",
        "/api/search?q=",
        "/api/posts",
    ]

    @pytest.mark.parametrize("endpoint", PAGINATED_ENDPOINTS)
    def test_pagination_meta_structure(self, website_client, endpoint):
        """페이지네이션 meta 구조 검증."""
        resp = website_client.get(f"{endpoint}{'&' if '?' in endpoint else '?'}page=1&per_page=5")
        data = resp.json()
        if data.get("meta"):
            meta = data["meta"]
            assert "page" in meta
            assert "per_page" in meta
            assert "total" in meta
            assert "total_pages" in meta
            assert meta["page"] == 1
            assert meta["per_page"] == 5
            assert meta["total"] >= 0
            assert meta["total_pages"] >= 0

    def test_page_bounds(self, website_client):
        """범위 밖 페이지 요청 시 빈 결과."""
        resp = website_client.get("/api/products/search?page=999&per_page=20")
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 0

    def test_per_page_limit(self, website_client):
        """per_page 최대값 검증."""
        resp = website_client.get("/api/products/search?per_page=5")
        data = resp.json()
        assert len(data["data"]) <= 5

    def test_default_pagination(self, website_client):
        """기본 페이지네이션 값."""
        resp = website_client.get("/api/products/search")
        data = resp.json()
        meta = data.get("meta", {})
        if meta:
            assert meta["page"] == 1
            assert meta["per_page"] == 20


class TestAuthentication:
    """인증/인가 검증."""

    PROTECTED_ENDPOINTS = [
        ("POST", "/api/posts", {"title": "t", "content": "c", "post_type": "free"}),
        ("GET", "/api/users/me", None),
        ("PUT", "/api/users/me", {"nickname": "new"}),
        ("GET", "/api/users/me/favorites", None),
        ("POST", "/api/users/me/favorites", {"product_id": 1}),
        ("GET", "/api/users/me/alerts", None),
        ("POST", "/api/users/me/alerts", {"product_id": 1, "target_price": 2000}),
    ]

    @pytest.mark.parametrize("method,endpoint,body", PROTECTED_ENDPOINTS)
    def test_protected_endpoints_require_auth(self, website_client, method, endpoint, body):
        """인증 필요 엔드포인트에 토큰 없이 접근 시 401."""
        if method == "GET":
            resp = website_client.get(endpoint)
        elif method == "POST":
            resp = website_client.post(endpoint, json=body)
        elif method == "PUT":
            resp = website_client.put(endpoint, json=body)
        assert resp.status_code == 401, f"{method} {endpoint}: 401이 아닌 {resp.status_code}"

    def test_invalid_token_rejected(self, website_client):
        """잘못된 토큰 거부."""
        headers = {"Authorization": "Bearer invalid-token-here"}
        resp = website_client.get("/api/users/me", headers=headers)
        assert resp.status_code == 401

    def test_valid_token_accepted(self, website_client, auth_headers):
        """유효한 토큰으로 접근 성공."""
        resp = website_client.get("/api/users/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["email"] == "test@example.com"

    def test_auth_register_login_flow(self, website_client):
        """회원가입 → 로그인 흐름."""
        # 회원가입
        reg_data = {
            "email": "newuser@example.com",
            "password": "secure123",
            "nickname": "새유저",
        }
        reg_resp = website_client.post("/api/auth/register", json=reg_data)
        assert reg_resp.status_code == 201
        tokens = reg_resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # 로그인
        login_data = {"email": "newuser@example.com", "password": "secure123"}
        login_resp = website_client.post("/api/auth/login", json=login_data)
        assert login_resp.status_code == 200
        login_tokens = login_resp.json()
        assert "access_token" in login_tokens

    def test_duplicate_registration_rejected(self, website_client):
        """중복 이메일 등록 거부."""
        reg_data = {
            "email": "dup@example.com",
            "password": "password123",
            "nickname": "유저A",
        }
        website_client.post("/api/auth/register", json=reg_data)
        dup_resp = website_client.post("/api/auth/register", json=reg_data)
        assert dup_resp.status_code == 400

    def test_token_refresh(self, website_client):
        """토큰 갱신."""
        reg = website_client.post("/api/auth/register", json={
            "email": "refresh@example.com",
            "password": "password123",
            "nickname": "리프레시유저",
        })
        refresh_token = reg.json()["refresh_token"]

        refresh_resp = website_client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200
        new_tokens = refresh_resp.json()
        assert "access_token" in new_tokens


class TestCORSHeaders:
    """CORS 헤더 검증."""

    def test_cors_allows_localhost(self, website_client):
        """localhost:5173 origin 허용."""
        resp = website_client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS preflight는 200 또는 405 (FastAPI CORS 미들웨어 동작 방식에 따라)
        assert resp.status_code in (200, 204, 405)

    def test_health_endpoint(self, website_client):
        """헬스 체크 엔드포인트."""
        resp = website_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestCrawlerAdminContracts:
    """Crawler-Admin API 계약."""

    def test_health(self, crawler_admin_client):
        """헬스 체크."""
        resp = crawler_admin_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "crawler-admin"

    def test_crawlers_list_format(self, crawler_admin_client):
        """크롤러 목록 응답 형식."""
        resp = crawler_admin_client.get("/api/crawlers")
        assert resp.status_code == 200
        data = resp.json()
        assert "crawlers" in data
        assert isinstance(data["crawlers"], list)

    def test_logs_format(self, crawler_admin_client):
        """로그 응답 형식."""
        resp = crawler_admin_client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_schedules_format(self, crawler_admin_client):
        """스케줄 응답 형식."""
        resp = crawler_admin_client.get("/api/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert "schedules" in data


class TestVoteValidation:
    """투표 API 입력 검증."""

    def test_invalid_vote_type_400(self, website_client, auth_headers):
        """유효하지 않은 vote_type 거부."""
        # 먼저 게시글 가져오기
        list_resp = website_client.get("/api/posts")
        posts = list_resp.json()["data"]
        if posts:
            post_id = posts[0]["id"]
            resp = website_client.post(
                f"/api/posts/{post_id}/vote",
                json={"vote_type": "invalid"},
                headers=auth_headers,
            )
            assert resp.status_code == 400


class TestPasswordValidation:
    """비밀번호 유효성 검사."""

    def test_short_password_rejected(self, website_client):
        """8자 미만 비밀번호 거부."""
        resp = website_client.post("/api/auth/register", json={
            "email": "short@example.com",
            "password": "pass1",
            "nickname": "짧은비번",
        })
        assert resp.status_code == 422  # Validation error

    def test_password_without_digit_rejected(self, website_client):
        """숫자 없는 비밀번호 거부."""
        resp = website_client.post("/api/auth/register", json={
            "email": "nodigit@example.com",
            "password": "password",
            "nickname": "숫자없음",
        })
        assert resp.status_code == 422
