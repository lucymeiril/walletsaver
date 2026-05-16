"""Manual-only live AI validation harness v2.

This script is intentionally outside normal application startup and test
registration. It defaults to an offline fixture/dry-run path and only performs
network crawler/provider/DB-admin actions when an operator passes explicit
``--allow-*`` flags.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"
for path in (str(CRAWLER_BACKEND), str(AI_BACKEND), str(SHARED)):
    while path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from pipeline.ai_export import to_raw_record, to_raw_records_with_invalid_rows  # noqa: E402

_loaded_config = sys.modules.get("config")
if _loaded_config is not None:
    loaded_file = Path(getattr(_loaded_config, "__file__", "")).resolve()
    if AI_BACKEND not in loaded_file.parents and loaded_file != AI_BACKEND / "config.py":
        del sys.modules["config"]

from providers.secret_resolver import resolve_secret_alias  # noqa: E402
from services.ai_ingestion import (  # noqa: E402
    build_labeling_prompt,
    split_records_for_ai,
)
from services.review_publish import (  # noqa: E402
    build_raw_ai_audit,
    db_item_from_review,
    publish_blockers,
)

EVIDENCE_CLASSES = (
    "exact_catalog",
    "learned_alias",
    "deterministic_raw",
    "model_inferred",
    "new_unknown",
)
GENERALIZATION_CLASSES = {"model_inferred", "new_unknown"}
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "v2"
DEFAULT_AI_BATCH_SIZE = 20
DEFAULT_AI_BATCH_PROMPT_CHARS = 8000
DEFAULT_LABEL_TIMEOUT_SECONDS = 240.0
MAX_LABEL_TIMEOUT_SECONDS = 900.0
MAX_LIVE_AI_BATCH_SIZE = 20
MAX_LIVE_AI_BATCH_PROMPT_CHARS = 12000
MAX_LIVE_ITEMS = 300
HARD_MAX_LIVE_ITEMS = 500
LIST_PROPOSAL_FIELDS = {"keywords", "aliases"}
VALIDATION_RUN_MODES = {"stub", "fixture", "source_replay", "live", "skipped"}
_TERM_RE = re.compile(r"[0-9a-z가-힣]+", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|key|token|authorization|secret|credential)(\s*[=:]\s*)[\"']?[^\"'\s,;}]+"
)
_ENV_ASSIGNMENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}(?:API_KEY|TOKEN|SECRET|KEY|CREDENTIAL)\b\s*=\s*[^\s,;}]+")
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
DEFAULT_LABEL_CHUNK_RETRIES = 1
MAX_LABEL_CHUNK_RETRIES = 5
DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS = 12.0
MAX_LABEL_CALL_MIN_INTERVAL_SECONDS = 300.0

def configure_utf8_runtime() -> None:
    """Keep live validation prompts and JSON output UTF-8 safe on Windows."""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _fixture_items() -> list[dict[str, Any]]:
    return [
        {
            "product_id": "fixture-kimbap-kit",
            "name": "한돈으로 만든 햄꼬마김밥키트157g",
            "sale_price": "6,980원",
            "original_price": "8,980원",
            "discount_percent": 22,
            "detail_url": "https://example.invalid/emart/kimbap-kit",
            "image_url": "https://example.invalid/emart/images/kimbap-kit.jpg",
            "source": "emart-fixture",
            "category_hint": "밀키트/델리",
            "attributes": {"collection": "manual-live-validation-v2"},
            "expected_ai": {
                "canonical_name": "햄꼬마김밥키트 157g",
                "category_id": "prepared_food.meal_kit.kimbap",
                "keywords": ["꼬마김밥키트"],
                "attributes": {"collection": "manual-live-validation-v2"},
            },
            "holdout_expected_class": "new_unknown",
        },
        {
            "product_id": "fixture-shrimp",
            "name": "베트남산 냉동 새우살 300g",
            "sale_price": "7,980원",
            "original_price": "9,980원",
            "discount_percent": 20,
            "detail_url": "https://example.invalid/emart/shrimp",
            "image_url": "https://example.invalid/emart/images/shrimp.jpg",
            "source": "emart-fixture",
            "category_hint": "수산/냉동",
            "origin": "베트남",
            "storage_type": "냉동",
            "expected_ai": {
                "category_id": "seafood.frozen",
                "keywords": ["새우"],
                "attributes": {"origin": "베트남", "storage_type": "냉동"},
            },
            "holdout_expected_class": "deterministic_raw",
        },
    ]

def _rows_from_container(container: Any) -> list[Any] | None:
    if isinstance(container, list):
        return container
    if isinstance(container, dict):
        for key in ("items", "records", "raw_items", "raw_selected_items"):
            if isinstance(container.get(key), list):
                return container[key]
    return None

def _load_input_artifact(path: Path) -> tuple[list[Any], list[dict[str, Any]]]:
    """Load a raw crawler artifact, including multi-source crawler-admin bundles."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = _rows_from_container(data)
    if rows is not None:
        return rows, []
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON list or an object with items/records/raw_items/raw_selected_items/sources")

    flattened: list[Any] = []
    source_artifacts: list[dict[str, Any]] = []
    for key in ("sources", "crawlers", "runs", "batches"):
        sources = data.get(key)
        if not isinstance(sources, list):
            continue
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                flattened.append(source)
                source_artifacts.append({"index": index, "container": key, "structurally_unreadable": True})
                continue
            source_rows = _rows_from_container(source) or []
            source_name = source.get("source_name") or source.get("source") or source.get("name")
            crawler_name = source.get("crawler_name") or source.get("crawler")
            schema_type = source.get("schema_type")
            source_artifacts.append(
                {
                    "index": index,
                    "container": key,
                    "source_name": source_name,
                    "crawler_name": crawler_name,
                    "schema_type": schema_type,
                    "row_count": len(source_rows),
                    "quality_details": source.get("quality_details"),
                    "alerts": source.get("alerts"),
                    "zero_result_diagnostic": source.get("zero_result_diagnostic"),
                }
            )
            for row in source_rows:
                if isinstance(row, dict):
                    annotated = dict(row)
                    if source_name and not (annotated.get("source_name") or annotated.get("source")):
                        annotated["source_name"] = source_name
                    if crawler_name and not annotated.get("crawler_name"):
                        annotated["crawler_name"] = crawler_name
                    if schema_type and not annotated.get("schema_type"):
                        annotated["schema_type"] = schema_type
                    flattened.append(annotated)
                else:
                    flattened.append(row)
        if flattened or source_artifacts:
            return flattened, source_artifacts
    raise ValueError(f"{path} must contain a JSON list or an object with items/records/raw_items/raw_selected_items/sources")

def _load_json_list(path: Path) -> list[dict[str, Any]]:
    rows, _source_artifacts = _load_input_artifact(path)
    if not all(isinstance(item, dict) for item in rows):
        raise ValueError(f"{path} must contain JSON object rows")
    return rows

def _load_terms(path: Path | None, *keys: str) -> set[str]:
    if path is None:
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("items", [])
    terms: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                terms.add(_norm(value))
            elif isinstance(value, list):
                terms.update(_norm(v) for v in value if isinstance(v, str) and v.strip())
    return terms

