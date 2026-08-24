"""크롤 결과를 record-safe raw DTO와 배치로 변환한다.

이 모듈은 순수 변환/분할만 담당한다. 네트워크 호출, provider 조회, 외부 AI
서버 전송, DB 쓰기를 하지 않으며 원본 ``raw_payload``를 보존한다.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any, Iterable, Optional

from core.contracts import (
    MAX_AI_BATCH_ITEMS,
    MAX_AI_BATCH_PROMPT_CHARS,
    PipelineStatus,
    RawCrawlBatchContract,
    RawCrawlRecord,
)
from core.record_ids import build_stable_raw_record_id

_logger = logging.getLogger(__name__)

_TITLE_KEYS = ("raw_title", "title", "name", "product_name", "normalized_name")
_PRICE_KEYS = ("raw_price", "sale_price", "price", "current_price", "original_price")
_URL_KEYS = ("source_url", "detail_url", "url", "link")
_RECORD_KEY_KEYS = ("source_record_key", "external_id", "post_id", "product_id", "id", "sku")


class RawExportError(ValueError):
    def __init__(self, message: str, *, kind: str = "validation") -> None:
        super().__init__(message)
        self.kind = kind


def _first_str(item: dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if value is None and isinstance(item.get("attributes"), dict):
            value = item["attributes"].get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _coerce_price(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        if raw != raw or raw < 0:
            return None
        return int(raw)
    if isinstance(raw, str):
        cleaned = raw.replace(",", "").replace("원", "").replace("₩", "").strip()
        if not cleaned:
            return None
        try:
            value = int(float(cleaned))
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None
    return None


def _first_price(item: dict[str, Any]) -> Optional[int]:
    for key in _PRICE_KEYS:
        if key in item:
            value = _coerce_price(item.get(key))
            if value is not None:
                return value
    return None


def _build_record_id(
    source_name: str,
    source_record_key: Optional[str],
    source_url: Optional[str],
    raw_title: str,
    index: int,
    batch_id: str,
) -> str:
    if source_record_key:
        return build_stable_raw_record_id(source_name=source_name, kind="key", value=source_record_key)
    if source_url:
        digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
        return build_stable_raw_record_id(source_name=source_name, kind="url", value=digest)
    digest = hashlib.sha1(f"{batch_id}:{index}:{raw_title}".encode("utf-8")).hexdigest()[:16]
    return build_stable_raw_record_id(source_name=source_name, kind="gen", value=digest)


def to_raw_record(
    item: dict[str, Any],
    *,
    source_name: str,
    index: int,
    batch_id: str,
    crawled_at: Optional[datetime] = None,
) -> Optional[RawCrawlRecord]:
    if not isinstance(item, dict):
        return None
    raw_title = _first_str(item, _TITLE_KEYS)
    if not raw_title:
        return None
    source_record_key = _first_str(item, _RECORD_KEY_KEYS)
    source_url = _first_str(item, _URL_KEYS)
    return RawCrawlRecord(
        raw_record_id=_build_record_id(
            source_name,
            source_record_key,
            source_url,
            raw_title,
            index,
            batch_id,
        ),
        source_name=source_name,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_title=raw_title,
        raw_price=_first_price(item),
        raw_payload=dict(item),
        crawled_at=crawled_at or datetime.now(),
    )


def to_raw_records(
    items: list[dict[str, Any]],
    *,
    source_name: str,
    batch_id: str,
    crawled_at: Optional[datetime] = None,
) -> tuple[list[RawCrawlRecord], int]:
    records: list[RawCrawlRecord] = []
    skipped = 0
    for idx, item in enumerate(items):
        record = to_raw_record(
            item,
            source_name=source_name,
            index=idx,
            batch_id=batch_id,
            crawled_at=crawled_at,
        )
        if record is None:
            skipped += 1
        else:
            records.append(record)
    return records, skipped


def to_raw_records_with_invalid_rows(
    items: list[dict[str, Any]],
    *,
    source_name: str,
    batch_id: str,
    crawled_at: Optional[datetime] = None,
) -> tuple[list[RawCrawlRecord], int, list[dict[str, Any]]]:
    records: list[RawCrawlRecord] = []
    invalid_rows: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        record = to_raw_record(
            item,
            source_name=source_name,
            index=idx,
            batch_id=batch_id,
            crawled_at=crawled_at,
        )
        if record is None:
            reason = "item must be an object" if not isinstance(item, dict) else "missing product name/title"
            invalid_rows.append({"index": idx, "reason": reason})
        else:
            records.append(record)
    return records, len(invalid_rows), invalid_rows


def _enforce_batch_limits(records: list[RawCrawlRecord]) -> None:
    if len(records) > MAX_AI_BATCH_ITEMS:
        raise RawExportError(f"raw batch has {len(records)} records; max is {MAX_AI_BATCH_ITEMS}")
    total_chars = sum(len(record.prompt_text()) for record in records)
    if total_chars > MAX_AI_BATCH_PROMPT_CHARS:
        raise RawExportError(
            f"raw batch prompt text is {total_chars} chars; max is {MAX_AI_BATCH_PROMPT_CHARS}"
        )


def split_raw_records(records: list[RawCrawlRecord]) -> list[list[RawCrawlRecord]]:
    """현재 raw handoff 제한에 맞게 record 경계를 보존하며 분할한다."""
    batches: list[list[RawCrawlRecord]] = []
    current: list[RawCrawlRecord] = []
    current_chars = 0

    for record in records:
        record_chars = len(record.prompt_text())
        if record_chars > MAX_AI_BATCH_PROMPT_CHARS:
            _logger.warning(
                "raw_export_single_record_exceeds_prompt_budget",
                extra={"raw_record_id": record.raw_record_id, "record_chars": record_chars},
            )
            if current:
                batches.append(current)
                current = []
                current_chars = 0
            batches.append([record])
            continue

        would_exceed = (
            len(current) >= MAX_AI_BATCH_ITEMS
            or current_chars + record_chars > MAX_AI_BATCH_PROMPT_CHARS
        )
        if current and would_exceed:
            batches.append(current)
            current = []
            current_chars = 0

        current.append(record)
        current_chars += record_chars

    if current:
        batches.append(current)
    return batches


def build_raw_batches(
    items: list[dict[str, Any]],
    *,
    source_name: str,
    crawler_name: str,
    schema_type: str,
    source_url: Optional[str] = None,
    raw_artifact_uri: Optional[str] = None,
    crawled_at: Optional[datetime] = None,
    batch_id: Optional[str] = None,
) -> tuple[list[RawCrawlBatchContract], list[list[RawCrawlRecord]], int]:
    if not source_name:
        raise RawExportError("source_name is required")
    if not crawler_name:
        raise RawExportError("crawler_name is required")
    if not schema_type:
        raise RawExportError("schema_type is required")

    root_batch_id = batch_id or f"raw-{uuid.uuid4().hex[:16]}"
    records, skipped, _ = to_raw_records_with_invalid_rows(
        items,
        source_name=source_name,
        batch_id=root_batch_id,
        crawled_at=crawled_at,
    )
    record_batches = split_raw_records(records)
    batches = [
        RawCrawlBatchContract(
            batch_id=f"{root_batch_id}-{index:03d}",
            source_name=source_name,
            crawler_name=crawler_name,
            item_count=len(record_batch),
            schema_type=schema_type,
            status=PipelineStatus.RAW_INGESTED,
            source_url=source_url,
            raw_artifact_uri=raw_artifact_uri,
        )
        for index, record_batch in enumerate(record_batches, start=1)
    ]
    return batches, record_batches, skipped


def build_raw_batch(
    items: list[dict[str, Any]],
    *,
    source_name: str,
    crawler_name: str,
    schema_type: str,
    source_url: Optional[str] = None,
    raw_artifact_uri: Optional[str] = None,
    crawled_at: Optional[datetime] = None,
    batch_id: Optional[str] = None,
) -> tuple[RawCrawlBatchContract, list[RawCrawlRecord], int]:
    if not source_name:
        raise RawExportError("source_name is required")
    if not crawler_name:
        raise RawExportError("crawler_name is required")
    if not schema_type:
        raise RawExportError("schema_type is required")

    resolved_batch_id = batch_id or f"raw-{uuid.uuid4().hex[:16]}"
    records, skipped = to_raw_records(
        items,
        source_name=source_name,
        batch_id=resolved_batch_id,
        crawled_at=crawled_at,
    )
    _enforce_batch_limits(records)
    return (
        RawCrawlBatchContract(
            batch_id=resolved_batch_id,
            source_name=source_name,
            crawler_name=crawler_name,
            item_count=len(records),
            schema_type=schema_type,
            status=PipelineStatus.RAW_INGESTED,
            source_url=source_url,
            raw_artifact_uri=raw_artifact_uri,
        ),
        records,
        skipped,
    )
