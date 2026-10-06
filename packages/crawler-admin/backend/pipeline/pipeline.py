"""Crawler pipeline: collect, validate, match, and submit current data."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Optional

import httpx

from audit import AuditEventType, audit_log
from core.events import CRAWL_COMPLETED, CRAWL_FAILED, CRAWL_STARTED, EventBus
from core.models import CrawlResult, CrawlStatus, Event
from crawlers.registry.registry import CrawlerRegistry
from pipeline.db_admin_auth import get_db_admin_auth
from pipeline.quality import summarize_discount_run
from pipeline.transformer import (
    enrich_with_category,
    to_discount_history,
    to_hotdeal_prices,
)
from pipeline.validator import (
    deduplicate,
    normalize_prices,
    validate_items,
    validate_price_range,
)
from services.matching_enrichment import enrich_items_with_matching_entries

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict[str, Any]], Any]
NON_RETRYABLE_CRAWL_HTTP_STATUSES = frozenset({400, 401, 403, 404, 429})

DB_ADMIN_API_URL = os.getenv(
    "DB_ADMIN_API_URL",
    "http://localhost:8002/api/prices/bulk",
)
INGESTION_API_URL = os.getenv(
    "INGESTION_API_URL",
    "http://localhost:8002/api/ingestions",
)
SKIP_REVIEW = os.getenv("SKIP_REVIEW", "").lower() == "true"


class PipelineResult:
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
    ) -> None:
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
    """Ingestion-capable pipeline used by the current four mart crawlers."""

    def __init__(
        self,
        registry: CrawlerRegistry | None = None,
        event_bus: EventBus | None = None,
        db_api_url: str = DB_ADMIN_API_URL,
        default_retry_count: int = 3,
    ) -> None:
        self.registry = registry or CrawlerRegistry()
        self.event_bus = event_bus or EventBus()
        self.db_api_url = db_api_url
        self.default_retry_count = default_retry_count

    async def run_crawler(
        self,
        crawler_name: str,
        progress_callback: ProgressCallback | None = None,
        crawl_method: str = "crawl",
    ) -> PipelineResult:
        start = time.monotonic()
        errors: list[str] = []
        await self._emit_progress(
            progress_callback,
            stage="started",
            items_found=0,
            items_valid=0,
            items_saved=0,
        )
        await self.event_bus.publish(
            Event(
                event_type=CRAWL_STARTED,
                data={"crawler_name": crawler_name},
                source="pipeline",
            )
        )

        try:
            crawler = self.registry.get_crawler(crawler_name)
        except (KeyError, ImportError) as exc:
            await self._emit_progress(
                progress_callback,
                stage="failed",
                errors=[str(exc)],
            )
            return self._fail(crawler_name, str(exc), start)

        try:
            setattr(crawler, "progress_callback", progress_callback)
        except Exception:
            logger.debug("[Pipeline] %s does not accept progress_callback", crawler_name)

        config = self.registry._registry.get(crawler_name, {}).get("config", {})
        schedule_conf = config.get("schedule", {})
        retry_count = (
            schedule_conf.get("retry_count", self.default_retry_count)
            if isinstance(schedule_conf, dict)
            else self.default_retry_count
        )

        crawl_result: CrawlResult | None = None
        for attempt in range(1, retry_count + 1):
            await self._emit_progress(
                progress_callback,
                stage="crawl_attempt",
                attempt=attempt,
                retry_count=retry_count,
            )
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
                # An offline fixture can exercise the parser, but cannot become
                # live collection evidence or trigger another provider attempt.
                if crawl_result.quality_details.get("fixture_fallback") is True:
                    break
                if crawl_result.status == CrawlStatus.PARTIAL:
                    errors.append(f"partial source collection: {crawl_result.error_msg or 'source run incomplete'}")
                    break  # Preserve these rows; do not repeat the whole supplier.
                if crawl_result.status == CrawlStatus.SUCCESS:
                    break
                errors.append(f"attempt {attempt}: status={crawl_result.status.value}")
                non_retryable_statuses = sorted(
                    {
                        failure.status_code
                        for failure in crawl_result.errors
                        if failure.status_code in NON_RETRYABLE_CRAWL_HTTP_STATUSES
                    }
                )
                source_quality = crawl_result.quality_details
                access_stop = ((source_quality.get("fetch") or {}).get("source_distribution") or {}).get("access_stop") or {}
                if access_stop.get("http_status") in {401, 403, 429}:
                    non_retryable_statuses.append(access_stop["http_status"])
                    non_retryable_statuses = sorted(set(non_retryable_statuses))
                if source_quality.get("source_stopped") is True and not non_retryable_statuses:
                    errors.append("not retrying explicit source-run stop")
                    break
                if non_retryable_statuses:
                    errors.append(
                        "not retrying non-retryable HTTP status: "
                        + ", ".join(str(status) for status in non_retryable_statuses)
                    )
                    logger.warning(
                        "[Pipeline] %s: stopping crawl retries after HTTP %s",
                        crawler_name,
                        ", ".join(str(status) for status in non_retryable_statuses),
                    )
                    break
            except Exception as exc:
                errors.append(f"attempt {attempt}: {exc}")
                await self._emit_progress(
                    progress_callback,
                    stage="crawl_error",
                    attempt=attempt,
                    errors=list(errors),
                )
                if attempt < retry_count:
                    await asyncio.sleep(min(attempt * 2, 10))

        if crawl_result is not None and crawl_result.quality_details.get("fixture_fallback") is True:
            reason = "fixture_fallback_not_live"
            message = "Offline fixture fallback is not live source collection; no rows were validated or submitted."
            next_action = "Keep fixture input for offline parser checks; require genuine source evidence before live submission."
            errors.append(message)
            quality_details = {
                "fixture_fallback": True,
                "fixture_items_count": len(crawl_result.items),
                "strategy_used": crawl_result.strategy_used,
                "source_quality_details": crawl_result.quality_details,
                "alerts": [reason],
                "zero_result_diagnostic": {
                    "stage": reason,
                    "message": message,
                    "next_action": next_action,
                    # The real source's row count is unknown; fixture rows are
                    # neither parsed live rows nor validation failures.
                    "counts": {"source_raw": None, "parsed": 0, "valid": 0, "invalid_or_dropped": 0},
                },
                "operator_diagnostics": [{"code": reason, "severity": "error", "message": message, "next_action": next_action}],
                "next_actions": [next_action],
                "quality_summary": {"status": "failing", "registered_vs_collecting": "failing"},
            }
            result = PipelineResult(
                crawler_name=crawler_name,
                status="failed",
                duration=time.monotonic() - start,
                errors=errors,
                quality_score=0,
                quality_details=quality_details,
            )
            await self._emit_progress(
                progress_callback, stage="failed", items_found=0, items_valid=0,
                items_saved=0, errors=list(errors), quality_details=quality_details,
            )
            await self.event_bus.publish(Event(
                event_type=CRAWL_FAILED,
                data={**result.to_dict(), "error": message},
                source="pipeline",
            ))
            return result

        if crawl_result is None or crawl_result.status not in {CrawlStatus.SUCCESS, CrawlStatus.PARTIAL}:
            await self._emit_progress(
                progress_callback,
                stage="failed",
                errors=list(errors),
            )
            return self._fail(
                crawler_name,
                crawl_result.error_msg if crawl_result else "all retries failed",
                start,
                errors,
                quality_details={"source_collection": {"status": crawl_result.status.value},
                                 "source_quality_details": crawl_result.quality_details} if crawl_result else None,
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
            errors.append("no items collected")

        items = [dict(item) for item in raw_items]
        for item in items:
            if item.get("valid_to") in (None, "") and item.get("valid_until") not in (None, ""):
                item["valid_to"] = item["valid_until"]

        output_conf = config.get("output", {})
        model_type = output_conf.get("model", "DiscountItem")
        price_field = (
            "price"
            if model_type == "HotdealPost"
            or not any("sale_price" in item for item in items)
            else "sale_price"
        )

        required_fields = output_conf.get("required_fields", [])
        items, invalid = validate_items(items, required_fields)
        if invalid:
            errors.append(f"validation: {len(invalid)} items missing or invalid fields")

        # A mixed raw batch may contain both legacy price and sale_price rows.
        # Never ignore a row's actual quote because another row uses a different field.
        price_valid, price_invalid = [], []
        for item in items:
            row_price_field = "price" if model_type == "HotdealPost" or "sale_price" not in item else "sale_price"
            normalize_prices([item], price_field=row_price_field)
            valid_rows, invalid_rows = validate_price_range([item], price_field=row_price_field)
            price_valid.extend(valid_rows)
            price_invalid.extend(invalid_rows)
        items = price_valid
        if price_invalid:
            errors.append(f"price_range: {len(price_invalid)} items out of range")

        dedup_fields = (
            ["title", "price"]
            if model_type == "HotdealPost"
            else ["name", price_field]
        )
        dedup_before = len(items)
        items = deduplicate(items, key_fields=dedup_fields)
        deduplicated_count = dedup_before - len(items)
        if model_type != "HotdealPost":
            items = enrich_with_category(items)

        # The persistent matching table is the current automatic knowledge base.
        # Hits receive canonical product/category metadata; misses remain explicit
        # so the raw-batch export can send only unresolved rows to external AI.
        if items and model_type != "HotdealPost":
            items = enrich_items_with_matching_entries(items)
        matching_hits = sum(
            1 for item in items if item.get("matching_status") == "hit"
        )
        matching_misses = sum(
            1 for item in items if item.get("matching_status") == "miss"
        )

        items_valid = len(items)
        await self._emit_progress(
            progress_callback,
            stage="validated",
            items_found=items_found,
            items_valid=items_valid,
            errors=list(errors),
        )

        quality_details = summarize_discount_run(
            items,
            raw_count=items_found,
            invalid_count=len(invalid) + len(price_invalid),
            errors=errors,
            strategy_used=crawl_result.strategy_used,
            fallback_used="fallback" in (crawl_result.strategy_used or "").lower(),
        )
        quality_details = {
            **quality_details,
            "source_collection": {"status": crawl_result.status.value,
                                  "error": crawl_result.error_msg},
            "source_quality_details": crawl_result.quality_details,
            "deduplicated_count": deduplicated_count,
            "matching": {
                "hits": matching_hits,
                "misses": matching_misses,
            },
        }

        # Mart observations require the source/spec/condition-aware review
        # contract; the legacy bulk writer cannot represent those facts.
        direct_store = SKIP_REVIEW and model_type not in {"DiscountItem", "HotdealPost"}
        items_saved = 0
        if items_valid == 0:
            if items_found:
                errors.append("validation rejected all collected items")
        else:
            await self._emit_progress(
                progress_callback,
                stage="storing",
                items_found=items_found,
                items_valid=items_valid,
                items_saved=0,
            )
            if direct_store:
                records = (
                    to_hotdeal_prices(items, source="hotdeal")
                    if model_type == "HotdealPost"
                    else to_discount_history(items, source="mart_discount")
                )
                items_saved = await self._store(records, errors)
            else:
                items_saved = await self._store_to_ingestion(
                    crawler_name=crawler_name,
                    crawl_status=crawl_result.status.value,
                    items=items,
                    schema_type=model_type,
                    strategy_used=crawl_result.strategy_used,
                    duration_seconds=time.monotonic() - start,
                    errors=errors,
                    quality_score=quality_details["score"],
                    quality_details=quality_details,
                )

        final_status = (
            "failed" if items_valid == 0 or items_saved == 0
            else "partial_failure" if items_saved < items_valid or crawl_result.status == CrawlStatus.PARTIAL
            else "success"
        )
        quality_details["delivery"] = {
            "target": "direct_store" if direct_store else "pending_review",
            "status": final_status,
            "attempted": items_valid,
            "acknowledged": items_saved,
        }
        if crawl_result.status == CrawlStatus.PARTIAL:
            quality_details["alerts"].append("source_collection_partial")
            quality_details["quality_summary"]["status"] = "failing" if final_status == "failed" else "warning"
            quality_details["quality_summary"]["registered_vs_collecting"] = quality_details["quality_summary"]["status"]
        if items_valid and items_saved < items_valid:
            message = f"storage acknowledged {items_saved} of {items_valid} valid items"
            errors.append(message)
            quality_details["alerts"].append("zero_items_saved" if items_saved == 0 else "partial_items_saved")
            quality_details["operator_diagnostics"].append({
                "code": "storage_no_acknowledged_items" if items_saved == 0 else "storage_partial_acknowledgement",
                "severity": "error" if items_saved == 0 else "warning",
                "message": message,
                "next_action": "Inspect storage acknowledgement and errors before resubmitting; collection is distinct from storage.",
            })
            quality_details["quality_summary"]["status"] = "failing" if items_saved == 0 else "warning"
            quality_details["quality_summary"]["registered_vs_collecting"] = quality_details["quality_summary"]["status"]
            quality_details["quality_summary"]["diagnostic_count"] = len(quality_details["operator_diagnostics"])
            storage_action = quality_details["operator_diagnostics"][-1]["next_action"]
            quality_details["next_actions"].append(storage_action)
            quality_details["quality_summary"]["next_actions"] = quality_details["next_actions"]

        duration = time.monotonic() - start
        await self._emit_progress(
            progress_callback,
            stage="stored" if final_status == "success" else final_status,
            items_found=items_found,
            items_valid=items_valid,
            items_saved=items_saved,
            errors=list(errors),
        )

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
        event_data = result.to_dict()
        if final_status == "failed":
            event_data["error"] = errors[-1]
        await self.event_bus.publish(
            Event(
                event_type=CRAWL_FAILED if final_status == "failed" else CRAWL_COMPLETED,
                data=event_data,
                source="pipeline",
            )
        )
        logger.info(
            "[Pipeline] %s: found=%d valid=%d saved=%d duration=%.2fs",
            crawler_name,
            items_found,
            items_valid,
            items_saved,
            duration,
        )
        return result

    async def run_all(self, category: Optional[str] = None) -> list[PipelineResult]:
        crawlers = self.registry.list_crawlers()
        if category:
            crawlers = [row for row in crawlers if row["category"] == category]
        return await self.run_batch([row["name"] for row in crawlers])

    async def run_batch(self, crawler_names: list[str]) -> list[PipelineResult]:
        raw_results = await asyncio.gather(
            *(self.run_crawler(name) for name in crawler_names),
            return_exceptions=True,
        )
        results: list[PipelineResult] = []
        for name, value in zip(crawler_names, raw_results):
            if isinstance(value, PipelineResult):
                results.append(value)
            elif isinstance(value, BaseException):
                logger.error("[Pipeline] batch: %s raised %s", name, value)
                results.append(
                    PipelineResult(
                        crawler_name=name,
                        status="failed",
                        errors=[f"unhandled: {value}"],
                    )
                )
        return results

    async def _emit_progress(
        self,
        callback: ProgressCallback | None,
        **payload: Any,
    ) -> None:
        if callback is None:
            return
        try:
            result = callback(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.debug("[Pipeline] progress callback failed", exc_info=True)

    async def _store(
        self,
        records: list[dict[str, Any]],
        errors: list[str],
        *,
        _max_retries: int = 3,
    ) -> int:
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
                    response = await client.post(
                        self.db_api_url,
                        json=records,
                        headers=headers,
                    )
                    if response.status_code == 401:
                        headers = await auth.handle_401()
                        response = await client.post(
                            self.db_api_url,
                            json=records,
                            headers=headers,
                        )
                    response.raise_for_status()
                    saved = response.json().get("saved")
                    if type(saved) is not int or not 0 <= saved <= len(records):
                        raise ValueError("invalid direct-store saved acknowledgement; reconcile before retry")
                    return saved
            except (ValueError, AttributeError) as exc:
                # HTTP succeeded: an ambiguous acknowledgement must not trigger additive retries.
                last_exc = exc
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500:
                    break
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())

        error_message = str(last_exc) if last_exc else "unknown"
        errors.append(f"store: {error_message}")
        logger.warning(
            "[Pipeline] direct store failed after %d retries: %s",
            _max_retries,
            error_message,
        )
        write_dead_letter(
            records,
            target="db_admin",
            error_msg=error_message,
        )
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
        import random
        import uuid
        from pipeline.dead_letter import write_dead_letter

        if not items:
            return 0

        chunk_size = 100
        total_saved = 0
        auth = get_db_admin_auth()
        ingestion_run_id = str(
            (quality_details or {}).get("ingestion_run_id") or uuid.uuid4().hex
        )

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
                "errors": [{"message": error} for error in errors],
                "quality_score": quality_score,
                "quality_details": {
                    **(quality_details or {}),
                    "ingestion_run_id": ingestion_run_id,
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
                        response = await client.post(
                            INGESTION_API_URL,
                            json=payload,
                            headers=headers,
                        )
                        if response.status_code == 401:
                            headers = await auth.handle_401()
                            response = await client.post(
                                INGESTION_API_URL,
                                json=payload,
                                headers=headers,
                            )
                        response.raise_for_status()
                        acknowledgement = response.json()
                        ids = acknowledgement.get("ids") or [acknowledgement.get("id")]
                        if acknowledgement.get("status") != "pending" or not all(type(value) is int and value > 0 for value in ids):
                            raise ValueError("invalid pending-review acknowledgement; reconcile before retry")
                        accepted = acknowledgement.get("total_items", len(chunk))
                        if type(accepted) is not int or not 0 <= accepted <= len(chunk):
                            raise ValueError("invalid pending-review item count; reconcile before retry")
                        if "items_per_chunk" in acknowledgement:
                            counts = acknowledgement["items_per_chunk"]
                            if not isinstance(counts, list) or len(counts) != len(ids) or not all(type(value) is int and value > 0 for value in counts) or sum(counts) != accepted:
                                raise ValueError("inconsistent pending-review chunk acknowledgement; reconcile before retry")
                        total_saved += accepted
                        chunk_saved = True
                        last_exc = None
                        audit_log(
                            AuditEventType.DATA_SUBMISSION,
                            resource=crawler_name,
                            detail={
                                "item_count": accepted,
                                "schema_type": schema_type,
                                "strategy": strategy_used,
                                "chunk_index": chunk_index,
                            },
                        )
                        break
                except (ValueError, AttributeError) as exc:
                    last_exc = exc
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

            if not chunk_saved and last_exc is not None:
                error_message = str(last_exc)
                errors.append(
                    f"ingestion_submit chunk {chunk_index}: {error_message}"
                )
                logger.warning(
                    "[Pipeline] ingestion chunk %d failed after %d retries: %s",
                    chunk_index,
                    _max_retries,
                    error_message,
                )
                write_dead_letter(
                    chunk,
                    crawler_name=crawler_name,
                    target="ingestion",
                    error_msg=error_message,
                )

            if offset + chunk_size < len(items):
                await asyncio.sleep(3)

        return total_saved

    def _fail(
        self,
        crawler_name: str,
        message: str,
        start: float,
        errors: list[str] | None = None,
        quality_details: dict | None = None,
    ) -> PipelineResult:
        all_errors = list(errors or [])
        all_errors.append(message)
        duration = time.monotonic() - start
        asyncio.ensure_future(
            self.event_bus.publish(
                Event(
                    event_type=CRAWL_FAILED,
                    data={"crawler_name": crawler_name, "error": message, "quality_details": quality_details or {}},
                    source="pipeline",
                )
            )
        )
        return PipelineResult(
            crawler_name=crawler_name,
            status="failed",
            duration=duration,
            errors=all_errors,
            quality_details=quality_details,
        )
