"""rd8_l2_import.py — L2 산출(matching_updates_final.jsonl)을 L3 import 파이프로 DB 적재.

3 마트(costco/homeplus/lottemart)별로:
 1. dry-run preview
 2. 사용자에게 보고 후 apply (--apply 플래그)
 3. 결과 ApplyResult 출력
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_ADMIN = ROOT / "packages" / "db-admin" / "backend"
sys.path.insert(0, str(DB_ADMIN))
sys.path.insert(0, str(ROOT / "packages" / "shared"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="False면 dry-run만, True면 실제 적용")
    ap.add_argument("--marts", default="costco,homeplus,lottemart")
    args = ap.parse_args()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from config import settings
    from services.external_classification_import import (
        apply_import,
        load_category_whitelist,
    )

    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)

    marts = [m.strip() for m in args.marts.split(",") if m.strip()]
    for mart in marts:
        p = ROOT / "artifacts" / "rd8" / "l2_classified" / mart / "matching_updates_final.jsonl"
        if not p.exists():
            print(f"[{mart}] FILE MISSING: {p}")
            continue
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        payload_bytes = p.read_bytes()

        print(f"\n=== {mart}: {len(rows)} rows ===")
        session = Session()
        try:
            wl = load_category_whitelist(session)
            print(f"  whitelist categories in DB: {len(wl)}")

            result_dry = apply_import(
                "matching", rows, payload_bytes, session,
                dry_run=True, importer="rd8-l2-import-tool",
            )
            print(f"  [dry-run] ok={result_dry.ok} counts={result_dry.counts}")
            if result_dry.error:
                print(f"  error={result_dry.error}")
            if not result_dry.ok:
                failed = result_dry.counts.get("failed_items", []) if isinstance(result_dry.counts, dict) else []
                for f in failed[:10]:
                    print(f"    FAIL row={f.get('row')} field={f.get('field')} reason={f.get('reason')}")
                session.rollback()
                continue

            if not args.apply:
                session.rollback()
                continue

            result = apply_import(
                "matching", rows, payload_bytes, session,
                dry_run=False, importer="rd8-l2-import-tool",
            )
            print(f"  [apply] ok={result.ok} counts={result.counts}")
            if result.ok:
                session.commit()
            else:
                session.rollback()
                print(f"  error={result.error}")
        finally:
            session.close()


if __name__ == "__main__":
    main()
