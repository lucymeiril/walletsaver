from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
HARNESS_PATH = REPO_ROOT / "tools" / "live_validation_harness_v2.py"
spec = importlib.util.spec_from_file_location("live_validation_harness_v2", HARNESS_PATH)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

FAKE_GOOGLE_KEY = "AIza" + "1" * 25

def _args(tmp_path: Path, **overrides) -> Namespace:
    defaults = {
        "input_json": None,
        "artifact_dir": tmp_path,
        "source_name": "manual-test",
        "crawler_name": "manual-test",
        "schema_type": "mart_discount",
        "max_items": 5,
        "retain_all_input": False,
        "allow_large_live_batch": False,
        "max_live_items_cap": harness.MAX_LIVE_ITEMS,
        "max_pages": 1,
        "max_crawler_requests": 1,
        "max_provider_calls": 1,
        "ai_batch_size": harness.DEFAULT_AI_BATCH_SIZE,
        "ai_batch_prompt_chars": harness.DEFAULT_AI_BATCH_PROMPT_CHARS,
        "label_chunk_retries": 0,
        "label_call_min_interval_seconds": 0,
        "allow_live_crawl": False,
        "live_crawler": None,
        "allow_live_provider": False,
        "provider_id": None,
        "provider_key_alias": None,
        "provider_model": None,
        "validation_mode": None,
        "ai_admin_url": "http://localhost:8003",
        "ai_admin_api_key_alias": None,
        "catalog_json": None,
        "learned_json": None,
        "allow_db_admin_submit": False,
        "reviewer_id": "manual-test",
    }
    defaults.update(overrides)
    return Namespace(**defaults)

def test_default_dry_run_writes_artifact_without_provider_calls(tmp_path: Path) -> None:
    def fail_http(*_args, **_kwargs):
        raise AssertionError("dry-run must not call HTTP/provider APIs")

    artifact = harness.run_harness(_args(tmp_path), http_json=fail_http)

    assert artifact["validation_run"]["mode"] == "fixture"
    assert artifact["quality_batch_validation"]["mode"] == "fixture"
    assert artifact["provider_response_summary"]["called"] is False
    assert artifact["provider_response_summary"]["provider_mode"] == "skipped"
    assert artifact["source"]["records_count"] == 2
    assert Path(artifact["artifact_path"]).is_file()
    assert artifact["publish_blockers"]["items"][0]["blockers"]
    assert all(
        record["raw_payload"].get("image_url")
        for record in artifact["raw_records"]
    )
    assert all(
        comparison["raw_image_url"] == comparison["final_image_url"]
        for comparison in artifact["raw_vs_final"]
    )
    assert not any(
        blocker == "data_quality: missing hotdeal publication evidence field image_url"
        for row in artifact["publish_blockers"]["items"]
        for blocker in row["blockers"]
    )
    assert artifact["db_admin_acceptance"]["db_admin_submit_allowed"] is False


def test_db_admin_acceptance_rejects_final_approve_without_public_verification() -> None:
    acceptance = harness.build_db_admin_acceptance_summary(
        {
            "submitted_to_db_admin": 1,
            "ai_safe_final_approved": 1,
            "pending_db_review": 0,
            "final_approve_failed": 0,
            "failed": 0,
            "results": [
                {
                    "raw_record_id": "row-1",
                    "status": "published",
                    "ai_safe_final_approve": {"status": "approved", "saved": 1},
                }
            ],
        },
        db_admin_submit_allowed=True,
    )

    assert acceptance["accepted"] is False
    assert any("publicly verified" in blocker for blocker in acceptance["blockers"])

