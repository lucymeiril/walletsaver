from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.normalized_mart3 import publish_mart3_rows
from services.normalized_price_read import get_normalized_price_comparison
from storage.models import Base


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _rows():
    return [
        {
            "raw_record_id": "emart-tofu-300g-w1",
            "source": "E-Mart",
            "source_record_key": "emart-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "source_url": "https://emart.example/products/tofu?week=1",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "price": 1980,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
        {
            "raw_record_id": "emart-tofu-300g-w2",
            "source": "E-Mart",
            "source_record_key": "emart-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "source_url": "https://emart.example/products/tofu?week=2",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "price": 1980,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-13T00:00:00",
            "week_end": "2026-04-19T00:00:00",
        },
        {
            "raw_record_id": "lotte-tofu-300g",
            "source": "LotteMart",
            "source_record_key": "lotte-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "source_url": "https://lotte.example/products/tofu",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "price": 1780,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
        {
            "raw_record_id": "homeplus-tofu-hidden",
            "source": "Homeplus",
            "source_record_key": "homeplus-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "source_url": "https://homeplus.example/products/tofu",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "price": 0,
            "price_state": "price_hidden",
            "promotion_type": "unknown",
            "event_name": "앱에서 가격 확인",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
        {
            "raw_record_id": "card-tofu-rate",
            "source": "CardMart",
            "source_record_key": "card-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "source_url": "https://card.example/products/tofu",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "price": None,
            "discount_rate": 0.2,
            "price_state": "discount_rate_only",
            "promotion_type": "checkout_discount",
            "event_name": "카드 20% 할인",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
    ]


def _read_model():
    Session = _session_factory()
    with Session.begin() as session:
        publish_mart3_rows(session, _rows())
    with Session() as session:
        return get_normalized_price_comparison(session, category_id="processed.tofu")


def _events(model):
    product = model["products"][0]
    return [
        event
        for variant in product["variants"]
        for listing in variant["source_listings"]
        for event in listing["offer_events"]
    ]


def test_read_model_sorts_comparable_prices_before_non_comparable_rows():
    model = _read_model()
    product = model["products"][0]
    prices = [
        listing["best_comparable_price"]
        for variant in product["variants"]
        for listing in variant["source_listings"]
    ]

    assert prices[:2] == [1780, 1980]
    assert prices[2:] == [None, None]
    assert model["sort_policy"] == "comparable_price_ascending_then_non_comparable"


def test_read_model_preserves_hidden_and_rate_only_display_state_without_fake_price():
    events = _events(_read_model())
    hidden = next(event for event in events if event["price_state"] == "price_hidden")
    rate_only = next(event for event in events if event["price_state"] == "discount_rate_only")

    assert hidden["display_state"] == "hidden"
    assert hidden["comparable_price"] is None
    assert hidden["is_default_sortable"] is False
    assert rate_only["display_state"] == "rate_only"
    assert rate_only["discount_rate"] == 0.2
    assert rate_only["comparable_price_available"] is False


def test_read_model_links_single_offer_event_to_multiple_week_buckets():
    events = _events(_read_model())
    emart = next(event for event in events if event["comparable_price"] == 1980)

    assert len(emart["weeks"]) == 2
    assert [week["week_start"] for week in emart["weeks"]] == [
        "2026-04-06T00:00:00",
        "2026-04-13T00:00:00",
    ]


def test_read_model_uses_source_listing_latest_url():
    model = _read_model()
    listings = [
        listing
        for variant in model["products"][0]["variants"]
        for listing in variant["source_listings"]
    ]
    emart = next(listing for listing in listings if listing["source_name"] == "e-mart")

    assert emart["latest_source_url"] == "https://emart.example/products/tofu?week=2"
    assert emart["source_url"] == emart["latest_source_url"]
