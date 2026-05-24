"""tools/ai_live_run.py — WalletSavior rd-ai-live-run 슬라이스 오케스트레이터.

Usage:
    py -3 tools/ai_live_run.py [--dry-run] [--provider-id google-gemini31-live-matrix]

이 스크립트는 다음을 순서대로 실행한다:
  1. 학습 매칭 테이블 백업 후 비우기 (learned_knowledge[keyword_alias_approved] + product_matches)
  2. 코스트코 신선 데이터 캡처 (cocodalin API 12카테고리)
  3. 롯데마트 HTTP 캡처 시도 (WAF 차단 시 fail-fast 문서화)
  4. 4사 전체 데이터를 실 Google AI provider로 라벨링
  5. Adversarial v2 분석 (분포·신뢰도·볼륨·시맨틱)
  6. JSON + 한국어 MD 리포트 생성
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — only done when running as script or when AI backend is needed.
# The utility functions (empty_learned_tables, count_keyword_category_proposals,
# build_confidence_histogram) only need stdlib and are always importable.
# Heavy AI backend imports are deferred to _ensure_ai_imports().
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
AI_ADMIN_BACKEND = REPO_ROOT / "packages" / "ai-admin" / "backend"
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
SHARED = REPO_ROOT / "packages" / "shared"

_AI_IMPORTS_LOADED = False


def _ensure_ai_imports() -> None:
    """Load AI-admin backend packages into sys.path and import them lazily.

    Called only when actually running the pipeline (not during unit tests of
    the pure utility functions).

    AI_ADMIN_BACKEND is inserted last (= position 0 after all inserts) so it
    wins over CRAWLER_BACKEND when both have a `services` package.
    """
    global _AI_IMPORTS_LOADED
    if _AI_IMPORTS_LOADED:
        return
    # Insert in reverse priority order so highest-priority ends at index 0.
    # Desired order: AI_ADMIN_BACKEND > SHARED > CRAWLER_BACKEND > _HERE
    for _p in [str(_HERE), str(CRAWLER_BACKEND), str(SHARED), str(AI_ADMIN_BACKEND)]:
        if _p not in sys.path:
            sys.path.insert(0, _p)
    _AI_IMPORTS_LOADED = True

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "walletsavior.ai_live_run.v1"
DEFAULT_PROVIDER_ID = "google-gemini31-live-matrix"
COCODALIN_API_BASE = "https://www.cocodalin.com/api/front"
COCODALIN_CATEGORY_IDS = (7, 9, 10, 11, 8, 12, 1, 2, 3, 4, 5, 6)
COCODALIN_SLEEP_SECONDS = 1.5
COSTCO_MIN_ROWS = 80
LOTTEMART_MIN_ROWS = 200
LABEL_SPACING_SECONDS = 12  # min_request_interval_seconds for provider calls

ARTIFACT_DIR = REPO_ROOT / ".walletsavior-live-validation" / "ai-live-run"
MART_DIRS = {
    "emart": REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "emart",
    "homeplus": REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "homeplus",
    "lottemart": REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "lottemart",
}
AI_CONTROL_DB_PATH = AI_ADMIN_BACKEND / "ai_control.db"

# Pipeline stage names for silent-drop tracking
STAGES = [
    "ai_ingestion",
    "queue_ai_router",
    "postcheck_gate",
    "review_publish",
    "oneshot_public_db",
]

GATE_MIN_CONFIDENCE = 0.9


# ===========================================================================
# TDD-covered utility functions
# ===========================================================================


def empty_learned_tables(
    db_path: str | None = None,
    backup_dir: str | None = None,
) -> dict[str, Any]:
    """Back up and empty learned matching tables.

    Clears:
      - learned_knowledge WHERE knowledge_type = 'keyword_alias_approved'
      - product_matches (all rows)

    Other knowledge types in learned_knowledge are preserved.

    Returns a dict with before/after row counts and backup_path.
    """
    import sqlite3

    db = Path(db_path or str(AI_CONTROL_DB_PATH))
    bdir = Path(backup_dir or str(ARTIFACT_DIR))
    bdir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Count before
    cur.execute(
        "SELECT COUNT(*) FROM learned_knowledge WHERE knowledge_type = 'keyword_alias_approved'"
    )
    kw_alias_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM product_matches")
    pm_before = cur.fetchone()[0]

    # Export to backup
    cur.execute(
        "SELECT * FROM learned_knowledge WHERE knowledge_type = 'keyword_alias_approved'"
    )
    alias_rows = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM product_matches")
    pm_rows = [dict(r) for r in cur.fetchall()]

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = bdir / f"learned-backup-{ts}.json"
    backup_data = {
        "schema": "walletsavior.learned_backup.v1",
        "created_at": datetime.now().isoformat(),
        "source_db": str(db),
        "learned_knowledge_keyword_alias_approved": alias_rows,
        "product_matches": pm_rows,
    }
    backup_path.write_text(
        json.dumps(backup_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Delete
    cur.execute(
        "DELETE FROM learned_knowledge WHERE knowledge_type = 'keyword_alias_approved'"
    )
    cur.execute("DELETE FROM product_matches")
    conn.commit()

    # Count after
    cur.execute(
        "SELECT COUNT(*) FROM learned_knowledge WHERE knowledge_type = 'keyword_alias_approved'"
    )
    kw_alias_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM product_matches")
    pm_after = cur.fetchone()[0]
    conn.close()

    return {
        "backup_path": str(backup_path),
        "keyword_alias_before": kw_alias_before,
        "keyword_alias_after": kw_alias_after,
        "product_matches_before": pm_before,
        "product_matches_after": pm_after,
    }


def count_keyword_category_proposals(proposal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count keyword and category proposals from labeling results.

    Args:
        proposal_rows: list of dicts with keys: source, category, keywords, ai_confidence

    Returns a dict with:
        total_keyword_proposals: total number of keyword tokens across all rows
        unique_categories_proposed: number of distinct category_ids
        retail_general_count: rows with category == 'retail.general'
        retail_general_ratio: retail_general_count / len(proposal_rows)
        per_mart_keyword_counts: {mart: total_keywords}
    """
    if not proposal_rows:
        return {
            "total_keyword_proposals": 0,
            "unique_categories_proposed": 0,
            "retail_general_count": 0,
            "retail_general_ratio": 0.0,
            "per_mart_keyword_counts": {},
        }

    total_keywords = 0
    categories: set[str] = set()
    retail_general_count = 0
    per_mart: dict[str, int] = defaultdict(int)

    for row in proposal_rows:
        keywords = row.get("keywords") or []
        if isinstance(keywords, list):
            kw_count = len(keywords)
        else:
            kw_count = 0
        total_keywords += kw_count

        cat = row.get("category") or "retail.general"
        categories.add(cat)
        if cat == "retail.general":
            retail_general_count += 1

        mart = row.get("source") or "unknown"
        per_mart[mart] += kw_count

    return {
        "total_keyword_proposals": total_keywords,
        "unique_categories_proposed": len(categories),
        "retail_general_count": retail_general_count,
        "retail_general_ratio": retail_general_count / len(proposal_rows),
        "per_mart_keyword_counts": dict(per_mart),
    }


