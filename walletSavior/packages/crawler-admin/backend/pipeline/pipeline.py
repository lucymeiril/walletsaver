"""크롤 파이프라인 — 크롤→파싱→검증→변환→저장 전체 흐름 관리."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from core.events import EventBus, CRAWL_STARTED, CRAWL_COMPLETED, CRAWL_FAILED
from core.models import CrawlResult, CrawlStatus, Event
from crawlers.registry.registry import CrawlerRegistry
from pipeline.validator import (
    validate_items,
    validate_price_range,
    deduplicate,
    normalize_prices,
)
from pipeline.transformer import (
    to_discount_history,
    to_hotdeal_prices,
    enrich_with_category,
)

logger = logging.getLogger(__name__)

# DB-Admin API endpoint (configurable)
DB_ADMIN_API_URL = "http://localhost:8001/api/prices/bulk"

# 대기열(Pending Ingestion) 설정
INGESTION_API_URL = os.getenv(
    "INGESTION_API_URL", "http://localhost:8002/api/ingestions"
)
SKIP_REVIEW = os.getenv("SKIP_REVIEW", "").lower() == "true"


class PipelineResult:
    """단일 크롤러 파이프라인 실행 결과."""

    def __init__(
        self,
        crawler_name: str,
        status: str = "success",
        items_found: int = 0,
        items_valid: int = 0,
        items_saved: int = 0,
        duration: float = 0.0,
        errors: list[str] | None = None,
    ):
        self.crawler_name = crawler_name
        self.status = status
        self.items_found = items_found
        self.items_valid = items_valid
        self.items_saved = items_saved
        self.duration = duration
        self.errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "crawler_name": self.crawler_name,
            "status": self.status,
            "items_found": self.items_found,
            "items_valid": self.items_valid,
            "items_saved": self.items_saved,
            "duration": round(self.duration, 2),
            "errors": self.errors,
        }


class CrawlPipeline:
    """크롤→파싱→검증→변환→저장 전체 파이프라인."""

    def __init__(
        self,
        registry: CrawlerRegistry | None = None,
        event_bus: EventBus | None = None,
        db_api_url: str = DB_ADMIN_API_URL,
        default_retry_count: int = 3,
    ):
        self.registry = registry or CrawlerRegistry()
        self.event_bus = event_bus or EventBus()
        self.db_api_url = db_api_url
        self.default_retry_count = default_retry_count

    async def run_crawler(self, crawler_name: str) -> PipelineResult:
        """단일 크롤러를 파이프라인 전체 흐름으로 실행."""
        start = time.monotonic()
        errors: list[str] = []

        await self.event_bus.publish(Event(
            event_type=CRAWL_STARTED,
            data={"crawler_name": crawler_name},
            source="pipeline",
        ))

        # 1. Crawl — 크롤러 인스턴스화 및 실행
        try:
            crawler = self.registry.get_crawler(crawler_name)
        except (KeyError, ImportError) as exc:
            return self._fail(crawler_name, str(exc), start)

        config = self.registry._registry.get(crawler_name, {}).get("config", {})
        # schedule은 cron 문자열일 수 있으므로 dict인 경우만 .get() 사용
        schedule_conf = config.get("schedule", {})
        if isinstance(schedule_conf, dict):
            retry_count = schedule_conf.get(
                "retry_count", self.default_retry_count
            )
        else:
            retry_count = self.default_retry_count

        crawl_result: CrawlResult | None = None
        for attempt in range(1, retry_count + 1):
            try:
                crawl_result = await crawler.crawl()
                if crawl_result.status == CrawlStatus.SUCCESS:
                    break
                errors.append(
                    f"attempt {attempt}: status={crawl_result.status.value}"
                )
            except Exception as exc:
                errors.append(f"attempt {attempt}: {exc}")
                if attempt < retry_count:
                    await asyncio.sleep(min(attempt * 2, 10))

        if crawl_result is None or crawl_result.status != CrawlStatus.SUCCESS:
            return self._fail(
                crawler_name,
                crawl_result.error_msg if crawl_result else "all retries failed",
                start,
                errors,
            )

        raw_items = crawl_result.items or []
        items_found = len(raw_items)
        if items_found == 0:
            return self._fail(crawler_name, "no items collected", start, errors)

        # 2. Parse — 이미 dict 리스트이므로 pass-through
        items = list(raw_items)

        # 3. Validate
        required = config.get("output", {}).get("required_fields", [])
        if required:
            items, invalid = validate_items(items, required)
            if invalid:
                errors.append(f"validation: {len(invalid)} items missing fields")
        items, price_invalid = validate_price_range(items)
        if price_invalid:
            errors.append(f"price_range: {len(price_invalid)} items out of range")
        items = normalize_prices(items)
        items = deduplicate(items, key_fields=["name", "price"])
        items = enrich_with_category(items)

        items_valid = len(items)

        # 4. Transform
        model_type = config.get("output", {}).get("model", "DiscountItem")
        if model_type == "HotdealPost":
            records = to_hotdeal_prices(items, source="hotdeal")
        else:
            records = to_discount_history(items, source="mart_discount")

        # 5. Store — 대기열 또는 직접 DB 저장
        if SKIP_REVIEW:
            items_saved = await self._store(records, errors)
        else:
            items_saved = await self._store_to_ingestion(
                crawler_name=crawler_name,
                crawl_status="success",
                items=items,
                schema_type=model_type,
                strategy_used=crawl_result.strategy_used,
                duration_seconds=time.monotonic() - start,
                errors=errors,
            )

        duration = time.monotonic() - start
        result = PipelineResult(
            crawler_name=crawler_name,
            status="success",
            items_found=items_found,
            items_valid=items_valid,
            items_saved=items_saved,
            duration=duration,
            errors=errors,
        )

        await self.event_bus.publish(Event(
            event_type=CRAWL_COMPLETED,
            data=result.to_dict(),
            source="pipeline",
        ))

        logger.info(
            f"[Pipeline] {crawler_name}: "
            f"found={items_found} valid={items_valid} saved={items_saved} "
            f"duration={duration:.2f}s"
        )
        return result

    async def run_all(
        self, category: Optional[str] = None
    ) -> list[PipelineResult]:
        """등록된 모든(또는 카테고리 필터) 크롤러 동시 실행."""
        crawlers = self.registry.list_crawlers()
        if category:
            crawlers = [c for c in crawlers if c["category"] == category]
        names = [c["name"] for c in crawlers]
        return await self.run_batch(names)

    async def run_batch(self, crawler_names: list[str]) -> list[PipelineResult]:
        """지정된 크롤러들을 동시 실행."""
        tasks = [self.run_crawler(name) for name in crawler_names]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    # --- internal helpers ---

    async def _store(
        self, records: list[dict[str, Any]], errors: list[str]
    ) -> int:
        """DB-Admin API 로 레코드 전송. 실패 시 0 반환."""
        if not records:
            return 0
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.db_api_url, json=records)
                resp.raise_for_status()
                return len(records)
        except Exception as exc:
            errors.append(f"store: {exc}")
            logger.warning(f"[Pipeline] store failed: {exc}")
            return 0

    async def _store_to_ingestion(
        self,
        crawler_name: str,
        crawl_status: str,
        items: list[dict[str, Any]],
        schema_type: str,
        strategy_used: str | None,
        duration_seconds: float,
        errors: list[str],
    ) -> int:
        """대기열(Pending Ingestion)에 크롤 결과 제출."""
        if not items:
            return 0
        payload = {
            "crawler_name": crawler_name,
            "crawl_status": crawl_status,
            "items": items,
            "schema_type": schema_type,
            "strategy_used": strategy_used,
            "duration_seconds": round(duration_seconds, 2),
            "errors": [{"message": e} for e in errors],
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(INGESTION_API_URL, json=payload)
                resp.raise_for_status()
                return len(items)
        except Exception as exc:
            errors.append(f"ingestion_submit: {exc}")
            logger.warning(f"[Pipeline] ingestion submit failed: {exc}")
            return 0

    def _fail(
        self,
        crawler_name: str,
        msg: str,
        start: float,
        errors: list[str] | None = None,
    ) -> PipelineResult:
        errs = list(errors or [])
        errs.append(msg)
        duration = time.monotonic() - start

        asyncio.ensure_future(self.event_bus.publish(Event(
            event_type=CRAWL_FAILED,
            data={"crawler_name": crawler_name, "error": msg},
            source="pipeline",
        )))

        return PipelineResult(
            crawler_name=crawler_name,
            status="failed",
            duration=duration,
            errors=errs,
        )
