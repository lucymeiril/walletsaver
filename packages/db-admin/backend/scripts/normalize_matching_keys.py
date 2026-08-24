"""Preview/apply MatchingEntry key normalization.

Usage:
    py packages/db-admin/backend/scripts/normalize_matching_keys.py
    py packages/db-admin/backend/scripts/normalize_matching_keys.py --apply

Dry-run is the default. ``--apply`` creates a source DB backup before mutating
matching_entries.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_SHARED = _BACKEND.parent.parent / "shared"
for path in (str(_BACKEND), str(_SHARED)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config import settings  # noqa: E402
from services.backup import create_backup  # noqa: E402
from services.base import get_session  # noqa: E402
from services.matching_key_migration import normalize_matching_keys  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize persistent matching keys")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply changes; default is dry-run only",
    )
    args = parser.parse_args()

    backup_path = None
    if args.apply:
        backup_path = create_backup(
            settings.DATABASE_URL,
            reason="pre_matching_key_normalization",
        )

    session = get_session()
    try:
        report = normalize_matching_keys(session, dry_run=not args.apply)
        if args.apply:
            session.commit()
        else:
            session.rollback()
        payload = report.to_dict()
        payload["backup_path"] = str(backup_path) if backup_path else None
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