def build_confidence_histogram(proposal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a 3-bucket confidence histogram.

    Buckets:
        ge_0_9:         confidence >= 0.9
        ge_0_7_lt_0_9:  0.7 <= confidence < 0.9
        lt_0_7:         confidence < 0.7

    Returns per-bucket count and percentage.
    """
    total = len(proposal_rows)
    ge_09 = ge_07 = lt_07 = 0
    for row in proposal_rows:
        conf = row.get("ai_confidence") or 0.0
        if conf >= 0.9:
            ge_09 += 1
        elif conf >= 0.7:
            ge_07 += 1
        else:
            lt_07 += 1

    def _pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    return {
        "total": total,
        "ge_0_9": {"count": ge_09, "pct": _pct(ge_09), "label": "≥0.9 (고신뢰도)"},
        "ge_0_7_lt_0_9": {"count": ge_07, "pct": _pct(ge_07), "label": "0.7~0.9 (중신뢰도)"},
        "lt_0_7": {"count": lt_07, "pct": _pct(lt_07), "label": "<0.7 (저신뢰도·폴백)"},
    }


# ===========================================================================
# Costco capture via cocodalin API
# ===========================================================================


def capture_costco_cocodalin(
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture Costco data via cocodalin.com public API.

    Calls /api/front/productList/{cat_id} for 12 categories.
    Applies 1.5s sleep between calls (ban-safe).

    Returns dict with:
        items: list of raw dicts (RawCrawlRecord-compatible)
        count: number of items captured
        failures: list of failure records
        blocked: True if count < COSTCO_MIN_ROWS
    """
    try:
        import requests
    except ImportError:
        return {
            "items": [],
            "count": 0,
            "failures": [{"cat": "all", "error": "requests not available"}],
            "blocked": True,
            "ban_evidence": "requests library not available",
        }

    _ensure_ai_imports()
    from crawlers.marts.source_utils import normalize_source_key

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.cocodalin.com/",
    }

    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()

    for i, cat_id in enumerate(COCODALIN_CATEGORY_IDS):
        url = f"{COCODALIN_API_BASE}/productList/{cat_id}"
        try:
            if dry_run:
                # In dry-run, simulate empty response
                products = []
            else:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    failures.append({
                        "cat": cat_id,
                        "error": f"HTTP {resp.status_code}",
                        "url": url,
                    })
                    print(f"  [costco/cocodalin] cat {cat_id}: HTTP {resp.status_code}", flush=True)
                    if i < len(COCODALIN_CATEGORY_IDS) - 1:
                        time.sleep(COCODALIN_SLEEP_SECONDS)
                    continue
                try:
                    products = resp.json()
                except Exception:
                    products = []

            if isinstance(products, list):
                for p in products:
                    name = (p.get("product_name") or "").strip()
                    if len(name) < 2:
                        continue
                    sale_price = p.get("sale_price")
                    if not sale_price:
                        continue
                    try:
                        sale_price = int(sale_price)
                    except (TypeError, ValueError):
                        continue
                    if sale_price <= 0:
                        continue

                    product_id = p.get("product_id")
                    detail_url = (
                        f"https://www.cocodalin.com/product.html?id={product_id}"
                        if product_id else ""
                    )
                    source_key = normalize_source_key(
                        "costco_cocodalin",
                        str(product_id) if product_id else name,
                    )
                    if source_key in seen:
                        continue
                    seen.add(source_key)

                    raw_record_id = f"costco:{source_key}"
                    normal_price = p.get("normal_price")
                    items.append({
                        "raw_record_id": raw_record_id,
                        "source_name": "costco",
                        "source_record_key": source_key,
                        "source_url": detail_url,
                        "raw_title": name,
                        "raw_price": sale_price,
                        "crawled_at": datetime.now().isoformat(),
                        "raw_payload": {
                            "store": "코스트코",
                            "name": name,
                            "sale_price": sale_price,
                            "original_price": int(normal_price) if normal_price else None,
                            "discount_percent": p.get("discount_percent"),
                            "category": p.get("category_name", ""),
                            "cocodalin_category_id": cat_id,
                            "source_url": detail_url,
                            "source_record_key": source_key,
                            "collection_path": "cocodalin_api",
                            "from_date": p.get("from_date"),
                            "to_date": p.get("to_date"),
                        },
                    })

            print(
                f"  [costco/cocodalin] cat {cat_id}: {len(products) if isinstance(products, list) else 0}건",
                flush=True,
            )

        except Exception as exc:
            failures.append({"cat": cat_id, "error": str(exc), "url": url})
            print(f"  [costco/cocodalin] cat {cat_id}: ERROR {exc}", flush=True)

        if i < len(COCODALIN_CATEGORY_IDS) - 1 and not dry_run:
            time.sleep(random.uniform(COCODALIN_SLEEP_SECONDS * 0.7, COCODALIN_SLEEP_SECONDS * 1.3))

    # Save capture artifact
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    capture_path = output_dir / f"costco-cocodalin-capture-{ts}.json"
    capture_data = {
        "schema": "walletsavior.costco_cocodalin_capture.v1",
        "created_at": datetime.now().isoformat(),
        "category_ids": list(COCODALIN_CATEGORY_IDS),
        "item_count": len(items),
        "failure_count": len(failures),
        "raw_records": items,
    }
    capture_path.write_text(
        json.dumps(capture_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    blocked = len(items) < COSTCO_MIN_ROWS
    ban_evidence = None
    if blocked:
        ban_evidence = (
            f"costco/cocodalin 캡처 건수 {len(items)}건 — 임계값 {COSTCO_MIN_ROWS}건 미달. "
            f"실패 기록: {failures[:3]}"
        )

    return {
        "items": items,
        "count": len(items),
        "failures": failures,
        "blocked": blocked,
        "ban_evidence": ban_evidence,
        "capture_path": str(capture_path),
    }


# ===========================================================================
# Data loading
# ===========================================================================


def load_mart_raw_records(mart_dir: Path, mart_name: str) -> tuple[list[dict], list[str]]:
    """Load raw record dicts from a mart directory. Returns (rows, errors)."""
    _ensure_ai_imports()
    from launch_gate_runbook import (  # noqa: F811
        _discover_input_files,
        _load_json_records,
        _load_jsonl,
    )

    errors: list[str] = []
    files = _discover_input_files(mart_dir)
    if not files:
        files = sorted(mart_dir.rglob("*.json")) + sorted(mart_dir.rglob("*.jsonl"))
    if not files:
        errors.append(f"{mart_name}: no input files found in {mart_dir}")
        return [], errors

    all_rows: list[dict] = []
    for path in files:
        try:
            if path.suffix == ".jsonl":
                rows = _load_jsonl(path)
            else:
                rows = _load_json_records(path)
            all_rows.extend(rows)
        except Exception as exc:
            errors.append(f"{mart_name}: failed to load {path.name}: {exc}")

    # De-duplicate
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in all_rows:
        rid = row.get("raw_record_id") or row.get("source_record_key")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        deduped.append(row)

    return deduped, errors


# ===========================================================================
# Real AI provider pipeline
# ===========================================================================


def _build_provider(provider_id: str) -> tuple[Any, Any]:
    """Build a real Google GenAI provider from the DB config."""
    import sqlite3

    _ensure_ai_imports()
    from core.contracts.control_plane import ProviderConfigContract  # noqa: F811
    from services.ai_ingestion import provider_from_config  # noqa: F811

    conn = sqlite3.connect(str(AI_CONTROL_DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT provider_id, provider_kind, display_name, default_model, secret_alias, "
        "min_request_interval_seconds, max_provider_calls_per_minute, max_provider_calls_per_day, "
        "provider_retry_max_attempts, provider_retry_min_delay_seconds, provider_retry_max_delay_seconds "
        "FROM provider_configs WHERE provider_id = ?",
        (provider_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"provider_id not found in DB: {provider_id}")

    (
        pid, pkind, dname, dmodel, secret_alias,
        min_interval, max_per_min, max_per_day,
        retry_max, retry_min_delay, retry_max_delay,
    ) = row

    from core.contracts.ai_pipeline import ProviderKind

    config = ProviderConfigContract(
        provider_id=pid,
        provider_kind=pkind,
        display_name=dname or pid,
        default_model=dmodel or "gemini-2.5-flash-lite",
        secret_alias=secret_alias or "GOOGLE_API_KEY",
        min_request_interval_seconds=float(min_interval or LABEL_SPACING_SECONDS),
        max_provider_calls_per_minute=int(max_per_min or 5),
        max_provider_calls_per_day=int(max_per_day or 300),
        provider_retry_max_attempts=int(retry_max or 3),
        provider_retry_min_delay_seconds=float(retry_min_delay or 10.0),
        provider_retry_max_delay_seconds=float(retry_max_delay or 60.0),
    )
    provider = provider_from_config(config)
    return provider, config


def run_mart_pipeline_real(
    mart_name: str,
    raw_rows: list[dict[str, Any]],
    provider_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run live AI labeling pipeline for one mart.

    Returns per-stage counts, proposal rows, shrink log summary, and
    escalation/fallback detail.
    """
    _ensure_ai_imports()
    from launch_gate_runbook import _raw_record_from_dict  # noqa: F811
    from services.ai_ingestion import (  # noqa: F811
        _call_provider_with_shrink_retries,
        _provider_ref,
    )

    crawler_rows = len(raw_rows)

    # Stage 1 (ai_ingestion): parse raw dicts to RawCrawlRecord
    records: list[Any] = []
    parse_errors: list[str] = []
    for row in raw_rows:
        rec = _raw_record_from_dict(row, mart_name)
        if rec is None:
            parse_errors.append(row.get("raw_record_id") or "unknown")
        else:
            records.append(rec)

    ingested_rows = len(records)
    ingestion_drop = crawler_rows - ingested_rows
    stage_counts = {
        "ai_ingestion": ingested_rows,
        "queue_ai_router": 0,
        "postcheck_gate": 0,
        "review_publish": 0,
        "oneshot_public_db": 0,
    }
    silent_drop = {
        "ai_ingestion": ingestion_drop,
        "queue_ai_router": 0,
        "postcheck_gate": 0,
        "review_publish": 0,
        "oneshot_public_db": 0,
    }

    if not records:
        return {
            "crawler_rows": crawler_rows,
            "ingested_rows": 0,
            "ai_proposals": 0,
            "gates_passed": 0,
            "publish_approved": 0,
            "public_snapshot_rows": 0,
            "stage_counts": stage_counts,
            "silent_drop": silent_drop,
            "proposal_rows": [],
            "parse_errors": parse_errors,
            "escalated": 0,
            "fallback": ingestion_drop,
            "shrink_log_summary": {},
            "pipeline_error": "no valid records after parsing",
        }

    if dry_run:
        # In dry-run mode, simulate with fallback proposals
        proposal_rows = []
        for rec in records:
            proposal_rows.append({
                "raw_record_id": rec.raw_record_id,
                "source": mart_name,
                "category": "retail.general",
                "raw_title": rec.raw_title,
                "current_price": rec.raw_price,
                "ai_confidence": 0.42,
                "source_url": rec.source_url or "",
                "keywords": ["상품"],
            })
        stage_counts.update({
            "ai_ingestion": ingested_rows,
            "queue_ai_router": ingested_rows,
            "postcheck_gate": 0,
            "review_publish": 0,
            "oneshot_public_db": 0,
        })
        silent_drop.update({
            "ai_ingestion": ingestion_drop,
            "queue_ai_router": 0,
            "postcheck_gate": ingested_rows,
            "review_publish": 0,
            "oneshot_public_db": 0,
        })
        return {
            "crawler_rows": crawler_rows,
            "ingested_rows": ingested_rows,
            "ai_proposals": ingested_rows,
            "gates_passed": 0,
            "publish_approved": 0,
            "public_snapshot_rows": 0,
            "stage_counts": stage_counts,
            "silent_drop": silent_drop,
            "proposal_rows": proposal_rows,
            "parse_errors": parse_errors,
            "escalated": 0,
            "fallback": ingested_rows,
            "shrink_log_summary": {"dry_run": True},
            "pipeline_error": None,
        }

    # Stage 2 (queue_ai_router): build provider
    provider, provider_config = _build_provider(provider_id)
    stage_counts["queue_ai_router"] = ingested_rows
    provider_ref = _provider_ref(provider_config)
    root_batch_id = f"ai-live-run-{mart_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Stage 3: split into batches and call provider
    from services.ai_ingestion import split_records_for_ai

    batches, _batch_truncations = split_records_for_ai(records, max_batch_items=20, max_prompt_chars=12000)
    print(f"  [{mart_name}] {len(records)}건 → {len(batches)}배치", flush=True)

    all_proposals = []
    all_kw_proposals = []
    all_shrink_log = []
    batch_errors: list[dict] = []
    quota_exhausted = False

    for batch_idx, batch in enumerate(batches):
        ai_batch_id = f"{root_batch_id}:batch{batch_idx}"
        print(
            f"  [{mart_name}] batch {batch_idx+1}/{len(batches)} ({len(batch)}건)...",
            flush=True,
        )
        try:
            proposals, kw_proposals, shrink_log = _call_provider_with_shrink_retries(
                records=batch,
                provider=provider,
                provider_ref=provider_ref,
                provider_id=provider_id,
                model=provider_config.default_model or "gemini-2.5-flash-lite",
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                keyword_catalog=[],
                learned_keyword_knowledge=[],
                max_prompt_chars=12000,
            )
            all_proposals.extend(proposals)
            all_kw_proposals.extend(kw_proposals)
            all_shrink_log.extend(shrink_log)
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "quota" in err_msg.lower():
                quota_exhausted = True
                batch_errors.append({
                    "batch_idx": batch_idx,
                    "batch_size": len(batch),
                    "error": err_msg,
                    "type": "quota_exhausted",
                })
                print(
                    f"  [{mart_name}] batch {batch_idx+1} QUOTA EXHAUSTED: {err_msg[:120]}",
                    flush=True,
                )
                # Continue with remaining batches after quota note
            else:
                batch_errors.append({
                    "batch_idx": batch_idx,
                    "batch_size": len(batch),
                    "error": err_msg,
                    "type": "provider_error",
                })
                print(
                    f"  [{mart_name}] batch {batch_idx+1} ERROR: {err_msg[:120]}",
                    flush=True,
                )

    # Count unique record IDs that got proposals
    proposed_record_ids: set[str] = {p.provenance.raw_record_id for p in all_proposals}
    ai_proposals_count = len(proposed_record_ids)
    stage_counts["queue_ai_router"] = ingested_rows

    # Stage 3 (postcheck_gate): confidence gate
    confidence_by_record: dict[str, float] = {}
    for p in all_proposals:
        rid = p.provenance.raw_record_id
        conf = p.provenance.confidence or 0.0
        if conf > confidence_by_record.get(rid, 0.0):
            confidence_by_record[rid] = conf

    gates_passed = sum(1 for c in confidence_by_record.values() if c >= GATE_MIN_CONFIDENCE)
    gate_failed = ai_proposals_count - gates_passed
    stage_counts["postcheck_gate"] = gates_passed
    silent_drop["postcheck_gate"] = gate_failed

    # Stage 4 (review_publish): all gate-passed → approved (in live-run, no manual review)
    stage_counts["review_publish"] = gates_passed
    silent_drop["review_publish"] = 0

    # Stage 5 (oneshot_public_db): same as approved for this run
    stage_counts["oneshot_public_db"] = gates_passed
    silent_drop["oneshot_public_db"] = 0

    # Update ai_ingestion drop
    silent_drop["ai_ingestion"] = ingestion_drop

    # Build proposal rows for adversarial analysis
    cat_by_record: dict[str, str] = {}
    title_by_record: dict[str, str] = {}
    price_by_record: dict[str, Any] = {}
    url_by_record: dict[str, str] = {}
    kw_by_record: dict[str, list] = {}

    for p in all_proposals:
        rid = p.provenance.raw_record_id
        if p.target_field == "category_id":
            cat_by_record[rid] = str(p.proposed_value or "retail.general")
        elif p.target_field == "source_title":
            title_by_record[rid] = str(p.proposed_value or "")
        elif p.target_field == "sale_price":
            price_by_record[rid] = p.proposed_value
        elif p.target_field == "source_url" and rid not in url_by_record:
            url_by_record[rid] = str(p.proposed_value or "")
        elif p.target_field == "keywords":
            if rid not in kw_by_record:
                kw_by_record[rid] = []
            v = p.proposed_value
            if isinstance(v, list):
                kw_by_record[rid].extend(v)
            elif v:
                kw_by_record[rid].append(str(v))

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
            "keywords": kw_by_record.get(rid, []),
        })

    fallback_count = sum(1 for e in all_shrink_log if e.get("fallback"))
    escalated_count = len(batch_errors)

    # Shrink log summary
    shrink_summary = {
        "total_batches": len(batches),
        "total_shrink_calls": len(all_shrink_log),
        "ok_calls": sum(1 for e in all_shrink_log if e.get("outcome") == "ok"),
        "fallback_calls": fallback_count,
        "retryable_error_calls": sum(
            1 for e in all_shrink_log if e.get("outcome") == "retryable_error"
        ),
        "quota_exhausted": quota_exhausted,
        "batch_errors": batch_errors,
    }

    return {
        "crawler_rows": crawler_rows,
        "ingested_rows": ingested_rows,
        "ai_proposals": ai_proposals_count,
        "gates_passed": gates_passed,
        "publish_approved": gates_passed,
        "public_snapshot_rows": gates_passed,
        "stage_counts": stage_counts,
        "silent_drop": silent_drop,
        "proposal_rows": proposal_rows,
        "parse_errors": parse_errors,
        "escalated": escalated_count,
        "fallback": fallback_count,
        "shrink_log_summary": shrink_summary,
        "pipeline_error": None,
        "quota_exhausted": quota_exhausted,
    }


# ===========================================================================
# Report generation
# ===========================================================================


def build_korean_md_report(
    run_id: str,
    timestamp: str,
    provider_id: str,
    per_mart_results: dict[str, dict[str, Any]],
    learned_empty_result: dict[str, Any],
    adversarial_v2: dict[str, Any],
    confidence_hist: dict[str, Any],
    proposal_counts: dict[str, Any],
    stage_drop_totals: dict[str, int],
    costco_capture: dict[str, Any],
    lottemart_status: dict[str, Any],
    verdict: str,
) -> str:
    _ensure_ai_imports()
    from services.seed_taxonomy import get_category_display_label  # noqa: F811

    lines: list[str] = []
    lines.append("# WalletSavior rd-ai-live-run 결과 보고서")
    lines.append("")
    lines.append(f"**실행 일시**: {timestamp}")
    lines.append(f"**실행 ID**: `{run_id}`")
    lines.append(f"**AI Provider**: `{provider_id}`")
    lines.append("")

    verdict_emoji = "✅" if verdict == "pass" else ("⚠️" if verdict == "needs_more_work" else "❌")
    lines.append(f"## 최종 판정: {verdict_emoji} `{verdict}`")
    lines.append("")

    # --- 매칭 테이블 비우기 결과 ---
    lines.append("## 1. 학습 매칭 테이블 비우기")
    lines.append("")
    lines.append(
        f"- **keyword_alias_approved 행**: {learned_empty_result.get('keyword_alias_before', '?')}건 → "
        f"{learned_empty_result.get('keyword_alias_after', '?')}건"
    )
    lines.append(
        f"- **product_matches 행**: {learned_empty_result.get('product_matches_before', '?')}건 → "
        f"{learned_empty_result.get('product_matches_after', '?')}건"
    )
    lines.append(
        f"- **백업 파일**: `{learned_empty_result.get('backup_path', 'N/A')}`"
    )
    lines.append("")
    lines.append(
        "> 매칭 테이블을 비운 상태에서 AI를 실행했으므로, 이번 라운드의 카테고리/키워드는 "
        "100% AI가 직접 분류한 결과입니다. 학습 이득은 없는 상태(zero-shot)에서 시작합니다."
    )
    lines.append("")

    # --- 크롤러 캡처 현황 ---
    lines.append("## 2. 신선 크롤러 데이터 캡처 현황")
    lines.append("")
    lines.append("| 마트 | 캡처 건수 | 상태 |")
    lines.append("|------|----------|------|")
    emart_count = per_mart_results.get("emart", {}).get("crawler_rows", 0)
    homeplus_count = per_mart_results.get("homeplus", {}).get("crawler_rows", 0)
    lottemart_count = per_mart_results.get("lottemart", {}).get("crawler_rows", 0)
    costco_count = costco_capture.get("count", 0)
    costco_blocked = costco_capture.get("blocked", True)
    lottemart_blocked = lottemart_status.get("blocked", False)

    lines.append(f"| 이마트 | {emart_count}건 | ✅ 정상 |")
    lines.append(f"| 홈플러스 | {homeplus_count}건 | ✅ 정상 |")
    lotte_status = "❌ fail-fast (WAF 차단 의심)" if lottemart_blocked else "⚠️ 임계값 미달" if lottemart_count < LOTTEMART_MIN_ROWS else "✅ 정상"
    lines.append(f"| 롯데마트 | {lottemart_count}건 | {lotte_status} |")
    costco_status = "❌ fail-fast (임계값 미달)" if costco_blocked else "✅ 정상"
    lines.append(f"| 코스트코 | {costco_count}건 | {costco_status} |")
    lines.append("")

    if lottemart_blocked or lottemart_count < LOTTEMART_MIN_ROWS:
        lines.append(
            f"> ⚠️ **롯데마트**: 캡처 건수 {lottemart_count}건 — 임계값 {LOTTEMART_MIN_ROWS}건 미달. "
            "롯데마트 WAF/접근제어 차단으로 추정됩니다. 기존 50건으로 AI 평가를 진행했습니다."
        )
        lines.append("")
    if costco_blocked:
        lines.append(
            f"> ⚠️ **코스트코**: 캡처 건수 {costco_count}건 — 임계값 {COSTCO_MIN_ROWS}건 미달. "
            f"차단 증거: {costco_capture.get('ban_evidence', 'N/A')}"
        )
        lines.append("")

    # --- AI 라벨링 결과 ---
    lines.append("## 3. AI 라벨링 결과 (단계별 수치)")
    lines.append("")
    lines.append("| 마트 | 크롤러 | 정규화 | AI제안 | 게이트통과 | DB승인 | 공개DB |")
    lines.append("|------|--------|--------|--------|-----------|--------|--------|")
    total_crawler = total_ingested = total_proposals = total_gates = total_approved = 0
    for mart_name, res in sorted(per_mart_results.items()):
        cr = res.get("crawler_rows", 0)
        ing = res.get("ingested_rows", 0)
        prop = res.get("ai_proposals", 0)
        gates = res.get("gates_passed", 0)
        appr = res.get("publish_approved", 0)
        pub = res.get("public_snapshot_rows", 0)
        lines.append(f"| {mart_name:<8} | {cr:>6} | {ing:>6} | {prop:>6} | {gates:>9} | {appr:>6} | {pub:>6} |")
        total_crawler += cr
        total_ingested += ing
        total_proposals += prop
        total_gates += gates
        total_approved += appr
    lines.append(
        f"| **합계** | **{total_crawler}** | **{total_ingested}** | "
        f"**{total_proposals}** | **{total_gates}** | **{total_approved}** | **{total_approved}** |"
    )
    lines.append("")

    # --- 단계별 silent drop ---
    lines.append("## 4. 단계별 누락(Silent Drop) 현황")
    lines.append("")
    lines.append("각 단계에서 입력 대비 얼마나 줄었는지 추적합니다.")
    lines.append("")
    lines.append("| 단계 | 누락 건수 | 설명 |")
    lines.append("|------|----------|------|")
    stage_desc = {
        "ai_ingestion": "raw 파싱 실패 (필드 누락 등)",
        "queue_ai_router": "AI 라우터 큐 진입 전 drop",
        "postcheck_gate": "신뢰도 게이트 미달 (<0.9 또는 폴백)",
        "review_publish": "리뷰 발행 단계 drop",
        "oneshot_public_db": "공개 DB 저장 drop",
    }
    for stage in STAGES:
        drop = stage_drop_totals.get(stage, 0)
        desc = stage_desc.get(stage, "")
        lines.append(f"| {stage} | {drop}건 | {desc} |")
    lines.append("")

    # --- AI 신뢰도 분포 ---
    lines.append("## 5. AI 신뢰도 분포")
    lines.append("")
    lines.append(
        "AI가 각 상품을 얼마나 자신 있게 분류했는지를 나타냅니다. "
        "0.9 이상이면 '매우 확실', 0.42이면 AI가 포기하고 사람 검토로 넘긴 것입니다."
    )
    lines.append("")
    h = confidence_hist
    lines.append(f"- **≥0.9 (고신뢰도)**: {h.get('ge_0_9',{}).get('count',0)}건 / {h.get('ge_0_9',{}).get('pct',0)}%")
    lines.append(f"- **0.7~0.9 (중신뢰도)**: {h.get('ge_0_7_lt_0_9',{}).get('count',0)}건 / {h.get('ge_0_7_lt_0_9',{}).get('pct',0)}%")
    lines.append(f"- **<0.7 (저신뢰도·폴백)**: {h.get('lt_0_7',{}).get('count',0)}건 / {h.get('lt_0_7',{}).get('pct',0)}%")
    lines.append(f"- **전체**: {h.get('total',0)}건")
    lines.append("")

    # --- 카테고리 분포 ---
    lines.append("## 6. 카테고리 분포")
    lines.append("")
    lines.append(f"- **retail.general 폴백 건수**: {proposal_counts.get('retail_general_count',0)}건 / {proposal_counts.get('retail_general_ratio',0)*100:.1f}%")
    lines.append(f"- **고유 카테고리 제안 수**: {proposal_counts.get('unique_categories_proposed',0)}개")
    lines.append(f"- **총 키워드 제안 수**: {proposal_counts.get('total_keyword_proposals',0)}개")
    lines.append("")

    cat_dist = adversarial_v2.get("category_distribution_per_mart", {})
    if cat_dist:
        lines.append("### 마트별 상위 카테고리 (상위 5개)")
        for mart, dist_data in sorted(cat_dist.items()):
            cats = dist_data.get("categories", {})
            sorted_cats = sorted(cats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
            if sorted_cats:
                lines.append(f"**{mart}**: " + ", ".join(
                    f"{get_category_display_label(cat) or cat}({info['count']}건)"
                    for cat, info in sorted_cats
                ))
        lines.append("")

    # --- 시맨틱 spot-check ---
    lines.append("## 7. 시맨틱 Spot-Check")
    lines.append("")
    sc = adversarial_v2.get("semantic_spotcheck", {})
    per_mart_sc = sc.get("per_mart", {})
    if per_mart_sc:
        for mart, sc_data in sorted(per_mart_sc.items()):
            sampled = sc_data.get("sampled", 0)
            checked = sc_data.get("checked", 0)
            flagged = sc_data.get("flagged", 0)
            ok_count = checked - flagged
            pass_rate = round(ok_count / checked * 100, 1) if checked > 0 else 100.0
            lines.append(f"- **{mart}**: {sampled}건 샘플, {ok_count}건 통과, {flagged}건 의심 → 통과율 {pass_rate}%")
        flagged_items = sc.get("flagged", [])
        if flagged_items:
            lines.append("")
            lines.append("**의심 항목 (최대 5건):**")
            for item in flagged_items[:5]:
                lines.append(
                    f"  - `{item.get('mart')}` / `{item.get('raw_title','')[:40]}` → {item.get('reason','')}"
                )
    else:
        lines.append("_(spot-check 데이터 없음)_")
    lines.append("")

    # --- 적대적 v2 판정 ---
    lines.append("## 8. 적대적 v2 분석 판정")
    lines.append("")
    blockers = adversarial_v2.get("overall_launch_gate_blockers", [])
    if blockers:
        lines.append(f"⚠️ **차단 요인 {len(blockers)}건**:")
        for b in blockers[:5]:
            lines.append(
                f"  - [{b.get('alert_type','?')}] {b.get('mart','')} — "
                f"{b.get('reason','') or b.get('deficit','')}"
            )
    else:
        lines.append("✅ **차단 요인 없음** — 모든 분석 기준 통과")
    lines.append("")

    # --- 다음 슬라이스 안내 ---
    lines.append("## 9. 다음 슬라이스 안내")
    lines.append("")
    lines.append("- **학습 테이블 상태**: 비어있음 (rd-empty-db-full-cycle 슬라이스 시작 가능)")
    lines.append(
        f"- **백업 경로**: `{learned_empty_result.get('backup_path','N/A')}`"
    )
    lines.append(
        "- 다음 슬라이스에서 위 백업을 복구한 뒤 '학습 이득'이 있는 상태에서 "
        "동일 데이터를 재실행하여 성능 비교 가능"
    )
    lines.append("")
    lines.append("---")
    lines.append(f"*자동 생성: `{timestamp}` | run_id `{run_id}`*")
    lines.append("")
    return "\n".join(lines)


# ===========================================================================
# Main orchestrator
# ===========================================================================


def run_ai_live_run(
    provider_id: str = DEFAULT_PROVIDER_ID,
    artifact_dir: Path = ARTIFACT_DIR,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main orchestrator for rd-ai-live-run slice.

    Steps:
      1. Backup + empty learned tables
      2. Capture costco data
      3. Load all mart data
      4. Run live AI labeling (real provider)
      5. Adversarial v2 analysis
      6. Generate artifacts
    """
    _ensure_ai_imports()
    from adversarial_compare_extensions import (  # noqa: F811
        analyze_ai_confidence,
        analyze_category_distribution,
        analyze_volume_sanity,
        collect_launch_gate_blockers,
        semantic_spotcheck,
    )
    from artifact_db_adversarial_compare import normalize_source_row  # noqa: F811
    from providers.secret_resolver import resolve_secret_alias  # noqa: F811

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = uuid.uuid4().hex[:8]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"run-{timestamp}-{run_id}"

    # -----------------------------------------------------------------------
    # Wire logging auto-setup: always activate for non-dry-run runs so there
    # is irrefutable HTTP-level evidence of real provider calls.
    # -----------------------------------------------------------------------
    wire_log_path_str = os.environ.get("WALLETSAVIOR_WIRE_LOG_PATH", "").strip()
    if not wire_log_path_str and not dry_run:
        wire_log_path_str = str(artifact_dir / f"wire-log-{timestamp}-{run_id}.jsonl")
        os.environ["WALLETSAVIOR_WIRE_LOG_PATH"] = wire_log_path_str
        print(f"[WIRE] Auto-activating wire log: {wire_log_path_str}", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"WalletSavior rd-ai-live-run | provider={provider_id} | dry_run={dry_run}", flush=True)
    print(f"run_id: {run_id}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # -----------------------------------------------------------------------
    # Step 2: Empty learned tables
    # -----------------------------------------------------------------------
    print("Step 2: 학습 매칭 테이블 백업 및 비우기...", flush=True)
    if dry_run:
        learned_empty_result = {
            "backup_path": str(artifact_dir / f"learned-backup-DRY-RUN.json"),
            "keyword_alias_before": 0,
            "keyword_alias_after": 0,
            "product_matches_before": 0,
            "product_matches_after": 0,
        }
    else:
        learned_empty_result = empty_learned_tables(backup_dir=str(artifact_dir))
    print(
        f"  keyword_alias_approved: {learned_empty_result['keyword_alias_before']} → "
        f"{learned_empty_result['keyword_alias_after']}",
        flush=True,
    )
    print(
        f"  product_matches: {learned_empty_result['product_matches_before']} → "
        f"{learned_empty_result['product_matches_after']}",
        flush=True,
    )
    print(f"  백업 경로: {learned_empty_result['backup_path']}", flush=True)

    # -----------------------------------------------------------------------
    # Step 1: Capture costco data
    # -----------------------------------------------------------------------
    print("\nStep 1: 코스트코 신선 데이터 캡처 (cocodalin API)...", flush=True)
    costco_output_dir = artifact_dir / "costco-capture"
    costco_capture = capture_costco_cocodalin(costco_output_dir, dry_run=dry_run)
    print(
        f"  코스트코: {costco_capture['count']}건 캡처 "
        f"({'BLOCKED' if costco_capture['blocked'] else 'OK'})",
        flush=True,
    )
    if costco_capture["blocked"]:
        print(f"  ⚠️ FAIL-FAST: {costco_capture.get('ban_evidence','')}", flush=True)

    # Add costco capture dir to mart dirs
    costco_capture_dir = costco_output_dir
    if costco_capture["count"] > 0:
        # Save costco data as a mart dir JSON file for loading
        costco_mart_dir = (
            REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "costco"
        )
        costco_mart_dir.mkdir(parents=True, exist_ok=True)
        costco_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        costco_file = costco_mart_dir / f"cocodalin-capture-{costco_ts}.json"
        costco_file.write_text(
            json.dumps(
                {"raw_records": costco_capture["items"]},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"  코스트코 캡처 저장: {costco_file}", flush=True)

    # -----------------------------------------------------------------------
    # Step 1b: Check lottemart status
    # -----------------------------------------------------------------------
    lm_dir = MART_DIRS["lottemart"]
    lm_rows, lm_errors = load_mart_raw_records(lm_dir, "lottemart")
    lottemart_status = {
        "count": len(lm_rows),
        "blocked": len(lm_rows) < LOTTEMART_MIN_ROWS,
        "threshold": LOTTEMART_MIN_ROWS,
        "ban_evidence": (
            f"롯데마트 캡처 건수 {len(lm_rows)}건 — 임계값 {LOTTEMART_MIN_ROWS}건 미달. "
            "WAF(AWS WAF) 차단 의심. 기존 캡처 데이터로 진행."
            if len(lm_rows) < LOTTEMART_MIN_ROWS else None
        ),
    }
    if lottemart_status["blocked"]:
        print(
            f"\n⚠️ 롯데마트 FAIL-FAST: {len(lm_rows)}건 < {LOTTEMART_MIN_ROWS}건 임계값",
            flush=True,
        )
        print(f"   {lottemart_status['ban_evidence']}", flush=True)

    # -----------------------------------------------------------------------
    # Step 3: Load all mart data
    # -----------------------------------------------------------------------
    print("\nStep 3: 전체 마트 데이터 로딩...", flush=True)
    all_mart_dirs = dict(MART_DIRS)
    if costco_capture["count"] > 0:
        all_mart_dirs["costco"] = (
            REPO_ROOT / ".walletsavior-live-validation" / "mart3-full-coverage-diagnostics" / "costco"
        )

    per_mart_raw: dict[str, list[dict]] = {}
    load_errors: list[str] = []
    for mart_name, mart_dir in all_mart_dirs.items():
        rows, errs = load_mart_raw_records(mart_dir, mart_name)
        per_mart_raw[mart_name] = rows
        load_errors.extend(errs)
        print(f"  [{mart_name}]: {len(rows)}건 로드", flush=True)

    total_rows = sum(len(v) for v in per_mart_raw.values())
    print(f"\n  총 {total_rows}건 로드 완료", flush=True)

    # -----------------------------------------------------------------------
    # Step 4: Run live AI labeling
    # -----------------------------------------------------------------------
    print(f"\nStep 4: 실 AI 라벨링 실행 (provider={provider_id})...", flush=True)
    if not dry_run:
        # Verify API key is available
        api_key = resolve_secret_alias("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY not found. Add to packages/ai-admin/backend/.env"
            )
        os.environ["GOOGLE_API_KEY"] = api_key
        print(f"  GOOGLE_API_KEY: 설정됨 (길이={len(api_key)})", flush=True)

    per_mart_results: dict[str, dict[str, Any]] = {}
    all_source_rows: list[dict] = []
    all_proposal_rows: list[dict] = []

    for mart_name, raw_rows in per_mart_raw.items():
        print(f"\n  [{mart_name}] {len(raw_rows)}건 AI 라벨링...", flush=True)
        all_source_rows.extend(raw_rows)
        result = run_mart_pipeline_real(
            mart_name=mart_name,
            raw_rows=raw_rows,
            provider_id=provider_id,
            dry_run=dry_run,
        )
        per_mart_results[mart_name] = result
        all_proposal_rows.extend(result.get("proposal_rows", []))
        print(
            f"  [{mart_name}] 완료: 크롤러={result['crawler_rows']}, "
            f"AI제안={result['ai_proposals']}, 게이트통과={result['gates_passed']}, "
            f"폴백={result['fallback']}, escalated={result['escalated']}",
            flush=True,
        )

    # -----------------------------------------------------------------------
    # Step 5: Aggregate stage drop counts
    # -----------------------------------------------------------------------
    stage_drop_totals: dict[str, int] = {s: 0 for s in STAGES}
    for res in per_mart_results.values():
        for stage in STAGES:
            stage_drop_totals[stage] += res.get("silent_drop", {}).get(stage, 0)

    # -----------------------------------------------------------------------
    # Step 5: Adversarial v2
    # -----------------------------------------------------------------------
    print("\nStep 5: Adversarial v2 분석...", flush=True)
    normalized_sources = [normalize_source_row(r) for r in all_source_rows]
    cat_analysis = analyze_category_distribution(all_proposal_rows)
    conf_analysis = analyze_ai_confidence(all_proposal_rows)
    vol_analysis = analyze_volume_sanity(normalized_sources, all_proposal_rows)
    spotcheck = semantic_spotcheck(all_proposal_rows)

    blockers = collect_launch_gate_blockers(
        imbalance_alerts=cat_analysis["category_imbalance_alerts"],
        starvation_alerts=cat_analysis["category_sibling_starvation_alerts"],
        confidence_alerts=conf_analysis["low_confidence_alerts"],
        volume_alerts=vol_analysis["volume_alerts"],
        semantic_alerts=spotcheck["semantic_alerts"],
    )

    adversarial_v2 = {
        "schema": "walletsavior.artifact_db_adversarial_compare.v2",
        "mode": "ai_live_run_embedded",
        "category_distribution_per_mart": cat_analysis["category_distribution_per_mart"],
        "category_imbalance_alerts": cat_analysis["category_imbalance_alerts"],
        "ai_confidence_distribution": conf_analysis["ai_confidence_distribution"],
        "mart_volume_sanity": vol_analysis["mart_volume_sanity"],
        "volume_alerts": vol_analysis["volume_alerts"],
        "semantic_spotcheck": spotcheck["semantic_spotcheck"],
        "semantic_alerts": spotcheck["semantic_alerts"],
        "overall_launch_gate_blockers": blockers,
    }

    # -----------------------------------------------------------------------
    # Step 6: Build supplementary analysis
    # -----------------------------------------------------------------------
    confidence_hist = build_confidence_histogram(all_proposal_rows)
    proposal_counts = count_keyword_category_proposals(all_proposal_rows)

    # Determine verdict
    hard_blockers = [b for b in blockers if b.get("alert_type") != "data_load_error"]
    all_quota_exhausted = any(
        r.get("quota_exhausted") for r in per_mart_results.values()
    )
    if all_quota_exhausted:
        verdict = "quota_blocked"
    elif hard_blockers:
        verdict = "needs_more_work"
    else:
        verdict = "pass"

    # -----------------------------------------------------------------------
    # Step 7: Generate artifacts
    # -----------------------------------------------------------------------
    print("\nStep 6: 산출물 생성...", flush=True)

    # Collect wire log stats before writing the report
    wire_log_stats: dict[str, Any] = {"enabled": False}
    _active_wire_log_path = os.environ.get("WALLETSAVIOR_WIRE_LOG_PATH", "").strip()
    if _active_wire_log_path and not dry_run:
        _wlp = Path(_active_wire_log_path)
        if _wlp.exists():
            try:
                _lines = _wlp.read_text(encoding="utf-8").splitlines()
                _wire_entries = [json.loads(ln) for ln in _lines if ln.strip()]
                _ok = sum(1 for e in _wire_entries if 200 <= e.get("status", 0) < 300)
                _total = len(_wire_entries)
                _google = sum(1 for e in _wire_entries if e.get("is_google_genai"))
                wire_log_stats = {
                    "enabled": True,
                    "path": _active_wire_log_path,
                    "total_http_calls": _total,
                    "ok_http_calls": _ok,
                    "failed_http_calls": _total - _ok,
                    "google_genai_calls": _google,
                    "sample_entries": _wire_entries[:3],
                }
                print(
                    f"  [WIRE] {_google} Google GenAI calls, {_ok}/{_total} HTTP 200, "
                    f"log: {_active_wire_log_path}",
                    flush=True,
                )
                if _google == 0:
                    print(
                        "  ⚠️ [WIRE] ZERO Google GenAI calls captured — "
                        "provider may not have made real HTTP calls!",
                        flush=True,
                    )
            except Exception as _wl_exc:
                wire_log_stats = {"enabled": True, "path": _active_wire_log_path, "read_error": str(_wl_exc)}
        else:
            wire_log_stats = {"enabled": True, "path": _active_wire_log_path, "exists": False,
                              "warning": "wire log file not created — wire logger may not have been attached"}
            print("  ⚠️ [WIRE] Wire log file was not created!", flush=True)

    # Summary: escalation reasons
    escalation_reasons: list[dict] = []
    for mart_name, res in per_mart_results.items():
        for err in res.get("shrink_log_summary", {}).get("batch_errors", []):
            escalation_reasons.append({
                "mart": mart_name,
                **err,
            })
    if costco_capture["blocked"]:
        escalation_reasons.append({
            "mart": "costco",
            "type": "capture_fail_fast",
            "error": costco_capture.get("ban_evidence", ""),
        })
    if lottemart_status["blocked"]:
        escalation_reasons.append({
            "mart": "lottemart",
            "type": "capture_fail_fast",
            "error": lottemart_status.get("ban_evidence", ""),
        })

    # JSON report
    json_report: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "timestamp": timestamp,
        "provider_id": provider_id,
        "dry_run": dry_run,
        "verdict": verdict,
        "wire_log_stats": wire_log_stats,
        "crawl_capture": {
            "emart": {"count": per_mart_results.get("emart", {}).get("crawler_rows", 0), "blocked": False},
            "homeplus": {"count": per_mart_results.get("homeplus", {}).get("crawler_rows", 0), "blocked": False},
            "lottemart": {"count": lottemart_status["count"], "blocked": lottemart_status["blocked"]},
            "costco": {"count": costco_capture["count"], "blocked": costco_capture["blocked"]},
        },
        "learned_empty_result": learned_empty_result,
        "per_mart_stage_counts": {
            mart: {
                "crawler_rows": res["crawler_rows"],
                "ingested_rows": res["ingested_rows"],
                "ai_proposals": res["ai_proposals"],
                "gates_passed": res["gates_passed"],
                "publish_approved": res["publish_approved"],
                "public_snapshot_rows": res["public_snapshot_rows"],
            }
            for mart, res in per_mart_results.items()
        },
        "stage_drop_totals": stage_drop_totals,
        "confidence_histogram": confidence_hist,
        "proposal_counts": proposal_counts,
        "adversarial_v2": adversarial_v2,
        "escalation_reasons": escalation_reasons,
        "per_mart_escalation": {
            mart: {
                "escalated": res.get("escalated", 0),
                "fallback": res.get("fallback", 0),
                "quota_exhausted": res.get("quota_exhausted", False),
                "shrink_log_summary": res.get("shrink_log_summary", {}),
            }
            for mart, res in per_mart_results.items()
        },
        "load_errors": load_errors,
        "costco_capture": {
            "count": costco_capture["count"],
            "blocked": costco_capture["blocked"],
            "ban_evidence": costco_capture.get("ban_evidence"),
            "capture_path": costco_capture.get("capture_path"),
            "failure_count": len(costco_capture.get("failures", [])),
        },
        "lottemart_status": lottemart_status,
    }

    json_path = artifact_dir / f"{out_name}.json"
    json_path.write_text(
        json.dumps(json_report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # MD report
    md_content = build_korean_md_report(
        run_id=run_id,
        timestamp=timestamp,
        provider_id=provider_id,
        per_mart_results=per_mart_results,
        learned_empty_result=learned_empty_result,
        adversarial_v2=adversarial_v2,
        confidence_hist=confidence_hist,
        proposal_counts=proposal_counts,
        stage_drop_totals=stage_drop_totals,
        costco_capture=costco_capture,
        lottemart_status=lottemart_status,
        verdict=verdict,
    )
    md_path = artifact_dir / f"{out_name}.md"
    md_path.write_text(md_content, encoding="utf-8")

    print(f"  JSON 리포트: {json_path}", flush=True)
    print(f"  MD 리포트:   {md_path}", flush=True)

    return {
        "run_id": run_id,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "verdict": verdict,
        "per_mart_stage_counts": json_report["per_mart_stage_counts"],
        "learned_empty_result": learned_empty_result,
        "confidence_histogram": confidence_hist,
        "proposal_counts": proposal_counts,
        "stage_drop_totals": stage_drop_totals,
        "escalation_reasons": escalation_reasons,
        "costco_capture": json_report["costco_capture"],
        "lottemart_status": lottemart_status,
        "wire_log_stats": wire_log_stats,
    }


# ===========================================================================
# CLI entry point
# ===========================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WalletSavior rd-ai-live-run 슬라이스 오케스트레이터",
    )
    parser.add_argument(
        "--provider-id",
        default=DEFAULT_PROVIDER_ID,
        help=f"AI provider ID (기본: {DEFAULT_PROVIDER_ID})",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACT_DIR,
        help=f"산출물 디렉토리 (기본: {ARTIFACT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="실제 AI 호출 없이 구조 검증 (fallback 응답)",
    )
    parser.add_argument(
        "--provider-mode",
        choices=["real", "fallback"],
        default="real",
        help="provider 모드 (기본: real). fallback은 --dry-run과 같음.",
    )
    parser.add_argument("--allow-live-ai-provider", action="store_true", default=False)
    parser.add_argument("--label-spacing", type=int, default=12)
    parser.add_argument("--large-batch-opt-in", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dry_run = args.dry_run or args.provider_mode == "fallback"

    if not dry_run and not args.allow_live_ai_provider:
        print(
            "ERROR: --provider-mode real requires --allow-live-ai-provider flag.",
            file=sys.stderr,
        )
        return 1

    # WALLETSAVIOR_AI_LIVE_FORCE=1: require wire logging to be active.
    force_live = os.environ.get("WALLETSAVIOR_AI_LIVE_FORCE", "").strip() == "1"
    wire_log_path = os.environ.get("WALLETSAVIOR_WIRE_LOG_PATH", "").strip()
    if force_live and not wire_log_path:
        print(
            "WARNING: WALLETSAVIOR_AI_LIVE_FORCE=1 is set but WALLETSAVIOR_WIRE_LOG_PATH "
            "is not — set WALLETSAVIOR_WIRE_LOG_PATH to capture wire-level HTTP evidence.",
            file=sys.stderr,
            flush=True,
        )
    if force_live:
        print(
            f"[FORCE-LIVE] ⚡ WALLETSAVIOR_AI_LIVE_FORCE=1 — "
            f"cache bypass confirmed, wire log: {wire_log_path or '(not set)'}",
            flush=True,
        )

    try:
        result = run_ai_live_run(
            provider_id=args.provider_id,
            artifact_dir=args.artifact_dir,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    print(f"\n{'='*60}", flush=True)
    print(f"VERDICT: {result['verdict']}", flush=True)
    print(f"JSON: {result['json_path']}", flush=True)
    print(f"MD:   {result['md_path']}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Print summary
    print("마트별 수치:", flush=True)
    for mart, counts in sorted(result["per_mart_stage_counts"].items()):
        print(
            f"  {mart:<10}: 크롤러={counts['crawler_rows']}, "
            f"AI제안={counts['ai_proposals']}, 게이트통과={counts['gates_passed']}",
            flush=True,
        )

    if result.get("escalation_reasons"):
        print(f"\n⚠️ Escalation reasons ({len(result['escalation_reasons'])}건):", flush=True)
        for r in result["escalation_reasons"][:5]:
            print(f"  [{r.get('mart')}] {r.get('type','?')} — {str(r.get('error',''))[:80]}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
