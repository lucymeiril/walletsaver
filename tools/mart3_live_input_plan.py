"""Build the bounded mart3 live DB-acceptance input manifest.

The script only prepares artifacts and command shapes. It never calls AI,
DB-admin, or crawlers.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "mart3-live-input-plan"
DEFAULT_PROVIDER_ID = "google-gemini31-live-matrix"
DEFAULT_PROVIDER_MODEL = "gemini-3.1-flash-lite-preview"
ITEMS_PER_MART = 2
TOTAL_MAX_ITEMS = 6
MAX_PROVIDER_CALLS = 3
AI_BATCH_SIZE = 2
LABEL_CALL_MIN_INTERVAL_SECONDS = 12
LABEL_CHUNK_RETRIES = 1

DEFAULT_EVIDENCE_ARTIFACTS = {
    "emart": REPO_ROOT
    / ".walletsavior-live-validation"
    / "live-model-batch"
    / "live-validation-v2-20260507-143442-cd83d519.json",
    "lottemart": REPO_ROOT
    / ".walletsavior-live-validation"
    / "mart3-live-input-plan"
    / "no-db-diagnostics"
    / "lottemart"
    / "live-validation-v2-20260507-221452-2720bf59.json",
    "homeplus": REPO_ROOT
    / ".walletsavior-live-validation"
    / "mart3-live-input-plan"
    / "no-db-diagnostics"
    / "homeplus"
    / "live-validation-v2-20260507-221457-1c75cc26.json",
}
FAILED_BOUNDED_DIAGNOSTICS = {
    "emart": REPO_ROOT
    / ".walletsavior-live-validation"
    / "mart3-live-input-plan"
    / "no-db-diagnostics"
    / "emart"
    / "live-validation-v2-20260507-221438-b90fa00c.json",
}

SOURCE_LABELS = {
    "emart": ("이마트", "emart"),
    "lottemart": ("롯데마트", "lottemart"),
    "homeplus": ("홈플러스", "homeplus"),
}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_items(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(artifact.get("raw_selected_items"), list):
        return [row for row in artifact["raw_selected_items"] if isinstance(row, dict)]
    live_crawl = artifact.get("source", {}).get("live_crawl", {})
    if isinstance(live_crawl.get("items"), list):
        return [row for row in live_crawl["items"] if isinstance(row, dict)]
    return []


def _matches_mart(item: dict[str, Any], mart: str) -> bool:
    korean, ascii_name = SOURCE_LABELS[mart]
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("store", "source", "source_name", "event_name", "detail_url")
    ).lower()
    return korean in haystack or ascii_name in haystack


def selected_items_for_mart(mart: str, artifact_path: Path, *, limit: int = ITEMS_PER_MART) -> list[dict[str, Any]]:
    artifact = _load_json(artifact_path)
    candidates = [item for item in _artifact_items(artifact) if _matches_mart(item, mart)]
    if len(candidates) < limit:
        candidates = _artifact_items(artifact)
    selected = []
    for index, item in enumerate(candidates[:limit], start=1):
        row = dict(item)
        row.setdefault("source", mart)
        row["mart3_acceptance_source"] = mart
        row["mart3_acceptance_source_artifact"] = _rel(artifact_path)
        row["mart3_acceptance_ordinal"] = index
        selected.append(row)
    if len(selected) != limit:
        raise ValueError(f"{mart} evidence artifact yielded {len(selected)} items, expected {limit}: {_rel(artifact_path)}")
    return selected


def build_plan(
    artifact_dir: Path,
    *,
    evidence_artifacts: dict[str, Path] | None = None,
    provider_id: str = DEFAULT_PROVIDER_ID,
    provider_model: str = DEFAULT_PROVIDER_MODEL,
) -> dict[str, Any]:
    evidence_artifacts = evidence_artifacts or DEFAULT_EVIDENCE_ARTIFACTS
    input_path = artifact_dir / "mart3-live-crawler-batch.json"
    live_artifact_dir = artifact_dir / "live-db-acceptance"
    diagnostic_dir = artifact_dir / "no-db-diagnostics"
    selected_items: list[dict[str, Any]] = []
    evidence = {}
    for mart in ("emart", "lottemart", "homeplus"):
        path = evidence_artifacts[mart]
        artifact = _load_json(path)
        counts = artifact.get("validation_run", {}).get("item_counts", {})
        source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
        live_crawl = source.get("live_crawl") if isinstance(source.get("live_crawl"), dict) else {}
        evidence[mart] = {
            "artifact": _rel(path),
            "run_id": artifact.get("run_id"),
            "db_admin_submit_allowed": artifact.get("decisions", {}).get("db_admin_submit_allowed") is True,
            "provider_called": artifact.get("provider_response_summary", {}).get("called") is True,
            "live_crawl_status": live_crawl.get("status"),
            "records": counts.get("records"),
            "selected_items": counts.get("selected_items"),
        }
        if mart in FAILED_BOUNDED_DIAGNOSTICS and FAILED_BOUNDED_DIAGNOSTICS[mart].is_file():
            failed = _load_json(FAILED_BOUNDED_DIAGNOSTICS[mart])
            failed_live = failed.get("source", {}).get("live_crawl", {})
            evidence[mart]["latest_bounded_diagnostic_blocker"] = {
                "artifact": _rel(FAILED_BOUNDED_DIAGNOSTICS[mart]),
                "status": failed_live.get("status"),
                "error_msg": failed_live.get("error_msg"),
            }
        selected_items.extend(selected_items_for_mart(mart, path))

    command = [
        "py",
        "tools\\one_shot_db_build_orchestrator.py",
        "--crawler-batch-json",
        _rel(input_path),
        "--artifact-dir",
        _rel(artifact_dir / "one-shot-db-acceptance"),
        "--live-batch-artifact-dir",
        _rel(live_artifact_dir),
        "--retain-all-crawler-input",
        "--live-batch-max-items",
        str(TOTAL_MAX_ITEMS),
        "--live-batch-max-provider-calls",
        str(MAX_PROVIDER_CALLS),
        "--live-batch-ai-batch-size",
        str(AI_BATCH_SIZE),
        "--live-batch-ai-batch-prompt-chars",
        "8000",
        "--provider-id",
        provider_id,
        "--provider-model",
        provider_model,
        "--live-batch-label-chunk-retries",
        str(LABEL_CHUNK_RETRIES),
        "--live-batch-label-call-min-interval-seconds",
        str(LABEL_CALL_MIN_INTERVAL_SECONDS),
        "--ai-admin-url",
        "http://127.0.0.1:8003",
        "--allow-live-ai-provider",
        "--allow-live-ai-labeling",
        "--allow-db-mutation",
    ]
    return {
        "schema": "walletsavior.mart3_live_input_plan.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "prepare-only; no DB mutation or provider call was made by this script",
        "source_evidence": evidence,
        "input_json": _rel(input_path),
        "selected_item_count": len(selected_items),
        "caps": {
            "marts": ["emart", "lottemart", "homeplus"],
            "items_per_mart": ITEMS_PER_MART,
            "total_max_items": TOTAL_MAX_ITEMS,
            "max_provider_calls": MAX_PROVIDER_CALLS,
            "ai_batch_size": AI_BATCH_SIZE,
            "label_chunk_retries": LABEL_CHUNK_RETRIES,
            "label_call_min_interval_seconds": LABEL_CALL_MIN_INTERVAL_SECONDS,
            "crawler_prefetch_for_fresh_inputs": {
                "max_items_per_mart": ITEMS_PER_MART,
                "max_pages": 1,
                "max_crawler_requests": 1,
                "max_provider_calls": 0,
                "db_admin_submit_allowed": False,
            },
        },
        "provider": {"provider_id": provider_id, "model": provider_model},
        "commands": {
            "fresh_no_db_diagnostics_per_mart": [
                [
                    "py",
                    "tools\\live_validation_harness_v2.py",
                    "--allow-live-crawl",
                    "--live-crawler",
                    mart,
                    "--max-items",
                    str(ITEMS_PER_MART),
                    "--max-pages",
                    "1",
                    "--max-crawler-requests",
                    "1",
                    "--max-provider-calls",
                    "0",
                    "--artifact-dir",
                    _rel(diagnostic_dir / mart),
                ]
                for mart in ("emart", "lottemart", "homeplus")
            ],
            "actual_db_acceptance_run": command,
        },
        "db_submit_final_approve_requirements": [
            "Do not run unless ai-admin is freshly restarted and /health passes.",
            "Provider and ai-admin API keys must be configured by alias/environment only; never put secret values in commands.",
            "Run the actual command exactly once for this 6-row batch; do not add --allow-large-live-batch.",
            "The actual command must enter through tools\\one_shot_db_build_orchestrator.py with --allow-db-mutation; it forwards --allow-db-admin-submit to tools\\run_live_model_batch.py only after DB-admin mutation preflight reports ready_to_mutate.",
            "Treat acceptance as passed only when the orchestrator DB-admin safety phase passes and the delegated live batch reports db_admin_acceptance.accepted true with submitted_to_db_admin >= 1, ai_safe_final_approved >= 1, public_db_verified >= ai_safe_final_approved, rollback/re-review evidence or next action present, and no pending/failed rows.",
            "If no rows are eligible, stop and inspect publish blockers; do not broaden collection.",
        ],
        "expected_output_artifacts": {
            "manifest": _rel(artifact_dir / "mart3-live-run-manifest.json"),
            "input_json": _rel(input_path),
            "orchestrator_artifacts": _rel(artifact_dir / "one-shot-db-acceptance" / "one-shot-db-build-<timestamp>-<id>.json"),
            "live_run_artifacts": _rel(live_artifact_dir / "live-validation-v2-<timestamp>-<id>.json"),
        },
        "selected_items": selected_items,
    }


def write_plan(plan: dict[str, Any], artifact_dir: Path) -> tuple[Path, Path]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_path = artifact_dir / "mart3-live-crawler-batch.json"
    manifest_path = artifact_dir / "mart3-live-run-manifest.json"
    input_path.write_text(json.dumps(plan["selected_items"], ensure_ascii=False, indent=2), encoding="utf-8")
    serializable = dict(plan)
    serializable.pop("selected_items", None)
    manifest_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    return input_path, manifest_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare mart3 live DB-acceptance input artifacts without mutating DB.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--emart-artifact", type=Path, default=DEFAULT_EVIDENCE_ARTIFACTS["emart"])
    parser.add_argument("--lottemart-artifact", type=Path, default=DEFAULT_EVIDENCE_ARTIFACTS["lottemart"])
    parser.add_argument("--homeplus-artifact", type=Path, default=DEFAULT_EVIDENCE_ARTIFACTS["homeplus"])
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--provider-model", default=DEFAULT_PROVIDER_MODEL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    plan = build_plan(
        args.artifact_dir,
        evidence_artifacts={
            "emart": args.emart_artifact,
            "lottemart": args.lottemart_artifact,
            "homeplus": args.homeplus_artifact,
        },
        provider_id=args.provider_id,
        provider_model=args.provider_model,
    )
    _input_path, manifest_path = write_plan(plan, args.artifact_dir)
    output = {
        "status": "prepared",
        "manifest": _rel(manifest_path),
        "input_json": plan["input_json"],
        "selected_item_count": plan["selected_item_count"],
        "caps": plan["caps"],
        "actual_db_acceptance_command": plan["commands"]["actual_db_acceptance_run"],
        "scope": plan["scope"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
