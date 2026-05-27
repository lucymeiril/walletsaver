r"""Round R G2 unified category tree seed CLI.

Usage:
    py -3 -m db_admin.scripts.g2_seed_unified_tree --yaml devlog\round-R\g2-unified-tree.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from services.base import managed_session
from services.unified_categories import upsert_mapping
from storage.models import UnifiedCategory


def _slug(node_id: str) -> str:
    return node_id.split(".")[-1]


def _level(node_id: str) -> int:
    return node_id.count(".")


def _name_path(node_id: str, names: dict[str, str]) -> str:
    parts = node_id.split(".")
    ids = [".".join(parts[:idx]) for idx in range(1, len(parts) + 1)]
    return " > ".join(names.get(part_id, part_id) for part_id in ids)


def seed_from_yaml(yaml_path: Path) -> dict[str, int]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if data.get("schema") != "unified_category_tree.v1":
        raise ValueError("지원하지 않는 G2 YAML schema입니다.")

    nodes: list[dict[str, Any]] = list(data.get("nodes") or [])
    node_by_id = {str(node["id"]): node for node in nodes}
    names = {node_id: str(node.get("name") or node_id) for node_id, node in node_by_id.items()}
    origin = str(data.get("authoritative_mart") or "g2-unified-tree")

    inserted_categories = 0
    updated_categories = 0
    inserted_mappings = 0
    updated_mappings = 0
    skipped_mappings = 0

    with managed_session() as session:
        for sort_order, node in enumerate(sorted(nodes, key=lambda n: (_level(str(n["id"])), str(n["id"])))):
            node_id = str(node["id"])
            existing = session.get(UnifiedCategory, node_id)
            if existing is None:
                existing = UnifiedCategory(id=node_id)
                session.add(existing)
                inserted_categories += 1
            else:
                updated_categories += 1
            existing.parent_id = node.get("parent_id")
            existing.slug = _slug(node_id)
            existing.name_ko = str(node.get("name") or node_id)
            existing.level = _level(node_id)
            existing.sort_order = sort_order
            existing.source_origin = origin

        session.flush()

        for node in nodes:
            node_id = str(node["id"])
            lotte_values = ((node.get("source_natives") or {}).get("lottemart") or [])
            native_path = _name_path(node_id, names)
            for native in lotte_values:
                mapping, action = upsert_mapping(
                    session,
                    mart="lottemart",
                    mart_native_id=str(native),
                    mart_native_path=native_path,
                    unified_category_id=node_id,
                    trust="auto-aggregate",
                    confidence=0.8,
                    decided_by="g2_seed_unified_tree",
                )
                if action == "created":
                    inserted_mappings += 1
                elif action == "updated":
                    updated_mappings += 1
                else:
                    skipped_mappings += 1

    return {
        "categories_inserted": inserted_categories,
        "categories_updated": updated_categories,
        "lottemart_mappings_inserted": inserted_mappings,
        "lottemart_mappings_updated": updated_mappings,
        "lottemart_mappings_skipped": skipped_mappings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Round R G2 unified categories and lottemart auto mappings.")
    parser.add_argument("--yaml", required=True, type=Path, help="g2-unified-tree.yaml 경로")
    args = parser.parse_args()
    result = seed_from_yaml(args.yaml)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
