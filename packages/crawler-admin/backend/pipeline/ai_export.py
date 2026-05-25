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
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# rd3-pipe-silent-gap-fix: 크롤러→ai-admin 브릿지에서 silent drop을 감시한다.
# 기존에는 forward()가 HTTP 200만 받으면 성공으로 간주했고, ai-admin이 records_stored 를
# 적게 반환해도 호출자가 알 길이 없어서 코스트코 OCC 995×3건이 0건으로 흡수됐다.
# - WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH 가 설정되면 forward 호출마다 JSONL 한 줄을 기록한다.
# - records_sent vs records_stored 가 다르면 RawExportError("ai_admin_silent_drop") 으로 즉시 차단한다.
# 다음 AI가 이 모듈을 리팩토링할 때 이 두 가드가 사라지면 silent gap 회귀가 발생한다.
_logger = logging.getLogger(__name__)
_FORWARD_WIRE_LOG_ENV = "WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH"

from core.contracts import (
    MAX_AI_BATCH_ITEMS,
    MAX_AI_BATCH_PROMPT_CHARS,
    PipelineStatus,
    RawCrawlBatchContract,
    RawCrawlRecord,
)
from core.record_ids import build_stable_raw_record_id


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
    """배치 한도 위반 등 raw export 단계의 안전한 예외.

    rd4-422-fix: kind 속성으로 timeout / connection / validation / silent_drop 등을 구분해
    라우터가 4xx vs 5xx 매핑을 정확히 할 수 있게 한다. 기본은 'validation' (=4xx).
    """

    def __init__(self, message: str, *, kind: str = "validation") -> None:
        super().__init__(message)
        self.kind = kind


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
        if v is None and isinstance(item.get("attributes"), dict):
            v = item["attributes"].get(k)
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
        return build_stable_raw_record_id(
            source_name=source_name,
            kind="key",
            value=source_record_key,
        )
    if source_url:
        digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
        return build_stable_raw_record_id(
            source_name=source_name,
            kind="url",
            value=digest,
        )
    digest = hashlib.sha1(
        f"{batch_id}:{index}:{raw_title}".encode("utf-8")
    ).hexdigest()[:16]
    return build_stable_raw_record_id(
        source_name=source_name,
        kind="gen",
        value=digest,
    )


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


