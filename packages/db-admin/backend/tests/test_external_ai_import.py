from __future__ import annotations

import json
from pathlib import Path

import yaml

from services.external_ai_import import validate_import_bundle

CANON_HASH = "0123456789abcdef0123456789abcdef01234567"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def test_validate_import_bundle_ok(tmp_path: Path):
    _write_jsonl(
        tmp_path / "matching_updates.jsonl",
        [
            {
                "canon_hash": CANON_HASH,
                "category_id": "rice",
                "keywords": ["쌀", "백미"],
                "confidence": 0.93,
                "source": "external-ai",
                "reason": "상품명과 원본 카테고리가 쌀 계열",
            }
        ],
    )
    (tmp_path / "category_keyword_updates.yaml").write_text(
        yaml.safe_dump(
            {
                "new_categories": [
                    {
                        "id": "instant_rice",
                        "name_kr": "즉석밥",
                        "parent_id": "processed_food",
                        "default_unit_kind": "GRAM_PER_100G",
                        "reason": "즉석밥 전용 분류 필요",
                    }
                ],
                "keywords": [
                    {
                        "keyword": "즉석밥",
                        "category_id": "instant_rice",
                        "synonyms": ["햇반"],
                        "reason": "검색 보강",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        tmp_path / "product_updates.jsonl",
        [
            {
                "canon_hash": CANON_HASH,
                "brand": "CJ",
                "normalized_name": "CJ 햇반 백미 210g",
                "pack_qty": 210,
                "pack_unit": "g",
            }
        ],
    )

    result = validate_import_bundle(tmp_path)

    assert result.ok, result.errors
    assert result.counts == {
        "matching_updates": 1,
        "new_categories": 1,
        "keywords": 1,
        "product_updates": 1,
    }
    assert result.matching_updates[0].keywords == ["쌀", "백미"]


def test_validate_import_bundle_schema_violation(tmp_path: Path):
    _write_jsonl(
        tmp_path / "matching_updates.jsonl",
        [
            {
                "canon_hash": "bad-hash",
                "category_id": "Rice Bad",
                "keywords": ["쌀"],
                "confidence": 1.5,
                "source": "external-ai",
            }
        ],
    )
    (tmp_path / "category_keyword_updates.yaml").write_text(
        yaml.safe_dump({"new_categories": [], "keywords": []}, allow_unicode=True),
        encoding="utf-8",
    )
    _write_jsonl(tmp_path / "product_updates.jsonl", [{"canon_hash": CANON_HASH}])

    result = validate_import_bundle(tmp_path)

    assert not result.ok
    assert len(result.errors) == 2
    assert {error["file"] for error in result.errors} == {"matching_updates.jsonl", "product_updates.jsonl"}
    assert result.counts["matching_updates"] == 0
    assert result.counts["product_updates"] == 0
