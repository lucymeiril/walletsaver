"""Read-only initial-catalog preparation and isolated import rehearsal.

The source DB is opened in SQLite read-only mode. This module never approves
pending ingestions, migrates the source, or publishes a snapshot.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from services.catalog_bundle import apply_bundle, validate_bundle
from services.initial_catalog_seed import build_initial_catalog_bundle, normalize_pending_ingestions, stable_id
from storage.models import Base

MARTS = {"emart", "homeplus", "lottemart", "costco"}


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def read_pending_source(database: Path) -> tuple[list[dict], dict]:
    database = database.resolve(strict=True)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Source database failed SQLite quick_check")
        ingestions = [dict(row) for row in connection.execute(
            "SELECT id, crawler_name, crawled_at, items_json, items_count, status "
            "FROM pending_ingestions WHERE lower(status) = 'pending' "
            "AND lower(crawler_name) IN ('emart','homeplus','lottemart','costco') ORDER BY id"
        )]
    totals: Counter = Counter()
    for row in ingestions:
        items = json.loads(row["items_json"])
        if not isinstance(items, list) or len(items) != row["items_count"]:
            raise ValueError(f"Ingestion {row['id']} has invalid JSON/count")
        totals[row["crawler_name"].lower()] += len(items)
    if set(totals) != MARTS or any(value <= 0 for value in totals.values()):
        raise ValueError("Initial source must contain nonempty pending data from all four marts")
    return ingestions, {
        "source_database": str(database), "source_read_only": True,
        "source_sha256": hashlib.sha256(json_bytes(ingestions)).hexdigest(),
        "ingestion_count": len(ingestions), "observation_count": sum(totals.values()),
        "by_mart": dict(sorted(totals.items())),
        "source_ingestions": [{"id": row["id"], "items_count": row["items_count"]} for row in ingestions],
    }


def prepare_assignments(rows: list[dict], classifier: Callable) -> tuple[dict, list[dict]]:
    decisions = [{"raw_record_id": row["raw_record_id"], **classifier(row)} for row in rows]
    grouped = defaultdict(list)
    for row, decision in zip(rows, decisions):
        grouped[(row["source_name"], row["source_record_key"])].append(decision)
    assignments = {}
    for key, members in grouped.items():
        categories = {member.get("unified_category_id") for member in members}
        confidences = [float(member.get("confidence", member.get("classification_confidence", 0))) for member in members]
        if len(categories) != 1 or not next(iter(categories)):
            continue
        # One weak/conflicting observation prevents trusting the whole listing.
        if min(confidences) < 0.8 or any(member.get("review_status") == "pending" for member in members):
            continue
        attribute_values = [member.get("classification_attributes") or {} for member in members]
        if any(not isinstance(value, dict) for value in attribute_values):
            continue
        attribute_candidates = defaultdict(dict)
        for attributes in attribute_values:
            for field, value in attributes.items():
                if value is not None:
                    attribute_candidates[field][json_bytes(value)] = value
        if any(len(values) > 1 for values in attribute_candidates.values()):
            continue  # a changed fat/flavor/etc. fact also requires listing review
        assignments[key] = {
            "unified_category_id": next(iter(categories)),
            "classification_confidence": min(confidences), "review_status": "classified",
            "classification_reason": sorted({str(member.get("classification_reason", member.get("reason", ""))) for member in members}),
        }
        assignments[key]["classification_attributes"] = {
            field: deepcopy(next(iter(values.values()))) for field, values in attribute_candidates.items()
        }
    return assignments, decisions


def merge_review_decisions(rows: list[dict], assignments: dict, document: dict, source_sha256: str) -> tuple[dict, dict]:
    """Apply explicit draft decisions only to the exact reviewed raw snapshot.

    This does not approve a crawl, relax offer checks, or publish a product.
    Proposal-only files deliberately cannot be consumed as reviewed decisions.
    """
    if document.get("schema_version") != "walletsaver-initial-review-v1" or document.get("status") != "reviewed_draft":
        raise ValueError("Expected a reviewed_draft decision document, not an unreviewed proposal")
    if document.get("source_sha256") != source_sha256:
        raise ValueError("Reviewed source snapshot changed; re-review before applying decisions")
    if not str(document.get("reviewed_by") or "").strip():
        raise ValueError("reviewed_by is required")
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["source_name"], row["source_record_key"])].append(row)
    merged = deepcopy(assignments)
    seen = set()
    allowed = {"unified_category_id", "classification_confidence", "canonical_name", "brand",
               "product_group_key", "aliases", "keywords", "package", "classification_attributes"}
    decisions = document.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Review decisions must be an array")
    for decision in decisions:
        key = (decision.get("source_name"), decision.get("source_record_key"))
        if key in seen or key not in grouped:
            raise ValueError(f"Duplicate or absent reviewed source listing: {key}")
        seen.add(key)
        expected = decision.get("expected_observations")
        if not isinstance(expected, list) or len({row.get("raw_record_id") for row in expected}) != len(expected):
            raise ValueError(f"Invalid reviewed observation set: {key}")
        actual = {row["raw_record_id"]: row["raw_payload_sha256"] for row in grouped[key]}
        if actual != {row["raw_record_id"]: row["raw_payload_sha256"] for row in expected}:
            raise ValueError(f"Reviewed raw evidence changed: {key}")
        reason = str(decision.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"Review reason missing: {key}")
        merged[key] = {
            **{field: deepcopy(value) for field, value in decision.items() if field in allowed},
            "review_status": "classified",  # still not DB/publication approval
            "classification_reason": f"reviewed draft by {document['reviewed_by']}: {reason}",
        }
    return merged, {"decision_count": len(seen), "reviewed_by": document["reviewed_by"],
                    "status": "reviewed_draft", "public_approval": False,
                    "document_sha256": hashlib.sha256(json_bytes(document)).hexdigest()}


def conservative_mappings(rows: list[dict], assignments: dict, included_raw_ids: set[str]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        if row["source_category_path"]:
            grouped[(row["source_name"], tuple(row["source_category_path"]))].append(row)
    mappings = []
    for (mart, path), members in sorted(grouped.items()):
        choices = [assignments.get((row["source_name"], row["source_record_key"])) for row in members]
        if not all(choices) or any(row["raw_record_id"] not in included_raw_ids for row in members):
            continue
        leaves = {choice["unified_category_id"] for choice in choices}
        if len(leaves) != 1:
            continue
        mappings.append({
            "mart": mart, "mart_native_id": stable_id("path", mart, list(path)),
            "mart_native_path": " > ".join(path), "unified_category_id": next(iter(leaves)),
            "confidence": min(choice["classification_confidence"] for choice in choices),
            "trust": "auto-aggregate", "decided_by": "initial-catalog-rehearsal",
        })
    return mappings


def prune_unused_categories(bundle: dict) -> None:
    by_id = {row["id"]: row for row in bundle["categories"]}
    used = {row["unified_category_id"] for row in bundle["products"]}
    # Keep the ancestor topology of assigned leaves; do not make an old
    # internal node a product leaf simply by dropping its children.
    internal = {row.get("parent_id") for row in by_id.values()}
    if used & internal:
        raise ValueError("A product assignment points at an internal category")
    for category_id in list(used):
        seen = set()
        while category_id:
            if category_id in seen or category_id not in by_id:
                raise ValueError("Category cycle or missing parent")
            seen.add(category_id)
            used.add(category_id)
            category_id = by_id[category_id].get("parent_id")
    bundle["categories"] = [row for row in bundle["categories"] if row["id"] in used]
    bundle["keywords"] = [row for row in bundle["keywords"] if row["unified_category_id"] in used]


def cross_mart_candidates(rows: list[dict]) -> list[dict]:
    """Candidates only: punctuation-folded identical titles do not auto-merge."""
    grouped = defaultdict(dict)
    for row in rows:
        title_key = re.sub(r"[\W_]", "", row["source_title"].casefold())
        if title_key:
            grouped[title_key][(row["source_name"], row["source_record_key"])] = row
    return [
        {"title_key": key, "review_status": "pending", "members": [
            {field: row[field] for field in ("source_name", "source_record_key", "source_title", "brand", "package", "source_category_path")}
            for _, row in sorted(members.items())
        ]}
        for key, members in sorted(grouped.items())
        if len({mart for mart, _ in members}) > 1
    ]


def rehearse_import(bundle: dict, stage_path: Path, file_hash: str) -> dict:
    # Never reuse an existing database, even for an idempotency rehearsal.
    with stage_path.open("xb"):
        pass
    engine = create_engine(f"sqlite:///{stage_path.resolve().as_posix()}")

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            validation = validate_bundle(session, bundle, file_hash)
            if not validation.ok:
                return {"validation": validation.as_dict(), "applied": False}
            first = apply_bundle(session, bundle, file_hash, user="initial-catalog-rehearsal")
            session.commit()
            counts_before = {table.name: session.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
            second = apply_bundle(session, bundle, file_hash, user="initial-catalog-rehearsal")
            session.commit()
            counts_after = {table.name: session.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
            if not second["idempotent"] or counts_before != counts_after:
                raise ValueError("Repeated bundle import changed table counts")
        with engine.connect() as connection:
            fk = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
        if fk or integrity != "ok":
            raise ValueError("Staging DB failed SQLite integrity/FK checks")
        return {"validation": validation.as_dict(), "applied": True, "first_idempotent": first["idempotent"],
                "second_idempotent": second["idempotent"], "table_counts": counts_after, "integrity_check": integrity, "foreign_key_violations": len(fk)}
    finally:
        engine.dispose()


def render_review(rows: list[dict], decisions: list[dict], bundle: dict) -> str:
    accounting = {row["raw_record_id"]: row for row in bundle["observation_accounting"]}
    names = {row["id"]: row["name_ko"] for row in bundle["categories"]}
    listings = {row["public_source_listing_id"]: row for row in bundle.get("source_listings", [])}
    variants = {row["public_variant_id"]: row for row in bundle.get("variants", [])}
    products = {row["public_product_id"]: row for row in bundle.get("products", [])}
    records = []
    for row, decision in zip(rows, decisions):
        account = accounting[row["raw_record_id"]]
        category = decision.get("unified_category_id") or ""
        listing = listings.get(account.get("public_source_listing_id"), {})
        variant = variants.get(listing.get("public_variant_id"), {})
        product = products.get(variant.get("public_product_id"), {})
        applied_package = {key: variant[key] for key in ("package_quantity", "package_unit", "bundle_count") if key in variant}
        values = [row["raw_record_id"], row["source_name"], row["source_title"], row["price"],
                  json.dumps(row["package"], ensure_ascii=False), json.dumps(applied_package, ensure_ascii=False),
                  product.get("canonical_name", ""), product.get("brand", ""), product.get("public_product_id", ""),
                  product.get("attributes", {}).get("identity_basis", ""), " > ".join(row["source_category_path"]),
                  names.get(category, category), decision.get("classification_reason", decision.get("reason", "")),
                  account["status"], account.get("offer_state", ""), ", ".join(account.get("reasons", []))]
        records.append("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in values) + "</tr>")
    headers = ["원본 행", "마트", "원본 상품명", "판매가", "원본 규격", "적재 규격", "적재 상품군 이름", "적재 브랜드", "상품군 ID", "병합 근거", "원본 경로", "제안 리프", "판정 근거", "준비 상태", "offer 검수 상태", "보류 사유"]
    return """<!doctype html><html lang="ko"><meta charset="utf-8"><title>초기 카탈로그 전량 검토</title>
