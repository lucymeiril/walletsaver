from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ORCHESTRATOR_PATH = REPO_ROOT / "tools" / "one_shot_db_build_orchestrator.py"
spec = importlib.util.spec_from_file_location("one_shot_db_build_orchestrator", ORCHESTRATOR_PATH)
assert spec and spec.loader
orchestrator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator)

def _args(tmp_path: Path, **overrides) -> Namespace:
    defaults = {
        "artifact_dir": tmp_path,
        "allow_live_crawler": False,
        "crawler_batch_json": None,
        "allow_live_ai_provider": False,
        "allow_live_ai_labeling": False,
        "provider_id": None,
        "provider_model": "gemini-3.1-flash-lite-preview",
        "provider_pool": None,
        "max_pool_attempts": None,
        "provider_secret_alias": "GOOGLE_API_KEY",
        "provider_key_alias": None,
        "ai_admin_url": "http://127.0.0.1:8003",
        "ai_admin_api_key_alias": None,
        "live_batch_artifact_dir": None,
        "live_batch_max_items": 2,
        "live_batch_max_provider_calls": 1,
        "live_batch_ai_batch_size": 20,
        "live_batch_ai_batch_prompt_chars": 8000,
        "live_batch_label_chunk_retries": 1,
        "live_batch_label_call_min_interval_seconds": 12.0,
        "retain_all_crawler_input": False,
        "allow_db_mutation": False,
        "db_admin_url": None,
        "db_admin_api_key": None,
        "db_admin_env_file": [],
        "allow_live_website": False,
        "website_url": None,
    }
    defaults.update(overrides)
    return Namespace(**defaults)

def _ready_db_mutation_preflight() -> dict:
    return {
        "status": "ready",
        "ready_to_mutate": True,
        "readiness": {"status": "ready", "key_present": True, "url": "https://admin.example.local/"},
        "current_state": {"total_pending": 0},
        "snapshot": {
            "verified": True,
            "latest_backup": "walletguardian_manual_20260101_000000.db",
            "rollback_path": "restore verified backup",
        },
        "error": None,
    }

def test_default_one_shot_dry_run_writes_success_artifact_without_live_side_effects(tmp_path: Path) -> None:
    artifact = orchestrator.run_orchestrator(_args(tmp_path))

    assert artifact["overall_status"] == "success"
    assert artifact["result_scope"] == "fixture_stub_dry_run"
    assert artifact["live_integrations_invoked"] == {
        "crawler": False,
        "crawler_batch_artifact": False,
        "ai_provider_smoke": False,
        "ai_labeling": False,
        "db_mutation": False,
        "website_verification": False,
    }
    assert artifact["manual_safe_defaults"] == {
        "consumes_ai_quota_by_default": False,
        "mutates_real_db_by_default": False,
        "live_requires_explicit_flags": True,
    }
    assert "fixture/stub/dry-run by default" in artifact["command_shape"]
    assert "--allow-live-ai-labeling" in artifact["command_shape"]
    assert "tools\\run_live_model_batch.py" in artifact["command_shape"]
    modes = {phase["name"]: phase["mode"] for phase in artifact["phases"]}
    assert modes == {
        "crawler-admin diagnostics/source evidence": "fixture",
        "ai-admin API label/classify": "stub",
        "DB-admin ingestion submit and ai-safe-final-approve": "fixture",
        "website/public verification of persisted product/offer/history shape": "fixture",
    }
    ai_phase = artifact["phases"][1]
    assert ai_phase["counts"]["provider_calls"] == 0
    assert ai_phase["details"]["classification_scope"] == "stub_dry_run"
    assert ai_phase["details"]["real_labeling_invoked"] is False
    db_phase = artifact["phases"][2]
    assert db_phase["counts"]["mutated_real_db"] == 0
    assert artifact["public_shape"]["shape_ok"] is True
    assert artifact["public_shape"]["product"]["category_id"] == "processed.tofu.firm"
    assert artifact["public_shape"]["offer"]["source_url"] == "https://emart.example/products/tofu-300g"
    assert artifact["public_shape"]["offer"]["original_price"] is None
    assert artifact["public_shape"]["offer"]["discount_rate"] is None
    assert artifact["public_shape"]["history"][0]["price"] == 1980
    assert artifact["retention"] == {
        "source_raw_count": 1,
        "review_candidate_count": 1,
        "retained_count": 1,
        "dropped_count": 0,
        "retain_all": True,
    }

    artifact_path = Path(artifact["artifact_path"])
    assert artifact_path.is_file()
    serialized = artifact_path.read_text(encoding="utf-8")
    assert "AIza" not in serialized
    assert "super-secret" not in serialized
    persisted = json.loads(serialized)
    assert persisted["overall_status"] == "success"
    assert persisted["result_scope"] == "fixture_stub_dry_run"

