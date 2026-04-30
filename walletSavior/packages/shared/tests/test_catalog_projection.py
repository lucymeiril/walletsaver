"""public catalog projection/snapshot 테스트."""

from shared.core.catalog_projection import (
    build_delta_manifest,
    build_projection_run,
    project_offer,
    project_product,
    project_variant,
)
from shared.core.contracts.ai_pipeline import (
    CanonicalProductDraft,
    ProductVariantDraft,
    SaleOfferDraft,
)


def test_projection_builds_stable_public_models_and_checksum():
    product = project_product(
        CanonicalProductDraft(
            canonical_name="오리온 오징어땅콩",
            brand="오리온",
            category_id="snack.nut",
            keywords=["오징어땅콩"],
        ),
        projection_version="v1",
    )
    variant = project_variant(
        product,
        ProductVariantDraft(
            variant_name="오리온 오징어땅콩 202g",
            package_quantity=202,
            package_unit="g",
            standard_unit="100g",
        ),
        projection_version="v1",
    )
    offer = project_offer(
        variant,
        SaleOfferDraft(
            source_name="emart",
            source_title="오리온 오징어땅콩 202g",
            price=2990,
            original_price=3990,
            standard_unit_price=1480.2,
            raw_record_id="raw-1",
        ),
        projection_version="v1",
    )

    run = build_projection_run(
        projection_version="v1",
        source_control_run_id="control-run-1",
        products=[product],
        variants=[variant],
        offers=[offer],
        published_by="admin",
    )

    assert product.public_product_id.startswith("prod-")
    assert variant.public_product_id == product.public_product_id
    assert offer.public_variant_id == variant.public_variant_id
    assert run.product_count == 1
    assert len(run.snapshot_checksum) == 64


def test_delta_manifest_reports_removed_public_ids():
    product = project_product(
        CanonicalProductDraft(canonical_name="삼겹살"),
        projection_version="v2",
    )

    manifest = build_delta_manifest(
        from_version="v1",
        to_version="v2",
        previous_ids={"prod-old", product.public_product_id},
        current_products=[product],
        current_variants=[],
        current_offers=[],
    )

    assert manifest.removed_public_ids == ["prod-old"]
    assert manifest.changed_products == 1
