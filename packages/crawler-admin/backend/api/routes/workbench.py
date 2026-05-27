"""workbench.py — RD8 운영자 워크밴치 API.

운영자가 매주 한 화면으로 4사 마트 크롤 상태를 관찰하도록 설계.

엔드포인트:
    GET /api/workbench/overview            — 4사 카드 + 액션 가능 여부
    GET /api/workbench/mart/{key}/runs     — 마트별 최근 run 목록 + 차단 사유
    GET /api/workbench/mart/{key}/samples  — 마트별 raw_payload 샘플
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from services import crawl_orchestrator as orch
from services.ai_admin_readonly import get_ai_admin_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

# ── 4사 마트 정의 (UI 브랜드 색상 동기화) ───────────────────────────
MARTS: list[dict[str, str]] = [
    {"key": "emart",     "label": "이마트",     "color": "#FFC107", "accent": "#F59E0B"},
    {"key": "homeplus",  "label": "홈플러스",   "color": "#E11D48", "accent": "#BE123C"},
    {"key": "lottemart", "label": "롯데마트",   "color": "#0D9488", "accent": "#0F766E"},
    {"key": "costco",    "label": "코스트코",   "color": "#1E3A8A", "accent": "#1E40AF"},
]
MART_KEYS = {m["key"] for m in MARTS}

# raw_crawl_records.source_name이 mart key와 다를 수 있어 alias 표 관리.
SOURCE_NAME_ALIASES: dict[str, list[str]] = {
    "emart": ["emart", "이마트"],
    "homeplus": ["homeplus", "홈플러스"],
    "lottemart": ["lottemart", "롯데마트", "lotte_mart", "lottemart_online"],
    "costco": ["costco", "코스트코", "cocodalin"],
}

# 흔한 캡 의심 round number — 캡처가 정확히 떨어지면 cap 가능성.
SUSPECT_ROUND_NUMBERS = {100, 150, 200, 250, 300, 400, 500, 750, 1000}


def _ensure_plugins() -> None:
    """ai 4사 플러그인 등록 — orchestrator.py와 동일한 idempotent 로직."""
    for mod in ("emart", "homeplus", "lottemart", "costco"):
        try:
            module = __import__(f"crawlers.marts.{mod}.plugin", fromlist=["register"])
            module.register()
        except Exception as exc:  # pragma: no cover - import-time best effort
            logger.warning("[workbench] plugin %s register failed: %s", mod, exc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _duration_ms(started: Optional[str], finished: Optional[str]) -> Optional[int]:
    s = _parse_iso(started)
    f = _parse_iso(finished)
    if not s or not f:
        return None
    delta = (f - s).total_seconds() * 1000
    if delta < 0:
        return None
    return int(delta)


def _cap_suspect(items_found: int) -> bool:
    """items_found가 흔한 round cap이면 True."""
    if items_found <= 0:
        return False
    if items_found in SUSPECT_ROUND_NUMBERS:
        return True
    # 100 이상의 100 단위 배수도 의심.
    if items_found >= 100 and items_found % 100 == 0:
        return True
    return False


def _raw_records_stats(session: Session, mart_key: str) -> dict[str, Any]:
    """ai-admin DB의 raw_crawl_records 중 해당 mart의 통계.

    매주 운영자가 보는 핵심 수치 — 총 row, 중복률, 최근 수집 시각.
    """
    aliases = SOURCE_NAME_ALIASES.get(mart_key, [mart_key])
    placeholders = ", ".join(f":a{i}" for i in range(len(aliases)))
    params = {f"a{i}": v for i, v in enumerate(aliases)}

    try:
        total = session.execute(
            text(
                f"SELECT COUNT(*) FROM raw_crawl_records "
                f"WHERE source_name IN ({placeholders})"
            ),
            params,
        ).scalar() or 0

        # 중복 raw_title 비율 — 동일 raw_title이 2회 이상 등장하는 비율.
        dup = session.execute(
            text(
                f"SELECT COUNT(*) FROM ( "
                f"  SELECT raw_title, COUNT(*) AS c FROM raw_crawl_records "
                f"  WHERE source_name IN ({placeholders}) AND raw_title IS NOT NULL "
                f"  GROUP BY raw_title HAVING c > 1 "
                f")"
            ),
            params,
        ).scalar() or 0

        latest = session.execute(
            text(
                f"SELECT MAX(crawled_at) FROM raw_crawl_records "
                f"WHERE source_name IN ({placeholders})"
            ),
            params,
        ).scalar()
    except Exception as exc:  # ai-admin DB가 없거나 raw_crawl_records 테이블이 없을 때
        logger.debug("[workbench] raw_crawl_records 조회 실패 mart=%s err=%s", mart_key, exc)
        return {"rawRecordCount": 0, "dupTitles": 0, "latestCrawledAt": None}

    return {
        "rawRecordCount": int(total),
        "dupTitles": int(dup),
        "latestCrawledAt": latest if isinstance(latest, str) else (latest.isoformat() if latest else None),
    }


def _mart_card(mart: dict[str, str], session: Session) -> dict[str, Any]:
    """카드 1장 — last run + raw_records stats 결합."""
    store = orch.get_run_store()
    last = store.last_run_for_plugin(mart["key"])
    runs_page = store.list_runs(plugin_name=mart["key"], page=1, page_size=20)
    recent_runs = runs_page.get("items", [])

    failed_recent = sum(1 for r in recent_runs if r.get("status") == "failed")
    items_found = int((last or {}).get("items_found", 0) or 0)
    items_saved = int((last or {}).get("items_saved", 0) or 0)
    failure_reasons = (last or {}).get("failure_reasons", []) or []

    raw_stats = _raw_records_stats(session, mart["key"])
    dup_ratio = (
        raw_stats["dupTitles"] / raw_stats["rawRecordCount"]
        if raw_stats["rawRecordCount"] > 0
        else 0.0
    )

    return {
        "key": mart["key"],
        "label": mart["label"],
        "color": mart["color"],
        "accent": mart["accent"],
        "lastRunAt": (last or {}).get("started_at"),
        "lastRunFinishedAt": (last or {}).get("finished_at"),
        "lastRunStatus": (last or {}).get("status") or "none",
        "durationMs": _duration_ms((last or {}).get("started_at"), (last or {}).get("finished_at")),
        "itemsFound": items_found,
        "itemsSaved": items_saved,
        "failureReasons": failure_reasons[:5],
        "recentFailed": failed_recent,
        "recentTotal": len(recent_runs),
        "capSuspect": _cap_suspect(items_found),
        "rawRecordCount": raw_stats["rawRecordCount"],
        "dupTitles": raw_stats["dupTitles"],
        "dupRatio": round(dup_ratio, 3),
        "latestCrawledAt": raw_stats["latestCrawledAt"],
    }


# ── GET /api/workbench/overview ──────────────────────────────────
@router.get("/overview")
def get_overview(
    session: Session = Depends(get_ai_admin_session),
) -> dict[str, Any]:
    """4사 마트 카드 + 라이브 가용성 + 마지막 export 요약."""
    _ensure_plugins()
    registry = orch.get_registry()
    registered = {p.name for p in registry.list_all()}

    cards = []
    for mart in MARTS:
        card = _mart_card(mart, session)
        card["pluginRegistered"] = mart["key"] in registered
        cards.append(card)

    # 라이브 가용성: 4사 모두 registered여야 "live ready" — 아니면 정직히 false.
    live_ready = MART_KEYS.issubset(registered)

    total_rows = sum(c["rawRecordCount"] for c in cards)

    return {
        "marts": cards,
        "liveReady": live_ready,
        "registeredCount": len(registered & MART_KEYS),
        "totalRawRecords": total_rows,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /api/workbench/mart/{key}/runs ───────────────────────────
@router.get("/mart/{key}/runs")
def get_mart_runs(
    key: str,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    if key not in MART_KEYS:
        raise HTTPException(status_code=404, detail=f"unknown mart: {key}")
    _ensure_plugins()
    store = orch.get_run_store()
    page = store.list_runs(plugin_name=key, page=1, page_size=limit)
    items = page.get("items", [])
    # duration 보강
    for r in items:
        r["durationMs"] = _duration_ms(r.get("started_at"), r.get("finished_at"))
    return {"mart": key, "runs": items, "total": page.get("total", len(items))}


# ── GET /api/workbench/mart/{key}/samples ────────────────────────
@router.get("/mart/{key}/samples")
def get_mart_samples(
    key: str,
    limit: int = Query(5, ge=1, le=20),
    session: Session = Depends(get_ai_admin_session),
) -> dict[str, Any]:
    """raw_crawl_records에서 마트별 샘플 N건. raw_payload 미리보기용."""
    if key not in MART_KEYS:
        raise HTTPException(status_code=404, detail=f"unknown mart: {key}")
    aliases = SOURCE_NAME_ALIASES.get(key, [key])
    placeholders = ", ".join(f":a{i}" for i in range(len(aliases)))
    params: dict[str, Any] = {f"a{i}": v for i, v in enumerate(aliases)}
    params["lim"] = limit

    try:
        rows = session.execute(
            text(
                f"SELECT raw_record_id, batch_id, source_name, raw_title, "
                f"raw_price, crawled_at, raw_payload "
                f"FROM raw_crawl_records "
                f"WHERE source_name IN ({placeholders}) "
                f"ORDER BY crawled_at DESC LIMIT :lim"
            ),
            params,
        ).fetchall()
    except Exception as exc:
        logger.debug("[workbench] samples 조회 실패 mart=%s err=%s", key, exc)
        return {"mart": key, "samples": [], "note": "raw_crawl_records 없음"}

    import json as _json

    samples: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else dict(zip(
            ["raw_record_id", "batch_id", "source_name", "raw_title", "raw_price", "crawled_at", "raw_payload"], r,
        ))
        payload = d.get("raw_payload")
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {"_raw": payload[:500]}
        d["raw_payload"] = payload or {}
        ca = d.get("crawled_at")
        if ca is not None and hasattr(ca, "isoformat"):
            d["crawled_at"] = ca.isoformat()
        samples.append(d)

    return {"mart": key, "samples": samples}


# ── POST /api/workbench/run-all ─────────────────────────────────
@router.post("/run-all", status_code=202)
def run_all_marts() -> dict[str, Any]:
    """4사 마트 전수 크롤 트리거 — 동기 직렬 실행.

    각 마트 trigger_run을 순차 호출하고 run_id 목록을 반환.
    실패한 마트는 결과에 error로 표시 (전체 실패로 만들지 않음).
    """
    _ensure_plugins()
    results: list[dict[str, Any]] = []
    for mart in MARTS:
        try:
            run_id = orch.trigger_run(plugin_name=mart["key"], triggered_by="workbench-run-all")
            results.append({"mart": mart["key"], "run_id": run_id, "status": "started"})
        except Exception as exc:
            logger.warning("[workbench] run-all failed mart=%s err=%s", mart["key"], exc)
            results.append({"mart": mart["key"], "run_id": None, "status": "error", "error": str(exc)})
    return {"results": results, "startedAt": datetime.now(timezone.utc).isoformat()}
