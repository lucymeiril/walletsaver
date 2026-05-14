"""control DB와 public DB 분리 계약 테스트."""

import pytest
from pydantic import ValidationError

from shared.core.contracts.control_plane import (
    ControlJobContract,
    ProviderConfigContract,
    RetryPolicyContract,
)
from shared.core.contracts.ai_pipeline import AIWorkerRole, ProviderKind
from shared.core.contracts.public_catalog import (
    CommunityProductReference,
    PublicSaleOffer,
    PriceState,
    PromotionType,
    PublicCanonicalProductContract,
    PublicCategoryContract,
    PublicOfferEventContract,
    PublicProductVariantContract,
    PublicSourceListingContract,
    PublicWeekBucketContract,
    ReferenceHealth,
)


def test_retry_policy_rejects_too_fast_defaults_that_could_ban_provider():
    with pytest.raises(ValidationError):
        RetryPolicyContract(min_delay_seconds=0.1)


def test_retry_policy_requires_dead_letter_after_max_attempts():
    with pytest.raises(ValidationError, match="dead_letter_after_attempts"):
        RetryPolicyContract(max_attempts=5, dead_letter_after_attempts=3)


def test_control_job_defaults_are_human_operable():
    job = ControlJobContract(
        job_id="job-1",
        batch_id="batch-1",
        role=AIWorkerRole.CLASSIFIER,
    )

    assert job.retry_policy.max_attempts == 3
    assert job.retry_policy.min_delay_seconds >= 1
    assert job.attempts == 0


def test_provider_config_stores_secret_alias_not_secret_value():
    provider = ProviderConfigContract(
        provider_id="gemini-main",
        provider_kind=ProviderKind.GEMINI,
        display_name="Gemini Main",
        default_model="gemini-2.5-pro",
        secret_alias="GEMINI_API_KEY",
    )

    assert provider.secret_alias == "GEMINI_API_KEY"
    assert provider.min_request_interval_seconds >= 1


def test_public_sale_offer_derives_discount_rate_and_validates_dates():
    offer = PublicSaleOffer(
        public_offer_id="offer-1",
        public_variant_id="variant-1",
        source_name="emart",
        source_title="오리온 오징어땅콩 202g",
        price=10990,
        original_price=13990,
        promotion_type=PromotionType.WAS_NOW_PRICE,
        projection_version="v1",
    )

    assert offer.discount_rate == pytest.approx(0.2144)


def test_public_sale_offer_rejects_invalid_discount_period():
    with pytest.raises(ValidationError, match="valid_to"):
        PublicSaleOffer(
            public_offer_id="offer-1",
            public_variant_id="variant-1",
            source_name="emart",
            source_title="오리온 오징어땅콩 202g",
            price=10990,
            valid_from="2026-04-20T00:00:00",
            valid_to="2026-04-10T00:00:00",
            projection_version="v1",
        )


def test_community_reference_uses_public_id_without_cross_db_fk():
    ref = CommunityProductReference(
        reference_id="ref-1",
        owner_entity_type="post",
        owner_entity_id="post-123",
        public_product_id="prod-orion-peanut-squid",
    )

    assert ref.health == ReferenceHealth.OK
    assert ref.public_product_id == "prod-orion-peanut-squid"


def test_normalized_contract_keeps_category_separate_from_canonical_product():
    category = PublicCategoryContract(
        public_category_id="cat-milk",
        display_name="우유",
        projection_version="v1",
    )
    product = PublicCanonicalProductContract(
        public_product_id="prod-chocoemon",
        category_id=category.public_category_id,
        canonical_name="초코에몽",
        brand="남양",
        projection_version="v1",
    )

    assert category.public_category_id == product.category_id
    assert "canonical_name" not in PublicCategoryContract.model_fields
    assert "display_name" not in PublicCanonicalProductContract.model_fields


