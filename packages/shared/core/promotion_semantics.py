"""Source-owned price/promotion semantics shared by AI, DB admin, and public contracts."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from math import isfinite
import re
from typing import Any, Mapping


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
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(number):
        return None
    return number


def confirmed_price_or_none(value: Any) -> int | float | None:
    """Return a source-confirmed positive price, never 0/negative/infinity placeholders."""

    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return int(number) if number.is_integer() else number


def bound_homeplus_product_currency(node: Any, *, native: str, title: str,
                                   source_url: str, price: Any) -> str | None:
    """Currency of this source quote, never a product matching attribute."""
    if not isinstance(node, Mapping) or node.get("@type") != "Product":
        return None
    offer = node.get("offers")
    if (node.get("mpn") != native or node.get("name") != title
            or not isinstance(offer, Mapping) or offer.get("@type") != "Offer"
            or offer.get("url") != source_url or offer.get("priceCurrency") != "KRW"
            or confirmed_price_or_none(price) is None
            or confirmed_price_or_none(offer.get("price")) != confirmed_price_or_none(price)):
        return None
    return "KRW"


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
    current_price: int | float | None = None
    original_price: int | float | None = None
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
    def comparable_price(self) -> int | float | None:
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


def comparable_price_or_none(facts: PromotionPriceFacts | dict[str, Any] | Any) -> int | float | None:
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


def buy_x_get_y_terms_or_none(conditions: Any) -> tuple[int, int] | None:
    """Return confirmed paid/free package counts, never infer missing promotion terms."""

    if not isinstance(conditions, Mapping):
        return None
    buy = conditions.get("buy_quantity")
    free = conditions.get("free_quantity")
    if type(buy) is not int or type(free) is not int or buy <= 0 or free <= 0:
        return None
    return buy, free


def conditional_selection_facts_or_none(event_name: Any) -> dict[str, Any] | None:
    """Keep explicit selection terms without claiming a payable basket price."""

    if not isinstance(event_name, str):
        return None
    free = re.fullmatch(r"([1-9]\d*)개씩 (?:골라 )?담으면, 그 중 1개는 무료", event_name)
    discount = re.fullmatch(r"([1-9]\d*)개씩 (?:골라 )?담으면, (\d+(?:\.\d+)?)% 할인", event_name)
    cash = re.fullmatch(r"([1-9]\d*)개씩 (?:골라 )?담으면, ((?:[1-9]\d{0,2}(?:,\d{3})+)|(?:[1-9]\d*))원( 할인)?", event_name)
    purchase = re.fullmatch(r"([1-9]\d*)개 담으면, ((?:[1-9]\d{0,2}(?:,\d{3})+)|(?:[1-9]\d*))원에 구매 \(최대 ([1-9]\d*)개까지 행사/할인 적용\)", event_name)
    match = free or discount or cash or purchase
    if match is None or int(match[1]) < 2:
        return None
    facts = {"condition_text": event_name, "required_selection_quantity": int(match[1]),
             "basket_selection_required": True, "payable_price_unconfirmed": True}
    if purchase:
        if int(purchase[3]) < int(purchase[1]):
            return None
        return {**facts, 'source_condition_kind': 'selected_basket_total',
                'conditional_basket_total_won': int(purchase[2].replace(',', '')),
                'eligible_selection_unconfirmed': True,
                'source_event_maximum_quantity': int(purchase[3])}
    if free:
        facts.update(source_condition_kind="selected_free_item", conditional_free_quantity=1,
                     free_item_valuation_unconfirmed=True)
    elif discount:
        percent = float(discount[2])
        if not 0 < percent < 100:
            return None
        facts.update(source_condition_kind="selected_percentage_discount",
                     conditional_discount_percent=percent, discount_application_unconfirmed=True)
    elif cash[3]:
        facts.update(source_condition_kind="selected_won_discount",
                     conditional_discount_won=int(cash[2].replace(",", "")),
                     discount_application_unconfirmed=True)
    else:
        facts.update(source_condition_kind="selected_basket_total",
                     conditional_basket_total_won=int(cash[2].replace(",", "")),
                     eligible_selection_unconfirmed=True)
    return facts


def conditional_program_facts_or_none(event_name: Any) -> dict[str, Any] | None:
    """Preserve named program wording without assuming eligibility or payment."""

    if not isinstance(event_name, str):
        return None
    if event_name == "농할 할인 20%_결제시 자동적용":
        program, stage, method, application = "농할", "checkout", "automatic", "결제시 자동적용"
    elif event_name == "수산대전 20% 할인":
        program, stage, method, application = "수산대전", None, None, None
    else:
        return None
    return {"condition_text": event_name,
            "source_condition_kind": "named_program_percentage_discount",
            "source_program_name": program, "conditional_discount_percent": 20,
            "payable_price_unconfirmed": True, "discount_application_unconfirmed": True,
            "program_eligibility_unconfirmed": True, "benefit_cap": None,
            "discount_calculation_basis": None,
            "source_declared_application_stage": stage,
            "source_declared_application_method": method,
            "source_application_text": application}


def conditional_basket_spend_facts_or_none(event_name: Any) -> dict[str, Any] | None:
    """Retain declared basket thresholds without qualifying a buyer or pricing an item."""
    if not isinstance(event_name, str):
        return None
    amount = r"(\d+(?:\.\d+)?)"
    patterns = (
        (rf"\[(동서식품)\] {amount}만(↑) {amount}천원 (할인)", "won", None),
        (rf"\[(동원)\] {amount}만원 (이상) 구매시, {amount}천원 (즉시할인)", "won", None),
        (rf"\[(행사카드)\] 명절세트 {amount}만(↑) {amount}% (할인)", "percent", "행사카드"),
        (rf"(제타패스 X 요즘) {amount}만원 (이상) {amount}천원 (할인)", "won", None),
    )
    for pattern, kind, card in patterns:
        match = re.fullmatch(pattern, event_name)
        if match is None:
            continue
        scope, threshold_text, marker, benefit_text, application = match.groups()
        threshold = Decimal(threshold_text) * 10000
        benefit = Decimal(benefit_text) * (1000 if kind == "won" else 1)
        if threshold <= 0 or benefit <= 0 or (kind == "percent" and benefit >= 100):
            return None
        def numeric(value: Decimal) -> int | float:
            return int(value) if value == value.to_integral_value() else float(value)
        threshold_value, benefit_value = numeric(threshold), numeric(benefit)
        if confirmed_price_or_none(threshold_value) is None or confirmed_price_or_none(benefit_value) is None:
            return None
        # An upward arrow does not establish equality at the stated threshold.
        inclusive = True if marker == "이상" else None
        facts = {
            "condition_text": event_name,
            "source_condition_kind": f"basket_spend_{kind}_discount",
            "source_spend_threshold_won": threshold_value,
            "source_threshold_amount_text": threshold_text + ("만" if marker == "↑" else "만원"),
            "source_threshold_marker": marker,
            "source_threshold_operator": ">=" if inclusive else None,
            "source_threshold_inclusive": inclusive,
            "threshold_equality_unconfirmed": inclusive is None,
            "source_scope_text": "행사카드 명절세트" if card else scope,
            "source_program_name": scope if scope == "제타패스 X 요즘" else None,
            "source_payment_card_text": card,
            "source_application_text": application if application == "즉시할인" else None,
            "source_declared_application_stage": None,
            "payable_price_unconfirmed": True,
            "discount_application_unconfirmed": True,
            "qualifying_basket_unconfirmed": True,
            "basket_allocation_unconfirmed": True,
            "spend_threshold_basis_unconfirmed": True,
            "discount_calculation_basis": None,
            "benefit_cap": None,
            "confirmed_user_eligibility": None,
        }
        facts["conditional_discount_won" if kind == "won" else "conditional_discount_percent"] = benefit_value
        return facts
    return None


def comparable_transaction_or_none(
    *,
    current_price: Any,
    promotion_type: PromotionType | str | None,
    promotion_conditions: Any = None,
) -> tuple[int | float, int] | None:
    """Return (actual spend, received-package count) for a confirmed transaction."""

    price = confirmed_price_or_none(current_price)
    if price is None:
        return None
    try:
        promotion = PromotionType(promotion_type) if promotion_type else PromotionType.UNKNOWN
    except ValueError:
        return None
    if promotion_conditions is not None and not isinstance(promotion_conditions, Mapping):
        return None
    conditions = promotion_conditions or {}
    if conditions.get("payable_price_unconfirmed") not in (None, False):
        return None
    if promotion in COMPARABLE_PROMOTION_TYPES:
        # A minimum order is paid quantity, not a free-package benefit. Never
        # discard an explicit invalid count or reinterpret a bundle's total as
        # its per-package price.
        if any(conditions.get(key) not in (None, 0) for key in ("buy_quantity", "free_quantity")):
            return None
        minimum = conditions.get("minimum_quantity", 1)
        if type(minimum) is not int or minimum < 1:
            return None
        if promotion == PromotionType.BUNDLE_PRICE and minimum != 1:
            return None
        return price * minimum, minimum
    if promotion == PromotionType.BUY_X_GET_Y:
        terms = buy_x_get_y_terms_or_none(conditions)
        if terms is not None:
            buy, free = terms
            minimum = conditions.get("minimum_quantity", buy)
            if type(minimum) is not int or minimum != buy:
                return None
            return price * buy, buy + free
    return None
