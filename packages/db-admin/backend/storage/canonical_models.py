"""
WalletSavior Phase B — 표준 도메인 ORM 모델 (SQLAlchemy 2.x).

왜 이 파일인가:
    packages/shared/core/canonical_models.py 의 Pydantic 모델은 전송·검증용 DTO이고,
    이 파일의 SQLAlchemy 모델은 실제 DB 스키마다.
    같은 구조지만 역할이 다르므로 파일을 분리한다.

왜 legacy models.py의 Base를 쓰지 않는가:
    legacy Base는 Product·DiscountHistory 등 기존 테이블을 담고 있다.
    canonical 테이블을 같은 Base에 넣으면 legacy 마이그레이션과 canonical 마이그레이션이
    엉켜 rollback 단위 분리가 불가능해진다.
    CanonicalBase를 분리해서 canonical 테이블만 독립적으로 create_all·drop_all 할 수 있다.

레거시 DiscountItem/Product 테이블은 건드리지 않는다. 점진 마이그레이션 대상.

bootstrap_canonical_tables(engine) 을 앱 시작 시 호출하거나,
Alembic revision에서 CanonicalBase.metadata를 참조해 마이그레이션을 생성한다.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Enum as SAEnum,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ══════════════════════════════════════════════════════
# 독립 Base — legacy Base와 격리
# ══════════════════════════════════════════════════════

class CanonicalBase(DeclarativeBase):
    """
    canonical 테이블 전용 Base — legacy Base(storage/models.py)와 분리.

    왜 분리하는가:
        canonical 스키마는 Phase B~E에 걸쳐 독립적으로 진화한다.
        legacy 테이블과 같은 metadata를 공유하면
        alembic autogenerate가 legacy 변경을 canonical 마이그레이션 파일에 섞어버린다.
    """
    pass


# ══════════════════════════════════════════════════════
# Python Enums (SAEnum과 1:1 대응)
# ══════════════════════════════════════════════════════

class MartKindEnum(str, enum.Enum):
    """
    마트 식별 DB enum.
    왜 VARCHAR가 아닌가: CHECK constraint 자동 생성 + ORM 레벨 검증이 목적.
    마트 추가 시 enum 값 추가 + alembic migration 한 번으로 끝난다.
    """
    EMART = "EMART"
    HOMEPLUS = "HOMEPLUS"
    LOTTEMART = "LOTTEMART"
    COSTCO = "COSTCO"
    COUPANG = "COUPANG"


class UnitPriceBasisEnum(str, enum.Enum):
    """
    단위가 기준 DB enum — PER_100G·PER_EACH 등.
    왜 enum인가: 단위가 비교는 기준이 맞아야만 의미 있다.
    잘못된 값(오타 등)이 DB에 들어가는 것을 enum constraint로 막는다.
    """
    PER_100G = "per_100g"
    PER_1KG = "per_1kg"
    PER_100ML = "per_100ml"
    PER_1L = "per_1l"
    PER_EACH = "per_each"
    UNKNOWN = "unknown"


class ReviewReasonEnum(str, enum.Enum):
    """
    검토 대기열 사유 enum — 운영자 대시보드 필터링에 사용.
    """
    CATEGORY_UNKNOWN = "CATEGORY_UNKNOWN"
    PRODUCT_AMBIGUOUS = "PRODUCT_AMBIGUOUS"
    UNIT_UNPARSABLE = "UNIT_UNPARSABLE"
    PRICE_INVALID = "PRICE_INVALID"


# ══════════════════════════════════════════════════════
# CategoryNode
# ══════════════════════════════════════════════════════

class CategoryNode(CanonicalBase):
    """
    내부 표준 카테고리 트리.

    왜 자기 참조 FK(parent_id → id)인가:
        깊이가 1~4로 가변적인 계층을 depth-agnostic하게 표현하기 위해.
        Closure Table·Nested Set 같은 대안도 있지만,
        B3 규모(수백 노드)에서는 adjacency list로 충분하다.
        재귀 CTE로 전체 경로 조회가 가능하다.

    path:
        "/정육ㆍ계란/계란ㆍ메추리알/일반란" — 슬래시 구분 한글 경로.
        id가 변경돼도 path는 바뀌지 않아야 한다(URL-safe slug와 다름).
        B3 카테고리매핑 결과를 적재할 때 path로 중복 체크.

    level:
        1=대분류, 2=중분류, 3=소분류, 4=세분류.
        홈플러스의 5단계(rcate·lcate·mcate·scate·dcate)에서
        rcate·lcate가 같은 이름인 경우가 많아 4단계로 압축.
    """
    __tablename__ = "canonical_category_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("canonical_category_nodes.id"), nullable=True
    )
    name_kr: Mapped[str] = mapped_column(String(200), nullable=False)
    name_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    # self-referential
    children: Mapped[list["CategoryNode"]] = relationship(
        "CategoryNode", back_populates="parent", foreign_keys=[parent_id]
    )
    parent: Mapped[Optional["CategoryNode"]] = relationship(
        "CategoryNode", back_populates="children", remote_side="CategoryNode.id",
        foreign_keys=[parent_id],
    )
    products: Mapped[list["CanonicalProduct"]] = relationship(
        "CanonicalProduct", back_populates="category_node"
    )


# ══════════════════════════════════════════════════════
# CanonicalProduct
# ══════════════════════════════════════════════════════

class CanonicalProduct(CanonicalBase):
    """
    마트 간 비교의 기본 단위 레코드.

    id:
        SHA1(brand|name_core|pack_qty|pack_unit) 40자 hex.
        왜 autoincrement int가 아닌가:
            크롤러가 canonical id를 "계산"해서 upsert할 수 있어야 한다.
            int pk를 쓰면 SELECT → INSERT 두 번이 필요하다.
            hash pk로 INSERT OR IGNORE + UPDATE 한 번으로 멱등 upsert 가능.

    pack_unit:
        현재 VARCHAR — B2 단위 파서 완료 후 UnitKindEnum으로 교체 예정.
        그때 alembic migration이 필요하다.

    category_path_internal_id:
        nullable FK → CategoryNode.id.
        B3 카테고리매핑 전까지 null. null이면 ProductReviewQueue에 CATEGORY_UNKNOWN 등록.
    """
    __tablename__ = "canonical_products"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # SHA1 hex
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    name_core: Mapped[str] = mapped_column(String(500), nullable=False)
    pack_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pack_unit: Mapped[str] = mapped_column(String(50), nullable=False, default="개")
    category_path_internal_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("canonical_category_nodes.id"), nullable=True
    )
    representative_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    category_node: Mapped[Optional["CategoryNode"]] = relationship(
        "CategoryNode", back_populates="products"
    )
    sku_aliases: Mapped[list["MartSkuAlias"]] = relationship(
        "MartSkuAlias", back_populates="canonical_product", cascade="all, delete-orphan"
    )
    price_observations: Mapped[list["PriceObservation"]] = relationship(
        "PriceObservation", back_populates="canonical_product", cascade="all, delete-orphan"
    )
    review_queue_items: Mapped[list["ProductReviewQueue"]] = relationship(
        "ProductReviewQueue", back_populates="canonical_product"
    )


# ══════════════════════════════════════════════════════
# MartSkuAlias
# ══════════════════════════════════════════════════════

class MartSkuAlias(CanonicalBase):
    """
    마트별 SKU ↔ CanonicalProduct 매핑.

    UNIQUE(mart, mart_item_id):
        같은 마트의 같은 상품 id가 두 번 등록되는 것을 DB 레벨에서 방지.
        upsert 시 이 제약으로 on_conflict를 처리한다.

    mart:
        왜 string이 아닌 enum인가:
            마트 식별은 JOIN·GROUP BY 키로 자주 쓰인다.
            typo로 "EMART"·"Emart"가 섞이면 집계가 깨진다.
            enum constraint로 DB 레벨에서 차단.

    source_url:
        nullable — 코스트코는 /p/{id} 상대경로만 있고 base URL이 고정이지만,
        운영 환경에서 도메인이 바뀔 수 있으므로 full URL로 저장 권장.
        이마트 itemUrl은 ssg.com 기준이므로 그대로 저장.
    """
    __tablename__ = "canonical_mart_sku_aliases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("canonical_products.id"), nullable=False
    )
    mart: Mapped[MartKindEnum] = mapped_column(
        SAEnum(MartKindEnum, name="mart_kind_enum"), nullable=False
    )
    mart_item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    mart_item_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )

    canonical_product: Mapped["CanonicalProduct"] = relationship(
        "CanonicalProduct", back_populates="sku_aliases"
    )

    __table_args__ = (
        UniqueConstraint("mart", "mart_item_id", name="uq_mart_sku"),
    )


# ══════════════════════════════════════════════════════
# PriceObservation
# ══════════════════════════════════════════════════════

class PriceObservation(CanonicalBase):
    """
    특정 마트·특정 시점의 가격 스냅샷.

    INDEX(canonical_id, mart, observed_at DESC):
        "이 상품의 A마트 최근 가격 이력" 쿼리가 가장 빈번하다.
        composite index로 이 쿼리를 커버링.

    raw_payload_hash:
        SHA1(원본 payload JSON) — raw 데이터 추적 키.
        raw blob 자체는 별도 raw_payloads 테이블에 저장(옵션).
        이 hash로 raw_payloads.hash를 lookup하면 원본 복원 가능.
        절대 raw를 잃지 않는다는 원칙을 DB 설계 수준에서 보장.

    event_labels:
        JSON array — 홈플러스 eventFlagList[label]("상품할인","마일리지"),
        롯데마트 offers[description]("[농할] 행복생생란 700원 할인").
        마트마다 형식이 달라 정규화하기 어려우므로 raw 텍스트 배열로 보존.
    """
    __tablename__ = "canonical_price_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("canonical_products.id"), nullable=False
    )
    mart: Mapped[MartKindEnum] = mapped_column(
        SAEnum(MartKindEnum, name="mart_kind_enum"), nullable=False
    )
    regular_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sale_price: Mapped[int] = mapped_column(Integer, nullable=False)
    on_sale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discount_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_price_normalized: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price_basis: Mapped[UnitPriceBasisEnum] = mapped_column(
        SAEnum(UnitPriceBasisEnum, name="unit_price_basis_enum"),
        nullable=False,
        default=UnitPriceBasisEnum.UNKNOWN,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_payload_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    event_labels: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    canonical_product: Mapped["CanonicalProduct"] = relationship(
        "CanonicalProduct", back_populates="price_observations"
    )

    __table_args__ = (
        Index(
            "ix_price_obs_canonical_mart_time",
            "canonical_id", "mart", "observed_at",
        ),
    )


# ══════════════════════════════════════════════════════
# ProductReviewQueue
# ══════════════════════════════════════════════════════

class ProductReviewQueue(CanonicalBase):
    """
    자동 처리 불가 상품 검토 대기열.

    raw_payload:
        JSON 컬럼 — 크롤러 원본 데이터 전체.
        SQLite는 JSON을 TEXT로, PostgreSQL은 JSONB로 저장.
        이 데이터로 언제든 canonicalize를 재시도할 수 있어야 한다.

    suggested_canonical_id:
        nullable — AI 추천 canonical id.
        운영자가 confirmed_at(=resolved_at)을 찍으면 MartSkuAlias에 반영.
        운영자가 다른 canonical_id를 선택해도 되므로 "suggested"다.

    resolver_user_id:
        nullable FK는 아님 — users 테이블이 별도 DB/서비스에 있을 수 있으므로
        application-level reference로만 관리한다.
    """
    __tablename__ = "canonical_product_review_queue"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_mart: Mapped[MartKindEnum] = mapped_column(
        SAEnum(MartKindEnum, name="mart_kind_enum"), nullable=False
    )
    reason: Mapped[ReviewReasonEnum] = mapped_column(
        SAEnum(ReviewReasonEnum, name="review_reason_enum"), nullable=False
    )
    suggested_canonical_id: Mapped[Optional[str]] = mapped_column(
        String(40), ForeignKey("canonical_products.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolver_user_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    canonical_product: Mapped[Optional["CanonicalProduct"]] = relationship(
        "CanonicalProduct", back_populates="review_queue_items"
    )


# ══════════════════════════════════════════════════════
# Bootstrap helper
# ══════════════════════════════════════════════════════

def bootstrap_canonical_tables(engine: Engine) -> None:
    """
    canonical 테이블을 생성한다 (존재하면 skip — CREATE TABLE IF NOT EXISTS).

    사용처:
        - 개발/테스트: create_engine("sqlite:///:memory:") 후 이 함수 호출.
        - 운영: alembic revision으로 마이그레이션 생성·적용 권장.
          이 함수는 alembic 없는 환경(CI, 단위 테스트)용 fallback이다.
    """
    CanonicalBase.metadata.create_all(engine)
