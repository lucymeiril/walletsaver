"""크롤러 관리 라우트."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry
from pipeline.pipeline import CrawlPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

_registry: CrawlerRegistry | None = None
_pipeline: CrawlPipeline | None = None
_crawl_results: dict[str, dict[str, Any]] = {}


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
    """등록된 크롤러 목록."""
    reg = _get_registry()
    return {"crawlers": reg.list_crawlers()}


@router.get("/{crawler_id}/status")
async def get_crawler_status(crawler_id: str):
    """크롤러 상태 조회."""
    reg = _get_registry()
    try:
        reg.get_crawler(crawler_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found")

    result = _crawl_results.get(crawler_id)
    if result:
        return result
    return {
        "crawler_id": crawler_id,
        "status": "idle",
        "last_run": None,
    }


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
    """백그라운드: 크롤러 실행 → 파이프라인 → DB Admin 대기열 제출."""
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
        logger.error(f"Crawler '{crawler_id}' failed: {e}", exc_info=True)
