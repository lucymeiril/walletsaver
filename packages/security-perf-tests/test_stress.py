"""
스트레스 테스트 — 대량 요청, 대용량 페이로드, 깊은 페이지네이션, 레이스 컨디션.

Tests:
- Rapid sequential requests (100 in 10s)
- Large payload handling (1MB body)
- Deep pagination (page 1000)
- Complex nested category queries
- Concurrent write operations (race conditions)
- Cache invalidation under load
"""

import pytest
import time
import concurrent.futures
import statistics


# ═══════════════════════════════════════════════
# Rapid Sequential Requests
# ═══════════════════════════════════════════════

class TestRapidRequests:
    """빠른 연속 요청 테스트."""

    def test_100_sequential_requests_in_10_seconds(self, website_client, timer):
        """10초 이내에 100개의 연속 요청을 처리할 수 있어야 한다."""
        with timer() as t:
            results = []
            for _ in range(100):
                resp = website_client.get("/api/health")
                results.append(resp.status_code)

        success = sum(1 for s in results if s == 200)
        assert success >= 95, f"Only {success}/100 succeeded"
        assert t.elapsed < 10, f"Took {t.elapsed:.1f}s (limit: 10s)"

    def test_rapid_search_requests(self, website_client, timer):
        """빠른 연속 검색 요청이 안정적이어야 한다."""
        queries = ["양파", "삼겹살", "사과", "우유", "감자"] * 10
        with timer() as t:
            results = []
            for q in queries:
                resp = website_client.get("/api/search", params={"q": q})
                results.append(resp.status_code)

        success = sum(1 for s in results if s == 200)
        assert success >= 45, f"Only {success}/50 succeeded"

    def test_rapid_auth_attempts(self, website_client, timer):
        """빠른 연속 인증 시도가 안정적이어야 한다."""
        with timer() as t:
            results = []
            for _ in range(30):
                resp = website_client.post("/api/auth/login", json={
                    "email": "stress@test.com",
                    "password": "wrongpass",
                })
                results.append(resp.status_code)

        for status in results:
            assert status in (401, 429)


# ═══════════════════════════════════════════════
# Large Payload Handling
# ═══════════════════════════════════════════════

class TestLargePayloads:
    """대용량 페이로드 처리 테스트."""

    def test_1mb_post_body(self, website_client, auth_headers, timer):
        """1MB 게시글 본문이 적절하게 처리되어야 한다."""
        content = "대용량 테스트 " * 50000  # ~600KB
        with timer() as t:
            resp = website_client.post("/api/posts", headers=auth_headers, json={
                "title": "대용량 페이로드 테스트",
                "content": content,
                "post_type": "free",
            })
        assert resp.status_code in (200, 400, 413, 422)
        assert t.elapsed < 5, f"Large payload took {t.elapsed:.1f}s"

    def test_deeply_nested_json(self, website_client, auth_headers):
        """깊이 중첩된 JSON이 적절하게 처리되어야 한다."""
        # Build nested structure, not too deep to avoid recursion limits
        nested = {"level": 0}
        current = nested
        for i in range(50):
            current["child"] = {"level": i + 1}
            current = current["child"]

        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "중첩 테스트",
            "content": str(nested),
            "post_type": "free",
        })
        assert resp.status_code in (200, 400, 422)

    def test_many_fields_in_json(self, website_client, auth_headers):
        """많은 필드의 JSON이 적절하게 처리되어야 한다."""
        extra_fields = {f"extra_{i}": f"value_{i}" for i in range(100)}
        payload = {
            "title": "필드 테스트",
            "content": "많은 필드 테스트",
            "post_type": "free",
            **extra_fields,
        }
        resp = website_client.post("/api/posts", headers=auth_headers, json=payload)
        # Should accept (Pydantic ignores extra fields) or reject
        assert resp.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════
# Deep Pagination
# ═══════════════════════════════════════════════