def test_one_shot_stub_batch_retention_keeps_all_fixture_items(tmp_path: Path, monkeypatch) -> None:
    batch_items = [
        {
            "product_id": f"one-shot-fixture-{index}",
            "name": f"원천명 국산콩 두부 300g {index}",
            "sale_price": 1980 + index,
            "source": "emart-fixture",
            "source_url": f"https://emart.example/products/tofu-300g-{index}",
            "image_url": f"https://emart.example/images/tofu-300g-{index}.jpg",
            "category_hint": "두부/콩나물",
        }
        for index in range(4)
    ]
    monkeypatch.setattr(orchestrator, "_fixture_source_items", lambda: batch_items)

    artifact = orchestrator.run_orchestrator(_args(tmp_path))

    assert artifact["overall_status"] == "success"
    assert artifact["phases"][0]["counts"]["source_raw"] == 4
    assert artifact["phases"][1]["counts"]["candidate_items"] == 4
    assert artifact["phases"][2]["counts"]["approved"] == 4
    assert artifact["phases"][3]["counts"]["products"] == 4
    assert artifact["public_shape"]["retained_shape_count"] == 4
    assert artifact["public_shape"]["all_shapes_ok"] is True
    assert artifact["retention"] == {
        "source_raw_count": 4,
        "review_candidate_count": 4,
        "retained_count": 4,
        "dropped_count": 0,
        "retain_all": True,
    }

def test_redaction_preserves_readiness_metadata_but_hides_secret_fields() -> None:
    redacted = orchestrator._safe_json(
        {
            "key_present": True,
            "key_missing": False,
            "env_path_with_alias": "packages/ai-admin/backend/.env",
            "secret_alias": "GOOGLE_API_KEY",
            "api_key": "super-secret",
            "db_admin_api_key": "another-secret",
            "headers": {"X-API-Key": "header-secret"},
            "message": "GOOGLE_API_KEY=super-secret Authorization header Bearer sk-abc123456 rejected",
        }
    )

    assert redacted["key_present"] is True
    assert redacted["key_missing"] is False
    assert redacted["env_path_with_alias"] == "packages/ai-admin/backend/.env"
    assert redacted["secret_alias"] == "GOOGLE_API_KEY"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["db_admin_api_key"] == "[REDACTED]"
    assert redacted["headers"]["X-API-Key"] == "[REDACTED]"
    assert redacted["message"] == "GOOGLE_API_KEY=[REDACTED] Authorization header Bearer [REDACTED] rejected"
    assert "sk-abc123456" not in str(redacted)

def test_live_provider_and_db_mutation_prerequisites_are_blocked_without_side_effects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("DB_ADMIN_URL", raising=False)

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            allow_live_ai_provider=True,
            provider_id=None,
            provider_secret_alias="WALLETSAVIOR_TEST_MISSING_PROVIDER_KEY",
            allow_db_mutation=True,
            db_admin_url=None,
            db_admin_api_key=None,
        )
    )

    assert artifact["overall_status"] == "blocked"
    ai_phase = artifact["phases"][1]
    db_phase = artifact["phases"][2]
    website_phase = artifact["phases"][3]

    assert ai_phase["mode"] == "live"
    assert ai_phase["status"] == "blocked"
    assert "--provider-id is required with --allow-live-ai-provider" in ai_phase["blockers"]
    assert ai_phase["details"]["aistudio_readiness"]["key_present"] is False
    assert ai_phase["details"]["aistudio_readiness"]["live_call_attempted"] is False

    assert db_phase["mode"] == "live"
    assert db_phase["status"] == "blocked"
    assert "DB_ADMIN_URL or --db-admin-url is required with --allow-db-mutation" in db_phase["blockers"]
    assert "DB_ADMIN_API_KEY or --db-admin-api-key is required with --allow-db-mutation" in db_phase["blockers"]
    assert "No AI-reviewed candidate item is available for DB-admin submit" in db_phase["blockers"]

    assert website_phase["mode"] == "skipped"
    assert website_phase["status"] == "skipped"
    assert artifact["counts"]["blocked"] == 2
    assert Path(artifact["artifact_path"]).is_file()

