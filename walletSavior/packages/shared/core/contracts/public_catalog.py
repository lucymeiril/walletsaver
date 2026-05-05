"""
public catalog/pricing DB와 community DB 사이의 공유 계약.

public catalog/pricing DB는 승인된 상품/가격 read model을 제공하고, community/user DB는
쓰기 많은 사용자 데이터를 별도로 관리한다. 물리 DB가 분리되므로 community 쪽은
stable public ID만 저장하고 API/검증 잡이 참조 무결성을 확인한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class OfferState(str, Enum):
    """public SaleOffer의 사용자 노출 상태."""

    ACTIVE = "active"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    HIDDEN = "hidden"


class ReferenceHealth(str, Enum):
    """물리적으로 분리된 DB 간 public ID 검증 결과."""

    OK = "ok"
    MISSING = "missing"
    SUPERSEDED = "superseded"
    INACTIVE = "inactive"


class PublicCatalogProduct(BaseModel):
    """public catalog DB의 canonical 대표상품 read model."""

    public_product_id: str = Field(min_length=3, max_length=120)
    canonical_name: str = Field(min_length=1, max_length=255)
    brand: Optional[str] = Field(default=None, max_length=120)
    category_id: Optional[str] = Field(default=None, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    projection_version: str = Field(min_length=1)
    is_active: bool = True
    updated_at: datetime = Field(default_factory=datetime.now)


class PublicProductVariant(BaseModel):
    """public catalog DB의 비교 가능한 variant read model."""

    public_variant_id: str = Field(min_length=3, max_length=120)
    public_product_id: str = Field(min_length=3, max_length=120)
    variant_name: str = Field(min_length=1, max_length=255)
    package_quantity: Optional[float] = Field(default=None, gt=0)
    package_unit: Optional[str] = Field(default=None, max_length=40)
    display_unit: Optional[str] = Field(default=None, max_length=80)
    bundle_count: int = Field(default=1, ge=1)
    standard_unit: Optional[str] = Field(default=None, max_length=40)
    attributes: dict[str, Any] = Field(default_factory=dict)
    projection_version: str = Field(min_length=1)
    is_active: bool = True


class PublicSaleOffer(BaseModel):
    """public catalog/pricing DB의 source-specific 가격 이벤트."""

    public_offer_id: str = Field(min_length=3, max_length=120)
    public_variant_id: str = Field(min_length=3, max_length=120)
    source_name: str = Field(min_length=1, max_length=120)
    source_record_key: Optional[str] = Field(default=None, max_length=200)
    source_title: str = Field(min_length=1, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    image_url: Optional[str] = Field(default=None, max_length=1000)
    price: int = Field(ge=0)
    original_price: Optional[int] = Field(default=None, ge=0)
    discount_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    event_name: Optional[str] = Field(default=None, max_length=255)
    standard_unit_price: Optional[float] = Field(default=None, ge=0.0)
    price_per_100g: Optional[float] = Field(default=None, ge=0.0)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    raw_record_id: Optional[str] = Field(default=None, max_length=200)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    audit_provenance: dict[str, Any] = Field(default_factory=dict)
    crawled_at: datetime = Field(default_factory=datetime.now)
    offer_state: OfferState = OfferState.ACTIVE
    projection_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates_and_discount(self) -> "PublicSaleOffer":
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be >= valid_from")
        if self.original_price is not None and self.discount_rate is None and self.original_price > 0:
            if self.price <= self.original_price:
                self.discount_rate = round((self.original_price - self.price) / self.original_price, 4)
        return self


class CommunityProductReference(BaseModel):
    """
    community/user DB가 catalog DB 상품을 참조할 때 저장하는 값.

    물리 DB 분리 때문에 FK를 걸지 않고 stable public ID만 저장한다. 제목/가격 스냅샷은
    정책상 저장하지 않으며, 검증 잡이 public ID의 상태를 확인한다.
    """

    reference_id: str = Field(min_length=1)
    owner_entity_type: str = Field(min_length=1)
    owner_entity_id: str = Field(min_length=1)
    public_product_id: str = Field(min_length=3, max_length=120)
    created_at: datetime = Field(default_factory=datetime.now)
    last_checked_at: Optional[datetime] = None
    health: ReferenceHealth = ReferenceHealth.OK


class ProjectionRunContract(BaseModel):
    """control DB 승인 데이터를 public catalog/pricing DB로 publish한 실행 기록."""

    projection_version: str = Field(min_length=1)
    source_control_run_id: str = Field(min_length=1)
    product_count: int = Field(ge=0)
    variant_count: int = Field(ge=0)
    offer_count: int = Field(ge=0)
    snapshot_checksum: str = Field(min_length=1)
    published_by: str = Field(min_length=1)
    published_at: datetime = Field(default_factory=datetime.now)
    rollback_of_version: Optional[str] = None


class CatalogDeltaManifest(BaseModel):
    """브라우저 캐시가 변경분만 받을 때 쓰는 snapshot/delta 계약."""

    from_version: Optional[str] = None
    to_version: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    changed_products: int = Field(ge=0)
    changed_variants: int = Field(ge=0)
    changed_offers: int = Field(ge=0)
    removed_public_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
