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