def test_live_ai_readiness_passed_blocks_without_stub_live_candidate(tmp_path: Path, monkeypatch) -> None:
    readiness = {
        "status": "PASSED",
        "live_call_attempted": True,
        "live_call_succeeded": True,
        "key_present": True,
    }

    monkeypatch.setattr(
        orchestrator._AISTUDIO_SMOKE,
        "run_aistudio_live_smoke",
        lambda **_kwargs: readiness,
    )

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            allow_live_ai_provider=True,
            provider_id="google-aistudio-live-smoke",
        )
    )

    assert artifact["overall_status"] == "blocked"
    assert artifact["result_scope"] == "mixed_explicit_live_opt_in_with_unimplemented_or_blocked_steps"
    assert artifact["live_integrations_invoked"]["ai_provider_smoke"] is True
    assert artifact["live_integrations_invoked"]["ai_labeling"] is False

    ai_phase = artifact["phases"][1]
    assert ai_phase["mode"] == "live"
    assert ai_phase["status"] == "blocked"
    assert ai_phase["counts"] == {"candidate_items": 0, "provider_calls": 0}
    assert orchestrator.REAL_AI_LABELING_BLOCKER in ai_phase["blockers"]
    assert ai_phase["details"]["real_labeling_invoked"] is False
    assert ai_phase["details"]["stub_candidate_created"] is False

    db_phase = artifact["phases"][2]
    assert db_phase["status"] == "skipped"
    assert "No candidate item available." in db_phase["blockers"]

def test_live_website_with_url_is_skipped_not_live_verified(tmp_path: Path) -> None:
    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            allow_live_website=True,
            website_url="https://walletsavior.example",
        )
    )

    website_phase = artifact["phases"][3]
    assert website_phase["mode"] == "live"
    assert website_phase["status"] == "skipped"
    assert website_phase["details"]["website_url_present"] is True
    assert website_phase["details"]["live_website_verification_invoked"] is False
    assert website_phase["details"]["verification_scope"] == "not_implemented_not_live_verified"
    assert any("not implemented/invoked" in warning for warning in website_phase["warnings"])

def test_crawler_batch_artifact_without_live_labeling_blocks_instead_of_stub_success(tmp_path: Path) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text(
        '[{"name":"실제 크롤러 두부 300g","sale_price":1980,"source":"emart","source_url":"https://emart.example/live-tofu"}]',
        encoding="utf-8",
    )

    artifact = orchestrator.run_orchestrator(_args(tmp_path, crawler_batch_json=crawler_batch))

    assert artifact["overall_status"] == "blocked"
    assert artifact["result_scope"] == "mixed_explicit_live_opt_in_with_unimplemented_or_blocked_steps"
    assert artifact["live_integrations_invoked"]["crawler_batch_artifact"] is True
    assert artifact["live_integrations_invoked"]["ai_labeling"] is False
    assert artifact["phases"][0]["mode"] == "artifact"
    ai_phase = artifact["phases"][1]
    assert ai_phase["status"] == "blocked"
    assert "no stub success is produced for crawler artifacts" in ai_phase["blockers"][0]
    assert artifact["retention"]["review_candidate_count"] == 0

