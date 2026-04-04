"""크롤러 관리 라우트."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

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

MAX_RECENT_RUNS = 5


def _load_status() -> dict[str, str]:
    """크롤러 활성/비활성 상태를 파일에서 로드."""
    if _STATUS_FILE.exists():
        try:
            with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_status(status: dict[str, str]) -> None:
    """크롤러 상태를 파일에 저장."""
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"크롤러 상태 저장 실패: {e}")


def _load_run_history() -> dict[str, list[dict]]:
    """크롤러 실행 이력을 파일에서 로드."""
    if _RUN_HISTORY_FILE.exists():
        try:
            with open(_RUN_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_run_history(history: dict[str, list[dict]]) -> None:
    """크롤러 실행 이력을 파일에 저장."""
    try:
        with open(_RUN_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"크롤러 실행 이력 저장 실패: {e}")


def _append_run_history(crawler_id: str, status: str, duration: float | None = None) -> None:
    """크롤러 실행 결과를 이력에 추가 (최근 5회 유지)."""
    history = _load_run_history()
    runs = history.get(crawler_id, [])
    runs.append({
        "status": status,
        "duration": duration,
        "timestamp": datetime.now().isoformat(),
    })
    history[crawler_id] = runs[-MAX_RECENT_RUNS:]
    _save_run_history(history)


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


@router.get("")
async def list_crawlers():
    """등록된 크롤러 목록 (활성/비활성 상태 + 최근 실행 이력 포함)."""
    reg = _get_registry()
    crawlers = reg.list_crawlers()
    status_map = _load_status()
    run_history = _load_run_history()

    for c in crawlers:
        c["status"] = status_map.get(c["name"], "active")
        c["recentRuns"] = run_history.get(c["name"], [])

    return {"crawlers": crawlers}


@router.get("/{crawler_id}/status")
async def get_crawler_status(crawler_id: str, request: Request):
    """크롤러 상태 조회 — ETag 기반 304 지원으로 폴링 시 불필요한 데이터 전송 방지."""
    reg = _get_registry()
    try:
        reg.get_crawler(crawler_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found")

    result = _crawl_results.get(crawler_id)
    if not result:
        result = {
            "crawler_id": crawler_id,
            "status": "idle",
            "last_run": None,
        }

    # ETag: 상태 해시로 변경 없으면 304 반환 — 폴링 시 대역폭 절약
    etag = hashlib.md5(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=304)

    return JSONResponse(content=result, headers={"ETag": f'"{etag}"'})


class CrawlerToggleRequest(BaseModel):
    status: str  # "active" or "inactive"


@router.put("/{crawler_id}/toggle")
async def toggle_crawler(crawler_id: str, body: CrawlerToggleRequest):
    """크롤러 활성/비활성 토글 — 상태를 파일에 저장."""
    if body.status not in ("active", "inactive"):
        raise HTTPException(400, "status must be 'active' or 'inactive'")

    status_map = _load_status()
    status_map[crawler_id] = body.status
    _save_status(status_map)

    return {"crawler_id": crawler_id, "status": body.status}


class CrawlerSettingsUpdate(BaseModel):
    target_url: Optional[str] = None
    delay: Optional[float] = None
    max_items: Optional[int] = None


_SETTINGS_FILE = _BACKEND_DIR / "crawler_settings.json"


def _load_settings() -> dict[str, dict]:
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_settings(settings: dict[str, dict]) -> None:
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"크롤러 설정 저장 실패: {e}")


@router.get("/{crawler_id}/settings")
async def get_crawler_settings(crawler_id: str):
    """크롤러 설정 조회."""
    reg = _get_registry()
    info = reg._registry.get(crawler_id)
    if not info:
        raise HTTPException(404, f"Crawler '{crawler_id}' not found")

    config = info.get("config", {})
    target = config.get("target", {})
    if isinstance(target, str):
        target = {"url": target}

    overrides = _load_settings().get(crawler_id, {})

    return {
        "crawler_id": crawler_id,
        "target_url": overrides.get("target_url", target.get("url", "")),
        "delay": overrides.get("delay", 1.0),
        "max_items": overrides.get("max_items", 100),
        "strategy": target.get("strategy", "requests"),
        "difficulty": target.get("difficulty", 1),
    }


@router.put("/{crawler_id}/settings")
async def update_crawler_settings(crawler_id: str, body: CrawlerSettingsUpdate):
    """크롤러 설정 업데이트 — 파일에 저장."""
    settings = _load_settings()
    current = settings.get(crawler_id, {})

    if body.target_url is not None:
        current["target_url"] = body.target_url
    if body.delay is not None:
        current["delay"] = body.delay
    if body.max_items is not None:
        current["max_items"] = body.max_items

    settings[crawler_id] = current
    _save_settings(settings)

    return {"crawler_id": crawler_id, "settings": current}


class BulkRunRequest(BaseModel):
    crawler_ids: List[str]


@router.post("/bulk-run")
async def bulk_run_crawlers(body: BulkRunRequest):
    """여러 크롤러 순차 실행, 결과 배열 반환."""
    reg = _get_registry()
    pipeline = _get_pipeline()
    results: list[dict[str, Any]] = []

    for cid in body.crawler_ids:
        try:
            reg.get_crawler(cid)
        except KeyError:
            results.append({
                "crawler_id": cid,
                "status": "failed",
                "error": f"Crawler '{cid}' not found",
            })
            continue

        current = _crawl_results.get(cid)
        if current and current.get("status") == "running":
            results.append({
                "crawler_id": cid,
                "status": "skipped",
                "message": f"Crawler '{cid}' is already running",
            })
            continue

        _crawl_results[cid] = {
            "crawler_id": cid,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "items_found": 0,
            "items_valid": 0,
            "items_saved": 0,
            "errors": [],
        }

        asyncio.create_task(_run_and_store(cid, pipeline))
        results.append({
            "crawler_id": cid,
            "status": "running",
            "message": f"Crawler '{cid}' started",
        })

    return {"results": results}


@router.post("/{crawler_id}/run")
async def run_crawler(crawler_id: str):
    """크롤러 즉시 실행 — 백그라운드에서 파이프라인 실행 후 DB Admin 대기열에 제출."""
    reg = _get_registry()
    try:
        reg.get_crawler(crawler_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found")

    current = _crawl_results.get(crawler_id)
    if current and current.get("status") == "running":
        return {
            "crawler_id": crawler_id,
            "status": "running",
            "message": f"Crawler '{crawler_id}' is already running",
        }

    _crawl_results[crawler_id] = {
        "crawler_id": crawler_id,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "items_found": 0,
        "items_valid": 0,
        "items_saved": 0,
        "errors": [],
    }

    pipeline = _get_pipeline()
    asyncio.create_task(_run_and_store(crawler_id, pipeline))

    return {
        "crawler_id": crawler_id,
        "status": "running",
        "message": f"Crawler '{crawler_id}' started",
    }


async def _run_and_store(crawler_id: str, pipeline: CrawlPipeline):
    """백그라운드: 크롤러 실행 → 파이프라인 → DB Admin 대기열 제출 → 이력 기록."""
    try:
        result = await pipeline.run_crawler(crawler_id)
        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": result.status,
            "items_found": result.items_found,
            "items_valid": result.items_valid,
            "items_saved": result.items_saved,
            "duration": result.duration,
            "errors": result.errors,
            "finished_at": datetime.now().isoformat(),
        }
        _append_run_history(crawler_id, result.status, result.duration)
        logger.info(
            f"Crawler '{crawler_id}' completed: {result.status} "
            f"(found={result.items_found}, saved={result.items_saved})"
        )
    except Exception as e:
        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": "failed",
            "error": str(e),
            "finished_at": datetime.now().isoformat(),
            "errors": [str(e)],
        }
        _append_run_history(crawler_id, "failed")
        logger.error(f"Crawler '{crawler_id}' failed: {e}", exc_info=True)


@router.get("/{crawler_id}/status/stream")
async def stream_crawler_status(crawler_id: str, request: Request):
    """SSE 스트림: 크롤러 실행 상태를 실시간 push — 폴링 대비 지연·트래픽 대폭 감소."""
    reg = _get_registry()
    try:
        reg.get_crawler(crawler_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found")

    async def event_generator():
        last_hash = None
        while True:
            if await request.is_disconnected():
                break

            result = _crawl_results.get(crawler_id, {
                "crawler_id": crawler_id,
                "status": "idle",
            })

            current_json = json.dumps(result, sort_keys=True, default=str)
            current_hash = hashlib.md5(current_json.encode()).hexdigest()

            # 상태 변경 시에만 이벤트 전송
            if current_hash != last_hash:
                last_hash = current_hash
                yield f"data: {current_json}\n\n"

            # 완료 상태면 스트림 종료
            if result.get("status") in ("success", "failed"):
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
