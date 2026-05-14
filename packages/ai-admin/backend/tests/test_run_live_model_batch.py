from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
WRAPPER_PATH = REPO_ROOT / "tools" / "run_live_model_batch.py"
spec = importlib.util.spec_from_file_location("run_live_model_batch", WRAPPER_PATH)
assert spec and spec.loader
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def _parse(argv: list[str] | None = None):
    return wrapper.build_arg_parser().parse_args(argv or [])


def test_defaults_build_minimal_live_fixture_command_without_db_admin_submit() -> None:
    args = _parse()

    command = wrapper.build_harness_command(args)

    assert "--allow-live-provider" in command
    assert command[command.index("--provider-id") + 1] == "google-gemini31-live-matrix"
    assert command[command.index("--provider-model") + 1] == "gemini-3.1-flash-lite-preview"
    assert command[command.index("--max-items") + 1] == "2"
    assert command[command.index("--max-provider-calls") + 1] == "1"
    assert command[command.index("--ai-batch-size") + 1] == "20"
    assert command[command.index("--ai-batch-prompt-chars") + 1] == "8000"
    assert command[command.index("--max-live-items-cap") + 1] == "300"
    assert command[command.index("--label-timeout-seconds") + 1] == "240.0"
    assert "--input-json" not in command
    assert "--allow-db-admin-submit" not in command


def test_retain_all_input_flag_is_forwarded_to_harness(tmp_path: Path) -> None:
    input_json = tmp_path / "crawler-artifact.json"
    input_json.write_text('{"sources":[{"source_name":"emart","items":[{"name":"두부"}]}]}', encoding="utf-8")
    args = _parse(["--input-json", str(input_json), "--retain-all-input"])

    command = wrapper.build_harness_command(args)

    assert "--input-json" in command
    assert command[command.index("--input-json") + 1] == str(input_json)
    assert "--retain-all-input" in command


def test_large_live_batch_flags_are_forwarded_to_harness() -> None:
    args = _parse(["--allow-large-live-batch", "--max-live-items-cap", "395", "--max-items", "395"])

    command = wrapper.build_harness_command(args)

    assert "--allow-large-live-batch" in command
    assert command[command.index("--max-live-items-cap") + 1] == "395"
    assert command[command.index("--max-items") + 1] == "395"


def test_preflight_blocks_395_rows_without_large_batch_opt_in(
    tmp_path: Path,
    capsys,
) -> None:
    input_json = tmp_path / "three-hundred-ninety-five-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"이마트 기본 제한 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(395)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checked_readiness = False

    def readiness(*_args, **_kwargs):
        nonlocal checked_readiness
        checked_readiness = True
        return True, "ready"

    exit_code = wrapper.main(
        [
            "--input-json",
            str(input_json),
            "--retain-all-input",
            "--max-items",
            "395",
            "--max-provider-calls",
            "60",
        ],
        readiness_checker=readiness,
    )

    assert exit_code == 2
    assert checked_readiness is False
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert "--max-items must be between 1 and 300" in output["reason"]


