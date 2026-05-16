from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PLAN_PATH = REPO_ROOT / "tools" / "mart3_live_input_plan.py"
spec = importlib.util.spec_from_file_location("mart3_live_input_plan", PLAN_PATH)
assert spec and spec.loader
plan_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_tool)


def _artifact(path: Path, mart: str, store: str) -> Path:
    rows = [
        {"name": f"{store} 상품 {index}", "store": store, "sale_price": 1000 + index, "detail_url": f"https://example.invalid/{mart}/{index}"}
        for index in range(3)
    ]
    path.write_text(
        json.dumps(
            {
                "run_id": f"{mart}-evidence",
                "validation_run": {"item_counts": {"records": len(rows), "selected_items": len(rows)}},
                "decisions": {"db_admin_submit_allowed": False},
                "provider_response_summary": {"called": mart == "emart"},
                "raw_selected_items": rows,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_build_plan_uses_two_items_per_mart_and_bounded_db_acceptance_command(tmp_path: Path) -> None:
    evidence = {
        "emart": _artifact(tmp_path / "emart.json", "emart", "이마트"),
        "lottemart": _artifact(tmp_path / "lottemart.json", "lottemart", "롯데마트"),
        "homeplus": _artifact(tmp_path / "homeplus.json", "homeplus", "홈플러스"),
    }

    plan = plan_tool.build_plan(tmp_path / "out", evidence_artifacts=evidence)

    assert plan["scope"].startswith("prepare-only")
    assert plan["selected_item_count"] == 6
    assert plan["caps"]["items_per_mart"] == 2
    assert plan["caps"]["total_max_items"] == 6
    assert plan["caps"]["max_provider_calls"] == 3
    assert plan["caps"]["ai_batch_size"] == 2
    command = plan["commands"]["actual_db_acceptance_run"]
    assert command[1] == "tools\\one_shot_db_build_orchestrator.py"
    assert "--real-readiness" in command
    assert command[command.index("--live-batch-max-items") + 1] == "6"
    assert command[command.index("--live-batch-max-provider-calls") + 1] == "3"
    assert command[command.index("--live-batch-ai-batch-size") + 1] == "2"
    assert command[command.index("--live-batch-label-chunk-retries") + 1] == "1"
    assert command[command.index("--live-batch-label-call-min-interval-seconds") + 1] == "12"
    assert "--allow-live-ai-provider" in command
    assert "--allow-live-ai-labeling" in command
    assert "--allow-db-mutation" in command
    assert "--allow-db-admin-submit" not in command
    assert "--allow-large-live-batch" not in command
    assert any("--real-readiness" in requirement and "fixture/stub fallback" in requirement for requirement in plan["db_submit_final_approve_requirements"])
    assert any("--allow-db-admin-submit" in requirement and "preflight" in requirement for requirement in plan["db_submit_final_approve_requirements"])
    assert "AIza" not in json.dumps(plan, ensure_ascii=False)


def test_write_plan_splits_manifest_from_input_rows(tmp_path: Path) -> None:
    evidence = {
        "emart": _artifact(tmp_path / "emart.json", "emart", "이마트"),
        "lottemart": _artifact(tmp_path / "lottemart.json", "lottemart", "롯데마트"),
        "homeplus": _artifact(tmp_path / "homeplus.json", "homeplus", "홈플러스"),
    }
    artifact_dir = tmp_path / "out"
    plan = plan_tool.build_plan(artifact_dir, evidence_artifacts=evidence)

    input_path, manifest_path = plan_tool.write_plan(plan, artifact_dir)

    assert len(json.loads(input_path.read_text(encoding="utf-8"))) == 6
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["selected_item_count"] == 6
    assert "selected_items" not in manifest
    assert manifest["expected_output_artifacts"]["input_json"].endswith("mart3-live-crawler-batch.json")
