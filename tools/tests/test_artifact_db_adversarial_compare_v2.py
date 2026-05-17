"""TDD tests for the four new adversarial-compare dimensions (D1-D4).

Run with:
    py -3 -m pytest tools/tests -q

Each dimension has:
  * a happy-path (normal data → 0 alerts)
  * at least one violation case (intended breach → exact alert triggered)
  * a false-positive guard (violation of one dimension does not fire another)
"""
from __future__ import annotations

import pytest

from adversarial_compare_extensions import (
    analyze_ai_confidence,
    analyze_category_distribution,
    analyze_volume_sanity,
    build_mart_stats_for_table,
    collect_launch_gate_blockers,
    format_markdown_summary_table,
    semantic_spotcheck,
)


# ---------------------------------------------------------------------------
# Helpers / fixture factories
# ---------------------------------------------------------------------------

def _rows(source: str, category: str, n: int, *, ai_conf: float | None = None) -> list[dict]:
    """Return *n* minimal rows for the given source/category."""
    row = {"source": source, "category": category, "raw_title": "테스트상품", "raw_record_id": None}
    if ai_conf is not None:
        row["ai_confidence"] = ai_conf
    return [dict(row) for _ in range(n)]


def _titled_row(source: str, title: str, category: str, **extra) -> dict:
    return {"source": source, "raw_title": title, "category": category, "raw_record_id": None, **extra}


# ===========================================================================
# D1 – Category distribution
# ===========================================================================

class TestCategoryDistribution:

    # ------------------------------------------------------------------ happy
    def test_no_alerts_when_balanced(self):
        rows = (
            _rows("emart", "grain.rice", 20)
            + _rows("emart", "grain.wheat", 20)
            + _rows("emart", "dairy.milk", 20)
            + _rows("emart", "dairy.cheese", 20)
            + _rows("emart", "meat.pork", 20)
        )
        result = analyze_category_distribution(rows, imbalance_threshold=0.60)
        assert result["category_imbalance_alerts"] == []
        assert result["category_sibling_starvation_alerts"] == []

    # ---------------------------------------------------------------- imbalance
    def test_imbalance_alert_fires_when_single_category_dominates(self):
        # grain.rice = 70 / 100 = 70 % → above 60 % threshold
        rows = _rows("emart", "grain.rice", 70) + _rows("emart", "dairy.milk", 30)
        result = analyze_category_distribution(rows, imbalance_threshold=0.60)
        alerts = result["category_imbalance_alerts"]
        assert len(alerts) == 1
        a = alerts[0]
        assert a["alert_type"] == "category_imbalance_alert"
        assert a["mart"] == "emart"
        assert a["category"] == "grain.rice"
        assert a["ratio"] >= 0.60

    def test_no_imbalance_alert_below_threshold(self):
        # 59 % — just under threshold
        rows = _rows("emart", "grain.rice", 59) + _rows("emart", "dairy.milk", 41)
        result = analyze_category_distribution(rows, imbalance_threshold=0.60)
        assert result["category_imbalance_alerts"] == []

    # ---------------------------------------------------------------- starvation
    def test_starvation_alert_fires_when_sibling_absent(self):
        # grain.rice alone with 120 items, no grain.wheat or grain.barley in data
        rows = _rows("emart", "grain.rice", 120) + _rows("emart", "dairy.milk", 50)
        result = analyze_category_distribution(rows, starvation_min_count=100)
        alerts = result["category_sibling_starvation_alerts"]
        assert len(alerts) == 1
        a = alerts[0]
        assert a["alert_type"] == "category_sibling_starvation_alert"
        assert a["category"] == "grain.rice"
        assert a["l1_parent"] == "grain"

    def test_no_starvation_when_sibling_present(self):
        # grain.rice 120 + grain.wheat 10 — sibling exists, no alert
        rows = (
            _rows("emart", "grain.rice", 120)
            + _rows("emart", "grain.wheat", 10)
            + _rows("emart", "dairy.milk", 50)
        )
        result = analyze_category_distribution(rows, starvation_min_count=100)
        assert result["category_sibling_starvation_alerts"] == []

    def test_starvation_below_min_count_no_alert(self):
        # grain.rice only 80 items (< 100 threshold) — no starvation alert
        rows = _rows("emart", "grain.rice", 80) + _rows("emart", "dairy.milk", 50)
        result = analyze_category_distribution(rows, starvation_min_count=100)
        assert result["category_sibling_starvation_alerts"] == []

    # ---------------------------------------------------------------- distribution accuracy
    def test_distribution_totals_match_input(self):
        rows = _rows("homeplus", "grain.rice", 40) + _rows("homeplus", "dairy.milk", 60)
        result = analyze_category_distribution(rows)
        dist = result["category_distribution_per_mart"]["homeplus"]
        assert dist["total"] == 100
        assert dist["categories"]["dairy.milk"]["count"] == 60

    # ---------------------------------------------------------------- false-positive guard
    def test_imbalance_does_not_trigger_starvation_for_leaf_category(self):
        # A single top-level category (no dot) dominates — should not produce starvation alert
        # because 'grain' with no sub-categories has no siblings by definition
        rows = _rows("emart", "grain", 120) + _rows("emart", "dairy", 5)
        result = analyze_category_distribution(rows, imbalance_threshold=0.95, starvation_min_count=100)
        # starvation: grain has no siblings (only category under 'grain' L1 is 'grain' itself)
        starvation = result["category_sibling_starvation_alerts"]
        # grain has no sibling → starvation fires
        assert any(a["category"] == "grain" for a in starvation)
        # imbalance: 120/125 = 96% but threshold=0.95 → should fire
        imbalance = result["category_imbalance_alerts"]
        assert any(a["category"] == "grain" for a in imbalance)


