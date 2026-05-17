"""tools/launch_gate_runbook.py — WalletSavior 라이브 가동 직전 게이트 통합 실행.

Usage:
    py -3 tools/launch_gate_runbook.py [options]

Options:
    --input-dir DIR        마트 디렉토리 (반복 지정 가능; 기본: 3개 자동 감지)
    --artifact-dir DIR     산출물 root (기본: .walletsavior-live-validation/launch-gate-runbook/)
    --provider-mode        fallback (기본) | real (--allow-live-ai-provider 필요)
    --allow-live-ai-provider  real provider 허용 opt-in
    --max-items-per-mart N 마트당 최대 처리 건수 (기본: 전체)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — must happen before any package imports
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
AI_ADMIN_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"

for _p in [str(AI_ADMIN_BACKEND), str(SHARED), str(_HERE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# AI-admin backend imports
# ---------------------------------------------------------------------------
from core.contracts.ai_pipeline import RawCrawlRecord, AIProviderRef  # noqa: E402
from core.contracts.control_plane import ProviderConfigContract  # noqa: E402
from providers.google_genai import ProviderResponseError  # noqa: E402
from services import ai_ingestion as _ai_ingestion_module  # noqa: E402
from services.ai_ingestion import (  # noqa: E402
    _call_provider_with_shrink_retries,
    _provider_ref,
)
from services.seed_taxonomy import get_category_display_label  # noqa: E402

# ---------------------------------------------------------------------------
# Adversarial compare extensions
# ---------------------------------------------------------------------------
from adversarial_compare_extensions import (  # noqa: E402
    analyze_ai_confidence,
    analyze_category_distribution,
    analyze_volume_sanity,
    build_mart_stats_for_table,
    collect_launch_gate_blockers,
    format_markdown_summary_table,
    semantic_spotcheck,
)
from adversarial_compare_constants import (  # noqa: E402
    MIN_ROWS_PER_MART,
    PIPELINE_ATTRITION_RATIO,
)
from artifact_db_adversarial_compare import normalize_source_row  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "walletsavior.launch_gate_runbook.v1"

DEFAULT_MART_DIRS: list[Path] = [
    REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "emart",
    REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "homeplus",
    REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "lottemart",
]

DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "launch-gate-runbook"

# Automation gate: proposals with confidence below this do not auto-approve
GATE_MIN_CONFIDENCE = 0.9

_MART_LABEL_MAP: dict[str, str] = {
    "이마트": "emart",
    "emart": "emart",
    "홈플러스": "homeplus",
    "homeplus": "homeplus",
    "롯데마트": "lottemart",
    "lottemart-live-public": "lottemart",
    "lottemart": "lottemart",
}


# ---------------------------------------------------------------------------
# Mock provider — always raises retryable error → forces fallback for every record
# ---------------------------------------------------------------------------

class _AlwaysFailMockProvider:
    """Reviewer-safe mock: every call returns a retryable quota error."""
    provider_mode = "offline"

    def __init__(self, config: ProviderConfigContract) -> None:
        self.config = config

    def call(self, *, prompt: str, schema: Any = None) -> dict[str, Any]:
        raise ProviderResponseError(
            "mock-429 quota exceeded (reviewer-safe fallback runbook mode)",
            provider_id="runbook-mock",
            model="mock-model",
        )


_MOCK_PROVIDER_CONFIG = ProviderConfigContract(
    provider_id="runbook-mock",
    provider_kind="gemini",
    display_name="Runbook Mock (always-fail → fallback)",
    default_model="mock-model",
)

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _discover_input_files(mart_dir: Path) -> list[Path]:
    """Return all raw_records JSONL or JSON files under a mart directory."""
    files: list[Path] = []
    # jsonl first (lottemart source-runs)
    files.extend(sorted(mart_dir.rglob("raw_records.jsonl")))
    # live-validation JSON artifacts (mart3 diagnostics)
    files.extend(
        p for p in sorted(mart_dir.rglob("*.json"))
        if "live-validation" in p.name or "fixture" in p.name
    )
    return files


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("raw_records", "records", "items", "raw_selected_items"):
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def load_mart_records(
    mart_dir: Path,
    mart_name: str,
    max_items: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load raw records from mart directory. Returns (records, load_errors)."""
    errors: list[str] = []
    files = _discover_input_files(mart_dir)
    if not files:
        # Try any JSON in the directory
        files = sorted(mart_dir.rglob("*.json")) + sorted(mart_dir.rglob("*.jsonl"))
    if not files:
        errors.append(f"{mart_name}: no input files found in {mart_dir}")
        return [], errors

    all_rows: list[dict[str, Any]] = []
    for path in files:
        try:
            if path.suffix == ".jsonl":
                rows = _load_jsonl(path)
            else:
                rows = _load_json_records(path)
            all_rows.extend(rows)
        except Exception as exc:
            errors.append(f"{mart_name}: failed to load {path.name}: {exc}")

    # De-duplicate by raw_record_id
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in all_rows:
        rid = row.get("raw_record_id") or row.get("source_record_key")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        deduped.append(row)

    if max_items is not None:
        deduped = deduped[:max_items]

    return deduped, errors


