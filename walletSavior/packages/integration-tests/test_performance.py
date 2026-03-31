"""
Performance Baseline Tests — 성능 기준 테스트.

API 응답 시간, 벌크 데이터 작업, 동시 요청 처리, 메모리 사용량 등을 검증한다.
"""

import pytest
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(ROOT / "packages" / "shared"),
    str(ROOT / "packages" / "website" / "backend"),
    str(ROOT / "packages" / "db-admin" / "backend"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker
from storage.models import (
    Base, Product, Category, BaselinePrice, DiscountHistory,
    HotdealPrice, User, UserRole,
)


@pytest.fixture
def perf_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def perf_session(perf_engine):
    Session = sessionmaker(bind=perf_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _seed_perf_data(session):
    cat = Category(id="perf", name="성능테스트", depth=0, sort_order=1, is_active=True)
    session.add(cat)
    session.flush()
    return cat


class TestAPIResponseTime:
    """API 응답 시간 기준선 (< 100ms)."""

    FAST_ENDPOINTS = [
        "/api/health",
        "/api/products/search",
        "/api/products/1",
        "/api/hotdeals",
        "/api/marts",
        "/api/search?q=양파",
        "/api/search/autocomplete?q=양",
        "/api/posts",
    ]

    @pytest.mark.parametrize("endpoint", FAST_ENDPOINTS)
    def test_response_under_100ms(self, website_client, endpoint):
        """응답 시간 < 100ms."""
        start = time.perf_counter()
        resp = website_client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 100, f"{endpoint}: {elapsed_ms:.1f}ms (> 100ms)"

    def test_product_detail_response_time(self, website_client):
        """상품 상세 조회 응답 시간."""
        start = time.perf_counter()
        resp = website_client.get("/api/products/1")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 100

    def test_price_compare_response_time(self, website_client):
        """가격 비교 응답 시간."""
        start = time.perf_counter()
        resp = website_client.get("/api/products/1/price-compare")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 100


class TestBulkDataOperations:
    """벌크 데이터 작업 성능."""

    def test_insert_1000_products(self, perf_session, perf_engine):
        """1000개 상품 삽입 성능."""
        cat = _seed_perf_data(perf_session)

        start = time.perf_counter()
        products = []
        for i in range(1000):
            products.append(Product(
                name=f"상품_{i:04d}",
                category_id="perf",
                unit="개",
                is_active=True,
            ))
        perf_session.add_all(products)
        perf_session.commit()
        elapsed = time.perf_counter() - start

        count = perf_session.query(Product).count()
        assert count == 1000
        assert elapsed < 5.0, f"1000개 삽입에 {elapsed:.2f}초 (> 5초)"

    def test_insert_1000_prices(self, perf_session, perf_engine):
        """1000개 가격 데이터 삽입."""
        cat = _seed_perf_data(perf_session)
        product = Product(name="벌크테스트", category_id="perf", unit="kg", is_active=True)
        perf_session.add(product)
        perf_session.commit()

        now = datetime.utcnow()
        start = time.perf_counter()
        prices = []
        for i in range(1000):
            prices.append(BaselinePrice(
                product_id=product.id,
                price=2000 + (i % 500),
                source=f"source_{i % 10}",
                unit="kg",
                recorded_at=now - timedelta(days=i),
            ))
        perf_session.add_all(prices)
        perf_session.commit()
        elapsed = time.perf_counter() - start

        count = perf_session.query(BaselinePrice).filter_by(product_id=product.id).count()
        assert count == 1000
        assert elapsed < 5.0, f"1000개 가격 삽입에 {elapsed:.2f}초"

    def test_query_performance_with_large_dataset(self, perf_session):
        """대규모 데이터셋 쿼리 성능."""
        cat = _seed_perf_data(perf_session)

        products = [Product(name=f"쿼리테스트_{i}", category_id="perf", unit="개", is_active=True) for i in range(500)]
        perf_session.add_all(products)
        perf_session.commit()

        start = time.perf_counter()
        results = perf_session.query(Product).filter(
            Product.category_id == "perf",
            Product.is_active == True,
        ).all()
        elapsed = time.perf_counter() - start

        assert len(results) == 500
        assert elapsed < 1.0, f"500개 쿼리에 {elapsed:.2f}초"

    def test_aggregate_query_performance(self, perf_session):
        """집계 쿼리 성능."""
        cat = _seed_perf_data(perf_session)
        product = Product(name="집계테스트", category_id="perf", unit="kg", is_active=True)
        perf_session.add(product)
        perf_session.commit()

        now = datetime.utcnow()
        prices = [
            BaselinePrice(
                product_id=product.id, price=2000 + i,
                source="KAMIS", unit="kg",
                recorded_at=now - timedelta(days=i),
            ) for i in range(200)
        ]
        perf_session.add_all(prices)
        perf_session.commit()

        start = time.perf_counter()
        result = perf_session.query(
            func.avg(BaselinePrice.price),
            func.min(BaselinePrice.price),
            func.max(BaselinePrice.price),
            func.count(BaselinePrice.id),
        ).filter_by(product_id=product.id).one()
        elapsed = time.perf_counter() - start

        avg_price, min_price, max_price, count = result
        assert count == 200
        assert min_price == 2000
        assert max_price == 2199
        assert elapsed < 0.5, f"집계 쿼리에 {elapsed:.2f}초"


class TestConcurrentRequests:
    """동시 요청 처리 성능."""

    def test_10_concurrent_search_requests(self, website_app):
        """10개 동시 검색 요청."""
        from fastapi.testclient import TestClient

        def make_request(query):
            client = TestClient(website_app)
            start = time.perf_counter()
            resp = client.get(f"/api/products/search?q={query}")
            elapsed = time.perf_counter() - start
            return resp.status_code, elapsed

        queries = ["양파", "삼겹살", "계란", "사과", "우유",
                    "쌀", "배추", "감자", "닭", "두부"]

        start_total = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, q) for q in queries]
            results = [f.result() for f in as_completed(futures)]
        total_elapsed = time.perf_counter() - start_total

        for status, elapsed in results:
            assert status == 200

        avg_time = sum(e for _, e in results) / len(results)
        assert avg_time < 0.1, f"평균 응답 시간 {avg_time:.3f}초 (> 0.1초)"

    def test_concurrent_different_endpoints(self, website_app):
        """다양한 엔드포인트에 동시 요청."""
        from fastapi.testclient import TestClient

        endpoints = [
            "/api/products/search?q=양파",
            "/api/hotdeals",
            "/api/marts",
            "/api/search?q=계란",
            "/api/posts",
            "/api/gas/nearby",
            "/api/health",
            "/api/products/1",
            "/api/hotdeals/1",
            "/api/search/autocomplete?q=삼",
        ]

        def make_request(endpoint):
            client = TestClient(website_app)
            resp = client.get(endpoint)
            return resp.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(make_request, endpoints))

        assert all(s == 200 for s in results), f"일부 요청 실패: {results}"


