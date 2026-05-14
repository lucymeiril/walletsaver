"""Manual-safe fixture/stub one-shot DB build orchestration harness.

The default path is intentionally offline: crawler evidence is fixture-backed,
AI labeling is stubbed, DB-admin mutation is a fixture/dry-run, and website
verification checks the persisted public shape from that fixture. Live/provider
or real DB mutation steps require explicit opt-in flags and readiness metadata.
AI Studio live smoke only checks provider readiness unless the operator also
passes --crawler-batch-json and --allow-live-ai-labeling, which delegates to the
bounded live model batch wrapper.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-one-shot-db-build"
LIVE_BATCH_WRAPPER = REPO_ROOT / "tools" / "run_live_model_batch.py"
DEFAULT_LIVE_BATCH_ARTIFACT_SUBDIR = "live-model-batch"
AI_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"
_ORIGINAL_SYS_PATH = list(sys.path)
for import_path in (AI_BACKEND, SHARED):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

def _load_ai_backend_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(
        f"one_shot_orchestrator_{module_name}",
        AI_BACKEND / relative_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load ai-admin backend module {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

_AISTUDIO_SMOKE = _load_ai_backend_module(
    "aistudio_live_smoke",
    "services\\aistudio_live_smoke.py",
)
_DB_ADMIN_ADAPTER = _load_ai_backend_module(
    "db_admin_adapter",
    "services\\db_admin_adapter.py",
)
LIVE_SMOKE_ENV = _AISTUDIO_SMOKE.LIVE_SMOKE_ENV
sys.path = _ORIGINAL_SYS_PATH
REAL_AI_LABELING_BLOCKER = (
    "Real AI labeling is only invoked when --allow-live-ai-labeling and "
    "--allow-live-ai-provider are both set; the orchestrator delegates to "
    "tools\\run_live_model_batch.py with bounded provider calls."
)

_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|key|token|authorization|secret|credential)(\s*[=:]\s*)[\"']?[^\"'\s,;}]+"  # noqa: E501
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[0-9A-Za-z_\-\.]{8,}")
_ENV_ASSIGNMENT_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]{2,}(?:API_KEY|TOKEN|SECRET|KEY|CREDENTIAL)\b\s*=\s*[^\s,;}]+"
)
_GOOGLE_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _sanitize_text(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = _GOOGLE_API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", text)
    text = _ENV_ASSIGNMENT_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=[REDACTED]", text)
    text = _SECRET_VALUE_RE.sub(r"\1\2[REDACTED]", text)
    return text.strip()[:1000]

def _is_secret_field(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized.endswith("_alias"):
        return False
    return normalized in {
        "api_key",
        "x_api_key",
        "token",
        "authorization",
        "password",
        "credential",
        "secret",
    } or normalized.endswith(
        (
            "_api_key",
            "_token",
            "_authorization",
            "_password",
            "_credential",
            "_secret",
        )
    )

def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): ("[REDACTED]" if _is_secret_field(key) else _safe_json(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value

def _load_json_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    source_artifact_rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("items", "records", "raw_items", "raw_selected_items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            for container_key in ("sources", "crawlers", "runs", "batches"):
                sources = data.get(container_key)
                if not isinstance(sources, list):
                    continue
                for source in sources:
                    if not isinstance(source, dict):
                        raise ValueError(f"{path} contains a structurally unreadable source entry")
                    rows = None
                    for row_key in ("items", "records", "raw_items", "raw_selected_items"):
                        if isinstance(source.get(row_key), list):
                            rows = source[row_key]
                            break
                    if rows is None:
                        rows = []
                    source_name = source.get("source_name") or source.get("source") or source.get("name")
                    crawler_name = source.get("crawler_name") or source.get("crawler")
                    schema_type = source.get("schema_type")
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError(f"{path} contains a structurally unreadable crawler row")
                        annotated = dict(row)
                        if source_name and not (annotated.get("source_name") or annotated.get("source")):
                            annotated["source_name"] = source_name
                        if crawler_name and not annotated.get("crawler_name"):
                            annotated["crawler_name"] = crawler_name
                        if schema_type and not annotated.get("schema_type"):
                            annotated["schema_type"] = schema_type
                        source_artifact_rows.append(annotated)
                data = source_artifact_rows
                break
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(f"{path} must contain a JSON list or an object with items/records/raw_items/sources")
    return data

def _command_shape(command: list[str]) -> list[str]:
    shaped: list[str] = []
    root = str(REPO_ROOT)
    for part in command:
        if part == sys.executable:
            shaped.append("python")
        elif isinstance(part, str) and part.startswith(root):
            shaped.append(str(Path(part).relative_to(REPO_ROOT)))
        else:
            shaped.append(str(part))
    return shaped

def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - args are explicit, shell is disabled.
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

def build_live_batch_command(args: argparse.Namespace) -> list[str]:
    artifact_dir = args.live_batch_artifact_dir or (args.artifact_dir / DEFAULT_LIVE_BATCH_ARTIFACT_SUBDIR)
    command = [
        sys.executable,
        str(LIVE_BATCH_WRAPPER),
        "--input-json",
        str(args.crawler_batch_json),
        "--artifact-dir",
        str(artifact_dir),
        "--max-items",
        str(args.live_batch_max_items),
        "--max-provider-calls",
        str(args.live_batch_max_provider_calls),
        "--ai-batch-size",
        str(args.live_batch_ai_batch_size),
        "--ai-batch-prompt-chars",
        str(args.live_batch_ai_batch_prompt_chars),
        "--provider-id",
        args.provider_id or "",
        "--provider-model",
        args.provider_model,
        "--ai-admin-url",
        args.ai_admin_url,
        "--label-chunk-retries",
        str(args.live_batch_label_chunk_retries),
        "--label-call-min-interval-seconds",
        str(args.live_batch_label_call_min_interval_seconds),
    ]
    if args.provider_pool:
        command.extend(["--provider-pool", args.provider_pool])
    if args.max_pool_attempts is not None:
        command.extend(["--max-pool-attempts", str(args.max_pool_attempts)])
    if args.provider_key_alias:
        command.extend(["--provider-key-alias", args.provider_key_alias])
    if args.ai_admin_api_key_alias:
        command.extend(["--ai-admin-api-key-alias", args.ai_admin_api_key_alias])
    if getattr(args, "retain_all_crawler_input", False):
        command.append("--retain-all-input")
    if args.allow_db_mutation:
        command.append("--allow-db-admin-submit")
    return command

def _db_admin_env_paths(args: argparse.Namespace) -> tuple[Path, ...] | None:
    env_file_arg = getattr(args, "db_admin_env_file", None)
    return tuple(env_file_arg) if env_file_arg is not None else None

def _run_db_mutation_preflight(args: argparse.Namespace) -> dict[str, Any]:
    return asyncio.run(
        _DB_ADMIN_ADAPTER.check_db_admin_mutation_preflight(
            base_url=args.db_admin_url,
            api_key=args.db_admin_api_key,
            env_paths=_db_admin_env_paths(args),
        )
    )

def _parse_live_batch_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout or "{}")
        return parsed if isinstance(parsed, dict) else {"stdout": _sanitize_text(parsed)}
    except json.JSONDecodeError:
        return {"stdout": _sanitize_text(stdout)}

def _countish(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def _db_admin_submit_safety(db_admin_result: Any) -> dict[str, Any]:
    if not isinstance(db_admin_result, dict) or db_admin_result.get("skipped"):
        return {
            "submit_attempted": False,
            "safe_final_approval_confirmed": False,
            "final_approved_count": 0,
            "pending_db_review_count": 0,
            "final_approve_failed_count": 0,
            "failed_count": 0,
            "public_db_verified_count": 0,
            "rollback_re_review_supported_count": 0,
            "blocked_rows_held_for_review": True,
            "blocked_rows_audited": bool(isinstance(db_admin_result, dict) and db_admin_result.get("reason")),
            "rollback_re_review_evidence_or_next_action": False,
            "blockers": ["DB-admin submit/final approval was skipped or missing."],
        }

    results = db_admin_result.get("results") if isinstance(db_admin_result.get("results"), list) else []
    result_statuses = [str(row.get("status") or "") for row in results if isinstance(row, dict)]
    final_approved_count = _countish(db_admin_result.get("ai_safe_final_approved"))
    pending_db_review_count = (
        _countish(db_admin_result.get("pending_db_review"))
        if db_admin_result.get("pending_db_review") is not None
        else sum(1 for status in result_statuses if status == "pending_db_review")
    )
    final_approve_failed_count = (
        _countish(db_admin_result.get("final_approve_failed"))
        if db_admin_result.get("final_approve_failed") is not None
        else sum(1 for row in results if isinstance(row, dict) and row.get("final_approve_error"))
    )
    failed_count = (
        _countish(db_admin_result.get("failed"))
        if db_admin_result.get("failed") is not None
        else sum(
            1
            for status in result_statuses
            if status and status not in {"published", "pending_db_review"}
        )
    )
    public_db_verified_count = (
        _countish(db_admin_result.get("public_db_verified"))
        if db_admin_result.get("public_db_verified") is not None
        else sum(
            1
            for row in results
            if isinstance(row, dict)
            and isinstance(row.get("ai_safe_final_approve"), dict)
            and row["ai_safe_final_approve"].get("public_db_verification", {}).get("verified") is True
        )
    )
    rollback_re_review_supported_count = (
        _countish(db_admin_result.get("rollback_re_review_supported"))
        if db_admin_result.get("rollback_re_review_supported") is not None
        else sum(
            1
            for row in results
            if isinstance(row, dict)
            and isinstance(row.get("ai_safe_final_approve"), dict)
            and row["ai_safe_final_approve"].get("rollback_supported")
            and row["ai_safe_final_approve"].get("re_review_supported")
        )
    )
    rollback_re_review_evidence_or_next_action = bool(
        rollback_re_review_supported_count >= final_approved_count > 0
        or db_admin_result.get("operator_next_action")
    )
    held_rows = [
        row
        for row in results
        if isinstance(row, dict)
        and (
            row.get("status") == "pending_db_review"
            or row.get("requires_db_admin_review")
            or row.get("final_approve_error")
        )
    ]
    blocked_rows_present = pending_db_review_count > 0 or final_approve_failed_count > 0 or failed_count > 0
    blocked_rows_held_for_review = (not blocked_rows_present) or bool(
        held_rows or pending_db_review_count > 0 or db_admin_result.get("held_for_review")
    )
    blocked_rows_audited = (not blocked_rows_present) or bool(
        db_admin_result.get("audit")
        or db_admin_result.get("audit_visible")
        or db_admin_result.get("approval_audit_visible")
        or results
    )

    blockers: list[str] = []
    if final_approved_count < 1:
        blockers.append("DB-admin result did not confirm ai_safe_final_approved rows; do not treat submit-only quality checks as safe DB mutation.")
    if public_db_verified_count < final_approved_count:
        blockers.append("DB-admin final-approved rows were not publicly verified in the DB response.")
    if final_approved_count and not rollback_re_review_evidence_or_next_action:
        blockers.append("DB-admin result did not include rollback/re-review evidence or a clear operator next action.")
    if pending_db_review_count or final_approve_failed_count or failed_count:
        blockers.append("DB-admin final approval left rows pending/failed; blocked rows must remain held/audited.")
    if not blocked_rows_held_for_review:
        blockers.append("DB-admin blocked rows were not proven held for review.")
    if not blocked_rows_audited:
        blockers.append("DB-admin blocked rows were not proven audited.")

    return {
        "submit_attempted": True,
        "safe_final_approval_confirmed": final_approved_count > 0 and not blockers,
        "final_approved_count": final_approved_count,
        "pending_db_review_count": pending_db_review_count,
        "final_approve_failed_count": final_approve_failed_count,
        "failed_count": failed_count,
        "public_db_verified_count": public_db_verified_count,
        "rollback_re_review_supported_count": rollback_re_review_supported_count,
        "blocked_rows_held_for_review": blocked_rows_held_for_review,
        "blocked_rows_audited": blocked_rows_audited,
        "rollback_re_review_evidence_or_next_action": rollback_re_review_evidence_or_next_action,
        "blockers": blockers,
    }

def _error_detail(exc: BaseException | str) -> dict[str, str]:
    return {
        "class": exc.__class__.__name__ if isinstance(exc, BaseException) else "Error",
        "message": _sanitize_text(str(exc)),
    }

def _phase(
    name: str,
    *,
    mode: str,
    status: str = "passed",
    counts: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "mode": mode,
        "status": status,
        "counts": counts or {},
        "blockers": blockers or [],
        "warnings": warnings or [],
        "details": _safe_json(details or {}),
    }

def _fixture_source_items() -> list[dict[str, Any]]:
    return [
        {
            "product_id": "one-shot-fixture-tofu-300g",
            "name": "원천명 국산콩 두부 300g",
            "sale_price": 1980,
            "source": "emart-fixture",
            "source_url": "https://emart.example/products/tofu-300g",
            "image_url": "https://emart.example/images/tofu-300g.jpg",
            "category_hint": "두부/콩나물",
        }
    ]

def _stub_ai_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_name": item["source"],
        "item": {
            "name": "풀무원 국산콩 두부 300g",
            "sale_price": 1980,
            "original_price": None,
            "discount_percent": None,
            "source_url": item["source_url"],
            "image_url": item["image_url"],
            "category_id": "processed.tofu.firm",
            "keywords": ["두부"],
            "attributes": {"origin": "domestic", "origin_label": "국산"},
            "package_quantity": 300,
            "package_unit": "g",
            "display_unit": "300g",
            "publication_kind": "price_observation",
            "price_observation_only": True,
            "raw_data": {
                "source_title": item["name"],
                "raw_evidence": {"raw_title": item["name"], "raw_unit": "300g"},
                "published_item": {
                    "name": "풀무원 국산콩 두부 300g",
                    "category_id": "processed.tofu.firm",
                    "keywords": ["두부"],
                },
            },
        },
    }

def _verify_public_shape(candidate: dict[str, Any], db_result: dict[str, Any]) -> dict[str, Any]:
    item = candidate["item"]
    product = {
        "canonical_name": item["name"],
        "category_id": item["category_id"],
        "keywords": item["keywords"],
        "attributes": item["attributes"],
    }
    offer = {
        "source_name": candidate["source_name"],
        "source_title": item["raw_data"]["source_title"],
        "source_url": item["source_url"],
        "image_url": item["image_url"],
        "price": item["sale_price"],
        "original_price": item["original_price"],
        "discount_rate": item["discount_percent"],
        "raw_data": item["raw_data"],
    }
    history = [
        {
            "date": db_result["approved_at"],
            "price": item["sale_price"],
            "source": candidate["source_name"],
            "source_url": item["source_url"],
            "raw_data": item["raw_data"],
        }
    ]
    missing = []
    if not product["canonical_name"]:
        missing.append("product.canonical_name")
    if not product["category_id"]:
        missing.append("product.category_id")
    for field in ("source_name", "source_title", "source_url", "image_url", "price"):
        if offer[field] in (None, "", []):
            missing.append(f"offer.{field}")
    if not history:
        missing.append("history")
    return {
        "product": product,
        "offer": offer,
        "history": history,
        "shape_ok": not missing,
        "missing": missing,
    }

async def _submit_live_db(candidate: dict[str, Any], db_admin_url: str, db_admin_api_key: str) -> dict[str, Any]:
    adapter = _DB_ADMIN_ADAPTER.DBAdminAdapter(
        ingestion_url=f"{db_admin_url.rstrip('/')}/api/ingestions",
        api_key=db_admin_api_key,
    )
    submit_result = await adapter.submit_ingestion(_DB_ADMIN_ADAPTER.build_db_admin_ingestion_payload(candidate))
    ingestion_id = submit_result.get("id") or submit_result.get("ingestion_id")
    if not ingestion_id:
        return {
            "submitted": True,
            "approved": False,
            "submit_result": submit_result,
            "blocker": "DB-admin submit response did not include id/ingestion_id for ai-safe-final-approve",
        }
    approve_result = await adapter.ai_safe_final_approve(
        ingestion_id,
        notes="one-shot DB build orchestrator explicit live mutation",
    )
    public_verified = (
        isinstance(approve_result.get("public_db_verification"), dict)
        and approve_result["public_db_verification"].get("verified") is True
    )
    rollback_re_review_ready = bool(
        approve_result.get("rollback_supported")
        and approve_result.get("re_review_supported")
        and (approve_result.get("operator_next_action") or approve_result.get("raw_evidence_retained"))
    )
    approved = (
        approve_result.get("status") == "approved"
        and bool(approve_result.get("saved"))
        and public_verified
        and rollback_re_review_ready
    )
    return {
        "submitted": True,
        "approved": approved,
        "submit_result": submit_result,
        "approve_result": approve_result,
        **(
            {}
            if approved
            else {
                "blocker": (
                    "DB-admin ai-safe-final-approve did not include saved-row public verification "
                    "and rollback/re-review evidence."
                )
            }
        ),
    }

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manual-safe fixture/stub one-shot DB build orchestrator. Defaults to fixture/stub/dry-run. "
            f"--allow-live-ai-provider runs AI Studio readiness smoke only when {LIVE_SMOKE_ENV}=1; "
            "--allow-live-ai-labeling plus --crawler-batch-json delegates real labeling to "
            "tools\\run_live_model_batch.py."
        ),
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--allow-live-crawler", action="store_true")
    parser.add_argument("--crawler-batch-json", type=Path, help="Crawler batch artifact JSON to feed into the live model batch wrapper.")
    parser.add_argument("--allow-live-ai-provider", action="store_true", help="Opt in to provider-backed ai-admin calls; required with --allow-live-ai-labeling.")
    parser.add_argument("--allow-live-ai-labeling", action="store_true", help="Run tools\\run_live_model_batch.py against --crawler-batch-json with bounded provider calls.")
    parser.add_argument("--provider-id")
    parser.add_argument("--provider-model", default="gemini-3.1-flash-lite-preview")
    parser.add_argument("--provider-pool")
    parser.add_argument("--max-pool-attempts", type=int, default=None)
    parser.add_argument("--provider-secret-alias", default="GOOGLE_API_KEY")
    parser.add_argument("--provider-key-alias", default=None, help="Alias presence check forwarded to live batch wrapper; never pass a secret value.")
    parser.add_argument("--ai-admin-url", default=os.getenv("AI_ADMIN_URL", "http://127.0.0.1:8003"))
    parser.add_argument("--ai-admin-api-key-alias", default=None, help="Alias for ai-admin X-API-Key forwarded to live batch wrapper; never pass a secret value.")
    parser.add_argument("--live-batch-artifact-dir", type=Path, default=None)
    parser.add_argument("--live-batch-max-items", type=int, default=2)
    parser.add_argument("--live-batch-max-provider-calls", type=int, default=1)
    parser.add_argument("--live-batch-ai-batch-size", type=int, default=20)
    parser.add_argument("--live-batch-ai-batch-prompt-chars", type=int, default=8000)
    parser.add_argument("--live-batch-label-chunk-retries", type=int, default=1)
    parser.add_argument("--live-batch-label-call-min-interval-seconds", type=float, default=12.0)
    parser.add_argument(
        "--retain-all-crawler-input",
        action="store_true",
        help=(
            "When delegating --crawler-batch-json live labeling, forward --retain-all-input "
            "so every readable crawler row is retained in live batch artifacts instead of "
            "bounding input rows to --live-batch-max-items."
        ),
    )
    parser.add_argument("--allow-db-mutation", action="store_true")
    parser.add_argument("--db-admin-url", default=os.getenv("DB_ADMIN_URL"))
    parser.add_argument("--db-admin-api-key", default=os.getenv("DB_ADMIN_API_KEY"))
    parser.add_argument("--db-admin-env-file", action="append", type=Path, default=None)
    parser.add_argument("--allow-live-website", action="store_true")
    parser.add_argument("--website-url", default=os.getenv("WEBSITE_PUBLIC_URL"))
    return parser

def run_orchestrator(
    args: argparse.Namespace,
    *,
    live_batch_runner=_run_command,
) -> dict[str, Any]:
    run_id = f"one-shot-db-build-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    phases: list[dict[str, Any]] = []
    warnings = [
        "Default run is fixture/stub/dry-run and does not prove live all-source DB construction.",
        "Live AI labeling is delegated to tools\\run_live_model_batch.py only when --allow-live-ai-labeling and --allow-live-ai-provider are explicit.",
    ]
    live_integrations_invoked = {
        "crawler": False,
        "crawler_batch_artifact": False,
        "ai_provider_smoke": False,
        "ai_labeling": False,
        "db_mutation": False,
        "website_verification": False,
    }
    live_batch_summary: dict[str, Any] | None = None
    db_mutation_preflight: dict[str, Any] | None = None

    if args.crawler_batch_json:
        try:
            source_items = _load_json_items(args.crawler_batch_json)
            retain_all_crawler_input = bool(getattr(args, "retain_all_crawler_input", False))
            intended_live_batch_rows = len(source_items) if retain_all_crawler_input else min(len(source_items), args.live_batch_max_items)
            live_integrations_invoked["crawler_batch_artifact"] = True
            phases.append(
                _phase(
                    "crawler-admin batch artifact/source evidence",
                    mode="artifact",
                    counts={
                        "source_raw": len(source_items),
                        "selected_for_live_batch_max": min(len(source_items), args.live_batch_max_items),
                        "readable_rows_intended_for_live_batch": intended_live_batch_rows,
                    },
                    warnings=[
                        "Crawler artifact was consumed from disk; no live crawler network call was made by this orchestrator.",
                        *(
                            [
                                "--retain-all-crawler-input keeps all readable crawler artifact rows in the delegated live batch input; this is not a claim that the orchestrator performed a live all-source crawler build."
                            ]
                            if retain_all_crawler_input
                            else []
                        ),
                    ],
                    details={
                        "crawler_batch_json": str(args.crawler_batch_json),
                        "live_batch_required_for_real_labeling": True,
                        "retain_all_crawler_input": retain_all_crawler_input,
                        "bounded_by_live_batch_max_items": not retain_all_crawler_input,
                    },
                )
            )
        except Exception as exc:
            source_items = []
            phases.append(
                _phase(
                    "crawler-admin batch artifact/source evidence",
                    mode="artifact",
                    status="blocked",
                    blockers=[f"Could not load --crawler-batch-json: {_sanitize_text(exc)}"],
                    details={"crawler_batch_json": str(args.crawler_batch_json)},
                )
            )
    elif args.allow_live_crawler:
        phases.append(
            _phase(
                "crawler-admin diagnostics/source evidence",
                mode="live",
                status="blocked",
                blockers=[
                    "Live crawler is not implemented/invoked by this orchestrator and cannot feed source_items without a concrete crawler target."
                ],
                details={"live_opt_in": True, "source_items_available": 0, "live_crawler_invoked": False},
            )
        )
        source_items: list[dict[str, Any]] = []
    else:
        source_items = _fixture_source_items()
        phases.append(
            _phase(
                "crawler-admin diagnostics/source evidence",
                mode="fixture",
                counts={"source_raw": len(source_items), "parsed": len(source_items), "valid": len(source_items)},
                warnings=["Fixture diagnostics only; live crawler network disabled by default."],
                details={
                    "route_target": "crawler-admin /api/crawlers/diagnostics",
                    "live_enabled": False,
                    "evidence": [{"crawler_id": "emart-fixture", "source_url": item["source_url"]} for item in source_items],
                },
            )
        )

    candidates: list[dict[str, Any]] = []
    candidate: dict[str, Any] | None = None
    if args.allow_live_ai_labeling:
        blockers = []
        if not args.allow_live_ai_provider:
            blockers.append("--allow-live-ai-labeling requires --allow-live-ai-provider")
        if not args.crawler_batch_json:
            blockers.append("--allow-live-ai-labeling requires --crawler-batch-json from a crawler batch artifact")
        if not args.provider_id and not args.provider_pool:
            blockers.append("--provider-id or --provider-pool is required for live AI labeling")
        if args.live_batch_max_provider_calls < 1:
            blockers.append("--live-batch-max-provider-calls must be >= 1 for live AI labeling")
        if args.allow_db_mutation:
            db_mutation_preflight = _run_db_mutation_preflight(args)
            if not db_mutation_preflight.get("ready_to_mutate"):
                blockers.append(
                    "DB-admin mutation preflight failed; --allow-db-admin-submit was not forwarded"
                )
        if blockers:
            phases.append(
                _phase(
                    "ai-admin live model batch label/classify",
                    mode="live",
                    status="blocked",
                    blockers=blockers,
                    counts={"candidate_items": 0, "provider_calls": 0},
                    details={
                        "live_batch_invoked": False,
                        "db_admin_submit_forwarded": False,
                        **(
                            {"db_admin_mutation_preflight": db_mutation_preflight}
                            if db_mutation_preflight is not None
                            else {}
                        ),
                    },
                )
            )
        else:
            live_batch_command = build_live_batch_command(args)
            result = live_batch_runner(live_batch_command)
            live_batch_summary = _parse_live_batch_stdout(result.stdout)
            harness_summary = live_batch_summary.get("harness_summary") if isinstance(live_batch_summary, dict) else None
            validation_run = harness_summary.get("validation_run", {}) if isinstance(harness_summary, dict) else {}
            provider_summary = harness_summary.get("provider_response_summary", {}) if isinstance(harness_summary, dict) else {}
            live_integrations_invoked["ai_labeling"] = bool(validation_run.get("live_call_attempted") or provider_summary.get("called"))
            status = "passed" if result.returncode == 0 and validation_run.get("live_call_succeeded") is True else "blocked"
            if result.returncode != 0:
                status = "failed"
            phases.append(
                _phase(
                    "ai-admin live model batch label/classify",
                    mode="live",
                    status=status,
                    counts={
                        "candidate_items": validation_run.get("item_counts", {}).get("records", 0),
                        "provider_calls": provider_summary.get("provider_calls") or 0,
                        "readable_rows_intended_for_live_batch": len(source_items)
                        if getattr(args, "retain_all_crawler_input", False)
                        else min(len(source_items), args.live_batch_max_items),
                    },
                    blockers=[] if status == "passed" else ["Live model batch did not complete successfully; inspect live_batch_summary."],
                    details={
                        "live_batch_invoked": True,
                        "command_shape": _command_shape(live_batch_command),
                        "returncode": result.returncode,
                        "stderr": _sanitize_text(result.stderr),
                        "live_batch_summary": live_batch_summary,
                        "db_admin_submit_forwarded": bool(args.allow_db_mutation),
                        "retain_all_crawler_input_forwarded": bool(getattr(args, "retain_all_crawler_input", False)),
                    },
                )
            )
    elif args.crawler_batch_json:
        phases.append(
            _phase(
                "ai-admin API label/classify",
                mode="skipped",
                status="blocked",
                blockers=[
                    "Crawler batch artifact loaded, but --allow-live-ai-labeling was not set; no stub success is produced for crawler artifacts."
                ],
                counts={"candidate_items": 0, "provider_calls": 0},
                details={"real_labeling_invoked": False, "stub_candidate_created": False},
            )
        )
    elif args.allow_live_ai_provider:
        readiness = _AISTUDIO_SMOKE.run_aistudio_live_smoke(
            config=_AISTUDIO_SMOKE.build_provider_config(
                provider_id=args.provider_id or "missing-provider-id",
                model=args.provider_model,
                secret_alias=args.provider_secret_alias,
            )
        )
        live_integrations_invoked["ai_provider_smoke"] = bool(readiness.get("live_call_attempted"))
        blockers = []
        if not args.provider_id:
            blockers.append("--provider-id is required with --allow-live-ai-provider")
        if readiness["status"] != "PASSED":
            blockers.append(
                f"AIStudio readiness status {readiness['status']}; {readiness.get('skip_reason') or 'live smoke did not pass'}"
            )
        else:
            blockers.append(REAL_AI_LABELING_BLOCKER)
        if blockers:
            phases.append(
                _phase(
                    "ai-admin API label/classify",
                    mode="live",
                    status="blocked",
                    blockers=blockers,
                    counts={"candidate_items": 0, "provider_calls": 0},
                    details={
                        "aistudio_readiness": readiness,
                        "live_provider_opt_in": True,
                        "real_labeling_invoked": False,
                        "stub_candidate_created": False,
                    },
                )
            )
    else:
        candidates = [_stub_ai_candidate(item) for item in source_items]
        candidate = candidates[0] if candidates else None
        phases.append(
            _phase(
                "ai-admin API label/classify",
                mode="stub",
                counts={"candidate_items": len(candidates), "provider_calls": 0},
                warnings=["Stub/dry-run classification only; no AI quota consumed and no real labeling request made."],
                details={
                    "live_provider_opt_in": False,
                    "classification_scope": "stub_dry_run",
                    "real_labeling_invoked": False,
                    "aistudio_readiness": {"status": "SKIPPED", "live_gate_env": LIVE_SMOKE_ENV},
                },
            )
        )

    db_result: dict[str, Any] | None = None
    if live_batch_summary is not None:
        harness_summary = live_batch_summary.get("harness_summary") if isinstance(live_batch_summary, dict) else {}
        db_admin_result = harness_summary.get("db_admin_submit_result") if isinstance(harness_summary, dict) else None
        db_admin_safety = _db_admin_submit_safety(db_admin_result)
        db_submit_completed = bool(
            args.allow_db_mutation
            and live_batch_summary.get("status") == "success"
            and db_admin_safety["safe_final_approval_confirmed"]
        )
        live_integrations_invoked["db_mutation"] = bool(
            args.allow_db_mutation
            and live_batch_summary.get("status") == "success"
            and db_admin_safety["safe_final_approval_confirmed"]
        )
        phases.append(
            _phase(
                "DB-admin ingestion submit and ai-safe-final-approve",
                mode="live" if args.allow_db_mutation else "skipped",
                status="passed" if db_submit_completed else ("blocked" if args.allow_db_mutation else "skipped"),
                blockers=[] if db_submit_completed or not args.allow_db_mutation else db_admin_safety["blockers"],
                warnings=[] if args.allow_db_mutation else [
                    "Live DB-admin submit/final approval was not allowed; rerun with --allow-db-mutation to forward --allow-db-admin-submit."
                ],
                counts={
                    "submit_forwarded": int(bool(args.allow_db_mutation)),
                    "mutated_real_db": db_admin_safety["final_approved_count"] if args.allow_db_mutation else 0,
                    "ai_safe_final_approved": db_admin_safety["final_approved_count"],
                    "pending_db_review": db_admin_safety["pending_db_review_count"],
                    "final_approve_failed": db_admin_safety["final_approve_failed_count"],
                },
                details={
                    "db_admin_submit_allowed": bool(args.allow_db_mutation),
                    "db_admin_submit_result": db_admin_result,
                    "db_admin_submit_safety": db_admin_safety,
                    **(
                        {"db_admin_mutation_preflight": db_mutation_preflight}
                        if db_mutation_preflight is not None
                        else {}
                    ),
                    "handled_by": "tools\\run_live_model_batch.py -> tools\\live_validation_harness_v2.py",
                },
            )
        )
    elif args.allow_db_mutation:
        blockers = []
        resolved_db_url, resolved_db_key = _DB_ADMIN_ADAPTER.resolve_db_admin_credentials(
            base_url=args.db_admin_url,
            api_key=args.db_admin_api_key,
            env_paths=_db_admin_env_paths(args),
        )
        if db_mutation_preflight is None:
            db_mutation_preflight = _run_db_mutation_preflight(args)
        readiness = db_mutation_preflight.get("readiness") or {}
        if readiness.get("status") == "url_missing":
            blockers.append("DB_ADMIN_URL or --db-admin-url is required with --allow-db-mutation")
        if not resolved_db_key:
            blockers.append("DB_ADMIN_API_KEY or --db-admin-api-key is required with --allow-db-mutation")
        if not db_mutation_preflight.get("ready_to_mutate"):
            blockers.append(
                f"DB-admin mutation preflight status {db_mutation_preflight.get('status')}; no DB mutation attempted"
            )
        if candidate is None:
            blockers.append("No AI-reviewed candidate item is available for DB-admin submit")
        if blockers:
            phases.append(
                _phase(
                    "DB-admin ingestion submit and ai-safe-final-approve",
                    mode="live",
                    status="blocked",
                    blockers=blockers,
                    details={
                        "mutation_opt_in": True,
                        "db_admin_readiness": readiness,
                        "db_admin_mutation_preflight": db_mutation_preflight,
                    },
                )
            )
        else:
            try:
                db_result = asyncio.run(_submit_live_db(candidate, resolved_db_url, resolved_db_key))
                live_integrations_invoked["db_mutation"] = bool(db_result.get("submitted"))
                status = "passed" if db_result.get("approved") else "blocked"
                phases.append(
                    _phase(
                        "DB-admin ingestion submit and ai-safe-final-approve",
                        mode="live",
                        status=status,
                        counts={"submitted": int(bool(db_result.get("submitted"))), "approved": int(bool(db_result.get("approved")))},
                        blockers=[db_result["blocker"]] if db_result.get("blocker") else [],
                        details={
                            **db_result,
                            "db_admin_readiness": readiness,
                            "db_admin_mutation_preflight": db_mutation_preflight,
                        },
                    )
                )
            except Exception as exc:  # pragma: no cover - live network error path
                phases.append(
                    _phase(
                        "DB-admin ingestion submit and ai-safe-final-approve",
                        mode="live",
                        status="failed",
                        blockers=["DB-admin live mutation failed; inspect sanitized error."],
                        details={"error": _error_detail(exc), "mutation_opt_in": True},
                    )
                )
    elif candidates:
        db_result = {
            "submitted": False,
            "approved": True,
            "approved_count": len(candidates),
            "dry_run": True,
            "ingestion_id": "fixture-ingestion-1",
            "product_id": "fixture-product-1",
            "history_id": "fixture-history-1",
            "approved_at": _utc_now(),
        }
        phases.append(
            _phase(
                "DB-admin ingestion submit and ai-safe-final-approve",
                mode="fixture",
                counts={"submitted": 0, "approved": len(candidates), "mutated_real_db": 0},
                warnings=["Fixture approval only; real DB mutation requires --allow-db-mutation and DB credentials."],
                details=db_result,
            )
        )
    else:
        phases.append(
            _phase(
                "DB-admin ingestion submit and ai-safe-final-approve",
                mode="skipped",
                status="skipped",
                blockers=["No candidate item available."],
            )
        )

    if args.allow_live_website:
        phases.append(
            _phase(
                "website/public verification of persisted product/offer/history shape",
                mode="live" if args.website_url else "skipped",
                status="blocked" if not args.website_url else "skipped",
                blockers=["WEBSITE_PUBLIC_URL or --website-url is required with --allow-live-website"] if not args.website_url else [],
                warnings=[
                    "Live website verification is not implemented/invoked by this orchestrator; URL presence is not live verification."
                ],
                details={
                    "website_url_present": bool(args.website_url),
                    "live_website_verification_invoked": False,
                    "verification_scope": "not_implemented_not_live_verified",
                },
            )
        )
        public_shape = None
    elif candidate is not None and db_result is not None:
        public_shapes = [_verify_public_shape(row, db_result) for row in candidates]
        public_shape = public_shapes[0] if public_shapes else None
        if public_shape is not None:
            public_shape["all_shapes_ok"] = all(shape["shape_ok"] for shape in public_shapes)
            public_shape["retained_shape_count"] = len(public_shapes)
        phases.append(
            _phase(
                "website/public verification of persisted product/offer/history shape",
                mode="fixture",
                status="passed" if public_shape and public_shape["all_shapes_ok"] else "blocked",
                counts={
                    "products": len(public_shapes),
                    "offers": len(public_shapes),
                    "history_points": sum(len(shape["history"]) for shape in public_shapes),
                },
                blockers=[f"missing {field}" for shape in public_shapes for field in shape["missing"]],
                details=public_shape,
            )
        )
    else:
        public_shape = None
        phases.append(
            _phase(
                "website/public verification of persisted product/offer/history shape",
                mode="skipped",
                status="skipped",
                blockers=["No persisted/fixture DB result available to verify."],
            )
        )

    failure_statuses = {"blocked", "failed"}
    overall_status = "blocked" if any(phase["status"] in failure_statuses for phase in phases) else "success"
    artifact = {
        "schema": "walletsavior.one_shot_db_build_orchestrator.v1",
        "run_id": run_id,
        "created_at": _utc_now(),
        "overall_status": overall_status,
        "result_scope": (
            "fixture_stub_dry_run"
            if not any(
                [
                    args.allow_live_crawler,
                    args.allow_live_ai_provider,
                    args.allow_live_ai_labeling,
                    args.crawler_batch_json,
                    args.allow_db_mutation,
                    args.allow_live_website,
                ]
            )
            else "mixed_explicit_live_opt_in_with_unimplemented_or_blocked_steps"
        ),
        "live_integrations_invoked": live_integrations_invoked,
        "manual_safe_defaults": {
            "consumes_ai_quota_by_default": False,
            "mutates_real_db_by_default": False,
            "live_requires_explicit_flags": True,
        },
        "command_shape": (
            "py tools\\one_shot_db_build_orchestrator.py "
            "# fixture/stub/dry-run by default; "
            f"AI smoke requires {LIVE_SMOKE_ENV}=1; "
            "real live labeling requires --crawler-batch-json plus --allow-live-ai-labeling "
            "and delegates to tools\\run_live_model_batch.py; "
            "[--allow-live-ai-provider --allow-live-ai-labeling --provider-id ...] "
            "[--allow-db-mutation to forward --allow-db-admin-submit]"
        ),
        "phases": phases,
        "counts": {
            "phases": len(phases),
            "passed": sum(1 for phase in phases if phase["status"] == "passed"),
            "blocked": sum(1 for phase in phases if phase["status"] == "blocked"),
            "failed": sum(1 for phase in phases if phase["status"] == "failed"),
            "skipped": sum(1 for phase in phases if phase["status"] == "skipped"),
        },
        "blockers": [blocker for phase in phases for blocker in phase["blockers"]],
        "warnings": warnings + [warning for phase in phases for warning in phase["warnings"]],
        "public_shape": public_shape,
        "retention": {
            "source_raw_count": len(source_items),
            "review_candidate_count": len(candidates),
            "retained_count": len(candidates),
            "dropped_count": max(len(source_items) - len(candidates), 0),
            "retain_all": len(source_items) == len(candidates),
        },
    }
    artifact_path = args.artifact_dir / f"{run_id}.json"
    artifact["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(_safe_json(artifact), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return artifact

def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    artifact = run_orchestrator(args)
    print(
        json.dumps(
            {
                "artifact_path": artifact["artifact_path"],
                "overall_status": artifact["overall_status"],
                "result_scope": artifact["result_scope"],
                "live_integrations_invoked": artifact["live_integrations_invoked"],
                "phase_modes": {phase["name"]: phase["mode"] for phase in artifact["phases"]},
                "counts": artifact["counts"],
                "blockers": artifact["blockers"],
                "warnings": artifact["warnings"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if artifact["overall_status"] == "success" else 2

if __name__ == "__main__":
    raise SystemExit(main())