def test_cli_prints_korean_json_when_parent_io_forces_ascii(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "ascii"
    env["PYTHONUTF8"] = "0"

    result = subprocess.run(  # noqa: S603 - test invokes the explicit harness path.
        [
            sys.executable,
            str(HARNESS_PATH),
            "--artifact-dir",
            str(tmp_path),
            "--max-items",
            "1",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    output = json.loads(result.stdout.decode("utf-8"))
    assert output["records"] == 1
    artifact = json.loads(Path(output["artifact_path"]).read_text(encoding="utf-8"))
    assert "햄꼬마김밥키트" in artifact["raw_records"][0]["raw_title"]

def test_fixture_hotdeal_without_image_url_remains_retained_with_anomaly(tmp_path: Path) -> None:
    input_json = tmp_path / "hotdeal-no-image.json"
    input_json.write_text(
        (
            '[{"name":"풀무원 국산콩 두부 300g","sale_price":1980,'
            '"original_price":2480,"discount_percent":20,'
            '"source":"emart","source_url":"https://emart.example/tofu"}]'
        ),
        encoding="utf-8",
    )

    artifact = harness.run_harness(_args(tmp_path, input_json=input_json, max_items=1))

    comparison = artifact["raw_vs_final"][0]
    blockers = artifact["publish_blockers"]["items"][0]["blockers"]
    assert comparison["publication_kind"] == "hotdeal"
    assert comparison["raw_image_url"] is None
    assert comparison["final_image_url"] is None
    assert "data_quality: missing hotdeal publication evidence field image_url" not in blockers
    quality_rows = {
        row["raw_record_id"]: row
        for row in artifact["quality_batch_validation"]["per_row_anomalies"]
    }
    assert "missing_hotdeal_final_image_url" in next(iter(quality_rows.values()))["image"]

def test_batch_retention_artifact_keeps_every_record_as_publish_or_raw_evidence(tmp_path: Path) -> None:
    input_json = tmp_path / "retain-all-batch.json"
    input_json.write_text(
        """[
          {"name":"풀무원 국산콩 두부 300g","sale_price":1980,"original_price":2480,"discount_percent":20,"source":"emart","source_url":"https://emart.example/tofu-hotdeal","image_url":"https://emart.example/tofu.jpg","unit":"300g"},
          {"name":"풀무원 국산콩 두부 300g","sale_price":1980,"source":"emart","source_url":"https://emart.example/tofu-observation","unit":"300g"},
          {"name":"브랜드X 말차 크런치볼 240g","sale_price":4980,"source":"emart","source_url":"https://emart.example/crunchball","unit":"240g"},
          {"name":"무제안 토마토 500g","sale_price":3980,"source":"emart","source_url":"https://emart.example/tomato","image_url":"https://emart.example/tomato.jpg","unit":"500g"}
        ]""",
        encoding="utf-8",
    )

    artifact = harness.run_harness(_args(tmp_path, input_json=input_json, max_items=4))

    assert artifact["source"]["selected_item_count"] == 4
    assert artifact["source"]["records_count"] == 4
    assert len(artifact["raw_records"]) == 4
    assert len(artifact["publish_blockers"]["items"]) == 4
    assert len(artifact["raw_vs_final"]) == 4
    assert artifact["validation_run"]["item_counts"]["records"] == 4
    assert artifact["validation_run"]["item_counts"]["publish_eligibility_items"] == 4
    by_url = {row["raw_source_url"]: row for row in artifact["raw_vs_final"]}
    assert by_url["https://emart.example/tofu-hotdeal"]["publication_kind"] == "hotdeal"
    assert "image_url" not in "; ".join(by_url["https://emart.example/tofu-observation"]["blockers"])
    assert by_url["https://emart.example/tofu-observation"]["publication_kind"] == "price_observation"
    assert all(row["final_sale_price"] for row in artifact["raw_vs_final"])
    assert all(row["final_source_url"] for row in artifact["raw_vs_final"])

def test_artifact_replay_accepts_raw_selected_items_container(tmp_path: Path) -> None:
    input_json = tmp_path / "previous-live-validation-artifact.json"
    input_json.write_text(
        json.dumps(
            {
                "run_id": "previous-run",
                "raw_selected_items": [
                    {
                        "name": "리플레이 검증 두부 300g",
                        "sale_price": 1980,
                        "source": "emart",
                        "detail_url": "https://emart.example/replay-tofu",
                        "image_url": "https://emart.example/replay-tofu.jpg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = harness.run_harness(_args(tmp_path, input_json=input_json, retain_all_input=True))

    assert artifact["validation_run"]["mode"] == "source_replay"
    assert artifact["quality_batch_validation"]["mode"] == "source_replay"
    assert artifact["source"]["selected_item_count"] == 1
    assert artifact["quality_batch_validation"]["input_count"] == 1
    assert artifact["raw_records"][0]["raw_title"] == "리플레이 검증 두부 300g"

def test_multi_source_crawler_artifact_retain_all_rows_and_reports_input_anomalies(tmp_path: Path) -> None:
    input_json = tmp_path / "mixed-crawler-artifact.json"
    input_json.write_text(
        """{
          "sources": [
            {
              "source_name": "emart",
              "crawler_name": "emart_discount",
              "schema_type": "mart_discount",
              "quality_details": {"alerts": []},
              "items": [
                {"product_id":"emart-tofu","name":"풀무원 국산콩 두부 300g","sale_price":"2,980원","detail_url":"https://emart.example/tofu","image_url":"https://emart.example/tofu.jpg","category_hint":"두부"},
                {"product_id":"emart-apple","name":"행사 사과 1kg","sale_price":"6,980원","detail_url":"https://emart.example/apple"},
                {"product_id":"emart-missing-title","sale_price":"990원","detail_url":"https://emart.example/missing-title"}
              ]
            },
            {
              "source_name": "naver-store",
              "crawler_name": "marketplace_skeleton",
              "schema_type": "shopping_product",
              "records": [
                {"external_id":"naver-1","product_name":"[스마트스토어] 제주 감귤 선물세트 3kg","current_price":19900,"link":"https://smartstore.example/tangerine","image":"https://smartstore.example/tangerine.jpg"},
                {"external_id":"naver-2","title":"마켓플레이스 리퍼 노트북 특가","price":"문의","link":"https://smartstore.example/laptop"}
              ]
            },
            {
              "source_name": "lottemart",
              "crawler_name": "lottemart_discount",
              "schema_type": "mart_discount",
              "raw_items": [
                {"sku":"lotte-ramen","normalized_name":"롯데마트 라면 멀티팩 5입","price":3980,"url":"https://lottemart.example/ramen"}
              ]
            }
          ]
        }""",
        encoding="utf-8",
    )

    artifact = harness.run_harness(
        _args(tmp_path, input_json=input_json, max_items=2, retain_all_input=True)
    )

    assert artifact["validation_run"]["mode"] == "source_replay"
    summary = artifact["quality_batch_validation"]
    assert summary["input_count"] == 6
    assert summary["selected_count"] == 6
    assert summary["retained_count"] == 6
    assert summary["invalid_row_count"] == 0
    assert summary["input_retention_valid"] is True
    assert summary["ai_batch_size"] == 20
    assert summary["ai_batch_prompt_chars"] == 8000
    assert summary["split_batch_count"] == 1
    assert artifact["validation_run"]["item_counts"]["input_retention_valid"] is True
    assert artifact["source"]["input_artifact_sources"][0]["source_name"] == "emart"
    assert {record["source_name"] for record in artifact["raw_records"]} == {
        "emart",
        "naver-store",
        "lottemart",
    }
    assert summary["input_anomaly_buckets"]["missing_product_name_title"] == 1
    assert summary["input_anomaly_buckets"]["missing_image"] >= 3
    assert summary["input_anomaly_buckets"]["missing_or_unparseable_price"] >= 1
    assert "crawler_rows_retained_with_anomalies" in artifact["source"]["alerts"]
    assert len(summary["per_row_anomalies"]) == 6
    assert summary["anomaly_counts"]["image"] >= 3

def test_retain_all_input_keeps_300_crawler_rows_in_quality_loop(tmp_path: Path) -> None:
    input_json = tmp_path / "three-hundred-crawler-rows.json"
    input_json.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_name": "emart",
                        "crawler_name": "emart_discount",
                        "items": [
                            {
                                "product_id": f"emart-{index}",
                                "name": f"이마트 행사 상품 {index}",
                                "sale_price": 1000 + index,
                                "detail_url": f"https://emart.example/{index}",
                                "image_url": f"https://emart.example/{index}.jpg",
                            }
                            for index in range(150)
                        ],
                    },
                    {
                        "source_name": "marketplace",
                        "crawler_name": "marketplace_skeleton",
                        "records": [
                            {
                                "external_id": f"market-{index}",
                                "product_name": f"마켓플레이스 상품 {index}",
                                "current_price": 5000 + index,
                                "link": f"https://market.example/{index}",
                            }
                            for index in range(150)
                        ],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = harness.run_harness(
        _args(tmp_path, input_json=input_json, max_items=20, retain_all_input=True)
    )

    summary = artifact["quality_batch_validation"]
    assert summary["input_count"] == 300
    assert summary["selected_count"] == 300
    assert summary["retained_count"] == 300
    assert summary["invalid_row_count"] == 0
    assert summary["input_retention_valid"] is True
    assert len(artifact["raw_records"]) == 300
    assert summary["split_batch_count"] > 1

def test_default_live_item_cap_rejects_more_than_300_without_http(tmp_path: Path) -> None:
    def fail_http(*_args, **_kwargs):
        raise AssertionError("item cap must block before HTTP/provider APIs")

    with pytest.raises(ValueError, match="--max-items must be between 1 and 300"):
        harness.run_harness(_args(tmp_path, max_items=301), http_json=fail_http)


def test_retain_all_input_default_cap_rejects_395_selected_rows_without_http(tmp_path: Path) -> None:
    input_json = tmp_path / "three-hundred-ninety-five-crawler-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"이마트 395 기본 제한 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(395)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_http(*_args, **_kwargs):
        raise AssertionError("item cap must block before HTTP/provider APIs")

    with pytest.raises(ValueError, match="selected live item count 395 exceeds cap 300"):
        harness.run_harness(
            _args(tmp_path, input_json=input_json, retain_all_input=True),
            http_json=fail_http,
        )


def test_explicit_large_live_batch_opt_in_allows_395_dry_run_rows(tmp_path: Path) -> None:
    input_json = tmp_path / "three-hundred-ninety-five-opt-in-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {
                    "product_id": f"emart-395-{index}",
                    "name": f"이마트 395 명시 승인 상품 {index}",
                    "sale_price": 1000 + index,
                    "detail_url": f"https://emart.example/large/{index}",
                    "source": "emart",
                }
                for index in range(395)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_http(*_args, **_kwargs):
        raise AssertionError("dry-run opt-in must not call HTTP/provider APIs")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            max_items=395,
            retain_all_input=True,
            allow_large_live_batch=True,
            max_live_items_cap=395,
        ),
        http_json=fail_http,
    )

    summary = artifact["quality_batch_validation"]
    assert summary["input_count"] == 395
    assert summary["selected_count"] == 395
    assert summary["retained_count"] == 395
    assert artifact["provider_response_summary"]["called"] is False
    assert artifact["decisions"]["bounds"]["allow_large_live_batch"] is True
    assert artifact["decisions"]["bounds"]["max_live_items_cap"] == 395
    assert summary["quality_gate"]["full_input_attempted"] is True
    assert summary["quality_gate"]["sample_only"] is False
    assert summary["quality_gate"]["scale_claim"] == "blocked_not_full_source_quality"


def test_dry_run_does_not_report_missing_ai_taxonomy_as_category_anomaly(tmp_path: Path) -> None:
    input_json = tmp_path / "no-provider-raw-taxonomy-absent.json"
    input_json.write_text(
        json.dumps(
            [
                {
                    "product_id": "no-ai-taxonomy-1",
                    "name": "원천 분류 없는 대량 검증 상품",
                    "sale_price": 1290,
                    "detail_url": "https://emart.example/no-taxonomy",
                    "source": "emart",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_http(*_args, **_kwargs):
        raise AssertionError("dry-run taxonomy check must not call HTTP/provider APIs")

    artifact = harness.run_harness(
        _args(tmp_path, input_json=input_json, retain_all_input=True),
        http_json=fail_http,
    )

    quality = artifact["quality_batch_validation"]
    assert quality["provider"]["called"] is False
    assert quality["anomaly_counts"]["category"] == 0
    assert quality["anomaly_counts"]["keyword"] == 0
    assert not any(
        "category/taxonomy" in blocker
        for blocker in quality["quality_gate"]["blockers"]
    )


def test_fractional_source_discount_percent_is_preserved_without_overwrite_risk(tmp_path: Path) -> None:
    input_json = tmp_path / "fractional-percent-discount.json"
    input_json.write_text(
        json.dumps(
            [
                {
                    "product_id": "fractional-percent-1",
                    "name": "반퍼센트 할인 원천 상품",
                    "sale_price": 20890,
                    "original_price": 21000,
                    "discount_percent": 0.5,
                    "detail_url": "https://emart.example/fractional-percent",
                    "image_url": "https://emart.example/fractional-percent.jpg",
                    "source": "emart",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = harness.run_harness(
        _args(tmp_path, input_json=input_json, retain_all_input=True)
    )

    comparison = artifact["raw_vs_final"][0]
    assert comparison["raw_discount_percent"] == 0.5
    assert comparison["final_discount_percent"] == 0.5
    assert artifact["quality_batch_validation"]["anomaly_counts"]["source_owned_overwrite_risk"] == 0
    assert artifact["quality_batch_validation"]["quality_gate"]["source_owned_overwrite_risks"] == []

def test_live_provider_requires_explicit_provider_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires --provider-id"):
        harness.run_harness(_args(tmp_path, allow_live_provider=True))

def test_live_crawler_requires_explicit_allow_flag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires --allow-live-crawl"):
        harness.run_harness(_args(tmp_path, live_crawler="emart"))

def test_stub_mode_observability_records_attempt_without_real_provider_quota(tmp_path: Path) -> None:
    label_timeouts: list[float] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            label_timeouts.append(_kwargs["timeout_seconds"])
            return {"raw_batch_id": "batch-stub", "provider_calls": 1, "ai_batches": 1, "proposal_ids": []}
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(tmp_path, allow_live_provider=True, provider_id="google-dev", provider_model="gemini-test", validation_mode="stub", max_items=1),
        http_json=fake_http,
    )

    metadata = artifact["validation_run"]
    assert metadata["mode"] == "stub"
    assert metadata["provider"] == "google-dev"
    assert metadata["model"] == "gemini-test"
    assert metadata["key_present"] is False
    assert metadata["live_opt_in"] is True
    assert metadata["live_call_attempted"] is True
    assert metadata["live_call_succeeded"] is True
    assert metadata["finished_at"]
    assert label_timeouts == [harness.DEFAULT_LABEL_TIMEOUT_SECONDS]
    assert artifact["label_timeout_seconds"] == harness.DEFAULT_LABEL_TIMEOUT_SECONDS
    assert artifact["decisions"]["bounds"]["label_timeout_seconds"] == harness.DEFAULT_LABEL_TIMEOUT_SECONDS


def test_label_timeout_option_is_capped_and_forwarded_to_label_call(tmp_path: Path) -> None:
    label_timeouts: list[float] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            label_timeouts.append(_kwargs["timeout_seconds"])
            return {"raw_batch_id": "batch-stub", "provider_calls": 1, "ai_batches": 1, "proposal_ids": []}
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="stub",
            max_items=1,
            label_timeout_seconds=harness.MAX_LABEL_TIMEOUT_SECONDS + 100,
        ),
        http_json=fake_http,
    )

    assert label_timeouts == [harness.MAX_LABEL_TIMEOUT_SECONDS]
    assert artifact["label_timeout_seconds"] == harness.MAX_LABEL_TIMEOUT_SECONDS
    assert artifact["decisions"]["bounds"]["label_timeout_seconds_requested"] == harness.MAX_LABEL_TIMEOUT_SECONDS + 100


def test_chunked_live_labeling_records_partial_timeout_retry_candidates(tmp_path: Path) -> None:
    input_json = tmp_path / "four-live-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"청크 검증 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(4)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    post_chunks: list[list[str]] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            raw_ids = [record["raw_record_id"] for record in body["records"]]
            post_chunks.append(raw_ids)
            if len(post_chunks) == 1:
                return {
                    "status": "completed",
                    "raw_batch_id": "batch-chunk-1",
                    "provider_mode": "stub",
                    "provider_calls": 1,
                    "ai_batches": 1,
                    "proposal_ids": [],
                }
            raise TimeoutError("label chunk timed out after bounded timeout")
        if method == "GET" and "/api/review/audit?" in url:
            assert "batch-chunk-1" in url
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            assert "batch-chunk-1" in url
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            retain_all_input=True,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="live",
            ai_batch_size=2,
            max_provider_calls=2,
        ),
        http_json=fake_http,
    )

    provider = artifact["provider_response_summary"]
    assert len(post_chunks) == 2
    assert len(artifact["raw_records"]) == 4
    assert provider["http_label_calls"] == 2
    assert provider["provider_calls"] == 1
    assert provider["successful_chunk_count"] == 1
    assert provider["failed_chunk_count"] == 1
    assert provider["partial_results"] is True
    assert provider["chunks"][0]["status"] == "success"
    assert provider["chunks"][1]["status"] == "failed"
    assert provider["chunks"][1]["retryable"] is True
    assert provider["missing_label_count"] == 2
    assert provider["missing_label_raw_record_ids"] == post_chunks[1]
    assert artifact["validation_run"]["live_call_succeeded"] is False
    assert artifact["validation_run"]["error"]["class"] == "TimeoutError"
    quality = artifact["quality_batch_validation"]
    assert quality["provider"]["partial_results"] is True
    assert quality["retryable_provider_failures"][0]["raw_record_ids"] == post_chunks[1]
    missing_group = next(
        group
        for group in quality["reviewer_retry_candidates"]["groups"]
        if group["missing_field"] == "missing_label"
    )
    assert missing_group["raw_record_ids"] == post_chunks[1]


def test_retryable_label_chunk_is_retried_with_minimum_spacing(tmp_path: Path) -> None:
    input_json = tmp_path / "retry-live-row.json"
    input_json.write_text(
        json.dumps([{"name": "재시도 검증 상품", "sale_price": 1200, "source": "emart"}], ensure_ascii=False),
        encoding="utf-8",
    )
    attempts = 0
    sleeps: list[float] = []

    def flaky_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal attempts
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            attempts += 1
            if attempts == 1:
                raise RuntimeError(
                    "POST http://127.0.0.1:8003/api/ingest/raw-records/label failed: "
                    "[WinError 10054] 현재 연결은 원격 호스트에 의해 강제로 끊겼습니다"
                )
            return {
                "status": "completed",
                "raw_batch_id": "batch-retried",
                "provider_mode": "live",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            retain_all_input=True,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="live",
            max_provider_calls=2,
            label_chunk_retries=1,
            label_call_min_interval_seconds=10,
        ),
        http_json=flaky_http,
        sleeper=sleeps.append,
    )

    provider = artifact["provider_response_summary"]
    assert attempts == 2
    assert sleeps and sleeps[0] >= 9.9
    assert provider["http_label_calls"] == 2
    assert provider["successful_chunk_count"] == 1
    assert provider["failed_chunk_count"] == 0
    assert provider["chunks"][0]["attempt_count"] == 2
    assert provider["chunks"][0]["attempts"][0]["retryable"] is True
    assert provider["chunks"][0]["attempts"][1]["slept_seconds"] >= 9.9
    assert provider["label_call_min_interval_seconds"] == 10
    assert artifact["validation_run"]["live_call_succeeded"] is True


def test_retryable_label_chunk_bound_exhaustion_preserves_first_transport_failure(
    tmp_path: Path,
) -> None:
    input_json = tmp_path / "bound-exhaustion-row.json"
    input_json.write_text(
        json.dumps([{"name": "호출 제한 재시도 상품", "sale_price": 1200, "source": "emart"}], ensure_ascii=False),
        encoding="utf-8",
    )
    attempts = 0

    def refusing_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal attempts
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            attempts += 1
            raise RuntimeError(
                "POST http://127.0.0.1:8003/api/ingest/raw-records/label failed: "
                "[WinError 10061] 대상 컴퓨터에서 연결을 거부했으므로 연결하지 못했습니다"
            )
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            retain_all_input=True,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="live",
            max_provider_calls=1,
            label_chunk_retries=1,
        ),
        http_json=refusing_http,
    )

    provider = artifact["provider_response_summary"]
    chunk = provider["chunks"][0]
    first_attempt = chunk["attempts"][0]
    assert attempts == 1
    assert provider["http_label_calls"] == 1
    assert provider["max_provider_calls"] == 1
    assert provider["provider_call_bound_exhausted"] is True
    assert provider["provider_call_bound_exhaustion"]["attempted_label_calls"] == 1
    assert chunk["call_bound_exhausted"] is True
    assert chunk["blocked_retry"]["class"] == "ProviderCallBoundExceeded"
    assert first_attempt["retryable"] is True
    assert "10061" in first_attempt["error"]["message"]
    assert artifact["validation_run"]["error"] == provider["error"]
    assert "10061" in artifact["validation_run"]["error"]["message"]
    assert "ProviderCallBoundExceeded" in json.dumps(chunk, ensure_ascii=False)


def test_chunked_live_labeling_enforces_max_provider_call_bound(tmp_path: Path) -> None:
    input_json = tmp_path / "three-live-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"호출 제한 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(3)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_http(*_args, **_kwargs):
        raise AssertionError("provider bound must block before HTTP calls")

    with pytest.raises(ValueError, match="provider call bound exceeded"):
        harness.run_harness(
            _args(
                tmp_path,
                input_json=input_json,
                retain_all_input=True,
                allow_live_provider=True,
                provider_id="google-dev",
                ai_batch_size=2,
                max_provider_calls=1,
            ),
            http_json=fail_http,
        )


def test_chunked_live_labeling_passes_remaining_provider_call_cap(tmp_path: Path) -> None:
    input_json = tmp_path / "four-live-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"남은 호출 제한 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(4)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    caps: list[int] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            caps.append(body["max_provider_calls"])
            return {
                "status": "labeled",
                "raw_batch_id": f"batch-{len(caps)}",
                "provider_mode": "stub",
                "provider_calls": 2 if len(caps) == 1 else 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            retain_all_input=True,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="live",
            ai_batch_size=2,
            max_provider_calls=3,
        ),
        http_json=fake_http,
    )

    assert caps == [3, 1]
    assert artifact["provider_response_summary"]["provider_calls"] == 3


def test_no_key_live_opt_in_is_observably_skipped_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_TEST_API_KEY", raising=False)

    def fail_http(*_args, **_kwargs):
        raise AssertionError("missing provider key must skip before HTTP/provider APIs")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            provider_key_alias="WALLETSAVIOR_TEST_MISSING_PROVIDER_KEY",
            max_items=1,
        ),
        http_json=fail_http,
    )

    metadata = artifact["validation_run"]
    assert metadata["mode"] == "skipped"
    assert metadata["key_present"] is False
    assert metadata["live_opt_in"] is True
    assert metadata["live_call_attempted"] is False
    assert metadata["live_call_succeeded"] is False
    assert metadata["skip_reason"] == "missing provider key alias WALLETSAVIOR_TEST_MISSING_PROVIDER_KEY"
    assert artifact["provider_response_summary"]["called"] is False

def test_failed_provider_observability_sanitizes_error_without_secret_leak(tmp_path: Path) -> None:
    def failing_http(*_args, **_kwargs):
        raise RuntimeError(
            f"429 quota exhausted GOOGLE_API_KEY={FAKE_GOOGLE_KEY} token=super-secret-value"
        )

    artifact = harness.run_harness(
        _args(tmp_path, allow_live_provider=True, provider_id="google-dev", validation_mode="live", max_items=1),
        http_json=failing_http,
    )

    metadata = artifact["validation_run"]
    message = metadata["error"]["message"]
    assert metadata["mode"] == "live"
    assert metadata["live_call_attempted"] is True
    assert metadata["live_call_succeeded"] is False
    assert metadata["error"]["class"] == "RuntimeError"
    assert "AIza" not in message
    assert "super-secret-value" not in message
    assert "[REDACTED]" in message
    assert artifact["provider_response_summary"]["error"] == metadata["error"]


def test_unicode_encode_error_artifact_includes_sanitized_location(tmp_path: Path) -> None:
    def failing_http(*_args, **_kwargs):
        raise UnicodeEncodeError("ascii", "이마트", 0, 3, "ordinal not in range(128)")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            validation_mode="live",
            max_items=1,
        ),
        http_json=failing_http,
    )

    error = artifact["validation_run"]["error"]
    assert error["class"] == "UnicodeEncodeError"
    assert error["location"]["function"] == "failing_http"
    assert error["location"]["file"] == "test_live_validation_harness_v2.py"
    assert "이마트" not in error["message"]
    assert artifact["provider_response_summary"]["error"] == error


