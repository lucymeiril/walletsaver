"""크롤러 관리 라우트."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

_registry: CrawlerRegistry | None = None


def _get_registry() -> CrawlerRegistry:
    global _registry
    if _registry is None:
        crawlers_dir = Path(__file__).resolve().parent.parent.parent / "crawlers"
        _registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
        _registry.discover()
    return _registry


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
    return {
        "crawler_id": crawler_id,
        "status": "idle",
        "last_run": None,
    }


@router.post("/{crawler_id}/run")
async def run_crawler(crawler_id: str):
    """크롤러 즉시 실행."""
    reg = _get_registry()
    try:
        reg.get_crawler(crawler_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Crawler '{crawler_id}' not found")
    return {
        "crawler_id": crawler_id,
        "status": "queued",
        "message": f"Crawler '{crawler_id}' queued for execution",
    }
