"""WalletSavior 데이터베이스 모델 — 완전한 스키마 정의

왜 존재하는가:
    core/models.py의 Pydantic 모델은 "전송·검증용 DTO"이고,
    이 파일의 SQLAlchemy 모델은 "실제 DB 스키마"다.
    두 계층을 분리해야 DB 스키마 변경이 API 응답 형태에 영향을 주지 않는다.
어디서 쓰이는가:
    storage/db.py (DBStorage)가 이 모델들로 CRUD를 수행한다.
    alembic 마이그레이션도 이 Base.metadata를 참조한다.
지원 DB:
    SQLite (개발) — auto-create, JSON은 TEXT로 저장
    PostgreSQL (운영) — 네이티브 JSON, 인덱스 최적화
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    Index, UniqueConstraint, CheckConstraint, JSON, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

import enum


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스 — metadata 공유로 일괄 테이블 생성 지원."""
    pass


# ═══════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════

class PriceTier(str, enum.Enum):
    ULTRA = "ultra"      # 70% 이하 (초특가)
    GREAT = "great"      # 70-85% (핫딜)
    GOOD = "good"        # 85-105% (적정가)
    WAIT = "wait"        # 105%+ (비쌈)


class PostType(str, enum.Enum):
    HOTDEAL = "hotdeal"   # 핫딜 게시판
    FREE = "free"         # 자유 게시판


class VoteType(str, enum.Enum):
    HOT = "hot"           # 핫딜 맞음
    NOT = "not"           # 핫딜 아님


