"""크롤 파이프라인 — 크롤→파싱→검증→변환→저장 전체 흐름 관리."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

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
from pipeline.quality import summarize_discount_run
from pipeline.diagnostics import run_bounded_crawler_diagnostics
from pipeline.transformer import (
    to_discount_history,
    to_hotdeal_prices,
    enrich_with_category,
)
from audit import audit_log, AuditEventType
from pipeline.db_admin_auth import get_db_admin_auth
from pipeline.source_runs import SourceRunPipeline, SourceRunResult, SourceRunStore

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], Any]

# DB-Admin API endpoint (port 8002, configurable via env)
DB_ADMIN_API_URL = os.getenv(
    "DB_ADMIN_API_URL", "http://localhost:8002/api/prices/bulk"
)

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
        quality_score: float | None = None,
        quality_details: dict[str, Any] | None = None,
    ):
        self.crawler_name = crawler_name
        self.status = status
        self.items_found = items_found
        self.items_valid = items_valid
        self.items_saved = items_saved
        self.duration = duration
        self.errors = errors or []
        self.quality_score = quality_score
        self.quality_details = quality_details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "crawler_name": self.crawler_name,
            "status": self.status,
            "items_found": self.items_found,
            "items_valid": self.items_valid,
            "items_saved": self.items_saved,
            "duration": round(self.duration, 2),
            "errors": self.errors,
            "quality_score": self.quality_score,
            "quality_details": self.quality_details,
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
        self.source_runs = SourceRunPipeline(
            self.registry,
            store=SourceRunStore(),
            retry_count=default_retry_count,
        )

    async def run_source_incremental(
        self,
        crawler_name: str,
        *,
        source_name: str | None = None,
        schema_type: str = "source_raw",
        source_url: str | None = None,
        force_full: bool = False,
    ) -> SourceRunResult:
        """Run crawler incrementally and write AI handoff artifacts without DB mutation."""
        return await self.source_runs.run_source_incremental(
            crawler_name,
            source_name=source_name,
            schema_type=schema_type,
            source_url=source_url,
            force_full=force_full,
        )

    async def run_crawler(
        self,
        crawler_name: str,
        progress_callback: ProgressCallback | None = None,
        crawl_method: str = "crawl",
    ) -> PipelineResult:
        """단일 크롤러를 파이프라인 전체 흐름으로 실행."""
        start = time.monotonic()
        errors: list[str] = []
        await self._emit_progress(progress_callback, stage="started", items_found=0, items_valid=0, items_saved=0)

        await self.event_bus.publish(Event(
            event_type=CRAWL_STARTED,
            data={"crawler_name": crawler_name},
            source="pipeline",
        ))

        # 1. Crawl — 크롤러 인스턴스화 및 실행
        try:
            crawler = self.registry.get_crawler(crawler_name)
        except (KeyError, ImportError) as exc:
            await self._emit_progress(progress_callback, stage="failed", errors=[str(exc)])
            return self._fail(crawler_name, str(exc), start)

        try:
            setattr(crawler, "progress_callback", progress_callback)
        except Exception:
            logger.debug("[Pipeline] %s crawler does not accept progress_callback", crawler_name)

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
            await self._emit_progress(progress_callback, stage="crawl_attempt", attempt=attempt, retry_count=retry_count)
            try:
                method = getattr(crawler, crawl_method, None)
                if not callable(method):
                    raise AttributeError(f"{crawler_name} does not support {crawl_method}")
                crawl_result = await method()
                await self._emit_progress(
                    progress_callback,
                    stage="crawl_finished",
                    attempt=attempt,
                    crawler_status=str(crawl_result.status.value),
                    items_found=crawl_result.items_count,
                    strategy_used=crawl_result.strategy_used,
                    quality_details=crawl_result.quality_details,
                )
                if crawl_result.status == CrawlStatus.SUCCESS:
                    break
                errors.append(
                    f"attempt {attempt}: status={crawl_result.status.value}"
                )
            except Exception as exc:
                errors.append(f"attempt {attempt}: {exc}")
                await self._emit_progress(progress_callback, stage="crawl_error", attempt=attempt, errors=list(errors))
                if attempt < retry_count:
                    await asyncio.sleep(min(attempt * 2, 10))

        if crawl_result is None or crawl_result.status != CrawlStatus.SUCCESS:
            await self._emit_progress(progress_callback, stage="failed", errors=list(errors))
            return self._fail(
                crawler_name,
                crawl_result.error_msg if crawl_result else "all retries failed",
                start,
                errors,
            )

        raw_items = crawl_result.items or []
        items_found = len(raw_items)
        await self._emit_progress(
            progress_callback,
            stage="items_collected",
            items_found=items_found,
            strategy_used=crawl_result.strategy_used,
            quality_details=crawl_result.quality_details,
        )
        if items_found == 0:
            await self._emit_progress(progress_callback, stage="failed", items_found=0, errors=[*errors, "no items collected"])
            return self._fail(crawler_name, "no items collected", start, errors)

        # 2. Parse — 이미 dict 리스트이므로 pass-through
        items = list(raw_items)

        # Sanitize raw items before they enter the pipeline
        for item in items:
            for key, val in list(item.items()):
                if isinstance(val, str) and len(val) > 5000:
                    item[key] = val[:5000]

        # 3. Validate
        model_type = config.get("output", {}).get("model", "DiscountItem")
        price_field = (
            "price"
            if model_type == "HotdealPost" or not any("sale_price" in item for item in items)
            else "sale_price"
        )
        required = config.get("output", {}).get("required_fields", [])
        if required:
            items, invalid = validate_items(items, required)
            if invalid:
                errors.append(f"validation: {len(invalid)} items missing fields")
        items = normalize_prices(items, price_field=price_field)
        items, price_invalid = validate_price_range(items, price_field=price_field)
        if price_invalid:
            errors.append(f"price_range: {len(price_invalid)} items out of range")
        dedup_fields = ["title", "price"] if model_type == "HotdealPost" else ["name", price_field]
        dedup_before = len(items)
        items = deduplicate(items, key_fields=dedup_fields)
        items = enrich_with_category(items)

        items_valid = len(items)
        await self._emit_progress(progress_callback, stage="validated", items_found=items_found, items_valid=items_valid, errors=list(errors))
        quality_details = summarize_discount_run(
            items,
            raw_count=items_found,
            invalid_count=max(0, items_found - len(items)),
            errors=errors,
            strategy_used=crawl_result.strategy_used,
            fallback_used="fallback" in (crawl_result.strategy_used or "").lower(),
        )
        quality_details = {
            **quality_details,
            "deduplicated_count": max(0, dedup_before - items_valid),
        }

        # 4. Transform
        if model_type == "HotdealPost":
            records = to_hotdeal_prices(items, source="hotdeal")
        else:
            records = to_discount_history(items, source="mart_discount")

        # 5. Store — 대기열 또는 직접 DB 저장
        await self._emit_progress(progress_callback, stage="storing", items_found=items_found, items_valid=items_valid, items_saved=0)
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
                quality_score=quality_details["score"],
                quality_details=quality_details,
            )

        duration = time.monotonic() - start
        await self._emit_progress(
            progress_callback,
            stage="stored",
            items_found=items_found,
            items_valid=items_valid,
            items_saved=items_saved,
            errors=list(errors),
        )

        # Determine status based on actual persistence outcome
        if items_saved == 0 and items_valid > 0:
            final_status = "partial_failure"
        elif 0 < items_saved < items_valid:
            final_status = "partial_failure"
        else:
            final_status = "success"

        result = PipelineResult(
            crawler_name=crawler_name,
            status=final_status,
            items_found=items_found,
            items_valid=items_valid,
            items_saved=items_saved,
            duration=duration,
            errors=errors,
            quality_score=quality_details["score"],
            quality_details=quality_details,
        )

        await self.event_bus.publish(Event(
            event_type=CRAWL_COMPLETED,
            data=result.to_dict(),
            source="pipeline",
        ))

        logger.info(
            "[Pipeline] %s: found=%d valid=%d saved=%d duration=%.2fs",
            crawler_name, items_found, items_valid, items_saved, duration,
            extra={
                "crawler_name": crawler_name,
                "items_found": items_found,
                "items_saved": items_saved,
                "duration": round(duration, 2),
                "status": final_status,
            },
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
        """지정된 크롤러들을 동시 실행. 개별 실패가 다른 크롤러에 영향을 주지 않는다."""
        tasks = [self.run_crawler(name) for name in crawler_names]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[PipelineResult] = []
        for name, r in zip(crawler_names, raw_results):
            if isinstance(r, PipelineResult):
                results.append(r)
            elif isinstance(r, BaseException):
                logger.error("[Pipeline] batch: %s raised %s", name, r)
                results.append(PipelineResult(
                    crawler_name=name,
                    status="failed",
                    errors=[f"unhandled: {r}"],
                ))
        return results

    async def run_bounded_diagnostics(
        self,
        *,
        fixture_by_source: dict[str, str] | None = None,
        crawler_ids: list[str] | None = None,
        live_enabled: bool = False,
    ) -> dict[str, Any]:
        """Run safe fixture diagnostics without live network crawling by default."""
        return await run_bounded_crawler_diagnostics(
            self.registry,
            fixture_by_source=fixture_by_source,
            crawler_ids=crawler_ids,
            live_enabled=live_enabled,
        )

    # --- internal helpers ---

    async def _emit_progress(self, callback: ProgressCallback | None, **payload: Any) -> None:
        if callback is None:
            return
        try:
            result = callback(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.debug("[Pipeline] progress callback failed", exc_info=True)

    async def _store(
        self, records: list[dict[str, Any]], errors: list[str],
        *, _max_retries: int = 3,
    ) -> int:
        """DB-Admin API 로 레코드 전송. 재시도 후 실패 시 DLQ에 기록."""
        import random
        from pipeline.dead_letter import write_dead_letter

        if not records:
            return 0

        auth = get_db_admin_auth()
        last_exc: Exception | None = None
        for attempt in range(1, _max_retries + 1):
            try:
                headers = await auth.get_headers()
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        self.db_api_url, json=records, headers=headers,
                    )
                    if resp.status_code == 401:
                        headers = await auth.handle_401()
                        resp = await client.post(
                            self.db_api_url, json=records, headers=headers,
                        )
                    resp.raise_for_status()
                    return len(records)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500:
                    break  # client error — no retry
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())

        # All retries exhausted — write to DLQ
        err_msg = str(last_exc) if last_exc else "unknown"
        errors.append(f"store: {err_msg}")
        logger.warning("[Pipeline] store failed after %d retries: %s", _max_retries, err_msg)
        write_dead_letter(records, target="db_admin", error_msg=err_msg)
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
        quality_score: float | None = None,
        quality_details: dict[str, Any] | None = None,
        *,
        _max_retries: int = 3,
    ) -> int:
        """대기열(Pending Ingestion)에 크롤 결과 제출. 재시도 후 실패 시 DLQ에 기록."""
        import random
        from pipeline.dead_letter import write_dead_letter

        if not items:
            return 0

        chunk_size = 100
        total_saved = 0
        auth = get_db_admin_auth()

        for offset in range(0, len(items), chunk_size):
            chunk = items[offset : offset + chunk_size]
            chunk_index = (offset // chunk_size) + 1
            payload = {
                "crawler_name": crawler_name,
                "crawl_status": crawl_status,
                "items": chunk,
                "schema_type": schema_type,
                "strategy_used": strategy_used,
                "duration_seconds": round(duration_seconds, 2),
                "errors": [{"message": e} for e in errors],
                "quality_score": quality_score,
                "quality_details": {
                    **(quality_details or {}),
                    "ingestion_chunk": {
                        "index": chunk_index,
                        "offset": offset,
                        "size": len(chunk),
                        "total_items": len(items),
                    },
                },
            }

            last_exc: Exception | None = None
            chunk_saved = False
            for attempt in range(1, _max_retries + 1):
                try:
                    headers = await auth.get_headers()
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.post(
                            INGESTION_API_URL, json=payload, headers=headers,
                        )
                        if resp.status_code == 401:
                            headers = await auth.handle_401()
                            resp = await client.post(
                                INGESTION_API_URL, json=payload, headers=headers,
                            )
                        resp.raise_for_status()
                        total_saved += len(chunk)
                        chunk_saved = True
                        last_exc = None
                        audit_log(
                            AuditEventType.DATA_SUBMISSION,
                            resource=crawler_name,
                            detail={
                                "item_count": len(chunk),
                                "schema_type": schema_type,
                                "strategy": strategy_used,
                                "chunk_index": chunk_index,
                            },
                        )
                        break
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    if exc.response.status_code == 429 and attempt < _max_retries:
                        retry_after = exc.response.headers.get("Retry-After")
                        try:
                            wait = float(retry_after) if retry_after else 5.0 * attempt
                        except ValueError:
                            wait = 5.0 * attempt
                        await asyncio.sleep(wait + random.random())
                        continue
                    if exc.response.status_code < 500:
                        break
                    if attempt < _max_retries:
                        await asyncio.sleep(2 ** attempt + random.random())
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    if attempt < _max_retries:
                        await asyncio.sleep(2 ** attempt + random.random())
            else:
                pass

            if not chunk_saved and last_exc is not None:
                err_msg = str(last_exc)
                errors.append(f"ingestion_submit chunk {chunk_index}: {err_msg}")
                logger.warning(
                    "[Pipeline] ingestion chunk %d failed after %d retries: %s",
                    chunk_index,
                    _max_retries,
                    err_msg,
                )
                write_dead_letter(
                    chunk,
                    crawler_name=crawler_name,
                    target="ingestion",
                    error_msg=err_msg,
                )

            if offset + chunk_size < len(items):
                await asyncio.sleep(3)

        return total_saved

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
