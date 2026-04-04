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

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    Index, UniqueConstraint, JSON, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    posts: Mapped[list["Post"]] = relationship(back_populates="author", cascade="all, delete-orphan")
    comments: Mapped[list["Comment"]] = relationship(back_populates="author", cascade="all, delete-orphan")
    votes: Mapped[list["Vote"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    favorites: Mapped[list["Favorite"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    price_alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="user", cascade="all, delete-orphan")


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
    """정부 공인 도매가 + 소매 공식 가격 (기준가)"""
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

    __table_args__ = (
        Index("ix_keywords_word", "word"),
        # 인기 검색어 정렬용 — search_count DESC 빈번 사용
        Index("ix_keywords_active_count", "is_active", "search_count"),
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