class CrawlStatus(str, enum.Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"


class OAuthProvider(str, enum.Enum):
    GOOGLE = "google"
    KAKAO = "kakao"
    NAVER = "naver"


# ═══════════════════════════════════════════════
# 사용자
# ═══════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER)
    profile_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 프로필 확장 필드
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    posts: Mapped[list["Post"]] = relationship(back_populates="author", cascade="all, delete-orphan")
    comments: Mapped[list["Comment"]] = relationship(back_populates="author", cascade="all, delete-orphan")
    votes: Mapped[list["Vote"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    favorites: Mapped[list["Favorite"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    price_alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    wishlist_items: Mapped[list["WishlistItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    activities: Mapped[list["UserActivity"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[OAuthProvider] = mapped_column(SAEnum(OAuthProvider))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )


# ═══════════════════════════════════════════════
# 카테고리
# ═══════════════════════════════════════════════

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # "meat.pork.belly"
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "삼겹살"
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["Category"]] = relationship("Category", remote_side="Category.id")
    products: Mapped[list["Product"]] = relationship(back_populates="category")


# ═══════════════════════════════════════════════
# 상품
# ═══════════════════════════════════════════════

class Product(Base):
    """품목 마스터 — 모든 가격 비교의 기준 단위."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    unit: Mapped[str] = mapped_column(String(50), default="개")
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_type: Mapped[Optional[str]] = mapped_column(String(20), default="unknown")
    # "mart_crawl" | "community_deal" | "baseline" | "user_submitted" | "unknown"
    categorization_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    categorization_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # "auto" | "suggested" | "manual" | "corrected"

    # ── RD8 D1 추가 컬럼 (migration f1a2b3c4d5e6) ─────────────────────────────
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    name_core: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pack_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    unit_kind: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    source_marts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    category: Mapped[Optional["Category"]] = relationship(back_populates="products")
    # lazy="selectin" — 상품 목록 조회 시 N+1 방지, 필요할 때만 서브쿼리로 일괄 로딩
    baseline_prices: Mapped[list["BaselinePrice"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin",
    )
    discount_history: Mapped[list["DiscountHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin",
    )
    hotdeal_prices: Mapped[list["HotdealPrice"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin",
    )
    product_keywords: Mapped[list["ProductKeyword"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_category", "category_id"),
        # source_type 필터 빈번 — 핫딜/마트/기준가 분류 필터링용
        Index("ix_products_source_type", "source_type"),
        Index("ix_products_active", "is_active"),
    )


# ═══════════════════════════════════════════════
# 가격 테이블 (Pure Price DB 전략)
# ═══════════════════════════════════════════════

class BaselinePrice(Base):
    """마트4사+쿠팡 수집 기준가 테이블.

    과거 정부/KAMIS source 값이 남아 있더라도 레거시 참고용으로만 취급하며,
    식료품 가격 티어 산출 경로에 다시 연결하지 않는다.
    """
    __tablename__ = "baseline_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(50))
    unit: Mapped[str] = mapped_column(String(50))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(50))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)

    product: Mapped["Product"] = relationship(back_populates="baseline_prices")

    __table_args__ = (
        Index("ix_baseline_product_date", "product_id", "recorded_at"),
        # 매장별 최신 기준가 조회 최적화
        Index("ix_baseline_product_source", "product_id", "source"),
    )


class DiscountHistory(Base):
    """마트 실제 할인 가격 (실거래가)"""
    __tablename__ = "discount_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[Optional[float]] = mapped_column(Float)
    discount_rate: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)

    product: Mapped["Product"] = relationship(back_populates="discount_history")

    __table_args__ = (
        Index("ix_discount_product_date", "product_id", "crawled_at"),
        Index("ix_discount_source", "source"),
        # 복합 인덱스: 매장별 최신 가격 조회 최적화 (source + product_id)
        Index("ix_discount_product_source", "product_id", "source"),
        # crawled_at 단독 인덱스: 최신 할인 목록 정렬용
        Index("ix_discount_crawled_at", "crawled_at"),
    )


class HotdealPrice(Base):
    """커뮤니티 핫딜 가격 (참고용, 기준가 산정에 사용 안 함)"""
    __tablename__ = "hotdeal_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    title: Mapped[Optional[str]] = mapped_column(String(500))
    votes_hot: Mapped[int] = mapped_column(Integer, default=0)
    votes_not: Mapped[int] = mapped_column(Integer, default=0)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped["Product"] = relationship(back_populates="hotdeal_prices")

    __table_args__ = (
        Index("ix_hotdeal_product_date", "product_id", "crawled_at"),
        # source 단독 인덱스: 출처별 핫딜 필터링용
        Index("ix_hotdeal_source", "source"),
        # crawled_at 단독: 최신 핫딜 정렬용
        Index("ix_hotdeal_crawled_at", "crawled_at"),
    )


# ═══════════════════════════════════════════════
# 주유소
# ═══════════════════════════════════════════════

class GasStation(Base):
    __tablename__ = "gas_stations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(50))
    address: Mapped[str] = mapped_column(String(500))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    gasoline_price: Mapped[Optional[float]] = mapped_column(Float)
    diesel_price: Mapped[Optional[float]] = mapped_column(Float)
    lpg_price: Mapped[Optional[float]] = mapped_column(Float)
    is_self: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(50), default="opinet")

    __table_args__ = (
        Index("ix_gas_location", "lat", "lng"),
    )


# ═══════════════════════════════════════════════
# 식당
# ═══════════════════════════════════════════════

class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(500))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    naver_place_id: Mapped[Optional[str]] = mapped_column(String(100))
    rating: Mapped[Optional[float]] = mapped_column(Float)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    menu_data: Mapped[Optional[dict]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_restaurant_location", "lat", "lng"),
    )


# ═══════════════════════════════════════════════
# 커뮤니티
# ═══════════════════════════════════════════════

class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    post_type: Mapped[PostType] = mapped_column(SAEnum(PostType), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    custom_category: Mapped[Optional[str]] = mapped_column(String(100))
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"))
    deal_price: Mapped[Optional[float]] = mapped_column(Float)
    deal_url: Mapped[Optional[str]] = mapped_column(String(500))
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    suggested_tier: Mapped[Optional[str]] = mapped_column(String(20))
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author: Mapped["User"] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(back_populates="post", cascade="all, delete-orphan")
    votes: Mapped[list["Vote"]] = relationship(back_populates="post", cascade="all, delete-orphan")
    images: Mapped[list["PostImage"]] = relationship(back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_posts_type_created", "post_type", "created_at"),
        Index("ix_posts_author", "author_id"),
    )


class PostImage(Base):
    """게시글 사이사이 삽입되는 이미지"""
    __tablename__ = "post_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    alt_text: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    post: Mapped["Post"] = relationship(back_populates="images")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comments.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    post: Mapped["Post"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(back_populates="comments")
    parent: Mapped[Optional["Comment"]] = relationship("Comment", remote_side="Comment.id")

    __table_args__ = (
        Index("ix_comments_post", "post_id"),
    )


class Vote(Base):
    """핫딜 여부 투표"""
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vote_type: Mapped[VoteType] = mapped_column(SAEnum(VoteType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    post: Mapped["Post"] = relationship(back_populates="votes")
    user: Mapped["User"] = relationship(back_populates="votes")

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_vote_post_user"),
    )


# ═══════════════════════════════════════════════
# 즐겨찾기 & 알림
# ═══════════════════════════════════════════════

class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"))
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="favorites")


class PriceAlert(Base):
    """가격 알림 — 목표 가격 이하 시 알림"""
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="price_alerts")


# ═══════════════════════════════════════════════
# 크롤링 로그
# ═══════════════════════════════════════════════

class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    crawler_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[CrawlStatus] = mapped_column(SAEnum(CrawlStatus))
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_saved: Mapped[int] = mapped_column(Integer, default=0)
    strategy_used: Mapped[Optional[str]] = mapped_column(String(50))
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_type: Mapped[Optional[str]] = mapped_column(String(50))
    raw_log: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_crawl_log_name_date", "crawler_name", "started_at"),
    )


# ═══════════════════════════════════════════════
# 자동완성 키워드
# ═══════════════════════════════════════════════

class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    synonyms: Mapped[Optional[list]] = mapped_column(JSON)
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product_keywords: Mapped[list["ProductKeyword"]] = relationship(
        back_populates="keyword", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_keywords_word", "word"),
        # 인기 검색어 정렬용 — search_count DESC 빈번 사용
        Index("ix_keywords_active_count", "is_active", "search_count"),
    )


# ═══════════════════════════════════════════════
# 상품-키워드 연결 (Junction Table)
# ═══════════════════════════════════════════════

class ProductKeyword(Base):
    """상품과 키워드의 다대다 관계를 위한 연결 테이블."""
    __tablename__ = "product_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"))

    product: Mapped["Product"] = relationship(back_populates="product_keywords")
    keyword: Mapped["Keyword"] = relationship(back_populates="product_keywords")

    __table_args__ = (
        UniqueConstraint("product_id", "keyword_id", name="uq_product_keyword"),
        Index("ix_product_keywords_product", "product_id"),
        Index("ix_product_keywords_keyword", "keyword_id"),
    )


# ═══════════════════════════════════════════════
# 배달 음식
# ═══════════════════════════════════════════════

class DeliveryItem(Base):
    """배달 앱 메뉴 가격"""
    __tablename__ = "delivery_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    restaurant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    menu_name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[Optional[float]] = mapped_column(Float)
    platform: Mapped[str] = mapped_column(String(50))
    delivery_fee: Mapped[Optional[float]] = mapped_column(Float)
    min_order: Mapped[Optional[float]] = mapped_column(Float)
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_delivery_restaurant", "restaurant_name"),
        Index("ix_delivery_platform", "platform"),
    )


# ═══════════════════════════════════════════════
# 쇼핑 (의류 등)
# ═══════════════════════════════════════════════

class ShoppingItem(Base):
    """쇼핑몰 할인 상품"""
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[Optional[float]] = mapped_column(Float)
    discount_rate: Mapped[Optional[float]] = mapped_column(Float)
    platform: Mapped[str] = mapped_column(String(50))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_shopping_platform", "platform"),
    )


# ═══════════════════════════════════════════════
# Normalized public mart catalog/pricing slice
# ═══════════════════════════════════════════════

class NormalizedCanonicalProduct(Base):
    """Static canonical product data for the normalized public catalog slice."""
    __tablename__ = "normalized_canonical_products"

    public_product_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    primary_image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mart3-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category: Mapped[Optional["Category"]] = relationship("Category")
    variants: Mapped[list["NormalizedProductVariant"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_norm_product_category", "category_id"),
        Index("ix_norm_product_name", "canonical_name"),
    )


class NormalizedProductVariant(Base):
    """Package/volume variant for a canonical product."""
    __tablename__ = "normalized_product_variants"

    public_variant_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    public_product_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_canonical_products.public_product_id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    package_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    package_unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    display_unit: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    bundle_count: Mapped[int] = mapped_column(Integer, default=1)
    standard_unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mart3-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped["NormalizedCanonicalProduct"] = relationship(back_populates="variants")
    source_listings: Mapped[list["NormalizedSourceListing"]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_norm_variant_product", "public_product_id"),
        Index("ix_norm_variant_package", "package_quantity", "package_unit", "bundle_count"),
    )


class NormalizedSourceListing(Base):
    """Source-owned listing data; latest URL lives here, not on product static rows."""
    __tablename__ = "normalized_source_listings"

    public_source_listing_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    public_variant_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_product_variants.public_variant_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_unit_text: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mart3-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variant: Mapped["NormalizedProductVariant"] = relationship(back_populates="source_listings")
    offer_events: Mapped[list["NormalizedOfferEvent"]] = relationship(
        back_populates="source_listing", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_norm_listing_variant", "public_variant_id"),
        Index("ix_norm_listing_source", "source_name", "source_record_key"),
    )


class NormalizedOfferEvent(Base):
    """Source-owned price/promotion fact; price can be null for unsafe price states."""
    __tablename__ = "normalized_offer_events"

    public_offer_event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    public_source_listing_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_source_listings.public_source_listing_id", ondelete="CASCADE"),
        nullable=False,
    )
    price_state: Mapped[str] = mapped_column(String(40), nullable=False)
    promotion_type: Mapped[str] = mapped_column(String(40), nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    original_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    event_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    standard_unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_per_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_record_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    raw_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    audit_provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    offer_state: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mart3-v1")

    source_listing: Mapped["NormalizedSourceListing"] = relationship(back_populates="offer_events")
    week_links: Mapped[list["NormalizedOfferWeekLink"]] = relationship(
        back_populates="offer_event", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_norm_offer_listing", "public_source_listing_id"),
        Index("ix_norm_offer_state", "offer_state"),
    )


class NormalizedWeekBucket(Base):
    """Comparison week bucket, shared by many offer events."""
    __tablename__ = "normalized_week_buckets"

    public_week_bucket_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    week_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    week_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False, default="mart3-v1")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    offer_links: Mapped[list["NormalizedOfferWeekLink"]] = relationship(
        back_populates="week_bucket", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("week_start", "week_end", name="uq_norm_week_range"),
        Index("ix_norm_week_start", "week_start"),
    )


class NormalizedOfferWeekLink(Base):
    """Many-to-many linkage between de-duplicated offer events and week buckets."""
    __tablename__ = "normalized_offer_week_links"

    public_offer_event_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_offer_events.public_offer_event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    public_week_bucket_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_week_buckets.public_week_bucket_id", ondelete="CASCADE"),
        primary_key=True,
    )
    observed_min_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_max_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    offer_event: Mapped["NormalizedOfferEvent"] = relationship(back_populates="week_links")
    week_bucket: Mapped["NormalizedWeekBucket"] = relationship(back_populates="offer_links")

    __table_args__ = (
        Index("ix_norm_offer_week", "public_week_bucket_id"),
    )


# ═══════════════════════════════════════════════
# 주간 diff — 사라진 SKU alert
# ═══════════════════════════════════════════════

class AlertDisappearedSku(Base):
    """사라진 SKU alert — 매주 diff 실행 시 이전 주에 있다가 당주 크롤에서 빠진 SKU 기록."""
    __tablename__ = "alert_disappeared_skus"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mart: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # 동일 mart+key 조합이 open 상태로 중복 삽입되지 않도록 partial unique
        # (SQLite UniqueConstraint는 resolved_at IS NULL 필터를 지원하지 않으므로
        #  애플리케이션 레벨에서 중복을 방지하고 인덱스만 생성)
        Index("ix_alert_sku_mart_key", "mart", "source_record_key"),
        Index("ix_alert_sku_detected", "detected_at"),
        Index("ix_alert_sku_resolved", "resolved_at"),
    )


# ═══════════════════════════════════════════════
# 대기열 (Pending Ingestion)
# ═══════════════════════════════════════════════

class IngestionStatus(str, enum.Enum):
    PENDING = "pending"                    # 대기 중 — 검토 필요
    CRAWLER_APPROVED = "crawler_approved"  # 크롤러 관리자 1차 승인
    APPROVED = "approved"                  # DB 관리자 최종 승인 → DB 저장 완료
    REJECTED = "rejected"                  # 거부됨
    PARTIAL = "partial"                    # 일부만 승인


class PendingIngestion(Base):
    """크롤 결과 대기열 — 크롤러→여기→검토→승인→최종 DB"""
    __tablename__ = "pending_ingestions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 크롤 메타데이터
    crawler_name: Mapped[str] = mapped_column(String(100), nullable=False)
    crawl_status: Mapped[str] = mapped_column(String(20))
    strategy_used: Mapped[Optional[str]] = mapped_column(String(50))

    # 데이터
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_type: Mapped[str] = mapped_column(String(50))

    # 품질
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    quality_details: Mapped[Optional[dict]] = mapped_column(JSON)
    errors_json: Mapped[Optional[str]] = mapped_column(Text)

    # 검토 상태
    status: Mapped[IngestionStatus] = mapped_column(
        SAEnum(IngestionStatus), default=IngestionStatus.PENDING,
    )
    crawler_reviewer_notes: Mapped[Optional[str]] = mapped_column(Text)
    db_reviewer_notes: Mapped[Optional[str]] = mapped_column(Text)
    approved_items_json: Mapped[Optional[str]] = mapped_column(Text)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)

    # 타임스탬프
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    crawler_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    db_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 실행 정보
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    source_url: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_pending_status", "status"),
        Index("ix_pending_crawler", "crawler_name"),
        Index("ix_pending_crawled_at", "crawled_at"),
    )


# ═══════════════════════════════════════════════
# 자동 카테고리 분류
# ═══════════════════════════════════════════════

class PendingCategorization(Base):
    """자동 분류 대기열 — 신뢰도 부족 시 관리자 확인 대기."""
    __tablename__ = "pending_categorizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    suggested_category_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    candidates_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    parsed_keywords: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    parsed_attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # "pending" | "approved" | "corrected" | "skipped"
    admin_category_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped["Product"] = relationship("Product", backref="pending_categorizations")

    __table_args__ = (
        Index("ix_pending_cat_status", "status"),
        Index("ix_pending_cat_product", "product_id"),
    )


class CategoryCorrection(Base):
    """관리자 보정 이력 — 피드백 루프용."""
    __tablename__ = "category_corrections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_name_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    wrong_category_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    correct_category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════
# 감사 로그
# ═══════════════════════════════════════════════

class AuditLog(Base):
    """관리자 작업 감사 로그."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[str] = mapped_column(String(100), default="anonymous")
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100))
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    request_id: Mapped[Optional[str]] = mapped_column(String(50))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_user", "user_id"),
    )


# ═══════════════════════════════════════════════
# 핫딜 댓글 & 투표 (크롤링 핫딜용)
# ═══════════════════════════════════════════════

class HotDealComment(Base):
    """크롤링 핫딜 댓글"""
    __tablename__ = "hotdeal_comments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hotdeal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(100), default="익명")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HotDealVote(Base):
    """크롤링 핫딜 투표"""
    __tablename__ = "hotdeal_votes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hotdeal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vote_type: Mapped[str] = mapped_column(String(10), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(50), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("hotdeal_id", "client_ip", name="uq_hotdeal_vote_identity"),
        Index("ix_hotdeal_votes_deal_type", "hotdeal_id", "vote_type"),
    )


# ═══════════════════════════════════════════════
# 장바구니
# ═══════════════════════════════════════════════

class CartItem(Base):
    """사용자 장바구니 — 상품 or 수동 입력 아이템"""
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    item_name: Mapped[str] = mapped_column(String(300), nullable=False)
    item_price: Mapped[float] = mapped_column(Float, nullable=False)
    item_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    store_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="cart_items")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", "store_name", name="uq_cart_user_product_store"),
        Index("ix_cart_user", "user_id"),
    )


