r"""Export Round R G3 unmatched isolation bundle.

Example:
    py -3 scripts\g3_export_unmatched.py --out artifacts\g3-unmatched-bundle
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "packages" / "db-admin" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.base import get_session  # noqa: E402
from services.external_ai_export import export_unclassified_bundle  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export external-AI bundle with unmatched isolation cases")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "g3-unmatched-bundle", help="bundle output directory")
    args = parser.parse_args()

    session = get_session()
    try:
        manifest = export_unclassified_bundle(args.out, session=session)
    finally:
        session.close()
    print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
