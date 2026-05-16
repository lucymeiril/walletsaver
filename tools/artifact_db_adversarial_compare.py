"""Compare source artifacts against local DB/public verification rows."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_PROOF_DIR = REPO_ROOT / ".walletsavior-live-validation" / "live-db-submit-safe-row-scale"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "artifact-db-adversarial-compare"

CRITICAL_FIELDS = (
    "raw_title",
    "current_price",
    "original_price",
    "discount_percent",
    "source_url",
    "detail_url",
    "image_url",
    "unit",
    "package_quantity",
    "package_unit",
    "bundle_count",
    "price_per_100g",
    "standard_unit_price",
    "category",
    "source",
)

SOURCE_ALIASES = {
    "이마트": "emart",
    "emart": "emart",
    "트레이더스": "traders",
    "traders": "traders",
    "homeplus": "homeplus",
    "홈플러스": "homeplus",
    "lottemart": "lottemart",
    "롯데마트": "lottemart",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_items(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        # Live validation artifacts keep the crawler-shaped rows in
        # raw_selected_items and the comparable ingestion rows, with stable
        # raw_record_id values, in raw_records. Prefer the latter when present
        # so artifact-vs-DB comparison does not fall back to brittle title/url
        # matching for large one-shot proofs.
        for key in ("raw_records", "items", "raw_selected_items", "records"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("원", "").strip())
    except ValueError:
        return None


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _field_equal(left: Any, right: Any, field: str) -> bool:
    if field == "source":
        return SOURCE_ALIASES.get(_str(left).lower(), _str(left).lower()) == SOURCE_ALIASES.get(
            _str(right).lower(), _str(right).lower()
        )
    if field == "category" and _str(left) == "" and _str(right) in {"", "mart3.uncategorized", "uncategorized"}:
        return True
    if field == "discount_percent" and {_num(left), _num(right)} <= {0.0, None}:
        return True
    if field in {
        "current_price",
        "original_price",
        "discount_percent",
        "package_quantity",
        "bundle_count",
        "price_per_100g",
        "standard_unit_price",
    }:
        lnum, rnum = _num(left), _num(right)
        if lnum is None and rnum is None:
            return True
        if lnum is None or rnum is None:
            return False
        return abs(lnum - rnum) <= max(0.01, abs(lnum) * 0.0001)
    return _str(left) == _str(right)


def _is_suspicious_diff(source: dict[str, Any], target: dict[str, Any], diff: dict[str, Any]) -> bool:
    field = diff["field"]
    source_value = diff["source"]
    target_value = diff["target"]
    if field in {"package_quantity", "package_unit", "price_per_100g", "standard_unit_price"}:
        return source_value not in (None, "")
    if field == "bundle_count":
        return _num(source_value) not in (None, 1.0)
    if field == "unit":
        source_unit = _str(source_value).lower()
        target_has_package = target.get("package_quantity") not in (None, "") and target.get("package_unit") not in (None, "")
        # SSG-style rows often expose the comparison basis ("100g") as unit,
        # while the DB projection stores the package unit parsed from the title.
        return not (target_has_package and source_unit in {"", "10g", "100g", "1kg", "100ml", "1l"})
    return True


def _source_id(row: dict[str, Any]) -> str:
    payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else row
    raw_id = row.get("raw_record_id") or payload.get("raw_record_id")
    if raw_id:
        return str(raw_id)
    source = payload.get("source") or payload.get("source_name") or row.get("source_name") or payload.get("store")
    url = payload.get("detail_url") or payload.get("source_url") or row.get("source_url")
    title = payload.get("name") or payload.get("raw_title") or row.get("raw_title")
    return f"{_str(source).lower()}|{_str(url)}|{_str(title)}"


def normalize_source_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else row
    attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    source = payload.get("source") or attrs.get("source") or attrs.get("source_name") or row.get("source_name") or payload.get("store")
    price_per_100g = payload.get("price_per_100g")
    unit_text = payload.get("display_unit") or payload.get("unit")
    bundle_count = payload.get("bundle_count") or _infer_bundle_count(unit_text) or 1
    return {
        "raw_record_id": row.get("raw_record_id") or payload.get("raw_record_id"),
        "match_key": _source_id(row),
        "raw_title": payload.get("name") or row.get("raw_title") or payload.get("raw_title"),
        "current_price": payload.get("sale_price") if payload.get("sale_price") is not None else row.get("raw_price"),
        "original_price": payload.get("original_price"),
        "discount_percent": payload.get("discount_percent"),
        "source_url": payload.get("source_url") or row.get("source_url") or payload.get("detail_url"),
        "detail_url": payload.get("detail_url") or payload.get("source_url") or row.get("source_url"),
        "image_url": payload.get("image_url") or attrs.get("image_url"),
        "unit": unit_text,
        "package_quantity": payload.get("package_quantity"),
        "package_unit": payload.get("package_unit"),
        "bundle_count": bundle_count,
        "price_per_100g": price_per_100g,
        "standard_unit_price": _expected_standard_unit_price(
            payload.get("sale_price") if payload.get("sale_price") is not None else row.get("raw_price"),
            payload.get("package_quantity"),
            payload.get("package_unit"),
            bundle_count,
        ),
        "category": payload.get("category"),
        "source": source,
    }


def _infer_bundle_count(unit_text: Any) -> int | None:
    text = _str(unit_text).lower().replace("*", "×").replace("x", "×")
    if "×" not in text:
        return None
    tail = text.rsplit("×", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return int(digits) if digits else None


def _expected_standard_unit_price(price: Any, quantity: Any, unit: Any, bundle_count: Any = 1) -> float | None:
    price_num, qty_num = _num(price), _num(quantity)
    bundle_num = _num(bundle_count) or 1
    unit_text = _str(unit).lower()
    if price_num is None or qty_num in (None, 0):
        return None
    total_qty = qty_num * bundle_num
    if unit_text in {"g", "ml"}:
        return round(price_num / total_qty * 1000, 2)
    if unit_text in {"kg", "l", "liter", "litre"}:
        return round(price_num / total_qty, 2)
    return None


def _proof_public_rows(proof: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in proof.get("db_admin_submit_result", {}).get("results", []):
        verification = result.get("ai_safe_final_approve", {}).get("public_db_verification", {})
        for item in verification.get("items") or []:
            published = item.get("published_row") or {}
            raw_record_id = result.get("raw_record_id") or published.get("raw_data", {}).get("raw_record", {}).get("raw_record_id")
            rows.append(normalize_public_row(published, raw_record_id=raw_record_id, row_kind="proof_public_verification"))
    return rows


def normalize_public_row(row: dict[str, Any], *, raw_record_id: str | None = None, row_kind: str = "public") -> dict[str, Any]:
    raw_data = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
    raw_record = raw_data.get("raw_record") if isinstance(raw_data.get("raw_record"), dict) else {}
    raw_payload = raw_data.get("raw_payload") if isinstance(raw_data.get("raw_payload"), dict) else {}
    normalized = raw_data.get("normalized") if isinstance(raw_data.get("normalized"), dict) else {}
    source_listing = normalized.get("source_listing") if isinstance(normalized.get("source_listing"), dict) else {}
    variant = normalized.get("product_variant") if isinstance(normalized.get("product_variant"), dict) else {}
    offer = normalized.get("offer_event") if isinstance(normalized.get("offer_event"), dict) else {}
    product = normalized.get("canonical_product") if isinstance(normalized.get("canonical_product"), dict) else {}
    sale_offer = raw_data.get("sale_offer") if isinstance(raw_data.get("sale_offer"), dict) else {}
    category_evidence = raw_data.get("category_evidence") if isinstance(raw_data.get("category_evidence"), dict) else {}
    source = (
        row.get("source")
        or source_listing.get("source_name")
        or sale_offer.get("source_name")
        or raw_payload.get("source")
        or raw_record.get("source_name")
    )
    title = source_listing.get("source_title") or sale_offer.get("source_title") or raw_payload.get("name")
    url = source_listing.get("source_url") or sale_offer.get("source_url") or row.get("source_url") or raw_payload.get("detail_url")
    normalized_row = {
        "raw_record_id": raw_record_id or offer.get("raw_record_id") or raw_record.get("raw_record_id"),
        "row_kind": row_kind,
        "db_table": row.get("table"),
        "db_id": row.get("id"),
        "product_id": row.get("product_id"),
        "match_key": "",
        "raw_title": title,
        "current_price": offer.get("current_price") if offer.get("current_price") is not None else row.get("price"),
        "original_price": offer.get("original_price") if offer.get("original_price") is not None else row.get("original_price"),
        "discount_percent": offer.get("discount_percent") if offer.get("discount_percent") is not None else _discount_to_percent(row.get("discount_rate")),
        "source_url": url,
        "detail_url": url,
        "image_url": source_listing.get("image_url") or sale_offer.get("image_url") or product.get("primary_image_url") or raw_payload.get("image_url"),
        "unit": variant.get("display_unit") or raw_data.get("display_unit") or raw_payload.get("display_unit") or raw_payload.get("unit"),
        "package_quantity": variant.get("package_quantity") if variant.get("package_quantity") is not None else raw_data.get("package_quantity"),
        "package_unit": variant.get("package_unit") or raw_data.get("package_unit"),
        "bundle_count": variant.get("bundle_count") or 1,
        "price_per_100g": offer.get("price_per_100g") if offer.get("price_per_100g") is not None else sale_offer.get("price_per_100g"),
        "standard_unit_price": offer.get("standard_unit_price") if offer.get("standard_unit_price") is not None else sale_offer.get("standard_unit_price"),
        "category": product.get("category_name") if product.get("category_name") is not None else category_evidence.get("safe_category_display_label", raw_payload.get("category")),
        "source": source,
    }
    normalized_row["match_key"] = (
        str(normalized_row["raw_record_id"])
        if normalized_row.get("raw_record_id")
        else f"{_str(source).lower()}|{_str(url)}|{_str(title)}"
    )
    return normalized_row


def _discount_to_percent(value: Any) -> float | None:
    num = _num(value)
    if num is None:
        return None
    return round(num * 100, 4) if abs(num) <= 1 else num


def _sqlite_rows(sqlite_path: Path | None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not sqlite_path or not sqlite_path.exists():
        return [], {}
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    try:
        for table in ("products", "discount_history", "normalized_source_listings", "normalized_offer_events"):
            counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
        query = """
            select
                oe.raw_record_id,
                oe.public_offer_event_id,
                oe.price,
                oe.original_price,
                oe.discount_rate,
                oe.standard_unit_price,
                oe.price_per_100g,
                oe.raw_evidence,
                sl.source_name,
                sl.source_title,
                sl.source_url,
                sl.image_url,
                sl.source_unit_text,
                pv.package_quantity,
                pv.package_unit,
                pv.display_unit,
                pv.bundle_count,
                cp.category_id,
                cp.canonical_name,
                cp.primary_image_url
            from normalized_offer_events oe
            join normalized_source_listings sl on sl.public_source_listing_id = oe.public_source_listing_id
            join normalized_product_variants pv on pv.public_variant_id = sl.public_variant_id
            join normalized_canonical_products cp on cp.public_product_id = pv.public_product_id
            order by oe.raw_record_id
        """
        for db_row in con.execute(query):
            raw_evidence = _loads_maybe(db_row["raw_evidence"])
            raw_payload = raw_evidence.get("raw_payload") if isinstance(raw_evidence.get("raw_payload"), dict) else {}
            row = {
                "raw_record_id": db_row["raw_record_id"],
                "row_kind": "sqlite_normalized_projection",
                "db_table": "normalized_offer_events",
                "db_id": db_row["public_offer_event_id"],
                "product_id": None,
                "match_key": str(db_row["raw_record_id"]),
                "raw_title": db_row["source_title"],
                "current_price": db_row["price"],
                "original_price": db_row["original_price"],
                "discount_percent": _discount_to_percent(db_row["discount_rate"]),
                "source_url": db_row["source_url"],
                "detail_url": db_row["source_url"],
                "image_url": db_row["image_url"] or db_row["primary_image_url"],
                "unit": db_row["display_unit"] or db_row["source_unit_text"],
                "package_quantity": db_row["package_quantity"],
                "package_unit": db_row["package_unit"],
                "bundle_count": db_row["bundle_count"],
                "price_per_100g": db_row["price_per_100g"],
                "standard_unit_price": db_row["standard_unit_price"],
                "category": db_row["category_id"] or raw_payload.get("category"),
                "source": db_row["source_name"],
            }
            rows.append(row)
    finally:
        con.close()
    return rows, counts


def _loads_maybe(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def compare_rows(source_rows: list[dict[str, Any]], target_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sources = [normalize_source_row(row) for row in source_rows]
    source_by_key = {row["match_key"]: row for row in sources}
    source_by_url_title = {
        f"{_str(row.get('source')).lower()}|{_str(row.get('detail_url') or row.get('source_url'))}|{_str(row.get('raw_title'))}": row
        for row in sources
    }
    matched: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    target_seen: set[int] = set()

    for source in sources:
        candidates = [
            (index, target)
            for index, target in enumerate(target_rows)
            if target.get("match_key") == source["match_key"]
            or f"{_str(target.get('source')).lower()}|{_str(target.get('detail_url') or target.get('source_url'))}|{_str(target.get('raw_title'))}" in source_by_url_title
            and source_by_url_title[
                f"{_str(target.get('source')).lower()}|{_str(target.get('detail_url') or target.get('source_url'))}|{_str(target.get('raw_title'))}"
            ]
            is source
        ]
        if not candidates:
            continue
        index, target = candidates[0]
        target_seen.add(index)
        diffs = []
        for field in CRITICAL_FIELDS:
            if not _field_equal(source.get(field), target.get(field), field):
                diffs.append({"field": field, "source": source.get(field), "target": target.get(field)})
        entry = {"match_key": source["match_key"], "target_row_kind": target.get("row_kind"), "diffs": diffs}
        matched.append(entry)
        if diffs:
            changed.append(entry)
            suspicious.extend(
                {
                    "match_key": source["match_key"],
                    "target_row_kind": target.get("row_kind"),
                    "field": diff["field"],
                    "source": diff["source"],
                    "target": diff["target"],
                    "reason": "source_owned_field_changed",
                }
                for diff in diffs
                if diff["field"] in CRITICAL_FIELDS and _is_suspicious_diff(source, target, diff)
            )

    missing = [row for row in sources if not any(entry["match_key"] == row["match_key"] for entry in matched)]
    extra = [target for index, target in enumerate(target_rows) if index not in target_seen]
    duplicate_keys = _duplicate_keys(sources, target_rows)
    return {
        "counts": {
            "source_rows": len(sources),
            "target_rows": len(target_rows),
            "matched_rows": len(matched),
            "missing_rows": len(missing),
            "extra_target_rows": len(extra),
            "changed_rows": len(changed),
            "duplicate_key_groups": len(duplicate_keys),
            "suspicious_fields": len(suspicious),
        },
        "matched": matched,
        "missing_source_rows": missing,
        "extra_target_rows": extra,
        "changed_rows": changed,
        "duplicate_keys": duplicate_keys,
        "suspicious_changed_fields": suspicious,
    }


def _duplicate_keys(sources: list[dict[str, Any]], targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for label, rows in (("source", sources), ("target", targets)):
        counter = Counter(row.get("match_key") for row in rows if row.get("match_key"))
        groups.extend({"side": label, "key": key, "count": count} for key, count in sorted(counter.items()) if count > 1)
    return groups


def latest_live_proof(proof_dir: Path = DEFAULT_LIVE_PROOF_DIR) -> Path:
    candidates = sorted(proof_dir.glob("local-db-submit-safe-row-scale-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"no live DB proof JSON found under {proof_dir}")
    return candidates[0]


def build_comparison(proof_json: Path, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    proof = _load_json(proof_json)
    input_json = (REPO_ROOT / proof["source"]["input_json"]).resolve()
    source_rows = _load_json_items(input_json)
    proof_rows = _proof_public_rows(proof)
    sqlite_path = proof_json.with_suffix(".sqlite")
    sqlite_rows, sqlite_counts = _sqlite_rows(sqlite_path)
    proof_comparison = compare_rows(source_rows, proof_rows)
    sqlite_comparison = compare_rows(source_rows, sqlite_rows)
    aggregate_counts = {
        "matched_rows": min(proof_comparison["counts"]["matched_rows"], sqlite_comparison["counts"]["matched_rows"]),
        "missing_rows": max(proof_comparison["counts"]["missing_rows"], sqlite_comparison["counts"]["missing_rows"]),
        "changed_rows": proof_comparison["counts"]["changed_rows"] + sqlite_comparison["counts"]["changed_rows"],
        "duplicate_key_groups": proof_comparison["counts"]["duplicate_key_groups"] + sqlite_comparison["counts"]["duplicate_key_groups"],
        "suspicious_fields": proof_comparison["counts"]["suspicious_fields"] + sqlite_comparison["counts"]["suspicious_fields"],
        "source_rows": len(source_rows),
        "proof_public_rows": len(proof_rows),
        "sqlite_projection_rows": len(sqlite_rows),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"artifact-db-adversarial-compare-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
    artifact = {
        "schema": "walletsavior.artifact_db_adversarial_compare.v1",
        "created_at": datetime.now().isoformat(),
        "summary": {
            "compared": [
                "raw_title",
                "current_price",
                "original_price",
                "discount_percent",
                "source_url",
                "detail_url",
                "image_url",
                "unit",
                "package_quantity",
                "package_unit",
                "bundle_count",
                "price_per_100g",
                "standard_unit_price",
                "category",
                "source",
                "product_count",
                "history_count",
                "duplicate_keys",
                "missing_rows",
                "suspicious_changed_fields",
            ],
            "result": (
                f"{aggregate_counts['matched_rows']} matched, {aggregate_counts['missing_rows']} missing, "
                f"{aggregate_counts['changed_rows']} changed, "
                f"{aggregate_counts['duplicate_key_groups']} duplicate key groups, "
                f"{aggregate_counts['suspicious_fields']} suspicious field changes"
            ),
        },
        "selection": {
            "mode": "latest_live_db_submit_safe_row_scale",
            "proof_json": str(proof_json),
            "sqlite_db": str(sqlite_path) if sqlite_path.exists() else None,
            "source_input_json": str(input_json),
            "reason": "no newer local DB one-shot artifact was present during comparison",
        },
        "db_counts": {
            "proof_product_rows": proof.get("local_db", {}).get("counts", {}).get("products"),
            "proof_discount_history_rows": proof.get("local_db", {}).get("counts", {}).get("discount_history"),
            "sqlite": sqlite_counts,
        },
        "aggregate_counts": aggregate_counts,
        "comparisons": {
            "source_vs_public_verification": proof_comparison,
            "source_vs_local_sqlite_projection": sqlite_comparison,
        },
        "blockers": [],
    }
    artifact["artifact_path"] = str(out_path)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifact


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-json", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    proof_json = args.proof_json or latest_live_proof()
    artifact = build_comparison(proof_json.resolve(), args.output_dir)
    print(json.dumps({"artifact_path": artifact["artifact_path"], **artifact["aggregate_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