def test_crawler_batch_artifact_accepts_multi_source_shape_for_preflight(tmp_path: Path) -> None:
    crawler_batch = tmp_path / "multi-source-crawler-batch.json"
    crawler_batch.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_name": "emart",
                        "crawler_name": "emart_discount",
                        "schema_type": "mart_discount",
                        "items": [
                            {
                                "product_id": "emart-tofu",
                                "name": "풀무원 국산콩 두부 300g",
                                "sale_price": "2,980원",
                            }
                        ],
                    },
                    {
                        "source_name": "naver-store",
                        "crawler_name": "marketplace_fixture",
                        "schema_type": "shopping_product",
                        "records": [
                            {
                                "external_id": "naver-tangerine",
                                "product_name": "제주 감귤 선물세트 3kg",
                                "current_price": 19900,
                            }
                        ],
                    },
                    {
                        "source_name": "community-hotdeal",
                        "crawler_name": "community_hotdeal_fixture",
                        "schema_type": "hotdeal",
                        "raw_items": [
                            {
                                "post_id": "hotdeal-ramen",
                                "title": "라면 멀티팩 5입 특가",
                                "price": "3,980원",
                            }
                        ],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = orchestrator._load_json_items(crawler_batch)
    artifact = orchestrator.run_orchestrator(
        _args(tmp_path, crawler_batch_json=crawler_batch, retain_all_crawler_input=True)
    )

    assert len(rows) == 3
    assert {row["source_name"] for row in rows} == {"emart", "naver-store", "community-hotdeal"}
    assert rows[1]["crawler_name"] == "marketplace_fixture"
    assert rows[2]["schema_type"] == "hotdeal"
    crawler_phase = artifact["phases"][0]
    assert crawler_phase["counts"]["source_raw"] == 3
    assert crawler_phase["counts"]["readable_rows_intended_for_live_batch"] == 3
    assert crawler_phase["details"]["bounded_by_live_batch_max_items"] is False

def test_live_labeling_requires_provider_opt_in_and_provider_choice(tmp_path: Path) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text('[{"name":"두부","sale_price":1980,"source":"emart"}]', encoding="utf-8")

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_labeling=True,
        )
    )

    ai_phase = artifact["phases"][1]
    assert artifact["overall_status"] == "blocked"
    assert ai_phase["details"]["live_batch_invoked"] is False
    assert "--allow-live-ai-labeling requires --allow-live-ai-provider" in ai_phase["blockers"]
    assert "--provider-id or --provider-pool is required for live AI labeling" in ai_phase["blockers"]

def test_live_batch_command_requires_db_mutation_flag_to_forward_submit(tmp_path: Path) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text('[{"name":"두부","sale_price":1980,"source":"emart"}]', encoding="utf-8")

    default_command = orchestrator.build_live_batch_command(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
        )
    )
    mutation_command = orchestrator.build_live_batch_command(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
            allow_db_mutation=True,
        )
    )

    assert "--allow-db-admin-submit" not in default_command
    assert "--allow-db-admin-submit" in mutation_command

def test_retain_all_crawler_input_forwards_flag_and_default_remains_bounded(tmp_path: Path) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text(
        json.dumps(
            [
                {"name": f"두부 {index}", "sale_price": 1980 + index, "source": "emart"}
                for index in range(4)
            ]
        ),
        encoding="utf-8",
    )

    default_args = _args(
        tmp_path,
        crawler_batch_json=crawler_batch,
        allow_live_ai_provider=True,
        allow_live_ai_labeling=True,
        provider_id="google-live",
        live_batch_max_items=2,
    )
    retain_args = _args(
        tmp_path,
        crawler_batch_json=crawler_batch,
        allow_live_ai_provider=True,
        allow_live_ai_labeling=True,
        provider_id="google-live",
        live_batch_max_items=2,
        retain_all_crawler_input=True,
    )

    default_command = orchestrator.build_live_batch_command(default_args)
    retain_command = orchestrator.build_live_batch_command(retain_args)

    assert default_command[default_command.index("--max-items") + 1] == "2"
    assert "--retain-all-input" not in default_command
    assert retain_command[retain_command.index("--max-items") + 1] == "2"
    assert "--retain-all-input" in retain_command

    bounded_artifact = orchestrator.run_orchestrator(_args(tmp_path, crawler_batch_json=crawler_batch))
    bounded_phase = bounded_artifact["phases"][0]
    assert bounded_phase["counts"]["selected_for_live_batch_max"] == 2
    assert bounded_phase["counts"]["readable_rows_intended_for_live_batch"] == 2
    assert bounded_phase["details"]["bounded_by_live_batch_max_items"] is True

    captured_commands: list[list[str]] = []

    def runner(command):
        captured_commands.append(command)
        stdout = json.dumps(
            {
                "status": "success",
                "harness_summary": {
                    "validation_run": {
                        "live_call_attempted": True,
                        "live_call_succeeded": True,
                        "item_counts": {"records": 4},
                    },
                    "provider_response_summary": {"called": True, "provider_calls": 1},
                    "db_admin_submit_result": {"skipped": True},
                },
            }
        )
        return orchestrator.subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    retain_artifact = orchestrator.run_orchestrator(retain_args, live_batch_runner=runner)
    retain_phase = retain_artifact["phases"][0]
    ai_phase = retain_artifact["phases"][1]
    assert "--retain-all-input" in captured_commands[0]
    assert "--retain-all-input" in ai_phase["details"]["command_shape"]
    assert retain_phase["counts"]["selected_for_live_batch_max"] == 2
    assert retain_phase["counts"]["readable_rows_intended_for_live_batch"] == 4
    assert retain_phase["details"]["bounded_by_live_batch_max_items"] is False
    assert ai_phase["counts"]["candidate_items"] == 4
    assert ai_phase["counts"]["readable_rows_intended_for_live_batch"] == 4
    assert ai_phase["details"]["retain_all_crawler_input_forwarded"] is True