def test_timeout_error_sanitization_preserves_korean_context_without_secret_leak(tmp_path: Path) -> None:
    def failing_http(*_args, **_kwargs):
        raise RuntimeError(
            "POST http://127.0.0.1:8003/api/ingest/raw-records/label failed: "
            f"서버 응답 지연으로 timed out GOOGLE_API_KEY={FAKE_GOOGLE_KEY}"
        )

    artifact = harness.run_harness(
        _args(tmp_path, allow_live_provider=True, provider_id="google-dev", validation_mode="live", max_items=1),
        http_json=failing_http,
    )

    metadata = artifact["validation_run"]
    message = metadata["error"]["message"]
    assert metadata["live_call_attempted"] is True
    assert metadata["live_call_succeeded"] is False
    assert "timed out" in message
    assert "서버 응답 지연" in message
    assert "AIza" not in message

def test_live_mode_metadata_shape_can_be_built_without_real_quota() -> None:
    metadata = harness.build_validation_run_metadata(
        mode="live",
        provider="google-dev",
        model="gemini-test",
        key_present=True,
        live_opt_in=True,
        live_call_attempted=False,
        live_call_succeeded=False,
        item_counts={"records": 1},
    )

    assert set(metadata) == {
        "mode",
        "provider",
        "model",
        "key_present",
        "live_opt_in",
        "live_call_attempted",
        "live_call_succeeded",
        "skip_reason",
        "error",
        "started_at",
        "finished_at",
        "item_counts",
    }
    assert metadata["mode"] == "live"
    assert metadata["key_present"] is True
    assert metadata["item_counts"] == {"records": 1}

