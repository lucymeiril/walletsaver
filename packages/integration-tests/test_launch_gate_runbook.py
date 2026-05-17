"""Integration tests for tools/launch_gate_runbook.py.

Uses subprocess to avoid storage package path conflicts:
- conftest.py loads db-admin's storage package (for other tests)
- launch_gate_runbook needs ai-admin's storage.repositories
Running via subprocess gives a clean Python process with no prior imports.

Tests:
- T1: All required JSON keys present
- T2: Markdown file generated and non-empty
- T3: Verdict accuracy (blockers → needs_more_work; no blockers → launch_ready)
- T4: Attrition reasons classified as 'low_confidence' in fallback mode
- T4b: Stage counts non-increasing; gates_passed=0 in fallback mode
- T5: Fallback mode exit code 0 (no live provider needed)
- T5b: Real mode without --allow-live-ai-provider exits with non-zero
- T6: adversarial_compare_v2 has all 9 extended keys
- T7: schema version and meta.provider_mode correct
- T8: Empty input dir handled gracefully (no crash)
- T9: --max-items-per-mart cap respected
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
RUNBOOK_SCRIPT = str(TOOLS_DIR / "launch_gate_runbook.py")
PYTHON_EXE = sys.executable

SCHEMA_VERSION = "walletsavior.launch_gate_runbook.v1"

REQUIRED_JSON_KEYS = {
    "schema",
    "meta",
    "per_mart_stage_counts",
    "per_mart_attrition_reasons",
    "adversarial_compare_v2",
    "launch_gate_blockers",
    "human_summary_md_path",
    "verdict",
}

REQUIRED_META_KEYS = {"timestamp", "git_sha", "provider_mode", "input_paths"}

REQUIRED_STAGE_COUNT_KEYS = {
    "crawler_rows",
    "ingested_rows",
    "ai_proposals",
    "gates_passed",
    "publish_approved",
    "public_snapshot_rows",
}

REQUIRED_ADV_V2_9_KEYS = {
    "category_distribution_per_mart",
    "category_imbalance_alerts",
    "category_sibling_starvation_alerts",
    "ai_confidence_distribution",
    "low_confidence_alerts",
    "mart_volume_sanity",
    "volume_alerts",
    "semantic_spotcheck",
    "semantic_alerts",
}

# ---------------------------------------------------------------------------
# Fixture data builders
# ---------------------------------------------------------------------------

def _make_mart_records(mart_name: str, store_name: str, count: int = 5) -> list[dict[str, Any]]:
    records = []
    for i in range(1, count + 1):
        records.append({
            "raw_record_id": f"{mart_name}:synth{i}",
            "source_name": mart_name,
            "source_record_key": f"synth{i}",
            "source_url": f"https://{mart_name}.example.com/item/{i}",
            "raw_title": f"합성 {store_name} 상품 {i} 500g",
            "raw_price": 2990 + i * 100,
            "raw_payload": {
                "name": f"합성 {store_name} 상품 {i}",
                "store": store_name,
                "sale_price": 2990 + i * 100,
                "original_price": 3990 + i * 100,
                "discount_percent": 25.0,
                "unit": "500g",
                "package_quantity": 500,
                "package_unit": "g",
                "category": "채소",
                "source_url": f"https://{mart_name}.example.com/item/{i}",
                "image_url": f"https://{mart_name}.example.com/img/{i}.jpg",
            },
            "crawled_at": "2026-05-16T12:00:00.000000",
        })
    return records


def _write_mart_fixture(tmp_path: Path, mart_name: str, store_name: str, count: int = 5) -> Path:
    mart_dir = tmp_path / mart_name
    mart_dir.mkdir(exist_ok=True)
    fixture_path = mart_dir / f"live-validation-v2-synth-{mart_name}.json"
    fixture_path.write_text(
        json.dumps({"raw_records": _make_mart_records(mart_name, store_name, count)},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return mart_dir


def _run_runbook(
    input_dirs: list[Path],
    artifact_dir: Path,
    extra_args: list[str] | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """Run the runbook script as a subprocess and return (returncode, stdout, stderr)."""
    cmd = [PYTHON_EXE, RUNBOOK_SCRIPT]
    for d in input_dirs:
        cmd += ["--input-dir", str(d)]
    cmd += ["--artifact-dir", str(artifact_dir)]
    cmd += ["--provider-mode", "fallback"]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _find_json_report(artifact_dir: Path) -> dict[str, Any] | None:
    """Find and parse the latest JSON report under artifact_dir."""
    json_files = list(artifact_dir.rglob("launch-gate-*.json"))
    if not json_files:
        return None
    json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return json.loads(json_files[0].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synth_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Run the runbook once with 3-mart synthetic input; return parsed JSON report."""
    tmp = tmp_path_factory.mktemp("synth")
    emart_dir = _write_mart_fixture(tmp, "emart", "이마트")
    homeplus_dir = _write_mart_fixture(tmp, "homeplus", "홈플러스")
    lottemart_dir = _write_mart_fixture(tmp, "lottemart", "롯데마트")
    artifact_dir = tmp / "out"
    artifact_dir.mkdir()
    rc, stdout, stderr = _run_runbook(
        [emart_dir, homeplus_dir, lottemart_dir],
        artifact_dir,
    )
    assert rc == 0, f"Runbook failed (rc={rc}).\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    report = _find_json_report(artifact_dir)
    assert report is not None, (
        f"No JSON report found in {artifact_dir}.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )
    return report


# ---------------------------------------------------------------------------
# T1: All required JSON keys present
# ---------------------------------------------------------------------------

def test_t1_top_level_keys(synth_result: dict[str, Any]) -> None:
    """T1: JSON output must contain all required top-level keys."""
    missing = REQUIRED_JSON_KEYS - set(synth_result.keys())
    assert not missing, f"Missing JSON keys: {missing}"


def test_t1_meta_keys(synth_result: dict[str, Any]) -> None:
    """T1b: meta block must have required keys."""
    missing = REQUIRED_META_KEYS - set(synth_result["meta"].keys())
    assert not missing, f"Missing meta keys: {missing}"


def test_t1_adversarial_v2_keys(synth_result: dict[str, Any]) -> None:
    """T1c: adversarial_compare_v2 must have required v2 keys."""
    adv = synth_result["adversarial_compare_v2"]
    missing = REQUIRED_ADV_V2_9_KEYS - set(adv.keys())
    assert not missing, f"Missing adversarial_compare_v2 keys: {missing}"


def test_t1_per_mart_stage_count_keys(synth_result: dict[str, Any]) -> None:
    """T1d: per-mart stage counts must have all 6 stage keys."""
    for mart, counts in synth_result["per_mart_stage_counts"].items():
        missing = REQUIRED_STAGE_COUNT_KEYS - set(counts.keys())
        assert not missing, f"Missing stage count keys for {mart}: {missing}"


# ---------------------------------------------------------------------------
# T2: Markdown file generated
# ---------------------------------------------------------------------------

def test_t2_markdown_path_in_report(synth_result: dict[str, Any]) -> None:
    """T2: human_summary_md_path must be present and point to a real file."""
    md_path_str = synth_result.get("human_summary_md_path", "")
    assert md_path_str, "human_summary_md_path is empty"
    md_path = Path(md_path_str)
    assert md_path.exists(), f"Markdown file not found: {md_path}"


def test_t2_markdown_content(synth_result: dict[str, Any]) -> None:
    """T2b: Markdown must contain WalletSavior and a mart table."""
    md_path = Path(synth_result["human_summary_md_path"])
    content = md_path.read_text(encoding="utf-8")
    assert len(content) > 200, "Markdown content is suspiciously short"
    assert "WalletSavior" in content
    assert ("마트별" in content or "emart" in content), "Expected mart table content"


# ---------------------------------------------------------------------------
# T3: Verdict correctness
# ---------------------------------------------------------------------------

def test_t3_verdict_is_valid(synth_result: dict[str, Any]) -> None:
    """T3: verdict must be 'launch_ready' or 'needs_more_work'."""
    verdict = synth_result["verdict"]
    assert verdict in ("launch_ready", "needs_more_work"), f"Unexpected verdict: {verdict}"


def test_t3_verdict_needs_more_work_when_hard_blockers(synth_result: dict[str, Any]) -> None:
    """T3b: if hard blockers exist, verdict must be needs_more_work."""
    blockers = synth_result.get("launch_gate_blockers", [])
    hard_blockers = [b for b in blockers if b.get("alert_type") not in {"data_load_error"}]
    if hard_blockers:
        assert synth_result["verdict"] == "needs_more_work", (
            f"Expected needs_more_work with {len(hard_blockers)} blockers, "
            f"got {synth_result['verdict']}"
        )


def test_t3_launch_ready_iff_no_hard_blockers(tmp_path: Path) -> None:
    """T3c: verdict=launch_ready ↔ hard blockers list is empty (logical invariant)."""
    mart_dir = _write_mart_fixture(tmp_path, "emart", "이마트")
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    _run_runbook([mart_dir], artifact_dir)
    report = _find_json_report(artifact_dir)
    assert report is not None
    hard_blockers = [
        b for b in report.get("launch_gate_blockers", [])
        if b.get("alert_type") not in {"data_load_error"}
    ]
    if report["verdict"] == "launch_ready":
        assert not hard_blockers, "launch_ready verdict must have no hard blockers"
    else:
        assert hard_blockers, "needs_more_work verdict must have at least one hard blocker"


# ---------------------------------------------------------------------------
# T4: Attrition reason classification
# ---------------------------------------------------------------------------

def test_t4_attrition_reason_low_confidence(synth_result: dict[str, Any]) -> None:
    """T4: In fallback mode, all attrition must be 'low_confidence'."""
    for mart, reasons in synth_result["per_mart_attrition_reasons"].items():
        assert "low_confidence" in reasons, (
            f"{mart}: expected 'low_confidence' in attrition_reasons, got {list(reasons.keys())}"
        )
        assert reasons["low_confidence"] > 0, f"{mart}: low_confidence count must be > 0"


def test_t4_stage_counts_non_increasing(synth_result: dict[str, Any]) -> None:
    """T4b: Stage counts must be monotonically non-increasing."""
    for mart, c in synth_result["per_mart_stage_counts"].items():
        assert c["crawler_rows"] >= c["ingested_rows"], f"{mart}: crawler_rows < ingested_rows"
        assert c["ingested_rows"] >= c["ai_proposals"], f"{mart}: ingested_rows < ai_proposals"


def test_t4_gates_passed_zero_in_fallback(synth_result: dict[str, Any]) -> None:
    """T4c: fallback mode confidence=0.42 < 0.9 threshold → gates_passed=0."""
    for mart, c in synth_result["per_mart_stage_counts"].items():
        assert c["gates_passed"] == 0, (
            f"{mart}: expected gates_passed=0 in fallback mode, got {c['gates_passed']}"
        )
        assert c["publish_approved"] == 0
        assert c["public_snapshot_rows"] == 0


def test_t4_all_records_get_fallback_proposals(synth_result: dict[str, Any]) -> None:
    """T4d: In fallback mode, every ingested record gets proposals."""
    for mart, c in synth_result["per_mart_stage_counts"].items():
        assert c["ai_proposals"] == c["ingested_rows"], (
            f"{mart}: ai_proposals={c['ai_proposals']} != ingested_rows={c['ingested_rows']}"
        )


# ---------------------------------------------------------------------------
# T5: Fallback mode / live guard
# ---------------------------------------------------------------------------

def test_t5_fallback_mode_exit_code_0(tmp_path: Path) -> None:
    """T5: fallback mode must exit 0 (no live provider needed)."""
    mart_dir = _write_mart_fixture(tmp_path, "emart", "이마트")
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    rc, stdout, stderr = _run_runbook([mart_dir], artifact_dir)
    assert rc == 0, f"rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"


def test_t5b_real_mode_without_flag_exits_nonzero(tmp_path: Path) -> None:
    """T5b: --provider-mode real without --allow-live-ai-provider must exit non-zero."""
    mart_dir = _write_mart_fixture(tmp_path, "emart", "이마트")
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    cmd = [
        PYTHON_EXE, RUNBOOK_SCRIPT,
        "--input-dir", str(mart_dir),
        "--artifact-dir", str(artifact_dir),
        "--provider-mode", "real",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, (
        "Expected non-zero exit for 'real' mode without --allow-live-ai-provider, "
        f"got rc={result.returncode}"
    )


# ---------------------------------------------------------------------------
# T6: Adversarial compare v2 - 9 keys
# ---------------------------------------------------------------------------

def test_t6_adversarial_compare_v2_has_9_keys(synth_result: dict[str, Any]) -> None:
    """T6: adversarial_compare_v2 must have all 9 extended output keys."""
    adv = synth_result["adversarial_compare_v2"]
    missing = REQUIRED_ADV_V2_9_KEYS - set(adv.keys())
    assert not missing, f"Missing adversarial_compare_v2 keys: {missing}"


def test_t6_adversarial_v2_schema_field(synth_result: dict[str, Any]) -> None:
    """T6b: adversarial_compare_v2 must have a schema field."""
    adv = synth_result["adversarial_compare_v2"]
    assert "schema" in adv, "adversarial_compare_v2 missing 'schema' key"


# ---------------------------------------------------------------------------
# T7: Schema and meta fields
# ---------------------------------------------------------------------------

def test_t7_schema_version(synth_result: dict[str, Any]) -> None:
    """T7: schema field must match expected version string."""
    assert synth_result["schema"] == SCHEMA_VERSION, (
        f"schema mismatch: {synth_result['schema']} != {SCHEMA_VERSION}"
    )


def test_t7_meta_provider_mode(synth_result: dict[str, Any]) -> None:
    """T7b: meta.provider_mode must match requested mode."""
    assert synth_result["meta"]["provider_mode"] == "fallback"


def test_t7_meta_timestamp_present(synth_result: dict[str, Any]) -> None:
    """T7c: meta.timestamp must be non-empty."""
    ts = synth_result["meta"].get("timestamp", "")
    assert ts, "meta.timestamp must be non-empty"


# ---------------------------------------------------------------------------
# T8: Empty input dir handled gracefully
# ---------------------------------------------------------------------------

def test_t8_empty_input_dir_no_crash(tmp_path: Path) -> None:
    """T8: An empty mart directory must not crash (exit 0, JSON produced)."""
    empty_dir = tmp_path / "empty_mart"
    empty_dir.mkdir()
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    rc, stdout, stderr = _run_runbook([empty_dir], artifact_dir)
    assert rc == 0, f"rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    report = _find_json_report(artifact_dir)
    assert report is not None, "JSON report must be produced even for empty input"


def test_t8_empty_input_zero_rows(tmp_path: Path) -> None:
    """T8b: Empty mart dir should produce a mart entry with crawler_rows=0."""
    empty_dir = tmp_path / "empty_mart"
    empty_dir.mkdir()
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    _run_runbook([empty_dir], artifact_dir)
    report = _find_json_report(artifact_dir)
    if report:
        mart_counts = report["per_mart_stage_counts"]
        assert any(v["crawler_rows"] == 0 for v in mart_counts.values()), (
            "Expected at least one mart with crawler_rows=0 for empty input"
        )


# ---------------------------------------------------------------------------
# T9: max_items_per_mart cap
# ---------------------------------------------------------------------------

def test_t9_max_items_cap_respected(tmp_path: Path) -> None:
    """T9: --max-items-per-mart 2 must limit each mart to ≤ 2 records."""
    emart_dir = _write_mart_fixture(tmp_path, "emart", "이마트", count=5)
    homeplus_dir = _write_mart_fixture(tmp_path, "homeplus", "홈플러스", count=5)
    artifact_dir = tmp_path / "out"
    artifact_dir.mkdir()
    rc, stdout, stderr = _run_runbook(
        [emart_dir, homeplus_dir],
        artifact_dir,
        extra_args=["--max-items-per-mart", "2"],
    )
    assert rc == 0, f"rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    report = _find_json_report(artifact_dir)
    assert report is not None
    for mart, counts in report["per_mart_stage_counts"].items():
        assert counts["crawler_rows"] <= 2, (
            f"{mart}: crawler_rows={counts['crawler_rows']} > cap of 2"
        )