# ═══════════════════════════════════════════════
# 찜 목록
# ═══════════════════════════════════════════════

class WishlistItem(Base):
    """사용자 찜 목록 — 가격 하락 알림 지원"""
    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    item_name: Mapped[str] = mapped_column(String(300), nullable=False)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    item_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    store_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price_at_add: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notify_on_drop: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="wishlist_items")

    __table_args__ = (
        Index("ix_wishlist_user", "user_id"),
    )


# ═══════════════════════════════════════════════
# 사용자 활동 (추천용)
# ═══════════════════════════════════════════════

class UserActivity(Base):
    """사용자 활동 로그 — 추천 알고리즘의 입력 데이터"""
    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # view / search / cart_add / wishlist_add / vote
    target_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # product / post / hotdeal
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="activities")

    __table_args__ = (
        Index("ix_activity_user_type_date", "user_id", "activity_type", "created_at"),
    )


# ═══════════════════════════════════════════════
# 정부 농축산물 도매가 앵커 (KAMIS 생산경로 금지 — 별도 공공데이터 출처)
# 출처: 서울시 공공데이터포털 농수산물 도매시장 시세 (GARAK_WHOLESALE 등)
# ═══════════════════════════════════════════════

class GovWholesaleSource(str, enum.Enum):
    """정부 공인 도매가 출처 — KAMIS 생산경로는 포함하지 않음."""
    GARAK_WHOLESALE = "GARAK_WHOLESALE"   # 서울 가락시장 (서울시 공공데이터포털 OA-1170)
    GANGSEO_WHOLESALE = "GANGSEO_WHOLESALE"  # 서울 강서시장
    SEOUL_WHOLESALE = "SEOUL_WHOLESALE"   # 서울시 농수산물 도매시장 통합
    MAFRA_WHOLESALE = "MAFRA_WHOLESALE"   # 농림축산식품부 직접 제공 도매가


