import pytest

from shared.core.promotion_semantics import (
    PriceState,
    PromotionPriceFacts,
    PromotionType,
    comparable_price_or_none,
    comparable_transaction_or_none,
    conditional_selection_facts_or_none,
    conditional_program_facts_or_none,
    conditional_basket_spend_facts_or_none,
    confirmed_price_or_none,
)


def test_missing_price_has_no_numeric_placeholder():
    facts = PromotionPriceFacts.from_source(promotion_type=PromotionType.UNKNOWN)

    assert facts.price_state == PriceState.PRICE_HIDDEN
    assert facts.current_price is None
    assert facts.comparable_price is None
    assert confirmed_price_or_none(0) is None
    assert confirmed_price_or_none(-1) is None


@pytest.mark.parametrize("text,threshold,benefit,key,inclusive", [
    ("[동서식품] 4.5만↑ 5천원 할인", 45000, 5000, "conditional_discount_won", None),
    ("[동원] 4만원 이상 구매시, 5천원 즉시할인", 40000, 5000, "conditional_discount_won", True),
    ("[행사카드] 명절세트 30만↑ 12% 할인", 300000, 12, "conditional_discount_percent", None),
    ("제타패스 X 요즘 1만원 이상 3천원 할인", 10000, 3000, "conditional_discount_won", True),
])
def test_declared_spend_threshold_retains_unknown_qualification_and_payable(text, threshold, benefit, key, inclusive):
    facts = conditional_basket_spend_facts_or_none(text)
    assert facts["condition_text"] == text
    assert facts["source_spend_threshold_won"] == threshold and type(facts["source_spend_threshold_won"]) is int
    assert facts[key] == benefit
    assert facts["source_threshold_inclusive"] is inclusive
    assert facts["source_threshold_operator"] == (">=" if inclusive else None)
    assert facts["threshold_equality_unconfirmed"] is (inclusive is None)
    assert facts["source_declared_application_stage"] is None
    assert facts["confirmed_user_eligibility"] is None
    assert facts["benefit_cap"] is None and facts["discount_calculation_basis"] is None
    assert "minimum_quantity" not in facts and "buy_quantity" not in facts
    for price in (1350, 1450.5):
        for promotion in ("unknown", "final_price", "buy_x_get_y"):
            assert comparable_transaction_or_none(current_price=price, promotion_type=promotion,
                                                   promotion_conditions=facts) is None


@pytest.mark.parametrize("text", [None, {}, "함께할인", "[동서식품] 0만↑ 5천원 할인",
    "[행사카드] 명절세트 30만↑ 100% 할인", "[동원] 4만원 이상 구매시, 0천원 즉시할인",
    "[동서식품] 4.5만↑ 5천원 할인 회원 한정", "[동서식품] 4.5만↑ -5천원 할인"])
def test_incomplete_or_extra_spend_terms_are_not_silently_qualified(text):
    assert conditional_basket_spend_facts_or_none(text) is None


@pytest.mark.parametrize("value", [3590.5, "3590.50"])
def test_fractional_source_quote_survives_normalization_and_transaction(value):
    from shared.core.models import DiscountItem

    item = DiscountItem(name="source product", store="lottemart", sale_price=value,
                        original_price="4000.25")
    assert item.sale_price == 3590.5
    assert item.to_product_price().price == 3590.5
    assert item.to_product_price().original_price == 4000.25
    facts = PromotionPriceFacts.from_source(current_price=item.sale_price,
                                            promotion_type="final_price")
    assert facts.comparable_price == 3590.5
    assert comparable_transaction_or_none(
        current_price=item.sale_price, promotion_type="final_price",
        promotion_conditions={"minimum_quantity": 2},
    ) == (7181, 2)


@pytest.mark.parametrize("value", [3590, 3590.0, "3590.00"])
def test_integral_source_quotes_keep_existing_integer_serialization(value):
    from shared.core.models import DiscountItem

    item = DiscountItem(name="source product", store="lottemart", sale_price=value)
    assert type(item.model_dump()["sale_price"]) is int
    assert type(item.to_product_price().price) is int
    assert type(confirmed_price_or_none(value)) is int


