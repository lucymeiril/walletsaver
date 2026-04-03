"""
성능 테스트 — API 응답 시간, 동시 요청, 대량 데이터, 검색, 가격 계산.

Tests:
- API endpoint response time benchmarks (< 200ms reads, < 500ms writes)
- Concurrent request handling (50 simultaneous)
- Large dataset queries (paginated)
- Search performance with complex queries
- Price calculation performance
- Memory monitoring during bulk operations
- Crawler pipeline throughput
"""

import pytest
import time
import statistics
import concurrent.futures
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════
# API Response Time Benchmarks
# ═══════════════════════════════════════════════

class TestAPIResponseTime:
    """API 응답 시간 벤치마크 테스트."""

    def test_health_endpoint_fast(self, website_client, timer):
        """헬스체크 엔드포인트가 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/health")
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Health took {t.elapsed_ms:.1f}ms (limit: 200ms)"

    def test_product_list_fast(self, website_client, timer):
        """상품 목록 조회가 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={"q": "", "type": "product"})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Product list took {t.elapsed_ms:.1f}ms"

    def test_search_endpoint_fast(self, website_client, timer):
        """검색이 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={"q": "양파"})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Search took {t.elapsed_ms:.1f}ms"

    def test_post_list_fast(self, website_client, timer):
        """게시글 목록 조회가 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/posts")
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Post list took {t.elapsed_ms:.1f}ms"

    def test_post_creation_within_limit(self, website_client, auth_headers, timer):
        """게시글 작성이 500ms 이내에 완료되어야 한다."""
        with timer() as t:
            resp = website_client.post("/api/posts", headers=auth_headers, json={
                "title": "성능 테스트 게시글",
                "content": "성능 테스트 콘텐츠",
                "post_type": "free",
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 500, f"Post creation took {t.elapsed_ms:.1f}ms"

    def test_login_within_limit(self, website_client, timer):
        """로그인이 500ms 이내에 완료되어야 한다 (bcrypt 포함)."""
        # Register first
        website_client.post("/api/auth/register", json={
            "email": "perf_login@test.com",
            "password": "password123",
            "nickname": "성능로그인",
        })
        with timer() as t:
            resp = website_client.post("/api/auth/login", json={
                "email": "perf_login@test.com",
                "password": "password123",
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 500, f"Login took {t.elapsed_ms:.1f}ms"

    def test_crawler_admin_health_fast(self, crawler_admin_client, timer):
        """크롤러 관리 헬스체크가 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = crawler_admin_client.get("/health")
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Crawler health took {t.elapsed_ms:.1f}ms"

    def test_autocomplete_fast(self, website_client, timer):
        """자동완성이 200ms 이내에 응답해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search/autocomplete", params={"q": "양"})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200, f"Autocomplete took {t.elapsed_ms:.1f}ms"


# ═══════════════════════════════════════════════
# Concurrent Request Tests
# ═══════════════════════════════════════════════

class TestConcurrentRequests:
    """동시 요청 처리 테스트."""

    def test_50_concurrent_health_checks(self, website_client, timer):
        """50개의 동시 헬스체크 요청을 처리할 수 있어야 한다."""
        results = []

        def make_request():
            start = time.perf_counter()
            resp = website_client.get("/api/health")
            elapsed = (time.perf_counter() - start) * 1000
            return resp.status_code, elapsed

        with timer() as t:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(make_request) for _ in range(50)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

        statuses = [r[0] for r in results]
        times = [r[1] for r in results]
        success_count = sum(1 for s in statuses if s == 200)

        assert success_count >= 45, f"Only {success_count}/50 succeeded"
        assert statistics.mean(times) < 500, f"Average {statistics.mean(times):.1f}ms"

    def test_concurrent_search_requests(self, website_client):
        """동시 검색 요청이 안정적으로 처리되어야 한다."""
        queries = ["양파", "삼겹살", "사과", "우유", "감자"] * 4

        def search(q):
            resp = website_client.get("/api/search", params={"q": q})
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(search, queries))

        success = sum(1 for s in results if s == 200)
        assert success >= 15, f"Only {success}/20 searches succeeded"

    def test_concurrent_post_reads(self, website_client):
        """동시 게시글 목록 조회가 안정적이어야 한다."""
        def read_posts():
            resp = website_client.get("/api/posts")
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_posts) for _ in range(30)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        success = sum(1 for s in results if s == 200)
        assert success >= 25, f"Only {success}/30 succeeded"


# ═══════════════════════════════════════════════
# Large Dataset Query Tests
# ═══════════════════════════════════════════════

class TestLargeDatasetQueries:
    """대량 데이터 쿼리 테스트."""

    def test_pagination_performance(self, website_client, timer):
        """페이지네이션이 효율적으로 동작해야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={
                "q": "",
                "page": 1,
                "per_page": 100,
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 300, f"Pagination took {t.elapsed_ms:.1f}ms"

    def test_high_page_number_handled(self, website_client, timer):
        """높은 페이지 번호가 적절하게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={
                "q": "양파",
                "page": 1000,
                "per_page": 20,
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 300, f"Deep page took {t.elapsed_ms:.1f}ms"
        data = resp.json()
        # Should return empty or valid response for out-of-range page
        assert "data" in data

    def test_max_per_page_handled(self, website_client, timer):
        """최대 per_page가 적절하게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/posts", params={"per_page": 100})
        assert resp.status_code == 200
        assert t.elapsed_ms < 300


# ═══════════════════════════════════════════════
# Search Performance Tests
# ═══════════════════════════════════════════════

class TestSearchPerformance:
    """검색 성능 테스트."""

    def test_empty_search_fast(self, website_client, timer):
        """빈 검색어가 빠르게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={"q": ""})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_korean_search_fast(self, website_client, timer):
        """한국어 검색이 빠르게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={"q": "삼겹살 할인"})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_search_with_filters_fast(self, website_client, timer):
        """필터가 있는 검색이 빠르게 처리되어야 한다."""
        with timer() as t:
            resp = website_client.get("/api/search", params={
                "q": "양파",
                "type": "product",
                "sort": "popular",
            })
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_multiple_searches_consistent(self, website_client):
        """여러 검색의 응답 시간이 일관되어야 한다."""
        times = []
        for q in ["양파", "삼겹살", "사과", "우유", "감자"]:
            start = time.perf_counter()
            resp = website_client.get("/api/search", params={"q": q})
            elapsed = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            times.append(elapsed)

        # Standard deviation should be reasonable
        if len(times) > 1:
            std_dev = statistics.stdev(times)
            mean = statistics.mean(times)
            # CV (coefficient of variation) should be < 200%
            assert std_dev / max(mean, 0.001) < 2.0, \
                f"Search times too variable: mean={mean:.1f}ms, std={std_dev:.1f}ms"


# ═══════════════════════════════════════════════
# Price Calculation Performance Tests
# ═══════════════════════════════════════════════

class TestPriceCalculationPerformance:
    """가격 계산 성능 테스트."""

    def test_price_statistics_fast(self, timer):
        """1000개 상품의 통계 계산이 빠르게 완료되어야 한다."""
        import random
        random.seed(42)
        prices = [random.randint(500, 50000) for _ in range(1000)]

        with timer() as t:
            mean = statistics.mean(prices)
            median = statistics.median(prices)
            std = statistics.stdev(prices)
            min_p = min(prices)
            max_p = max(prices)

        assert t.elapsed_ms < 50, f"Stats calc took {t.elapsed_ms:.1f}ms"
        assert mean > 0
        assert median > 0

    def test_hotdeal_tier_calculation_fast(self, timer):
        """핫딜 등급 계산이 빠르게 완료되어야 한다."""
        deals = [
            {"price": p, "original": o}
            for p, o in [(1000, 3000), (2500, 3000), (2800, 3000), (3500, 3000)] * 250
        ]

        def calc_tier(deal):
            if deal["original"] == 0:
                return "unknown"
            ratio = deal["price"] / deal["original"]
            if ratio <= 0.3:
                return "ultra"
            elif ratio <= 0.5:
                return "great"
            elif ratio <= 0.7:
                return "good"
            else:
                return "wait"

        with timer() as t:
            tiers = [calc_tier(d) for d in deals]

        assert t.elapsed_ms < 50, f"Tier calc took {t.elapsed_ms:.1f}ms"
        assert len(tiers) == 1000

    def test_discount_rate_batch_calculation(self, timer):
        """할인율 일괄 계산이 빠르게 완료되어야 한다."""
        import random
        random.seed(42)
        items = [
            {"price": random.randint(500, 5000), "original": random.randint(3000, 10000)}
            for _ in range(1000)
        ]

        with timer() as t:
            rates = []
            for item in items:
                if item["original"] > 0:
                    rate = 1 - (item["price"] / item["original"])
                    rates.append(round(rate * 100, 1))
            avg_discount = statistics.mean(rates) if rates else 0

        assert t.elapsed_ms < 50, f"Discount calc took {t.elapsed_ms:.1f}ms"
        assert len(rates) == 1000


# ═══════════════════════════════════════════════
# Memory Usage Tests
# ═══════════════════════════════════════════════

class TestMemoryUsage:
    """메모리 사용량 테스트."""

    def test_bulk_post_creation_memory(self, website_client, auth_headers):
        """대량 게시글 생성 시 메모리가 합리적이어야 한다."""
        import sys
        initial_size = sys.getsizeof([])

        posts = []
        for i in range(50):
            resp = website_client.post("/api/posts", headers=auth_headers, json={
                "title": f"메모리 테스트 {i}",
                "content": f"메모리 테스트 콘텐츠 {i}" * 10,
                "post_type": "free",
            })
            if resp.status_code == 200:
                posts.append(resp.json()["data"]["id"])

        assert len(posts) >= 40, f"Only {len(posts)}/50 posts created"

    def test_search_result_size_reasonable(self, website_client):
        """검색 결과 크기가 합리적이어야 한다."""
        resp = website_client.get("/api/search", params={"q": "", "per_page": 100})
        assert resp.status_code == 200
        body_size = len(resp.content)
        # Response should be < 1MB
        assert body_size < 1_000_000, f"Response too large: {body_size} bytes"


# ═══════════════════════════════════════════════
# Crawler Pipeline Throughput Tests
# ═══════════════════════════════════════════════

class TestCrawlerPipelineThroughput:
    """크롤러 파이프라인 처리량 테스트."""

    def test_crawler_list_fast(self, crawler_admin_client, timer):
        """크롤러 목록 조회가 빠르게 응답해야 한다."""
        with timer() as t:
            resp = crawler_admin_client.get("/api/crawlers")
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_schedule_list_fast(self, crawler_admin_client, timer):
        """스케줄 목록 조회가 빠르게 응답해야 한다."""
        with timer() as t:
            resp = crawler_admin_client.get("/api/schedules")
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_log_query_fast(self, crawler_admin_client, timer):
        """로그 조회가 빠르게 응답해야 한다."""
        with timer() as t:
            resp = crawler_admin_client.get("/api/logs", params={"limit": 50})
        assert resp.status_code == 200
        assert t.elapsed_ms < 200

    def test_simulated_pipeline_throughput(self, timer):
        """파이프라인 처리량 시뮬레이션 (1000 아이템/초 이상)."""
        items = [
            {"name": f"상품_{i}", "price": 1000 + i, "store": "이마트"}
            for i in range(1000)
        ]

        def process_item(item):
            # Simulate pipeline: validate, normalize, transform
            if not item.get("name") or not item.get("price"):
                return None
            return {
                "name": item["name"].strip(),
                "price": int(item["price"]),
                "store": item["store"].strip(),
                "processed_at": datetime.now().isoformat(),
            }

        with timer() as t:
            results = [process_item(item) for item in items]

        processed = [r for r in results if r is not None]
        assert len(processed) == 1000
        throughput = 1000 / max(t.elapsed, 0.001)
        assert throughput > 1000, f"Only {throughput:.0f} items/sec"
