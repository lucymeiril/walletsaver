"""Current crawler management routes for the ingestion-capable mart pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.app import limiter
from audit import AuditEventType, audit_log
from concurrency import (
    MAX_CONCURRENT_CRAWLS,
    acquire_crawler_slot,
    get_semaphore,
    release_crawler_slot,
)
from crawlers.registry.registry import CrawlerRegistry
from pipeline.pipeline import CrawlPipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

_registry: CrawlerRegistry | None = None
_pipeline: CrawlPipeline | None = None
_crawl_results: dict[str, dict[str, Any]] = {}

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_STATUS_FILE = _BACKEND_DIR / "crawler_status.json"
_RUN_HISTORY_FILE = _BACKEND_DIR / "crawler_run_history.json"
_SETTINGS_FILE = _BACKEND_DIR / "crawler_settings.json"
MAX_RECENT_RUNS = 5
_SSE_MAX_DURATION = int(os.getenv("SSE_MAX_DURATION", "1800"))
_TERMINAL_STATUSES = {"success", "failed", "partial_failure"}


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("[crawler-api] ignored invalid runtime state file: %s", path.name)
        return default


def _write_json(path: Path, payload) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("[crawler-api] failed to persist runtime state: %s", path.name)


def _load_status() -> dict[str, str]:
    return _read_json(_STATUS_FILE, {})


def _save_status(status: dict[str, str]) -> None:
    _write_json(_STATUS_FILE, status)


def _load_run_history() -> dict[str, list[dict]]:
    return _read_json(_RUN_HISTORY_FILE, {})


def _append_run_history(crawler_id: str, status: str, duration: float | None = None) -> None:
    history = _load_run_history()
    runs = history.get(crawler_id, [])
    runs.append(
        {
            "status": status,
            "duration": duration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    history[crawler_id] = runs[-MAX_RECENT_RUNS:]
    _write_json(_RUN_HISTORY_FILE, history)


def _load_settings() -> dict[str, dict]:
    return _read_json(_SETTINGS_FILE, {})


def _save_settings(settings: dict[str, dict]) -> None:
    _write_json(_SETTINGS_FILE, settings)


def _get_registry() -> CrawlerRegistry:
    global _registry
    if _registry is None:
        crawlers_dir = Path(__file__).resolve().parent.parent.parent / "crawlers"
        _registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
        _registry.discover()
    return _registry


def _get_pipeline() -> CrawlPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CrawlPipeline(registry=_get_registry())
    return _pipeline


def _require_crawler(crawler_id: str):
    try:
        return _get_registry().get_crawler(crawler_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found") from exc


@router.get("")
@limiter.limit("60/minute")
async def list_crawlers(request: Request):
    """Return only crawlers explicitly registered for the current product pipeline."""
    registry = _get_registry()
    rows = registry.list_crawlers()
    status_map = _load_status()
    run_history = _load_run_history()

    for row in rows:
        crawler_id = row["name"]
        row["status"] = status_map.get(crawler_id, "active")
        row["recentRuns"] = run_history.get(crawler_id, [])
        if crawler_id == "lottemart":
            try:
                crawler = registry.get_crawler(crawler_id)
                loader = getattr(crawler, "load_waf_blocked_categories", None)
                blocked = loader() if callable(loader) else []
            except Exception:
                blocked = []
            row["wafBlockedCount"] = len(blocked)
            row["wafBlockedItems"] = blocked[:10]

    return {"crawlers": rows}


class LotteCategoryRunRequest(BaseModel):
    url: Optional[str] = Field(None, max_length=500)
    query: Optional[str] = Field(None, max_length=200)
    category_hint: Optional[str] = Field(None, max_length=200)


def _lotte_category_payload(row: dict[str, Any]) -> dict[str, Any]:
    url = str(row.get("url") or "")
    return {
        "key": hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] if url else "",
        "query": row.get("query"),
        "category_hint": row.get("category_hint"),
        "category_path": row.get("category_path") if isinstance(row.get("category_path"), list) else [],
        "request_type": row.get("request_type"),
        "url": url,
    }


@router.get("/lottemart/categories")
@limiter.limit("30/minute")
async def list_lottemart_categories(request: Request, refresh: bool = Query(False)):
    crawler = _require_crawler("lottemart")
    lister = getattr(crawler, "list_category_requests", None)
    if not callable(lister):
        raise HTTPException(status_code=404, detail="Lotte category listing is unavailable")
    rows = lister(refresh=refresh)
    return {
        "crawler_id": "lottemart",
        "count": len(rows),
        "categories": [_lotte_category_payload(row) for row in rows],
    }


@router.post("/lottemart/run-category")
@limiter.limit("10/minute")
async def run_lottemart_category(body: LotteCategoryRunRequest, request: Request):
    crawler = _require_crawler("lottemart")
    lister = getattr(crawler, "list_category_requests", None)
    if not callable(lister):
        raise HTTPException(status_code=404, detail="Lotte category listing is unavailable")

    selected = None
    for row in lister(refresh=False):
        if body.url and row.get("url") == body.url:
            selected = row
            break
        if body.query and row.get("query") == body.query:
            selected = row
            break
        if body.category_hint and row.get("category_hint") == body.category_hint:
            selected = row
            break
    if selected is None:
        raise HTTPException(status_code=404, detail="요청한 롯데마트 카테고리를 찾을 수 없습니다")

    if not await acquire_crawler_slot("lottemart"):
        return {
            "crawler_id": "lottemart",
            "status": "running",
            "message": "Crawler 'lottemart' is already running",
            "category": _lotte_category_payload(selected),
        }

    crawler._selected_category_request = selected
    _crawl_results["lottemart"] = {
        "crawler_id": "lottemart",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items_found": 0,
        "items_valid": 0,
        "items_saved": 0,
        "errors": [],
        "progress_stage": "selected_category_started",
        "selectedCategory": _lotte_category_payload(selected),
    }
    asyncio.create_task(
        _run_and_store("lottemart", _get_pipeline(), crawl_method="crawl_selected_category")
    )
    return {
        "crawler_id": "lottemart",
        "status": "running",
        "message": f"롯데마트 카테고리 수동 실행 시작: {selected.get('query')}",
        "category": _lotte_category_payload(selected),
    }


class CrawlerToggleRequest(BaseModel):
    status: str


@router.put("/{crawler_id}/toggle")
async def toggle_crawler(crawler_id: str, body: CrawlerToggleRequest):
    _require_crawler(crawler_id)
    if body.status not in {"active", "inactive"}:
        raise HTTPException(400, "status must be 'active' or 'inactive'")
    status_map = _load_status()
    status_map[crawler_id] = body.status
    _save_status(status_map)
    return {"crawler_id": crawler_id, "status": body.status}


class CrawlerSettingsUpdate(BaseModel):
    target_url: Optional[str] = None
    delay: Optional[float] = None
    max_items: Optional[int] = None


@router.get("/{crawler_id}/settings")
async def get_crawler_settings(crawler_id: str):
    _require_crawler(crawler_id)
    registry_info = _get_registry()._registry[crawler_id]
    config = registry_info.get("config", {})
    overrides = _load_settings().get(crawler_id, {})
    return {
        "crawler_id": crawler_id,
        "target_url": overrides.get("target_url", ""),
        "delay": overrides.get("delay", 1.0),
        "max_items": overrides.get("max_items", 100),
        "strategy": "current_crawler",
        "difficulty": config.get("difficulty", 1),
    }


@router.put("/{crawler_id}/settings")
async def update_crawler_settings(crawler_id: str, request: Request, body: CrawlerSettingsUpdate):
    _require_crawler(crawler_id)
    settings = _load_settings()
    current = settings.get(crawler_id, {})

    if body.target_url is not None:
        from api.security.url_validator import validate_target_url
        current["target_url"] = validate_target_url(body.target_url)
    if body.delay is not None:
        if not 0.1 <= body.delay <= 60.0:
            raise HTTPException(422, "delay must be between 0.1 and 60.0 seconds")
        current["delay"] = body.delay
    if body.max_items is not None:
        if not 1 <= body.max_items <= 10000:
            raise HTTPException(422, "max_items must be between 1 and 10000")
        current["max_items"] = body.max_items

    settings[crawler_id] = current
    _save_settings(settings)
    audit_log(
        AuditEventType.CRAWLER_SETTINGS_UPDATE,
        request=request,
        resource=crawler_id,
        detail={"fields_changed": list(body.model_dump(exclude_unset=True).keys())},
    )
    return {"crawler_id": crawler_id, "settings": current}


class BulkRunRequest(BaseModel):
    crawler_ids: List[str]

    @field_validator("crawler_ids")
    @classmethod
    def cap_size(cls, values):
        if len(values) > MAX_CONCURRENT_CRAWLS:
            raise ValueError(f"Maximum {MAX_CONCURRENT_CRAWLS} crawlers per bulk-run request")
        return values


@router.post("/bulk-run")
async def bulk_run_crawlers(request: Request, body: BulkRunRequest):
    results: list[dict[str, Any]] = []
    audit_log(
        AuditEventType.CRAWLER_BULK_RUN,
        request=request,
        detail={"crawler_ids": body.crawler_ids},
    )

    for crawler_id in body.crawler_ids:
        try:
            _require_crawler(crawler_id)
        except HTTPException:
            results.append(
                {
                    "crawler_id": crawler_id,
                    "status": "failed",
                    "error": f"Crawler '{crawler_id}' not found",
                }
            )
            continue
        if not await acquire_crawler_slot(crawler_id):
            results.append(
                {
                    "crawler_id": crawler_id,
                    "status": "skipped",
                    "message": f"Crawler '{crawler_id}' is already running",
                }
            )
            continue

        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "items_found": 0,
            "items_valid": 0,
            "items_saved": 0,
            "errors": [],
        }
        asyncio.create_task(_run_and_store(crawler_id, _get_pipeline()))
        results.append({"crawler_id": crawler_id, "status": "running"})

    return {"results": results}


@router.post("/{crawler_id}/run")
@limiter.limit("5/minute")
async def run_crawler(crawler_id: str, request: Request):
    _require_crawler(crawler_id)
    if not await acquire_crawler_slot(crawler_id):
        return {
            "crawler_id": crawler_id,
            "status": "running",
            "message": f"Crawler '{crawler_id}' is already running",
        }

    _crawl_results[crawler_id] = {
        "crawler_id": crawler_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items_found": 0,
        "items_valid": 0,
        "items_saved": 0,
        "errors": [],
    }
    audit_log(AuditEventType.CRAWLER_RUN, request=request, resource=crawler_id)
    asyncio.create_task(_run_and_store(crawler_id, _get_pipeline()))
    return {
        "crawler_id": crawler_id,
        "status": "running",
        "message": f"Crawler '{crawler_id}' started",
    }


@router.post("/{crawler_id}/retry-waf-blocked")
@limiter.limit("5/minute")
async def retry_waf_blocked(crawler_id: str, request: Request):
    if crawler_id != "lottemart":
        raise HTTPException(status_code=404, detail="WAF blocked retry is only supported for lottemart")
    crawler = _require_crawler(crawler_id)
    loader = getattr(crawler, "load_waf_blocked_categories", None)
    queued = loader() if callable(loader) else []
    if not queued:
        return {
            "crawler_id": crawler_id,
            "status": "idle",
            "message": "재시도할 WAF 차단 카테고리가 없습니다.",
            "wafBlockedCount": 0,
        }
    if not await acquire_crawler_slot(crawler_id):
        return {
            "crawler_id": crawler_id,
            "status": "running",
            "message": f"Crawler '{crawler_id}' is already running",
            "wafBlockedCount": len(queued),
        }

    _crawl_results[crawler_id] = {
        "crawler_id": crawler_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items_found": 0,
        "items_valid": 0,
        "items_saved": 0,
        "errors": [],
        "progress_stage": "waf_retry_started",
        "wafBlockedCount": len(queued),
    }
    asyncio.create_task(
        _run_and_store(crawler_id, _get_pipeline(), crawl_method="crawl_waf_blocked_categories")
    )
    return {
        "crawler_id": crawler_id,
        "status": "running",
        "message": f"{len(queued)}개 WAF 차단 카테고리 재시도 시작",
        "wafBlockedCount": len(queued),
    }


@router.get("/{crawler_id}/status")
@limiter.limit("60/minute")
async def get_crawler_status(crawler_id: str, request: Request):
    _require_crawler(crawler_id)
    result = _crawl_results.get(
        crawler_id,
        {"crawler_id": crawler_id, "status": "idle", "last_run": None},
    )
    etag = hashlib.md5(
        json.dumps(result, sort_keys=True, default=str).encode()
    ).hexdigest()
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=304)
    return JSONResponse(content=result, headers={"ETag": f'"{etag}"'})


@router.get("/{crawler_id}/status/stream")
async def stream_crawler_status(crawler_id: str, request: Request):
    _require_crawler(crawler_id)

    async def event_generator():
        last_hash = None
        stream_start = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            if time.monotonic() - stream_start > _SSE_MAX_DURATION:
                yield 'data: {"status":"timeout","message":"Stream max duration reached"}\n\n'
                break

            result = _crawl_results.get(
                crawler_id,
                {"crawler_id": crawler_id, "status": "idle"},
            )
            current_json = json.dumps(result, sort_keys=True, default=str)
            current_hash = hashlib.md5(current_json.encode()).hexdigest()
            if current_hash != last_hash:
                last_hash = current_hash
                yield f"data: {current_json}\n\n"
            if result.get("status") in _TERMINAL_STATUSES:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_and_store(
    crawler_id: str,
    pipeline: CrawlPipeline,
    crawl_method: str = "crawl",
):
    async def publish_progress(payload: dict[str, Any]) -> None:
        current = _crawl_results.setdefault(crawler_id, {"crawler_id": crawler_id})
        quality = payload.get("quality_details") if isinstance(payload.get("quality_details"), dict) else {}
        current.update(
            {
                "crawler_id": crawler_id,
                "status": "running",
                "progress_stage": payload.get("stage", current.get("progress_stage", "running")),
                "items_found": payload.get("items_found", current.get("items_found", 0)),
                "items_valid": payload.get("items_valid", current.get("items_valid", 0)),
                "items_saved": payload.get("items_saved", current.get("items_saved", 0)),
                "errors": payload.get("errors", current.get("errors", [])),
            }
        )
        if payload.get("strategy_used"):
            current["strategy_used"] = payload["strategy_used"]
        for key in (
            "pages_attempted",
            "queries_attempted",
            "source_raw_count",
            "items_count",
            "deduplicated_count",
            "invalid_count",
        ):
            if key in payload:
                current[key] = payload[key]
            elif key in quality:
                current[key] = quality[key]

    try:
        async with get_semaphore():
            result = await pipeline.run_crawler(
                crawler_id,
                progress_callback=publish_progress,
                crawl_method=crawl_method,
            )

        final_payload = {
            "crawler_id": crawler_id,
            "status": result.status,
            "items_found": result.items_found,
            "items_valid": result.items_valid,
            "items_saved": result.items_saved,
            "duration": result.duration,
            "errors": result.errors,
            "progress_stage": "finished",
            "quality_score": result.quality_score,
            "quality_details": result.quality_details,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        _crawl_results[crawler_id] = final_payload
        _append_run_history(crawler_id, result.status, result.duration)
        audit_log(
            AuditEventType.CRAWL_COMPLETED,
            resource=crawler_id,
            detail={
                "items_found": result.items_found,
                "items_saved": result.items_saved,
                "duration": result.duration,
            },
        )
    except Exception:
        logger.exception("Crawler '%s' failed", crawler_id)
        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": "failed",
            "error": "Crawler execution failed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "errors": ["internal error"],
        }
        _append_run_history(crawler_id, "failed")
        audit_log(
            AuditEventType.CRAWL_FAILED,
            resource=crawler_id,
            result="error",
        )
    finally:
        await release_crawler_slot(crawler_id)