<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}th{position:sticky;top:0;background:#eef}input{padding:8px;width:420px}tr[hidden]{display:none}</style>
<h1>초기 카탈로그 전량 검토 — 미승인 초안</h1><p>included는 별도 검증 DB에 준비되었다는 뜻이며, 검토·공개 승인을 뜻하지 않습니다. 모든 원본 행을 포함합니다.</p>
<input id="query" placeholder="마트·상품명·분류·보류 사유 검색"><p id="count"></p><table><thead><tr>""" + "".join(f"<th>{heading}</th>" for heading in headers) + "</tr></thead><tbody>" + "".join(records) + """</tbody></table>
<script>const rows=[...document.querySelectorAll('tbody tr')];const q=document.querySelector('#query');function filter(){let n=0;for(const row of rows){row.hidden=!row.textContent.toLowerCase().includes(q.value.toLowerCase());if(!row.hidden)n++}document.querySelector('#count').textContent=n+' / '+rows.length+'개 원본 행'}q.addEventListener('input',filter);filter()</script></html>"""


def prepare_workspace(database: Path, output: Path, *, run_id: str, classifier: Callable, categories: list[dict], keywords: list[dict], review_document: dict | None = None) -> dict:
    ingestions, manifest = read_pending_source(database)
    # Existing artifacts are evidence. Require a fresh directory, never wipe it.
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "source-ingestions.json").write_bytes(json_bytes(ingestions))
    rows = normalize_pending_ingestions(ingestions)
    assignments, decisions = prepare_assignments(rows, classifier)
    review_context = None
    if review_document is not None:
        assignments, review_context = merge_review_decisions(rows, assignments, review_document, manifest["source_sha256"])
        reviewed_keys = {(row["source_name"], row["source_record_key"]) for row in review_document["decisions"]}
        for index, row in enumerate(rows):
            key = (row["source_name"], row["source_record_key"])
            if key in reviewed_keys:
                decisions[index] = {
                    **decisions[index], "initial_classifier_decision": deepcopy(decisions[index]),
                    "reviewed_assignment": deepcopy(assignments[key]),
                    **{field: deepcopy(assignments[key].get(field)) for field in (
                        "unified_category_id", "classification_confidence", "classification_reason", "classification_attributes", "review_status",
                    )},
                    "evidence_type": "reviewed_raw_snapshot",
                }
        (output / "reviewed-decisions.json").write_bytes(json_bytes(review_document))
    bundle = build_initial_catalog_bundle(ingestions, categories=deepcopy(categories), assignments=assignments, run_id=run_id, keywords=keywords)
    bundle["source_manifest"] = manifest
    bundle["review_context"] = review_context
    included = {row["raw_record_id"] for row in bundle["observation_accounting"] if row["status"] == "included"}
    bundle["mart_category_mappings"] = conservative_mappings(rows, assignments, included)
    prune_unused_categories(bundle)
    content = json_bytes(bundle)
    digest = hashlib.sha256(content).hexdigest()
    (output / "catalog-bundle.json").write_bytes(content)
    (output / "classification-decisions.json").write_bytes(json_bytes(decisions))
    candidates = cross_mart_candidates(rows)
    (output / "product-group-candidates.json").write_bytes(json_bytes(candidates))
    (output / "review.html").write_text(render_review(rows, decisions, bundle), encoding="utf-8")
    rehearsal = rehearse_import(bundle, output / "staging.sqlite", digest)
    summary = {**manifest, "run_id": run_id, "bundle_sha256": digest, "source_modified": False,
               "review_context": review_context,
               "public_approval": False, "build_report": bundle["build_report"],
               "category_count": len(bundle["categories"]), "keyword_count": len(bundle["keywords"]),
               "mapping_count": len(bundle["mart_category_mappings"]), "cross_mart_candidate_groups": len(candidates),
               "rehearsal": rehearsal}
    (output / "summary.json").write_bytes(json_bytes(summary))
    return summary
