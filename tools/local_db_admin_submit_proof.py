"""Local DB-admin submit/final-approve proof for bounded real source artifacts."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
AI_BACKEND = ROOT / "packages" / "ai-admin" / "backend"
DB_BACKEND = ROOT / "packages" / "db-admin" / "backend"
SHARED = ROOT / "packages" / "shared"

for _path in (str(SHARED), str(DB_BACKEND)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

from api.routes import admin as admin_routes  # noqa: E402
from api.routes import ingestion as ingestion_routes  # noqa: E402
from config import settings  # noqa: E402
from storage.models import (  # noqa: E402
    Base,
    DiscountHistory,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    PendingIngestion,
    Product,
)


@dataclass
class LocalProofArgs:
    input_json: Path
    artifact_dir: Path
    max_items: int = 3
    allow_db_admin_submit: bool = False
    source_name: str = "local-source-artifact"
    reviewer_id: str = "operator-safe-local-proof"


def _load_ai_harness():
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "services"
        or name.startswith("services.")
        or name == "storage"
        or name.startswith("storage.")
        or name == "providers"
        or name.startswith("providers.")
    }
    for name in list(saved_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AI_BACKEND))
    sys.path.insert(0, str(SHARED))
    try:
        spec = importlib.util.spec_from_file_location(
            "live_validation_harness_v2_local_db_proof",
            ROOT / "tools" / "live_validation_harness_v2.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load live_validation_harness_v2.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == "services"
            or name.startswith("services.")
            or name == "storage"
            or name.startswith("storage.")
            or name == "providers"
            or name.startswith("providers.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path = saved_path


def _load_json_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "raw_selected_items", "raw_records"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"{path} does not contain a JSON item list")


def _session_factory(db_path: Path):
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)),
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def _patch_db_admin_sessions(Session):
    original_ingestion_get_session = ingestion_routes.get_session
    original_ingestion_managed_session = ingestion_routes.managed_session
    original_admin_get_session = admin_routes.get_session
    original_admin_list_backups = admin_routes.list_backups

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    ingestion_routes.get_session = get_test_session
    ingestion_routes.managed_session = managed_test_session
    admin_routes.get_session = get_test_session
    admin_routes.list_backups = lambda: [{"filename": "local-db-submit-safe-row-scale.sqlite"}]

    def restore() -> None:
        ingestion_routes.get_session = original_ingestion_get_session
        ingestion_routes.managed_session = original_ingestion_managed_session
        admin_routes.get_session = original_admin_get_session
        admin_routes.list_backups = original_admin_list_backups

    return restore


def _db_admin_client(Session, api_key: str) -> TestClient:
    restore_routes = _patch_db_admin_sessions(Session)
    original_require = settings.REQUIRE_AUTH
    original_keys = settings.SERVICE_API_KEYS
    settings.REQUIRE_AUTH = True
    settings.SERVICE_API_KEYS = {api_key: "admin"}
    app = FastAPI(title="local DB-admin submit proof")
    app.include_router(ingestion_routes.router)
    app.include_router(admin_routes.router, prefix="/api")
    client = TestClient(app)

    def restore() -> None:
        settings.REQUIRE_AUTH = original_require
        settings.SERVICE_API_KEYS = original_keys
        restore_routes()

    client._walletsavior_restore_settings = restore  # type: ignore[attr-defined]
    return client


def _price_observation_item(item: dict[str, Any]) -> dict[str, Any]:
    safe = copy.deepcopy(item)
    safe["publication_kind"] = "price_observation"
    safe["price_observation_only"] = True
    safe["discount_claim_status"] = "price_observation_no_hotdeal_claim"
    audit = safe.setdefault("ai_review_audit", {})
    if isinstance(audit, dict):
        audit["operator_safe_local_proof"] = True
        audit["hotdeal_claim_suppressed"] = True
    raw_data = safe.setdefault("raw_data", {})
    if isinstance(raw_data, dict):
        raw_data["operator_safe_local_proof"] = {
            "publication_kind": "price_observation",
            "hotdeal_claim_suppressed": True,
        }
    return safe


def _hold_reasons(record: Any, item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not (item.get("name") or item.get("source_title") or getattr(record, "raw_title", None)):
        reasons.append("missing_name")
    price = item.get("sale_price") or item.get("current_price") or getattr(record, "raw_price", None)
    try:
        if float(price) <= 0:
            reasons.append("missing_or_nonpositive_price")
    except (TypeError, ValueError):
        reasons.append("missing_or_nonpositive_price")
    if not (item.get("source_url") or item.get("detail_url") or getattr(record, "source_url", None)):
        reasons.append("missing_source_url")
    if not item.get("image_url"):
        reasons.append("missing_image_url")
    if not (item.get("source") or item.get("store") or getattr(record, "source_name", None)):
        reasons.append("missing_source")
    return reasons


def _build_db_admin_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(candidate["item"])
    raw_data = item.setdefault("raw_data", {})
    if isinstance(raw_data, dict):
        raw_data["ai_review_publish_provenance"] = {
            "raw_record_id": candidate["raw_record_id"],
            "batch_id": candidate["batch_id"],
            "source_name": candidate["source_name"],
            "human_decision_ids": candidate["human_decision_ids"],
            "db_handoff_mode": candidate["db_handoff_mode"],
            "publication_kind": candidate["publication_kind"],
        }
    audit = item.setdefault("ai_review_audit", {})
    if isinstance(audit, dict):
        audit["human_decision_ids"] = candidate["human_decision_ids"]
    return {
        "crawler_name": f"ai-admin:{candidate['source_name']}",
        "crawl_status": "success",
        "items": [item],
        "schema_type": "DiscountItem",
        "strategy_used": "ai_review_publish",
        "duration_seconds": 0,
        "errors": [],
        "source_url": item.get("source_url"),
    }


def run_local_proof(args: LocalProofArgs) -> dict[str, Any]:
    if not args.allow_db_admin_submit:
        raise ValueError("--allow-db-admin-submit is required for the local DB-admin proof")
    if args.max_items < 1 or args.max_items > 20:
        raise ValueError("--max-items must be between 1 and 20 for the local DB-admin proof")

    run_id = f"local-db-submit-safe-row-scale-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.artifact_dir / f"{run_id}.sqlite"
    artifact_path = args.artifact_dir / f"{run_id}.json"
    harness = _load_ai_harness()
    raw_items = _load_json_items(args.input_json)
    selected_items = raw_items[: args.max_items]
    batch_id = f"{run_id}:operator-safe"
    records, skipped, invalid_rows, retention_anomalies = harness._build_quality_raw_records(
        selected_items,
        fallback_source_name=args.source_name,
        batch_id=batch_id,
    )

    safe_candidates: list[dict[str, Any]] = []
    held_rows: list[dict[str, Any]] = []
    held_reason_counts: Counter[str] = Counter()
    for record in records:
        item = _price_observation_item(harness.db_item_from_review(record, [], {}))
        reasons = _hold_reasons(record, item)
        if reasons:
            held_rows.append({"raw_record_id": record.raw_record_id, "reasons": reasons})
            held_reason_counts.update(reasons)
            continue
        safe_candidates.append(
            {
                "raw_record_id": record.raw_record_id,
                "batch_id": batch_id,
                "source_name": record.source_name,
                "human_decision_ids": [args.reviewer_id],
                "db_handoff_mode": "operator_safe_local_ai_safe_final_approve",
                "publication_kind": "price_observation",
                "item": item,
            }
        )

    api_key = f"local-proof-{uuid.uuid4().hex}"
    Session, engine = _session_factory(db_path)
    client = _db_admin_client(Session, api_key)
    submit_results: list[dict[str, Any]] = []
    try:
        backup_response = client.get("/api/admin/backups", headers={"X-API-Key": api_key})
        for candidate in safe_candidates:
            payload = _build_db_admin_payload(candidate)
            submit_response = client.post(
                "/api/ingestions",
                json=json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
                headers={"X-API-Key": api_key},
            )
            result: dict[str, Any] = {
                "raw_record_id": candidate["raw_record_id"],
                "submit_status_code": submit_response.status_code,
            }
            if submit_response.status_code == 200:
                ingestion_id = submit_response.json()["id"]
                result["db_ingestion_id"] = ingestion_id
                approve_response = client.post(
                    f"/api/ingestions/{ingestion_id}/ai-safe-final-approve",
                    json={"action": "approve", "notes": args.reviewer_id},
                    headers={"X-API-Key": api_key},
                )
                result["final_approve_status_code"] = approve_response.status_code
                result["ai_safe_final_approve"] = (
                    approve_response.json() if approve_response.status_code == 200 else {"error": approve_response.text}
                )
                result["status"] = (
                    "published"
                    if approve_response.status_code == 200
                    and result["ai_safe_final_approve"].get("status") == "approved"
                    else "final_approve_failed"
                )
            else:
                result["status"] = "submit_failed"
                result["error"] = submit_response.text
            submit_results.append(result)

        with Session() as session:
            db_counts = {
                "pending_ingestions": session.scalar(select(func.count()).select_from(PendingIngestion)),
                "products": session.scalar(select(func.count()).select_from(Product)),
                "discount_history": session.scalar(select(func.count()).select_from(DiscountHistory)),
                "normalized_canonical_products": session.scalar(select(func.count()).select_from(NormalizedCanonicalProduct)),
                "normalized_product_variants": session.scalar(select(func.count()).select_from(NormalizedProductVariant)),
                "normalized_source_listings": session.scalar(select(func.count()).select_from(NormalizedSourceListing)),
                "normalized_offer_events": session.scalar(select(func.count()).select_from(NormalizedOfferEvent)),
                "normalized_week_buckets": session.scalar(select(func.count()).select_from(NormalizedWeekBucket)),
                "normalized_offer_week_links": session.scalar(select(func.count()).select_from(NormalizedOfferWeekLink)),
            }
    finally:
        client.close()
        client._walletsavior_restore_settings()  # type: ignore[attr-defined]
        engine.dispose()

    submitted = sum(1 for row in submit_results if row.get("submit_status_code") == 200)
    final_approved = sum(1 for row in submit_results if row.get("status") == "published")
    public_verified = sum(
        1
        for row in submit_results
        if row.get("ai_safe_final_approve", {}).get("public_db_verification", {}).get("verified") is True
    )
    rollback_supported = sum(
        1
        for row in submit_results
        if row.get("ai_safe_final_approve", {}).get("rollback_supported")
        and row.get("ai_safe_final_approve", {}).get("re_review_supported")
    )
    artifact = {
        "schema": "walletsavior.local_db_admin_submit_proof.v1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "command_shape": "py tools\\local_db_admin_submit_proof.py --input-json <artifact> --allow-db-admin-submit",
        "source": {
            "input_json": str(args.input_json),
            "input_items": len(raw_items),
            "selected_rows": len(selected_items),
            "records": len(records),
            "skipped": skipped,
            "invalid_rows": invalid_rows,
            "retention_anomalies": retention_anomalies,
        },
        "provider": {
            "mode": "local_operator_safe_no_provider",
            "provider_calls": 0,
            "http_label_calls": 0,
        },
        "db_admin_submit_plan": {
            "mode": "operator_safe_local_price_observation_only",
            "submit_allowed_rows": len(safe_candidates),
            "raw_record_ids": [row["raw_record_id"] for row in safe_candidates],
            "confirm_count": len(safe_candidates),
            "held_for_review_count": len(held_rows),
            "held_for_review_rows": held_rows,
            "held_reason_counts": dict(sorted(held_reason_counts.items())),
            "operator_safety_rule": (
                "Only structurally complete rows are submitted to local/test DB-admin; "
                "all rows are forced to price_observation and hotdeal final claims are suppressed."
            ),
        },
        "db_admin_submit_result": {
            "submitted_to_db_admin": submitted,
            "ai_safe_final_approved": final_approved,
            "public_db_verified": public_verified,
            "rollback_re_review_supported": rollback_supported,
            "pending_db_review": submitted - final_approved,
            "final_approve_failed": sum(1 for row in submit_results if row.get("status") == "final_approve_failed"),
            "failed": sum(1 for row in submit_results if row.get("status") == "submit_failed"),
            "results": submit_results,
            "backup_snapshot_listed": backup_response.status_code == 200,
        },
        "local_db": {
            "path": str(db_path),
            "scope": "local_sqlite_test_db_admin",
            "counts": db_counts,
        },
    }
    artifact["accepted"] = bool(
        safe_candidates
        and submitted == len(safe_candidates)
        and final_approved == len(safe_candidates)
        and public_verified == len(safe_candidates)
        and rollback_supported == len(safe_candidates)
    )
    artifact["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifact


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, default=Path(".walletsavior-live-validation") / "live-db-submit-safe-row-scale")
    parser.add_argument("--max-items", type=int, default=3)
    parser.add_argument("--allow-db-admin-submit", action="store_true")
    parser.add_argument("--source-name", default="local-source-artifact")
    parser.add_argument("--reviewer-id", default="operator-safe-local-proof")
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_arg_parser().parse_args(argv)
    artifact = run_local_proof(
        LocalProofArgs(
            input_json=ns.input_json,
            artifact_dir=ns.artifact_dir,
            max_items=ns.max_items,
            allow_db_admin_submit=ns.allow_db_admin_submit,
            source_name=ns.source_name,
            reviewer_id=ns.reviewer_id,
        )
    )
    print(json.dumps({
        "artifact_path": artifact["artifact_path"],
        "accepted": artifact["accepted"],
        "selected_rows": artifact["source"]["selected_rows"],
        "provider_calls": artifact["provider"]["provider_calls"],
        "safe_submit_rows": artifact["db_admin_submit_plan"]["submit_allowed_rows"],
        "held_for_review_count": artifact["db_admin_submit_plan"]["held_for_review_count"],
        "held_reason_counts": artifact["db_admin_submit_plan"]["held_reason_counts"],
        "submitted_to_db_admin": artifact["db_admin_submit_result"]["submitted_to_db_admin"],
        "ai_safe_final_approved": artifact["db_admin_submit_result"]["ai_safe_final_approved"],
        "public_db_verified": artifact["db_admin_submit_result"]["public_db_verified"],
    }, ensure_ascii=False, indent=2))
    return 0 if artifact["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
