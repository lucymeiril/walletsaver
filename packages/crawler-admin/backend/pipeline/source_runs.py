"""Incremental source runs for repeated crawler -> AI handoff without DB writes."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import CrawlStatus
from pipeline.ai_export import build_raw_batches
from pipeline.dead_letter import write_dead_letter


_VOLATILE_FIELDS = {
    "crawled_at",
    "created_at",
    "updated_at",
    "timestamp",
    "collected_at",
    "fetched_at",
}
_SOURCE_KEY_FIELDS = (
    "source_record_key",
    "external_id",
    "post_id",
    "product_id",
    "id",
    "sku",
)
_SOURCE_URL_FIELDS = ("source_url", "detail_url", "url", "link")
_TITLE_FIELDS = ("raw_title", "title", "name", "product_name", "normalized_name")
_PRICE_FIELDS = ("raw_price", "sale_price", "price", "current_price", "original_price")


@dataclass(frozen=True)
class SourceRunResult:
    crawler_name: str
    source_name: str
    status: str
    run_id: str
    items_found: int
    items_new: int
    items_changed: int
    items_skipped: int
    records_handed_off: int
    skipped_invalid: int
    since: str | None
    artifact_dir: str
    manifest_path: str
    ai_handoff_path: str
    dead_letter_path: str | None = None
    retry_attempts: list[dict[str, Any]] | None = None
    duration: float = 0.0
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "crawler_name": self.crawler_name,
            "source_name": self.source_name,
            "status": self.status,
            "run_id": self.run_id,
            "items_found": self.items_found,
            "items_new": self.items_new,
            "items_changed": self.items_changed,
            "items_skipped": self.items_skipped,
            "records_handed_off": self.records_handed_off,
            "skipped_invalid": self.skipped_invalid,
            "since": self.since,
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "ai_handoff_path": self.ai_handoff_path,
            "dead_letter_path": self.dead_letter_path,
            "retry_attempts": self.retry_attempts or [],
            "duration": round(self.duration, 2),
            "errors": self.errors or [],
        }


class SourceRunStore:
    """Small file-backed source-run state and artifact store."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        default_dir = Path(__file__).resolve().parent.parent / "data" / "source_runs"
        self.base_dir = Path(base_dir or os.getenv("SOURCE_RUN_DIR", str(default_dir)))

    def state_path(self, source_name: str) -> Path:
        return self.base_dir / "_state" / f"{_safe_name(source_name)}.json"

    def load_state(self, source_name: str) -> dict[str, Any]:
        path = self.state_path(source_name)
        if not path.exists():
            return {"source_name": source_name, "last_success": None, "items": {}}
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("items", {})
        return data

    def save_state(self, source_name: str, state: dict[str, Any]) -> Path:
        path = self.state_path(source_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, default=str)
        return path

    def artifact_dir(self, source_name: str, run_id: str) -> Path:
        return self.base_dir / _safe_name(source_name) / run_id