class GovWholesalePrice(Base):
    """정부 제공 농축산물 도매가 앵커.

    상한/하한/핫딜 가격 산정의 기준선으로 사용한다.
    KAMIS(aT 소매가 지수)는 생산 경로에서 금지되어 있으므로
    이 테이블은 반드시 서울시·농림부 등 별도 공공데이터 출처만 적재한다.
    """
    __tablename__ = "gov_wholesale_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 품목 정보 (정부 분류 그대로)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 도매시장 정보
    wholesale_market: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[GovWholesaleSource] = mapped_column(SAEnum(GovWholesaleSource), nullable=False)
    api_dataset_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 가격 (원/단위)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 가격 앵커 계산 (avg_price 기준 %)
    upper_bound_rate: Mapped[float] = mapped_column(Float, default=1.30)  # 상한: 도매가 130%
    lower_bound_rate: Mapped[float] = mapped_column(Float, default=0.70)  # 하한: 도매가 70%
    hotdeal_rate: Mapped[float] = mapped_column(Float, default=0.85)       # 핫딜: 도매가 85% 이하

    # 날짜
    recorded_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_gov_wholesale_product_date", "product_name", "recorded_date"),
        Index("ix_gov_wholesale_source", "source"),
        Index("ix_gov_wholesale_market", "wholesale_market"),
    )

    @property
    def upper_bound(self) -> float:
        return round(self.avg_price * self.upper_bound_rate, 0)

    @property
    def lower_bound(self) -> float:
        return round(self.avg_price * self.lower_bound_rate, 0)

    @property
    def hotdeal_threshold(self) -> float:
        return round(self.avg_price * self.hotdeal_rate, 0)