def test_live_labeling_invokes_bounded_wrapper_and_forwards_db_submit_only_with_mutation_flag(tmp_path: Path, monkeypatch) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text('[{"name":"두부","sale_price":1980,"source":"emart"}]', encoding="utf-8")
    captured_commands: list[list[str]] = []
    monkeypatch.setattr(
        orchestrator,
        "_run_db_mutation_preflight",
        lambda _args: _ready_db_mutation_preflight(),
    )

    def runner(command):
        captured_commands.append(command)
        stdout = json.dumps(
            {
                "status": "success",
                "db_admin_submit_allowed": True,
                "harness_summary": {
                    "validation_run": {
                        "live_call_attempted": True,
                        "live_call_succeeded": True,
                        "item_counts": {"records": 1},
                    },
                    "provider_response_summary": {"called": True, "provider_calls": 1},
                    "db_admin_submit_result": {
                        "published": 1,
                        "submitted_to_db_admin": 1,
                        "pending_db_review": 0,
                        "ai_safe_final_approved": 1,
                        "public_db_verified": 1,
                        "rollback_re_review_supported": 1,
                        "operator_next_action": "rollback or re-review if audit fails",
                        "final_approve_failed": 0,
                        "failed": 0,
                        "results": [
                            {
                                "raw_record_id": "tofu",
                                "status": "published",
                                "ai_safe_final_approve": {
                                    "status": "approved",
                                    "saved": 1,
                                    "public_db_verification": {"verified": True, "verified_count": 1, "expected_count": 1},
                                    "rollback_supported": True,
                                    "re_review_supported": True,
                                },
                            }
                        ],
                    },
                },
            }
        )
        return orchestrator.subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
            provider_model="gemini-live",
            provider_key_alias="GOOGLE_API_KEY",
            ai_admin_api_key_alias="AI_ADMIN_API_KEY",
            allow_db_mutation=True,
        ),
        live_batch_runner=runner,
    )

    command = captured_commands[0]
    assert artifact["overall_status"] == "success"
    assert "--allow-db-admin-submit" in command
    assert command[command.index("--input-json") + 1] == str(crawler_batch)
    assert command[command.index("--max-provider-calls") + 1] == "1"
    assert command[command.index("--ai-batch-size") + 1] == "20"
    assert command[command.index("--ai-batch-prompt-chars") + 1] == "8000"
    assert command[command.index("--label-chunk-retries") + 1] == "1"
    assert command[command.index("--label-call-min-interval-seconds") + 1] == "12.0"
    assert artifact["live_integrations_invoked"]["ai_labeling"] is True
    assert artifact["live_integrations_invoked"]["db_mutation"] is True
    ai_phase = artifact["phases"][1]
    db_phase = artifact["phases"][2]
    assert ai_phase["details"]["db_admin_submit_forwarded"] is True
    assert db_phase["mode"] == "live"
    assert db_phase["details"]["db_admin_submit_result"]["ai_safe_final_approved"] == 1
    assert db_phase["details"]["db_admin_submit_safety"]["safe_final_approval_confirmed"] is True
    assert db_phase["details"]["db_admin_mutation_preflight"]["ready_to_mutate"] is True
    assert artifact["live_integrations_invoked"]["website_verification"] is False

def test_live_labeling_db_mutation_fails_closed_when_preflight_blocks(tmp_path: Path, monkeypatch) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text('[{"name":"두부","sale_price":1980,"source":"emart"}]', encoding="utf-8")

    def runner(_command):
        raise AssertionError("live batch must not run when DB mutation preflight fails")

    monkeypatch.setattr(
        orchestrator,
        "_run_db_mutation_preflight",
        lambda _args: {
            "status": "blocked",
            "ready_to_mutate": False,
            "readiness": {"status": "server_unreachable", "key_present": True},
            "current_state": None,
            "snapshot": {"verified": False, "rollback_path": "restore verified backup"},
            "error": {"class": "ReadinessBlocked", "message": "server_unreachable"},
        },
    )

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
            allow_db_mutation=True,
        ),
        live_batch_runner=runner,
    )

    ai_phase = artifact["phases"][1]
    db_phase = artifact["phases"][2]
    assert artifact["overall_status"] == "blocked"
    assert ai_phase["details"]["db_admin_submit_forwarded"] is False
    assert "DB-admin mutation preflight failed" in ai_phase["blockers"][0]
    assert db_phase["details"]["db_admin_mutation_preflight"]["ready_to_mutate"] is False
    assert artifact["live_integrations_invoked"]["db_mutation"] is False

