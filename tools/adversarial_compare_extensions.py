"""Extended analysis modules for artifact_db_adversarial_compare.

Each public function is independently testable with synthetic data.
Dimensions covered:
  D1 – per-mart category distribution imbalance / sibling starvation
  D2 – AI confidence distribution and low-tail alert
  D3 – mart absolute-volume sanity + pipeline attrition
  D4 – semantic spot-check (keyword → category heuristics)
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any

from adversarial_compare_constants import (
    CATEGORY_IMBALANCE_THRESHOLD,
    CATEGORY_STARVATION_MIN_COUNT,
    CONFIDENCE_LOW_BIN_THRESHOLD,
    CONFIDENCE_LOW_P25_THRESHOLD,
    KEYWORD_CATEGORY_RULES,
    MIN_ROWS_PER_MART,
    PIPELINE_ATTRITION_RATIO,
    SPOTCHECK_PASS_RATE_THRESHOLD,
    SPOTCHECK_SAMPLE_SIZE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_mart(row: dict[str, Any]) -> str:
    return str(row.get("source") or "").lower().strip()


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    n = len(s)
    idx = p / 100.0 * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return s[-1]
    return s[lo] + (idx - lo) * (s[hi] - s[lo])


# ---------------------------------------------------------------------------
# D1: Category distribution per mart
# ---------------------------------------------------------------------------

def analyze_category_distribution(
    rows: list[dict[str, Any]],
    imbalance_threshold: float = CATEGORY_IMBALANCE_THRESHOLD,
    starvation_min_count: int = CATEGORY_STARVATION_MIN_COUNT,
) -> dict[str, Any]:
    """Return per-mart category distribution, imbalance alerts, and sibling-starvation alerts.

    Args:
        rows: Normalised DB rows, each with ``source`` and ``category`` fields.
        imbalance_threshold: Single-category ratio that triggers an imbalance alert.
        starvation_min_count: Minimum category count that triggers starvation check.

    Returns:
        Dict with keys ``category_distribution_per_mart``,
        ``category_imbalance_alerts``, ``category_sibling_starvation_alerts``.
    """
    mart_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        mart = _get_mart(row)
        category = str(row.get("category") or "uncategorized").strip()
        mart_categories[mart][category] += 1

    distribution: dict[str, Any] = {}
    imbalance_alerts: list[dict[str, Any]] = []
    starvation_alerts: list[dict[str, Any]] = []

    for mart, counter in sorted(mart_categories.items()):
        total = sum(counter.values())
        categories = {
            cat: {"count": cnt, "ratio": round(cnt / total, 4)}
            for cat, cnt in counter.most_common()
        }
        distribution[mart] = {"total": total, "categories": categories}

        # Imbalance: one category dominates
        for cat, cnt in counter.items():
            ratio = cnt / total
            if ratio >= imbalance_threshold:
                imbalance_alerts.append(
                    {
                        "alert_type": "category_imbalance_alert",
                        "mart": mart,
                        "category": cat,
                        "count": cnt,
                        "ratio": round(ratio, 4),
                        "threshold": imbalance_threshold,
                    }
                )

        # Sibling starvation: category >= starvation_min_count with no siblings in this mart
        # Build a map: L1 prefix → list of (category, count) with count > 0
        l1_to_cats: dict[str, list[str]] = defaultdict(list)
        for cat in counter:
            l1 = cat.split(".")[0] if "." in cat else cat
            l1_to_cats[l1].append(cat)

        for l1, siblings in l1_to_cats.items():
            for cat in siblings:
                if counter[cat] < starvation_min_count:
                    continue
                other_siblings = [s for s in siblings if s != cat]
                total_sibling_count = sum(counter[s] for s in other_siblings)
                if total_sibling_count == 0:
                    starvation_alerts.append(
                        {
                            "alert_type": "category_sibling_starvation_alert",
                            "mart": mart,
                            "category": cat,
                            "count": counter[cat],
                            "l1_parent": l1,
                            "siblings_present": other_siblings,
                        }
                    )

    return {
        "category_distribution_per_mart": distribution,
        "category_imbalance_alerts": imbalance_alerts,
        "category_sibling_starvation_alerts": starvation_alerts,
    }


# ---------------------------------------------------------------------------
# D2: AI confidence distribution
# ---------------------------------------------------------------------------

def analyze_ai_confidence(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return AI-confidence percentiles, histogram, and low-confidence alerts.

    Rows that lack the ``ai_confidence`` field are silently skipped.
    """
    values: list[float] = []
    for row in rows:
        v = row.get("ai_confidence")
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass

    if not values:
        return {
            "ai_confidence_distribution": {
                "available": False,
                "reason": "no ai_confidence field found in rows",
            },
            "low_confidence_alerts": [],
        }

    bins: dict[str, int] = {
        "0.0-0.5": 0,
        "0.5-0.7": 0,
        "0.7-0.8": 0,
        "0.8-0.9": 0,
        "0.9-1.0": 0,
    }
    for v in values:
        if v < 0.5:
            bins["0.0-0.5"] += 1
        elif v < 0.7:
            bins["0.5-0.7"] += 1
        elif v < 0.8:
            bins["0.7-0.8"] += 1
        elif v < 0.9:
            bins["0.8-0.9"] += 1
        else:
            bins["0.9-1.0"] += 1

    n = len(values)
    bin_ratios = {k: round(cnt / n, 4) for k, cnt in bins.items()}
    p25 = _percentile(values, 25)

    distribution: dict[str, Any] = {
        "available": True,
        "count": n,
        "p10": round(_percentile(values, 10), 4),
        "p25": round(p25, 4),
        "p50": round(_percentile(values, 50), 4),
        "p75": round(_percentile(values, 75), 4),
        "p90": round(_percentile(values, 90), 4),
        "histogram": bins,
        "histogram_ratios": bin_ratios,
    }

    alerts: list[dict[str, Any]] = []
    if p25 < CONFIDENCE_LOW_P25_THRESHOLD:
        alerts.append(
            {
                "alert_type": "low_confidence_tail_alert",
                "reason": f"p25={round(p25, 4)} < threshold={CONFIDENCE_LOW_P25_THRESHOLD}",
                "metric": "p25",
                "value": round(p25, 4),
                "threshold": CONFIDENCE_LOW_P25_THRESHOLD,
            }
        )

    low_bin_ratio = bin_ratios["0.0-0.5"]
    if low_bin_ratio > CONFIDENCE_LOW_BIN_THRESHOLD:
        alerts.append(
            {
                "alert_type": "low_confidence_tail_alert",
                "reason": f"0.0-0.5 bin ratio={low_bin_ratio} > threshold={CONFIDENCE_LOW_BIN_THRESHOLD}",
                "metric": "bin_0.0-0.5",
                "value": low_bin_ratio,
                "threshold": CONFIDENCE_LOW_BIN_THRESHOLD,
            }
        )

    return {
        "ai_confidence_distribution": distribution,
        "low_confidence_alerts": alerts,
    }


