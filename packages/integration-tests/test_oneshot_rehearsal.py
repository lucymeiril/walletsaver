"""rd3-oneshot-reproducibility — orchestrator 통합 테스트.

검증 범위:
  1. `tools/oneshot_live_rehearsal.py` 가 빈 DB → 크롤 → ai → publish → website
     까지 한 번에 완주한다.
  2. 사용자 시나리오 게이트 (raw vs publish drop ≤ 5%, category/keyword/매칭테이블/
     baseline_price/hotdeal_score 0 아님) 가 fixture 모드에서 통과한다.
  3. 동일 fixture 두 번 실행 시 stable_id / canonical / category / publish 키의
     정규화 산출물이 byte-identical (SHA256 일치) 이다.
  4. CLI 3 단계 (`--step crawl`, `--step ai --no-init`, `--step publish --no-init`)
     로 분리 실행해도 동일한 게이트가 통과한다.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORCHESTRATOR_PATH = REPO_ROOT / "tools" / "oneshot_live_rehearsal.py"


def _load_orchestrator():
    spec = importlib.util.spec_from_file_location("oneshot_live_rehearsal_under_test", ORCHESTRATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def orchestrator():
    return _load_orchestrator()


def _full_pipeline(orchestrator, tmp_dir: Path) -> dict:
    """artifact_dir tmp_dir 위에서 step1-step7 + 게이트 평가."""
    orchestrator.step1_init_empty_db(tmp_dir)
    crawl = orchestrator.step2_crawl(artifact_dir=tmp_dir, allow_live_crawler=False)
    ai = orchestrator.step3_to_5_ai_pipeline(
        artifact_dir=tmp_dir, records=crawl["records"], allow_live_ai_provider=False
    )
    publish = orchestrator.step6_db_publish(artifact_dir=tmp_dir, db_items=ai["db_items"])
    website = orchestrator.step7_website(
        artifact_dir=tmp_dir, publish_artifact=publish, allow_live_website=False
    )
    gates = orchestrator.evaluate_user_scenario_gates(ai_artifact=ai, publish_artifact=publish)
    engine = publish.pop("_engine", None)
    publish.pop("_session_factory", None)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            pass
    return {"crawl": crawl, "ai": ai, "publish": publish, "website": website, "gates": gates}


def test_oneshot_full_cycle_fixture_mode(orchestrator, tmp_path):
    """크롤→ai→publish→website 까지 fixture 모드 완주 + 사용자 시나리오 게이트."""
    result = _full_pipeline(orchestrator, tmp_path / "run-once")

    crawl = result["crawl"]
    assert crawl["raw_total"] == 12
    assert set(crawl["raw_counts_by_source"].keys()) == {"emart", "homeplus", "lottemart", "costco"}

    ai = result["ai"]
    assert ai["status"] == "passed"
    assert ai["publish_total"] == 12
    assert ai["drop_pct"] <= 5.0
    assert len(ai["db_items"]) == 12
    # rule_mapper 매칭 테이블 시드 — 사람 보완 시뮬레이션
    assert ai["match_table_seeded_count"] >= 1

    publish = result["publish"]
    assert publish["status"] == "passed"
    assert publish["approved_count"] == 12
    db_state = publish["db_state"]
    assert db_state["products"] == 12
    assert db_state["discount_histories"] == 12
    # 카테고리/키워드 0이 아님
    assert db_state["categories"] >= 1
    assert db_state["keywords"] >= 1

    website = result["website"]
    assert website["status"] == "passed"
    assert website["captured_product_count"] == 5
    # 상품 상세는 모두 200
    for resp in website["product_responses"]:
        assert resp.get("status_code") == 200, resp

    gates = result["gates"]
    assert gates["passed"], gates["blockers"]
    # 매칭 테이블 시드 카운트 0 아님
    assert gates["zero_fields"]["match_table_seed"] == 0
    # 모든 상품에 baseline_price (current_price) 존재
    assert gates["zero_fields"]["baseline_price"] < 12


def test_oneshot_reproducibility_byte_identical(orchestrator, tmp_path):
    """동일 fixture 2회 실행 시 stable_id / canonical / category / publish 정규화
    산출물이 byte-identical (SHA256 일치) — `검증 불가` 끝맺음 금지 게이트."""
    summary = orchestrator.verify_reproducibility(tmp_path / "reproducibility")
    assert summary["verified_identical"] is True, summary.get("diff")
    # 모든 비교 키 digest 동일
    for key in orchestrator.REPRODUCIBILITY_KEYS:
        assert summary["run1_digests"][key] == summary["run2_digests"][key], key


def test_oneshot_cli_3_step_segmentation(orchestrator, tmp_path):
    """--step crawl|ai|publish 분할 실행 후에도 게이트 통과."""
    artifact_dir = tmp_path / "segmented"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # step1+2: init + crawl
    assert orchestrator.main([
        "--step", "crawl",
        "--artifact-dir", str(artifact_dir),
    ]) == 0
    state = orchestrator._load_state(artifact_dir)
    assert state.get("crawl_records"), "crawl records must be persisted between steps"

    # step3-5: ai
    assert orchestrator.main([
        "--step", "ai",
        "--artifact-dir", str(artifact_dir),
        "--no-init",
    ]) == 0
    state = orchestrator._load_state(artifact_dir)
    assert state.get("ai_db_items"), "ai db_items must be persisted between steps"

    # step6+7: publish + website
    assert orchestrator.main([
        "--step", "publish",
        "--artifact-dir", str(artifact_dir),
        "--no-init",
    ]) == 0

    gates = json.loads((artifact_dir / "user_scenario_gates.json").read_text(encoding="utf-8"))
    assert gates["passed"], gates["blockers"]
    assert gates["publish_total"] == 12


def test_oneshot_report_artifact_emitted(orchestrator, tmp_path):
    """리허설 직후 report.md 가 생성되고 라이브 가이드 라인을 포함한다."""
    artifact_dir = tmp_path / "report-check"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rc = orchestrator.main([
        "--step", "all",
        "--artifact-dir", str(artifact_dir),
    ])
    assert rc == 0
    report = (artifact_dir / "report.md").read_text(encoding="utf-8")
    assert "rd3-oneshot-reproducibility" in report
    assert "사용자 시나리오 게이트" in report
    assert "py -3 tools/oneshot_live_rehearsal.py --step crawl" in report
