#!/usr/bin/env python3
"""Prepare a new review directory and a separate SQLite import rehearsal.

No source mutation, automatic ingestion approval, or public snapshot creation.
Run from the repository: python tools/prepare_initial_catalog.py --out .debug-artifacts/initial-catalog-RUN --run-id RUN
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "shared"))
sys.path.insert(0, str(ROOT / "packages" / "db-admin" / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / ".walletsavior" / "admin.sqlite")
    parser.add_argument("--out", type=Path, required=True, help="New, ignored review directory; must not exist")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--review-decisions", type=Path, help="Explicit reviewed draft assignments pinned to raw snapshot hashes")
    args = parser.parse_args()
    from services.initial_catalog_workspace import prepare_workspace
    from services.initial_taxonomy import classify_record, keyword_definitions, taxonomy_categories
    summary = prepare_workspace(args.db, args.out, run_id=args.run_id, classifier=classify_record,
                                categories=taxonomy_categories(), keywords=keyword_definitions(),
                                review_document=json.loads(args.review_decisions.read_text(encoding="utf-8")) if args.review_decisions else None)
    print(json.dumps({
        "output": str(args.out.resolve()), "source_sha256": summary["source_sha256"],
        "build_report": {key: value for key, value in summary["build_report"].items() if key != "source_ingestion_ids"},
        "category_count": summary["category_count"], "keyword_count": summary["keyword_count"],
        "mapping_count": summary["mapping_count"], "cross_mart_candidate_groups": summary["cross_mart_candidate_groups"],
        "validation_ok": summary["rehearsal"]["validation"]["ok"],
        "validation_errors": summary["rehearsal"]["validation"]["errors"],
        "second_import_idempotent": summary["rehearsal"].get("second_idempotent"),
        "source_modified": False, "public_approval": False,
    }, ensure_ascii=True, indent=2))
    return 0 if summary["rehearsal"]["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