def test_exact_catalog_and_learned_alias_are_not_generalization() -> None:
    catalog = {"새우"}
    learned = {"꼬마김밥키트"}

    exact = harness.classify_evidence({"name": "냉동 새우 300g"}, catalog_terms=catalog, learned_terms=learned)
    learned_alias = harness.classify_evidence({"name": "햄 꼬마김밥키트"}, catalog_terms=catalog, learned_terms=learned)
    inferred = harness.classify_evidence({"name": "처음 보는 상품"}, {"canonical_name": "모델 추론 상품"})

    assert exact["evidence_class"] == "exact_catalog"
    assert exact["trust_label"] == "reuse_exact_catalog"
    assert exact["counts_as_generalization"] is False
    assert learned_alias["evidence_class"] == "learned_alias"
    assert learned_alias["trust_label"] == "reuse_learned_alias"
    assert learned_alias["counts_as_generalization"] is False
    assert inferred["counts_as_generalization"] is True

def test_catalog_and_learned_terms_do_not_match_inside_unrelated_compounds() -> None:
    catalog = {"새우"}
    learned = {"꼬마김밥키트"}

    snack = harness.classify_evidence(
        {"name": "오리온 새우깡 90g"},
        catalog_terms=catalog,
        learned_terms=learned,
    )
    renamed = harness.classify_evidence(
        {"name": "한돈 꼬마 김밥 만들기 세트 180g"},
        {"canonical_name": "모델 추론 김밥 만들기 세트", "keywords": ["김밥만들기세트"]},
        catalog_terms=catalog,
        learned_terms=learned,
    )

    assert snack["evidence_class"] == "new_unknown"
    assert snack["counts_as_generalization"] is True
    assert renamed["evidence_class"] == "model_inferred"
    assert renamed["counts_as_generalization"] is True

