"""
WalletSavior 통합 테스트 — 공통 fixture.

모든 통합 테스트가 사용하는 공유 fixture 정의:
- FastAPI TestClient (website, crawler-admin, db-admin)
- SQLite 인메모리 DB 세션
- 샘플 데이터 생성 헬퍼
- 인증 토큰 생성
"""

import sys
import os
from pathlib import Path

# --- 경로 설정 ---
ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES = ROOT / "packages"
WEBSITE_BACKEND = PACKAGES / "website" / "backend"
CRAWLER_BACKEND = PACKAGES / "crawler-admin" / "backend"
DB_BACKEND = PACKAGES / "db-admin" / "backend"
SHARED = PACKAGES / "shared"

# proj/ may conflict with packages — remove it if present
_proj = str(ROOT / "proj")
if _proj in sys.path:
    sys.path.remove(_proj)

# DB_BACKEND first so storage.models resolves to db-admin, not proj/
# ROOT 추가: tools.xxx import 경로 해결 (tools/ 패키지는 루트 하위)
for p in [
    str(ROOT),
    str(DB_BACKEND),
    str(WEBSITE_BACKEND),
    str(CRAWLER_BACKEND),
    str(SHARED),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
import importlib.util
from datetime import datetime, timedelta, timezone
from typing import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# --- Shared models ---
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlRequest, CrawlResult, CrawlStatus,
    StrategyFailure, ErrorType, ProductPrice, DataSource,
    DiscountItem, HotdealPost, Event,
)

# --- DB models ---
from storage.models import (
    Base, Product, Category, BaselinePrice, DiscountHistory,
    HotdealPrice, User, Post, Comment, Vote, Favorite, PriceAlert,
    Keyword, CrawlLog, GasStation, PriceTier, PostType, VoteType,
    UserRole,
)


def _load_module_from_path(module_name, file_path):
    """파일 경로로 모듈 직접 로드 (이름 충돌 방지)."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════
# Website App Factory
# ═══════════════════════════════════════════════

@pytest.fixture
def website_app():
    """Website FastAPI app (mock mode — storage=None)."""
    # Ensure website backend is importable for lazy imports inside create_app
    saved_path = sys.path.copy()
    sys.path.insert(0, str(WEBSITE_BACKEND))
    try:
        mod = _load_module_from_path(
            "website_api_app",
            str(WEBSITE_BACKEND / "api" / "app.py"),
        )
        app = mod.create_app(storage=None, engine=None, event_bus=None)
        return app
    finally:
        sys.path = saved_path


@pytest.fixture
def website_client(website_app) -> TestClient:
    """Website TestClient for HTTP-like testing."""
    return TestClient(website_app)


# ═══════════════════════════════════════════════
# Crawler-Admin App Factory
# ═══════════════════════════════════════════════

@pytest.fixture
def crawler_admin_app():
    """Crawler-admin FastAPI app."""
    # Save and clear all api.* modules to avoid conflicts with website's api package
    api_modules = {k: v for k, v in sys.modules.items() if k == "api" or k.startswith("api.")}
    for k in api_modules:
        del sys.modules[k]

    # Temporarily prioritize crawler-admin backend path
    saved_path = sys.path.copy()
    sys.path.insert(0, str(CRAWLER_BACKEND))
    try:
        mod = _load_module_from_path(
            "crawler_api_app",
            str(CRAWLER_BACKEND / "api" / "app.py"),
        )
        app = mod.create_app()
        return app
    finally:
        # Clean up crawler-admin api modules
        for k in [k for k in sys.modules if k == "api" or k.startswith("api.")]:
            del sys.modules[k]
        # Restore previous api modules and path
        sys.modules.update(api_modules)
        sys.path = saved_path


@pytest.fixture
def crawler_admin_client(crawler_admin_app) -> TestClient:
    return TestClient(crawler_admin_app)


# ═══════════════════════════════════════════════
# SQLite In-Memory DB
# ═══════════════════════════════════════════════

@pytest.fixture
def db_engine():
    """SQLite 인메모리 엔진 — 테스트용."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    # SQLite FK 지원 활성화
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """DB 세션 fixture."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


# ═══════════════════════════════════════════════
# Authentication Helpers
# ═══════════════════════════════════════════════

@pytest.fixture
def auth_token():
    """유효한 JWT 액세스 토큰 생성."""
    from services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": "1", "email": "test@example.com", "role": "user"},
        expires_delta=timedelta(hours=1),
    )
    return token


@pytest.fixture
def admin_token():
    """관리자 JWT 토큰."""
    from services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": "99", "email": "admin@example.com", "role": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return token


@pytest.fixture
def auth_headers(auth_token):
    """Authorization 헤더."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ═══════════════════════════════════════════════
# Sample Data Generators
# ═══════════════════════════════════════════════

