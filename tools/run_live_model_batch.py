"""Safe operator wrapper for a minimal live model validation batch.

The wrapper keeps the live path repeatable while preserving the harness safety
gates: fixture input by default, a provider-call bound that matches the
default fixture split, and no DB-admin submit unless explicitly requested.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tools" / "live_validation_harness_v2.py"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "live-model-batch"
DEFAULT_AI_ADMIN_URL = "http://127.0.0.1:8003"
DEFAULT_PROVIDER_ID = "google-gemini31-live-matrix"
DEFAULT_PROVIDER_MODEL = "gemini-3.1-flash-lite-preview"
SAFE_PROVIDER_POOL_EXAMPLE = (
    "google-gemini31-live-matrix=gemini-3.1-flash-lite-preview,"
    "google-gemma4-live=gemma-4-26b-a4b-it"
)
DEFAULT_MAX_ITEMS = 2
DEFAULT_MAX_PROVIDER_CALLS = 1
DEFAULT_AI_BATCH_SIZE = 20
DEFAULT_AI_BATCH_PROMPT_CHARS = 8000
DEFAULT_LABEL_TIMEOUT_SECONDS = 240.0
MAX_LABEL_TIMEOUT_SECONDS = 900.0
MAX_LIVE_AI_BATCH_SIZE = 20
MAX_LIVE_AI_BATCH_PROMPT_CHARS = 12000
DEFAULT_MAX_LIVE_ITEMS = 300
HARD_MAX_LIVE_ITEMS = 500
MIN_POOL_RETRY_DELAY_SECONDS = 10.0
MAX_POOL_CHOICES = 5
PREFERRED_PROVIDER_GUIDANCE = (
    "Default provider/model is the locally configured higher-quota choice "
    f"{DEFAULT_PROVIDER_ID}/{DEFAULT_PROVIDER_MODEL}; this is a configuration "
    "preference, not proof of live provider availability. If it is not configured "
    "for your environment, list provider_configs without secret_alias values and "
    "choose a higher-quota configured Gemma 3/Gemma 4/Gemini 3.1 Flash Lite model "
    "with --provider-id and --provider-model, or pass a finite pool such as "
    f"--provider-pool {SAFE_PROVIDER_POOL_EXAMPLE}. Timeouts are retryable server "
    "slowness and do not make Gemma 4 permanently bad; NOT_FOUND means that exact "
    "model name is not available for that provider/key. The wrapper never loops "
    "forever: pool attempts are finite and still bounded by --max-provider-calls. "
    "Do not fall back to gemini-2.5-flash-lite for repeated validation batches."
)
BACKEND_FRESHNESS_WARNING = (
    "Readiness only checks ai-admin /health. It does not prove the running "
    "backend loaded current source code; restart ai-admin before validating "
    "wrapper/backend code changes."
)
BACKEND_START_COMMAND = (
    "From repository root: cd packages\\ai-admin\\backend; "
    "$env:PYTHONPATH = '..\\..\\shared'; "
    "python -m uvicorn api.app:create_app --factory --port 8003 --host 127.0.0.1"
)

_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|key|token|authorization|secret|credential)(\s*[=:]\s*)[\"']?[^\"'\s,;}]+"  # noqa: E501
)
_ENV_ASSIGNMENT_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]{2,}(?:API_KEY|TOKEN|SECRET|KEY|CREDENTIAL)\b\s*=\s*[^\s,;}]+"
)
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_RETRYABLE_FAILURE_MARKERS = (
    "timeout",
    "timed out",
    "deadline",
    "503",
    "504",
    "500",
    "502",
    "temporarily",
    "temporary",
    "unavailable",
    "try again",
    "quota",
    "rate limit",
    "rate_limit",
    "429",
    "10054",
    "10061",
    "connection reset",
    "connection aborted",
    "connection refused",
    "reset by peer",
    "transport reset",
    "transport refused",
    "forcibly closed",
    "actively refused",
    "강제로 끊",
    "연결을 거부",
)
_NOT_FOUND_MARKERS = ("not_found", "not found", "404", "model was not found")
DEFAULT_LABEL_CHUNK_RETRIES = 1
MAX_LABEL_CHUNK_RETRIES = 5
DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS = 12.0
MAX_LABEL_CALL_MIN_INTERVAL_SECONDS = 300.0


def configure_utf8_stdio() -> None:
    """Keep operator JSON output UTF-8 safe on Windows/non-UTF-8 consoles."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