# ═══════════════════════════════════════════════
# 마트 상품 매칭 (multi-mart product match)
# ═══════════════════════════════════════════════

class ProductMatch(Base):
    """동일 상품의 마트별 매칭 테이블.

    한 canonical product_id 를 이마트/홈플러스/롯데마트 등
    N개 마트의 실제 상품 ID에 매핑한다.
    같은 product_id 가 여러 마트에 매칭될 수 있으나,
    (product_id, mart_name) 쌍은 유일해야 한다.
    """
    __tablename__ = "product_matches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    mart_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 이마트 | 홈플러스 | 롯데마트 | 코스트코
    mart_product_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    mart_product_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    mart_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # 매칭 신뢰도 0~1
    match_method: Mapped[str] = mapped_column(String(30), default="manual")
    # "manual" | "auto" | "ai_suggested" | "corrected"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped["Product"] = relationship(
        "Product",
        backref="product_matches",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("product_id", "mart_name", name="uq_product_mart"),
        Index("ix_product_match_product", "product_id"),
        Index("ix_product_match_mart", "mart_name"),
        Index("ix_product_match_active", "is_active"),
    )


# ═══════════════════════════════════════════════
# 매칭 테이블 (Matching Entries)
# 새 크롤 파이프라인: crawler raw → matching_table hit → DB 직행
# miss인 경우만 외부 LLM 분류 후 import. DB가 단일 진실 소스.
# ═══════════════════════════════════════════════

