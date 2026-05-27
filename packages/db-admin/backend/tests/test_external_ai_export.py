from __future__ import annotations

import json
from pathlib import Path

import yaml

from services.external_ai_export import export_unclassified_bundle


def test_export_unclassified_bundle_empty_db(tmp_path: Path):
    out_dir = tmp_path / "external-ai-bundle"

    manifest = export_unclassified_bundle(out_dir)

    expected_files = {
        "manifest.json",
        "unclassified.jsonl",
        "category_list.yaml",
        "keyword_list.yaml",
        "instructions.md",
    }
    assert expected_files.issubset({p.name for p in out_dir.iterdir()})
    assert manifest.schema_version == "external-ai-classify-v1"
    assert manifest.counts["unclassified"] == 0
    assert (out_dir / "unclassified.jsonl").read_text(encoding="utf-8") == ""

    manifest_json = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_json["files"]["unclassified"]["rows"] == 0
    assert "external_classify_instructions_v1.md" in manifest_json["source_prompt"]

    keyword_payload = yaml.safe_load((out_dir / "keyword_list.yaml").read_text(encoding="utf-8"))
    assert keyword_payload == {"keywords": []}
    assert "공용 지침 원본" in (out_dir / "instructions.md").read_text(encoding="utf-8")