class ProviderChoice(NamedTuple):
    provider_id: str
    provider_model: str


def sanitize_message(message: object) -> str:
    text = str(message or "").replace("\r", " ").replace("\n", " ")
    text = _GOOGLE_API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = _ENV_ASSIGNMENT_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=[REDACTED]", text)
    text = _SECRET_VALUE_RE.sub(r"\1\2[REDACTED]", text)
    return text.strip()[:2000]


def parse_provider_pool(args: argparse.Namespace) -> list[ProviderChoice]:
    """Return a finite ordered provider/model pool from CLI args."""
    raw_pool = str(getattr(args, "provider_pool", "") or "").strip()
    if not raw_pool:
        return [ProviderChoice(args.provider_id, args.provider_model)]

    choices: list[ProviderChoice] = []
    for raw_entry in raw_pool.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(
                "--provider-pool entries must use provider_id=model syntax"
            )
        provider_id, provider_model = (part.strip() for part in entry.split("=", 1))
        if not provider_id or not provider_model:
            raise ValueError("--provider-pool entries require both provider_id and model")
        choices.append(ProviderChoice(provider_id, provider_model))
    if not choices:
        raise ValueError("--provider-pool did not contain any provider choices")
    if len(choices) > MAX_POOL_CHOICES:
        raise ValueError(f"--provider-pool supports at most {MAX_POOL_CHOICES} choices")
    return choices


def provider_choice_payloads(choices: list[ProviderChoice]) -> list[dict[str, str]]:
    return [choice._asdict() for choice in choices]


def failure_class_from_summary(summary: dict) -> str:
    """Classify provider failures without marking timeout as permanently bad."""
    candidates = [
        summary.get("reason"),
        summary.get("stdout"),
        summary.get("stderr"),
        summary.get("error"),
    ]
    validation_run = summary.get("validation_run")
    if isinstance(validation_run, dict):
        candidates.append(validation_run.get("error"))
    provider_summary = summary.get("provider_response_summary")
    if isinstance(provider_summary, dict):
        candidates.append(provider_summary.get("error"))
    text = json.dumps(candidates, ensure_ascii=False, sort_keys=True).lower()
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return "model_not_found_non_retryable"
    if any(marker in text for marker in _RETRYABLE_FAILURE_MARKERS):
        return "retryable_provider_or_quota_failure"
    return "unknown_provider_failure"


def enrich_harness_summary(harness_summary: dict) -> dict:
    """Attach sanitized artifact failure detail so operators can distinguish causes."""
    artifact_path = harness_summary.get("artifact_path")
    if not artifact_path:
        return harness_summary
    try:
        path = Path(str(artifact_path))
        if not path.is_file():
            return harness_summary
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        enriched = dict(harness_summary)
        enriched["artifact_read_error"] = sanitize_message(exc)
        return enriched
    enriched = dict(harness_summary)
    for key in (
        "validation_run",
        "provider_response_summary",
        "source",
        "quality_batch_validation",
        "db_admin_submit_result",
        "db_admin_acceptance",
    ):
        if key in artifact:
            enriched[key] = artifact[key]
    return enriched


