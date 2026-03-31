"""
Cross-Service Integration Tests — 서비스 간 데이터 흐름 검증.

크롤러 → 파이프라인 → DB → Website API 의 전체 데이터 흐름을 테스트한다.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure paths
ROOT = Path(__file__).resolve().parent.parent.parent
SHARED = ROOT / "packages" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from core.models import (
    CrawlResult, CrawlStatus, ProductPrice, DataSource,
    DiscountItem, HotdealPost, CrawlerInfo, CrawlerGroup,
    CrawlRequest, StrategyFailure, ErrorType, Event,
)
from storage.models import Category


class TestCrawlerToAPIFlow:
    """크롤러 → 파이프라인 → DB → API 데이터 흐름 테스트."""

    def test_crawl_result_to_product_price_via_discount_item(self):
        """CrawlResult items → DiscountItem → ProductPrice 변환 흐름."""
        raw_items = [
            {"name": "GAP 양파 1.5kg", "price": 2480, "original_price": 3980,
             "store": "이마트", "category": "채소류", "discount_percent": 37.7},
        ]
        item = DiscountItem(
            name=raw_items[0]["name"],
            normalized_name="양파",
            store=raw_items[0]["store"],
            original_price=raw_items[0]["original_price"],
            sale_price=raw_items[0]["price"],
            discount_percent=raw_items[0]["discount_percent"],
            unit="1.5kg",
            category=raw_items[0]["category"],
        )
        pp = item.to_product_price()

        assert pp.product_name == "양파"
        assert pp.store == "이마트"
        assert pp.source == DataSource.MART_DISCOUNT
        assert pp.price == 2480
        assert pp.original_price == 3980
        assert pp.discount_rate == pytest.approx(0.377, abs=0.001)
        assert pp.raw_text == "GAP 양파 1.5kg"

    def test_full_crawl_pipeline_flow(self, sample_crawl_result):
        """전체 파이프라인: CrawlResult → DiscountItem 변환 → ProductPrice 목록."""
        result = sample_crawl_result
        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count == 3

        product_prices = []
        for item_data in result.items:
            di = DiscountItem(
                name=item_data["name"],
                normalized_name=item_data["name"].split()[0],
                store=item_data["store"],
                original_price=item_data.get("original_price"),
                sale_price=item_data["price"],
                category=item_data.get("category", ""),
            )
            product_prices.append(di.to_product_price())

        assert len(product_prices) == 3
        assert all(isinstance(pp, ProductPrice) for pp in product_prices)
        assert all(pp.source == DataSource.MART_DISCOUNT for pp in product_prices)

    def test_crawl_result_items_are_stored_in_db(self, db_session, sample_products):
        """크롤 결과 → DB 저장 시뮬레이션."""
        from storage.models import DiscountHistory

        product = sample_products[0]  # 양파
        discount = DiscountHistory(
            product_id=product.id,
            price=2480,
            original_price=3980,
            discount_rate=0.377,
            source="이마트",
            crawled_at=datetime.utcnow(),
        )
        db_session.add(discount)
        db_session.commit()

        saved = db_session.query(DiscountHistory).filter_by(product_id=product.id).all()
        assert len(saved) >= 1
        assert saved[-1].price == 2480
        assert saved[-1].source == "이마트"

    def test_db_data_served_through_website_api(self, website_client):
        """DB 저장 데이터가 Website API로 제공되는지 검증 (mock mode)."""
        response = website_client.get("/api/products/search?q=양파")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        found = [p for p in data["data"] if "양파" in p["name"]]
        assert len(found) > 0


class TestPriceBaselineCalculation:
    """가격 기준선 계산 흐름."""

    def test_baseline_price_statistical_analysis(self, db_session, sample_products, sample_baseline_prices):
        """기준가 통계 분석."""
        from storage.models import BaselinePrice

        product = sample_products[0]  # 양파
        prices = db_session.query(BaselinePrice).filter_by(product_id=product.id).all()
        price_values = [p.price for p in prices]

        assert len(price_values) >= 2
        avg_price = sum(price_values) / len(price_values)
        min_price = min(price_values)
        max_price = max(price_values)

        assert min_price <= avg_price <= max_price
        assert avg_price > 0

    def test_price_tier_assignment(self):
        """가격 등급(tier) 판정 로직."""
        avg = 10000

        def get_tier(price, avg_price):
            ratio = price / avg_price
            if ratio <= 0.70:
                return "ultra"
            elif ratio <= 0.85:
                return "great"
            elif ratio <= 1.05:
                return "good"
            else:
                return "wait"

        assert get_tier(6000, avg) == "ultra"    # 60%
        assert get_tier(7000, avg) == "ultra"    # 70% — boundary
        assert get_tier(7500, avg) == "great"    # 75%
        assert get_tier(8500, avg) == "great"    # 85% — boundary
        assert get_tier(9000, avg) == "good"     # 90%
        assert get_tier(10500, avg) == "good"    # 105% — boundary
        assert get_tier(11000, avg) == "wait"    # 110%
        assert get_tier(15000, avg) == "wait"    # 150%

    def test_price_tier_via_api(self, website_client):
        """API에서 반환하는 price_tier 확인 (mock)."""
        response = website_client.get("/api/products/search")
        data = response.json()
        products = data["data"]
        tiers = {p["name"]: p["price_tier"] for p in products}
        valid_tiers = {"ultra", "great", "good", "wait"}
        for name, tier in tiers.items():
            assert tier in valid_tiers, f"{name}의 tier '{tier}'가 유효하지 않음"

    def test_discount_rate_calculation(self):
        """할인율 계산 정확성."""
        item = DiscountItem(
            name="테스트상품",
            store="테스트마트",
            original_price=10000,
            sale_price=7000,
            discount_percent=30.0,
        )
        pp = item.to_product_price()
        assert pp.price == 7000
        assert pp.original_price == 10000
        assert pp.discount_rate == pytest.approx(0.30, abs=0.001)


class TestCategorySyncFlow:
    """카테고리 동기화 흐름."""

    def test_category_hierarchy_in_db(self, db_session, sample_categories):
        """DB 카테고리 계층 구조 검증."""
        root_cats = db_session.query(Category).filter_by(depth=0).all()
        assert len(root_cats) >= 2  # food, electronics

        food_children = db_session.query(Category).filter_by(parent_id="food").all()
        assert len(food_children) >= 3  # vegetable, meat, fruit, dairy

        veggie_children = db_session.query(Category).filter_by(parent_id="food.vegetable").all()
        assert len(veggie_children) >= 1  # root

    def test_category_products_relationship(self, db_session, sample_products):
        """카테고리-상품 관계."""
        from storage.models import Product
        veggie_products = db_session.query(Product).filter_by(
            category_id="food.vegetable.root"
        ).all()
        names = [p.name for p in veggie_products]
        assert "양파" in names
        assert "감자" in names

    def test_category_filtering_in_api(self, website_client):
        """API 카테고리 필터링."""
        response = website_client.get("/api/products/search?category=채소류")
        data = response.json()
        assert data["success"] is True
        for p in data["data"]:
            assert "채소류" in p.get("cat", "")


class TestSearchFlow:
    """검색 흐름 (keyword → autocomplete → results → price data)."""

    def test_search_returns_products(self, website_client):
        """검색 결과에 상품이 포함됨."""
        response = website_client.get("/api/search?q=삼겹살")
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) > 0
        product_results = [r for r in data["data"] if r["type"] == "product"]
        assert len(product_results) > 0

    def test_autocomplete_suggests_matches(self, website_client):
        """자동완성 결과 확인."""
        response = website_client.get("/api/search/autocomplete?q=양")
        data = response.json()
        assert data["success"] is True
        suggestions = data["data"]
        assert isinstance(suggestions, list)
        if suggestions:
            assert "text" in suggestions[0]
            assert "type" in suggestions[0]

    def test_search_then_product_detail(self, website_client):
        """검색 → 상품 상세 조회 흐름."""
        search_resp = website_client.get("/api/search?q=우유")
        search_data = search_resp.json()
        product_results = [r for r in search_data["data"] if r["type"] == "product"]

        if product_results:
            product_id = product_results[0]["id"]
            detail_resp = website_client.get(f"/api/products/{product_id}")
            assert detail_resp.status_code == 200
            detail_data = detail_resp.json()
            assert detail_data["success"] is True
            assert detail_data["data"]["id"] == product_id

    def test_search_type_filter(self, website_client):
        """타입 필터로 검색 범위 제한."""
        response = website_client.get("/api/search?q=삼겹살&type=product")
        data = response.json()
        for item in data["data"]:
            assert item["type"] == "product"

    def test_search_pagination(self, website_client):
        """검색 결과 페이지네이션."""
        resp1 = website_client.get("/api/search?q=&per_page=5&page=1")
        data1 = resp1.json()
        assert data1["meta"]["page"] == 1
        assert data1["meta"]["per_page"] == 5

        if data1["meta"]["total_pages"] > 1:
            resp2 = website_client.get("/api/search?q=&per_page=5&page=2")
            data2 = resp2.json()
            assert data2["meta"]["page"] == 2
            ids1 = {r["id"] for r in data1["data"]}
            ids2 = {r["id"] for r in data2["data"]}
            assert ids1.isdisjoint(ids2), "페이지 간 결과가 중복됨"