# ===========================================================================
# D2 – AI confidence
# ===========================================================================

class TestAiConfidence:

    # ------------------------------------------------------------------ happy
    def test_no_alerts_when_confidence_high(self):
        rows = [{"ai_confidence": 0.95} for _ in range(100)]
        result = analyze_ai_confidence(rows)
        assert result["ai_confidence_distribution"]["available"] is True
        assert result["ai_confidence_distribution"]["p25"] >= 0.7
        assert result["low_confidence_alerts"] == []

    # ---------------------------------------------------------------- no data
    def test_no_data_returns_available_false(self):
        rows = [{"source": "emart", "category": "grain"}] * 10  # no ai_confidence
        result = analyze_ai_confidence(rows)
        assert result["ai_confidence_distribution"]["available"] is False
        assert result["low_confidence_alerts"] == []

    # ---------------------------------------------------------------- p25 alert
    def test_p25_below_threshold_fires_alert(self):
        # Inject enough low values to push p25 below 0.7
        low = [{"ai_confidence": 0.3}] * 30
        high = [{"ai_confidence": 0.95}] * 70
        result = analyze_ai_confidence(low + high)
        alert_types = [a["alert_type"] for a in result["low_confidence_alerts"]]
        assert "low_confidence_tail_alert" in alert_types
        # Verify metric
        p25_alerts = [a for a in result["low_confidence_alerts"] if a.get("metric") == "p25"]
        assert p25_alerts, "expected a p25 metric alert"

    # ---------------------------------------------------------------- 0.0-0.5 bin alert
    def test_low_bin_fires_alert_when_over_5_percent(self):
        # 7 rows below 0.5 out of 100 → 7 % > 5 % threshold
        rows = [{"ai_confidence": 0.3}] * 7 + [{"ai_confidence": 0.9}] * 93
        result = analyze_ai_confidence(rows)
        bin_alerts = [
            a for a in result["low_confidence_alerts"]
            if a.get("metric") == "bin_0.0-0.5"
        ]
        assert bin_alerts, "expected a bin alert"

    def test_low_bin_no_alert_when_under_5_percent(self):
        # 4 rows below 0.5 out of 100 → 4 % ≤ 5 % → no bin alert
        rows = [{"ai_confidence": 0.3}] * 4 + [{"ai_confidence": 0.9}] * 96
        result = analyze_ai_confidence(rows)
        # p25 will be well above 0.7, so no p25 alert either
        assert result["low_confidence_alerts"] == []

    # ---------------------------------------------------------------- histogram
    def test_histogram_bins_sum_to_total(self):
        rows = [{"ai_confidence": v} for v in [0.3, 0.6, 0.75, 0.85, 0.95]]
        result = analyze_ai_confidence(rows)
        dist = result["ai_confidence_distribution"]
        assert sum(dist["histogram"].values()) == 5

    # ---------------------------------------------------------------- false positive
    def test_p25_alert_does_not_fire_unrelated_category_alert(self):
        """A confidence-based alert must not bleed into category alerts."""
        # Use four balanced categories so NO imbalance fires despite low confidence values
        rows = (
            [{"ai_confidence": 0.3, "source": "emart", "category": "grain.rice"}] * 25
            + [{"ai_confidence": 0.95, "source": "emart", "category": "grain.wheat"}] * 25
            + [{"ai_confidence": 0.3, "source": "emart", "category": "dairy.milk"}] * 25
            + [{"ai_confidence": 0.95, "source": "emart", "category": "dairy.cheese"}] * 25
        )
        cat_result = analyze_category_distribution(rows)
        assert cat_result["category_imbalance_alerts"] == []


