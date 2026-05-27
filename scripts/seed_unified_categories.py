r"""Seed unified category tree and mart native category mappings.

Usage:
    set DATABASE_URL=sqlite:///E:/pdf/capston01/packages/db-admin/backend/walletguardian.db
    py -3 scripts\seed_unified_categories.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_ADMIN_BACKEND = REPO_ROOT / "packages" / "db-admin" / "backend"
if str(DB_ADMIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(DB_ADMIN_BACKEND))

from services.base import managed_session  # noqa: E402
from services.unified_categories import upsert_mapping  # noqa: E402
from storage.models import UnifiedCategory  # noqa: E402

DEFAULT_SEED = REPO_ROOT / "packages" / "shared" / "data" / "unified_category_seed.yaml"


def _load_seed(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("schema") != "unified_category_seed.v1":
        raise ValueError(f"Unsupported seed schema in {path}")
    return data


def seed(path: Path = DEFAULT_SEED) -> dict[str, int]:
    data = _load_seed(path)
    categories = list(data.get("categories") or [])
    mappings = list(data.get("mappings") or [])
    stats = {
        "categories_inserted": 0,
        "categories_updated": 0,
        "mappings_inserted": 0,
        "mappings_updated": 0,
        "mappings_conflict": 0,
    }

    with managed_session() as session:
        for item in categories:
            category_id = str(item["id"])
            category = session.get(UnifiedCategory, category_id)
            if category is None:
                category = UnifiedCategory(id=category_id)
                session.add(category)
                stats["categories_inserted"] += 1
            else:
                stats["categories_updated"] += 1

            category.parent_id = item.get("parent_id")
            category.slug = str(item.get("slug") or category_id.split(".")[-1])
            category.name_ko = str(item["name_ko"])
            category.level = int(item.get("level", category_id.count(".")))
            category.sort_order = int(item.get("sort_order", 0))
            category.source_origin = str(data.get("source") or "round-U")[:50]

        session.flush()

        for item in mappings:
            _, action = upsert_mapping(
                session,
                mart=str(item["mart"]),
                mart_native_id=str(item["mart_native_id"]),
                mart_native_path=item.get("mart_native_path"),
                unified_category_id=str(item["unified_category_id"]),
                trust=str(item.get("trust") or "auto-aggregate"),
                confidence=float(item.get("confidence", 0.8)),
                decided_by="seed_unified_categories",
            )
            if action == "created":
                stats["mappings_inserted"] += 1
            elif action == "updated":
                stats["mappings_updated"] += 1
            else:
                stats["mappings_conflict"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed unified categories and native mart mappings.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="Seed YAML path")
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        print("DATABASE_URL is not set; using db-admin backend default SQLite database.")

    stats = seed(args.seed)
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