def test_observed_quote_conversion_keeps_spec_and_unqualified_conditions():
    from datetime import datetime, timezone
    from shared.core.models import DiscountItem

    observed = datetime(2026, 10, 4, 11, 18, 13, tzinfo=timezone.utc)
    conditions = {"source_condition_kind": "source_quote_purchase_conditions_unverified",
                  "payable_price_unconfirmed": True, "minimum_purchase_quantity_unconfirmed": True,
                  "coupon_application_unconfirmed": True}
    item = DiscountItem(name="물 2L×6", source="homeplus", store="홈플러스",
        sale_price=2190.5, display_unit="2L×6", package_quantity=2, package_unit="L",
        detail_url="https://mfront.homeplus.co.kr/item?itemNo=059102628&storeType=HYPER",
        crawled_at=observed, attributes={"mart_native_code": "059102628", "bundle_count": 6,
            "promotion_conditions": conditions, "source_evidence": {"price_quote": 2190.5}})
    price = item.to_product_price()
    assert price.price == 2190.5 and price.source_name == "homeplus"
    assert price.source_url == item.detail_url and price.raw_text == item.name
    assert price.crawled_at == price.recorded_date == observed
    assert (price.package_quantity, price.package_unit, price.display_unit) == (2, "L", "2L×6")
    assert price.attributes == item.attributes
    assert price.promo_type is None and price.price_per_100g is None
    assert comparable_transaction_or_none(current_price=price.price,
        promotion_type=price.promo_type, promotion_conditions=price.attributes["promotion_conditions"]) is None
    price.attributes["source_evidence"]["price_quote"] = 999
    assert item.attributes["source_evidence"]["price_quote"] == 2190.5


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf")])
def test_crawler_money_model_rejects_boolean_and_nonfinite_quotes(value):
    from pydantic import ValidationError
    from shared.core.models import DiscountItem, ProductPrice, DataSource

    with pytest.raises(ValidationError):
        DiscountItem(name="source product", store="lottemart", sale_price=value)
    with pytest.raises(ValidationError):
        ProductPrice(product_name="source product", source=DataSource.MART_DISCOUNT,
                     price=value)


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


def test_confirmed_buy_x_get_y_exposes_actual_spend_and_received_packages():
    assert comparable_transaction_or_none(
        current_price=10000,
        promotion_type="buy_x_get_y",
        promotion_conditions={"buy_quantity": 1, "free_quantity": 1},
    ) == (10000, 2)
    assert comparable_transaction_or_none(
        current_price=4000,
        promotion_type="buy_x_get_y",
        promotion_conditions={"buy_quantity": 2, "free_quantity": 1},
    ) == (8000, 3)


def test_explicit_minimum_order_retains_paid_and_received_quantity():
    assert comparable_transaction_or_none(
        current_price=4000, promotion_type="final_price",
        promotion_conditions={"minimum_quantity": 2, "condition_text": "최소구매 2"},
    ) == (8000, 2)
    for conditions in (["minimum_quantity"], {"minimum_quantity": True},
                       {"minimum_quantity": 0}, {"minimum_quantity": -2},
                       {"minimum_quantity": 2.5}, {"minimum_quantity": "2"},
                       {"minimum_quantity": 2, "free_quantity": 1}):
        assert comparable_transaction_or_none(
            current_price=4000, promotion_type="final_price",
            promotion_conditions=conditions,
        ) is None
    assert comparable_transaction_or_none(
        current_price=4000, promotion_type="bundle_price",
        promotion_conditions={"minimum_quantity": 2},
    ) is None


@pytest.mark.parametrize("conditions", [None, {}, {"buy_quantity": 1}, {"buy_quantity": 0, "free_quantity": 1},
    {"buy_quantity": True, "free_quantity": 1}, {"buy_quantity": 2, "free_quantity": True},
    {"buy_quantity": 2.7, "free_quantity": 1}, {"buy_quantity": 2, "free_quantity": 1.5},
    {"buy_quantity": "2", "free_quantity": 1}, {"buy_quantity": 2, "free_quantity": "1"},
    {"buy_quantity": float("inf"), "free_quantity": 1}, [2, 1]])