def test_holdout_evaluation_separates_reuse_from_new_product_cases() -> None:
    records = [
        Namespace(raw_record_id="exact", raw_title="냉동 새우 300g", raw_payload={"name": "냉동 새우 300g"}),
        Namespace(raw_record_id="learned", raw_title="햄 꼬마김밥키트", raw_payload={"name": "햄 꼬마김밥키트"}),
        Namespace(raw_record_id="renamed", raw_title="브랜드A 김밥 만들기 세트 180g", raw_payload={"name": "브랜드A 김밥 만들기 세트 180g"}),
        Namespace(raw_record_id="new-sku", raw_title="처음보는 그릭요거트볼 120g", raw_payload={"name": "처음보는 그릭요거트볼 120g"}),
        Namespace(raw_record_id="ambiguous", raw_title="오리온 새우깡 90g", raw_payload={"name": "오리온 새우깡 90g"}),
    ]
    provider_items = {
        "renamed": {"canonical_name": "브랜드A 김밥 만들기 세트", "keywords": ["김밥만들기세트"]},
        "new-sku": {"canonical_name": "처음보는 그릭요거트볼", "keywords": ["그릭요거트볼"]},
    }

    result = harness.evaluate_holdout_generalization(
        records,
        provider_items,
        catalog_terms={"새우"},
        learned_terms={"꼬마김밥키트"},
    )
    by_id = {item["raw_record_id"]: item for item in result["evidence"]}

    assert by_id["exact"]["evidence_class"] == "exact_catalog"
    assert by_id["exact"]["counts_as_generalization"] is False
    assert by_id["learned"]["evidence_class"] == "learned_alias"
    assert by_id["learned"]["counts_as_generalization"] is False
    assert by_id["renamed"]["evidence_class"] == "model_inferred"
    assert by_id["new-sku"]["evidence_class"] == "model_inferred"
    assert by_id["ambiguous"]["evidence_class"] == "new_unknown"
    assert result["generalization_success_count"] == 3

def test_live_provider_evidence_uses_returned_proposals(tmp_path: Path) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    raw_record_id = ""
    input_json = tmp_path / "raw.json"
    input_json.write_text(
        '[{"name":"브랜드 없는 미래 신상품","sale_price":"1234원","source":"emart"}]',
        encoding="utf-8",
    )

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal raw_record_id
        calls.append((method, url, body))
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            raw_record_id = body["records"][0]["raw_record_id"]
            return {
                "raw_batch_id": "batch-live",
                "provider_mode": "stub",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": ["p1"],
            }
        if method == "GET" and url.endswith("/api/review/proposals/p1"):
            return {
                "proposal": {
                    "proposal_id": "p1",
                    "target_field": "canonical_name",
                    "proposed_value": "모델이 추론한 신상품",
                    "provenance": {
                        "raw_record_id": raw_record_id,
                    },
                }
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": []}
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            source_name="manual-test",
            crawler_name="manual-test",
            input_json=input_json,
            max_items=1,
        ),
        http_json=fake_http,
    )

    assert calls[0][0] == "POST"
    assert artifact["provider_response_summary"]["provider_mode"] == "stub"
    evidence = artifact["holdout_generalization"]["evidence"][0]
    assert evidence["evidence_class"] == "model_inferred"
    assert evidence["counts_as_generalization"] is True

def test_raw_vs_final_artifact_captures_price_observation_taxonomy_and_keywords(tmp_path: Path) -> None:
    input_json = tmp_path / "tofu-price-observation.json"
    input_json.write_text(
        (
            '[{"name":"풀무원 국산콩 두부 300g","sale_price":1980,'
            '"source":"emart","source_url":"https://emart.example/tofu",'
            '"category_id":"processed.tofu.firm","keywords":["두부"]}]'
        ),
        encoding="utf-8",
    )
    raw_record_id = ""

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal raw_record_id
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            raw_record_id = body["records"][0]["raw_record_id"]
            return {"raw_batch_id": "batch-tofu", "provider_calls": 0, "ai_batches": 0, "proposal_ids": [f"{raw_record_id}:p"]}
        if method == "GET" and "/api/review/proposals/" in url:
            raw_id = url.rsplit("/", 1)[-1].removesuffix(":p")
            return {
                "proposal": {
                    "proposal_id": f"{raw_id}:p",
                    "target_field": "category_id",
                    "proposed_value": "processed.tofu.firm",
                    "provenance": {"raw_record_id": raw_id},
                }
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": raw_record_id,
                        "eligible": True,
                        "publication_kind": "price_observation",
                        "price_observation_only": True,
                        "item": {
                            "name": "풀무원 국산콩 두부 300g",
                            "sale_price": 1980,
                            "original_price": None,
                            "discount_percent": None,
                            "source_url": "https://emart.example/tofu",
                            "category_id": "processed.tofu.firm",
                            "keywords": ["두부"],
                            "publication_kind": "price_observation",
                            "price_observation_only": True,
                        },
                        "blockers": [],
                    }
                ]
            }
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            allow_live_provider=True,
            provider_id="stubbed-provider",
            max_items=1,
        ),
        http_json=fake_http,
    )

    comparison = artifact["raw_vs_final"][0]
    assert comparison["raw_price"] == 1980
    assert comparison["final_sale_price"] == 1980
    assert comparison["raw_original_price"] is None
    assert comparison["final_original_price"] is None
    assert comparison["raw_discount_percent"] is None
    assert comparison["final_discount_percent"] is None
    assert comparison["raw_category_id"] == "processed.tofu.firm"
    assert comparison["final_category_id"] == "processed.tofu.firm"
    assert comparison["raw_keywords"] == ["두부"]
    assert comparison["final_keywords"] == ["두부"]
    assert comparison["publication_kind"] == "price_observation"
    assert comparison["price_observation_only"] is True

