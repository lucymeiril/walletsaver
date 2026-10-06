from __future__ import annotations

from pipeline.quality import summarize_discount_run


def test_quality_summary_is_collecting_for_complete_rows():
    summary = summarize_discount_run(
        [
            {"name": "양파 1kg", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"name": "두부 300g", "sale_price": 1980, "detail_url": "https://example.test/b"},
        ],
        raw_count=2,
        source_raw_count=2,
    )

    assert summary["quality_summary"]["status"] == "collecting"
    assert summary["quality_summary"]["critical_field_coverage"] == {
        "name": 1.0,
        "sale_price": 1.0,
        "detail_url": 1.0,
    }
    assert summary["operator_diagnostics"] == []


def test_quality_summary_warns_when_customer_visible_fields_are_missing():
    summary = summarize_discount_run(
        [
            {"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"name": "두부", "sale_price": 1980},
        ],
        raw_count=2,
        source_raw_count=2,
    )

    assert summary["quality_summary"]["status"] == "warning"
    assert summary["operator_diagnostics"][0]["code"] == "low_critical_field_coverage"
    assert summary["quality_summary"]["low_critical_fields"][0]["field"] == "detail_url"


def test_quality_summary_reports_duplicate_heavy_output():
    summary = summarize_discount_run(
        [
            {"store": "emart", "name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"store": "emart", "name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"store": "emart", "name": "두부", "sale_price": 1980, "detail_url": "https://example.test/b"},
        ],
        raw_count=3,
        source_raw_count=3,
    )

    diag = next(row for row in summary["operator_diagnostics"] if row["code"] == "duplicate_heavy_output")
    assert diag["duplicate_count"] == 1
    assert diag["duplicate_ratio"] == 0.333
    assert "high_duplicate_rate" in summary["alerts"]


def test_quality_preserves_distinct_source_spec_and_condition_contexts():
    base = {"name": "같은 상품", "sale_price": 1000, "native_product_id": "sku-a", "detail_url": "https://example.test/a",
            "attributes": {"quantity": 50, "unit": "g", "coupon_required": False}}
    rows = [base, {**base, "native_product_id": "sku-b"}, {**base, "detail_url": "https://example.test/b"},
            {**base, "attributes": {"quantity": 100, "unit": "g", "coupon_required": False}},
            {**base, "attributes": {"quantity": 50, "unit": "g", "coupon_required": True}}]
    summary = summarize_discount_run(rows, raw_count=len(rows))
    assert summary["item_counts"]["duplicates_after_validation"] == 0
    assert "high_duplicate_rate" not in summary["alerts"]
    assert summary["quality_summary"]["status"] == "collecting"


def test_quality_summary_distinguishes_source_and_parser_zero_results():
    source_empty = summarize_discount_run([], raw_count=0, source_raw_count=0)
    parser_empty = summarize_discount_run([], raw_count=0, source_raw_count=3)

    assert source_empty["zero_result_diagnostic"]["stage"] == "source_zero_raw_rows"
    assert parser_empty["zero_result_diagnostic"]["stage"] == "parse_filtered_all_raw_rows"