def test_incomplete_buy_x_get_y_terms_remain_non_comparable(conditions):
    assert comparable_transaction_or_none(
        current_price=10000,
        promotion_type="buy_x_get_y",
        promotion_conditions=conditions,
    ) is None


@pytest.mark.parametrize("value", [True, False, {}, [], "unconfirmed", float("inf"), float("nan")])
def test_malformed_price_is_unknown_and_never_a_boolean_quote(value):
    assert confirmed_price_or_none(value) is None
    assert comparable_transaction_or_none(
        current_price=value, promotion_type="final_price",
    ) is None


@pytest.mark.parametrize("text", ["3개씩 골라 담으면, 그 중 1개는 무료", "4개씩 골라 담으면, 50% 할인",
    "3개씩 골라 담으면, 9,900원", "4개씩 골라 담으면, 2,000원 할인",
    pytest.param("2개씩 담으면, 그 중 1개는 무료", id="add_to_basket_free"),
    pytest.param("2개씩 담으면, 50% 할인", id="add_to_basket_percentage"),
    pytest.param("2개씩 담으면, 21,000원", id="add_to_basket_total"),
    pytest.param("2개씩 담으면, 4,000원 할인", id="add_to_basket_deduction"),
    "3개 담으면, 9,990원에 구매 (최대 99개까지 행사/할인 적용)",
    "4개 담으면, 9,990원에 구매 (최대 100개까지 행사/할인 적용)"])
def test_known_basket_terms_do_not_claim_paid_quantity_or_final_price(text):
    facts = conditional_selection_facts_or_none(text)
    assert facts["condition_text"] == text
    assert facts["required_selection_quantity"] in (2, 3, 4)
    assert facts["basket_selection_required"] is True
    assert "buy_quantity" not in facts and "free_quantity" not in facts
    for promotion in ("unknown", "final_price", "buy_x_get_y"):
        assert comparable_transaction_or_none(
            current_price=4000, promotion_type=promotion, promotion_conditions=facts,
        ) is None


@pytest.mark.parametrize("text", [None, {}, "함께할인", "1개씩 골라 담으면, 그 중 1개는 무료",
    "3개씩 골라 담으면, 100% 할인", "3개씩 골라 담으면, 0% 할인",
    "3개씩 골라 담으면, 그 중 1개는 무료 회원 한정", "3개씩 골라 담으면, 10,00원",
    "3개씩 골라 담으면, 0원", "3개씩 골라 담으면, 2,000원 할인 회원 한정",
    "3개 담으면, 9,990원에 구매 (최대 2개까지 행사/할인 적용)",
    "3개 담으면, 9,990원에 구매 (최대 99개까지 행사/할인 적용) 회원 한정",
    "3개 담으면, 9,990원에 구매 (최대 99개 재고)"])
def test_incomplete_or_extra_basket_conditions_are_not_silently_dropped(text):
    assert conditional_selection_facts_or_none(text) is None


@pytest.mark.parametrize("text,program,application", [
    ("농할 할인 20%_결제시 자동적용", "농할", "automatic"),
    ("수산대전 20% 할인", "수산대전", None),
])
def test_named_program_rate_preserves_wording_without_payable_inference(text, program, application):
    facts = conditional_program_facts_or_none(text)
    assert facts["condition_text"] == text
    assert facts["source_program_name"] == program
    assert facts["conditional_discount_percent"] == 20
    assert facts["source_declared_application_method"] == application
    assert facts["benefit_cap"] is None and facts["discount_calculation_basis"] is None
    assert facts["program_eligibility_unconfirmed"] is True
    assert "buy_quantity" not in facts and "minimum_quantity" not in facts
    for promotion in ("unknown", "final_price", "buy_x_get_y"):
        assert comparable_transaction_or_none(
            current_price=4000, promotion_type=promotion, promotion_conditions=facts,
        ) is None


@pytest.mark.parametrize("text", [None, {}, "할인", "함께할인", "농할 할인 20%",
    "수산대전 20% 할인_결제시 자동적용", "농할 할인 30%_결제시 자동적용",
    "수산대전 20% 할인 회원 한정", "[행사카드] 20% 할인"])
def test_incomplete_or_other_program_terms_need_their_own_review(text):
    assert conditional_program_facts_or_none(text) is None


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