def test_db_admin_submit_skips_when_no_rows_are_eligible(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            return {
                "raw_batch_id": "batch-live",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {"items": [{"raw_record_id": "x", "eligible": False}]}
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            raise AssertionError("must not publish when no row is eligible")
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            allow_db_admin_submit=True,
            max_items=1,
        ),
        http_json=fake_http,
    )

    assert artifact["db_admin_submit_result"] == {
        "skipped": True,
        "reason": "no ai-safe-final-approve eligible rows after publish eligibility gates",
        "db_admin_submit_plan": {
            "mode": "ai_safe_final_approve_only",
            "submit_allowed_rows": 0,
            "raw_record_ids": [],
            "confirm_count": 0,
            "held_for_review_count": 1,
            "held_for_review_rows": [
                {
                    "raw_record_id": "x",
                    "status": None,
                    "eligible": False,
                    "ai_safe_final_approve_eligible": None,
                    "db_handoff_mode": None,
                    "publication_kind": None,
                    "discount_claim_status": None,
                    "reasons": ["not publish eligible"],
                }
            ],
            "held_reason_counts": {"not publish eligible": 1},
            "eligible_but_not_final_safe_count": 0,
            "operator_safety_rule": (
                "Only rows marked ai_safe_final_approve_eligible are submitted; eligible rows "
                "with keyword/category/unit/audit caveats stay held for DB-admin/manual review."
            ),
        },
    }


def test_db_admin_submit_posts_selected_ai_safe_pending_final_approval(tmp_path: Path) -> None:
    raw_record_id = "pending-final-approval-row"
    calls: list[tuple[str, str, dict | None]] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        calls.append((method, url, body))
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            return {
                "raw_batch_id": "batch-pending-final",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": raw_record_id,
                        "status": "pending_db_review",
                        "eligible": False,
                        "ai_safe_final_approve_eligible": True,
                        "db_ingestion_id": "782",
                        "item": {
                            "name": "풀무원 국산콩 두부 300g",
                            "sale_price": 1980,
                            "source_url": "https://emart.example/products/tofu-300g",
                        },
                        "blockers": [
                            "pending_db_review: already submitted to DB-admin; wait for final DB-admin approval or rollback the pending ingestion before resubmitting"
                        ],
                    }
                ]
            }
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            assert body == {
                "raw_record_ids": [raw_record_id],
                "reviewer_id": "manual-test",
                "confirm_count": 1,
                "batch_id": "batch-pending-final",
            }
            return {
                "submitted_to_db_admin": 1,
                "ai_safe_final_approved": 1,
                "public_db_verified": 1,
                "rollback_re_review_supported": 1,
                "pending_db_review": 0,
                "results": [
                    {
                        "raw_record_id": raw_record_id,
                        "status": "published",
                        "skipped_duplicate": True,
                        "ai_safe_final_approve": {
                            "status": "approved",
                            "saved": 1,
                            "public_db_verification": {"verified": True},
                            "rollback_supported": True,
                            "re_review_supported": True,
                        },
                    }
                ],
            }
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            allow_db_admin_submit=True,
            max_items=1,
        ),
        http_json=fake_http,
    )

    assert any(method == "POST" and url.endswith("/api/review/publish-approved") for method, url, _ in calls)
    assert artifact["db_admin_submit_result"]["ai_safe_final_approved"] == 1
    assert artifact["db_admin_acceptance"]["accepted"] is True


def test_db_admin_submit_posts_eligible_rows_and_records_raw_vs_final(tmp_path: Path) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    raw_record_id = ""
    input_json = tmp_path / "raw.json"
    input_json.write_text(
        (
            '[{"name":"원천명 두부 300g","sale_price":"1980원","source":"emart",'
            '"source_url":"https://emart.example/products/tofu-300g",'
            '"original_price":null,"discount_percent":null,"category_id":"processed.tofu.firm",'
            '"keywords":["두부"]}]'
        ),
        encoding="utf-8",
    )

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal raw_record_id
        calls.append((method, url, body))
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            raw_record_id = body["records"][0]["raw_record_id"]
            return {
                "raw_batch_id": "batch-live",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": raw_record_id,
                        "eligible": True,
                        "ai_safe_final_approve_eligible": True,
                        "status": "approved",
                        "db_handoff_mode": "ai_safe_final_approve",
                        "item": {
                            "name": "풀무원 국산콩 두부 300g",
                            "sale_price": 1980,
                            "original_price": None,
                            "discount_percent": None,
                            "source_url": "https://emart.example/products/tofu-300g",
                            "category_id": "processed.tofu.firm",
                            "keywords": ["두부"],
                            "publication_kind": "price_observation",
                            "price_observation_only": True,
                        },
                        "blockers": [],
                    }
                ]
            }
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            assert body == {
                "raw_record_ids": [raw_record_id],
                "reviewer_id": "manual-test",
                "confirm_count": 1,
                "batch_id": "batch-live",
            }
            return {
                "submitted_to_db_admin": 1,
                "pending_db_review": 1,
                "results": [{"raw_record_id": raw_record_id, "status": "pending_db_review"}],
            }
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            allow_live_provider=True,
            provider_id="google-dev",
            allow_db_admin_submit=True,
            max_items=1,
        ),
        http_json=fake_http,
    )

    assert any(method == "POST" and url.endswith("/api/review/publish-approved") for method, url, _ in calls)
    assert artifact["db_admin_submit_result"]["submitted_to_db_admin"] == 1
    comparison = artifact["raw_vs_final"][0]
    assert comparison["raw_title"] == "원천명 두부 300g"
    assert comparison["final_name"] == "풀무원 국산콩 두부 300g"
    assert comparison["raw_price"] == 1980
    assert comparison["final_sale_price"] == 1980
    assert comparison["raw_category_id"] == "processed.tofu.firm"
    assert comparison["final_category_id"] == "processed.tofu.firm"
    assert comparison["raw_keywords"] == ["두부"]
    assert comparison["final_keywords"] == ["두부"]
    assert comparison["publication_kind"] == "price_observation"
    assert comparison["price_observation_only"] is True
    assert artifact["db_admin_submit_plan"]["submit_allowed_rows"] == 1


def test_db_admin_submit_holds_eligible_rows_that_are_not_final_approve_safe(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            return {
                "raw_batch_id": "batch-needs-db-review",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": "keyword-review-row",
                        "status": "approved",
                        "eligible": True,
                        "ai_safe_final_approve_eligible": False,
                        "db_handoff_mode": "db_admin_review",
                        "publication_kind": "price_observation",
                        "post_publish_audit_flags": [{"code": "db_keyword_proposal_unresolved"}],
                        "blockers": [],
                    }
                ]
            }
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            raise AssertionError("eligible-but-not-final-safe rows must stay held")
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            allow_db_admin_submit=True,
            max_items=1,
        ),
        http_json=fake_http,
    )

    plan = artifact["db_admin_submit_plan"]
    assert plan["submit_allowed_rows"] == 0
    assert plan["eligible_but_not_final_safe_count"] == 1
    assert plan["held_reason_counts"] == {"post_publish_audit_flags": 1}
    assert artifact["db_admin_submit_result"]["skipped"] is True