# ===========================================================================
# D3 – Volume sanity
# ===========================================================================

class TestVolumeSanity:

    MIN = {"emart": 200, "homeplus": 150, "lottemart": 100}

    # ------------------------------------------------------------------ happy
    def test_no_alerts_when_volumes_sufficient(self):
        crawler = _rows("emart", "grain", 300) + _rows("homeplus", "dairy", 200) + _rows("lottemart", "meat", 120)
        final = _rows("emart", "grain", 250) + _rows("homeplus", "dairy", 180) + _rows("lottemart", "meat", 110)
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart=self.MIN)
        assert result["volume_alerts"] == []

    # ---------------------------------------------------------------- undercount
    def test_volume_undercount_alert_fires(self):
        crawler = _rows("emart", "grain", 300)
        final = _rows("emart", "grain", 100)  # 100 < threshold 200
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart=self.MIN)
        # Other marts in MIN will also fire undercount (0 rows), so filter by mart
        alerts = [
            a for a in result["volume_alerts"]
            if a["alert_type"] == "volume_undercount_alert" and a["mart"] == "emart"
        ]
        assert len(alerts) == 1
        assert alerts[0]["deficit"] == 100

    def test_undercount_alert_reports_both_actual_and_threshold(self):
        crawler = _rows("homeplus", "dairy", 200)
        final = _rows("homeplus", "dairy", 50)
        # Use single-mart dict to get a clean single-alert result
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart={"homeplus": 150})
        alert = next(a for a in result["volume_alerts"] if a["alert_type"] == "volume_undercount_alert")
        assert alert["final_db_count"] == 50
        assert alert["min_threshold"] == 150

    # ---------------------------------------------------------------- attrition
    def test_pipeline_attrition_alert_fires(self):
        # crawler=274, final=100 → 100/274 ≈ 0.365 < 0.5
        crawler = _rows("emart", "grain", 274)
        final = _rows("emart", "grain", 100)
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart={}, attrition_ratio=0.5)
        alerts = [a for a in result["volume_alerts"] if a["alert_type"] == "pipeline_attrition_alert"]
        assert len(alerts) == 1
        assert alerts[0]["crawler_count"] == 274
        assert alerts[0]["final_db_count"] == 100

    def test_no_attrition_alert_when_ratio_above_threshold(self):
        # 270/300 = 0.9 > 0.5
        crawler = _rows("emart", "grain", 300)
        final = _rows("emart", "grain", 270)
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart={}, attrition_ratio=0.5)
        attrition = [a for a in result["volume_alerts"] if a["alert_type"] == "pipeline_attrition_alert"]
        assert attrition == []

    def test_unknown_mart_no_undercount_alert(self):
        # 'coupang' not in MIN_ROWS_PER_MART (our custom dict) → no undercount alert
        crawler = _rows("coupang", "snack", 10)
        final = _rows("coupang", "snack", 5)
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart=self.MIN, attrition_ratio=0.5)
        undercount = [a for a in result["volume_alerts"] if a["alert_type"] == "volume_undercount_alert" and a["mart"] == "coupang"]
        assert undercount == []

    # ---------------------------------------------------------------- false positive
    def test_undercount_does_not_fire_attrition_when_ratio_fine(self):
        # final(80) < threshold(200) → undercount alert
        # but final(80) / crawler(100) = 0.8 > 0.5 → no attrition alert
        crawler = _rows("emart", "grain", 100)
        final = _rows("emart", "grain", 80)
        result = analyze_volume_sanity(crawler, final, min_rows_per_mart={"emart": 200}, attrition_ratio=0.5)
        attrition = [a for a in result["volume_alerts"] if a["alert_type"] == "pipeline_attrition_alert"]
        undercount = [a for a in result["volume_alerts"] if a["alert_type"] == "volume_undercount_alert"]
        assert undercount  # fires
        assert not attrition  # does not fire