def db_admin_acceptance_from_summary(summary: dict) -> dict:
    """Require DB mutation proof when --allow-db-admin-submit was requested."""
    acceptance = summary.get("db_admin_acceptance")
    if isinstance(acceptance, dict):
        return acceptance
    db_admin_result = summary.get("db_admin_submit_result")
    if not isinstance(db_admin_result, dict) or db_admin_result.get("skipped"):
        return {
            "accepted": False,
            "blockers": ["DB-admin submit/final approval was skipped or missing."],
        }
    results = db_admin_result.get("results") if isinstance(db_admin_result.get("results"), list) else []
    final_approved = int(db_admin_result.get("ai_safe_final_approved") or 0)
    submitted = int(db_admin_result.get("submitted_to_db_admin") or 0)
    public_verified = int(db_admin_result.get("public_db_verified") or 0)
    rollback_ready = int(db_admin_result.get("rollback_re_review_supported") or 0)
    if not public_verified:
        public_verified = sum(
            1
            for row in results
            if isinstance(row, dict)
            and isinstance(row.get("ai_safe_final_approve"), dict)
            and row["ai_safe_final_approve"].get("public_db_verification", {}).get("verified") is True
        )
    if not rollback_ready:
        rollback_ready = sum(
            1
            for row in results
            if isinstance(row, dict)
            and isinstance(row.get("ai_safe_final_approve"), dict)
            and row["ai_safe_final_approve"].get("rollback_supported")
            and row["ai_safe_final_approve"].get("re_review_supported")
        )
    blockers = []
    if submitted < 1:
        blockers.append("DB-admin submit success was not confirmed.")
    if final_approved < 1:
        blockers.append("ai-safe-final-approved saved rows were not confirmed.")
    if public_verified < final_approved:
        blockers.append("Final-approved rows were not publicly verified in DB-admin response.")
    if final_approved and not (
        rollback_ready >= final_approved or db_admin_result.get("operator_next_action")
    ):
        blockers.append("Rollback/re-review evidence or a clear next action was not present.")
    if int(db_admin_result.get("pending_db_review") or 0) or int(db_admin_result.get("final_approve_failed") or 0) or int(db_admin_result.get("failed") or 0):
        blockers.append("DB-admin left rows pending/failed; inspect held/audited blockers.")
    return {
        "accepted": not blockers,
        "submitted_to_db_admin": submitted,
        "ai_safe_final_approved": final_approved,
        "public_db_verified": public_verified,
        "rollback_re_review_supported": rollback_ready,
        "blockers": blockers,
    }