def test_db_admin_submit_batches_multiple_ai_safe_rows_and_holds_caveats(tmp_path: Path) -> None:
    posted_body: dict | None = None

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal posted_body
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            return {
                "raw_batch_id": "batch-multi-safe",
                "provider_calls": 1,
                "ai_batches": 1,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {"issues": []}
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": "safe-price-observation-1",
                        "status": "approved",
                        "eligible": True,
                        "ai_safe_final_approve_eligible": True,
                        "db_handoff_mode": "ai_safe_final_approve",
                        "publication_kind": "price_observation",
                        "blockers": [],
                    },
                    {
                        "raw_record_id": "safe-price-observation-2",
                        "status": "approved",
                        "eligible": True,
                        "ai_safe_final_approve_eligible": True,
                        "db_handoff_mode": "ai_safe_final_approve",
                        "publication_kind": "price_observation",
                        "blockers": [],
                    },
                    {
                        "raw_record_id": "keyword-review-row",
                        "status": "approved",
                        "eligible": True,
                        "ai_safe_final_approve_eligible": False,
                        "db_handoff_mode": "db_admin_review",
                        "publication_kind": "price_observation",
                        "post_publish_audit_flags": [{"code": "db_keyword_proposal_unresolved"}],
                        "blockers": [],
                    },
                ]
            }
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            posted_body = body
            return {
                "submitted_to_db_admin": 2,
                "ai_safe_final_approved": 2,
                "public_db_verified": 2,
                "rollback_re_review_supported": 2,
                "pending_db_review": 0,
                "results": [
                    {"raw_record_id": "safe-price-observation-1", "status": "published"},
                    {"raw_record_id": "safe-price-observation-2", "status": "published"},
                ],
            }
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_provider=True,
            provider_id="google-dev",
            allow_db_admin_submit=True,
            max_items=2,
        ),
        http_json=fake_http,
    )

    assert posted_body == {
        "raw_record_ids": ["safe-price-observation-1", "safe-price-observation-2"],
        "reviewer_id": "manual-test",
        "confirm_count": 2,
        "batch_id": "batch-multi-safe",
    }
    assert artifact["db_admin_submit_plan"]["submit_allowed_rows"] == 2
    assert artifact["db_admin_submit_plan"]["held_for_review_count"] == 1
    assert artifact["db_admin_acceptance"]["ai_safe_final_approved"] == 2

def test_provider_items_from_proposals_merges_lists_and_attributes() -> None:
    provider_items = harness.provider_items_from_proposals(
        [
            {
                "target_field": "canonical_name",
                "proposed_value": "풀무원 국산콩 두부 300g",
                "provenance": {"raw_record_id": "r1"},
            },
            {
                "target_field": "keywords",
                "proposed_value": ["두부", "국산콩"],
                "provenance": {"raw_record_id": "r1"},
            },
            {
                "target_field": "keywords",
                "proposed_value": ["두부", "찌개용"],
                "provenance": {"raw_record_id": "r1"},
            },
            {
                "target_field": "attributes.storage_type",
                "proposed_value": "chilled",
                "provenance": {"raw_record_id": "r1"},
            },
            {
                "target_field": "canonical_name",
                "proposed_value": "ignored-without-raw-id",
                "provenance": {},
            },
        ]
    )

    assert provider_items == {
        "r1": {
            "raw_record_id": "r1",
            "canonical_name": "풀무원 국산콩 두부 300g",
            "keywords": ["두부", "국산콩", "찌개용"],
            "attributes": {"storage_type": "chilled"},
        }
    }

def test_live_crawler_zero_result_diagnostics_are_carried_into_artifact(tmp_path: Path, monkeypatch) -> None:
    async def fake_live_crawler(_crawler_name: str, _max_pages: int, _max_items: int, _max_requests: int):
        return {
            "crawler_name": "emart",
            "status": "failed",
            "strategy_used": "requests",
            "items_count": 0,
            "crawler_items_count": 0,
            "errors": [
                {
                    "strategy_name": "requests",
                    "error_type": "empty_response",
                    "error_msg": "Source returned zero candidate rows.",
                }
            ],
            "error_msg": "Source returned zero candidate rows.",
            "quality_score": 0.0,
            "quality_details": {
                "alerts": ["zero_valid_items", "zero_source_raw_rows"],
                "zero_result_diagnostic": {
                    "stage": "source_zero_raw_rows",
                    "message": "Source returned zero candidate rows. Check network/source blocking.",
                    "operator_action": "Check network/source blocking.",
                    "counts": {"source_raw": 0, "parsed": 0, "valid": 0, "invalid_or_dropped": 0},
                    "source_errors": [],
                },
            },
            "alerts": ["zero_valid_items", "zero_source_raw_rows"],
            "zero_result_diagnostic": {
                "stage": "source_zero_raw_rows",
                "message": "Source returned zero candidate rows. Check network/source blocking.",
                "operator_action": "Check network/source blocking.",
                "counts": {"source_raw": 0, "parsed": 0, "valid": 0, "invalid_or_dropped": 0},
                "source_errors": [],
            },
            "items": [],
        }

    monkeypatch.setattr(harness, "_run_live_crawler", fake_live_crawler)

    artifact = harness.run_harness(
        _args(tmp_path, allow_live_crawl=True, live_crawler="emart", max_items=1)
    )

    assert artifact["source"]["records_count"] == 0
    assert artifact["source"]["live_crawl"]["error_msg"]
    assert "zero_source_raw_rows" in artifact["source"]["alerts"]
    stages = {diag["stage"] for diag in artifact["source"]["diagnostics"]}
    assert "source_zero_raw_rows" in stages
    assert "crawler_returned_zero_selected_items" in stages


def test_live_crawler_artifact_records_no_db_bounded_request_limits(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, int | str] = {}

    async def fake_live_crawler(crawler_name: str, max_pages: int, max_items: int, max_requests: int):
        captured.update(
            {
                "crawler_name": crawler_name,
                "max_pages": max_pages,
                "max_items": max_items,
                "max_requests": max_requests,
            }
        )
        return {
            "crawler_name": crawler_name,
            "status": "success",
            "strategy_used": "playwright",
            "items_count": 1,
            "crawler_items_count": 1,
            "errors": None,
            "error_msg": None,
            "quality_score": 100.0,
            "quality_details": {},
            "alerts": [],
            "zero_result_diagnostic": None,
            "run_limits": {"max_items": max_items, "max_pages": max_pages, "max_requests": max_requests},
            "items": [
                {
                    "name": "fixture tofu",
                    "sale_price": 1980,
                    "source_url": "https://example.test/a",
                    "image_url": "https://example.test/a.jpg",
                }
            ],
        }

    monkeypatch.setattr(harness, "_run_live_crawler", fake_live_crawler)

    artifact = harness.run_harness(
        _args(
            tmp_path,
            allow_live_crawl=True,
            live_crawler="homeplus",
            max_items=2,
            max_pages=1,
            max_crawler_requests=1,
            max_provider_calls=0,
        )
    )

    assert captured == {"crawler_name": "homeplus", "max_pages": 1, "max_items": 2, "max_requests": 1}
    assert artifact["decisions"]["live_crawl_allowed"] is True
    assert artifact["decisions"]["live_provider_allowed"] is False
    assert artifact["decisions"]["db_admin_submit_allowed"] is False
    assert artifact["decisions"]["bounds"]["max_crawler_requests"] == 1
    assert artifact["source"]["live_crawl"]["run_limits"] == {"max_items": 2, "max_pages": 1, "max_requests": 1}


def test_selected_rows_rejected_by_raw_record_mapping_get_artifact_diagnostics(tmp_path: Path) -> None:
    input_json = tmp_path / "invalid-rows.json"
    input_json.write_text('[{"sale_price":"1234원","source":"emart"}]', encoding="utf-8")

    artifact = harness.run_harness(_args(tmp_path, input_json=input_json, max_items=1))

    assert artifact["source"]["selected_item_count"] == 1
    assert artifact["source"]["records_count"] == 1
    assert artifact["source"]["invalid_rows"] == []
    assert artifact["source"]["retention_anomalies"][0]["bucket"] == "missing_product_name_title"
    assert "crawler_rows_retained_with_anomalies" in artifact["source"]["alerts"]
    assert artifact["quality_batch_validation"]["input_retention_valid"] is True