def test_live_labeling_blocks_submit_only_result_without_final_approve_proof(tmp_path: Path, monkeypatch) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text('[{"name":"두부","sale_price":1980,"source":"emart"}]', encoding="utf-8")
    monkeypatch.setattr(
        orchestrator,
        "_run_db_mutation_preflight",
        lambda _args: _ready_db_mutation_preflight(),
    )

    def runner(command):
        stdout = json.dumps(
            {
                "status": "success",
                "harness_summary": {
                    "validation_run": {
                        "live_call_attempted": True,
                        "live_call_succeeded": True,
                        "item_counts": {"records": 1},
                    },
                    "provider_response_summary": {"called": True, "provider_calls": 1},
                    "db_admin_submit_result": {"published_count": 1},
                },
            }
        )
        return orchestrator.subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
            allow_db_mutation=True,
        ),
        live_batch_runner=runner,
    )

    db_phase = artifact["phases"][2]
    assert artifact["overall_status"] == "blocked"
    assert artifact["live_integrations_invoked"]["db_mutation"] is False
    assert db_phase["status"] == "blocked"
    assert db_phase["counts"]["mutated_real_db"] == 0
    assert db_phase["details"]["db_admin_submit_safety"]["safe_final_approval_confirmed"] is False
    assert "ai_safe_final_approved" in db_phase["blockers"][0]

def test_live_labeling_keeps_partial_final_approve_failures_blocked_and_audited(tmp_path: Path, monkeypatch) -> None:
    crawler_batch = tmp_path / "crawler-batch.json"
    crawler_batch.write_text(
        json.dumps(
            [
                {"name": "두부", "sale_price": 1980, "source": "emart"},
                {"name": "이미지 없는 두부", "sale_price": 1980, "source": "emart"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "_run_db_mutation_preflight",
        lambda _args: _ready_db_mutation_preflight(),
    )

    def runner(command):
        stdout = json.dumps(
            {
                "status": "success",
                "harness_summary": {
                    "validation_run": {
                        "live_call_attempted": True,
                        "live_call_succeeded": True,
                        "item_counts": {"records": 2},
                    },
                    "provider_response_summary": {"called": True, "provider_calls": 1},
                    "db_admin_submit_result": {
                        "published": 1,
                        "submitted_to_db_admin": 2,
                        "pending_db_review": 1,
                        "ai_safe_final_approved": 1,
                        "final_approve_failed": 1,
                        "failed": 1,
                        "results": [
                            {"raw_record_id": "ok", "status": "published", "ai_safe_final_approve": {"status": "approved"}},
                            {
                                "raw_record_id": "blocked",
                                "status": "pending_db_review",
                                "final_approve_error": "missing image_url",
                                "requires_db_admin_review": True,
                            },
                        ],
                    },
                },
            }
        )
        return orchestrator.subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    artifact = orchestrator.run_orchestrator(
        _args(
            tmp_path,
            crawler_batch_json=crawler_batch,
            allow_live_ai_provider=True,
            allow_live_ai_labeling=True,
            provider_id="google-live",
            allow_db_mutation=True,
            retain_all_crawler_input=True,
        ),
        live_batch_runner=runner,
    )

    db_phase = artifact["phases"][2]
    safety = db_phase["details"]["db_admin_submit_safety"]
    assert artifact["overall_status"] == "blocked"
    assert artifact["live_integrations_invoked"]["db_mutation"] is False
    assert db_phase["status"] == "blocked"
    assert db_phase["counts"]["ai_safe_final_approved"] == 1
    assert db_phase["counts"]["pending_db_review"] == 1
    assert db_phase["counts"]["final_approve_failed"] == 1
    assert safety["blocked_rows_held_for_review"] is True
    assert safety["blocked_rows_audited"] is True
    assert any("pending/failed" in blocker for blocker in db_phase["blockers"])