# source 허용 리터럴 — CHECK constraint 및 @validates가 공유하는 단일 진실 집합.
# 이 집합을 줄이거나 변경하면 기존 데이터와 호환성이 깨지므로 마이그레이션이 필요하다.
_MATCHING_ENTRY_VALID_SOURCES = frozenset({"crawler-auto", "human", "external-ai"})


class MatchingEntry(Base):
    """크롤러 raw 상품 → canonical_product_id 매칭 룩업 테이블.

    왜 필요한가:
        AI live pipeline 대신 사전 구축된 매칭 테이블로 전환.
        크롤러가 raw 상품을 정규화(brand|name_core|pack_qty|pack_unit)한 후
        match_key로 이 테이블을 조회하면 hit 시 canonical_product_id를 바로 얻는다.
        miss인 경우만 외부 LLM 분류 파이프라인에 보내고, 결과를 이 테이블에 재적재한다.

    match_key:
        brand|name_core|pack_qty|pack_unit을 파이프 구분자로 연결한 정규화 문자열.
        예: "CJ|햇반|210.000000|g"
        UNIQUE constraint — 같은 정규화 결과가 두 번 등록되지 않도록 DB 레벨에서 보장.

    confidence:
        [0.0, 1.0] 범위 FLOAT. CHECK constraint를 절대 제거하지 말 것.
        0~1 범위 외 값은 매칭 알고리즘 버그 또는 외부 AI 오류 신호이므로 DB에서 차단해야 한다.

    source:
        'crawler-auto' | 'human' | 'external-ai' 세 가지만 허용.
        CHECK constraint + @validates 이중 방어. constraint를 제거하면
        외부 import 시 잘못된 문자열이 DB에 조용히 들어올 수 있다.

    category_id:
        categories.id FK (String(100) — Category PK가 문자열임에 주의).
        태스크 명세에 "INT NULL"로 기술되어 있으나 실제 categories.id는 String(100)이므로
        올바른 FK 참조를 위해 String(100)으로 정의한다.

    keyword_ids:
        JSON list[int] — 관련 키워드 ID 목록. 빈 리스트([])도 유효값이다.

    last_used_at:
        pipeline이 hit할 때마다 갱신. hit_count와 함께 매칭 품질 모니터링에 사용.
    """
    __tablename__ = "matching_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # match_key: brand|name_core|pack_qty|pack_unit 정규화 결과
    # UNIQUE — 동일 정규화 결과를 두 번 등록하면 IntegrityError
    match_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    # 디버깅용 분해 필드 — match_key를 파싱하지 않고 DB에서 바로 확인 가능
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    name_core: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pack_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # canonical_product_id: CanonicalProduct.id soft 참조 (nullable).
    # 현재는 FK 제약 없음 — canonical_products 테이블이 CanonicalBase 소속이라
    # 같은 metadata가 아니므로 DDL FK로 강화하려면 별도 마이그레이션 필요.
    # null 허용: 외부 AI 분류 완료 전에는 canonical_id가 미정임.
    canonical_product_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # category_id: categories.id FK
    # 주의: Category.id는 String(100) (예: "meat.pork.belly") — INT가 아님
    category_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("categories.id"), nullable=True
    )

    # keyword_ids: list[int] JSON. 빈 리스트([])도 정상값. NULL ≠ []이므로 구분 필요.
    keyword_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # confidence: 매칭 신뢰도 [0.0, 1.0].
    # CHECK constraint 절대 제거 금지 — 범위 위반은 알고리즘 버그 신호.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # source: 매칭 출처. 허용값 = _MATCHING_ENTRY_VALID_SOURCES.
    # CHECK constraint 절대 제거 금지 — 외부 LLM import 시 오타 차단이 목적.
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    # 타임스탬프 (UTC timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # last_used_at: pipeline hit 시마다 갱신. NULL = 아직 한 번도 사용 안 됨.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # hit_count: 매칭 성공 횟수 — 품질 모니터링 및 miss 임계치 판단에 활용
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # notes: 운영자 메모 (nullable)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── RD8 L3 추가 컬럼 ────────────────────────────────────────────────────────
    # pack_unit_kind: 단위 분류 캐시 (migration f3c4d5e6f7a8에서 DB 컬럼 추가됨)
    pack_unit_kind: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # source_record_key: 크롤러 원본 레코드 키. 멱등성 보장용.
    source_record_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # aliases: 동일 항목의 표기 변형 목록. JSON list[str]. 최대 50개.
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        # confidence 범위 CHECK — 절대 제거 금지 (위 docstring 참조)
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_matching_confidence_range",
        ),
        # source enum CHECK — 절대 제거 금지 (위 docstring 참조)
        CheckConstraint(
            "source IN ('crawler-auto', 'human', 'external-ai')",
            name="ck_matching_source_enum",
        ),
        Index("ix_matching_category", "category_id"),
        Index("ix_matching_source", "source"),
    )

    @validates("source")
    def validate_source(self, key: str, value: str) -> str:
        """Python ORM 레벨에서 source 값을 검증한다.

        CHECK constraint가 DB 레벨을 방어하고,
        이 validator가 Python 레벨을 방어한다 (이중 방어).
        외부 AI import 스크립트가 잘못된 source 값을 넘길 경우
        DB flush 이전에 ValueError를 발생시켜 빠른 실패를 보장한다.
        """
        if value not in _MATCHING_ENTRY_VALID_SOURCES:
            raise ValueError(
                f"MatchingEntry.source 허용값: {sorted(_MATCHING_ENTRY_VALID_SOURCES)}, "
                f"받은 값: {value!r}"
            )
        return value