def _countish(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_db_admin_acceptance_summary(
    db_admin_result: Any,
    *,
    db_admin_submit_allowed: bool,
) -> dict[str, Any]:
    """Summarize whether an explicit DB mutation run proved real public persistence."""
    if not db_admin_submit_allowed:
        return {
            "accepted": False,
            "db_admin_submit_allowed": False,
            "submit_success": False,
            "ai_safe_final_approved": 0,
            "public_db_verified": 0,
            "blocked_rows_held_for_review": True,
            "blocked_rows_audited": True,
            "rollback_re_review_evidence_or_next_action": False,
            "blockers": ["DB-admin submit was not explicitly allowed."],
        }
    if not isinstance(db_admin_result, dict) or db_admin_result.get("skipped"):
        return {
            "accepted": False,
            "db_admin_submit_allowed": True,
            "submit_success": False,
            "ai_safe_final_approved": 0,
            "public_db_verified": 0,
            "blocked_rows_held_for_review": True,
            "blocked_rows_audited": bool(isinstance(db_admin_result, dict) and db_admin_result.get("reason")),
            "rollback_re_review_evidence_or_next_action": False,
            "blockers": ["DB-admin submit/final approval was skipped or missing."],
        }

    results = db_admin_result.get("results") if isinstance(db_admin_result.get("results"), list) else []
    final_approved = _countish(db_admin_result.get("ai_safe_final_approved"))
    submitted = _countish(db_admin_result.get("submitted_to_db_admin"))
    pending = _countish(db_admin_result.get("pending_db_review"))
    final_failed = _countish(db_admin_result.get("final_approve_failed"))
    failed = _countish(db_admin_result.get("failed"))
    public_verified = (
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
    rollback_ready = (
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
    blocked_rows_present = pending > 0 or final_failed > 0 or failed > 0
    held = (not blocked_rows_present) or any(
        isinstance(row, dict)
        and (
            row.get("status") == "pending_db_review"
            or row.get("requires_db_admin_review")
            or row.get("final_approve_error")
        )
        for row in results
    )
    audited = (not blocked_rows_present) or bool(results or db_admin_result.get("safety"))
    rollback_next_action = bool(
        (final_approved and rollback_ready >= final_approved)
        or db_admin_result.get("operator_next_action")
    )

    blockers: list[str] = []
    if submitted < 1:
        blockers.append("DB-admin submit success was not confirmed.")
    if final_approved < 1:
        blockers.append("ai-safe-final-approved saved rows were not confirmed.")
    if public_verified < final_approved:
        blockers.append("Final-approved rows were not publicly verified in DB-admin response.")
    if blocked_rows_present and not held:
        blockers.append("Blocked rows were not proven held for DB-admin review.")
    if blocked_rows_present and not audited:
        blockers.append("Blocked rows were not proven audited.")
    if final_approved and not rollback_next_action:
        blockers.append("Rollback/re-review evidence or a clear next action was not present.")

    return {
        "accepted": not blockers,
        "db_admin_submit_allowed": True,
        "submit_success": submitted > 0,
        "submitted_to_db_admin": submitted,
        "ai_safe_final_approved": final_approved,
        "public_db_verified": public_verified,
        "pending_db_review": pending,
        "final_approve_failed": final_failed,
        "failed": failed,
        "blocked_rows_held_for_review": held,
        "blocked_rows_audited": audited,
        "rollback_re_review_supported": rollback_ready,
        "rollback_re_review_evidence_or_next_action": rollback_next_action,
        "blockers": blockers,
    }

def sanitize_validation_error_message(message: Any) -> str:
    """Sanitize provider/operator errors before storing validation metadata."""
    text = str(message or "").replace("\r", " ").replace("\n", " ")
    text = _GOOGLE_API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = _ENV_ASSIGNMENT_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=[REDACTED]", text)
    text = _SECRET_VALUE_RE.sub(r"\1\2[REDACTED]", text)
    return text.strip()[:1000]

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _safe_error_detail(exc: BaseException | None) -> dict[str, Any] | None:
    if exc is None:
        return None
    frames = traceback.extract_tb(exc.__traceback__)
    location = None
    if frames:
        frame = frames[-1]
        location = {
            "file": Path(frame.filename).name,
            "function": frame.name,
            "line": frame.lineno,
        }
    return {
        "class": exc.__class__.__name__,
        "message": sanitize_validation_error_message(str(exc)),
        "location": location,
    }

def _is_retryable_provider_error(error_detail: dict[str, Any] | None) -> bool:
    text = json.dumps(error_detail or {}, ensure_ascii=False, sort_keys=True).lower()
    return any(marker in text for marker in _RETRYABLE_FAILURE_MARKERS)

def _sleep_between_label_calls(
    *,
    last_call_at: float | None,
    min_interval_seconds: float,
    sleeper: Callable[[float], None],
) -> float | None:
    if last_call_at is None or min_interval_seconds <= 0:
        return None
    elapsed = time.monotonic() - last_call_at
    delay = max(0.0, min_interval_seconds - elapsed)
    if delay > 0:
        sleeper(delay)
    return delay

def build_validation_run_metadata(
    *,
    mode: str,
    provider: str | None,
    model: str | None,
    key_present: bool,
    live_opt_in: bool,
    live_call_attempted: bool = False,
    live_call_succeeded: bool = False,
    skip_reason: str | None = None,
    error: BaseException | str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    item_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the shared validation observability shape stored in artifacts/tests."""
    if mode not in VALIDATION_RUN_MODES:
        raise ValueError(f"mode must be one of {sorted(VALIDATION_RUN_MODES)}")
    error_detail = None
    if isinstance(error, BaseException):
        error_detail = _safe_error_detail(error)
    elif error is not None:
        error_detail = {"class": "Error", "message": sanitize_validation_error_message(error)}
    return {
        "mode": mode,
        "provider": provider,
        "model": model,
        "key_present": bool(key_present),
        "live_opt_in": bool(live_opt_in),
        "live_call_attempted": bool(live_call_attempted),
        "live_call_succeeded": bool(live_call_succeeded),
        "skip_reason": skip_reason,
        "error": error_detail,
        "started_at": started_at or _utc_now(),
        "finished_at": finished_at,
        "item_counts": item_counts or {},
    }


def infer_default_validation_mode(args: argparse.Namespace) -> str:
    """Label dry-runs from source artifacts separately from built-in fixtures."""
    if args.allow_live_provider:
        return "live"
    if getattr(args, "input_json", None) or (
        getattr(args, "allow_live_crawl", False) and getattr(args, "live_crawler", None)
    ):
        return "source_replay"
    return "fixture"

def finish_validation_run_metadata(
    metadata: dict[str, Any],
    *,
    live_call_attempted: bool | None = None,
    live_call_succeeded: bool | None = None,
    skip_reason: str | None = None,
    error: BaseException | str | None = None,
    item_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize a validation metadata object without exposing secrets."""
    updated = dict(metadata)
    if live_call_attempted is not None:
        updated["live_call_attempted"] = bool(live_call_attempted)
    if live_call_succeeded is not None:
        updated["live_call_succeeded"] = bool(live_call_succeeded)
    if skip_reason is not None:
        updated["skip_reason"] = skip_reason
    if error is not None:
        if isinstance(error, BaseException):
            updated["error"] = _safe_error_detail(error)
        else:
            updated["error"] = {"class": "Error", "message": sanitize_validation_error_message(error)}
    if item_counts is not None:
        updated["item_counts"] = item_counts
    updated["finished_at"] = _utc_now()
    return updated

def _norm(value: Any) -> str:
    return "".join(str(value).lower().split())

def _norm_tokens(value: Any) -> set[str]:
    return {_norm(token) for token in _TERM_RE.findall(str(value or "")) if _norm(token)}

def _term_matches_text(term: str, text: Any) -> bool:
    term_norm = _norm(term)
    if not term_norm:
        return False
    text_norm = _norm(text)
    return term_norm == text_norm or term_norm in _norm_tokens(text)

def _term_matches_provider_list(term: str, values: Any) -> bool:
    if not isinstance(values, list):
        return False
    term_norm = _norm(term)
    return any(term_norm == _norm(value) for value in values if isinstance(value, str))

def _dedupe_list(values: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped

def _matches_any_term(
    terms: set[str] | None,
    item: dict[str, Any],
    provider_item: dict[str, Any] | None,
) -> bool:
    if not terms:
        return False
    text_fields = [item.get(key) for key in ("name", "title", "raw_title", "product_name")]
    provider_text_fields = [provider_item.get("canonical_name")] if provider_item else []
    for term in terms:
        if any(_term_matches_text(term, field) for field in [*text_fields, *provider_text_fields] if field):
            return True
        if provider_item and any(
            _term_matches_provider_list(term, provider_item.get(key))
            for key in LIST_PROPOSAL_FIELDS
        ):
            return True
    return False

def classify_evidence(
    item: dict[str, Any],
    provider_item: dict[str, Any] | None = None,
    *,
    catalog_terms: set[str] | None = None,
    learned_terms: set[str] | None = None,
) -> dict[str, Any]:
    """Classify whether a result is catalog/learned reuse or true holdout work."""
    expected = item.get("holdout_expected_class")
    if isinstance(expected, str) and expected in EVIDENCE_CLASSES:
        evidence_class = expected
        reason = "operator-provided holdout_expected_class"
    else:
        if _matches_any_term(catalog_terms, item, provider_item):
            evidence_class = "exact_catalog"
            reason = "matched configured catalog term as a token/exact provider value"
        elif _matches_any_term(learned_terms, item, provider_item):
            evidence_class = "learned_alias"
            reason = "matched configured learned alias as a token/exact provider value"
        elif any(item.get(key) not in (None, "") for key in ("unit", "quantity", "origin", "storage_type")):
            evidence_class = "deterministic_raw"
            reason = "raw item contains deterministic structured signals"
        elif provider_item:
            evidence_class = "model_inferred"
            reason = "provider output needed without catalog/learned/deterministic match"
        else:
            evidence_class = "new_unknown"
            reason = "no provider output and no catalog/learned/deterministic match"
    trust_labels = {
        "exact_catalog": "reuse_exact_catalog",
        "learned_alias": "reuse_learned_alias",
        "deterministic_raw": "deterministic_structured",
        "model_inferred": "provider_inferred_holdout",
        "new_unknown": "unresolved_new_product_holdout",
    }
    return {
        "evidence_class": evidence_class,
        "trust_label": trust_labels[evidence_class],
        "reason": reason,
        "counts_as_generalization": evidence_class in GENERALIZATION_CLASSES,
    }

def evaluate_holdout_generalization(
    records: list[Any],
    provider_items: dict[str, dict[str, Any]],
    *,
    catalog_terms: set[str] | None = None,
    learned_terms: set[str] | None = None,
) -> dict[str, Any]:
    evidence = [
        {
            "raw_record_id": record.raw_record_id,
            "raw_title": record.raw_title,
            **classify_evidence(
                record.raw_payload,
                provider_items.get(record.raw_record_id),
                catalog_terms=catalog_terms,
                learned_terms=learned_terms,
            ),
        }
        for record in records
    ]
    evidence_counts = Counter(item["evidence_class"] for item in evidence)
    return {
        "evidence": evidence,
        "counts": dict(evidence_counts),
        "generalization_success_count": sum(
            1 for item in evidence if item["counts_as_generalization"]
        ),
        "rule": "exact_catalog and learned_alias are reuse, never generalization success",
        "todo_hooks": [
            "Load production catalog/learned exports via --catalog-json and --learned-json.",
        ],
    }

def provider_items_from_proposals(proposals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rebuild per-record provider outputs from stored field proposals."""
    items: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        provenance = proposal.get("provenance") or {}
        raw_record_id = provenance.get("raw_record_id")
        target_field = proposal.get("target_field")
        if not isinstance(raw_record_id, str) or not isinstance(target_field, str):
            continue

        item = items.setdefault(raw_record_id, {"raw_record_id": raw_record_id})
        proposed_value = proposal.get("proposed_value")
        if target_field.startswith("attributes."):
            attr_name = target_field.split(".", 1)[1]
            item.setdefault("attributes", {})[attr_name] = proposed_value
        elif target_field in LIST_PROPOSAL_FIELDS:
            values = item.setdefault(target_field, [])
            if isinstance(proposed_value, list):
                values.extend(value for value in proposed_value if value not in values)
            elif proposed_value not in values:
                values.append(proposed_value)
        elif target_field not in item:
            item[target_field] = proposed_value
    return items

def build_quality_batch_validation_summary(
    *,
    args: argparse.Namespace,
    total_input_count: int,
    selected_count: int,
    retained_count: int,
    invalid_rows: list[dict[str, Any]],
    split_batch_count: int,
    provider_summary: dict[str, Any],
    validation_metadata: dict[str, Any],
    raw_vs_final: list[dict[str, Any]],
    audit_issues: dict[str, Any],
    publish_blockers: dict[str, Any],
    retention_anomalies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Operator-facing bounded-batch quality summary for live item repetitions."""
    issues_by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in audit_issues.get("issues", []) if isinstance(audit_issues, dict) else []:
        if isinstance(issue, dict):
            issues_by_raw[str(issue.get("raw_record_id"))].append(issue)
    blockers_by_raw: dict[str, list[str]] = defaultdict(list)
    for row in publish_blockers.get("items", []) if isinstance(publish_blockers, dict) else []:
        if isinstance(row, dict):
            blockers_by_raw[str(row.get("raw_record_id"))].extend(str(blocker) for blocker in row.get("blockers") or [])

    row_anomalies = [
        _quality_row_anomalies(
            row,
            issues_by_raw.get(str(row.get("raw_record_id")), []),
            blockers_by_raw.get(str(row.get("raw_record_id")), []),
            provider_called=bool(provider_summary.get("called")),
        )
        for row in raw_vs_final
    ]
    category_counts = {
        field: sum(1 for row in row_anomalies if row[field])
        for field in ("category", "keyword", "unit", "source", "price", "image")
    }
    category_counts["package"] = sum(
        1
        for row in row_anomalies
        if any(
            "package" in str(reason).lower() or "display_unit" in str(reason).lower()
            for reason in [*(row.get("unit") or []), *(row.get("blockers") or [])]
        )
    )
    category_counts["source_owned_overwrite_risk"] = sum(
        1 for row in row_anomalies if row.get("source_owned_overwrite_risk")
    )
    provider_attempts = provider_summary.get("provider_calls")
    if provider_attempts is None:
        provider_attempts = 0 if not provider_summary.get("called") else None
    missing_label_count = int(provider_summary.get("missing_label_count") or 0)
    partial_review_required = (
        provider_summary.get("status") == "partial_review_required"
        or missing_label_count > 0
    )
    retention_anomalies = retention_anomalies or []
    input_anomaly_buckets = Counter(str(row.get("bucket") or "unknown") for row in retention_anomalies)
    return {
        "purpose": "bounded_quality_repetition_not_full_all_source_one_shot",
        "mode": validation_metadata.get("mode"),
        "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
        "input_count": total_input_count,
        "selected_count": selected_count,
        "retained_count": retained_count,
        "invalid_row_count": len(invalid_rows),
        "input_retention_valid": selected_count == retained_count + len(invalid_rows),
        "retention_anomaly_count": len(retention_anomalies),
        "input_anomaly_buckets": dict(input_anomaly_buckets),
        "per_row_input_anomalies": retention_anomalies,
        "max_items": args.max_items,
        "ai_batch_size": args.ai_batch_size,
        "ai_batch_prompt_chars": args.ai_batch_prompt_chars,
        "split_batch_count": split_batch_count,
        "max_provider_calls": args.max_provider_calls,
        "provider": {
            "called": bool(provider_summary.get("called")),
            "mode": provider_summary.get("provider_mode"),
            "provider_id": provider_summary.get("provider_id"),
            "model": provider_summary.get("model"),
            "ai_batches": provider_summary.get("ai_batches"),
            "call_attempts": provider_attempts,
            "http_label_calls": provider_summary.get("http_label_calls"),
            "chunk_count": provider_summary.get("chunk_count"),
            "successful_chunk_count": provider_summary.get("successful_chunk_count"),
            "failed_chunk_count": provider_summary.get("failed_chunk_count"),
            "partial_results": bool(provider_summary.get("partial_results")),
            "proposals_stored": provider_summary.get("proposals_stored"),
            "keyword_proposals_stored": provider_summary.get("keyword_proposals_stored"),
        },
        "label_chunks": provider_summary.get("chunks") or [],
        "retryable_provider_failures": provider_summary.get("retryable_failures") or [],
        "missing_label_retry": {
            "status": provider_summary.get("status") or ("not_called" if not provider_summary.get("called") else "unknown"),
            "partial_review_required": partial_review_required,
            "missing_label_count": missing_label_count,
            "missing_label_raw_record_ids": provider_summary.get("missing_label_raw_record_ids") or [],
            "retry_batches_configured": 2,
        },
        "reviewer_retry_candidates": build_reviewer_retry_candidates(
            row_anomalies,
            raw_vs_final,
            missing_label_raw_record_ids=provider_summary.get("missing_label_raw_record_ids") or [],
        ),
        "anomaly_counts": category_counts,
        "rows_with_any_anomaly": sum(1 for row in row_anomalies if row["has_any_anomaly"]),
        "per_row_anomalies": row_anomalies,
        "quality_gate": build_quality_gate_summary(
            args=args,
            total_input_count=total_input_count,
            selected_count=selected_count,
            retained_count=retained_count,
            invalid_rows=invalid_rows,
            retention_anomalies=retention_anomalies,
            anomaly_counts=category_counts,
            provider_summary=provider_summary,
            row_anomalies=row_anomalies,
        ),
        "honesty_notes": [
            "This validates only the bounded selected rows, not a full all-source one-shot build.",
            "DB-admin mutation is disabled unless --allow-db-admin-submit is explicit.",
        ],
    }

def build_quality_gate_summary(
    *,
    args: argparse.Namespace,
    total_input_count: int,
    selected_count: int,
    retained_count: int,
    invalid_rows: list[dict[str, Any]],
    retention_anomalies: list[dict[str, Any]],
    anomaly_counts: dict[str, int],
    provider_summary: dict[str, Any],
    row_anomalies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make scale/quality claims explicit so bounded runs cannot overclaim."""
    blockers: list[str] = []
    warnings: list[str] = []
    retain_all = bool(getattr(args, "retain_all_input", False))
    sample_only = selected_count < total_input_count
    full_input_attempted = retain_all and selected_count == total_input_count
    if sample_only:
        blockers.append(
            f"Only {selected_count} of {total_input_count} input rows were selected; this is a bounded sample, not a full-source quality pass."
        )
    if selected_count != retained_count + len(invalid_rows):
        blockers.append("Input retention accounting does not balance retained rows plus invalid rows.")
    if invalid_rows:
        blockers.append(f"{len(invalid_rows)} structurally unreadable rows were not retained for validation.")
    if retention_anomalies:
        warnings.append(
            f"{len(retention_anomalies)} retained input anomalies require review before publication."
        )

    missing_label_count = int(provider_summary.get("missing_label_count") or 0)
    failed_chunk_count = int(provider_summary.get("failed_chunk_count") or 0)
    if missing_label_count:
        blockers.append(f"{missing_label_count} rows are missing provider labels after configured attempts.")
    if failed_chunk_count:
        blockers.append(f"{failed_chunk_count} provider label chunks failed or were only partially validated.")
    if provider_summary.get("partial_results") or provider_summary.get("partial_review_required"):
        blockers.append("Provider reported partial results/review-required status.")
    provider_validation = provider_summary.get("provider_response_validation") or {}
    invalid_provider_rows = int(provider_validation.get("invalid_response_row_count") or 0)
    if invalid_provider_rows:
        blockers.append(f"{invalid_provider_rows} provider response rows could not be mapped back to source records.")
    if not provider_summary.get("called"):
        blockers.append("Provider labeling was skipped; AI taxonomy/keyword quality was not evaluated.")

    if anomaly_counts.get("category"):
        blockers.append(f"{anomaly_counts['category']} rows have category/taxonomy anomalies.")
    if anomaly_counts.get("package"):
        blockers.append(f"{anomaly_counts['package']} rows have package/display-unit anomalies.")
    source_owned_risks = [
        {
            "raw_record_id": row.get("raw_record_id"),
            "raw_title": row.get("raw_title"),
            "risks": row.get("source_owned_overwrite_risk"),
        }
        for row in row_anomalies
        if row.get("source_owned_overwrite_risk")
    ]
    if source_owned_risks:
        blockers.append(
            f"{len(source_owned_risks)} rows changed source-owned evidence fields between raw and final output."
        )

    return {
        "accepted": not blockers,
        "full_input_attempted": full_input_attempted,
        "sample_only": sample_only,
        "claim_scope": "full_input" if full_input_attempted else "bounded_sample",
        "scale_claim": (
            "full_input_quality_candidate"
            if full_input_attempted and not blockers
            else "blocked_not_full_source_quality"
        ),
        "blockers": blockers,
        "warnings": warnings,
        "source_owned_overwrite_risks": source_owned_risks,
    }

def build_reviewer_retry_candidates(
    row_anomalies: list[dict[str, Any]],
    raw_vs_final: list[dict[str, Any]],
    *,
    missing_label_raw_record_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Group deterministic quality failures for a future reviewer-AI retry pass."""
    raw_by_id = {str(row.get("raw_record_id")): row for row in raw_vs_final if row.get("raw_record_id")}
    missing_label_ids = {str(raw_id) for raw_id in (missing_label_raw_record_ids or [])}
    groups = {
        "missing_label": {
            "prompt_category": "full_record_label_retry",
            "reason_tokens": ("provider returned no usable item for this row",),
            "items": [],
        },
        "category": {
            "prompt_category": "taxonomy_classification_retry",
            "reason_tokens": ("category", "taxonomy"),
            "items": [],
        },
        "unit": {
            "prompt_category": "unit_normalization_retry",
            "reason_tokens": ("unit", "standard_unit", "100g"),
            "items": [],
        },
        "package": {
            "prompt_category": "package_quantity_unit_retry",
            "reason_tokens": ("package", "display_unit"),
            "items": [],
        },
        "source": {
            "prompt_category": "source_evidence_retry",
            "reason_tokens": ("source", "source_url"),
            "items": [],
        },
        "price": {
            "prompt_category": "price_evidence_retry",
            "reason_tokens": ("price", "discount", "hotdeal", "claim"),
            "items": [],
        },
    }

    for anomaly in row_anomalies:
        raw_id = str(anomaly.get("raw_record_id") or "")
        if not raw_id:
            continue
        raw_row = raw_by_id.get(raw_id, {})
        blockers = [str(blocker) for blocker in anomaly.get("blockers") or []]
        if raw_id in missing_label_ids:
            groups["missing_label"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, ["missing_label_after_configured_retries"], groups["missing_label"]["prompt_category"])
            )
        if anomaly.get("category"):
            groups["category"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, anomaly["category"], groups["category"]["prompt_category"])
            )
        unit_reasons = [str(reason) for reason in anomaly.get("unit") or []]
        if unit_reasons:
            groups["unit"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, unit_reasons, groups["unit"]["prompt_category"])
            )
        package_reasons = [
            reason
            for reason in unit_reasons + blockers
            if "package" in reason.lower() or "display_unit" in reason.lower()
        ]
        if package_reasons:
            groups["package"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, package_reasons, groups["package"]["prompt_category"])
            )
        source_reasons = [
            reason
            for reason in blockers
            if "source" in reason.lower()
        ]
        if raw_row.get("final_source_url") in (None, ""):
            source_reasons.append("missing_final_source_url")
        if source_reasons:
            groups["source"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, source_reasons, groups["source"]["prompt_category"])
            )
        if anomaly.get("price"):
            groups["price"]["items"].append(
                _reviewer_retry_item(raw_id, anomaly, anomaly["price"], groups["price"]["prompt_category"])
            )

    output_groups = []
    for missing_field, group in groups.items():
        items = _dedupe_retry_items(group["items"])
        if not items:
            continue
        output_groups.append(
            {
                "missing_field": missing_field,
                "prompt_category": group["prompt_category"],
                "row_count": len(items),
                "raw_record_ids": [item["raw_record_id"] for item in items],
                "items": items,
            }
        )
    return {
        "purpose": "one_more_targeted_reviewer_retry_before_human_admin",
        "source": "deterministic_quality_batch_validation_no_live_reviewer_ai",
        "candidate_count": len({raw_id for group in output_groups for raw_id in group["raw_record_ids"]}),
        "group_count": len(output_groups),
        "groups": output_groups,
        "human_admin_fallback": (
            "Rows still failing after the future reviewer retry remain in DB-admin/manual review; "
            "eligible rows can continue through publish gates."
        ),
    }

def _reviewer_retry_item(
    raw_id: str,
    anomaly: dict[str, Any],
    reasons: list[Any],
    prompt_category: str,
) -> dict[str, Any]:
    return {
        "raw_record_id": raw_id,
        "raw_title": anomaly.get("raw_title"),
        "publication_kind": anomaly.get("publication_kind"),
        "reasons": _dedupe_list([str(reason) for reason in reasons if str(reason)]),
        "recommended_retry_prompt_category": prompt_category,
    }

def _dedupe_retry_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        raw_id = item["raw_record_id"]
        if raw_id not in merged:
            merged[raw_id] = item
            continue
        merged[raw_id]["reasons"] = _dedupe_list(merged[raw_id]["reasons"] + item["reasons"])
    return list(merged.values())

def _quality_row_anomalies(
    row: dict[str, Any],
    issues: list[dict[str, Any]],
    blockers: list[str],
    *,
    provider_called: bool = True,
) -> dict[str, Any]:
    issue_codes = {str(issue.get("code")) for issue in issues if isinstance(issue, dict)}
    blocker_text = " | ".join(blockers)

    def issue_or_blocker(tokens: set[str]) -> list[str]:
        values = [code for code in sorted(issue_codes) if any(token in code for token in tokens)]
        values.extend(blocker for blocker in blockers if any(token in blocker.lower() for token in tokens))
        return _dedupe_list(values)

    category = issue_or_blocker({"category", "taxonomy"})
    if row.get("raw_category_id") and row.get("final_category_id") and row.get("raw_category_id") != row.get("final_category_id"):
        category.append("category_changed_raw_vs_final")
    if (provider_called or row.get("raw_category_id")) and not row.get("final_category_id"):
        category.append("missing_final_category_id")

    keyword = issue_or_blocker({"keyword", "alias"})
    if row.get("raw_keywords") and row.get("final_keywords") and row.get("raw_keywords") != row.get("final_keywords"):
        keyword.append("keywords_changed_raw_vs_final")
    if (provider_called or row.get("raw_keywords")) and not row.get("final_keywords"):
        keyword.append("missing_final_keywords")

    unit = issue_or_blocker({"unit", "package", "standard_unit", "100g"})
    source = issue_or_blocker({"source"})
    if row.get("final_source_url") in (None, ""):
        source.append("missing_final_source_url")
    price = issue_or_blocker({"price", "discount", "hotdeal", "claim", "period"})
    if row.get("raw_price") in (None, ""):
        price.append("missing_raw_price")
    if row.get("final_sale_price") in (None, ""):
        price.append("missing_final_sale_price")
    if (
        row.get("raw_price") not in (None, "")
        and row.get("final_sale_price") not in (None, "")
        and row.get("raw_price") != row.get("final_sale_price")
    ):
        price.append("price_changed_raw_vs_final")

    image = issue_or_blocker({"image"})
    if row.get("raw_image_url") in (None, ""):
        image.append("missing_raw_image_url")
    if row.get("publication_kind") == "hotdeal" and row.get("final_image_url") in (None, ""):
        image.append("missing_hotdeal_final_image_url")
    if "image_url" in blocker_text and not image:
        image.append("image_blocker_present")
    source_owned_overwrite_risk = _source_owned_overwrite_risks(row)

    anomaly = {
        "raw_record_id": row.get("raw_record_id"),
        "raw_title": row.get("raw_title"),
        "publication_kind": row.get("publication_kind"),
        "category": _dedupe_list(category),
        "keyword": _dedupe_list(keyword),
        "unit": _dedupe_list(unit),
        "source": _dedupe_list(source),
        "price": _dedupe_list(price),
        "image": _dedupe_list(image),
        "source_owned_overwrite_risk": source_owned_overwrite_risk,
        "blockers": blockers,
        "audit_issue_codes": sorted(issue_codes),
    }
    anomaly["has_any_anomaly"] = any(
        anomaly[field]
        for field in ("category", "keyword", "unit", "source", "price", "image", "source_owned_overwrite_risk")
    )
    return anomaly

def _source_owned_overwrite_risks(row: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    for raw_field, final_field, label in (
        ("raw_price", "final_sale_price", "sale_price"),
        ("raw_original_price", "final_original_price", "original_price"),
        ("raw_discount_percent", "final_discount_percent", "discount_percent"),
        ("raw_source_url", "final_source_url", "source_url"),
        ("raw_image_url", "final_image_url", "image_url"),
    ):
        raw_value = row.get(raw_field)
        final_value = row.get(final_field)
        if raw_value in (None, "") or final_value in (None, ""):
            continue
        if _norm_compare_value(raw_value) != _norm_compare_value(final_value):
            risks.append(f"source_owned_{label}_changed_raw_vs_final")
    return risks

def _norm_compare_value(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return _norm(value)

async def _run_live_crawler(crawler_name: str, max_pages: int, max_items: int, max_requests: int) -> dict[str, Any]:
    from crawlers.registry.registry import CrawlerRegistry

    registry = CrawlerRegistry()
    registry.discover()
    crawler = registry.get_crawler(crawler_name)
    if hasattr(crawler, "MAX_PAGES"):
        setattr(crawler, "MAX_PAGES", max(1, max_pages))
    if hasattr(crawler, "MAX_ITEMS"):
        setattr(crawler, "MAX_ITEMS", max(1, max_items))
    if hasattr(crawler, "MAX_REQUESTS"):
        setattr(crawler, "MAX_REQUESTS", max(1, max_requests))
    if hasattr(crawler, "SEARCH_QUERIES"):
        query_cap = min(max(1, max_pages), max(1, max_requests))
        setattr(crawler, "SEARCH_QUERIES", list(getattr(crawler, "SEARCH_QUERIES"))[:query_cap])
    result = await crawler.crawl()
    items = list(getattr(result, "items", []) or [])[:max_items]
    quality_details = getattr(result, "quality_details", {}) or {}
    return {
        "crawler_name": crawler_name,
        "status": str(getattr(result, "status", "")),
        "strategy_used": getattr(result, "strategy_used", None),
        "items_count": len(items),
        "crawler_items_count": getattr(result, "items_count", len(items)),
        "errors": _jsonable(getattr(result, "errors", None)),
        "error_msg": getattr(result, "error_msg", None),
        "quality_score": getattr(result, "quality_score", None),
        "quality_details": _jsonable(quality_details),
        "alerts": list(quality_details.get("alerts", [])),
        "zero_result_diagnostic": quality_details.get("zero_result_diagnostic"),
        "run_limits": {
            "max_items": max_items,
            "max_pages": max_pages,
            "max_requests": max_requests,
        },
        "items": items,
    }

def _http_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if api_key:
        headers["X-API-Key"] = api_key
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(text) if text else {}
        except json.JSONDecodeError:
            detail = {"detail": text}
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc

def _record_payload(record: Any) -> dict[str, Any]:
    return record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)

def _item_source_name(item: dict[str, Any], fallback: str) -> str:
    for key in ("source_name", "source", "marketplace", "store"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback

def _build_quality_raw_records(
    items: list[Any],
    *,
    fallback_source_name: str,
    batch_id: str,
) -> tuple[list[Any], int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert crawler rows for validation while retaining readable ambiguous rows."""
    records: list[Any] = []
    invalid_rows: list[dict[str, Any]] = []
    retention_anomalies: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            invalid_rows.append(
                {
                    "index": index,
                    "reason": "item must be an object",
                    "bucket": "structurally_unreadable",
                    "retained": False,
                }
            )
            continue
        source_name = _item_source_name(item, fallback_source_name)
        record = to_raw_record(
            item,
            source_name=source_name,
            index=index,
            batch_id=batch_id,
        )
        if record is None:
            placeholder_item = dict(item)
            placeholder_title = f"[missing product name/title row {index}]"
            placeholder_item["raw_title"] = placeholder_title
            record = to_raw_record(
                placeholder_item,
                source_name=source_name,
                index=index,
                batch_id=batch_id,
            )
            if record is None:
                invalid_rows.append(
                    {
                        "index": index,
                        "reason": "missing product name/title",
                        "bucket": "raw_record_mapping_failed",
                        "retained": False,
                    }
                )
                continue
            if hasattr(record, "model_copy"):
                record = record.model_copy(update={"raw_payload": dict(item)})
            retention_anomalies.append(
                {
                    "index": index,
                    "raw_record_id": record.raw_record_id,
                    "bucket": "missing_product_name_title",
                    "reason": "missing product name/title retained with placeholder title",
                    "retained": True,
                }
            )
        if record.raw_price is None and not any(
            anomaly.get("raw_record_id") == record.raw_record_id and anomaly.get("bucket") == "missing_or_unparseable_price"
            for anomaly in retention_anomalies
        ):
            retention_anomalies.append(
                {
                    "index": index,
                    "raw_record_id": record.raw_record_id,
                    "bucket": "missing_or_unparseable_price",
                    "reason": "price missing or not parseable; row retained for AI/review",
                    "retained": True,
                }
            )
        raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        if not (raw_payload.get("image_url") or raw_payload.get("image")):
            retention_anomalies.append(
                {
                    "index": index,
                    "raw_record_id": record.raw_record_id,
                    "bucket": "missing_image",
                    "reason": "image is absent; row retained for quality anomaly reporting",
                    "retained": True,
                }
            )
        records.append(record)
    return records, len(invalid_rows), invalid_rows, retention_anomalies

def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

def _build_source_diagnostics(
    *,
    live_crawl: dict[str, Any] | None,
    selected_count: int,
    records_count: int,
    skipped_count: int,
    invalid_rows: list[dict[str, Any]],
    retention_anomalies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    alerts: list[str] = []
    diagnostics: list[dict[str, Any]] = []

    if live_crawl:
        alerts.extend(live_crawl.get("alerts", []))
        zero_diag = live_crawl.get("zero_result_diagnostic")
        if zero_diag:
            diagnostics.append({"scope": "crawler", **zero_diag})
        if selected_count == 0:
            alerts.append("harness_zero_selected_items")
            diagnostics.append({
                "scope": "harness_source_selection",
                "stage": "crawler_returned_zero_selected_items",
                "message": (
                    "Live crawler yielded zero selected items for the harness. Inspect crawler "
                    "quality_details.zero_result_diagnostic, errors, network/source-block signals, and selectors."
                ),
                "operator_action": "Fix crawler/source diagnostics before running provider or DB-admin validation.",
                "counts": {
                    "crawler_items": live_crawl.get("crawler_items_count"),
                    "selected_items": selected_count,
                    "records": records_count,
                },
            })

    if selected_count > 0 and records_count == 0:
        stage = "raw_records_validation_rejected_all_rows" if invalid_rows else "raw_records_filtered_all_rows"
        alerts.append(stage)
        diagnostics.append({
            "scope": "harness_raw_ingestion",
            "stage": stage,
            "message": (
                "Crawler/input rows were selected, but no raw AI records were produced. "
                "Check raw-record required fields, schema mapping, skipped rows, and invalid_rows."
            ),
            "operator_action": "Inspect source.invalid_rows and raw_selected_items before enabling provider/DB submit.",
            "counts": {
                "selected_items": selected_count,
                "records": records_count,
                "skipped": skipped_count,
                "invalid_rows": len(invalid_rows),
            },
        })

    if records_count == 0 and not diagnostics:
        alerts.append("harness_zero_records")
        diagnostics.append({
            "scope": "harness_raw_ingestion",
            "stage": "zero_records_no_stage_detail",
            "message": "No raw records were produced; inspect selected item count and invalid rows.",
            "operator_action": "Do not treat this artifact as a successful live validation until records exist.",
            "counts": {
                "selected_items": selected_count,
                "records": records_count,
                "skipped": skipped_count,
                "invalid_rows": len(invalid_rows),
            },
        })

    if retention_anomalies:
        alerts.append("crawler_rows_retained_with_anomalies")
        buckets = Counter(str(row.get("bucket") or "unknown") for row in retention_anomalies)
        diagnostics.append({
            "scope": "harness_quality_retention",
            "stage": "readable_rows_retained_with_anomaly_buckets",
            "message": (
                "Readable crawler rows with missing/ambiguous fields were retained for AI "
                "classification/review instead of being filtered out."
            ),
            "operator_action": "Inspect quality_batch_validation.input_anomaly_buckets before publishing.",
            "counts": {
                "retained_anomaly_rows": len({row.get("raw_record_id") for row in retention_anomalies if row.get("raw_record_id")}),
                "retention_anomalies": len(retention_anomalies),
                "buckets": dict(buckets),
            },
        })

    return {
        "alerts": list(dict.fromkeys(alerts)),
        "diagnostics": diagnostics,
    }

def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED_ALIAS_VALUE]" if "key" in key.lower() or "token" in key.lower() else _redact(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value

def build_db_admin_submit_plan(publish_items: list[Any]) -> dict[str, Any]:
    """Select only rows safe for the one-shot submit + ai-safe-final-approve path."""
    rows = [item for item in publish_items if isinstance(item, dict)]
    safe_rows: list[dict[str, Any]] = []
    held_rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    for row in rows:
        raw_id = row.get("raw_record_id")
        if row.get("ai_safe_final_approve_eligible") is True:
            safe_rows.append(row)
            continue

        reasons: list[str] = []
        if not row.get("eligible"):
            reasons.extend(str(blocker) for blocker in row.get("blockers") or ["not publish eligible"])
        elif row.get("post_publish_audit_flags"):
            reasons.append("post_publish_audit_flags")
        elif row.get("blocking_audit_issues"):
            reasons.append("blocking_audit_issues")
        else:
            reasons.append("eligible_but_not_ai_safe_final_approve")
        for reason in reasons:
            reason_counts[reason] += 1
        held_rows.append(
            {
                "raw_record_id": raw_id,
                "status": row.get("status"),
                "eligible": row.get("eligible"),
                "ai_safe_final_approve_eligible": row.get("ai_safe_final_approve_eligible"),
                "db_handoff_mode": row.get("db_handoff_mode"),
                "publication_kind": row.get("publication_kind"),
                "discount_claim_status": row.get("discount_claim_status"),
                "reasons": _dedupe_list(reasons),
            }
        )

    safe_ids = [str(row["raw_record_id"]) for row in safe_rows if row.get("raw_record_id")]
    return {
        "mode": "ai_safe_final_approve_only",
        "submit_allowed_rows": len(safe_ids),
        "raw_record_ids": safe_ids,
        "confirm_count": len(safe_ids),
        "held_for_review_count": len(held_rows),
        "held_for_review_rows": held_rows[:100],
        "held_reason_counts": dict(sorted(reason_counts.items())),
        "eligible_but_not_final_safe_count": sum(
            1
            for row in rows
            if row.get("eligible") and row.get("ai_safe_final_approve_eligible") is not True
        ),
        "operator_safety_rule": (
            "Only rows marked ai_safe_final_approve_eligible are submitted; eligible rows "
            "with keyword/category/unit/audit caveats stay held for DB-admin/manual review."
        ),
    }

def effective_live_items_cap(args: argparse.Namespace) -> int:
    cap = int(getattr(args, "max_live_items_cap", MAX_LIVE_ITEMS))
    allow_large = bool(getattr(args, "allow_large_live_batch", False))
    if cap < 1:
        raise ValueError("--max-live-items-cap must be >= 1")
    if cap > HARD_MAX_LIVE_ITEMS:
        raise ValueError(f"--max-live-items-cap must be <= {HARD_MAX_LIVE_ITEMS}")
    if cap > MAX_LIVE_ITEMS and not allow_large:
        raise ValueError(
            f"--max-live-items-cap above {MAX_LIVE_ITEMS} requires --allow-large-live-batch"
        )
    return cap


def _assert_live_item_count_within_cap(count: int, cap: int) -> None:
    if count > cap:
        raise ValueError(
            f"selected live item count {count} exceeds cap {cap}; "
            f"pass --allow-large-live-batch with --max-live-items-cap up to {HARD_MAX_LIVE_ITEMS} "
            "only for deliberate bounded live validation"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manual-only WalletSavior live AI validation harness v2. Defaults to dry-run/no-provider.",
    )
    parser.add_argument("--input-json", type=Path, help="Offline raw item JSON file. Defaults to built-in fixture.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--source-name", default="manual-live-validation-v2")
    parser.add_argument("--crawler-name", default="manual-live-validation-v2")
    parser.add_argument("--schema-type", default="mart_discount")
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument(
        "--retain-all-input",
        action="store_true",
        help="Validate every readable row from --input-json instead of sampling --max-items.",
    )
    parser.add_argument(
        "--allow-large-live-batch",
        action="store_true",
        help=f"Permit --max-live-items-cap above the default {MAX_LIVE_ITEMS}; still hard-capped.",
    )
    parser.add_argument(
        "--max-live-items-cap",
        type=int,
        default=MAX_LIVE_ITEMS,
        help=f"Maximum selected rows allowed in one live validation run; default {MAX_LIVE_ITEMS}, hard cap {HARD_MAX_LIVE_ITEMS}.",
    )
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-crawler-requests", type=int, default=1)
    parser.add_argument("--max-provider-calls", type=int, default=1)
    parser.add_argument(
        "--ai-batch-size",
        type=int,
        default=DEFAULT_AI_BATCH_SIZE,
        help="Target records per provider prompt for live validation; bounded by prompt chars and capped at 20.",
    )
    parser.add_argument(
        "--ai-batch-prompt-chars",
        type=int,
        default=DEFAULT_AI_BATCH_PROMPT_CHARS,
        help="Provider prompt character budget per AI batch; capped at 12000.",
    )
    parser.add_argument("--allow-live-crawl", action="store_true")
    parser.add_argument("--live-crawler", choices=["emart", "homeplus", "lottemart"], help="Crawler registry name to run.")
    parser.add_argument("--allow-live-provider", action="store_true")
    parser.add_argument("--provider-id", help="ai-admin provider_id. Required with --allow-live-provider.")
    parser.add_argument("--provider-key-alias", help="Optional AIStudio key alias used only for observability/no-key skip checks; value is never printed.")
    parser.add_argument("--provider-model", help="Optional provider model name to record in validation_run metadata.")
    parser.add_argument(
        "--validation-mode",
        choices=sorted(VALIDATION_RUN_MODES),
        help="Override artifact validation mode label for stub/fixture/source_replay/live smoke runs.",
    )
    parser.add_argument("--ai-admin-url", default="http://localhost:8003")
    parser.add_argument(
        "--label-timeout-seconds",
        type=float,
        default=DEFAULT_LABEL_TIMEOUT_SECONDS,
        help=(
            "Bounded HTTP timeout for /api/ingest/raw-records/label; "
            f"default {DEFAULT_LABEL_TIMEOUT_SECONDS:.0f}s, capped at {MAX_LABEL_TIMEOUT_SECONDS:.0f}s."
        ),
    )
    parser.add_argument(
        "--label-chunk-retries",
        type=int,
        default=DEFAULT_LABEL_CHUNK_RETRIES,
        help=(
            "Retry each failed /label chunk this many times when the error is retryable; "
            f"default {DEFAULT_LABEL_CHUNK_RETRIES}, capped at {MAX_LABEL_CHUNK_RETRIES}."
        ),
    )
    parser.add_argument(
        "--label-call-min-interval-seconds",
        type=float,
        default=DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS,
        help=(
            "Minimum spacing between /label HTTP attempts so live validation stays under 5 requests/min; "
            f"default {DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS:.0f}s."
        ),
    )
    parser.add_argument("--ai-admin-api-key-alias", help="Optional alias for ai-admin X-API-Key; value is never printed.")
    parser.add_argument("--catalog-json", type=Path, help="Optional approved catalog terms for evidence labels.")
    parser.add_argument("--learned-json", type=Path, help="Optional learned alias terms for evidence labels.")
    parser.add_argument("--allow-db-admin-submit", action="store_true", help="Also call ai-admin publish-approved; writes to DB-admin.")
    parser.add_argument("--reviewer-id", default="manual-live-validation-v2")
    return parser

def run_harness(
    args: argparse.Namespace,
    *,
    http_json: Callable[..., dict[str, Any]] = _http_json,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    configure_utf8_runtime()
    live_items_cap = effective_live_items_cap(args)
    if args.max_items < 1 or args.max_items > live_items_cap:
        raise ValueError(f"--max-items must be between 1 and {live_items_cap}")
    if args.max_pages < 1:
        raise ValueError("--max-pages must be >= 1")
    if args.max_provider_calls < 0 or args.max_provider_calls > 100:
        raise ValueError("--max-provider-calls must be between 0 and 100")
    if args.max_crawler_requests < 1:
        raise ValueError("--max-crawler-requests must be >= 1")
    if not hasattr(args, "ai_batch_size"):
        args.ai_batch_size = DEFAULT_AI_BATCH_SIZE
    if not hasattr(args, "ai_batch_prompt_chars"):
        args.ai_batch_prompt_chars = DEFAULT_AI_BATCH_PROMPT_CHARS
    if not hasattr(args, "label_timeout_seconds") or args.label_timeout_seconds is None:
        args.label_timeout_seconds = DEFAULT_LABEL_TIMEOUT_SECONDS
    if not hasattr(args, "label_chunk_retries"):
        args.label_chunk_retries = DEFAULT_LABEL_CHUNK_RETRIES
    if not hasattr(args, "label_call_min_interval_seconds"):
        args.label_call_min_interval_seconds = DEFAULT_LABEL_CALL_MIN_INTERVAL_SECONDS
    if args.ai_batch_size < 1 or args.ai_batch_size > MAX_LIVE_AI_BATCH_SIZE:
        raise ValueError(f"--ai-batch-size must be between 1 and {MAX_LIVE_AI_BATCH_SIZE}")
    if args.ai_batch_prompt_chars < 1 or args.ai_batch_prompt_chars > MAX_LIVE_AI_BATCH_PROMPT_CHARS:
        raise ValueError(f"--ai-batch-prompt-chars must be between 1 and {MAX_LIVE_AI_BATCH_PROMPT_CHARS}")
    requested_label_timeout_seconds = float(args.label_timeout_seconds)
    if requested_label_timeout_seconds < 1:
        raise ValueError("--label-timeout-seconds must be >= 1")
    effective_label_timeout_seconds = min(requested_label_timeout_seconds, MAX_LABEL_TIMEOUT_SECONDS)
    args.label_timeout_seconds = effective_label_timeout_seconds
    if args.label_chunk_retries < 0 or args.label_chunk_retries > MAX_LABEL_CHUNK_RETRIES:
        raise ValueError(f"--label-chunk-retries must be between 0 and {MAX_LABEL_CHUNK_RETRIES}")
    requested_label_call_min_interval_seconds = float(args.label_call_min_interval_seconds)
    if requested_label_call_min_interval_seconds < 0:
        raise ValueError("--label-call-min-interval-seconds must be >= 0")
    effective_label_call_min_interval_seconds = min(
        requested_label_call_min_interval_seconds,
        MAX_LABEL_CALL_MIN_INTERVAL_SECONDS,
    )
    args.label_call_min_interval_seconds = effective_label_call_min_interval_seconds
    if args.live_crawler and not args.allow_live_crawl:
        raise ValueError("--live-crawler requires --allow-live-crawl")
    if args.allow_live_provider and not args.provider_id:
        raise ValueError("--allow-live-provider requires --provider-id")
    if args.allow_db_admin_submit and not args.allow_live_provider:
        raise ValueError("--allow-db-admin-submit requires --allow-live-provider")

    run_id = f"live-validation-v2-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = args.artifact_dir / f"{run_id}.json"

    provider_key_alias = getattr(args, "provider_key_alias", None)
    provider_key_present = bool(provider_key_alias and resolve_secret_alias(provider_key_alias))
    validation_mode = getattr(args, "validation_mode", None) or infer_default_validation_mode(args)
    if validation_mode not in VALIDATION_RUN_MODES:
        raise ValueError(f"validation_mode must be one of {sorted(VALIDATION_RUN_MODES)}")
    validation_metadata = build_validation_run_metadata(
        mode=validation_mode,
        provider=args.provider_id,
        model=getattr(args, "provider_model", None),
        key_present=provider_key_present,
        live_opt_in=bool(args.allow_live_provider),
        skip_reason=None if args.allow_live_provider else "offline fixture/dry-run; live provider not opted in",
    )

    decisions = {
        "manual_only": True,
        "dry_run_no_provider": not args.allow_live_provider,
        "live_crawl_allowed": bool(args.allow_live_crawl),
        "live_provider_allowed": bool(args.allow_live_provider),
        "db_admin_submit_allowed": bool(args.allow_db_admin_submit),
        "provider_secret_handling": "harness passes provider_id only; ai-admin resolves provider secret_alias via existing resolver",
        "provider_key_alias_checked": bool(provider_key_alias),
        "bounds": {
            "max_items": args.max_items,
            "retain_all_input": bool(getattr(args, "retain_all_input", False)),
            "allow_large_live_batch": bool(getattr(args, "allow_large_live_batch", False)),
            "max_live_items_cap": live_items_cap,
            "hard_max_live_items_cap": HARD_MAX_LIVE_ITEMS,
            "max_pages": args.max_pages,
            "max_crawler_requests": args.max_crawler_requests,
            "max_provider_calls": args.max_provider_calls,
            "ai_batch_size": args.ai_batch_size,
            "ai_batch_prompt_chars": args.ai_batch_prompt_chars,
            "label_timeout_seconds": effective_label_timeout_seconds,
            "label_timeout_seconds_requested": requested_label_timeout_seconds,
            "label_timeout_seconds_cap": MAX_LABEL_TIMEOUT_SECONDS,
            "label_chunk_retries": args.label_chunk_retries,
            "label_call_min_interval_seconds": effective_label_call_min_interval_seconds,
            "label_call_min_interval_seconds_requested": requested_label_call_min_interval_seconds,
        },
    }

    live_crawl: dict[str, Any] | None = None
    input_artifact_sources: list[dict[str, Any]] = []
    if args.allow_live_crawl and args.live_crawler:
        live_crawl = asyncio.run(
            _run_live_crawler(args.live_crawler, args.max_pages, args.max_items, args.max_crawler_requests)
        )
        total_input_count = int(live_crawl.get("crawler_items_count") or len(live_crawl["items"]))
        items = live_crawl["items"][: args.max_items]
        source_name = args.live_crawler
        crawler_name = args.live_crawler
    elif args.input_json:
        loaded_items, input_artifact_sources = _load_input_artifact(args.input_json)
        total_input_count = len(loaded_items)
        items = loaded_items if getattr(args, "retain_all_input", False) else loaded_items[: args.max_items]
        source_name = args.source_name
        crawler_name = args.crawler_name
    else:
        loaded_items = _fixture_items()
        total_input_count = len(loaded_items)
        items = loaded_items[: args.max_items]
        source_name = args.source_name
        crawler_name = args.crawler_name

    _assert_live_item_count_within_cap(len(items), live_items_cap)

    batch_seed = f"{run_id}:raw"
    records, skipped, invalid_rows, retention_anomalies = _build_quality_raw_records(
        items,
        fallback_source_name=source_name,
        batch_id=batch_seed,
    )
    source_diagnostics = _build_source_diagnostics(
        live_crawl=live_crawl,
        selected_count=len(items),
        records_count=len(records),
        skipped_count=skipped,
        invalid_rows=invalid_rows,
        retention_anomalies=retention_anomalies,
    )
    split_batches = split_records_for_ai(
        records,
        max_batch_items=args.ai_batch_size,
        max_prompt_chars=args.ai_batch_prompt_chars,
    )
    prompt_budget = []
    for index, batch in enumerate(split_batches, start=1):
        prompt = build_labeling_prompt(batch, max_prompt_chars=args.ai_batch_prompt_chars)
        prompt_budget.append(
            {
                "batch_index": index,
                "record_count": len(batch),
                "raw_record_ids": [record.raw_record_id for record in batch],
                "prompt_chars": len(prompt),
                "max_prompt_chars": args.ai_batch_prompt_chars,
                "within_budget": len(prompt) <= args.ai_batch_prompt_chars,
            }
        )
    if args.allow_live_provider and len(split_batches) > args.max_provider_calls:
        raise ValueError(
            f"provider call bound exceeded: would need {len(split_batches)} calls, max is {args.max_provider_calls}"
        )

    catalog_terms = _load_terms(args.catalog_json, "word", "name", "canonical_name", "keywords", "aliases", "match_terms")
    learned_terms = _load_terms(args.learned_json, "pattern", "word", "keywords", "aliases", "match_terms")

    proposals: list[dict[str, Any]] = []
    provider_summary: dict[str, Any] = {"called": False, "provider_mode": "skipped", "reason": "dry-run/no-provider mode"}
    provider_error: BaseException | None = None
    review_fetch: dict[str, Any] = {}
    db_admin_result: dict[str, Any] | None = None
    db_admin_submit_plan: dict[str, Any] = build_db_admin_submit_plan([])
    api_key = resolve_secret_alias(args.ai_admin_api_key_alias) if args.ai_admin_api_key_alias else None
    provider_skip_reason = None
    if args.allow_live_provider and provider_key_alias and not provider_key_present:
        provider_skip_reason = f"missing provider key alias {provider_key_alias}"
        provider_summary = {"called": False, "provider_mode": "skipped", "reason": provider_skip_reason}
        validation_metadata["mode"] = "skipped"
    if args.allow_live_provider and not provider_skip_reason:
        try:
            validation_metadata["live_call_attempted"] = True
            base = args.ai_admin_url.rstrip("/")
            ingest_results: list[dict[str, Any]] = []
            chunk_statuses: list[dict[str, Any]] = []
            first_chunk_error: BaseException | None = None
            http_label_attempts = 0
            provider_call_attempts_consumed = 0
            last_label_call_at: float | None = None
            for chunk_index, batch in enumerate(split_batches, start=1):
                raw_record_ids = [record.raw_record_id for record in batch]
                ingest_body = {
                    "provider_id": args.provider_id,
                    "source_name": source_name,
                    "crawler_name": crawler_name,
                    "schema_type": args.schema_type,
                    "records": [_record_payload(record) for record in batch],
                    "max_ai_batch_items": args.ai_batch_size,
                    "max_ai_batch_prompt_chars": args.ai_batch_prompt_chars,
                    "max_provider_calls": max(1, args.max_provider_calls - provider_call_attempts_consumed),
                }
                chunk_attempts: list[dict[str, Any]] = []
                result: dict[str, Any] | None = None
                final_error_detail: dict[str, Any] | None = None
                blocked_retry_detail: dict[str, Any] | None = None
                retryable = False
                for attempt_index in range(1, args.label_chunk_retries + 2):
                    if (
                        http_label_attempts >= args.max_provider_calls
                        or provider_call_attempts_consumed >= args.max_provider_calls
                    ):
                        blocked_retry_detail = {
                            "class": "ProviderCallBoundExceeded",
                            "message": (
                                "configured max_provider_calls exhausted before this chunk could be retried"
                            ),
                            "location": None,
                            "attempted_label_calls": http_label_attempts,
                            "attempted_provider_calls": provider_call_attempts_consumed,
                            "max_provider_calls": args.max_provider_calls,
                        }
                        final_error_detail = blocked_retry_detail
                        retryable = False
                        break
                    slept_seconds = _sleep_between_label_calls(
                        last_call_at=last_label_call_at,
                        min_interval_seconds=effective_label_call_min_interval_seconds,
                        sleeper=sleeper,
                    )
                    try:
                        http_label_attempts += 1
                        last_label_call_at = time.monotonic()
                        result = http_json(
                            "POST",
                            f"{base}/api/ingest/raw-records/label",
                            body=ingest_body,
                            api_key=api_key,
                            timeout_seconds=effective_label_timeout_seconds,
                        )
                        chunk_attempts.append(
                            {
                                "attempt": attempt_index,
                                "status": "success",
                                "slept_seconds": round(slept_seconds or 0.0, 3),
                            }
                        )
                        break
                    except Exception as exc:
                        if first_chunk_error is None:
                            first_chunk_error = exc
                        final_error_detail = _safe_error_detail(exc)
                        retryable = _is_retryable_provider_error(final_error_detail)
                        chunk_attempts.append(
                            {
                                "attempt": attempt_index,
                                "status": "failed",
                                "retryable": retryable,
                                "slept_seconds": round(slept_seconds or 0.0, 3),
                                "error": final_error_detail,
                            }
                        )
                        if not retryable:
                            break
                if result is not None:
                    provider_call_attempts_consumed += int(result.get("provider_calls") or 0)
                    ingest_results.append(result)
                    chunk_statuses.append(
                        {
                            "chunk_index": chunk_index,
                            "status": "success",
                            "record_count": len(batch),
                            "raw_record_ids": raw_record_ids,
                            "attempt_count": len(chunk_attempts),
                            "attempts": chunk_attempts,
                            "raw_batch_id": result.get("raw_batch_id"),
                            "provider_calls": int(result.get("provider_calls") or 0),
                            "ai_batches": int(result.get("ai_batches") or 0),
                            "missing_label_count": int(result.get("missing_label_count") or 0),
                            "missing_label_raw_record_ids": result.get("missing_label_raw_record_ids") or [],
                            "provider_response_validation": result.get("provider_response_validation") or {},
                        }
                    )
                else:
                    chunk_statuses.append(
                        {
                            "chunk_index": chunk_index,
                            "status": "failed",
                            "record_count": len(batch),
                            "raw_record_ids": raw_record_ids,
                            "attempt_count": len(chunk_attempts),
                            "attempts": chunk_attempts,
                            "error": final_error_detail,
                            "retryable": retryable,
                            "call_bound_exhausted": bool(blocked_retry_detail),
                            "blocked_retry": blocked_retry_detail,
                            "missing_label_count": len(batch),
                            "missing_label_raw_record_ids": raw_record_ids,
                        }
                    )
                    continue
            failed_chunks = [chunk for chunk in chunk_statuses if chunk.get("status") == "failed"]
            if http_label_attempts > args.max_provider_calls:
                raise RuntimeError(
                    f"provider call bound exceeded: attempted {http_label_attempts} label HTTP calls, "
                    f"max is {args.max_provider_calls}"
                )
            ingest_result = ingest_results[0] if ingest_results else {}
            raw_batch_ids = [result.get("raw_batch_id") for result in ingest_results if result.get("raw_batch_id")]
            missing_label_ids: list[str] = []
            proposal_ids: list[Any] = []
            for result in ingest_results:
                missing_label_ids.extend(str(raw_id) for raw_id in result.get("missing_label_raw_record_ids") or [])
                proposal_ids.extend(result.get("proposal_ids", []))
            for chunk in failed_chunks:
                missing_label_ids.extend(str(raw_id) for raw_id in chunk.get("missing_label_raw_record_ids") or [])
            provider_calls = sum(int(result.get("provider_calls") or 0) for result in ingest_results)
            ai_batches = sum(int(result.get("ai_batches") or 0) for result in ingest_results)
            proposals_stored = sum(int(result.get("proposals_stored") or 0) for result in ingest_results)
            keyword_proposals_stored = sum(int(result.get("keyword_proposals_stored") or 0) for result in ingest_results)
            provider_response_validations = [
                result.get("provider_response_validation") or {}
                for result in ingest_results
                if isinstance(result.get("provider_response_validation"), dict)
            ]
            provider_response_invalid_count = sum(
                int(validation.get("invalid_response_row_count") or 0)
                for validation in provider_response_validations
            )
            provider_response_index_mapping_count = sum(
                int(validation.get("index_mapping_count") or 0)
                for validation in provider_response_validations
            )
            status_values = {str(result.get("status") or "") for result in ingest_results}
            missing_label_count = (
                sum(int(result.get("missing_label_count") or 0) for result in ingest_results)
                + sum(int(chunk.get("missing_label_count") or 0) for chunk in failed_chunks)
            )
            retryable_failures = [
                chunk for chunk in failed_chunks if chunk.get("retryable")
            ]
            provider_call_bound_exhaustions = [
                chunk for chunk in failed_chunks if chunk.get("call_bound_exhausted")
            ]
            if failed_chunks:
                if retryable_failures:
                    aggregate_status = "partial_failed_retryable" if ingest_results else "failed_retryable"
                else:
                    aggregate_status = "partial_failed" if ingest_results else "failed"
            elif missing_label_count or "partial_review_required" in status_values:
                aggregate_status = "partial_review_required"
            else:
                aggregate_status = ingest_result.get("status")
            provider_summary = {
                "called": True,
                "provider_mode": ingest_result.get("provider_mode") or ("failed" if failed_chunks else "live"),
                "provider_id": args.provider_id,
                "model": getattr(args, "provider_model", None),
                "raw_batch_id": ingest_result.get("raw_batch_id"),
                "raw_batch_ids": raw_batch_ids,
                "provider_calls": provider_calls,
                "max_provider_calls": args.max_provider_calls,
                "provider_call_bound_exhausted": bool(provider_call_bound_exhaustions),
                "provider_call_bound_exhaustion": (
                    provider_call_bound_exhaustions[0].get("blocked_retry")
                    if provider_call_bound_exhaustions
                    else None
                ),
                "ai_batches": ai_batches,
                "http_label_calls": http_label_attempts,
                "chunks": chunk_statuses,
                "chunk_count": len(chunk_statuses),
                "successful_chunk_count": len(ingest_results),
                "failed_chunk_count": len(failed_chunks),
                "retryable_failure_count": len(retryable_failures),
                "retryable_failures": retryable_failures,
                "label_chunk_retries": args.label_chunk_retries,
                "label_call_min_interval_seconds": effective_label_call_min_interval_seconds,
                "partial_results": bool(ingest_results and failed_chunks),
                "status": aggregate_status,
                "partial_review_required": aggregate_status == "partial_review_required" or bool(failed_chunks),
                "missing_label_count": missing_label_count,
                "missing_label_raw_record_ids": _dedupe_list(missing_label_ids),
                "provider_response_validation": {
                    "invalid_response_row_count": provider_response_invalid_count,
                    "index_mapping_count": provider_response_index_mapping_count,
                    "batch_summaries": provider_response_validations,
                    "reason": (
                        "provider returned unknown or missing raw_record_id values; raw records were retained for review"
                        if provider_response_invalid_count
                        else None
                    ),
                },
                "proposals_stored": proposals_stored,
                "keyword_proposals_stored": keyword_proposals_stored,
            }
            if failed_chunks and first_chunk_error is not None:
                provider_error = first_chunk_error
                provider_summary["error"] = _safe_error_detail(first_chunk_error)
            for proposal_id in proposal_ids[:300]:
                detail = http_json("GET", f"{base}/api/review/proposals/{proposal_id}", api_key=api_key)
                if isinstance(detail.get("proposal"), dict):
                    proposals.append(detail["proposal"])
            audit_issues: list[Any] = []
            publish_items: list[Any] = []
            for raw_batch_id in raw_batch_ids:
                query = urlencode({"batch_id": raw_batch_id})
                audit = http_json("GET", f"{base}/api/review/audit?{query}", api_key=api_key)
                publish = http_json("GET", f"{base}/api/review/publish-eligibility?{query}", api_key=api_key)
                audit_issues.extend(audit.get("issues", []) if isinstance(audit, dict) else [])
                publish_items.extend(publish.get("items", []) if isinstance(publish, dict) else [])
            review_fetch = {
                "audit": {"issues": audit_issues},
                "publish_eligibility": {"items": publish_items},
            }
            if args.allow_db_admin_submit:
                db_admin_submit_plan = build_db_admin_submit_plan(
                    review_fetch.get("publish_eligibility", {}).get("items", [])
                )
                eligible_ids = db_admin_submit_plan["raw_record_ids"]
                if eligible_ids:
                    db_admin_result = http_json(
                        "POST",
                        f"{base}/api/review/publish-approved",
                        body={
                            "raw_record_ids": eligible_ids,
                            "reviewer_id": args.reviewer_id,
                            "confirm_count": len(eligible_ids),
                            "batch_id": ",".join(raw_batch_ids) if raw_batch_ids else ingest_result.get("raw_batch_id"),
                        },
                        api_key=api_key,
                        timeout_seconds=90.0,
                    )
                else:
                    db_admin_result = {
                        "skipped": True,
                        "reason": "no ai-safe-final-approve eligible rows after publish eligibility gates",
                        "db_admin_submit_plan": db_admin_submit_plan,
                    }
        except Exception as exc:
            provider_error = exc
            provider_summary = {
                "called": True,
                "provider_mode": "failed",
                "provider_id": args.provider_id,
                "model": getattr(args, "provider_model", None),
                "error": _safe_error_detail(exc),
            }

    provider_items = provider_items_from_proposals(proposals)
    holdout_generalization = evaluate_holdout_generalization(
        records,
        provider_items,
        catalog_terms=catalog_terms,
        learned_terms=learned_terms,
    )

    local_audit = build_raw_ai_audit(records, [], batch_id=batch_seed)
    local_publish_rows = []
    for record in records:
        issues = [issue for issue in local_audit["issues"] if issue["raw_record_id"] == record.raw_record_id]
        item = db_item_from_review(record, [], {})
        local_publish_rows.append(
            {
                "raw_record_id": record.raw_record_id,
                "item": item,
                "blockers": publish_blockers(record, [], issues, {}, []),
            }
        )

    raw_vs_final = []
    live_rows = {
        row.get("raw_record_id"): row
        for row in review_fetch.get("publish_eligibility", {}).get("items", [])
        if isinstance(row, dict)
    }
    fallback_rows = {row["raw_record_id"]: row for row in local_publish_rows}
    for record in records:
        row = live_rows.get(record.raw_record_id) or fallback_rows.get(record.raw_record_id) or {}
        final_item = row.get("item") or {}
        raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        raw_vs_final.append(
            {
                "raw_record_id": record.raw_record_id,
                "raw_title": record.raw_title,
                "final_name": final_item.get("name"),
                "raw_price": record.raw_price,
                "final_sale_price": final_item.get("sale_price"),
                "raw_original_price": raw_payload.get("original_price"),
                "final_original_price": final_item.get("original_price"),
                "raw_discount_percent": raw_payload.get("discount_percent"),
                "final_discount_percent": final_item.get("discount_percent"),
                "raw_source_url": record.source_url,
                "final_source_url": final_item.get("source_url"),
                "raw_image_url": raw_payload.get("image_url") or raw_payload.get("image"),
                "final_image_url": final_item.get("image_url"),
                "raw_category_id": raw_payload.get("category_id"),
                "final_category_id": final_item.get("category_id"),
                "raw_keywords": raw_payload.get("keywords"),
                "final_keywords": final_item.get("keywords"),
                "publication_kind": row.get("publication_kind") or final_item.get("publication_kind"),
                "price_observation_only": row.get("price_observation_only")
                    if "price_observation_only" in row
                    else final_item.get("price_observation_only"),
                "blockers": row.get("blockers", []),
            }
        )

    item_counts = {
        "input_items": total_input_count,
        "selected_items": len(items),
        "retained_items": len(records),
        "records": len(records),
        "skipped": skipped,
        "invalid_rows": len(invalid_rows),
        "retention_anomalies": len(retention_anomalies),
        "input_retention_valid": len(items) == len(records) + len(invalid_rows),
        "split_batches": len(split_batches),
        "proposals": len(proposals),
        "publish_eligibility_items": len(
            review_fetch.get("publish_eligibility", {}).get("items", local_publish_rows)
        ),
        "provider_calls": provider_summary.get("provider_calls"),
        "provider_call_attempts": provider_summary.get("provider_calls"),
        "partial_review_required": provider_summary.get("status") == "partial_review_required",
        "missing_label_count": provider_summary.get("missing_label_count") or 0,
    }
    validation_metadata = finish_validation_run_metadata(
        validation_metadata,
        live_call_attempted=bool(validation_metadata.get("live_call_attempted")),
        live_call_succeeded=bool(args.allow_live_provider and not provider_skip_reason and provider_error is None),
        skip_reason=provider_skip_reason or validation_metadata.get("skip_reason"),
        error=provider_error,
        item_counts=item_counts,
    )
    quality_batch_validation = build_quality_batch_validation_summary(
        args=args,
        total_input_count=total_input_count,
        selected_count=len(items),
        retained_count=len(records),
        invalid_rows=invalid_rows,
        split_batch_count=len(split_batches),
        provider_summary=provider_summary,
        validation_metadata=validation_metadata,
        raw_vs_final=raw_vs_final,
        audit_issues=review_fetch.get("audit", local_audit),
        publish_blockers=review_fetch.get("publish_eligibility", {"items": local_publish_rows}),
        retention_anomalies=retention_anomalies,
    )
    db_admin_acceptance = build_db_admin_acceptance_summary(
        db_admin_result,
        db_admin_submit_allowed=bool(args.allow_db_admin_submit),
    )

    artifact = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "command_shape": (
            "py tools\\live_validation_harness_v2.py "
            "[--input-json data.json | --allow-live-crawl --live-crawler emart] "
            "[--allow-live-provider --provider-id google-dev] "
            "[--allow-db-admin-submit]"
        ),
        "validation_run": validation_metadata,
        "decisions": decisions,
        "source": {
            "selected_item_count": len(items),
            "records_count": len(records),
            "skipped_count": skipped,
            "invalid_rows": invalid_rows,
            "retention_anomalies": retention_anomalies,
            "input_artifact_sources": input_artifact_sources,
            "live_crawl": live_crawl,
            "alerts": source_diagnostics["alerts"],
            "diagnostics": source_diagnostics["diagnostics"],
        },
        "raw_selected_items": items,
        "raw_records": [_record_payload(record) for record in records],
        "prompt_budget": prompt_budget,
        "provider_response_summary": provider_summary,
        "label_timeout_seconds": effective_label_timeout_seconds,
        "proposals": _redact(proposals),
        "audit_issues": review_fetch.get("audit", local_audit),
        "publish_blockers": review_fetch.get("publish_eligibility", {"items": local_publish_rows}),
        "db_admin_submit_plan": _redact(db_admin_submit_plan),
        "db_admin_submit_result": _redact(db_admin_result),
        "db_admin_acceptance": _redact(db_admin_acceptance),
        "raw_vs_final": raw_vs_final,
        "quality_batch_validation": quality_batch_validation,
        "holdout_generalization": holdout_generalization,
        "risks": [
            "Live crawl/provider/DB-admin paths are operator-gated but can touch external systems when explicitly enabled.",
            "Dry-run artifacts use no provider output; customer-safety verdicts remain blockers until human/provider proposals exist.",
        ],
    }
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact

def main(argv: list[str] | None = None) -> int:
    configure_utf8_runtime()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    artifact = run_harness(args)
    print(json.dumps({
        "artifact_path": artifact["artifact_path"],
        "records": artifact["source"]["records_count"],
        "provider_called": artifact["provider_response_summary"]["called"],
        "label_timeout_seconds": artifact["label_timeout_seconds"],
        "validation_mode": artifact["validation_run"]["mode"],
        "live_call_attempted": artifact["validation_run"]["live_call_attempted"],
        "live_call_succeeded": artifact["validation_run"]["live_call_succeeded"],
        "quality_batch_validation": artifact["quality_batch_validation"],
        "db_admin_acceptance": artifact["db_admin_acceptance"],
        "generalization_success_count": artifact["holdout_generalization"]["generalization_success_count"],
    }, ensure_ascii=False, indent=2))
    if args.allow_db_admin_submit and not artifact["db_admin_acceptance"].get("accepted"):
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