def test_quality_batch_validation_summary_reports_bounded_partial_anomalies_without_db_submit(tmp_path: Path) -> None:
    input_json = tmp_path / "quality-batch.json"
    input_json.write_text(
        """[
          {"name":"카테고리 변경 두부 300g","sale_price":1980,"source":"emart","source_url":"https://emart.example/1","image_url":"https://emart.example/1.jpg","category_id":"processed.tofu.firm","keywords":["두부"]},
          {"name":"단위 확인 우유 900ml","sale_price":2980,"source":"emart","source_url":"https://emart.example/2","image_url":"https://emart.example/2.jpg","keywords":["우유"]},
          {"name":"이미지 없는 핫딜 라면 5입","sale_price":3980,"original_price":4980,"discount_percent":20,"source":"emart","source_url":"https://emart.example/3","keywords":["라면"]},
          {"name":"정상 사과 1kg","sale_price":5980,"source":"emart","source_url":"https://emart.example/4","image_url":"https://emart.example/4.jpg","keywords":["사과"]},
          {"name":"정상 새우 300g","sale_price":7980,"source":"emart","source_url":"https://emart.example/5","image_url":"https://emart.example/5.jpg","keywords":["새우"]},
          {"name":"범위 밖 예비 행","sale_price":999,"source":"emart","source_url":"https://emart.example/6"}
        ]""",
        encoding="utf-8",
    )
    raw_ids: list[str] = []

    def fake_http(method: str, url: str, *, body=None, **_kwargs):
        nonlocal raw_ids
        if method == "POST" and url.endswith("/api/ingest/raw-records/label"):
            raw_ids = [record["raw_record_id"] for record in body["records"]]
            return {
                "status": "partial_review_required",
                "raw_batch_id": "batch-quality",
                "provider_mode": "stub",
                "provider_calls": 3,
                "ai_batches": 1,
                "missing_label_count": 1,
                "missing_label_raw_record_ids": [raw_ids[-1]],
                "proposals_stored": 8,
                "keyword_proposals_stored": 2,
                "proposal_ids": [],
            }
        if method == "GET" and "/api/review/audit?" in url:
            return {
                "issues": [
                    {"raw_record_id": raw_ids[0], "code": "unknown_taxonomy_category"},
                    {"raw_record_id": raw_ids[2], "code": "price_mismatch_raw"},
                ]
            }
        if method == "GET" and "/api/review/publish-eligibility?" in url:
            return {
                "items": [
                    {
                        "raw_record_id": raw_ids[0],
                        "eligible": False,
                        "publication_kind": "price_observation",
                        "item": {
                            "name": "카테고리 변경 두부 300g",
                            "sale_price": 1980,
                            "source_url": "https://emart.example/1",
                            "image_url": "https://emart.example/1.jpg",
                            "category_id": "unknown.category",
                            "keywords": [],
                            "publication_kind": "price_observation",
                        },
                        "blockers": ["data_quality: category requires review"],
                    },
                    {
                        "raw_record_id": raw_ids[1],
                        "eligible": False,
                        "publication_kind": "price_observation",
                        "item": {
                            "name": "단위 확인 우유 900ml",
                            "sale_price": 2980,
                            "source_url": "https://emart.example/2",
                            "image_url": "https://emart.example/2.jpg",
                            "category_id": "dairy.milk",
                            "keywords": ["우유"],
                            "publication_kind": "price_observation",
                        },
                        "blockers": ["data_quality: missing DB-admin package field standard_unit"],
                    },
                    {
                        "raw_record_id": raw_ids[2],
                        "eligible": True,
                        "publication_kind": "hotdeal",
                        "item": {
                            "name": "이미지 없는 핫딜 라면 5입",
                            "sale_price": 3990,
                            "source_url": "https://emart.example/3",
                            "category_id": "noodle.ramen",
                            "keywords": ["라면"],
                            "publication_kind": "hotdeal",
                        },
                        "blockers": [],
                    },
                    *[
                        {
                            "raw_record_id": raw_id,
                            "eligible": True,
                            "publication_kind": "price_observation",
                            "item": {
                                "name": f"정상 {index}",
                                "sale_price": 5980 + index,
                                "source_url": f"https://emart.example/{index}",
                                "image_url": f"https://emart.example/{index}.jpg",
                                "category_id": "fresh.normal",
                                "keywords": ["정상"],
                                "publication_kind": "price_observation",
                            },
                            "blockers": [],
                        }
                        for index, raw_id in enumerate(raw_ids[3:], start=4)
                    ],
                ]
            }
        if method == "POST" and url.endswith("/api/review/publish-approved"):
            raise AssertionError("DB-admin submit must remain disabled by default")
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    artifact = harness.run_harness(
        _args(
            tmp_path,
            input_json=input_json,
            allow_live_provider=True,
            provider_id="stubbed-provider",
            provider_model="stub-model",
            validation_mode="stub",
            max_items=5,
            max_provider_calls=2,
        ),
        http_json=fake_http,
    )

    summary = artifact["quality_batch_validation"]
    assert summary["purpose"] == "bounded_quality_repetition_not_full_all_source_one_shot"
    assert summary["mode"] == "stub"
    assert summary["db_admin_submit_allowed"] is False
    assert summary["input_count"] == 6
    assert summary["selected_count"] == 5
    assert summary["retained_count"] == 5
    assert summary["provider"]["call_attempts"] == 3
    assert summary["provider"]["ai_batches"] == 1
    assert summary["missing_label_retry"]["partial_review_required"] is True
    assert summary["missing_label_retry"]["missing_label_raw_record_ids"] == [raw_ids[-1]]
    assert summary["anomaly_counts"]["category"] >= 1
    assert summary["anomaly_counts"]["keyword"] >= 1
    assert summary["anomaly_counts"]["unit"] >= 1
    assert summary["anomaly_counts"]["package"] >= 1
    assert summary["anomaly_counts"]["price"] >= 1
    assert summary["anomaly_counts"]["image"] >= 1
    assert summary["anomaly_counts"]["source_owned_overwrite_risk"] >= 1
    gate = summary["quality_gate"]
    assert gate["accepted"] is False
    assert gate["sample_only"] is True
    assert gate["claim_scope"] == "bounded_sample"
    assert any("Only 5 of 6 input rows" in blocker for blocker in gate["blockers"])
    assert not any("retention accounting" in blocker for blocker in gate["blockers"])
    by_id = {row["raw_record_id"]: row for row in summary["per_row_anomalies"]}
    assert "category_changed_raw_vs_final" in by_id[raw_ids[0]]["category"]
    assert "missing_final_keywords" in by_id[raw_ids[0]]["keyword"]
    assert any("standard_unit" in item for item in by_id[raw_ids[1]]["unit"])
    assert "price_changed_raw_vs_final" in by_id[raw_ids[2]]["price"]
    assert "source_owned_sale_price_changed_raw_vs_final" in by_id[raw_ids[2]]["source_owned_overwrite_risk"]
    assert "missing_hotdeal_final_image_url" in by_id[raw_ids[2]]["image"]
    retry = summary["reviewer_retry_candidates"]
    assert retry["source"] == "deterministic_quality_batch_validation_no_live_reviewer_ai"
    assert retry["candidate_count"] >= 3
    groups = {group["missing_field"]: group for group in retry["groups"]}
    assert groups["missing_label"]["prompt_category"] == "full_record_label_retry"
    assert groups["missing_label"]["raw_record_ids"] == [raw_ids[-1]]
    assert groups["category"]["prompt_category"] == "taxonomy_classification_retry"
    assert raw_ids[0] in groups["category"]["raw_record_ids"]
    assert groups["package"]["prompt_category"] == "package_quantity_unit_retry"
    assert raw_ids[1] in groups["package"]["raw_record_ids"]
    assert groups["price"]["prompt_category"] == "price_evidence_retry"
    assert raw_ids[2] in groups["price"]["raw_record_ids"]
    assert "human_admin_fallback" in retry
