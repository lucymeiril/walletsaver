"""
Regression Test Suite — 회귀 테스트.

기존 단위 테스트가 영향받지 않았는지, 크로스 패키지 임포트 충돌이 없는지,
공유 모델이 일관되게 사용되는지 검증한다.
"""

import pytest
import sys
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES = ROOT / "packages"
SHARED = PACKAGES / "shared"

for p in [str(SHARED), str(PACKAGES / "website" / "backend"),
          str(PACKAGES / "crawler-admin" / "backend"),
          str(PACKAGES / "db-admin" / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestSharedModelConsistency:
    """공유 모델이 모든 패키지에서 일관되게 사용되는지 검증."""

    def test_import_core_models(self):
        """core.models 정상 임포트."""
        from core.models import (
            CrawlStatus, ErrorType, CrawlerGroup, CrawlerInfo,
            CrawlRequest, CrawlResult, StrategyFailure,
            DiagnosisReport, Event, DataSource, ProductPrice,
            DiscountItem, HotdealPost,
        )
        assert CrawlStatus.SUCCESS.value == "success"
        assert DataSource.GOVERNMENT.value == "government"
        assert CrawlerGroup.MART.value == "marts"

    def test_import_core_contracts(self):
        """core.contracts 정상 임포트."""
        from core.contracts.crawler import CrawlerContract
        from core.contracts.engine import EngineContract
        from core.contracts.storage import StorageContract
        from core.contracts.scheduler import SchedulerContract
        assert CrawlerContract is not None
        assert EngineContract is not None

    def test_import_core_events(self):
        """core.events 정상 임포트."""
        from core.events import EventBus
        bus = EventBus()
        assert bus is not None

    def test_import_core_exceptions(self):
        """core.exceptions 정상 임포트."""
        from core.exceptions import CrawlError
        assert issubclass(CrawlError, Exception)

    def test_crawl_status_enum_values(self):
        """CrawlStatus enum 값 완전성."""
        from core.models import CrawlStatus
        expected = {"pending", "running", "success", "failed", "partial", "cancelled"}
        actual = {s.value for s in CrawlStatus}
        assert expected == actual

    def test_error_type_enum_values(self):
        """ErrorType enum 값 완전성."""
        from core.models import ErrorType
        expected = {
            "http_error", "captcha_detected", "ip_banned", "js_challenge",
            "dom_changed", "timeout", "login_required", "empty_response",
            "parse_error", "network_error", "unknown",
        }
        actual = {e.value for e in ErrorType}
        assert expected == actual

    def test_data_source_enum_values(self):
        """DataSource enum 값 완전성."""
        from core.models import DataSource
        expected = {"government", "mart_regular", "mart_discount", "hotdeal", "delivery", "gas_station"}
        actual = {s.value for s in DataSource}
        assert expected == actual

    def test_product_price_model_fields(self):
        """ProductPrice 필드 완전성."""
        from core.models import ProductPrice, DataSource
        pp = ProductPrice(
            product_name="테스트",
            source=DataSource.GOVERNMENT,
            price=1000,
        )
        assert pp.product_name == "테스트"
        assert pp.price == 1000
        assert pp.source == DataSource.GOVERNMENT
        assert pp.category == ""
        assert pp.store == ""

    def test_discount_item_to_product_price_conversion(self):
        """DiscountItem → ProductPrice 변환."""
        from core.models import DiscountItem, DataSource
        item = DiscountItem(
            name="GAP 양파 1.5kg",
            normalized_name="양파",
            store="이마트",
            original_price=3980,
            sale_price=2480,
            discount_percent=37.7,
            unit="1.5kg",
            category="채소류",
        )
        pp = item.to_product_price()
        assert pp.product_name == "양파"
        assert pp.source == DataSource.MART_DISCOUNT
        assert pp.price == 2480
        assert pp.raw_text == "GAP 양파 1.5kg"


class TestCrossPackageImports:
    """크로스 패키지 임포트 충돌 검증."""

    def test_website_app_import(self):
        """Website app 임포트 충돌 없음."""
        sys.path.insert(0, str(PACKAGES / "website" / "backend"))
        from api.app import create_app
        app = create_app()
        assert app is not None

    def test_website_schemas_import(self):
        """Website 스키마 임포트."""
        sys.path.insert(0, str(PACKAGES / "website" / "backend"))
        from api.schemas.common import ApiResponse, PaginationMeta
        resp = ApiResponse(data={"test": True})
        assert resp.success is True
        assert resp.data == {"test": True}

    def test_website_auth_service_import(self):
        """auth_service 임포트."""
        sys.path.insert(0, str(PACKAGES / "website" / "backend"))
        from services.auth_service import (
            hash_password, verify_password, create_token_pair, decode_token,
        )
        hashed = hash_password("test123")
        assert verify_password("test123", hashed)
        assert not verify_password("wrong", hashed)

    def test_db_models_import(self):
        """DB ORM 모델 임포트."""
        from storage.models import (
            Base, Product, Category, BaselinePrice,
            DiscountHistory, HotdealPrice, User, Post,
            Comment, Vote, Favorite, PriceAlert,
        )
        assert Product.__tablename__ == "products"
        assert Category.__tablename__ == "categories"
        assert User.__tablename__ == "users"

    def test_db_models_table_count(self):
        """19개 테이블 존재 확인."""
        from storage.models import Base
        table_names = set(Base.metadata.tables.keys())
        expected_tables = {
            "users", "oauth_accounts", "categories", "products",
            "baseline_prices", "discount_history", "hotdeal_prices",
            "gas_stations", "restaurants", "posts", "post_images",
            "comments", "votes", "favorites", "price_alerts",
            "crawl_logs", "keywords", "delivery_items", "shopping_items",
        }
        missing = expected_tables - table_names
        assert not missing, f"누락 테이블: {missing}"


class TestInitExports:
    """__init__.py 파일 존재 여부 검증."""

    INIT_PATHS = [
        PACKAGES / "shared" / "__init__.py",
        PACKAGES / "shared" / "core" / "__init__.py",
        PACKAGES / "shared" / "core" / "contracts" / "__init__.py",
        PACKAGES / "website" / "backend" / "__init__.py",
        PACKAGES / "crawler-admin" / "backend" / "__init__.py",
        PACKAGES / "db-admin" / "backend" / "__init__.py",
    ]

    @pytest.mark.parametrize("init_path", INIT_PATHS)
    def test_init_file_exists(self, init_path):
        """__init__.py 존재 확인."""
        assert init_path.exists(), f"{init_path}가 존재하지 않음"


class TestApiResponseConsistency:
    """ApiResponse 사용 일관성."""

    def test_api_response_default_values(self):
        """ApiResponse 기본값."""
        from api.schemas.common import ApiResponse
        resp = ApiResponse()
        assert resp.success is True
        assert resp.data is None
        assert resp.error is None
        assert resp.meta is None

    def test_api_response_with_error(self):
        """에러 ApiResponse."""
        from api.schemas.common import ApiResponse
        resp = ApiResponse(success=False, error="에러 발생")
        assert resp.success is False
        assert resp.error == "에러 발생"
        assert resp.data is None

    def test_pagination_meta(self):
        """PaginationMeta 구조."""
        from api.schemas.common import PaginationMeta
        meta = PaginationMeta(page=1, per_page=20, total=100, total_pages=5)
        assert meta.page == 1
        assert meta.per_page == 20
        assert meta.total == 100
        assert meta.total_pages == 5

    def test_api_response_with_pagination(self):
        """ApiResponse + 페이지네이션."""
        from api.schemas.common import ApiResponse, PaginationMeta
        meta = PaginationMeta(page=2, per_page=10, total=50, total_pages=5)
        resp = ApiResponse(data=[1, 2, 3], meta=meta)
        assert resp.success is True
        assert resp.meta.page == 2
        assert len(resp.data) == 3


class TestEventBusContract:
    """EventBus 계약 검증."""

    def test_event_bus_subscribe_publish(self):
        """이벤트 발행-구독."""
        import asyncio
        from core.events import EventBus
        from core.models import Event
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test_event", handler)
        event = Event(event_type="test_event", data={"key": "value"}, source="test")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bus.publish(event))
        loop.close()
        assert len(received) == 1
        assert received[0].data == {"key": "value"}

    def test_event_bus_clear(self):
        """EventBus 초기화."""
        import asyncio
        from core.events import EventBus
        from core.models import Event
        bus = EventBus()

        async def handler(event):
            pass

        bus.subscribe("e", handler)
        bus.clear()
        event = Event(event_type="e", data={}, source="test")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bus.publish(event))
        loop.close()
