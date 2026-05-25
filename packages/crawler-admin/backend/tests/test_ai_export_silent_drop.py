"""rd3-pipe-silent-gap-fix — silent drop 감지 + forward wire log 회귀 테스트.

코스트코 OCC 995건 × 3회가 raw_crawl_records에 0건 도착했던 silent gap이 다시 생기지 않게,
records_sent vs ai-admin records_stored 불일치를 즉시 RawExportError로 끌어올리는지 검증한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.ai_export import RawExportError, forward_raw_records_to_ai_admin


def _items(n: int) -> list[dict]:
    return [
        {
            "product_id": f"sku-{i}",
            "name": f"테스트 상품 {i}",
            "sale_price": 1000 + i,
            "detail_url": f"https://mart.example/p/{i}",
        }
        for i in range(n)
    ]


def test_forward_detects_silent_drop_when_records_stored_is_lower():
    """200 OK여도 records_stored 가 records_sent 보다 적으면 RawExportError 로 끌어올린다."""

    def fake_post(url, payload, headers, timeout_seconds):
        # ai-admin이 일부 행만 적재했다고 보고하는 시나리오(silent drop).
        sent = len(payload["records"])
        return 200, {
            "raw_batch_id": "ai-drop",
            "records_stored": max(0, sent - 1),
            "ai_batches": 1,
            "provider_calls": 1,
        }

    with pytest.raises(RawExportError) as exc_info:
        forward_raw_records_to_ai_admin(
            _items(5),
            ai_admin_base_url="http://ai-admin.test",
            provider_id="google-dev",
            source_name="costco",
            crawler_name="costco_crawler",
            schema_type="mart_discount",
            batch_id="raw-costco-drop",
            http_post=fake_post,
        )

    msg = str(exc_info.value)
    assert "ai_admin_silent_drop" in msg
    assert "sent=5" in msg
    assert "drop=1" in msg


def test_forward_succeeds_when_records_stored_matches():
    def fake_post(url, payload, headers, timeout_seconds):
        return 200, {
            "raw_batch_id": "ai-ok",
            "records_stored": len(payload["records"]),
            "ai_batches": 1,
            "provider_calls": 1,
        }

    result = forward_raw_records_to_ai_admin(
        _items(3),
        ai_admin_base_url="http://ai-admin.test",
        provider_id="google-dev",
        source_name="emart",
        crawler_name="emart_crawler",
        schema_type="mart_discount",
        batch_id="raw-emart-ok",
        http_post=fake_post,
    )
    assert result["records_sent"] == 3
    assert result["records_accepted"] == 3
    assert result["drop_count"] == 0


def test_forward_writes_wire_log_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "forward.jsonl"
    monkeypatch.setenv("WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH", str(log_path))

    def fake_post(url, payload, headers, timeout_seconds):
        return 200, {
            "raw_batch_id": "ai-ok",
            "records_stored": len(payload["records"]),
        }

    result = forward_raw_records_to_ai_admin(
        _items(2),
        ai_admin_base_url="http://ai-admin.test",
        provider_id="google-dev",
        source_name="lottemart",
        crawler_name="lottemart_crawler",
        schema_type="mart_discount",
        http_post=fake_post,
    )

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["status"] == "ok"
    assert entry["records_sent"] == 2
    assert entry["records_accepted"] == 2
    assert entry["source_name"] == "lottemart"
    assert result["wire_log_path"] == str(log_path)


def test_forward_wire_log_records_drop_status(tmp_path, monkeypatch):
    log_path = tmp_path / "forward_drop.jsonl"
    monkeypatch.setenv("WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH", str(log_path))

    def fake_post(url, payload, headers, timeout_seconds):
        return 200, {"raw_batch_id": "ai-drop", "records_stored": 0}

    with pytest.raises(RawExportError):
        forward_raw_records_to_ai_admin(
            _items(4),
            ai_admin_base_url="http://ai-admin.test",
            provider_id="google-dev",
            source_name="homeplus",
            crawler_name="homeplus_crawler",
            schema_type="mart_discount",
            http_post=fake_post,
        )

    # 알람 차단 후에도 wire log 는 남아 JobsPanel/매칭 모니터가 드롭을 볼 수 있어야 한다.
    entries = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["status"] == "drop"
    assert entries[-1]["drop_count"] == 4