# ═══════════════════════════════════════════════
# RD8 L3: Import 감사 로그
# ═══════════════════════════════════════════════

class ImportsAudit(Base):
    """외부 LLM 분류 결과 import 이력 감사 로그.

    apply_import() 호출마다 한 행이 기록된다.
    같은 파일을 2회 apply하면 audit 행은 2개 생기지만 DB 상태는 변화 없음 (멱등성).
    """
    __tablename__ = "imports_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_type: Mapped[str] = mapped_column(String(30), nullable=False)   # matching|categories|products
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)   # sha256 hex (64자)
    importer: Mapped[str] = mapped_column(String(255), nullable=False)   # email 또는 "anonymous"
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_counts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_imports_audit_file_hash", "file_hash"),
        Index("ix_imports_audit_timestamp", "timestamp"),
        Index("ix_imports_audit_file_type", "file_type"),
    )


# ═══════════════════════════════════════════════
# RD8 L3: 카테고리 검토 큐
# ═══════════════════════════════════════════════

class CategoryReviewQueue(Base):
    """외부 LLM이 제안한 신규 카테고리 — 운영자 검토 대기 큐.

    신규 카테고리는 categories 테이블에 즉시 쓰지 않는다.
    운영자가 approve 하면 별도 승인 API를 통해 DB에 반영된다.
    """
    __tablename__ = "category_review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposed_id: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    label_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    similar_existing: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending | approved | rejected
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_cat_review_status", "status"),
        Index("ix_cat_review_proposed_id", "proposed_id"),
        UniqueConstraint("proposed_id", "source_file_hash", name="uq_cat_review_proposal"),
    )