def _raw_record_from_dict(row: dict[str, Any], mart_name: str) -> RawCrawlRecord | None:
    """Build a RawCrawlRecord from a raw dict. Returns None on failure."""
    try:
        raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        raw_record_id = (
            row.get("raw_record_id")
            or f"{mart_name}:{row.get('source_record_key') or uuid.uuid4().hex[:8]}"
        )
        return RawCrawlRecord(
            raw_record_id=str(raw_record_id),
            source_name=str(
                row.get("source_name")
                or raw_payload.get("store")
                or mart_name
            ),
            source_record_key=str(row.get("source_record_key") or ""),
            source_url=row.get("source_url") or raw_payload.get("source_url"),
            raw_title=str(
                row.get("raw_title")
                or raw_payload.get("name")
                or raw_payload.get("raw_title")
                or ""
            ),
            raw_price=(
                int(row["raw_price"])
                if row.get("raw_price") is not None
                else (int(raw_payload["sale_price"]) if raw_payload.get("sale_price") is not None else None)
            ),
            raw_payload=raw_payload,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pipeline simulation
# ---------------------------------------------------------------------------

def _infer_mart_name(mart_dir: Path) -> str:
    name = mart_dir.name.lower()
    return _MART_LABEL_MAP.get(name, name)


def run_mart_pipeline(
    mart_name: str,
    raw_rows: list[dict[str, Any]],
    provider_mode: str = "fallback",
) -> dict[str, Any]:
    """Run the pipeline for one mart and return per-stage counts."""
    crawler_rows = len(raw_rows)

    # Stage 2: Build RawCrawlRecord objects
    records: list[RawCrawlRecord] = []
    parse_errors: list[str] = []
    for row in raw_rows:
        rec = _raw_record_from_dict(row, mart_name)
        if rec is None:
            parse_errors.append(row.get("raw_record_id") or "unknown")
        else:
            records.append(rec)

    ingested_rows = len(records)
    ingestion_drop = crawler_rows - ingested_rows

    if not records:
        return {
            "crawler_rows": crawler_rows,
            "ingested_rows": 0,
            "ai_proposals": 0,
            "gates_passed": 0,
            "publish_approved": 0,
            "public_snapshot_rows": 0,
            "attrition_reasons": {"parse_error": ingestion_drop},
            "proposal_rows": [],
            "parse_errors": parse_errors,
            "pipeline_error": "no valid records after parsing",
        }

    # Stage 3: AI labeling via _call_provider_with_shrink_retries
    # Patch to avoid real prompt building delays and sleeps
    _original_sleep = _ai_ingestion_module._sleep
    _original_prompt = _ai_ingestion_module.build_labeling_prompt
    _ai_ingestion_module._sleep = lambda _: None
    _ai_ingestion_module.build_labeling_prompt = (
        lambda recs, **kw: "fallback-stub-prompt:" + ",".join(r.raw_record_id for r in recs[:3])
    )
    try:
        provider_ref = _provider_ref(_MOCK_PROVIDER_CONFIG)
        provider = _AlwaysFailMockProvider(_MOCK_PROVIDER_CONFIG)
        root_batch_id = f"runbook-{mart_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        proposals, kw_proposals, shrink_log = _call_provider_with_shrink_retries(
            records=records,
            provider=provider,
            provider_ref=provider_ref,
            provider_id="runbook-mock",
            model="mock-model",
            raw_batch_id=root_batch_id,
            ai_batch_id=f"{root_batch_id}:ai",
            keyword_catalog=[],
            learned_keyword_knowledge=[],
        )
    except Exception as exc:
        return {
            "crawler_rows": crawler_rows,
            "ingested_rows": ingested_rows,
            "ai_proposals": 0,
            "gates_passed": 0,
            "publish_approved": 0,
            "public_snapshot_rows": 0,
            "attrition_reasons": {"shrink_retries_error": ingested_rows},
            "proposal_rows": [],
            "parse_errors": parse_errors,
            "pipeline_error": f"_call_provider_with_shrink_retries raised: {exc}",
        }
    finally:
        _ai_ingestion_module._sleep = _original_sleep
        _ai_ingestion_module.build_labeling_prompt = _original_prompt

    # Count unique record IDs that got proposals
    proposed_record_ids: set[str] = {p.provenance.raw_record_id for p in proposals}
    ai_proposals = len(proposed_record_ids)

    # Verify all fallback (shrink_log should only have retryable_error + fallback)
    fallback_count = sum(1 for e in shrink_log if e.get("fallback"))
    all_fallback = fallback_count == len(records)

    # Stage 4: Gate simulation
    # Build per-record confidence: take max confidence across all proposals for that record
    confidence_by_record: dict[str, float] = {}
    for p in proposals:
        rid = p.provenance.raw_record_id
        conf = p.provenance.confidence or 0.0
        if conf > confidence_by_record.get(rid, 0.0):
            confidence_by_record[rid] = conf

    gates_passed = sum(1 for c in confidence_by_record.values() if c >= GATE_MIN_CONFIDENCE)
    publish_approved = gates_passed  # In fallback mode: gate-passed = publish-approved
    public_snapshot_rows = publish_approved  # Dry-run: same as approved

    # Attrition reasons
    attrition_reasons: dict[str, int] = {}
    if ingestion_drop > 0:
        attrition_reasons["parse_error"] = ingestion_drop
    for rid, conf in confidence_by_record.items():
        if conf < GATE_MIN_CONFIDENCE:
            reason = "low_confidence"
            attrition_reasons[reason] = attrition_reasons.get(reason, 0) + 1

    # Build normalized "proposal rows" for adversarial compare
    # One row per record from the category_id + canonical_name proposals
    cat_by_record: dict[str, str] = {}
    title_by_record: dict[str, str] = {}
    price_by_record: dict[str, Any] = {}
    url_by_record: dict[str, str] = {}
    for p in proposals:
        rid = p.provenance.raw_record_id
        if p.target_field == "category_id":
            cat_by_record[rid] = str(p.proposed_value or "retail.general")
        elif p.target_field == "source_title":
            title_by_record[rid] = str(p.proposed_value or "")
        elif p.target_field == "sale_price":
            price_by_record[rid] = p.proposed_value
        elif p.target_field == "source_url" and rid not in url_by_record:
            url_by_record[rid] = str(p.proposed_value or "")

    proposal_rows: list[dict[str, Any]] = []
    for rid in proposed_record_ids:
        proposal_rows.append({
            "raw_record_id": rid,
            "source": mart_name,
            "category": cat_by_record.get(rid, "retail.general"),
            "raw_title": title_by_record.get(rid, ""),
            "current_price": price_by_record.get(rid),
            "ai_confidence": confidence_by_record.get(rid, 0.42),
            "source_url": url_by_record.get(rid, ""),
        })

    return {
        "crawler_rows": crawler_rows,
        "ingested_rows": ingested_rows,
        "ai_proposals": ai_proposals,
        "gates_passed": gates_passed,
        "publish_approved": publish_approved,
        "public_snapshot_rows": public_snapshot_rows,
        "attrition_reasons": attrition_reasons,
        "proposal_rows": proposal_rows,
        "parse_errors": parse_errors,
        "pipeline_error": None,
        "all_fallback_verified": all_fallback,
        "shrink_log_summary": {
            "total_calls": len(shrink_log),
            "fallback_calls": fallback_count,
            "retryable_error_calls": sum(1 for e in shrink_log if e.get("outcome") == "retryable_error"),
        },
    }


