"""P0#10, #16 — effective_price_type + 단위 정규화 + UTC/TZ 컬럼.

db-FINAL §2-3 / §2-7. observed_at_utc + source_timezone + local_sale_date 필수.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator


class EffectivePriceType(str, Enum):
    BASE = "base"
    SALE = "sale"
    COUPON = "coupon"
    MEMBERSHIP = "membership"
    CARD = "card"
    BUNDLE = "bundle"


class UnitBasis(str, Enum):
    PER_100G = "per_100g"
    PER_1KG = "per_1kg"
    PER_EACH = "per_each"
    PER_1L = "per_1l"
    PER_100ML = "per_100ml"


class StoreScope(str, Enum):
    ONLINE_NATIONAL = "online_national"
    ONLINE_REGION = "online_region"
    OFFLINE_STORE = "offline_store"


def normalize_unit(
    price_krw: float,
    pack_qty: float,
    pack_unit: str,
) -> tuple[Optional[int], Optional[UnitBasis], float]:
    """raw pack -> normalized unit price.

    반환 (unit_price, basis, confidence).
    g→per_100g, kg→per_1kg (kg 단위는 그대로 1kg당), ml/L 유사. 인식 못 하면 (None, None, 0.0).

    의도: 마트별 표기 차이(100g / 100ml / kg / 봉지)를 분위수 계산 가능한 단일 축으로 통일.
    """
    if pack_qty <= 0 or not pack_unit:
        return (None, None, 0.0)
    unit = pack_unit.strip().lower()
    if unit in ("g", "그램", "gram"):
        # per_100g
        return (round(price_krw * 100.0 / pack_qty), UnitBasis.PER_100G, 1.0)
    if unit in ("kg", "킬로", "킬로그램"):
        return (round(price_krw / pack_qty), UnitBasis.PER_1KG, 1.0)
    if unit in ("ml", "밀리", "밀리리터"):
        return (round(price_krw * 100.0 / pack_qty), UnitBasis.PER_100ML, 1.0)
    if unit in ("l", "리터", "ℓ"):
        return (round(price_krw / pack_qty), UnitBasis.PER_1L, 1.0)
    if unit in ("개", "ea", "each", "팩", "봉지", "병", "캔"):
        return (round(price_krw / pack_qty), UnitBasis.PER_EACH, 0.9)
    return (None, None, 0.0)


class PriceObservation(BaseModel):
    """관측 한 건. 조건부 가격·UTC·local_sale_date 풀세트."""

    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    stable_id: str
    mart: str

    raw_price: int = Field(ge=0)
    display_price_text: str = ""

    effective_price_type: EffectivePriceType = EffectivePriceType.BASE
    min_purchase_qty: int = Field(default=1, ge=1)
    requires_membership: bool = False
    requires_card: Optional[str] = None
    coupon_code: Optional[str] = None
    bundle_description: Optional[str] = None

    normalized_unit_price: Optional[int] = None
    normalized_unit_basis: Optional[UnitBasis] = None
    normalization_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    region_hint: Optional[str] = None
    store_scope: StoreScope = StoreScope.ONLINE_NATIONAL

    # P0#16 — 타임존 풀세트
    observed_at_utc: datetime
    source_timezone: str = "Asia/Seoul"
    local_sale_date: date

    suspicious_regular_jump: bool = False

    @model_validator(mode="after")
    def _ensure_utc(self) -> "PriceObservation":
        # observed_at_utc는 naive 거부 — UTC 명시 강제.
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be tz-aware (UTC)")
        if self.observed_at_utc.utcoffset() != timezone.utc.utcoffset(self.observed_at_utc):
            # UTC offset이 0이 아닌 timezone-aware도 허용은 하되 의도적 정책상 UTC로 표준화 권장.
            # 여기서는 허용. 정책 강제는 ingestion 레이어에서.
            pass
        return self
