"""pipeline.ai_export 단위 테스트 + /api/ai-export/raw-batch 라우트 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
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
    fetch_ai_admin_providers,
    forward_raw_records_to_ai_admin,
    split_raw_records_for_ai,
    to_raw_record,
    to_raw_records,
)


# ── 변환 단위 테스트 ─────────────────────────────────────────


class TestRawRecordConversion:
    def test_mart_like_item(self):
        item = {
            "name": "신라면 5개입",
            "store": "이마트",
            "sale_price": "3,990원",
            "original_price": "5,000",
            "detail_url": "https://emart.example/product/1",
            "category": "라면",
        }
        rec = to_raw_record(
            item,
            source_name="emart",
            index=0,
            batch_id="raw-test",
        )
        assert isinstance(rec, RawCrawlRecord)
        assert rec.source_name == "emart"
        assert rec.raw_title == "신라면 5개입"
        assert rec.raw_price == 3990
        assert rec.source_url == "https://emart.example/product/1"
        assert rec.raw_payload["store"] == "이마트"
        assert rec.raw_record_id.startswith("emart:")

    def test_hotdeal_like_item(self):
        item = {
            "title": "[쿠팡] 무선청소기 199,000",
            "url": "https://ppomppu.example/post/42",
            "post_id": "42",
            "price": 199000,
            "source_community": "ppomppu",
        }
        rec = to_raw_record(
            item,
            source_name="ppomppu",
            index=0,
            batch_id="raw-test",
        )
        assert rec is not None
        assert rec.raw_title == "[쿠팡] 무선청소기 199,000"
        assert rec.raw_price == 199000
        assert rec.source_record_key == "42"
        assert rec.raw_record_id == "ppomppu:42"

    def test_missing_title_skipped(self):
        item = {"price": 1000, "url": "https://x.example/a"}
        rec = to_raw_record(
            item, source_name="x", index=0, batch_id="raw-test"
        )
        assert rec is None

    def test_blank_title_skipped(self):
        rec = to_raw_record(
            {"title": "   "}, source_name="x", index=0, batch_id="raw-test"
        )
        assert rec is None

    def test_missing_price_is_none_not_error(self):
        rec = to_raw_record(
            {"title": "제품A"}, source_name="x", index=0, batch_id="raw-test"
        )
        assert rec is not None
        assert rec.raw_price is None

    def test_unparseable_price_is_none(self):
        rec = to_raw_record(
            {"title": "제품A", "price": "문의"},
            source_name="x",
            index=0,
            batch_id="raw-test",
        )
        assert rec is not None
        assert rec.raw_price is None

    def test_negative_price_rejected(self):
        rec = to_raw_record(
            {"title": "제품A", "price": -100},
            source_name="x",
            index=0,
            batch_id="raw-test",
        )
        assert rec is not None
        assert rec.raw_price is None

    def test_to_raw_records_skips_invalid(self):
        items = [
            {"title": "ok1"},
            {"price": 100},  # no title
            {"name": "ok2"},
        ]
        records, skipped = to_raw_records(
            items, source_name="x", batch_id="raw-test"
        )
        assert len(records) == 2
        assert skipped == 1


# ── 배치 빌드/한도 테스트 ────────────────────────────────────


class TestBuildRawBatch:
    def test_basic_batch_metadata(self):
        items = [{"title": f"item-{i}"} for i in range(3)]
        batch, records, skipped = build_raw_batch(
            items,
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            source_url="https://emart.example",
        )
        assert isinstance(batch, RawCrawlBatchContract)
        assert batch.source_name == "emart"
        assert batch.crawler_name == "emart_crawler"
        assert batch.schema_type == "mart_discount"
        assert batch.status == PipelineStatus.RAW_INGESTED
        assert batch.item_count == 3
        assert len(records) == 3
        assert skipped == 0

    def test_batch_size_limit_enforced(self):
        items = [{"title": f"t{i}"} for i in range(MAX_AI_BATCH_ITEMS + 1)]
        with pytest.raises(RawExportError):
            build_raw_batch(
                items,
                source_name="s",
                crawler_name="c",
                schema_type="mart_discount",
            )

    def test_batch_size_limit_exact_ok(self):
        items = [{"title": f"t{i}"} for i in range(MAX_AI_BATCH_ITEMS)]
        batch, records, _ = build_raw_batch(
            items,
            source_name="s",
            crawler_name="c",
            schema_type="mart_discount",
        )
        assert len(records) == MAX_AI_BATCH_ITEMS
        assert batch.item_count == MAX_AI_BATCH_ITEMS

    def test_prompt_char_limit_enforced(self):
        # 각 record의 prompt_text가 ~200자를 넘게 만들어 총합이 2000자를 초과하도록.
        long_title = "가" * 300
        items = [
            {"title": long_title, "id": f"id-{i}"}
            for i in range(MAX_AI_BATCH_ITEMS)
        ]
        with pytest.raises(RawExportError):
            build_raw_batch(
                items,
                source_name="s",
                crawler_name="c",
                schema_type="mart_discount",
            )

    def test_prompt_char_limit_under_ok(self):
        items = [{"title": "짧음", "id": str(i)} for i in range(5)]
        _, records, _ = build_raw_batch(
            items,
            source_name="s",
            crawler_name="c",
            schema_type="mart_discount",
        )
        assert sum(len(r.prompt_text()) for r in records) <= MAX_AI_BATCH_PROMPT_CHARS

    def test_build_raw_batches_splits_more_than_30_records(self):
        items = [{"title": f"상품 {i}", "id": f"emart-{i}"} for i in range(31)]
        batches, record_batches, skipped = build_raw_batches(
            items,
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            batch_id="raw-emart",
        )
        assert skipped == 0
        assert [len(records) for records in record_batches] == [30, 1]
        assert [batch.item_count for batch in batches] == [30, 1]
        assert all(len(records) <= MAX_AI_BATCH_ITEMS for records in record_batches)

    def test_build_raw_batches_splits_by_prompt_chars_with_korean_records(self):
        long_name = "오리온 오징어 땅콩 " + ("고소한맛" * 80)
        items = [
            {"name": long_name, "sale_price": "1,980원", "product_id": f"sku-{i}"}
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
            assert sum(len(r.prompt_text()) for r in records) <= MAX_AI_BATCH_PROMPT_CHARS

    def test_split_rejects_long_single_record_clearly(self):
        rec = to_raw_record(
            {"title": "가" * (MAX_AI_BATCH_PROMPT_CHARS + 10), "id": "too-long"},
            source_name="emart",
            index=0,
            batch_id="raw-long",
        )
        assert rec is not None
        with pytest.raises(RawExportError, match="record emart:too-long prompt text"):
            split_raw_records_for_ai([rec])

    def test_forward_posts_ai_ingest_contract_in_safe_batches(self):
        calls = []

        def fake_post(url, payload, headers, timeout_seconds):
            calls.append((url, payload, headers, timeout_seconds))
            prompt_chars = sum(
                len(
                    f"{r['source_name']}:{r['raw_record_id']}:{r['raw_title']}"
                    + (f" price={r['raw_price']}" if r.get("raw_price") is not None else "")
                )
                for r in payload["records"]
            )
            assert len(payload["records"]) <= MAX_AI_BATCH_ITEMS
            assert prompt_chars <= MAX_AI_BATCH_PROMPT_CHARS
            return 200, {
                "raw_batch_id": f"ai-{len(calls)}",
                "records_stored": len(payload["records"]),
                "ai_batches": 1,
                "provider_calls": 1,
                "proposals_stored": len(payload["records"]),
            }

        items = [
            {
                "product_id": "orion-squid-peanut",
                "name": "오리온 오징어 땅콩 98g",
                "sale_price": "1,980원",
                "detail_url": "https://emart.example/orion",
                "category": "과자",
            },
            *[
                {"product_id": f"sku-{i}", "name": f"테스트 상품 {i}", "sale_price": 1000 + i}
                for i in range(31)
            ],
        ]
        result = forward_raw_records_to_ai_admin(
            items,
            ai_admin_base_url="http://ai-admin.test",
            provider_id="google-dev",
            source_name="emart",
            crawler_name="emart_crawler",
            schema_type="mart_discount",
            batch_id="raw-forward",
            http_post=fake_post,
        )

        assert result["batches_sent"] == 2
        assert result["records_sent"] == 32
        assert calls[0][0] == "http://ai-admin.test/api/ingest/raw-records/label"
        assert calls[0][1]["provider_id"] == "google-dev"
        assert calls[0][1]["records"][0]["raw_title"] == "오리온 오징어 땅콩 98g"

    def test_fetch_ai_admin_providers_uses_server_side_get(self):
        calls = []

        def fake_get(url, headers, timeout_seconds):
            calls.append((url, headers, timeout_seconds))
            return 200, {
                "providers": [
                    {
                        "provider_id": "google-dev",
                        "provider_kind": "gemini",
                        "default_model": "gemma-3-27b-it",
                    }
                ],
                "count": 1,
            }

        result = fetch_ai_admin_providers(
            ai_admin_base_url="http://ai-admin.test/",
            timeout_seconds=7,
            http_get=fake_get,
        )

        assert result["count"] == 1
        assert result["providers"][0]["provider_id"] == "google-dev"
        assert calls == [("http://ai-admin.test/api/providers", {}, 7)]

    def test_fetch_ai_admin_providers_rejects_bad_response(self):
        def fake_get(url, headers, timeout_seconds):
            return 200, {"providers": "not-a-list"}

        with pytest.raises(RawExportError, match="invalid providers"):
            fetch_ai_admin_providers(
                ai_admin_base_url="http://ai-admin.test",
                http_get=fake_get,
            )


# ── HTTP 라우트 테스트 ───────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    app = create_app()
    return TestClient(app)


class TestAIExportRoute:
    def test_post_raw_batch_ok(self, client):
        payload = {
            "source_name": "emart",
            "crawler_name": "emart_crawler",
            "schema_type": "mart_discount",
            "items": [
                {"name": "신라면", "sale_price": "3,990", "detail_url": "u1"},
                {"title": "참치캔", "price": 5000},
            ],
        }
        resp = client.post("/api/ai-export/raw-batch", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["batch"]["source_name"] == "emart"
        assert data["batch"]["item_count"] == 2
        assert data["batch"]["status"] == "raw_ingested"
        assert data["skipped_count"] == 0
        assert len(data["records"]) == 2
        # raw_payload 보존 확인
        titles = [r["raw_title"] for r in data["records"]]
        assert "신라면" in titles and "참치캔" in titles

    def test_post_raw_batch_skips_missing_title(self, client):
        payload = {
            "source_name": "ppomppu",
            "crawler_name": "ppomppu_crawler",
            "schema_type": "hotdeal",
            "items": [
                {"title": "ok", "url": "u"},
                {"price": 1000},  # skipped
            ],
        }
        resp = client.post("/api/ai-export/raw-batch", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped_count"] == 1
        assert data["batch"]["item_count"] == 1
        assert len(data["records"]) == 1

    def test_post_raw_batch_size_limit_returns_422(self, client):
        payload = {
            "source_name": "s",
            "crawler_name": "c",
            "schema_type": "mart_discount",
            "items": [{"title": f"t{i}"} for i in range(MAX_AI_BATCH_ITEMS + 1)],
        }
        resp = client.post("/api/ai-export/raw-batch", json=payload)
        assert resp.status_code == 422

    def test_get_ai_providers_proxies_through_backend(self, client, monkeypatch):
        calls = []

        def fake_fetch(**kwargs):
            calls.append(kwargs)
            return {
                "providers": [
                    {
                        "provider_id": "google-dev",
                        "provider_kind": "gemini",
                        "default_model": "gemma-3-27b-it",
                    }
                ],
                "count": 1,
            }

        monkeypatch.setattr("api.routes.ai_export.fetch_ai_admin_providers", fake_fetch)

        resp = client.get(
            "/api/ai-export/providers",
            params={"ai_admin_base_url": "http://localhost:8003"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["providers"][0]["provider_id"] == "google-dev"
        assert calls == [
            {
                "ai_admin_base_url": "http://localhost:8003",
                "timeout_seconds": 10.0,
            }
        ]