def _nested_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _countish(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def real_ai_labeling_evidence(summary: dict) -> dict:
    """Require explicit live provider-call proof before claiming real labeling."""
    validation_run = _nested_dict(summary.get("validation_run"))
    provider_summary = _nested_dict(summary.get("provider_response_summary"))
    quality = _nested_dict(summary.get("quality_batch_validation"))
    quality_provider = _nested_dict(quality.get("provider"))
    item_counts = _nested_dict(validation_run.get("item_counts"))

    live_call_attempted = bool(
        summary.get("live_call_attempted")
        or validation_run.get("live_call_attempted")
    )
    live_call_succeeded = bool(
        summary.get("live_call_succeeded")
        or validation_run.get("live_call_succeeded")
    )
    provider_called = bool(
        summary.get("provider_called")
        or provider_summary.get("called")
        or quality_provider.get("called")
    )
    provider_calls = max(
        _countish(provider_summary.get("provider_calls")),
        _countish(quality_provider.get("call_attempts")),
        _countish(item_counts.get("provider_calls")),
    )
    http_label_calls = max(
        _countish(provider_summary.get("http_label_calls")),
        _countish(quality_provider.get("http_label_calls")),
        _countish(item_counts.get("provider_call_attempts")),
    )
    artifact_path = summary.get("artifact_path")
    blockers = []
    if not artifact_path:
        blockers.append("Harness did not report an artifact_path.")
    if not live_call_attempted:
        blockers.append("Harness did not report live_call_attempted=true.")
    if not live_call_succeeded:
        blockers.append("Harness did not report live_call_succeeded=true.")
    if not provider_called:
        blockers.append("Harness did not report provider called=true.")
    if provider_calls < 1:
        blockers.append("Harness did not report provider_calls >= 1.")
    return {
        "real_ai_labeling": not blockers,
        "artifact_path": artifact_path,
        "live_call_attempted": live_call_attempted,
        "live_call_succeeded": live_call_succeeded,
        "provider_called": provider_called,
        "provider_calls": provider_calls,
        "http_label_calls": http_label_calls,
        "blockers": blockers,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the minimal WalletSavior live model batch through "
            "tools\\live_validation_harness_v2.py."
        ),
        epilog=PREFERRED_PROVIDER_GUIDANCE,
    )
    parser.add_argument("--input-json", type=Path, help="Optional raw item JSON. Defaults to built-in fixture.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument(
        "--retain-all-input",
        action="store_true",
        help="Pass every readable row from --input-json into the harness instead of sampling --max-items.",
    )
    parser.add_argument(
        "--allow-large-live-batch",
        action="store_true",
        help=f"Permit --max-live-items-cap above the default {DEFAULT_MAX_LIVE_ITEMS}; still hard-capped.",
    )
    parser.add_argument(
        "--max-live-items-cap",
        type=int,
        default=DEFAULT_MAX_LIVE_ITEMS,
        help=f"Maximum selected rows allowed in one live validation run; default {DEFAULT_MAX_LIVE_ITEMS}, hard cap {HARD_MAX_LIVE_ITEMS}.",
    )
    parser.add_argument("--max-provider-calls", type=int, default=DEFAULT_MAX_PROVIDER_CALLS)
    parser.add_argument(
        "--ai-batch-size",
        type=int,
        default=DEFAULT_AI_BATCH_SIZE,
        help="Target rows per AI provider prompt; bounded by prompt chars and capped at 20.",
    )
    parser.add_argument(
        "--ai-batch-prompt-chars",
        type=int,
        default=DEFAULT_AI_BATCH_PROMPT_CHARS,
        help="AI prompt character budget per provider call; capped at 12000.",
    )
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--provider-model", default=DEFAULT_PROVIDER_MODEL)
    parser.add_argument(
        "--provider-pool",
        help=(
            "Optional finite comma-separated provider_id=model list. Example: "
            f"{SAFE_PROVIDER_POOL_EXAMPLE}. If set, each failed choice consumes "
            "one bounded harness run; no infinite switching."
        ),
    )
    parser.add_argument(
        "--max-pool-attempts",
        type=int,
        default=None,
        help=(
            "Maximum provider-pool choices to try. Defaults to all entries when "
            "--provider-pool is set, otherwise one."
        ),
    )
    parser.add_argument("--ai-admin-url", default=DEFAULT_AI_ADMIN_URL)
    parser.add_argument(
        "--label-timeout-seconds",
        type=float,
        default=DEFAULT_LABEL_TIMEOUT_SECONDS,
        help=(
            "Forwarded bounded timeout for the harness /api/ingest/raw-records/label call; "
            f"default {DEFAULT_LABEL_TIMEOUT_SECONDS:.0f}s, capped at {MAX_LABEL_TIMEOUT_SECONDS:.0f}s."
        ),
    )
    parser.add_argument(
        "--label-chunk-retries",
        type=int,
        default=DEFAULT_LABEL_CHUNK_RETRIES,
        help=(
            "Retry failed /label chunks inside one harness run when the error is retryable; "
            f"default {DEFAULT_LABEL_CHUNK_RETRIES}, capped at {MAX_LABEL_CHUNK_RETRIES}."
        ),
    )
    parser.add_argument(
        "--label-call-min-interval-seconds",
        type=float,
        default=DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS,
        help=(
            "Minimum spacing between /label attempts; default 12s keeps live validation under 5 requests/min."
        ),
    )
    parser.add_argument("--provider-key-alias", help="Optional provider key alias presence check; never pass a secret value.")
    parser.add_argument("--ai-admin-api-key-alias", help="Optional ai-admin API key alias; never pass a secret value.")
    parser.add_argument(
        "--allow-db-admin-submit",
        action="store_true",
        help="Explicitly allow harness publish-approved call; otherwise DB-admin is never mutated.",
    )
    parser.add_argument(
        "--readiness-timeout-seconds",
        type=float,
        default=3.0,
        help="Timeout for ai-admin /health readiness check.",
    )
    return parser


def health_url(ai_admin_url: str) -> str:
    return f"{ai_admin_url.rstrip('/')}/health"


def check_ai_admin_ready(ai_admin_url: str, *, timeout_seconds: float = 3.0) -> tuple[bool, str]:
    url = health_url(ai_admin_url)
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - local operator readiness check
            status = getattr(response, "status", response.getcode())
            if 200 <= int(status) < 300:
                return True, f"ai-admin /health returned HTTP {status} at {url}; {BACKEND_FRESHNESS_WARNING}"
            return False, f"ai-admin /health returned HTTP {status} at {url}"
    except URLError as exc:
        return False, f"ai-admin backend is not ready at {url}: {sanitize_message(exc.reason)}"
    except Exception as exc:
        return False, f"ai-admin backend is not ready at {url}: {sanitize_message(exc)}"