@pytest.fixture
def sample_categories(db_session):
    """카테고리 계층 생성."""
    cats = [
        Category(id="food", name="식품", depth=0, sort_order=1, is_active=True),
        Category(id="food.vegetable", name="채소류", parent_id="food", depth=1, sort_order=1, is_active=True),
        Category(id="food.vegetable.root", name="근채류", parent_id="food.vegetable", depth=2, sort_order=1, is_active=True),
        Category(id="food.meat", name="축산물", parent_id="food", depth=1, sort_order=2, is_active=True),
        Category(id="food.meat.pork", name="돼지고기", parent_id="food.meat", depth=2, sort_order=1, is_active=True),
        Category(id="food.fruit", name="과일류", parent_id="food", depth=1, sort_order=3, is_active=True),
        Category(id="food.dairy", name="유제품", parent_id="food", depth=1, sort_order=4, is_active=True),
        Category(id="electronics", name="전자기기", depth=0, sort_order=2, is_active=True),
    ]
    db_session.add_all(cats)
    db_session.commit()
    return cats


@pytest.fixture
def sample_products(db_session, sample_categories):
    """샘플 상품 생성."""
    products = [
        Product(name="양파", category_id="food.vegetable.root", unit="1kg", is_active=True),
        Product(name="삼겹살", category_id="food.meat.pork", unit="100g", is_active=True),
        Product(name="사과", category_id="food.fruit", unit="1kg", is_active=True),
        Product(name="우유", category_id="food.dairy", unit="1L", is_active=True),
        Product(name="감자", category_id="food.vegetable.root", unit="1kg", is_active=True),
    ]
    db_session.add_all(products)
    db_session.commit()
    return products


@pytest.fixture
def sample_baseline_prices(db_session, sample_products):
    """기준가 데이터 생성."""
    now = datetime.utcnow()
    prices = []
    price_data = [
        (sample_products[0].id, 2350, "KAMIS"),   # 양파
        (sample_products[0].id, 2280, "이마트"),
        (sample_products[0].id, 2490, "홈플러스"),
        (sample_products[1].id, 1850, "KAMIS"),   # 삼겹살
        (sample_products[1].id, 1680, "이마트"),
        (sample_products[2].id, 4800, "KAMIS"),   # 사과
        (sample_products[2].id, 5200, "이마트"),
        (sample_products[3].id, 2650, "KAMIS"),   # 우유
        (sample_products[3].id, 2590, "이마트"),
        (sample_products[4].id, 2800, "KAMIS"),   # 감자
    ]
    for pid, price, source in price_data:
        prices.append(BaselinePrice(
            product_id=pid, price=price, source=source,
            unit="kg", recorded_at=now - timedelta(days=1),
        ))
    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def sample_discount_history(db_session, sample_products):
    """할인 이력 생성."""
    now = datetime.utcnow()
    discounts = []
    discount_data = [
        (sample_products[0].id, 1980, 2350, 0.157, "이마트"),
        (sample_products[1].id, 1100, 1850, 0.405, "이마트"),
        (sample_products[2].id, 3900, 4800, 0.188, "홈플러스"),
    ]
    for pid, price, orig, rate, source in discount_data:
        discounts.append(DiscountHistory(
            product_id=pid, price=price, original_price=orig,
            discount_rate=rate, source=source,
            crawled_at=now - timedelta(hours=6),
        ))
    db_session.add_all(discounts)
    db_session.commit()
    return discounts


@pytest.fixture
def sample_user(db_session):
    """테스트 사용자."""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        email="test@example.com",
        hashed_password=pwd_context.hash("password123"),
        nickname="테스트유저",
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_crawl_result():
    """파이프라인 테스트용 크롤 결과."""
    return CrawlResult(
        status=CrawlStatus.SUCCESS,
        crawler_name="이마트",
        strategy_used="requests",
        items_count=3,
        items=[
            {"name": "양파 1.5kg", "price": 2480, "original_price": 3980, "store": "이마트", "category": "채소류"},
            {"name": "삼겹살 600g", "price": 9900, "original_price": 14900, "store": "이마트", "category": "축산물"},
            {"name": "계란 30구", "price": 5980, "original_price": 7980, "store": "이마트", "category": "축산물"},
        ],
        duration_seconds=2.5,
    )


@pytest.fixture
def sample_product_prices():
    """ProductPrice 리스트."""
    return [
        ProductPrice(
            product_name="양파", category="채소류 > 근채류", store="이마트",
            source=DataSource.MART_DISCOUNT, price=2480, unit="1.5kg",
            original_price=3980, discount_rate=0.377,
        ),
        ProductPrice(
            product_name="삼겹살", category="축산물 > 돼지고기", store="이마트",
            source=DataSource.MART_DISCOUNT, price=9900, unit="600g",
            original_price=14900, discount_rate=0.336,
        ),
    ]


@pytest.fixture
def sample_hotdeal_post():
    """핫딜 게시글."""
    return HotdealPost(
        title="이마트 삼겹살 100g 1,100원",
        url="https://example.com/deal/1",
        source_community="뽐뿌",
        price=1100,
        original_price=1850,
        category="식품",
        matched_product="삼겹살",
        price_vs_avg=0.595,
    )