def test_canonical_static_data_is_separate_from_variant_and_source_listing():
    product = PublicCanonicalProductContract(
        public_product_id="prod-seoul-choco-milk",
        category_id="cat-milk",
        canonical_name="서울우유 초코우유",
        primary_image_url="https://example.test/product.jpg",
        projection_version="v1",
    )
    variant = PublicProductVariantContract(
        public_variant_id="var-seoul-choco-milk-200ml",
        public_product_id=product.public_product_id,
        variant_name="서울우유 초코우유 200ml",
        package_quantity=200,
        package_unit="ml",
        projection_version="v1",
    )
    listing = PublicSourceListingContract(
        public_source_listing_id="listing-emart-seoul-choco-milk-200ml",
        public_variant_id=variant.public_variant_id,
        source_name="emart",
        source_title="서울우유 초코우유 200ml",
        image_url="https://example.test/source.jpg",
        projection_version="v1",
    )

    assert variant.public_product_id == product.public_product_id
    assert listing.public_variant_id == variant.public_variant_id
    assert "category_id" not in PublicProductVariantContract.model_fields
    assert "brand" not in PublicProductVariantContract.model_fields
    assert "canonical_name" not in PublicSourceListingContract.model_fields


def test_offer_event_references_source_listing_without_product_static_fields():
    offer = PublicOfferEventContract(
        public_offer_event_id="offer-shinramyun-week-1",
        public_source_listing_id="listing-coupang-shinramyun-5pack",
        price=3980,
        original_price=4980,
        promotion_type=PromotionType.WAS_NOW_PRICE,
        event_name="주말특가",
        projection_version="v1",
    )

    assert offer.public_source_listing_id == "listing-coupang-shinramyun-5pack"
    assert offer.discount_rate == pytest.approx(0.2008)
    forbidden_duplicate_fields = {
        "public_product_id",
        "public_variant_id",
        "category_id",
        "canonical_name",
        "brand",
        "image_url",
        "source_title",
    }
    assert forbidden_duplicate_fields.isdisjoint(PublicOfferEventContract.model_fields)


def test_week_bucket_links_to_offer_event_separately():
    bucket = PublicWeekBucketContract(
        public_week_bucket_id="week-2026-01-offer-1",
        public_offer_event_id="offer-happy-eggs-1",
        week_start="2026-01-05T00:00:00",
        week_end="2026-01-11T23:59:59",
        observed_min_price=6990,
        projection_version="v1",
    )

    assert bucket.public_offer_event_id == "offer-happy-eggs-1"
    assert "public_source_listing_id" not in PublicWeekBucketContract.model_fields
    assert "canonical_name" not in PublicWeekBucketContract.model_fields


def test_hidden_or_missing_offer_prices_are_nullable_without_fake_defaults():
    hidden_offer = PublicOfferEventContract(
        public_offer_event_id="offer-hidden-price",
        public_source_listing_id="listing-source-hidden-price",
        price_state=PriceState.PRICE_HIDDEN,
        projection_version="v1",
    )
    missing_offer = PublicOfferEventContract(
        public_offer_event_id="offer-missing-price",
        public_source_listing_id="listing-source-missing-price",
        price_state=PriceState.PRICE_HIDDEN,
        projection_version="v1",
    )

    assert hidden_offer.price is None
    assert hidden_offer.original_price is None
    assert missing_offer.price is None
    assert missing_offer.standard_unit_price is None
    with pytest.raises(ValidationError, match="normal offer events require price"):
        PublicOfferEventContract(
            public_offer_event_id="offer-visible-no-price",
            public_source_listing_id="listing-visible-no-price",
            projection_version="v1",
        )


def test_discount_rate_only_offer_event_keeps_nullable_prices():
    offer = PublicOfferEventContract(
        public_offer_event_id="offer-card-rate-only",
        public_source_listing_id="listing-card-rate-only",
        price_state=PriceState.DISCOUNT_RATE_ONLY,
        promotion_type=PromotionType.CHECKOUT_DISCOUNT,
        discount_rate=0.15,
        projection_version="v1",
    )

    assert offer.price is None
    assert offer.original_price is None
    assert offer.discount_rate == pytest.approx(0.15)