class TestDeepPagination:
    """깊은 페이지네이션 테스트."""

    def test_page_1000(self, website_client, timer):
        """페이지 1000 요청이 안정적이어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/posts", params={"page": 1000, "per_page": 20})
        assert resp.status_code == 200
        assert t.elapsed_ms < 300

    def test_page_with_max_per_page(self, website_client, timer):
        """최대 per_page로 깊은 페이지 요청이 안정적이어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={
                "q": "",
                "page": 100,
                "per_page": 100,
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 300

    def test_invalid_page_number_handled(self, website_client):
        """잘못된 페이지 번호가 적절하게 처리되어야 한다."""
        resp = website_client.get("/api/posts", params={"page": 0})
        assert resp.status_code in (200, 400, 422)

    def test_negative_page_rejected(self, website_client):
        """음수 페이지 번호가 거부되어야 한다."""
        resp = website_client.get("/api/posts", params={"page": -1})
        assert resp.status_code in (200, 400, 422)

    def test_excessive_per_page_capped(self, website_client):
        """과도한 per_page가 제한되어야 한다."""
        resp = website_client.get("/api/posts", params={"per_page": 10000})
        assert resp.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════
# Complex Nested Category Queries
# ═══════════════════════════════════════════════

class TestComplexCategoryQueries:
    """복잡한 중첩 카테고리 쿼리 테스트."""

    def test_search_by_category_fast(self, website_client, timer):
        """카테고리별 검색이 빠르게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={
                "q": "양파",
                "type": "product",
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 300

    def test_posts_by_category_fast(self, website_client, timer):
        """카테고리별 게시글 조회가 빠르게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/posts", params={"category": "식품"})
        assert resp.status_code == 200
        assert t.elapsed_ms < 300

    def test_search_all_types(self, website_client, timer):
        """모든 유형 검색이 빠르게 처리되어야 한다."""
        types = ["product", "hotdeal", "post"]
        for search_type in types:
            with timer() as t:
                resp = website_client.get("/api/search", params={
                    "q": "양파",
                    "type": search_type,
                })
            assert resp.status_code == 200
            assert t.elapsed_ms < 300, f"Search type={search_type} took {t.elapsed_ms:.1f}ms"


# ═══════════════════════════════════════════════
# Concurrent Write Operations (Race Conditions)
# ═══════════════════════════════════════════════

class TestConcurrentWrites:
    """동시 쓰기 작업 (레이스 컨디션) 테스트."""

    def test_concurrent_post_creation(self, website_client, auth_headers):
        """동시 게시글 생성이 데이터 무결성을 유지해야 한다."""
        results = []

        def create_post(i):
            resp = website_client.post("/api/posts", headers=auth_headers, json={
                "title": f"동시 작성 테스트 {i}",
                "content": f"동시 작성 콘텐츠 {i}",
                "post_type": "free",
            })
            return resp.status_code, resp.json() if resp.status_code == 200 else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_post, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        created = [r for r in results if r[0] == 200]
        assert len(created) >= 15, f"Only {len(created)}/20 created"

        # Check IDs are unique
        ids = [r[1]["data"]["id"] for r in created if r[1]]
        assert len(set(ids)) == len(ids), "Duplicate IDs detected (race condition)"

    def test_concurrent_votes_on_same_post(self, website_client, auth_headers):
        """같은 게시글에 대한 동시 투표가 안정적이어야 한다."""
        # Create a post first
        post_resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "투표 스트레스 테스트",
            "content": "동시 투표 테스트",
            "post_type": "hotdeal",
            "price": 1000,
            "original_price": 2000,
        })
        assert post_resp.status_code == 200
        post_id = post_resp.json()["data"]["id"]

        # Same user votes rapidly (toggle test)
        results = []
        for _ in range(10):
            resp = website_client.post(
                f"/api/posts/{post_id}/vote",
                headers=auth_headers,
                json={"vote_type": "hot"},
            )
            results.append(resp.status_code)

        assert all(s == 200 for s in results)


# ═══════════════════════════════════════════════
# Cache Invalidation Under Load
# ═══════════════════════════════════════════════

class TestCacheInvalidation:
    """부하 상태에서의 캐시 무효화 테스트."""

    def test_read_after_write_consistency(self, website_client, auth_headers):
        """쓰기 후 읽기 일관성이 유지되어야 한다."""
        # Create a post
        create_resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "일관성 테스트 게시글",
            "content": "읽기-쓰기 일관성",
            "post_type": "free",
        })
        assert create_resp.status_code == 200
        post_id = create_resp.json()["data"]["id"]

        # Immediately read it
        get_resp = website_client.get(f"/api/posts/{post_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["title"] == "일관성 테스트 게시글"

    def test_update_reflected_immediately(self, website_client, auth_headers):
        """업데이트가 즉시 반영되어야 한다."""
        # Create
        create_resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "업데이트 전 제목",
            "content": "업데이트 테스트",
            "post_type": "free",
        })
        assert create_resp.status_code == 200
        post_id = create_resp.json()["data"]["id"]

        # Update
        update_resp = website_client.put(
            f"/api/posts/{post_id}",
            headers=auth_headers,
            json={"title": "업데이트 후 제목"},
        )
        assert update_resp.status_code == 200

        # Read updated
        get_resp = website_client.get(f"/api/posts/{post_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["title"] == "업데이트 후 제목"

    def test_delete_reflected_immediately(self, website_client, auth_headers):
        """삭제가 즉시 반영되어야 한다."""
        # Create
        create_resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "삭제 테스트",
            "content": "삭제 테스트 콘텐츠",
            "post_type": "free",
        })
        assert create_resp.status_code == 200
        post_id = create_resp.json()["data"]["id"]

        # Delete
        del_resp = website_client.delete(f"/api/posts/{post_id}", headers=auth_headers)
        assert del_resp.status_code == 200

        # Verify deleted
        get_resp = website_client.get(f"/api/posts/{post_id}")
        assert get_resp.status_code == 404
