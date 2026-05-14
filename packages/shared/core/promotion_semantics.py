"""Source-owned price/promotion semantics shared by AI, DB admin, and public contracts."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite
from typing import Any


class PriceState(str, Enum):
    """Whether a source provided a numeric price that is safe to expose/use."""

    NORMAL = "normal"
    PRICE_HIDDEN = "price_hidden"
    DISCOUNT_RATE_ONLY = "discount_rate_only"
    SALE_PRICE_ONLY = "sale_price_only"
    ORIGINAL_PRICE_ONLY = "original_price_only"

    # Backward-compatible aliases for older public contract callers.
    VISIBLE = "normal"
    HIDDEN = "price_hidden"
    MISSING = "price_hidden"

    @classmethod
    def _missing_(cls, value: object) -> "PriceState | None":
        legacy = {
            "visible": cls.NORMAL,
            "hidden": cls.PRICE_HIDDEN,
            "missing": cls.PRICE_HIDDEN,
        }
        return legacy.get(value)


class PromotionType(str, Enum):
    """Promotion semantics without converting ambiguous events into fake prices."""

    FINAL_PRICE = "final_price"
    WAS_NOW_PRICE = "was_now_price"
    RATE_OFF_UNCLEAR = "rate_off_unclear"
    CHECKOUT_DISCOUNT = "checkout_discount"
    BUY_X_GET_Y = "buy_x_get_y"
    BUNDLE_PRICE = "bundle_price"
    UNKNOWN = "unknown"


COMPARABLE_PROMOTION_TYPES = {
    PromotionType.FINAL_PRICE,
    PromotionType.WAS_NOW_PRICE,
    PromotionType.BUNDLE_PRICE,
}
SAFE_DISCOUNT_CALC_PROMOTION_TYPES = {PromotionType.WAS_NOW_PRICE}


def _finite_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number


def confirmed_price_or_none(value: Any) -> int | None:
    """Return a source-confirmed positive price, never 0/negative/infinity placeholders."""

    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return int(number)


def discount_rate_or_none(value: Any) -> float | None:
    """Return a source-provided fractional discount rate (0..1), or None."""

    number = _finite_number(value)
    if number is None or number < 0 or number > 1:
        return None
    return number


def infer_price_state(
    *,
    current_price: Any = None,
    original_price: Any = None,
    discount_rate: Any = None,
) -> PriceState:
    current = confirmed_price_or_none(current_price)
    original = confirmed_price_or_none(original_price)
    rate = discount_rate_or_none(discount_rate)
    if current is not None and original is not None:
        return PriceState.NORMAL
    if current is not None:
        return PriceState.SALE_PRICE_ONLY
    if original is not None:
        return PriceState.ORIGINAL_PRICE_ONLY
    if rate is not None:
        return PriceState.DISCOUNT_RATE_ONLY
    return PriceState.PRICE_HIDDEN


@dataclass(frozen=True)
class PromotionPriceFacts:
    """Normalized, calculation-safe price facts owned by the source record."""

    price_state: PriceState
    promotion_type: PromotionType = PromotionType.UNKNOWN
    current_price: int | None = None
    original_price: int | None = None
    discount_rate: float | None = None

    @classmethod
    def from_source(
        cls,
        *,
        current_price: Any = None,
        original_price: Any = None,
        discount_rate: Any = None,
        price_state: PriceState | str | None = None,
        promotion_type: PromotionType | str | None = None,
    ) -> "PromotionPriceFacts":
        current = confirmed_price_or_none(current_price)
        original = confirmed_price_or_none(original_price)
        rate = discount_rate_or_none(discount_rate)
        state = PriceState(price_state) if price_state else infer_price_state(
            current_price=current,
            original_price=original,
            discount_rate=rate,
        )
        promo = PromotionType(promotion_type) if promotion_type else PromotionType.UNKNOWN
        if state == PriceState.PRICE_HIDDEN:
            current = None
        return cls(
            price_state=state,
            promotion_type=promo,
            current_price=current,
            original_price=original,
            discount_rate=rate,
        )

    @property
    def comparable_price(self) -> int | None:
        if (
            self.current_price is not None
            and self.price_state in {PriceState.NORMAL, PriceState.SALE_PRICE_ONLY}
            and self.promotion_type in COMPARABLE_PROMOTION_TYPES
        ):
            return self.current_price
        return None

    @property
    def comparable_price_available(self) -> bool:
        return self.comparable_price is not None

    def with_safe_calculations(self) -> "PromotionPriceFacts":
        """Derive only unambiguous was/now discount rate; never derive hidden prices."""

        if self.discount_rate is not None:
            return self
        if self.promotion_type not in SAFE_DISCOUNT_CALC_PROMOTION_TYPES:
            return self
        if self.current_price is None or self.original_price is None:
            return self
        if self.original_price <= 0 or self.current_price > self.original_price:
            return self
        return replace(
            self,
            discount_rate=round((self.original_price - self.current_price) / self.original_price, 4),
        )


def comparable_price_or_none(facts: PromotionPriceFacts | dict[str, Any] | Any) -> int | None:
    if isinstance(facts, PromotionPriceFacts):
        return facts.comparable_price
    if isinstance(facts, dict):
        return PromotionPriceFacts.from_source(
            current_price=facts.get("current_price", facts.get("price")),
            original_price=facts.get("original_price"),
            discount_rate=facts.get("discount_rate"),
            price_state=facts.get("price_state"),
            promotion_type=facts.get("promotion_type"),
        ).comparable_price
    return confirmed_price_or_none(facts)