def to_raw_records_with_invalid_rows(
    items: list[dict[str, Any]],
    *,
    source_name: str,
    batch_id: str,
    crawled_at: Optional[datetime] = None,
) -> tuple[list[RawCrawlRecord], int, list[dict[str, Any]]]:
    """item list → records plus row-level skip reasons for UI/API diagnostics."""
    records: list[RawCrawlRecord] = []
    invalid_rows: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        rec = to_raw_record(
            item,
            source_name=source_name,
            index=idx,
            batch_id=batch_id,
            crawled_at=crawled_at,
        )
        if rec is None:
            reason = "item must be an object" if not isinstance(item, dict) else "missing product name/title"
            invalid_rows.append({"index": idx, "reason": reason})
        else:
            records.append(rec)
    return records, len(invalid_rows), invalid_rows


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
    """RawCrawlRecord를 AI ingest 호출 한도(30개/8000자)에 맞춰 record-safe 분할.

    단일 record 가 prompt 한도를 초과하면 ``RawExportError`` 를 발생시키지 않고
    **solo batch 로 격리** 하여 ai-admin 으로 전달한다. ai-admin 의
    ``split_records_for_ai`` / ``_truncate_record_to_fit`` 가 이 경우를 다루며
    ``oversized_truncations`` 메타데이터를 응답에 포함한다.

    배경: 이전 구현은 2000자 한도에 한 글자라도 넘으면 422 로 전체 배치를 거절했고,
    사용자 라이브 화면에 ``ai_ingest_oversized_record_truncated`` 폭주 + 422 가
    동시에 발생했다 (한도 자체가 너무 작았고 거절 정책이 운영자 떠넘김이었음).
    한도를 8000자로 올리는 변경(MAX_AI_BATCH_PROMPT_CHARS) 과 함께, 그래도 넘는
    예외 record 는 명확한 단일 batch 로 격리 + 구조화 메타 전달로 처리한다.
    """
    batches: list[list[RawCrawlRecord]] = []
    current: list[RawCrawlRecord] = []
    current_chars = 0

    for record in records:
        record_chars = len(record.prompt_text())
        if record_chars > MAX_AI_BATCH_PROMPT_CHARS:
            # Solo-batch isolation: flush current and send oversized record alone.
            # ai-admin 가 segment-aware truncation + oversized_truncations 응답으로
            # 운영자에게 명시적으로 보고한다. 운영자 떠넘김 금지.
            _logger.warning(
                "raw_export_single_record_exceeds_prompt_budget",
                extra={
                    "raw_record_id": record.raw_record_id,
                    "record_chars": record_chars,
                    "prompt_char_limit": MAX_AI_BATCH_PROMPT_CHARS,
                    "action": "solo_batch_isolation",
                },
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
    records, skipped, _invalid_rows = to_raw_records_with_invalid_rows(
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
            try:
                data = json.loads(response_body) if response_body else {}
            except json.JSONDecodeError:
                data = {"detail": response_body}
            return response.status, data
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            data = {"detail": response_body}
        return exc.code, data
    except (TimeoutError, socket.timeout) as exc:
        raise RawExportError(
            f"failed to call ai-admin ingest endpoint: timed out after {timeout_seconds:.0f}s",
            kind="timeout",
        ) from exc
    except (URLError, OSError) as exc:
        raise RawExportError(
            f"failed to call ai-admin ingest endpoint: {exc}",
            kind="connection",
        ) from exc


def _get_json(
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            try:
                data = json.loads(response_body) if response_body else {}
            except json.JSONDecodeError:
                data = {"detail": response_body}
            return response.status, data
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            data = {"detail": response_body}
        return exc.code, data
    except (TimeoutError, socket.timeout) as exc:
        raise RawExportError(
            f"failed to call ai-admin providers endpoint: timed out after {timeout_seconds:.0f}s",
            kind="timeout",
        ) from exc
    except (URLError, OSError) as exc:
        raise RawExportError(
            f"failed to call ai-admin providers endpoint: {exc}",
            kind="connection",
        ) from exc


def _format_ai_admin_error(data: dict[str, Any]) -> str:
    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, dict):
        provider = detail.get("provider_id")
        model = detail.get("model")
        stage = detail.get("stage")
        raw_batch_id = detail.get("raw_batch_id")
        ai_batch_id = detail.get("ai_batch_id")
        row_count = detail.get("row_count")
        message = detail.get("message") or detail.get("error") or detail
        parts = []
        if stage:
            parts.append(f"stage={stage}")
        if provider:
            parts.append(f"provider={provider}")
        if model:
            parts.append(f"model={model}")
        if raw_batch_id:
            parts.append(f"raw_batch_id={raw_batch_id}")
        if ai_batch_id:
            parts.append(f"ai_batch_id={ai_batch_id}")
        if row_count is not None:
            parts.append(f"row_count={row_count}")
        parts.append(f"message={message}")
        return ", ".join(parts)
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        error = data["error"]
        code = error.get("code")
        message = error.get("message")
        error_id = error.get("error_id")
        parts = []
        if code:
            parts.append(f"code={code}")
        if error_id:
            parts.append(f"error_id={error_id}")
        if message:
            parts.append(f"message={message}")
        return ", ".join(parts) or str(error)
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


def _write_forward_wire_log(entry: dict[str, Any]) -> Optional[str]:
    """forward 호출 결과를 JSONL 한 줄로 기록(env-gated). 실패해도 호출은 막지 않는다."""
    path = os.environ.get(_FORWARD_WIRE_LOG_ENV)
    if not path:
        return None
    try:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return str(log_path)
    except OSError as exc:
        _logger.warning("forward wire log write failed: %s", exc)
        return None


def _accepted_count_from_response(data: dict[str, Any]) -> Optional[int]:
    """ai-admin 응답에서 raw_crawl_records 에 실제 적재된 행 수를 추출."""
    if not isinstance(data, dict):
        return None
    for key in ("records_stored", "records_saved", "raw_records_stored"):
        v = data.get(key)
        if isinstance(v, int):
            return v
    return None


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
    if not source_name:
        raise RawExportError("source_name is required")
    if not crawler_name:
        raise RawExportError("crawler_name is required")
    if not schema_type:
        raise RawExportError("schema_type is required")

    root_batch_id = batch_id or f"raw-{uuid.uuid4().hex[:16]}"
    records, skipped, invalid_rows = to_raw_records_with_invalid_rows(
        items,
        source_name=source_name,
        batch_id=root_batch_id,
    )
    record_batches = split_raw_records_for_ai(records)
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
    post = http_post or _post_json
    headers = {"X-API-Key": api_key} if api_key else {}
    endpoint = _ai_admin_endpoint(ai_admin_base_url, "/api/ingest/raw-records/label")

    responses: list[dict[str, Any]] = []
    accepted_total = 0
    per_batch_drops: list[dict[str, Any]] = []
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
        # rd3-pipe-silent-gap-fix: 200 OK여도 records_stored 가 expected보다 적으면 silent drop.
        accepted = _accepted_count_from_response(data)
        expected = len(records)
        if accepted is not None and accepted < expected:
            per_batch_drops.append(
                {
                    "batch_id": batch.batch_id,
                    "expected": expected,
                    "accepted": accepted,
                    "drop": expected - accepted,
                }
            )
        accepted_total += accepted if accepted is not None else expected
        responses.append({"raw_export_batch_id": batch.batch_id, **data})

    expected_total = sum(len(r) for r in record_batches)
    drop_total = max(0, expected_total - accepted_total)
    # rd3-422-fix: ai-admin 가 반환한 oversized_truncations 를 응답 + wire-log 에 누적.
    oversized_truncations_total: list[dict[str, Any]] = []
    for resp in responses:
        trunc = resp.get("oversized_truncations") or []
        if isinstance(trunc, list):
            oversized_truncations_total.extend(trunc)
    result = {
        "batches_sent": len(record_batches),
        "records_sent": expected_total,
        "records_accepted": accepted_total,
        "drop_count": drop_total,
        "per_batch_drops": per_batch_drops,
        "skipped_count": skipped,
        "invalid_rows": invalid_rows,
        "oversized_truncations": oversized_truncations_total,
        "oversized_truncations_count": len(oversized_truncations_total),
        "responses": responses,
    }
    wire_log_path = _write_forward_wire_log(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source_name": source_name,
            "crawler_name": crawler_name,
            "schema_type": schema_type,
            "ai_admin_base_url": ai_admin_base_url,
            "provider_id": provider_id,
            "root_batch_id": root_batch_id,
            "items_in": len(items),
            "skipped": skipped,
            "records_sent": expected_total,
            "records_accepted": accepted_total,
            "drop_count": drop_total,
            "per_batch_drops": per_batch_drops,
            "oversized_truncations_count": len(oversized_truncations_total),
            "oversized_truncations": oversized_truncations_total,
            "status": "drop" if drop_total > 0 else ("truncated" if oversized_truncations_total else "ok"),
        }
    )
    if wire_log_path:
        result["wire_log_path"] = wire_log_path

    if drop_total > 0:
        # 명시적으로 차단: JobsPanel/wire_log 알람이 빨간색으로 표시되도록 RawExportError 로 끌어올린다.
        raise RawExportError(
            "ai_admin_silent_drop: "
            f"source={source_name} sent={expected_total} accepted={accepted_total} "
            f"drop={drop_total} per_batch={per_batch_drops}"
        )

    return result