def test_explicit_395_large_batch_opt_in_reaches_mocked_runner_without_db_submit(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    input_json = tmp_path / "three-hundred-ninety-five-opt-in-rows.json"
    input_json.write_text("[]", encoding="utf-8")
    captured_command: list[str] = []

    def twenty_two_batches(_args):
        return 22

    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        captured_command.extend(command)
        stdout = json.dumps({"artifact_path": "artifact.json", "provider_called": True})
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", twenty_two_batches)

    exit_code = wrapper.main(
        [
            "--input-json",
            str(input_json),
            "--retain-all-input",
            "--max-items",
            "395",
            "--max-provider-calls",
            "60",
            "--allow-large-live-batch",
            "--max-live-items-cap",
            "395",
        ],
        readiness_checker=ready,
        runner=runner,
    )

    assert exit_code == 0
    assert "--allow-large-live-batch" in captured_command
    assert captured_command[captured_command.index("--max-live-items-cap") + 1] == "395"
    assert captured_command[captured_command.index("--max-items") + 1] == "395"
    assert "--allow-db-admin-submit" not in captured_command
    output = json.loads(capsys.readouterr().out)
    assert output["estimated_provider_calls"] == 22
    assert output["db_admin_submit_allowed"] is False


def test_label_timeout_option_is_capped_forwarded_and_reported(capsys, monkeypatch) -> None:
    captured_command: list[str] = []

    def one_batch(_args):
        return 1

    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        captured_command.extend(command)
        stdout = json.dumps({"artifact_path": "artifact.json", "provider_called": True})
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", one_batch)

    exit_code = wrapper.main(
        ["--label-timeout-seconds", str(wrapper.MAX_LABEL_TIMEOUT_SECONDS + 123)],
        readiness_checker=ready,
        runner=runner,
    )

    assert exit_code == 0
    assert captured_command[captured_command.index("--label-timeout-seconds") + 1] == str(wrapper.MAX_LABEL_TIMEOUT_SECONDS)
    assert captured_command[captured_command.index("--label-chunk-retries") + 1] == str(wrapper.DEFAULT_LABEL_CHUNK_RETRIES)
    assert (
        captured_command[captured_command.index("--label-call-min-interval-seconds") + 1]
        == str(wrapper.DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS)
    )
    output = json.loads(capsys.readouterr().out)
    assert output["label_timeout_seconds"] == wrapper.MAX_LABEL_TIMEOUT_SECONDS
    assert output["label_timeout_seconds_requested"] == wrapper.MAX_LABEL_TIMEOUT_SECONDS + 123
    assert output["label_timeout_seconds_cap"] == wrapper.MAX_LABEL_TIMEOUT_SECONDS
    assert output["label_chunk_retries"] == wrapper.DEFAULT_LABEL_CHUNK_RETRIES
    assert output["label_call_min_interval_seconds"] == wrapper.DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS


def test_run_command_forces_utf8_child_env_and_decoding(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout='{"name":"두부"}', stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    result = wrapper.run_command(["py", "tools\\live_validation_harness_v2.py"])

    assert result.stdout == '{"name":"두부"}'
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_preflight_provider_calls_follow_operator_ai_batch_prompt_budget(tmp_path: Path) -> None:
    input_json = tmp_path / "six-retained-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {
                    "name": f"프롬프트 예산 검증용 행사 상품 {index} 300g 대용량 구성",
                    "sale_price": 1000 + index,
                    "original_price": 2000 + index,
                    "discount_percent": 30,
                    "source": "emart",
                    "detail_url": f"https://emart.example/products/{index}?campaign=walletsavior-live-validation-batch-sizing",
                    "image_url": f"https://emart.example/images/{index}.jpg",
                    "category_hint": "가공식품/행사상품",
                }
                for index in range(6)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    small_budget = _parse(
        [
            "--input-json",
            str(input_json),
            "--retain-all-input",
            "--ai-batch-size",
            "20",
            "--ai-batch-prompt-chars",
            "2000",
        ]
    )
    larger_budget = _parse(
        [
            "--input-json",
            str(input_json),
            "--retain-all-input",
            "--ai-batch-size",
            "20",
            "--ai-batch-prompt-chars",
            "8000",
        ]
    )

    assert wrapper.estimate_provider_call_count(small_budget) == 3
    assert wrapper.estimate_provider_call_count(larger_budget) == 1


def test_preflight_bound_still_blocks_when_operator_batch_requires_too_many_calls(
    tmp_path: Path,
    capsys,
) -> None:
    input_json = tmp_path / "six-retained-rows.json"
    input_json.write_text(
        json.dumps(
            [
                {"name": f"배치 제한 상품 {index}", "sale_price": 1000 + index, "source": "emart"}
                for index in range(6)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checked_readiness = False

    def readiness(*_args, **_kwargs):
        nonlocal checked_readiness
        checked_readiness = True
        return True, "ready"

    exit_code = wrapper.main(
        [
            "--input-json",
            str(input_json),
            "--retain-all-input",
            "--ai-batch-size",
            "2",
            "--ai-batch-prompt-chars",
            "8000",
            "--max-provider-calls",
            "2",
        ],
        readiness_checker=readiness,
    )

    assert exit_code == 2
    assert checked_readiness is False
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["estimated_provider_calls"] == 3
    assert output["ai_batch_size"] == 2


def test_parser_guidance_discourages_flash_lite_for_repeated_batches() -> None:
    parser = wrapper.build_arg_parser()
    normalized_help = " ".join(str(parser.epilog).split())

    assert wrapper.DEFAULT_PROVIDER_ID in normalized_help
    assert wrapper.DEFAULT_PROVIDER_MODEL in normalized_help
    assert "not proof of live provider availability" in normalized_help
    assert "Gemma 3/Gemma 4/Gemini 3.1 Flash Lite" in normalized_help
    assert "Timeouts are retryable server slowness" in normalized_help
    assert "NOT_FOUND means that exact model name is not available" in normalized_help
    assert "never loops forever" in normalized_help
    assert "Do not fall back to gemini-2.5-flash-lite" in normalized_help


def test_provider_pool_parser_preserves_gemini31_and_gemma4_choices() -> None:
    args = _parse(
        [
            "--provider-pool",
            "google-gemini31-live-matrix=gemini-3.1-flash-lite-preview,"
            "google-gemma4-live=gemma-4-26b-a4b-it",
        ]
    )

    choices = wrapper.parse_provider_pool(args)

    assert [choice.provider_id for choice in choices] == [
        "google-gemini31-live-matrix",
        "google-gemma4-live",
    ]
    assert [choice.provider_model for choice in choices] == [
        "gemini-3.1-flash-lite-preview",
        "gemma-4-26b-a4b-it",
    ]


def test_failure_classifier_distinguishes_not_found_from_timeout() -> None:
    timeout_summary = {
        "validation_run": {
            "error": {
                "message": "Google server deadline exceeded; request timed out after 90s"
            }
        }
    }
    not_found_summary = {
        "provider_response_summary": {
            "error": {
                "message": "404 NOT_FOUND model gemma-3-27b-it was not found"
            }
        }
    }

    assert wrapper.failure_class_from_summary(timeout_summary) == "retryable_provider_or_quota_failure"
    assert wrapper.failure_class_from_summary(not_found_summary) == "model_not_found_non_retryable"


def test_failure_classifier_treats_local_transport_reset_and_refused_as_retryable() -> None:
    reset_summary = {
        "provider_response_summary": {
            "error": {
                "message": (
                    "POST http://127.0.0.1:8003/api/ingest/raw-records/label failed: "
                    "local transport reset by peer [WinError 10054]"
                )
            }
        }
    }
    refused_summary = {
        "validation_run": {
            "error": {
                "message": (
                    "POST http://127.0.0.1:8003/api/ingest/raw-records/label failed: "
                    "local transport connection refused [WinError 10061]"
                )
            }
        }
    }

    assert wrapper.failure_class_from_summary(reset_summary) == "retryable_provider_or_quota_failure"
    assert wrapper.failure_class_from_summary(refused_summary) == "retryable_provider_or_quota_failure"


def test_provider_pool_preflight_blocks_when_total_bound_exceeds_max(capsys, monkeypatch) -> None:
    checked_readiness = False

    def one_batch(_args):
        return 1

    def readiness(*_args, **_kwargs):
        nonlocal checked_readiness
        checked_readiness = True
        return True, "ready"

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", one_batch)

    exit_code = wrapper.main(
        [
            "--provider-pool",
            "google-gemini31-live-matrix=gemini-3.1-flash-lite-preview,"
            "google-gemma4-live=gemma-4-26b-a4b-it",
            "--max-provider-calls",
            "1",
        ],
        readiness_checker=readiness,
    )

    assert exit_code == 2
    assert checked_readiness is False
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["estimated_total_provider_calls"] == 2
    assert [choice["provider_model"] for choice in output["provider_pool"]] == [
        "gemini-3.1-flash-lite-preview",
        "gemma-4-26b-a4b-it",
    ]


def test_provider_pool_tries_next_choice_after_retryable_timeout_with_spacing(
    capsys,
    monkeypatch,
) -> None:
    captured_commands: list[list[str]] = []
    sleeps: list[float] = []

    def one_batch(_args):
        return 1

    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        captured_commands.append(command)
        if len(captured_commands) == 1:
            stdout = json.dumps(
                {
                    "artifact_path": "artifact.json",
                    "live_call_attempted": True,
                    "live_call_succeeded": False,
                    "validation_run": {
                        "error": {"message": "request timed out after 90s"}
                    },
                }
            )
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        stdout = json.dumps(
            {
                "artifact_path": "artifact2.json",
                "provider_called": True,
                "live_call_succeeded": True,
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", one_batch)

    exit_code = wrapper.main(
        [
            "--provider-pool",
            "google-gemma4-live=gemma-4-26b-a4b-it,"
            "google-gemini31-live-matrix=gemini-3.1-flash-lite-preview",
            "--max-provider-calls",
            "2",
        ],
        readiness_checker=ready,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert exit_code == 0
    assert len(captured_commands) == 2
    assert captured_commands[0][captured_commands[0].index("--provider-model") + 1] == "gemma-4-26b-a4b-it"
    assert captured_commands[1][captured_commands[1].index("--provider-model") + 1] == "gemini-3.1-flash-lite-preview"
    assert sleeps == [wrapper.MIN_POOL_RETRY_DELAY_SECONDS]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert output["previous_attempts"][0]["failure_class"] == "retryable_provider_or_quota_failure"


def test_readme_documents_higher_quota_default_and_safe_fallback() -> None:
    readme = (wrapper.REPO_ROOT / "packages" / "ai-admin" / "README.md").read_text(encoding="utf-8")
    minimal_batch_section = readme.split("Minimal batch validation from the repository root:", 1)[1]

    assert "`google-gemini31-live-matrix`" in minimal_batch_section
    assert "`gemini-3.1-flash-lite-preview`" in minimal_batch_section
    assert "not proof that the live provider is available" in minimal_batch_section
    assert "never `secret_alias` values" in minimal_batch_section
    assert "Do not use `gemini-2.5-flash-lite` for\nrepeated validation batches" in minimal_batch_section
    assert "--provider-pool" in minimal_batch_section
    assert "gemma-4-26b-a4b-it" in minimal_batch_section
    assert "timeout/deadline" in minimal_batch_section
    assert "`NOT_FOUND`/404" in minimal_batch_section


def test_preflight_blocks_when_provider_call_bound_is_too_low(capsys, monkeypatch) -> None:
    checked_readiness = False

    def too_many_batches(_args):
        return 2

    def readiness(*_args, **_kwargs):
        nonlocal checked_readiness
        checked_readiness = True
        return True, "ready"

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", too_many_batches)

    exit_code = wrapper.main(["--max-provider-calls", "1"], readiness_checker=readiness)

    assert exit_code == 2
    assert checked_readiness is False
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["estimated_provider_calls"] == 2
    assert "No live provider call was made" in output["operator_action"]


def test_db_admin_submit_is_forwarded_only_with_explicit_flag() -> None:
    default_command = wrapper.build_harness_command(_parse())
    explicit_command = wrapper.build_harness_command(_parse(["--allow-db-admin-submit"]))

    assert "--allow-db-admin-submit" not in default_command
    assert "--allow-db-admin-submit" in explicit_command


def test_db_admin_submit_success_requires_public_verification_and_recovery_evidence(capsys, monkeypatch) -> None:
    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        stdout = json.dumps(
            {
                "artifact_path": "artifact.json",
                "live_call_succeeded": True,
                "db_admin_submit_result": {
                    "published": 1,
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
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(wrapper, "estimate_provider_call_count", lambda _args: 1)

    exit_code = wrapper.main(
        ["--allow-db-admin-submit"],
        readiness_checker=ready,
        runner=runner,
    )

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["db_admin_submit_allowed"] is True
    assert "publicly verified" in "; ".join(output["db_admin_acceptance"]["blockers"])


def test_readiness_failure_blocks_before_harness_execution(capsys) -> None:
    executed = False

    def not_ready(*_args, **_kwargs):
        return False, "ai-admin not ready GOOGLE_API_KEY=super-secret"

    def runner(_command):
        nonlocal executed
        executed = True
        raise AssertionError("harness must not run when ai-admin is not ready")

    exit_code = wrapper.main([], readiness_checker=not_ready, runner=runner)

    assert exit_code == 2
    assert executed is False
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert "GOOGLE_API_KEY=[REDACTED]" in output["reason"]
    assert "super-secret" not in json.dumps(output)
    assert "cd packages\\ai-admin\\backend" in output["operator_action"]
    assert "does not prove the running backend loaded current source code" in output["backend_freshness_warning"]


def test_ready_wrapper_runs_expected_harness_command_and_prints_sanitized_summary(capsys) -> None:
    captured_command: list[str] = []

    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        captured_command.extend(command)
        stdout = json.dumps({"artifact_path": "artifact.json", "provider_called": True})
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    exit_code = wrapper.main(["--provider-key-alias", "GOOGLE_API_KEY"], readiness_checker=ready, runner=runner)

    assert exit_code == 0
    assert captured_command
    assert "--allow-live-provider" in captured_command
    assert captured_command[captured_command.index("--provider-key-alias") + 1] == "GOOGLE_API_KEY"
    assert "--allow-db-admin-submit" not in captured_command
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert "does not prove the running backend loaded current source code" in output["backend_freshness_warning"]
    assert output["estimated_provider_calls"] == 1
    assert output["db_admin_submit_allowed"] is False
    assert output["harness_summary"]["provider_called"] is True


def test_wrapper_blocks_when_harness_reports_live_call_failure(capsys) -> None:
    captured_command: list[str] = []

    def ready(*_args, **_kwargs):
        return True, "ready"

    def runner(command):
        captured_command.extend(command)
        stdout = json.dumps(
            {
                "artifact_path": "artifact.json",
                "live_call_attempted": True,
                "live_call_succeeded": False,
                "validation_mode": "live",
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    exit_code = wrapper.main([], readiness_checker=ready, runner=runner)

    assert exit_code == 2
    assert captured_command
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason"] == "live provider call did not succeed"
    assert output["db_admin_submit_allowed"] is False
    assert output["harness_summary"]["live_call_succeeded"] is False
