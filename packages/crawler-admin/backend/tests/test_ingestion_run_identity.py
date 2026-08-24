"""Crawler-run identity used by PendingIngestion retry idempotency."""
from __future__ import annotations

import pipeline.pipeline as pipeline_module
from pipeline import quality


def test_each_quality_summary_gets_one_fresh_ingestion_run_id():
    item = {
        "name": "테스트 상품",
        "sale_price": 1200,
        "detail_url": "https://example.test/item",
        "source": "emart",
    }

    first = quality.summarize_discount_run([item])
    second = quality.summarize_discount_run([item])

    # pipeline.py must hold the package-installed wrapper, not the pre-wrapper
    # function object, otherwise real crawler runs would miss this identity.
    assert pipeline_module.summarize_discount_run is quality.summarize_discount_run
    assert first["ingestion_run_id"].startswith("ingrun-")
    assert second["ingestion_run_id"].startswith("ingrun-")
    assert first["ingestion_run_id"] != second["ingestion_run_id"]