class TestMemoryUsage:
    """메모리 사용량 기준선."""

    def test_large_product_list_memory(self, perf_session):
        """대량 상품 로드 시 메모리."""
        import tracemalloc
        cat = _seed_perf_data(perf_session)

        products = [Product(name=f"메모리테스트_{i}", category_id="perf", unit="개", is_active=True) for i in range(500)]
        perf_session.add_all(products)
        perf_session.commit()

        tracemalloc.start()
        loaded = perf_session.query(Product).all()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert len(loaded) == 500
        peak_mb = peak / 1024 / 1024
        assert peak_mb < 50, f"피크 메모리 {peak_mb:.1f}MB (> 50MB)"

    def test_price_aggregation_memory(self, perf_session):
        """가격 집계 시 메모리."""
        import tracemalloc
        cat = _seed_perf_data(perf_session)
        product = Product(name="메모리가격테스트", category_id="perf", unit="kg", is_active=True)
        perf_session.add(product)
        perf_session.commit()

        now = datetime.utcnow()
        prices = [
            BaselinePrice(
                product_id=product.id, price=2000 + i,
                source="KAMIS", unit="kg",
                recorded_at=now - timedelta(days=i),
            ) for i in range(500)
        ]
        perf_session.add_all(prices)
        perf_session.commit()

        tracemalloc.start()
        all_prices = perf_session.query(BaselinePrice).filter_by(product_id=product.id).all()
        price_values = [p.price for p in all_prices]
        avg = sum(price_values) / len(price_values)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert len(price_values) == 500
        peak_mb = peak / 1024 / 1024
        assert peak_mb < 50, f"피크 메모리 {peak_mb:.1f}MB"


class TestSearchPerformance:
    """검색 성능."""

    def test_autocomplete_fast(self, website_client):
        """자동완성 응답 < 50ms."""
        start = time.perf_counter()
        resp = website_client.get("/api/search/autocomplete?q=양")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 50, f"자동완성 {elapsed_ms:.1f}ms (> 50ms)"

    def test_empty_search_fast(self, website_client):
        """빈 검색어 빠른 응답."""
        start = time.perf_counter()
        resp = website_client.get("/api/search?q=")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 100
