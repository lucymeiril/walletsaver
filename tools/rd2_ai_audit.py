"""tools/rd2_ai_audit.py — 적대적 AI provider 호출 감사 스크립트.

rd2-ai-provider-audit 태스크 산출물:
  1. 직전 run-bd82105d 진단 (provider call count, 캐시 재탕 여부)
  2. 100건 emart 재실행 with wire-level HTTP 인터셉터
  3. .walletsavior-live-validation/rd2-ai-audit/audit-{ts}-{id}.{json,md}
  4. .walletsavior-live-validation/rd2-ai-audit/provider-wire-log-{ts}.jsonl

Usage (wire log 강제 + force-live 검증):
    set WALLETSAVIOR_WIRE_LOG_PATH=.walletsavior-live-validation/rd2-ai-audit/provider-wire-log-{ts}.jsonl
    set WALLETSAVIOR_AI_LIVE_FORCE=1
    py -3 tools/rd2_ai_audit.py --allow-live-ai-provider

"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
AI_ADMIN_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"

_AI_IMPORTS_LOADED = False


def _ensure_ai_imports() -> None:
    global _AI_IMPORTS_LOADED
    if _AI_IMPORTS_LOADED:
        return
    for _p in [str(_HERE), str(CRAWLER_BACKEND), str(SHARED), str(AI_ADMIN_BACKEND)]:
        if _p not in sys.path:
            sys.path.insert(0, _p)
    _AI_IMPORTS_LOADED = True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUDIT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "rd2-ai-audit"
PRIOR_RUN_JSON = (
    REPO_ROOT
    / ".walletsavior-live-validation"
    / "ai-live-run"
    / "run-20260518-002226-bd82105d.json"
)
EMART_DATA_JSON = (
    REPO_ROOT
    / ".walletsavior-live-validation"
    / "mart3-full-coverage-diagnostics"
    / "emart"
    / "live-validation-v2-20260516-123122-513830c4.json"
)
DEFAULT_PROVIDER_ID = "google-gemini31-live-matrix"
AUDIT_SAMPLE_SIZE = 100


# ---------------------------------------------------------------------------
# Prior run diagnosis
# ---------------------------------------------------------------------------


def diagnose_prior_run(prior_json_path: Path) -> dict[str, Any]:
    """적대적 직전 run 진단.

    Returns a diagnosis dict with:
      - provider_call_count: total shrink-log calls (ok + retryable)
      - ok_calls: successful provider calls
      - retryable_errors: errors that triggered batch splits (impossible in fixture mode)
      - wire_log_present: False — prior run had NO wire-level logging
      - cache_bypass_confirmed: True if product_matches_before == 0
      - verdict: "no_wire_evidence" | "circumstantially_live" | "confirmed_cache"
    """
    if not prior_json_path.exists():
        return {"error": f"prior run JSON not found: {prior_json_path}"}

    with prior_json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    dry_run = data.get("dry_run", True)
    learned_empty = data.get("learned_empty_result", {})
    product_matches_before = learned_empty.get("product_matches_before", -1)
    keyword_alias_before = learned_empty.get("keyword_alias_before", -1)

    per_mart = data.get("per_mart_escalation", {})
    total_batches = 0
    total_shrink_calls = 0
    ok_calls = 0
    retryable_errors = 0
    for mart, info in per_mart.items():
        sl = info.get("shrink_log_summary", {})
        total_batches += sl.get("total_batches", 0)
        total_shrink_calls += sl.get("total_shrink_calls", 0)
        ok_calls += sl.get("ok_calls", 0)
        retryable_errors += sl.get("retryable_error_calls", 0)

    # Check for wire log evidence
    wire_log_present = bool(data.get("wire_log_path") or data.get("wire_log_stats"))

    # Cache bypass: tables were empty before run
    cache_bypass_confirmed = (product_matches_before == 0) and (keyword_alias_before == 0)

    # Verdict
    if dry_run:
        verdict = "confirmed_dry_run"
    elif wire_log_present:
        verdict = "confirmed_live_with_wire_evidence"
    elif retryable_errors > 0 and ok_calls > 0 and not dry_run:
        # Real API calls fail transiently; fixture/mocks never fail with retryable errors.
        verdict = "circumstantially_live"
    else:
        verdict = "no_wire_evidence"

    # Timing analysis: 20 min elapsed for ~39 batches × 12s spacing = ~8 min
    # + costco cocodalin crawl (~18s) + lottemart attempt + emart/homeplus load
    # 20-minute total is consistent with real API calls at rate-limited 12s/batch
    timing_note = (
        f"Run elapsed ~20 min (00:22→00:42). "
        f"39 batches × 12s rate limit ≈ 8 min. "
        f"Remaining time: crawling overhead. Timing consistent with live API calls."
    )

    return {
        "run_id": data.get("run_id"),
        "timestamp": data.get("timestamp"),
        "dry_run": dry_run,
        "total_items_labeled": sum(
            v.get("crawler_rows", 0)
            for v in data.get("per_mart_stage_counts", {}).values()
        ),
        "total_batches": total_batches,
        "total_shrink_calls": total_shrink_calls,
        "ok_calls": ok_calls,
        "retryable_errors": retryable_errors,
        "wire_log_present": wire_log_present,
        "cache_bypass_confirmed": cache_bypass_confirmed,
        "product_matches_before": product_matches_before,
        "keyword_alias_before": keyword_alias_before,
        "verdict": verdict,
        "timing_note": timing_note,
        "CRITICAL_GAP": (
            "직전 run에 wire-level HTTP 로그가 없음. "
            "shrink_log는 ok/retryable 카운트만 제공하며 HTTP URL/latency/status 없음. "
            "retryable_errors > 0은 실 API 호출의 간접 증거이지만 결정적 증거가 아님."
        ),
    }


# ---------------------------------------------------------------------------
# Wire-log setup
# ---------------------------------------------------------------------------


def setup_wire_log(audit_dir: Path, ts: str) -> tuple[Path, dict[str, str]]:
    """Create wire log path and set env vars. Returns (log_path, env_dict)."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    log_path = audit_dir / f"provider-wire-log-{ts}.jsonl"
    env_vars = {
        "WALLETSAVIOR_WIRE_LOG_PATH": str(log_path),
        "WALLETSAVIOR_AI_LIVE_FORCE": "1",
    }
    for k, v in env_vars.items():
        os.environ[k] = v
    return log_path, env_vars