# ---------------------------------------------------------------------------
# D3: Mart absolute-volume sanity
# ---------------------------------------------------------------------------

def analyze_volume_sanity(
    crawler_rows: list[dict[str, Any]],
    final_rows: list[dict[str, Any]],
    min_rows_per_mart: dict[str, int] | None = None,
    attrition_ratio: float = PIPELINE_ATTRITION_RATIO,
) -> dict[str, Any]:
    """Return per-mart volume statistics and undercount / attrition alerts.

    Args:
        crawler_rows: Normalised source (crawler) rows — each must have ``source``.
        final_rows:   Normalised final-DB rows — each must have ``source``.
        min_rows_per_mart: Override for volume thresholds (defaults to constants).
        attrition_ratio: Minimum acceptable final/crawler ratio.

    Returns:
        Dict with keys ``mart_volume_sanity`` and ``volume_alerts``.
    """
    if min_rows_per_mart is None:
        min_rows_per_mart = MIN_ROWS_PER_MART

    crawler_counts: Counter[str] = Counter(_get_mart(r) for r in crawler_rows)
    final_counts: Counter[str] = Counter(_get_mart(r) for r in final_rows)

    all_marts = sorted(
        set(list(crawler_counts) + list(final_counts) + list(min_rows_per_mart))
    )

    sanity: dict[str, Any] = {}
    alerts: list[dict[str, Any]] = []

    for mart in all_marts:
        crawler_n = crawler_counts.get(mart, 0)
        final_n = final_counts.get(mart, 0)
        threshold = min_rows_per_mart.get(mart)

        sanity[mart] = {
            "crawler_count": crawler_n,
            "final_db_count": final_n,
            "min_threshold": threshold,
        }

        if threshold is not None and final_n < threshold:
            alerts.append(
                {
                    "alert_type": "volume_undercount_alert",
                    "mart": mart,
                    "final_db_count": final_n,
                    "min_threshold": threshold,
                    "deficit": threshold - final_n,
                }
            )

        if crawler_n > 0 and final_n < crawler_n * attrition_ratio:
            alerts.append(
                {
                    "alert_type": "pipeline_attrition_alert",
                    "mart": mart,
                    "crawler_count": crawler_n,
                    "final_db_count": final_n,
                    "ratio": round(final_n / crawler_n, 4),
                    "attrition_threshold": attrition_ratio,
                }
            )

    return {
        "mart_volume_sanity": sanity,
        "volume_alerts": alerts,
    }