class SourceRunPipeline:
    """Run crawlers incrementally and materialize AI handoff artifacts."""

    def __init__(
        self,
        registry: Any,
        *,
        store: SourceRunStore | None = None,
        retry_count: int = 3,
    ) -> None:
        self.registry = registry
        self.store = store or SourceRunStore()
        self.retry_count = retry_count

    async def run_source_incremental(
        self,
        crawler_name: str,
        *,
        source_name: str | None = None,
        schema_type: str = "source_raw",
        source_url: str | None = None,
        source_input: str | None = None,
        source_input_label: str | None = None,
        force_full: bool = False,
    ) -> SourceRunResult:
        started = time.monotonic()
        source = source_name or crawler_name
        run_id = f"source-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        state = self.store.load_state(source)
        since = None if force_full else state.get("last_success")
        attempts: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            crawler = self.registry.get_crawler(crawler_name)
        except Exception as exc:
            return self._failed_result(crawler_name, source, run_id, since, started, attempts, [str(exc)])

        crawl_result = None
        for attempt in range(1, self.retry_count + 1):
            try:
                crawl_result = await _call_crawler(crawler, since=since, source_input=source_input)
                attempts.append({"attempt": attempt, "status": getattr(crawl_result.status, "value", crawl_result.status)})
                if crawl_result.status == CrawlStatus.SUCCESS:
                    break
                errors.append(crawl_result.error_msg or f"status={crawl_result.status}")
            except Exception as exc:
                attempts.append({"attempt": attempt, "status": "failed", "error": str(exc)})
                errors.append(str(exc))
                if attempt < self.retry_count:
                    await asyncio.sleep(min(attempt * 2, 10))

        if crawl_result is None or crawl_result.status != CrawlStatus.SUCCESS:
            msg = crawl_result.error_msg if crawl_result is not None else "all retries failed"
            return self._failed_result(crawler_name, source, run_id, since, started, attempts, [*errors, msg])

        raw_items = [_item_to_dict(item) for item in (crawl_result.items or [])]
        previous = state.get("items", {})
        selected: list[dict[str, Any]] = []
        item_states = dict(previous)
        counts = {"new": 0, "changed": 0, "skipped": 0}

        for item in raw_items:
            source_key = stable_source_key(source, item)
            fingerprint = source_fingerprint(item)
            enriched = dict(item)
            attrs = dict(enriched.get("attributes") or {})
            attrs.setdefault("source_record_key", source_key)
            enriched["attributes"] = attrs
            enriched.setdefault("source_record_key", source_key)

            old = previous.get(source_key)
            if not old:
                counts["new"] += 1
                selected.append(enriched)
            elif old.get("fingerprint") != fingerprint:
                counts["changed"] += 1
                selected.append(enriched)
            else:
                counts["skipped"] += 1

            item_states[source_key] = {
                "fingerprint": fingerprint,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }

        artifact_dir = self.store.artifact_dir(source, run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        ai_handoff_path = artifact_dir / "ai_handoff.json"
        manifest_path = artifact_dir / "manifest.json"
        raw_records_path = artifact_dir / "raw_records.jsonl"

        raw_artifact_uri = str(raw_records_path)
        batches, record_batches, skipped_invalid = build_raw_batches(
            selected,
            source_name=source,
            crawler_name=crawler_name,
            schema_type=schema_type,
            source_url=source_url,
            raw_artifact_uri=raw_artifact_uri,
            batch_id=run_id,
        )
        flat_records = [record for batch in record_batches for record in batch]

        with open(raw_records_path, "w", encoding="utf-8") as fh:
            for record in flat_records:
                fh.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, default=str) + "\n")

        source_input_manifest = _source_input_manifest(source_input, source_input_label)
        handoff = {
            "run_id": run_id,
            "source_name": source,
            "crawler_name": crawler_name,
            "schema_type": schema_type,
            "source_input": source_input_manifest,
            "collection_mode": "bounded_source_input_no_db" if source_input is not None else "crawler_default_no_db",
            "live_network_enabled": False if source_input is not None else None,
            "records": [record.model_dump(mode="json") for record in flat_records],
            "batches": [batch.model_dump(mode="json") for batch in batches],
        }
        with open(ai_handoff_path, "w", encoding="utf-8") as fh:
            json.dump(handoff, fh, ensure_ascii=False, indent=2, default=str)

        now = datetime.now(timezone.utc).isoformat()
        state.update(
            {
                "source_name": source,
                "last_success": now,
                "last_run_id": run_id,
                "last_manifest_path": str(manifest_path),
                "items": item_states,
            }
        )
        self.store.save_state(source, state)

        manifest = {
            "run_id": run_id,
            "source_name": source,
            "crawler_name": crawler_name,
            "status": "success",
            "since": since,
            "completed_at": now,
            "counts": {
                "source_raw": int(
                    ((getattr(crawl_result, "quality_details", {}) or {}).get("item_counts", {}) or {}).get(
                        "source_raw"
                    )
                    or len(raw_items)
                ),
                "parsed_valid": len(raw_items),
                "found": len(raw_items),
                "new": counts["new"],
                "changed": counts["changed"],
                "skipped_unchanged": counts["skipped"],
                "records_handed_off": len(flat_records),
                "skipped_invalid": skipped_invalid,
            },
            "source_input": source_input_manifest,
            "collection_mode": "bounded_source_input_no_db" if source_input is not None else "crawler_default_no_db",
            "live_network_enabled": False if source_input is not None else None,
            "artifacts": {
                "manifest": str(manifest_path),
                "raw_records_jsonl": raw_artifact_uri,
                "ai_handoff": str(ai_handoff_path),
            },
            "retry_attempts": attempts,
            "dead_letter_path": None,
        }
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, default=str)

        return SourceRunResult(
            crawler_name=crawler_name,
            source_name=source,
            status="success",
            run_id=run_id,
            items_found=len(raw_items),
            items_new=counts["new"],
            items_changed=counts["changed"],
            items_skipped=counts["skipped"],
            records_handed_off=len(flat_records),
            skipped_invalid=skipped_invalid,
            since=since,
            artifact_dir=str(artifact_dir),
            manifest_path=str(manifest_path),
            ai_handoff_path=str(ai_handoff_path),
            retry_attempts=attempts,
            duration=time.monotonic() - started,
            errors=errors,
        )

    def _failed_result(
        self,
        crawler_name: str,
        source_name: str,
        run_id: str,
        since: str | None,
        started: float,
        attempts: list[dict[str, Any]],
        errors: list[str],
    ) -> SourceRunResult:
        artifact_dir = self.store.artifact_dir(source_name, run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        dead_letter_path = write_dead_letter(
            [],
            crawler_name=crawler_name,
            target="source_run",
            error_msg="; ".join(error for error in errors if error),
        )
        manifest_path = artifact_dir / "manifest.json"
        ai_handoff_path = artifact_dir / "ai_handoff.json"
        manifest = {
            "run_id": run_id,
            "source_name": source_name,
            "crawler_name": crawler_name,
            "status": "failed",
            "since": since,
            "counts": {
                "found": 0,
                "new": 0,
                "changed": 0,
                "skipped_unchanged": 0,
                "records_handed_off": 0,
                "skipped_invalid": 0,
            },
            "artifacts": {"manifest": str(manifest_path), "ai_handoff": str(ai_handoff_path)},
            "retry_attempts": attempts,
            "dead_letter_path": str(dead_letter_path),
            "errors": errors,
        }
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, default=str)
        with open(ai_handoff_path, "w", encoding="utf-8") as fh:
            json.dump({"run_id": run_id, "records": [], "batches": []}, fh, ensure_ascii=False, indent=2)
        return SourceRunResult(
            crawler_name=crawler_name,
            source_name=source_name,
            status="failed",
            run_id=run_id,
            items_found=0,
            items_new=0,
            items_changed=0,
            items_skipped=0,
            records_handed_off=0,
            skipped_invalid=0,
            since=since,
            artifact_dir=str(artifact_dir),
            manifest_path=str(manifest_path),
            ai_handoff_path=str(ai_handoff_path),
            dead_letter_path=str(dead_letter_path),
            retry_attempts=attempts,
            duration=time.monotonic() - started,
            errors=errors,
        )


