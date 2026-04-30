"""
AI 파이프라인 경계 — 크롤 결과를 RawCrawlRecord 배치로 변환.

이 모듈은 ai-admin이 ingest 할 수 있는 형식의 ``RawCrawlRecord`` DTO 묶음을 만든다.
크롤러-어드민이 최종 product/offer 테이블에 직접 쓰는 것을 막고, 원본 보존
(불변 raw_payload, 원본 title/price/url) 책임만 담당한다.

배치는 ``AIJobBatch``의 record-safe 한도(MAX_AI_BATCH_ITEMS=30,
MAX_AI_BATCH_PROMPT_CHARS=2000)를 그대로 재사용한다. 한도를 넘으면 배치 자체를
거부하여 호출자가 안전하게 더 작은 청크로 다시 나누게 한다.
"""

from __future__ import annotations

import hashlib
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


_TITLE_KEYS: tuple[str, ...] = (
    "raw_title",
    "title",
    "name",
    "product_name",
    "normalized_name",
)
_PRICE_KEYS: tuple[str, ...] = (
    "raw_price",
    "sale_price",
    "price",
    "current_price",
    "original_price",
)
_URL_KEYS: tuple[str, ...] = (
    "source_url",
    "detail_url",
    "url",
    "link",
)
_RECORD_KEY_KEYS: tuple[str, ...] = (
    "source_record_key",
    "external_id",
    "post_id",
    "product_id",
    "id",
    "sku",
)


class RawExportError(ValueError):
    """배치 한도 위반 등 raw export 단계의 안전한 예외."""


def _first_str(item: dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        v = item.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _coerce_price(raw: Any) -> Optional[int]:
    """문자열/숫자에서 0 이상 정수 가격을 안전하게 추출. 실패 시 None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        if raw != raw or raw < 0:  # NaN or negative
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
    for k in _PRICE_KEYS:
        if k not in item:
            continue
        v = _coerce_price(item.get(k))
        if v is not None:
            return v
    return None


def _build_record_id(
    source_name: str,
    source_record_key: Optional[str],
    source_url: Optional[str],
    raw_title: str,
    index: int,
    batch_id: str,
) -> str:
    """안정적인 raw_record_id 생성. key/url이 있으면 결정적으로, 없으면 batch+index 기반."""
    if source_record_key:
        return f"{source_name}:{source_record_key}"
    if source_url:
        digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
        return f"{source_name}:url:{digest}"
    digest = hashlib.sha1(
        f"{batch_id}:{index}:{raw_title}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{source_name}:gen:{digest}"


def to_raw_record(
    item: dict[str, Any],
    *,
    source_name: str,
    index: int,
    batch_id: str,
    crawled_at: Optional[datetime] = None,
) -> Optional[RawCrawlRecord]:
    """
    단일 크롤 item dict → RawCrawlRecord. 제목이 없으면 None을 돌려 호출자가 skip.

    raw_payload는 원본 dict 전체를 보존한다 (정규화/덮어쓰기 금지).
    """
    if not isinstance(item, dict):
        return None
    raw_title = _first_str(item, _TITLE_KEYS)
    if not raw_title:
        return None

    source_record_key = _first_str(item, _RECORD_KEY_KEYS)
    source_url = _first_str(item, _URL_KEYS)
    raw_price = _first_price(item)

    record_id = _build_record_id(
        source_name=source_name,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_title=raw_title,
        index=index,
        batch_id=batch_id,
    )

    return RawCrawlRecord(
        raw_record_id=record_id,
        source_name=source_name,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_title=raw_title,
        raw_price=raw_price,
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
    """item list → (records, skipped_count). 제목 없는 항목은 skip."""
    records: list[RawCrawlRecord] = []
    skipped = 0
    for idx, item in enumerate(items):
        rec = to_raw_record(
            item,
            source_name=source_name,
            index=idx,
            batch_id=batch_id,
            crawled_at=crawled_at,
        )
        if rec is None:
            skipped += 1
        else:
            records.append(rec)
    return records, skipped


def _enforce_batch_limits(records: list[RawCrawlRecord]) -> None:
    if len(records) > MAX_AI_BATCH_ITEMS:
        raise RawExportError(
            f"raw batch has {len(records)} records; "
            f"max is {MAX_AI_BATCH_ITEMS}"
        )
    total_chars = sum(len(r.prompt_text()) for r in records)
    if total_chars > MAX_AI_BATCH_PROMPT_CHARS:
        raise RawExportError(
            f"raw batch prompt text is {total_chars} chars; "
            f"max is {MAX_AI_BATCH_PROMPT_CHARS}"
        )


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
    """
    크롤 결과 → (batch metadata, records, skipped_count).

    schema_type은 ai-admin이 정규화 흐름을 분기하기 위한 힌트
    (예: "mart_discount", "hotdeal", "shopping_product"). 최종 DB 테이블에 직접
    쓰지 않고 record-safe DTO만 반환한다.
    """
    if not source_name:
        raise RawExportError("source_name is required")
    if not crawler_name:
        raise RawExportError("crawler_name is required")
    if not schema_type:
        raise RawExportError("schema_type is required")

    bid = batch_id or f"raw-{uuid.uuid4().hex[:16]}"
    records, skipped = to_raw_records(
        items,
        source_name=source_name,
        batch_id=bid,
        crawled_at=crawled_at,
    )
    _enforce_batch_limits(records)

    batch = RawCrawlBatchContract(
        batch_id=bid,
        source_name=source_name,
        crawler_name=crawler_name,
        item_count=len(records),
        schema_type=schema_type,
        status=PipelineStatus.RAW_INGESTED,
        source_url=source_url,
        raw_artifact_uri=raw_artifact_uri,
    )
    return batch, records, skipped