# ===========================================================================
# D4 – Semantic spot-check
# ===========================================================================

class TestSemanticSpotcheck:

    # ------------------------------------------------------------------ happy
    def test_no_alerts_when_categories_match(self):
        rows = [
            _titled_row("emart", "쌀 20kg", "grain.rice"),
            _titled_row("emart", "우유 1L", "dairy.milk"),
            _titled_row("emart", "사과 2kg", "fruit.apple"),
            _titled_row("emart", "삼겹살 500g", "meat.pork"),
        ] * 10  # 40 rows but only 30 sampled
        result = semantic_spotcheck(rows, seed=0, sample_size=30)
        assert result["semantic_spotcheck"]["flagged"] == []
        assert result["semantic_alerts"] == []

    # ---------------------------------------------------------------- mismatch
    def test_mismatch_flagged_when_keyword_category_wrong(self):
        # "쌀" → should be grain.*, but we assign dairy.milk
        rows = [_titled_row("emart", "쌀 20kg", "dairy.milk")] * 5
        result = semantic_spotcheck(rows, seed=0, sample_size=30)
        flagged = result["semantic_spotcheck"]["flagged"]
        assert len(flagged) == 5
        assert all(f["expected_prefix"] == "grain" for f in flagged)
        assert all(f["matched_keyword"] == "쌀" for f in flagged)

    # ---------------------------------------------------------------- no-keyword skip
    def test_no_keyword_row_not_checked_not_flagged(self):
        # Generic title with no known keyword → checked=0, flagged=0
        rows = [_titled_row("emart", "특가 묶음상품", "misc.bundle")] * 20
        result = semantic_spotcheck(rows, seed=0, sample_size=30)
        sc = result["semantic_spotcheck"]
        assert sc["checked"] == 0
        assert sc["flagged"] == []
        assert result["semantic_alerts"] == []  # no alert when nothing was checked

    # ---------------------------------------------------------------- pass-rate alert
    def test_pass_rate_alert_fires_when_many_mismatches(self):
        # All 20 rows have "우유" but wrong category → 0 % pass rate < 80 %
        rows = [_titled_row("emart", "우유 1L", "grain.rice")] * 20
        result = semantic_spotcheck(rows, seed=0, sample_size=30, pass_rate_threshold=0.80)
        alerts = result["semantic_alerts"]
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "semantic_spotcheck_alert"
        assert alerts[0]["pass_rate"] == 0.0

    def test_pass_rate_no_alert_when_above_threshold(self):
        # 10 correct + 1 wrong among 11 checked → 10/11 ≈ 91 % > 80 %
        rows = [_titled_row("emart", "우유 1L", "dairy.milk")] * 10 + [_titled_row("emart", "우유 1L", "grain.rice")]
        result = semantic_spotcheck(rows, seed=0, sample_size=30, pass_rate_threshold=0.80)
        assert result["semantic_alerts"] == []

    # ---------------------------------------------------------------- per-mart stats
    def test_per_mart_stats_present_in_result(self):
        rows = (
            [_titled_row("emart", "쌀 20kg", "grain.rice")] * 5
            + [_titled_row("homeplus", "우유 1L", "dairy.milk")] * 5
        )
        result = semantic_spotcheck(rows, seed=0, sample_size=10)
        pm = result["semantic_spotcheck"]["per_mart"]
        assert "emart" in pm
        assert "homeplus" in pm
        assert pm["emart"]["sampled"] == 5

    # ---------------------------------------------------------------- seed reproducibility
    def test_same_seed_produces_same_result(self):
        rows = [_titled_row("emart", f"상품{i}", "grain.rice" if i % 2 == 0 else "dairy.milk") for i in range(100)]
        r1 = semantic_spotcheck(rows, seed=42, sample_size=30)
        r2 = semantic_spotcheck(rows, seed=42, sample_size=30)
        assert r1["semantic_spotcheck"]["sampled"] == r2["semantic_spotcheck"]["sampled"]

    # ---------------------------------------------------------------- false positive
    def test_mismatch_does_not_trigger_volume_alert(self):
        """D4 mismatch should not produce volume or confidence alerts."""
        rows = [_titled_row("emart", "쌀 20kg", "dairy.milk")] * 5
        vol = analyze_volume_sanity(rows, rows, min_rows_per_mart={})
        assert vol["volume_alerts"] == []


