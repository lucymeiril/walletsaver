"""pipeline.ai_export 순수 raw DTO 변환/분할 단위 테스트."""
from __future__ import annotations

import pytest

from core.contracts import (
    MAX_AI_BATCH_ITEMS,
    MAX_AI_BATCH_PROMPT_CHARS,
    PipelineStatus,
    RawCrawlBatchContract,
    RawCrawlRecord,
)
from pipeline.ai_export import (
    RawExportError,
    build_raw_batch,
    build_raw_batches,
    split_raw_records_for_ai,
    to_raw_record,
    to_raw_records,
    to_raw_records_with_invalid_rows,
)


class TestRawRecordConversion:
    def test_mart_like_item_preserves_raw_payload(self):
        item = {
            "name": "신라면 5개입",
            "store": "이마트",
            "sale_price": "3,990원",
            "detail_url": "https://emart.example/product/1",
            "category": "라면",
        }
        rec = to_raw_record(item, source_name="emart", index=0, batch_id="raw-test")
        assert isinstance(rec, RawCrawlRecord)
        assert rec.raw_title == "신라면 5개입"
        assert rec.raw_price == 3990
        assert rec.source_url == "https://emart.example/product/1"
        assert rec.raw_payload == item

    def test_korean_source_name_gets_ascii_stable_id(self):
        rec = to_raw_record(
            {
                "name": "친환경 대추방울토마토 600g/팩",
                "sale_price": "4,110원",
                "detail_url": "https://emart.example/product/100?tr=live",
            },
            source_name="이마트",
            index=0,
            batch_id="raw-emart-live",
        )
        assert rec is not None
        assert rec.raw_record_id.isascii()
        assert rec.raw_record_id.startswith("emart:url:")

    def test_source_record_key_wins_for_stable_id(self):
        rec = to_raw_record(
            {
                "title": "무선청소기",
                "post_id": "42",
                "price": 199000,
                "url": "https://example.test/42",
            },
            source_name="community",
            index=0,
            batch_id="raw-test",
        )
        assert rec is not None
        assert rec.source_record_key == "42"
        assert rec.raw_record_id == "community:42"

    @pytest.mark.parametrize(
        "item",
        [
            {"price": 1000, "url": "https://x.example/a"},
            {"title": "   "},
        ],
    )
    def test_missing_title_is_skipped(self, item):
        assert to_raw_record(item, source_name="x", index=0, batch_id="raw-test") is None

    @pytest.mark.parametrize("raw_price", [None, "문의", -100, True])
    def test_unsafe_price_becomes_none(self, raw_price):
        item = {"title": "제품A"}
        if raw_price is not None:
            item["price"] = raw_price
        rec = to_raw_record(item, source_name="x", index=0, batch_id="raw-test")
        assert rec is not None
        assert rec.raw_price is None

    def test_to_raw_records_reports_skipped_rows(self):
        records, skipped, invalid_rows = to_raw_records_with_invalid_rows(
            [
                {"name": "정상", "sale_price": 1000},
                {"sale_price": 2000},
            ],
            source_name="emart",
            batch_id="raw-row-errors",
        )
        assert len(records) == 1
        assert skipped == 1
        assert invalid_rows == [{"index": 1, "reason": "missing product name/title"}]

    def test_to_raw_records_returns_skipped_count(self):
        records, skipped = to_raw_records(
            [{"title": "ok1"}, {"price": 100}, {"name": "ok2"}],
            source_name="x",
            batch_id="raw-test",
        )
        assert len(records) == 2
        assert skipped == 1


class TestRawBatchConversion:
    def test_basic_batch_metadata(self):
        batch, records, skipped = build_raw_batch(
            [{"title": f"item-{i}"} for i in range(3)],
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            source_url="https://emart.example",
        )
        assert isinstance(batch, RawCrawlBatchContract)
        assert batch.status == PipelineStatus.RAW_INGESTED
        assert batch.item_count == 3
        assert len(records) == 3
        assert skipped == 0

    def test_batch_size_limit_is_enforced_for_single_batch(self):
        items = [{"title": f"t{i}"} for i in range(MAX_AI_BATCH_ITEMS + 1)]
        with pytest.raises(RawExportError):
            build_raw_batch(
                items,
                source_name="s",
                crawler_name="c",
                schema_type="mart_discount",
            )

    def test_prompt_limit_is_enforced_for_single_batch(self):
        items = [
            {"title": "가" * 1000, "id": f"id-{i}"}
            for i in range(MAX_AI_BATCH_ITEMS)
        ]
        with pytest.raises(RawExportError):
            build_raw_batch(
                items,
                source_name="s",
                crawler_name="c",
                schema_type="mart_discount",
            )

    def test_multiple_batches_split_at_record_limit(self):
        batches, record_batches, skipped = build_raw_batches(
            [{"title": f"상품 {i}", "id": f"emart-{i}"} for i in range(31)],
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            batch_id="raw-emart",
        )
        assert skipped == 0
        assert [len(records) for records in record_batches] == [30, 1]
        assert [batch.item_count for batch in batches] == [30, 1]

    def test_multiple_batches_split_by_prompt_budget(self):
        items = [
            {
                "name": "오리온 오징어 땅콩 " + ("고소한맛" * 200),
                "sale_price": "1,980원",
                "product_id": f"sku-{i}",
            }
            for i in range(12)
        ]
        _, record_batches, _ = build_raw_batches(
            items,
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            batch_id="raw-korean",
        )
        assert len(record_batches) > 1
        for records in record_batches:
            assert len(records) <= MAX_AI_BATCH_ITEMS
            assert sum(len(record.prompt_text()) for record in records) <= MAX_AI_BATCH_PROMPT_CHARS

    def test_oversized_single_record_is_isolated_without_network_assumptions(self):
        record = to_raw_record(
            {"title": "가" * (MAX_AI_BATCH_PROMPT_CHARS + 10), "id": "too-long"},
            source_name="emart",
            index=0,
            batch_id="raw-long",
        )
        assert record is not None
        batches = split_raw_records_for_ai([record])
        assert batches == [[record]]

    def test_required_metadata_is_validated(self):
        with pytest.raises(RawExportError):
            build_raw_batches([], source_name="", crawler_name="crawler", schema_type="raw")
        with pytest.raises(RawExportError):
            build_raw_batches([], source_name="source", crawler_name="", schema_type="raw")
        with pytest.raises(RawExportError):
            build_raw_batches([], source_name="source", crawler_name="crawler", schema_type="")