def _load_harness_module():
    spec = importlib.util.spec_from_file_location("live_validation_harness_v2_preflight", HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load harness module at {HARNESS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def effective_live_items_cap(args: argparse.Namespace) -> int:
    cap = int(getattr(args, "max_live_items_cap", DEFAULT_MAX_LIVE_ITEMS))
    allow_large = bool(getattr(args, "allow_large_live_batch", False))
    if cap < 1:
        raise ValueError("--max-live-items-cap must be >= 1")
    if cap > HARD_MAX_LIVE_ITEMS:
        raise ValueError(f"--max-live-items-cap must be <= {HARD_MAX_LIVE_ITEMS}")
    if cap > DEFAULT_MAX_LIVE_ITEMS and not allow_large:
        raise ValueError(
            f"--max-live-items-cap above {DEFAULT_MAX_LIVE_ITEMS} requires --allow-large-live-batch"
        )
    return cap


def assert_live_item_count_within_cap(count: int, cap: int) -> None:
    if count > cap:
        raise ValueError(
            f"selected live item count {count} exceeds cap {cap}; "
            f"pass --allow-large-live-batch with --max-live-items-cap up to {HARD_MAX_LIVE_ITEMS} "
            "only for deliberate bounded live validation"
        )


def estimate_provider_call_count(args: argparse.Namespace) -> int:
    """Compute the deterministic AI batch count without calling providers."""
    harness = _load_harness_module()
    live_items_cap = effective_live_items_cap(args)
    if args.max_items < 1 or args.max_items > live_items_cap:
        raise ValueError(f"--max-items must be between 1 and {live_items_cap}")
    if args.input_json:
        loaded_items, _source_artifacts = harness._load_input_artifact(args.input_json)
        items = loaded_items if args.retain_all_input else loaded_items[: args.max_items]
    else:
        items = harness._fixture_items()[: args.max_items]
    assert_live_item_count_within_cap(len(items), live_items_cap)
    records, _skipped, _invalid_rows, _retention_anomalies = harness._build_quality_raw_records(
        items,
        fallback_source_name="manual-live-validation-v2",
        batch_id="run-live-model-batch-preflight",
    )
    return len(
        harness.split_records_for_ai(
            records,
            max_batch_items=args.ai_batch_size,
            max_prompt_chars=args.ai_batch_prompt_chars,
        )
    )


def effective_label_timeout_seconds(args: argparse.Namespace) -> float:
    return min(float(getattr(args, "label_timeout_seconds", DEFAULT_LABEL_TIMEOUT_SECONDS)), MAX_LABEL_TIMEOUT_SECONDS)


def effective_label_call_min_interval_seconds(args: argparse.Namespace) -> float:
    return min(
        float(getattr(args, "label_call_min_interval_seconds", DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS)),
        MAX_LABEL_CALL_MIN_INTERVAL_SECONDS,
    )


def build_harness_command(
    args: argparse.Namespace,
    choice: ProviderChoice | None = None,
) -> list[str]:
    selected = choice or ProviderChoice(args.provider_id, args.provider_model)
    command = [
        sys.executable,
        str(HARNESS),
        "--allow-live-provider",
        "--provider-id",
        selected.provider_id,
        "--provider-model",
        selected.provider_model,
        "--max-items",
        str(args.max_items),
        "--max-provider-calls",
        str(args.max_provider_calls),
        "--ai-batch-size",
        str(args.ai_batch_size),
        "--ai-batch-prompt-chars",
        str(args.ai_batch_prompt_chars),
        "--artifact-dir",
        str(args.artifact_dir),
        "--ai-admin-url",
        args.ai_admin_url,
        "--label-timeout-seconds",
        str(effective_label_timeout_seconds(args)),
        "--label-chunk-retries",
        str(args.label_chunk_retries),
        "--label-call-min-interval-seconds",
        str(effective_label_call_min_interval_seconds(args)),
    ]
    if args.input_json:
        command.extend(["--input-json", str(args.input_json)])
    if args.retain_all_input:
        command.append("--retain-all-input")
    if args.allow_large_live_batch:
        command.append("--allow-large-live-batch")
    command.extend(["--max-live-items-cap", str(args.max_live_items_cap)])
    if args.provider_key_alias:
        command.extend(["--provider-key-alias", args.provider_key_alias])
    if args.ai_admin_api_key_alias:
        command.extend(["--ai-admin-api-key-alias", args.ai_admin_api_key_alias])
    if args.allow_db_admin_submit:
        command.append("--allow-db-admin-submit")
    return command


def command_shape(command: list[str]) -> list[str]:
    root = str(REPO_ROOT)
    shaped = []
    for part in command:
        if part == sys.executable:
            shaped.append("python")
        elif part.startswith(root):
            shaped.append(str(Path(part).relative_to(REPO_ROOT)))
        else:
            shaped.append(part)
    return shaped


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(  # noqa: S603 - args are explicit, shell is disabled.
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def pool_attempt_bound(args: argparse.Namespace, choices: list[ProviderChoice]) -> int:
    if args.max_pool_attempts is not None:
        return args.max_pool_attempts
    return len(choices) if args.provider_pool else 1


def main(
    argv: list[str] | None = None,
    *,
    readiness_checker=check_ai_admin_ready,
    runner=run_command,
    sleeper=time.sleep,
) -> int:
    configure_utf8_stdio()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_items < 1:
        parser.error("--max-items must be >= 1")
    if args.max_provider_calls < 1:
        parser.error("--max-provider-calls must be >= 1 for the live model batch wrapper")
    if args.ai_batch_size < 1 or args.ai_batch_size > MAX_LIVE_AI_BATCH_SIZE:
        parser.error(f"--ai-batch-size must be between 1 and {MAX_LIVE_AI_BATCH_SIZE}")
    if args.ai_batch_prompt_chars < 1 or args.ai_batch_prompt_chars > MAX_LIVE_AI_BATCH_PROMPT_CHARS:
        parser.error(f"--ai-batch-prompt-chars must be between 1 and {MAX_LIVE_AI_BATCH_PROMPT_CHARS}")
    if args.label_timeout_seconds < 1:
        parser.error("--label-timeout-seconds must be >= 1")
    if args.label_chunk_retries < 0 or args.label_chunk_retries > MAX_LABEL_CHUNK_RETRIES:
        parser.error(f"--label-chunk-retries must be between 0 and {MAX_LABEL_CHUNK_RETRIES}")
    if args.label_call_min_interval_seconds < 0:
        parser.error("--label-call-min-interval-seconds must be >= 0")
    requested_label_timeout_seconds = float(args.label_timeout_seconds)
    args.label_timeout_seconds = effective_label_timeout_seconds(args)
    requested_label_call_min_interval_seconds = float(args.label_call_min_interval_seconds)
    args.label_call_min_interval_seconds = effective_label_call_min_interval_seconds(args)
    try:
        provider_choices = parse_provider_pool(args)
    except ValueError as exc:
        parser.error(str(exc))
    max_pool_attempts = pool_attempt_bound(args, provider_choices)
    if max_pool_attempts < 1:
        parser.error("--max-pool-attempts must be >= 1")
    if max_pool_attempts > len(provider_choices):
        parser.error("--max-pool-attempts cannot exceed provider pool size")
    provider_choices = provider_choices[:max_pool_attempts]

    try:
        estimated_provider_calls = estimate_provider_call_count(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": f"preflight could not compute AI batch count: {sanitize_message(exc)}",
                    "operator_action": (
                        "Fix the input/bounds before any live provider call. "
                        f"{BACKEND_FRESHNESS_WARNING}"
                    ),
                    "real_ai_labeling": False,
                    "blockers": [f"preflight could not compute AI batch count: {sanitize_message(exc)}"],
                    "db_admin_submit_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    estimated_total_provider_calls = estimated_provider_calls * len(provider_choices)
    if estimated_total_provider_calls > args.max_provider_calls:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": (
                        "preflight provider call bound exceeded: "
                        f"would need up to {estimated_total_provider_calls} AI batches/calls "
                        f"across {len(provider_choices)} provider choice(s), "
                        f"max is {args.max_provider_calls}"
                    ),
                    "operator_action": (
                        "Increase --max-provider-calls deliberately or reduce --max-items/input. "
                        "No live provider call was made. "
                        f"{BACKEND_FRESHNESS_WARNING}"
                    ),
                    "real_ai_labeling": False,
                    "blockers": ["preflight provider call bound exceeded; no live provider call was made"],
                    "estimated_provider_calls": estimated_provider_calls,
                    "estimated_total_provider_calls": estimated_total_provider_calls,
                    "ai_batch_size": args.ai_batch_size,
                    "ai_batch_prompt_chars": args.ai_batch_prompt_chars,
                    "label_timeout_seconds": args.label_timeout_seconds,
                    "label_timeout_seconds_requested": requested_label_timeout_seconds,
                    "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
                    "label_chunk_retries": args.label_chunk_retries,
                    "label_call_min_interval_seconds": args.label_call_min_interval_seconds,
                    "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
                    "provider_pool": provider_choice_payloads(provider_choices),
                    "db_admin_submit_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    ready, readiness_message = readiness_checker(
        args.ai_admin_url,
        timeout_seconds=args.readiness_timeout_seconds,
    )
    if not ready:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": sanitize_message(readiness_message),
                    "operator_action": (
                        "Start or restart ai-admin backend, then rerun. "
                        f"{BACKEND_START_COMMAND}. {BACKEND_FRESHNESS_WARNING}"
                    ),
                    "backend_freshness_warning": BACKEND_FRESHNESS_WARNING,
                    "real_ai_labeling": False,
                    "blockers": [sanitize_message(readiness_message)],
                    "label_timeout_seconds": args.label_timeout_seconds,
                    "label_timeout_seconds_requested": requested_label_timeout_seconds,
                    "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
                    "label_chunk_retries": args.label_chunk_retries,
                    "label_call_min_interval_seconds": args.label_call_min_interval_seconds,
                    "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
                    "db_admin_submit_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    attempt_summaries = []
    last_failure_class = None
    for attempt_index, choice in enumerate(provider_choices, start=1):
        command = build_harness_command(args, choice)
        result = runner(command)
        if result.returncode != 0:
            failure_summary = {
                "attempt": attempt_index,
                "provider_id": choice.provider_id,
                "provider_model": choice.provider_model,
                "command_shape": command_shape(command),
                "stdout": sanitize_message(result.stdout),
                "stderr": sanitize_message(result.stderr),
                "returncode": result.returncode,
            }
            last_failure_class = failure_class_from_summary(failure_summary)
            failure_summary["failure_class"] = last_failure_class
            attempt_summaries.append(failure_summary)
            if attempt_index < len(provider_choices):
                sleeper(MIN_POOL_RETRY_DELAY_SECONDS)
                continue
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "label_timeout_seconds": args.label_timeout_seconds,
                        "label_timeout_seconds_requested": requested_label_timeout_seconds,
                        "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
                        "label_chunk_retries": args.label_chunk_retries,
                        "label_call_min_interval_seconds": args.label_call_min_interval_seconds,
                        "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
                        "attempts": attempt_summaries,
                        "real_ai_labeling": False,
                        "blockers": ["live validation harness command failed before complete real AI labeling evidence"],
                        "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return result.returncode
        try:
            harness_summary = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            harness_summary = {"stdout": sanitize_message(result.stdout)}
        harness_summary = enrich_harness_summary(harness_summary)
        if harness_summary.get("live_call_succeeded") is False:
            live_ai_evidence = real_ai_labeling_evidence(harness_summary)
            last_failure_class = failure_class_from_summary(harness_summary)
            attempt_summaries.append(
                {
                    "attempt": attempt_index,
                    "provider_id": choice.provider_id,
                    "provider_model": choice.provider_model,
                    "command_shape": command_shape(command),
                    "failure_class": last_failure_class,
                    "harness_summary": harness_summary,
                }
            )
            if attempt_index < len(provider_choices):
                sleeper(MIN_POOL_RETRY_DELAY_SECONDS)
                continue
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "live provider call did not succeed",
                        "failure_class": last_failure_class,
                        "operator_action": (
                            "Timeout/deadline failures are retryable server slowness; "
                            "keep the Gemma 4 provider configured and rerun later with "
                            "at least 10 seconds between attempts. NOT_FOUND means that "
                            "exact model string should be corrected for that provider/key."
                        ),
                        "readiness": sanitize_message(readiness_message),
                        "backend_freshness_warning": BACKEND_FRESHNESS_WARNING,
                        "estimated_provider_calls": estimated_provider_calls,
                        "estimated_total_provider_calls": estimated_total_provider_calls,
                        "ai_batch_size": args.ai_batch_size,
                        "ai_batch_prompt_chars": args.ai_batch_prompt_chars,
                        "label_timeout_seconds": args.label_timeout_seconds,
                        "label_timeout_seconds_requested": requested_label_timeout_seconds,
                        "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
                        "label_chunk_retries": args.label_chunk_retries,
                        "label_call_min_interval_seconds": args.label_call_min_interval_seconds,
                        "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
                        "provider_pool": provider_choice_payloads(provider_choices),
                        "attempts": attempt_summaries,
                        "real_ai_labeling": False,
                        "live_ai_evidence": live_ai_evidence,
                        "blockers": live_ai_evidence["blockers"] or ["live provider call did not succeed"],
                        "harness_summary": harness_summary,
                        "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        live_ai_evidence = real_ai_labeling_evidence(harness_summary)
        if not live_ai_evidence["real_ai_labeling"]:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "live AI labeling evidence was incomplete",
                        "readiness": sanitize_message(readiness_message),
                        "backend_freshness_warning": BACKEND_FRESHNESS_WARNING,
                        "estimated_provider_calls": estimated_provider_calls,
                        "estimated_total_provider_calls": estimated_total_provider_calls,
                        "provider_pool": provider_choice_payloads(provider_choices),
                        "successful_attempt": {
                            "attempt": attempt_index,
                            "provider_id": choice.provider_id,
                            "provider_model": choice.provider_model,
                        },
                        "command_shape": command_shape(command),
                        "real_ai_labeling": False,
                        "live_ai_evidence": live_ai_evidence,
                        "blockers": live_ai_evidence["blockers"],
                        "harness_summary": harness_summary,
                        "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        db_admin_acceptance = db_admin_acceptance_from_summary(harness_summary)
        if args.allow_db_admin_submit and not db_admin_acceptance.get("accepted"):
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "DB-admin mutation acceptance gates did not pass",
                        "real_ai_labeling": live_ai_evidence["real_ai_labeling"],
                        "live_ai_evidence": live_ai_evidence,
                        "db_admin_submit_allowed": True,
                        "db_admin_acceptance": db_admin_acceptance,
                        "harness_summary": harness_summary,
                        "operator_action": (
                            "Do not treat this run as live DB success. Require DB-admin submit success, "
                            "ai-safe-final-approved saved rows, public DB verification, held/audited "
                            "blockers, and rollback/re-review evidence or a clear next action."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(
            json.dumps(
                {
                    "status": "success",
                    "readiness": sanitize_message(readiness_message),
                    "backend_freshness_warning": BACKEND_FRESHNESS_WARNING,
                    "estimated_provider_calls": estimated_provider_calls,
                    "estimated_total_provider_calls": estimated_total_provider_calls,
                    "ai_batch_size": args.ai_batch_size,
                    "ai_batch_prompt_chars": args.ai_batch_prompt_chars,
                    "label_timeout_seconds": args.label_timeout_seconds,
                    "label_timeout_seconds_requested": requested_label_timeout_seconds,
                    "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
                    "label_chunk_retries": args.label_chunk_retries,
                    "label_call_min_interval_seconds": args.label_call_min_interval_seconds,
                    "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
                    "provider_pool": provider_choice_payloads(provider_choices),
                    "successful_attempt": {
                        "attempt": attempt_index,
                        "provider_id": choice.provider_id,
                        "provider_model": choice.provider_model,
                    },
                    "previous_attempts": attempt_summaries,
                    "command_shape": command_shape(command),
                    "artifact_path": live_ai_evidence["artifact_path"],
                    "provider_calls": live_ai_evidence["provider_calls"],
                    "real_ai_labeling": live_ai_evidence["real_ai_labeling"],
                    "live_ai_evidence": live_ai_evidence,
                    "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
                    "db_admin_acceptance": db_admin_acceptance,
                    "harness_summary": harness_summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