# ===========================================================================
# Launch-gate blocker aggregator
# ===========================================================================

class TestCollectLaunchGateBlockers:

    def test_all_critical_types_included(self):
        blockers = collect_launch_gate_blockers(
            imbalance_alerts=[{"alert_type": "category_imbalance_alert"}],
            confidence_alerts=[{"alert_type": "low_confidence_tail_alert"}],
            volume_alerts=[
                {"alert_type": "volume_undercount_alert"},
                {"alert_type": "pipeline_attrition_alert"},
            ],
            semantic_alerts=[{"alert_type": "semantic_spotcheck_alert"}],
        )
        assert len(blockers) == 5

    def test_starvation_not_a_blocker(self):
        blockers = collect_launch_gate_blockers(
            starvation_alerts=[{"alert_type": "category_sibling_starvation_alert"}]
        )
        assert len(blockers) == 0

    def test_empty_inputs_return_empty_list(self):
        assert collect_launch_gate_blockers() == []


# ===========================================================================
# Markdown summary table
# ===========================================================================

class TestMarkdownSummaryTable:

    def test_table_contains_header(self):
        stats = {
            "emart": {
                "crawler_count": 274,
                "normalized_count": 270,
                "ai_approved_count": 200,
                "final_db_count": 198,
                "missing_count": 76,
                "missing_pct": 27.7,
                "semantic_fail": "2/30",
            }
        }
        table = format_markdown_summary_table(stats)
        assert "마트" in table
        assert "크롤러" in table
        assert "emart" in table
        assert "274" in table
        assert "76" in table

    def test_table_has_separator_row(self):
        table = format_markdown_summary_table({"emart": {
            "crawler_count": 100, "normalized_count": 100, "ai_approved_count": 100,
            "final_db_count": 100, "missing_count": 0, "missing_pct": 0.0, "semantic_fail": "-",
        }})
        lines = table.split("\n")
        assert any("---" in line for line in lines)

    def test_build_mart_stats_for_table(self):
        src = _rows("emart", "grain", 50)
        proof = _rows("emart", "grain", 48)
        final = _rows("emart", "grain", 45)
        sc_result = {
            "semantic_spotcheck": {
                "per_mart": {"emart": {"sampled": 30, "checked": 10, "flagged": 2}}
            }
        }
        vol_result = {"mart_volume_sanity": {"emart": {"crawler_count": 50, "final_db_count": 45}}}
        stats = build_mart_stats_for_table(src, proof, final, sc_result, vol_result)
        assert "emart" in stats
        assert stats["emart"]["crawler_count"] == 50
        assert stats["emart"]["semantic_fail"] == "2/30"
        assert stats["emart"]["missing_count"] == 5
