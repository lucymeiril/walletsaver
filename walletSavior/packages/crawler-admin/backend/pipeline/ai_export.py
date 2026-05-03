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
import json
import uuid
from datetime import datetime
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], tuple[int, dict[str, Any]]]
HttpGet = Callable[[str, dict[str, str], float], tuple[int, dict[str, Any]]]


def _ai_admin_endpoint(ai_admin_base_url: str, path: str) -> str:
    base_url = ai_admin_base_url.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RawExportError("ai_admin_base_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise RawExportError("ai_admin_base_url must not include credentials")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RawExportError(
            "ai_admin_base_url must be only the ai-admin origin, for example http://localhost:8003"
        )
    if not parsed.hostname:
        raise RawExportError("ai_admin_base_url must include a hostname")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


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


def split_raw_records_for_ai(records: list[RawCrawlRecord]) -> list[list[RawCrawlRecord]]:
    """RawCrawlRecord를 AI ingest 호출 한도(30개/2000자)에 맞춰 record-safe 분할."""
    batches: list[list[RawCrawlRecord]] = []
    current: list[RawCrawlRecord] = []
    current_chars = 0

    for record in records:
        record_chars = len(record.prompt_text())
        if record_chars > MAX_AI_BATCH_PROMPT_CHARS:
            raise RawExportError(
                f"record {record.raw_record_id} prompt text is {record_chars} chars; "
                f"max is {MAX_AI_BATCH_PROMPT_CHARS}"
            )

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
    """
    크롤 결과를 ai-admin ingest 호출 한도에 맞는 여러 raw batch로 변환.

    긴 단일 record는 자르지 않고 명확히 거절한다.
    """
    if not source_name:
        raise RawExportError("source_name is required")
    if not crawler_name:
        raise RawExportError("crawler_name is required")
    if not schema_type:
        raise RawExportError("schema_type is required")

    root_batch_id = batch_id or f"raw-{uuid.uuid4().hex[:16]}"
    records, skipped = to_raw_records(
        items,
        source_name=source_name,
        batch_id=root_batch_id,
        crawled_at=crawled_at,
    )
    record_batches = split_raw_records_for_ai(records)
    batches: list[RawCrawlBatchContract] = []
    for index, record_batch in enumerate(record_batches, start=1):
        batches.append(
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
        )
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


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            **headers,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body) if response_body else {}
            return response.status, data
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            data = {"detail": response_body}
        return exc.code, data
    except URLError as exc:
        raise RawExportError(f"failed to call ai-admin ingest endpoint: {exc}") from exc


def _get_json(
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body) if response_body else {}
            return response.status, data
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            data = {"detail": response_body}
        return exc.code, data
    except URLError as exc:
        raise RawExportError(f"failed to call ai-admin providers endpoint: {exc}") from exc


def _format_ai_admin_error(data: dict[str, Any]) -> str:
    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, dict):
        provider = detail.get("provider_id")
        model = detail.get("model")
        message = detail.get("message") or detail.get("error") or detail
        parts = []
        if provider:
            parts.append(f"provider={provider}")
        if model:
            parts.append(f"model={model}")
        parts.append(f"message={message}")
        return ", ".join(parts)
    return str(detail or data.get("error") or data)


def fetch_ai_admin_providers(
    *,
    ai_admin_base_url: str,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10.0,
    http_get: Optional[HttpGet] = None,
) -> dict[str, Any]:
    """Server-side proxy for ai-admin providers so browsers avoid cross-origin calls."""
    if not ai_admin_base_url:
        raise RawExportError("ai_admin_base_url is required")

    headers = {"X-API-Key": api_key} if api_key else {}
    endpoint = _ai_admin_endpoint(ai_admin_base_url, "/api/providers")
    get = http_get or _get_json
    status_code, data = get(endpoint, headers, timeout_seconds)
    if status_code >= 400:
        detail = _format_ai_admin_error(data)
        raise RawExportError(f"ai-admin providers failed ({status_code}): {detail}")
    if not isinstance(data, dict):
        raise RawExportError("ai-admin providers response is not an object")
    providers = data.get("providers")
    if providers is not None and not isinstance(providers, list):
        raise RawExportError("ai-admin providers response has invalid providers field")
    return data


def forward_raw_records_to_ai_admin(
    items: list[dict[str, Any]],
    *,
    ai_admin_base_url: str,
    provider_id: str,
    source_name: str,
    crawler_name: str,
    schema_type: str,
    source_url: Optional[str] = None,
    raw_artifact_uri: Optional[str] = None,
    batch_id: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_seconds: float = 30.0,
    http_post: Optional[HttpPost] = None,
) -> dict[str, Any]:
    """크롤 결과를 변환/분할한 뒤 ai-admin raw label ingest API로 전송한다."""
    if not ai_admin_base_url:
        raise RawExportError("ai_admin_base_url is required")
    if not provider_id:
        raise RawExportError("provider_id is required")

    batches, record_batches, skipped = build_raw_batches(
        items,
        source_name=source_name,
        crawler_name=crawler_name,
        schema_type=schema_type,
        source_url=source_url,
        raw_artifact_uri=raw_artifact_uri,
        batch_id=batch_id,
    )
    post = http_post or _post_json
    headers = {"X-API-Key": api_key} if api_key else {}
    endpoint = _ai_admin_endpoint(ai_admin_base_url, "/api/ingest/raw-records/label")

    responses: list[dict[str, Any]] = []
    for batch, records in zip(batches, record_batches):
        payload = {
            "provider_id": provider_id,
            "source_name": source_name,
            "crawler_name": crawler_name,
            "schema_type": schema_type,
            "records": [record.model_dump(mode="json") for record in records],
        }
        status_code, data = post(endpoint, payload, headers, timeout_seconds)
        if status_code >= 400:
            detail = _format_ai_admin_error(data)
            raise RawExportError(
                f"ai-admin ingest failed for {batch.batch_id}: "
                f"status={status_code}, detail={detail}"
            )
        responses.append({"raw_export_batch_id": batch.batch_id, **data})

    return {
        "batches_sent": len(record_batches),
        "records_sent": sum(len(records) for records in record_batches),
        "skipped_count": skipped,
        "responses": responses,
    }