# ---------------------------------------------------------------------------
# D4: Semantic spot-check
# ---------------------------------------------------------------------------

def semantic_spotcheck(
    rows: list[dict[str, Any]],
    seed: int = 42,
    sample_size: int = SPOTCHECK_SAMPLE_SIZE,
    rules: list[tuple[list[str], str]] | None = None,
    pass_rate_threshold: float = SPOTCHECK_PASS_RATE_THRESHOLD,
) -> dict[str, Any]:
    """Sample rows per mart and flag keyword→category mismatches.

    Args:
        rows: Normalised DB rows with ``raw_title``, ``category``, ``source``.
        seed: Random seed for reproducible sampling.
        sample_size: Max rows sampled per mart.
        rules: Override for keyword→prefix rules (defaults to constants).
        pass_rate_threshold: Minimum acceptable pass rate for spotcheck alert.

    Returns:
        Dict with keys ``semantic_spotcheck`` and ``semantic_alerts``.
    """
    if rules is None:
        rules = KEYWORD_CATEGORY_RULES

    mart_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mart_rows[_get_mart(row)].append(row)

    rng = random.Random(seed)
    sampled_total = 0
    checked_total = 0
    flagged: list[dict[str, Any]] = []
    per_mart: dict[str, dict[str, int]] = {}

    for mart, mart_row_list in sorted(mart_rows.items()):
        sample = rng.sample(mart_row_list, min(sample_size, len(mart_row_list)))
        mart_sampled = len(sample)
        mart_checked = 0
        mart_flagged = 0

        for row in sample:
            title = str(row.get("raw_title") or "").strip()
            category = str(row.get("category") or "").strip()

            # Find first matching rule
            matched_rule: tuple[list[str], str] | None = None
            for keywords, expected_prefix in rules:
                if any(kw in title for kw in keywords):
                    matched_rule = (keywords, expected_prefix)
                    break

            if matched_rule is None:
                continue  # No keyword found — skip to prevent false positives

            mart_checked += 1
            keywords, expected_prefix = matched_rule
            if not category.lower().startswith(expected_prefix.lower()):
                matched_kw = next(kw for kw in keywords if kw in title)
                flagged.append(
                    {
                        "raw_record_id": row.get("raw_record_id"),
                        "mart": mart,
                        "raw_title": title,
                        "category": category,
                        "expected_prefix": expected_prefix,
                        "matched_keyword": matched_kw,
                        "reason": (
                            f"title contains '{matched_kw}' but category "
                            f"'{category}' does not start with '{expected_prefix}'"
                        ),
                    }
                )
                mart_flagged += 1

        sampled_total += mart_sampled
        checked_total += mart_checked
        per_mart[mart] = {
            "sampled": mart_sampled,
            "checked": mart_checked,
            "flagged": mart_flagged,
        }

    pass_rate = (
        round((checked_total - len(flagged)) / checked_total, 4)
        if checked_total > 0
        else 1.0
    )

    alerts: list[dict[str, Any]] = []
    if checked_total > 0 and pass_rate < pass_rate_threshold:
        alerts.append(
            {
                "alert_type": "semantic_spotcheck_alert",
                "pass_rate": pass_rate,
                "threshold": pass_rate_threshold,
                "checked": checked_total,
                "flagged": len(flagged),
            }
        )

    return {
        "semantic_spotcheck": {
            "sampled": sampled_total,
            "checked": checked_total,
            "pass_rate": pass_rate,
            "flagged": flagged,
            "per_mart": per_mart,
        },
        "semantic_alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Launch-gate blocker aggregator
# ---------------------------------------------------------------------------

_CRITICAL_ALERT_TYPES: frozenset[str] = frozenset(
    {
        "category_imbalance_alert",
        "low_confidence_tail_alert",
        "volume_undercount_alert",
        "pipeline_attrition_alert",
        "semantic_spotcheck_alert",
    }
)


def collect_launch_gate_blockers(
    imbalance_alerts: list[dict[str, Any]] | None = None,
    starvation_alerts: list[dict[str, Any]] | None = None,
    confidence_alerts: list[dict[str, Any]] | None = None,
    volume_alerts: list[dict[str, Any]] | None = None,
    semantic_alerts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Collect all critical alerts into a single launch-gate blocker list.

    Starvation alerts are included as warnings but not counted as hard blockers
    (they do not appear in the critical alert type set).
    """
    blockers: list[dict[str, Any]] = []
    for alert in [
        *(imbalance_alerts or []),
        *(confidence_alerts or []),
        *(volume_alerts or []),
        *(semantic_alerts or []),
    ]:
        if alert.get("alert_type") in _CRITICAL_ALERT_TYPES:
            blockers.append(alert)
    return blockers


# ---------------------------------------------------------------------------
# Per-mart stats builder (for markdown summary table)
# ---------------------------------------------------------------------------

def build_mart_stats_for_table(
    normalized_source_rows: list[dict[str, Any]],
    proof_rows: list[dict[str, Any]],
    final_db_rows: list[dict[str, Any]],
    spotcheck_result: dict[str, Any],
    volume_result: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Aggregate per-mart pipeline counters for the summary table."""
    crawler_counts: Counter[str] = Counter(_get_mart(r) for r in normalized_source_rows)
    proof_counts: Counter[str] = Counter(_get_mart(r) for r in proof_rows)
    final_counts: Counter[str] = Counter(_get_mart(r) for r in final_db_rows)

    per_mart_spotcheck: dict[str, dict[str, int]] = (
        spotcheck_result.get("semantic_spotcheck", {}).get("per_mart", {})
    )

    all_marts = sorted(
        set(list(crawler_counts) + list(final_counts))
        | set(volume_result.get("mart_volume_sanity", {}).keys())
    )

    stats: dict[str, dict[str, Any]] = {}
    for mart in all_marts:
        crawler_n = crawler_counts.get(mart, 0)
        proof_n = proof_counts.get(mart, 0)
        final_n = final_counts.get(mart, 0)
        missing_n = max(0, crawler_n - final_n)
        missing_pct = round(missing_n / crawler_n * 100, 1) if crawler_n > 0 else 0

        sc = per_mart_spotcheck.get(mart, {})
        sc_sampled = sc.get("sampled", 0)
        sc_flagged = sc.get("flagged", 0)
        semantic_fail = f"{sc_flagged}/{sc_sampled}" if sc_sampled else "-"

        stats[mart] = {
            "crawler_count": crawler_n,
            "normalized_count": proof_n if proof_n else "-",
            "ai_approved_count": proof_n if proof_n else "-",
            "final_db_count": final_n,
            "missing_count": missing_n,
            "missing_pct": missing_pct,
            "semantic_fail": semantic_fail,
        }
    return stats


# ---------------------------------------------------------------------------
# Markdown summary table formatter
# ---------------------------------------------------------------------------

def format_markdown_summary_table(mart_stats: dict[str, dict[str, Any]]) -> str:
    """Return a markdown table summarising the per-mart pipeline funnel."""
    header = "| 마트     | 크롤러 | 정규화 | AI승인 | 공개DB | 누락           | 시맨틱fail |"
    sep    = "|----------|--------|--------|--------|--------|----------------|------------|"
    rows = [header, sep]
    for mart, s in sorted(mart_stats.items()):
        crawler   = s.get("crawler_count", "-")
        normalized = s.get("normalized_count", "-")
        ai_appr   = s.get("ai_approved_count", "-")
        pub_db    = s.get("final_db_count", "-")
        m_n       = s.get("missing_count", "-")
        m_pct     = s.get("missing_pct", "")
        if m_n != "-" and m_pct != "":
            missing_str = f"{m_n} ({m_pct}%)"
        elif m_n != "-":
            missing_str = str(m_n)
        else:
            missing_str = "-"
        sem = s.get("semantic_fail", "-")
        rows.append(
            f"| {mart:<8} | {str(crawler):>6} | {str(normalized):>6} "
            f"| {str(ai_appr):>6} | {str(pub_db):>6} | {missing_str:<14} | {str(sem):>10} |"
        )
    return "\n".join(rows)