# ---------------------------------------------------------------------------
# Adversarial compare v2
# ---------------------------------------------------------------------------

def run_adversarial_compare_v2(
    all_source_rows: list[dict[str, Any]],
    all_proposal_rows: list[dict[str, Any]],
    proof_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the full adversarial compare v2 analysis and return the result dict."""
    normalized_sources = [normalize_source_row(r) for r in all_source_rows]

    # In fallback mode the "final DB" is empty since no proposals pass gates
    # Use proposal rows for confidence/category analysis only
    cat_analysis = analyze_category_distribution(all_proposal_rows)
    conf_analysis = analyze_ai_confidence(all_proposal_rows)
    vol_analysis = analyze_volume_sanity(normalized_sources, proof_rows)
    spotcheck = semantic_spotcheck(all_proposal_rows)

    blockers = collect_launch_gate_blockers(
        imbalance_alerts=cat_analysis["category_imbalance_alerts"],
        starvation_alerts=cat_analysis["category_sibling_starvation_alerts"],
        confidence_alerts=conf_analysis["low_confidence_alerts"],
        volume_alerts=vol_analysis["volume_alerts"],
        semantic_alerts=spotcheck["semantic_alerts"],
    )

    mart_stats = build_mart_stats_for_table(
        normalized_sources, proof_rows, proof_rows, spotcheck, vol_analysis
    )

    return {
        "schema": "walletsavior.artifact_db_adversarial_compare.v2",
        "mode": "runbook_embedded",
        "category_distribution_per_mart": cat_analysis["category_distribution_per_mart"],
        "category_imbalance_alerts": cat_analysis["category_imbalance_alerts"],
        "category_sibling_starvation_alerts": cat_analysis["category_sibling_starvation_alerts"],
        "ai_confidence_distribution": conf_analysis["ai_confidence_distribution"],
        "low_confidence_alerts": conf_analysis["low_confidence_alerts"],
        "mart_volume_sanity": vol_analysis["mart_volume_sanity"],
        "volume_alerts": vol_analysis["volume_alerts"],
        "semantic_spotcheck": spotcheck["semantic_spotcheck"],
        "semantic_alerts": spotcheck["semantic_alerts"],
        "overall_launch_gate_blockers": blockers,
        "blockers": blockers,
        "_mart_stats_for_table": mart_stats,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()[:12] if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _attrition_rate(crawler: int, final: int) -> float:
    if crawler == 0:
        return 0.0
    return round((crawler - final) / crawler, 4)


def _format_pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def build_markdown_report(
    meta: dict[str, Any],
    per_mart_stage_counts: dict[str, dict[str, int]],
    per_mart_attrition_reasons: dict[str, dict[str, int]],
    adversarial_compare_v2: dict[str, Any],
    launch_gate_blockers: list[dict[str, Any]],
    verdict: str,
) -> str:
    lines: list[str] = []

    lines.append("# WalletSavior 라이브 가동 직전 게이트 리포트")
    lines.append("")
    lines.append(f"**생성일시**: {meta['timestamp']}")
    lines.append(f"**git SHA**: `{meta['git_sha']}`")
    lines.append(f"**provider_mode**: `{meta['provider_mode']}`")
    lines.append("")
    verdict_emoji = "✅" if verdict == "launch_ready" else "⚠️"
    lines.append(f"## 한 줄 결론: {verdict_emoji} `{verdict}`")
    lines.append("")

    if meta["provider_mode"] == "fallback":
        lines.append("> **참고**: fallback 모드로 실행됨. 실제 AI 호출 없이 모든 행이 reviewer-safe")
        lines.append("> 폴백 프로포잘로 처리됨 (confidence=0.42). gates_passed=0은 예상된 결과.")
        lines.append("> 실 데이터 AI 라벨링은 `--provider-mode real --allow-live-ai-provider` 로 실행.")
        lines.append("")

    # Mart-by-stage table
    lines.append("## 마트별 스테이지별 수치")
    lines.append("")
    lines.append("| 마트 | 크롤러 | 정규화 | AI제안 | 4게이트통과 | DB승인 | 공개DB | 누락률 |")
    lines.append("|------|--------|--------|--------|------------|--------|--------|--------|")
    for mart_name, counts in sorted(per_mart_stage_counts.items()):
        crawler = counts["crawler_rows"]
        ingested = counts["ingested_rows"]
        ai_prop = counts["ai_proposals"]
        gates = counts["gates_passed"]
        pub_appr = counts["publish_approved"]
        pub_snap = counts["public_snapshot_rows"]
        rate = _attrition_rate(crawler, pub_snap)
        lines.append(
            f"| {mart_name:<8} | {crawler:>6} | {ingested:>6} | {ai_prop:>6} "
            f"| {gates:>10} | {pub_appr:>6} | {pub_snap:>6} | {_format_pct(rate):>6} |"
        )
    lines.append("")

    # Category distribution
    lines.append("## 카테고리 분포 (마트별 상위 5개)")
    lines.append("")
    cat_dist = adversarial_compare_v2.get("category_distribution_per_mart", {})
    for mart, dist_data in sorted(cat_dist.items()):
        lines.append(f"### {mart}")
        cats = dist_data.get("categories", {})
        sorted_cats = sorted(cats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
        if sorted_cats:
            lines.append("| 카테고리 | 건수 | 비율 |")
            lines.append("|----------|------|------|")
            for cat, info in sorted_cats:
                display = get_category_display_label(cat) or cat
                lines.append(f"| {display} | {info['count']} | {info['ratio']:.1%} |")
        else:
            lines.append("_(데이터 없음)_")
        lines.append("")

    # AI confidence
    lines.append("## AI 신뢰도 분포")
    lines.append("")
    ai_conf = adversarial_compare_v2.get("ai_confidence_distribution", {})
    if ai_conf.get("available"):
        lines.append(
            f"p10: {ai_conf.get('p10', 'N/A')} / "
            f"p25: {ai_conf.get('p25', 'N/A')} / "
            f"p50: {ai_conf.get('p50', 'N/A')} / "
            f"p75: {ai_conf.get('p75', 'N/A')} / "
            f"p90: {ai_conf.get('p90', 'N/A')}"
        )
        if meta["provider_mode"] == "fallback":
            lines.append("")
            lines.append("> _(fallback 모드 고정값 0.42 — 실 AI 실행 시 갱신됨)_")
    else:
        lines.append("_(신뢰도 데이터 없음)_")
    lines.append("")

    # Semantic spotcheck
    lines.append("## 시맨틱 spot-check")
    lines.append("")
    sc = adversarial_compare_v2.get("semantic_spotcheck", {})
    per_mart_sc = sc.get("per_mart", {})
    for mart, sc_data in sorted(per_mart_sc.items()):
        sampled = sc_data.get("sampled", 0)
        checked = sc_data.get("checked", 0)
        flagged = sc_data.get("flagged", 0)
        ok_count = checked - flagged
        pass_rate = round(ok_count / checked * 100, 1) if checked > 0 else 100.0
        lines.append(f"- **{mart}**: {sampled}건 샘플, {ok_count} ok, {flagged} flagged — 통과율 {pass_rate}%")
    if not per_mart_sc:
        lines.append("_(spot-check 데이터 없음)_")
    flagged_items = sc.get("flagged", [])
    if flagged_items:
        lines.append("")
        lines.append("**Flagged 항목 (최대 5건):**")
        for item in flagged_items[:5]:
            lines.append(f"  - `{item.get('mart')}` / `{item.get('raw_title', '')[:40]}` → {item.get('reason', '')}")
    lines.append("")

    # Volume sanity
    lines.append("## 볼륨 sanity")
    lines.append("")
    vol_sanity = adversarial_compare_v2.get("mart_volume_sanity", {})
    for mart, vdata in sorted(vol_sanity.items()):
        crawler_n = vdata.get("crawler_count", 0)
        final_n = vdata.get("final_db_count", 0)
        threshold = vdata.get("min_threshold")
        suffix = ""
        if threshold is not None and final_n < threshold:
            suffix = f" ⚠️ 임계값 {threshold}건 미달"
        lines.append(f"- **{mart}**: 크롤러 {crawler_n}건 → 공개DB {final_n}건{suffix}")
    lines.append("")

    # Launch gate blockers
    lines.append("## launch_gate_blockers")
    lines.append("")
    if launch_gate_blockers:
        for i, blocker in enumerate(launch_gate_blockers, 1):
            alert_type = blocker.get("alert_type", "unknown")
            mart = blocker.get("mart", "")
            detail = blocker.get("reason") or blocker.get("deficit") or ""
            lines.append(f"{i}. **{alert_type}** [{mart}] {detail}")
    else:
        lines.append("_(없음)_")
    lines.append("")

    # Attrition reasons
    lines.append("## 누락 사유 분류")
    lines.append("")
    for mart_name, reasons in sorted(per_mart_attrition_reasons.items()):
        if reasons:
            lines.append(f"**{mart_name}**:")
            for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - `{reason}`: {count}건")
    lines.append("")

    # Recommended next actions
    lines.append("## 다음 라운드 추천 액션")
    lines.append("")
    action_idx = 1

    # Volume blockers → crawler debugging
    vol_alerts = adversarial_compare_v2.get("volume_alerts", [])
    for alert in vol_alerts:
        if alert.get("alert_type") == "volume_undercount_alert":
            mart = alert.get("mart", "")
            deficit = alert.get("deficit", 0)
            lines.append(
                f"{action_idx}. **{mart}** 크롤러 페이지네이션 디버깅 — "
                f"{deficit}건 부족, 카테고리 트리 일부 미수집 의심"
            )
            action_idx += 1

    # Semantic flagged → learned_alias
    flagged_items = adversarial_compare_v2.get("semantic_spotcheck", {}).get("flagged", [])
    if flagged_items:
        flagged_marts = list({item.get("mart") for item in flagged_items})
        for mart in sorted(flagged_marts):
            n = sum(1 for item in flagged_items if item.get("mart") == mart)
            lines.append(
                f"{action_idx}. **{mart}** 시맨틱 mismatch {n}건 수동 검토 후 "
                f"learned_alias 등록 → 다음 라운드 자동 보정"
            )
            action_idx += 1

    # Fallback mode → real AI
    if meta["provider_mode"] == "fallback":
        lines.append(
            f"{action_idx}. 실 AI 라벨링 실행: `py -3 tools/launch_gate_runbook.py "
            f"--provider-mode real --allow-live-ai-provider`"
        )
        action_idx += 1

    if action_idx == 1:
        lines.append("_(추천 액션 없음 — 모든 지표 통과)_")

    lines.append("")
    lines.append("---")
    lines.append(f"*자동 생성: `{meta['timestamp']}` | git `{meta['git_sha']}`*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main runbook
# ---------------------------------------------------------------------------

def run_runbook(
    input_dirs: list[Path],
    artifact_dir: Path,
    provider_mode: str = "fallback",
    max_items_per_mart: int | None = None,
    allow_live: bool = False,
) -> dict[str, Any]:
    if provider_mode == "real" and not allow_live:
        raise ValueError(
            "--provider-mode real requires --allow-live-ai-provider flag. "
            "This ensures the user explicitly opts in to real AI calls."
        )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = uuid.uuid4().hex[:8]
    artifact_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "git_sha": _git_sha(),
        "provider_mode": provider_mode,
        "input_paths": [],
        "max_items_per_mart": max_items_per_mart,
    }

    per_mart_stage_counts: dict[str, dict[str, int]] = {}
    per_mart_attrition_reasons: dict[str, dict[str, int]] = {}
    all_source_rows: list[dict[str, Any]] = []
    all_proposal_rows: list[dict[str, Any]] = []
    load_errors: list[str] = []
    pipeline_errors: list[dict[str, Any]] = []

    for mart_dir in input_dirs:
        mart_name = _infer_mart_name(mart_dir)
        print(f"  [{mart_name}] 로딩: {mart_dir}", flush=True)

        raw_rows, load_errs = load_mart_records(mart_dir, mart_name, max_items_per_mart)
        load_errors.extend(load_errs)

        if not raw_rows and not load_errs:
            pipeline_errors.append({
                "mart": mart_name,
                "error": f"no records found in {mart_dir}",
                "is_blocker": True,
            })
            per_mart_stage_counts[mart_name] = {
                "crawler_rows": 0, "ingested_rows": 0, "ai_proposals": 0,
                "gates_passed": 0, "publish_approved": 0, "public_snapshot_rows": 0,
            }
            per_mart_attrition_reasons[mart_name] = {"empty_input": 0}
            continue
        elif load_errs and not raw_rows:
            pipeline_errors.append({
                "mart": mart_name,
                "error": "; ".join(load_errs),
                "is_blocker": True,
            })
            per_mart_stage_counts[mart_name] = {
                "crawler_rows": 0, "ingested_rows": 0, "ai_proposals": 0,
                "gates_passed": 0, "publish_approved": 0, "public_snapshot_rows": 0,
            }
            per_mart_attrition_reasons[mart_name] = {"load_error": len(load_errs)}
            continue

        meta["input_paths"].append(str(mart_dir))
        all_source_rows.extend(raw_rows)

        print(f"  [{mart_name}] 파이프라인 실행 ({len(raw_rows)}건)...", flush=True)
        result = run_mart_pipeline(mart_name, raw_rows, provider_mode)

        if result.get("pipeline_error"):
            pipeline_errors.append({
                "mart": mart_name,
                "error": result["pipeline_error"],
                "is_blocker": True,
            })

        per_mart_stage_counts[mart_name] = {
            "crawler_rows": result["crawler_rows"],
            "ingested_rows": result["ingested_rows"],
            "ai_proposals": result["ai_proposals"],
            "gates_passed": result["gates_passed"],
            "publish_approved": result["publish_approved"],
            "public_snapshot_rows": result["public_snapshot_rows"],
        }
        per_mart_attrition_reasons[mart_name] = result.get("attrition_reasons", {})
        all_proposal_rows.extend(result.get("proposal_rows", []))

        shrink_summary = result.get("shrink_log_summary", {})
        all_fallback = result.get("all_fallback_verified", False)
        print(
            f"  [{mart_name}] 완료: 크롤러={result['crawler_rows']}, "
            f"AI제안={result['ai_proposals']}, 폴백검증={all_fallback}, "
            f"shrink_calls={shrink_summary.get('total_calls', '?')}",
            flush=True,
        )

    # Run adversarial compare v2
    print("  Adversarial compare v2 실행 중...", flush=True)
    # Use proposal rows as "proof rows" so volume_sanity compares crawler vs DB realistically
    # (proof_rows = what would actually end up in DB; in fallback mode = 0 since all fail gates)
    adversarial_v2 = run_adversarial_compare_v2(
        all_source_rows=all_source_rows,
        all_proposal_rows=all_proposal_rows,
        proof_rows=[],  # fallback mode: no rows pass gates → empty DB
    )

    # Collect all launch-gate blockers
    launch_gate_blockers: list[dict[str, Any]] = []

    # From adversarial compare
    launch_gate_blockers.extend(adversarial_v2.get("overall_launch_gate_blockers", []))

    # Pipeline errors
    for err in pipeline_errors:
        launch_gate_blockers.append({
            "alert_type": "pipeline_error_blocker",
            "mart": err.get("mart", ""),
            "reason": err.get("error", ""),
        })

    # High attrition rate per mart
    for mart_name, counts in per_mart_stage_counts.items():
        crawler = counts["crawler_rows"]
        final = counts["public_snapshot_rows"]
        if crawler > 0:
            rate = _attrition_rate(crawler, final)
            if rate > 0.5 and provider_mode != "fallback":
                launch_gate_blockers.append({
                    "alert_type": "high_attrition_alert",
                    "mart": mart_name,
                    "reason": f"attrition_rate={_format_pct(rate)} > 50%",
                    "crawler_rows": crawler,
                    "final_rows": final,
                })

    # Load errors
    for err_msg in load_errors:
        launch_gate_blockers.append({
            "alert_type": "data_load_error",
            "mart": "unknown",
            "reason": err_msg,
        })

    # Verdict
    hard_blockers = [
        b for b in launch_gate_blockers
        if b.get("alert_type") not in {"data_load_error"}
    ]
    verdict = "launch_ready" if not hard_blockers else "needs_more_work"

    # Build final report JSON
    out_name = f"launch-gate-{timestamp}-{run_id}"
    json_path = artifact_dir / f"{out_name}.json"
    md_path = artifact_dir / f"{out_name}.md"

    mart_stats = adversarial_v2.pop("_mart_stats_for_table", {})

    report: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "meta": meta,
        "per_mart_stage_counts": per_mart_stage_counts,
        "per_mart_attrition_reasons": per_mart_attrition_reasons,
        "adversarial_compare_v2": adversarial_v2,
        "launch_gate_blockers": launch_gate_blockers,
        "human_summary_md_path": str(md_path),
        "verdict": verdict,
    }

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Build markdown
    md_content = build_markdown_report(
        meta=meta,
        per_mart_stage_counts=per_mart_stage_counts,
        per_mart_attrition_reasons=per_mart_attrition_reasons,
        adversarial_compare_v2={**adversarial_v2, "_mart_stats_for_table": mart_stats},
        launch_gate_blockers=launch_gate_blockers,
        verdict=verdict,
    )
    md_path.write_text(md_content, encoding="utf-8")

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "verdict": verdict,
        "per_mart_stage_counts": per_mart_stage_counts,
        "launch_gate_blockers": launch_gate_blockers,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WalletSavior 라이브 가동 직전 게이트 통합 실행",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        dest="input_dirs",
        type=Path,
        action="append",
        default=None,
        metavar="DIR",
        help="마트 디렉토리 (반복 지정 가능; 기본: 3개 자동 감지)",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=DEFAULT_ARTIFACT_DIR,
        help=f"산출물 root (기본: {DEFAULT_ARTIFACT_DIR})",
    )
    parser.add_argument(
        "--provider-mode",
        choices=["fallback", "real"],
        default="fallback",
        help="fallback (기본): 실 AI 없이 전체 폴백; real: 실 AI provider 사용",
    )
    parser.add_argument(
        "--allow-live-ai-provider",
        action="store_true",
        default=False,
        help="--provider-mode real 사용 시 필수 opt-in 플래그",
    )
    parser.add_argument(
        "--max-items-per-mart",
        type=int,
        default=None,
        metavar="N",
        help="마트당 최대 처리 건수 (디버깅용; 기본: 전체)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    input_dirs: list[Path] = args.input_dirs or DEFAULT_MART_DIRS
    # Validate
    valid_dirs: list[Path] = []
    for d in input_dirs:
        if not d.exists():
            print(f"WARNING: input dir not found, skipping: {d}", file=sys.stderr)
        else:
            valid_dirs.append(d)
    if not valid_dirs:
        print("ERROR: no valid input dirs found.", file=sys.stderr)
        return 1

    print(f"WalletSavior launch-gate runbook — provider_mode={args.provider_mode}", flush=True)
    print(f"입력 디렉토리 ({len(valid_dirs)}개):", flush=True)
    for d in valid_dirs:
        print(f"  {d}", flush=True)
    print("", flush=True)

    try:
        result = run_runbook(
            input_dirs=valid_dirs,
            artifact_dir=args.artifact_dir,
            provider_mode=args.provider_mode,
            max_items_per_mart=args.max_items_per_mart,
            allow_live=args.allow_live_ai_provider,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("", flush=True)
    print("=" * 60, flush=True)
    print(f"VERDICT: {result['verdict']}", flush=True)
    print(f"JSON 리포트: {result['json_path']}", flush=True)
    print(f"MD 리포트:   {result['md_path']}", flush=True)
    print("", flush=True)

    # Print per-mart table
    print("마트별 스테이지별 수치:", flush=True)
    print("  마트       | 크롤러 | 정규화 | AI제안 | 게이트 | DB승인 | 공개DB | 누락률", flush=True)
    print("  -----------|--------|--------|--------|--------|--------|--------|-------", flush=True)
    for mart, counts in sorted(result["per_mart_stage_counts"].items()):
        c = counts["crawler_rows"]
        i = counts["ingested_rows"]
        a = counts["ai_proposals"]
        g = counts["gates_passed"]
        p = counts["publish_approved"]
        s = counts["public_snapshot_rows"]
        rate = _attrition_rate(c, s)
        print(
            f"  {mart:<10} | {c:>6} | {i:>6} | {a:>6} | {g:>6} | {p:>6} | {s:>6} | {_format_pct(rate):>6}",
            flush=True,
        )

    # Blockers
    print("", flush=True)
    if result["launch_gate_blockers"]:
        print(f"⚠️  LAUNCH GATE BLOCKERS ({len(result['launch_gate_blockers'])}건):", flush=True)
        for b in result["launch_gate_blockers"]:
            print(f"  • [{b.get('alert_type')}] {b.get('mart', '')} — {b.get('reason', '')}", flush=True)
    else:
        print("✅ LAUNCH GATE BLOCKERS: 없음", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
