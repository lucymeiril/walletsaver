from __future__ import annotations

import pytest

from core.contracts import MAX_AI_BATCH_ITEMS, MAX_AI_BATCH_PROMPT_CHARS, RawCrawlRecord
from pipeline.raw_export import (
    RawExportError,
    build_raw_batch,
    build_raw_batches,
    split_raw_records,
    to_raw_record,
    to_raw_records_with_invalid_rows,
)


def test_raw_record_preserves_payload_and_stable_source_identity():
    item = {
        "name": "신라면 5개입",
        "product_id": "sku-1",
        "sale_price": "3,990원",
        "detail_url": "https://example.test/product/1",
    }
    record = to_raw_record(item, source_name="emart", index=0, batch_id="raw-test")
    assert record is not None
    assert record.raw_record_id == "emart:sku-1"
    assert record.raw_price == 3990
    assert record.raw_payload == item


def test_invalid_rows_are_reported_without_dropping_valid_rows():
    records, skipped, invalid = to_raw_records_with_invalid_rows(
        [{"name": "정상", "sale_price": 1000}, {"sale_price": 2000}],
        source_name="emart",
        batch_id="raw-test",
    )
    assert len(records) == 1
    assert skipped == 1
    assert invalid == [{"index": 1, "reason": "missing product name/title"}]


def test_single_batch_enforces_item_limit():
    with pytest.raises(RawExportError):
        build_raw_batch(
            [{"title": f"item-{i}"} for i in range(MAX_AI_BATCH_ITEMS + 1)],
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
        )


def test_multi_batch_preserves_record_boundaries():
    _, record_batches, skipped = build_raw_batches(
        [{"title": f"상품 {i}", "id": f"sku-{i}"} for i in range(MAX_AI_BATCH_ITEMS + 1)],
        source_name="emart",
        crawler_name="emart_crawler",
        schema_type="mart_discount",
        batch_id="raw-emart",
    )
    assert skipped == 0
    assert [len(batch) for batch in record_batches] == [MAX_AI_BATCH_ITEMS, 1]


def test_oversized_record_is_isolated_instead_of_rejected():
    record = RawCrawlRecord(
        raw_record_id="emart:big",
        source_name="emart",
        raw_title="가" * (MAX_AI_BATCH_PROMPT_CHARS + 500),
        raw_payload={},
    )
    assert split_raw_records([record]) == [[record]]


def test_required_batch_metadata_is_validated():
    with pytest.raises(RawExportError):
        build_raw_batches([], source_name="", crawler_name="crawler", schema_type="raw")