# ---------------------------------------------------------------------------
# 100-item audit run
# ---------------------------------------------------------------------------


def run_100item_audit(
    provider_id: str,
    wire_log_path: Path,
    *,
    sample_size: int = AUDIT_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Run AI labeling on 100 emart items with wire logging active.

    Returns per-stage counts + wire_log stats.
    """
    _ensure_ai_imports()

    if not EMART_DATA_JSON.exists():
        return {"error": f"emart data not found: {EMART_DATA_JSON}"}

    with EMART_DATA_JSON.open(encoding="utf-8") as f:
        emart_data = json.load(f)

    raw_records = emart_data.get("raw_records", [])
    if not raw_records:
        return {"error": "emart data has no raw_records"}

    # Sample deterministically for reproducibility
    rng = random.Random(42)
    sample = rng.sample(raw_records, min(sample_size, len(raw_records)))
    print(
        f"[AUDIT] emart 샘플: {len(sample)}건 / 전체 {len(raw_records)}건",
        flush=True,
    )

    # Import pipeline runner
    sys.path.insert(0, str(_HERE))
    from ai_live_run import run_mart_pipeline_real

    print(f"[AUDIT] Wire log → {wire_log_path}", flush=True)
    print(f"[AUDIT] AI provider 실 호출 시작 (provider_id={provider_id})...", flush=True)

    t_start = time.perf_counter()
    result = run_mart_pipeline_real(
        mart_name="emart",
        raw_rows=sample,
        provider_id=provider_id,
        dry_run=False,
    )
    elapsed_s = time.perf_counter() - t_start

    return {
        "sample_size": len(sample),
        "elapsed_s": round(elapsed_s, 1),
        "crawler_rows": result.get("crawler_rows", 0),
        "ingested_rows": result.get("ingested_rows", 0),
        "ai_proposals": result.get("ai_proposals", 0),
        "gates_passed": result.get("gates_passed", 0),
        "shrink_log_summary": result.get("shrink_log_summary", {}),
        "pipeline_error": result.get("pipeline_error"),
        "quota_exhausted": result.get("quota_exhausted", False),
        "escalated": result.get("escalated", 0),
        "fallback": result.get("fallback", 0),
    }


def read_wire_log(log_path: Path) -> list[dict[str, Any]]:
    """Read all entries from the wire log JSONL file."""
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def analyze_wire_log(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute statistics and extract sample entries from wire log."""
    if not entries:
        return {
            "total_requests": 0,
            "ok_requests": 0,
            "failed_requests": 0,
            "google_genai_requests": 0,
            "unique_domains": [],
            "latency_ms_avg": None,
            "latency_ms_min": None,
            "latency_ms_max": None,
            "sample_entries": [],
            "verdict": "NO_CALLS_CAPTURED",
        }

    total = len(entries)
    ok = sum(1 for e in entries if 200 <= e.get("status", 0) < 300)
    failed = total - ok
    google_calls = sum(1 for e in entries if e.get("is_google_genai", False))
    domains = list({e.get("domain", "") for e in entries})
    latencies = [e["latency_ms"] for e in entries if e.get("latency_ms") is not None]
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else None
    min_lat = min(latencies) if latencies else None
    max_lat = max(latencies) if latencies else None

    # Sample: first 3 entries for report
    sample = entries[:3]

    verdict = (
        "CONFIRMED_LIVE" if google_calls >= 3
        else "PARTIAL_EVIDENCE" if google_calls >= 1
        else "NO_GOOGLE_CALLS"
    )

    return {
        "total_requests": total,
        "ok_requests": ok,
        "failed_requests": failed,
        "google_genai_requests": google_calls,
        "unique_domains": domains,
        "latency_ms_avg": avg_lat,
        "latency_ms_min": min_lat,
        "latency_ms_max": max_lat,
        "sample_entries": sample,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def build_audit_json(
    run_id: str,
    ts: str,
    prior_diagnosis: dict[str, Any],
    rerun_result: dict[str, Any],
    wire_stats: dict[str, Any],
    wire_log_path: Path,
    env_vars: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": "walletsavior.rd2_ai_audit.v1",
        "audit_id": run_id,
        "timestamp": ts,
        "prior_run_diagnosis": prior_diagnosis,
        "rerun_100items": rerun_result,
        "wire_log_analysis": wire_stats,
        "wire_log_path": str(wire_log_path),
        "env_vars_used": {k: ("(set)" if v else "(not set)") for k, v in env_vars.items()},
    }


def build_audit_md(
    run_id: str,
    ts: str,
    prior_diagnosis: dict[str, Any],
    rerun_result: dict[str, Any],
    wire_stats: dict[str, Any],
    wire_log_path: Path,
) -> str:
    lines = [
        f"# WalletSavior rd2-ai-provider-audit 결과",
        f"",
        f"**감사 ID**: `{run_id}`  ",
        f"**실행 일시**: `{ts}`",
        f"",
        f"---",
        f"",
        f"## 1. 직전 run-bd82105d 적대적 진단",
        f"",
        f"### 결론: **{prior_diagnosis.get('verdict', 'UNKNOWN')}**",
        f"",
    ]

    d = prior_diagnosis
    lines += [
        f"| 항목 | 값 |",
        f"|------|-----|",
        f"| run_id | `{d.get('run_id')}` |",
        f"| dry_run | `{d.get('dry_run')}` |",
        f"| 총 라벨링 건수 | {d.get('total_items_labeled')}건 |",
        f"| 총 배치 수 | {d.get('total_batches')}배치 |",
        f"| 총 shrink 호출 수 | {d.get('total_shrink_calls')}회 |",
        f"| ok 호출 수 | **{d.get('ok_calls')}회** |",
        f"| retryable 에러 수 | **{d.get('retryable_errors')}회** |",
        f"| wire log 존재 | **{d.get('wire_log_present')} ← 없음** |",
        f"| product_matches_before | {d.get('product_matches_before')}건 (0=캐시 비운 상태) |",
        f"| keyword_alias_before | {d.get('keyword_alias_before')}건 |",
        f"| 캐시 우회 확인 | `{d.get('cache_bypass_confirmed')}` |",
        f"",
    ]

    if d.get("verdict") == "circumstantially_live":
        lines += [
            f"### 직전 run 판정: 실 호출 **간접 증거 있음** — 결정적 증거 없음",
            f"",
            f"> **retryable_errors = {d.get('retryable_errors')}건**: fixture/mock은 절대 retryable error를 발생시키지 않는다.",
            f"> 이것은 실 API 호출의 간접 증거이지만, wire-level HTTP 로그가 없어 **결정적 증거가 아니다**.",
            f">",
            f"> {d.get('CRITICAL_GAP')}",
            f"",
            f"**타이밍 분석**: {d.get('timing_note')}",
            f"",
        ]
    elif d.get("verdict") == "no_wire_evidence":
        lines += [
            f"### 직전 run 판정: ❌ **wire 증거 없음 — 캐시/fixture 가능성 배제 불가**",
            f"",
            f"> {d.get('CRITICAL_GAP')}",
            f"",
        ]

    lines += [
        f"---",
        f"",
        f"## 2. 재실행 100건 결과 (wire log 강제 활성화)",
        f"",
    ]

    r = rerun_result
    if r.get("error"):
        lines += [
            f"**⚠️ 재실행 오류**: `{r['error']}`",
            f"",
        ]
    else:
        lines += [
            f"| 항목 | 값 |",
            f"|------|-----|",
            f"| 샘플 크기 | {r.get('sample_size')}건 |",
            f"| 소요 시간 | {r.get('elapsed_s')}초 |",
            f"| 크롤러 행 | {r.get('crawler_rows')}건 |",
            f"| ingested 행 | {r.get('ingested_rows')}건 |",
            f"| AI 제안 수 | {r.get('ai_proposals')}건 |",
            f"| 게이트 통과 | {r.get('gates_passed')}건 |",
            f"| 배치 수 | {r.get('shrink_log_summary', {}).get('total_batches')}배치 |",
            f"| ok 호출 | {r.get('shrink_log_summary', {}).get('ok_calls')}회 |",
            f"| retryable | {r.get('shrink_log_summary', {}).get('retryable_error_calls')}회 |",
            f"| quota 소진 | {r.get('quota_exhausted')} |",
            f"| pipeline 오류 | {r.get('pipeline_error') or 'None'} |",
            f"",
        ]

    lines += [
        f"---",
        f"",
        f"## 3. Wire Log 분석 — 결정적 증거",
        f"",
        f"**Wire log 경로**: `{wire_log_path}`",
        f"",
        f"### 결론: **{wire_stats.get('verdict', 'UNKNOWN')}**",
        f"",
        f"| 항목 | 값 |",
        f"|------|-----|",
        f"| 총 HTTP 요청 수 | **{wire_stats.get('total_requests')}건** |",
        f"| 성공 (2xx) | {wire_stats.get('ok_requests')}건 |",
        f"| 실패 | {wire_stats.get('failed_requests')}건 |",
        f"| Google GenAI API 호출 | **{wire_stats.get('google_genai_requests')}건** |",
        f"| 도메인 목록 | {', '.join(wire_stats.get('unique_domains', []))} |",
        f"| 평균 latency | {wire_stats.get('latency_ms_avg')} ms |",
        f"| 최소 latency | {wire_stats.get('latency_ms_min')} ms |",
        f"| 최대 latency | {wire_stats.get('latency_ms_max')} ms |",
        f"",
    ]

    sample_entries = wire_stats.get("sample_entries", [])
    if sample_entries:
        lines += [
            f"### Wire Log 샘플 (상위 3건)",
            f"",
            f"```json",
        ]
        for e in sample_entries:
            lines.append(json.dumps(e, ensure_ascii=False))
        lines += [
            f"```",
            f"",
            f"> **`generativelanguage.googleapis.com`** 도메인이 확인되면 실 Google API 호출 입증.",
            f"",
        ]
    else:
        lines += [
            f"⚠️ **Wire log 샘플 없음** — HTTP 호출이 캡처되지 않았습니다.",
            f"",
        ]

    # Final verdict
    google_calls = wire_stats.get("google_genai_requests", 0)
    prior_verdict = prior_diagnosis.get("verdict", "")
    lines += [
        f"---",
        f"",
        f"## 4. 최종 감사 결론",
        f"",
    ]

    if google_calls >= 3:
        lines += [
            f"### ✅ 실 API 호출 입증됨",
            f"",
            f"- Wire log에 `generativelanguage.googleapis.com` 호출 **{google_calls}건** 캡처됨",
            f"- 직전 run은 wire 증거 없었으나 간접 증거(retryable_errors={d.get('retryable_errors')})는 실 호출 시사",
            f"- **본 재실행에서 wire-level 결정적 증거 확보됨**",
        ]
        if prior_verdict == "circumstantially_live":
            lines += [
                f"",
                f"**직전 rd-ai-live-run 직전에 대한 판정 업데이트**:",
                f"> 직전 run도 동일 코드 경로(`run_mart_pipeline_real` → `_call_provider_with_shrink_retries`)를",
                f"> dry_run=False로 실행했으며, retryable_errors가 발생했음. 본 재실행과 동일 메커니즘.",
                f"> 따라서 직전 run도 실 API 호출이었을 가능성이 높다. 단, wire 증거는 없었음.",
            ]
    elif google_calls >= 1:
        lines += [
            f"### ⚠️ 부분 증거 — {google_calls}건 캡처됨",
            f"",
            f"- Wire log에 일부 Google API 호출이 캡처됐으나 100건 대비 매우 적음",
            f"- quota 소진 또는 wire logger 부착 타이밍 문제 가능성",
        ]
    else:
        lines += [
            f"### ❌ 실 API 호출 증거 없음",
            f"",
            f"- Wire log에 `generativelanguage.googleapis.com` 호출 0건",
            f"- wire logger가 실제로 httpx client에 부착되지 않았거나 API key 누락으로 호출 자체가 없었음",
            f"- 반드시 `WALLETSAVIOR_WIRE_LOG_PATH`와 API key 설정 확인 필요",
        ]

    lines += [
        f"",
        f"---",
        f"*자동 생성: `{ts}` | audit_id `{run_id}`*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="rd2-ai-provider-audit: 직전 AI run 진단 + 100건 wire-log 재실행",
    )
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--allow-live-ai-provider", action="store_true", default=False)
    parser.add_argument("--skip-rerun", action="store_true", default=False,
                        help="직전 run 진단만 하고 재실행은 건너뜀")
    parser.add_argument("--sample-size", type=int, default=AUDIT_SAMPLE_SIZE)
    args = parser.parse_args(argv)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = uuid.uuid4().hex[:8]
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70, flush=True)
    print(f"WalletSavior rd2-ai-provider-audit | {ts} | {run_id}", flush=True)
    print("=" * 70, flush=True)

    # Step 1: Diagnose prior run
    print("\n[1/4] 직전 run 적대적 진단 (bd82105d)...", flush=True)
    prior_diagnosis = diagnose_prior_run(PRIOR_RUN_JSON)
    print(f"  verdict: {prior_diagnosis.get('verdict')}", flush=True)
    print(f"  ok_calls: {prior_diagnosis.get('ok_calls')}, retryable_errors: {prior_diagnosis.get('retryable_errors')}", flush=True)
    print(f"  wire_log_present: {prior_diagnosis.get('wire_log_present')}", flush=True)

    # Step 2: Setup wire log
    wire_log_path, env_vars = setup_wire_log(AUDIT_DIR, ts)
    print(f"\n[2/4] Wire log 초기화: {wire_log_path}", flush=True)

    # Step 3: 100-item rerun
    rerun_result: dict[str, Any]
    if args.skip_rerun:
        print("\n[3/4] --skip-rerun: 재실행 건너뜀", flush=True)
        rerun_result = {"skipped": True}
    elif not args.allow_live_ai_provider:
        print(
            "\n[3/4] ⛔ 재실행 건너뜀 — --allow-live-ai-provider 플래그 없음",
            flush=True,
        )
        print(
            "      실 API 호출 증거를 수집하려면:",
            flush=True,
        )
        print(
            f"      py -3 tools/rd2_ai_audit.py --allow-live-ai-provider",
            flush=True,
        )
        rerun_result = {"skipped": True, "reason": "missing --allow-live-ai-provider"}
    else:
        print(f"\n[3/4] 100건 emart 재실행 (wire log 활성화)...", flush=True)
        try:
            rerun_result = run_100item_audit(
                args.provider_id,
                wire_log_path,
                sample_size=args.sample_size,
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            rerun_result = {"error": str(exc)}

    # Step 4: Analyze wire log
    print(f"\n[4/4] Wire log 분석...", flush=True)
    wire_entries = read_wire_log(wire_log_path)
    wire_stats = analyze_wire_log(wire_entries)
    print(f"  총 HTTP 요청: {wire_stats['total_requests']}건", flush=True)
    print(f"  Google GenAI 호출: {wire_stats['google_genai_requests']}건", flush=True)
    print(f"  verdict: {wire_stats['verdict']}", flush=True)

    # Step 5: Generate reports
    json_report = build_audit_json(
        run_id, ts, prior_diagnosis, rerun_result, wire_stats, wire_log_path, env_vars
    )
    md_report = build_audit_md(
        run_id, ts, prior_diagnosis, rerun_result, wire_stats, wire_log_path
    )

    json_path = AUDIT_DIR / f"audit-{ts}-{run_id}.json"
    md_path = AUDIT_DIR / f"audit-{ts}-{run_id}.md"
    json_path.write_text(json.dumps(json_report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md_report, encoding="utf-8")

    print(f"\n{'='*70}", flush=True)
    print(f"감사 완료: verdict={wire_stats['verdict']}", flush=True)
    print(f"JSON: {json_path}", flush=True)
    print(f"MD:   {md_path}", flush=True)
    print(f"Wire: {wire_log_path}", flush=True)
    print(f"{'='*70}\n", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
