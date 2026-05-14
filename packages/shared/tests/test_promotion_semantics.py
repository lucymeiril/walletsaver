import pytest

from shared.core.promotion_semantics import (
    PriceState,
    PromotionPriceFacts,
    PromotionType,
    comparable_price_or_none,
    confirmed_price_or_none,
)


def test_missing_price_has_no_numeric_placeholder():
    facts = PromotionPriceFacts.from_source(promotion_type=PromotionType.UNKNOWN)

    assert facts.price_state == PriceState.PRICE_HIDDEN
    assert facts.current_price is None
    assert facts.comparable_price is None
    assert confirmed_price_or_none(0) is None
    assert confirmed_price_or_none(-1) is None


def test_legacy_price_state_values_map_to_safe_semantics():
    assert PriceState("visible") == PriceState.NORMAL
    assert PriceState("hidden") == PriceState.PRICE_HIDDEN
    assert PriceState("missing") == PriceState.PRICE_HIDDEN


def test_discount_rate_only_is_public_but_not_sortable():
    facts = PromotionPriceFacts.from_source(
        discount_rate=0.2,
        promotion_type=PromotionType.RATE_OFF_UNCLEAR,
    )

    assert facts.price_state == PriceState.DISCOUNT_RATE_ONLY
    assert facts.discount_rate == pytest.approx(0.2)
    assert facts.comparable_price_available is False


def test_final_price_is_comparable_without_inventing_original_or_discount():
    facts = PromotionPriceFacts.from_source(
        current_price=7900,
        promotion_type=PromotionType.FINAL_PRICE,
    ).with_safe_calculations()

    assert facts.price_state == PriceState.SALE_PRICE_ONLY
    assert facts.original_price is None
    assert facts.discount_rate is None
    assert facts.comparable_price == 7900


def test_was_now_price_safely_derives_discount_rate_only():
    facts = PromotionPriceFacts.from_source(
        current_price=8000,
        original_price=10000,
        promotion_type=PromotionType.WAS_NOW_PRICE,
    ).with_safe_calculations()

    assert facts.price_state == PriceState.NORMAL
    assert facts.discount_rate == pytest.approx(0.2)
    assert facts.comparable_price == 8000


@pytest.mark.parametrize(
    "promotion_type",
    [
        PromotionType.CHECKOUT_DISCOUNT,
        PromotionType.BUY_X_GET_Y,
        PromotionType.RATE_OFF_UNCLEAR,
        PromotionType.UNKNOWN,
    ],
)
def test_ambiguous_promotions_do_not_derive_missing_values(promotion_type):
    facts = PromotionPriceFacts.from_source(
        original_price=10000,
        discount_rate=0.2,
        promotion_type=promotion_type,
    ).with_safe_calculations()

    assert facts.current_price is None
    assert facts.comparable_price is None


def test_buy_x_get_y_is_not_converted_to_simple_discount_rate():
    facts = PromotionPriceFacts.from_source(
        current_price=10000,
        original_price=10000,
        promotion_type=PromotionType.BUY_X_GET_Y,
    ).with_safe_calculations()

    assert facts.discount_rate is None
    assert facts.comparable_price is None


def test_bundle_price_is_sortable_only_when_bundle_price_is_confirmed():
    bundle = PromotionPriceFacts.from_source(
        current_price=15000,
        promotion_type=PromotionType.BUNDLE_PRICE,
    )
    hidden_bundle = PromotionPriceFacts.from_source(
        discount_rate=0.3,
        promotion_type=PromotionType.BUNDLE_PRICE,
    )

    assert bundle.comparable_price == 15000
    assert hidden_bundle.comparable_price is None


def test_numeric_sorting_uses_only_confirmed_comparable_prices():
    rows = [
        {"price": 7900, "promotion_type": "final_price"},
        {"discount_rate": 0.5, "promotion_type": "rate_off_unclear"},
        {"price": 10000, "promotion_type": "buy_x_get_y"},
        {"price": 15000, "promotion_type": "bundle_price"},
        {"price": 0, "promotion_type": "final_price"},
    ]

    sortable = [price for row in rows if (price := comparable_price_or_none(row)) is not None]

    assert sortable == [7900, 15000]