def stable_source_key(source_name: str, item: dict[str, Any]) -> str:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    for field in _SOURCE_KEY_FIELDS:
        value = item.get(field) or attrs.get(field)
        if value not in (None, ""):
            return str(value).strip()
    for field in _SOURCE_URL_FIELDS:
        value = item.get(field) or attrs.get(field)
        if value not in (None, ""):
            return f"url:{_hash_text(str(value).strip())}"
    title = _first_value(item, attrs, _TITLE_FIELDS)
    price = _first_value(item, attrs, _PRICE_FIELDS)
    return f"{source_name}:{_hash_text(f'{title}|{price}')}"


def source_fingerprint(item: dict[str, Any]) -> str:
    stable = _without_volatile(item)
    return _hash_text(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str))


async def _call_crawler(crawler: Any, *, since: str | None, source_input: str | None = None) -> Any:
    if hasattr(crawler, "crawl_incremental"):
        crawl_incremental = crawler.crawl_incremental
        signature = inspect.signature(crawl_incremental)
        kwargs: dict[str, Any] = {"since": since}
        if source_input is not None:
            if "source_input" in signature.parameters:
                kwargs["source_input"] = source_input
            elif "fixture" in signature.parameters:
                kwargs["fixture"] = source_input
            elif "raw_data" in signature.parameters:
                kwargs["raw_data"] = source_input
            else:
                raise ValueError("crawler does not support caller-supplied source_input")
        result = crawl_incremental(**kwargs)
        return await result if inspect.isawaitable(result) else result
    crawl = crawler.crawl
    signature = inspect.signature(crawl)
    kwargs = {}
    if "since" in signature.parameters:
        kwargs["since"] = since
    if source_input is not None:
        if "fixture" in signature.parameters:
            kwargs["fixture"] = source_input
        elif "raw_data" in signature.parameters:
            kwargs["raw_data"] = source_input
        elif "source_input" in signature.parameters:
            kwargs["source_input"] = source_input
        else:
            raise ValueError("crawler does not support caller-supplied source_input")
    result = crawl(**kwargs)
    return await result if inspect.isawaitable(result) else result


def _source_input_manifest(source_input: str | None, source_input_label: str | None) -> dict[str, Any]:
    if source_input is None:
        return {"provided": False}
    return {
        "provided": True,
        "label": source_input_label,
        "sha1": _hash_text(source_input),
        "bytes": len(source_input.encode("utf-8")),
        "mode": "caller_supplied_saved_source_input",
        "live_network_enabled": False,
    }


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "dict"):
        return item.dict()
    return dict(item)


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile(child)
            for key, child in sorted(value.items())
            if str(key) not in _VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [_without_volatile(child) for child in value]
    return value


def _first_value(item: dict[str, Any], attrs: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = item.get(field) or attrs.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    return safe or "source"
