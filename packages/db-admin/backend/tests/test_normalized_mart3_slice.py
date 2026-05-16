from __future__ import annotations

import pytest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from api.routes.ingestion import _insert_items
from services.normalized_mart3 import publish_mart3_rows
from storage.models import (
    Base,
    Category,
    DiscountHistory,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _mart3_rows():
    return [
        {
            "raw_record_id": "emart-tofu-300g-w1",
            "source": "E-Mart",
            "source_record_key": "emart-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "image_url": "https://emart.example/images/tofu.jpg",
            "source_url": "https://emart.example/products/tofu?week=1",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "unit": "300g",
            "price": 1980,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
            "raw_evidence": {"price_text": "1,980원"},
        },
        {
            "raw_record_id": "emart-tofu-300g-w2",
            "source": "E-Mart",
            "source_record_key": "emart-tofu-300",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "image_url": "https://emart.example/images/tofu.jpg",
            "source_url": "https://emart.example/products/tofu?week=2",
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "unit": "300g",
            "price": 1980,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-13T00:00:00",
            "week_end": "2026-04-19T00:00:00",
        },
        {
            "raw_record_id": "lottemart-cabbage-card-rate",
            "source": "LotteMart",
            "source_record_key": "lotte-cabbage-800",
            "source_title": "한끼 양배추 카드 20% 할인",
            "canonical_name": "한끼 양배추",
            "category_id": "vegetable.cabbage",
            "category_name": "양배추",
            "image_url": "https://lotte.example/images/cabbage.jpg",
            "source_url": "https://lotte.example/products/cabbage",
            "package_quantity": 800,
            "package_unit": "g",
            "display_unit": "800g",
            "price": None,
            "discount_rate": 0.2,
            "price_state": "discount_rate_only",
            "promotion_type": "checkout_discount",
            "event_name": "카드 20% 할인",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
        {
            "raw_record_id": "homeplus-ramen-hidden",
            "source": "Homeplus",
            "source_record_key": "homeplus-ramen-5",
            "source_title": "농심 라면 멀티팩",
            "canonical_name": "농심 라면",
            "category_id": "processed.ramen",
            "category_name": "라면",
            "image_url": "https://homeplus.example/images/ramen.jpg",
            "source_url": "https://homeplus.example/products/ramen",
            "package_quantity": 5,
            "package_unit": "pack",
            "display_unit": "5입",
            "price": 0,
            "price_state": "price_hidden",
            "promotion_type": "unknown",
            "event_name": "앱에서 가격 확인",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
        {
            "raw_record_id": "emart-tofu-500g-package-candidate",
            "source": "E-Mart",
            "source_record_key": "emart-tofu-500",
            "source_title": "풀무원 국산콩 두부",
            "canonical_name": "풀무원 국산콩 두부",
            "category_id": "processed.tofu",
            "category_name": "두부",
            "image_url": "https://emart.example/images/tofu.jpg",
            "source_url": "https://emart.example/products/tofu-500",
            "package_quantity": 500,
            "package_unit": "g",
            "display_unit": "500g",
            "price": 2980,
            "price_state": "normal",
            "promotion_type": "final_price",
            "event_name": "상시가",
            "week_start": "2026-04-06T00:00:00",
            "week_end": "2026-04-12T00:00:00",
        },
    ]


def test_mart3_normalized_slice_dedupes_static_rows_offers_and_updates_listing_url():
    Session = _session_factory()
    rows = _mart3_rows()
    with Session.begin() as session:
        placements = publish_mart3_rows(session, rows)

    with Session() as session:
        tofu_product = session.execute(
            select(NormalizedCanonicalProduct).where(
                NormalizedCanonicalProduct.canonical_name == "풀무원 국산콩 두부"
            )
        ).scalar_one()
        tofu_variants = session.execute(
            select(NormalizedProductVariant).where(
                NormalizedProductVariant.public_product_id == tofu_product.public_product_id
            )
        ).scalars().all()
        tofu_listings = session.execute(
            select(NormalizedSourceListing).join(NormalizedProductVariant).where(
                NormalizedProductVariant.public_product_id == tofu_product.public_product_id
            )
        ).scalars().all()
        tofu_offer_count = session.scalar(
            select(func.count()).select_from(NormalizedOfferEvent).where(
                NormalizedOfferEvent.public_source_listing_id == placements[0]["public_source_listing_id"]
            )
        )
        tofu_week_links = session.execute(
            select(NormalizedOfferWeekLink).where(
                NormalizedOfferWeekLink.public_offer_event_id == placements[0]["public_offer_event_id"]
            )
        ).scalars().all()
        week_count = session.scalar(select(func.count()).select_from(NormalizedWeekBucket))
        category_count = session.scalar(
            select(func.count()).select_from(Category).where(Category.id == "processed.tofu")
        )
        product_count = session.scalar(
            select(func.count()).select_from(NormalizedCanonicalProduct).where(
                NormalizedCanonicalProduct.canonical_name == "풀무원 국산콩 두부"
            )
        )
        latest_listing = session.get(
            NormalizedSourceListing,
            placements[0]["public_source_listing_id"],
        )
        tofu_offer = session.get(
            NormalizedOfferEvent,
            placements[0]["public_offer_event_id"],
        )

    assert product_count == 1
    assert category_count == 1
    assert tofu_product.primary_image_url == "https://emart.example/images/tofu.jpg"
    assert len(tofu_variants) == 2
    assert len(tofu_listings) == 2
    assert placements[1]["match_result"] == "auto_same_title_package"
    assert placements[1]["public_source_listing_id"] == placements[0]["public_source_listing_id"]
    assert placements[4]["match_result"] == "candidate_package_mismatch"
    assert placements[4]["public_source_listing_id"] != placements[0]["public_source_listing_id"]
    assert tofu_offer_count == 1
    assert len(tofu_week_links) == 2
    assert week_count == 2
    assert latest_listing.source_url == "https://emart.example/products/tofu?week=2"
    assert tofu_offer.raw_evidence == {"price_text": "1,980원"}


def test_mart3_nullable_price_states_do_not_create_fake_comparable_prices():
    Session = _session_factory()
    with Session.begin() as session:
        placements = publish_mart3_rows(session, _mart3_rows())

    with Session() as session:
        discount_rate_only = session.get(
            NormalizedOfferEvent,
            placements[2]["public_offer_event_id"],
        )
        hidden = session.get(
            NormalizedOfferEvent,
            placements[3]["public_offer_event_id"],
        )
        unsafe_links = session.execute(
            select(NormalizedOfferWeekLink).where(
                NormalizedOfferWeekLink.public_offer_event_id.in_(
                    [
                        placements[2]["public_offer_event_id"],
                        placements[3]["public_offer_event_id"],
                    ]
                )
            )
        ).scalars().all()

    assert discount_rate_only.price_state == "discount_rate_only"
    assert discount_rate_only.promotion_type == "checkout_discount"
    assert discount_rate_only.price is None
    assert discount_rate_only.discount_rate == 0.2
    assert hidden.price_state == "price_hidden"
    assert hidden.price is None
    assert placements[2]["comparable_price"] is None
    assert placements[3]["comparable_price"] is None
    assert all(link.observed_min_price is None for link in unsafe_links)
    assert all(link.observed_max_price is None for link in unsafe_links)


def _ai_publish_item(**overrides):
    item = {
        "name": "테스트 두부 300g",
        "source_title": "테스트 두부 300g",
        "sale_price": 1980,
        "current_price": 1980,
        "source": "emart",
        "source_url": "https://emart.example/products/test-tofu?week=1",
        "image_url": "https://emart.example/images/test-tofu.jpg",
        "unit": "300g",
        "display_unit": "300g",
        "package_quantity": 300,
        "package_unit": "g",
        "raw_record_id": "test-tofu-300g-w1",
        "source_record_key": "emart-sku-test-tofu-300g",
        "promotion_type": "final_price",
        "week_start": "2026-04-06T00:00:00",
        "week_end": "2026-04-12T00:00:00",
        "ai_review_audit": {"raw_record_id": "test-tofu-300g-w1", "proposal_ids": ["name", "price"]},
        "raw_data": {"raw_evidence": {"title": "테스트 두부 300g", "price_text": "1,980원"}},
    }
    item.update(overrides)
    return item


def test_db_admin_insert_items_publishes_legacy_and_normalized_discount_rows():
    Session = _session_factory()
    rows = [
        _ai_publish_item(),
        _ai_publish_item(
            raw_record_id="test-tofu-300g-w2",
            source_url="https://emart.example/products/test-tofu?week=2",
            week_start="2026-04-13T00:00:00",
            week_end="2026-04-19T00:00:00",
        ),
    ]
    with Session.begin() as session:
        saved = _insert_items(session, rows, "DiscountItem")

    with Session() as session:
        product_count = session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct))
        variant_count = session.scalar(select(func.count()).select_from(NormalizedProductVariant))
        listing_count = session.scalar(select(func.count()).select_from(NormalizedSourceListing))
        offer_count = session.scalar(select(func.count()).select_from(NormalizedOfferEvent))
        week_count = session.scalar(select(func.count()).select_from(NormalizedWeekBucket))
        link_count = session.scalar(select(func.count()).select_from(NormalizedOfferWeekLink))
        legacy_count = session.scalar(select(func.count()).select_from(DiscountHistory))
        listing = session.execute(select(NormalizedSourceListing)).scalar_one()
        offer = session.execute(select(NormalizedOfferEvent)).scalar_one()
        links = session.execute(select(NormalizedOfferWeekLink)).scalars().all()

    assert saved == 2
    assert legacy_count == 2
    assert product_count == 1
    assert variant_count == 1
    assert listing_count == 1
    assert offer_count == 1
    assert week_count == 2
    assert link_count == 2
    assert listing.source_url == "https://emart.example/products/test-tofu?week=2"
    assert offer.raw_evidence == {"title": "테스트 두부 300g", "price_text": "1,980원"}
    assert offer.audit_provenance["raw_record_id"] == "test-tofu-300g-w1"
    assert all(link.observed_min_price == 1980 for link in links)


def test_db_admin_insert_items_treats_one_discount_percent_as_one_percent():
    Session = _session_factory()
    item = _ai_publish_item(discount_percent=1, original_price=2000)
    with Session.begin() as session:
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        legacy = session.execute(select(DiscountHistory)).scalar_one()
        offer = session.execute(select(NormalizedOfferEvent)).scalar_one()

    assert saved == 1
    assert legacy.discount_rate == 1
    assert offer.discount_rate == 0.01


def test_db_admin_insert_items_treats_sub_one_discount_percent_as_percent():
    Session = _session_factory()
    item = _ai_publish_item(discount_percent=0.7, original_price=44120, sale_price=43830, current_price=43830)
    with Session.begin() as session:
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        legacy = session.execute(select(DiscountHistory)).scalar_one()
        offer = session.execute(select(NormalizedOfferEvent)).scalar_one()

    assert saved == 1
    assert legacy.discount_rate == 0.7
    assert offer.discount_rate == pytest.approx(0.007)


def test_db_admin_insert_items_keeps_conditional_price_non_comparable():
    Session = _session_factory()
    item = _ai_publish_item(
        promotion_type="checkout_discount",
        event_name="카드 결제 할인",
        raw_record_id="conditional-card-discount",
    )
    with Session.begin() as session:
        saved = _insert_items(session, [item], "DiscountItem")

    with Session() as session:
        legacy = session.execute(select(DiscountHistory)).scalar_one()
        offer = session.execute(select(NormalizedOfferEvent)).scalar_one()
        link = session.execute(select(NormalizedOfferWeekLink)).scalar_one()

    assert saved == 1
    assert legacy.price == 1980
    assert offer.price == 1980
    assert offer.promotion_type == "checkout_discount"
    assert link.observed_min_price is None
    assert link.observed_max_price is None
