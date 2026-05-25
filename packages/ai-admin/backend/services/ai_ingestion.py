"""Raw crawl ingestion and provider-backed labeling service."""
from __future__ import annotations

from datetime import datetime
import logging
import os
import re
import time
from typing import Any, Protocol
from uuid import uuid4

_logger = logging.getLogger("walletsavior.ai_ingestion")

# 2026-05-25 보류: 504 무한 회귀 문제로 live AI pipeline 비활성화.
# 외부 분류 워크플로우로 전환. 삭제 금지; 향후 복귀 시 flag만 켜면 됨.
WALLETSAVIOR_LIVE_AI_ENABLED = os.environ.get("WALLETSAVIOR_LIVE_AI_ENABLED", "false").lower() in ("1", "true", "yes")

from sqlalchemy.orm import Session

from core.contracts.ai_pipeline import (
    AIProviderRef,
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    MAX_AI_BATCH_ITEMS,
    MAX_AI_BATCH_PROMPT_CHARS,
    PipelineStatus,
    ProposalType,
    ProviderKind,
    RawCrawlRecord,
)
from core.contracts.control_plane import (
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProviderConfigContract,
    RawCrawlBatchContract,
)
from providers import GoogleGenAIProvider
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from core.product_units import normalize_unit_metadata, quantity_to_standard_total
from core.record_ids import provider_facing_raw_record_id_map
from storage.repositories import (
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
)
from services.keyword_catalog import (
    KeywordCatalogAdapter,
    build_keyword_outputs,
    canonical_candidate,
    normalize_keyword,
)
from services.seed_taxonomy import (
    get_category_display_label,
    is_safe_seed_category,
    normalize_category_id,
    seed_taxonomy_prompt_line,
)
from services.rule_mapper import record_rule_hit as _record_rule_hit


_TRANSIENT_PROVIDER_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "quota",
    "rate limit",
    "rate_limit",
    "timeout",
    "timed out",
    "temporarily",
    "temporary",
    "unavailable",
    "internal_error",
    "internal error",
    "try again",
)
_MAX_PROVIDER_ATTEMPTS = 3
_MISSING_LABEL_RETRY_BATCHES = 2
_MIN_PROVIDER_BACKOFF_SECONDS = 10.0
_MAX_PROVIDER_BACKOFF_SECONDS = 60.0
_MIN_PROVIDER_REQUEST_INTERVAL_SECONDS = 12.0
_MAX_PROVIDER_CALLS_PER_MINUTE = 5
_MAX_PROVIDER_CALLS_PER_DAY = 300
# rd5-batch-bigger: 사용자 직격 "30건인데 왜 ai 요청이 여러 번 발생함? 30개 이상씩 묶어서 한 번에 요청 보내고
# 한 번에 json 응답 받고 파싱". Gemma 4 는 128k token context, 60_000 chars 는 충분히 안전한 상한.
# 기존 12_000 은 8000 chars budget 위에서 30건이 prompt 만들면서 자주 4-5 sub-batch 로 잘리는 원인이었음.
MAX_OPERATOR_AI_BATCH_PROMPT_CHARS = 60_000
_PROVIDER_RATE_WINDOW_SECONDS = 60.0
_PROVIDER_DAILY_WINDOW_SECONDS = 86400.0
_provider_call_history: dict[str, list[float]] = {}
_sleep = time.sleep
_monotonic = time.monotonic

# ---------------------------------------------------------------------------
# Prompt truncation helpers
#
# Why truncate instead of reject?
# A single record exceeding the prompt budget must NOT kill the entire batch
# (운영자 떠넘김 금지). We preserve a marker so reviewers and audits know
# something was cut — the original is always recoverable from the raw DB.
# ---------------------------------------------------------------------------

# Payload keys that tend to carry long free-text; truncate these first so we
# disturb the structured fields (price/unit/date) as little as possible.
_TRUNCATABLE_PAYLOAD_KEYS: tuple[str, ...] = (
    "description",
    "content",
    "body",
    "detail",
    "text",
    "summary",
    "category_hint",   # can be a long taxonomy path
    "image_url",       # URLs can be hundreds of chars
    "image",
)


def _make_truncation_marker(orig_len: int) -> str:
    return f"\u2026[truncated:{orig_len}chars]"


def _truncate_str(s: str, max_len: int) -> str:
    """Shorten *s* to *max_len* chars, appending a preservation marker.

    The marker records the original length so reviewers know exactly how much
    was removed. We never return an empty string — the marker alone is kept
    even if max_len is very small.
    """
    if len(s) <= max_len:
        return s
    marker = _make_truncation_marker(len(s))
    available = max_len - len(marker)
    if available < 1:
        return marker[:max_len]
    return s[:available] + marker


def _truncate_record_to_fit(
    record: RawCrawlRecord,
    prompt_char_limit: int,
    catalog: list[Any] | None,
    learned_knowledge: list[Any] | None,
) -> tuple[RawCrawlRecord, dict[str, Any] | None]:
    """Return a (possibly truncated) copy of *record* that fits within
    *prompt_char_limit*.

    Strategy (priority order):
    1. Truncate long free-text payload fields (description, image_url, …).
    2. Truncate raw_title — the main user-visible text.
    3. If still over after aggressive title truncation, return the record as-is
       but mark it as an oversized single-record batch; provider call proceeds
       with the oversized prompt rather than crashing the whole batch.

    Returns ``(record, None)`` when no truncation is needed.
    Returns ``(truncated_record, meta_dict)`` otherwise.
    """
    record_chars = _prompt_chars_for(
        [record], catalog, learned_knowledge, max_prompt_chars=prompt_char_limit
    )
    if record_chars <= prompt_char_limit:
        return record, None

    orig_chars = record_chars

    # ── Step 1: truncate long payload fields ──────────────────────────────
    payload = dict(record.raw_payload)
    payload_changed = False
    for key in _TRUNCATABLE_PAYLOAD_KEYS:
        val = payload.get(key)
        if not isinstance(val, str) or len(val) <= 50:
            continue
        excess = record_chars - prompt_char_limit
        new_len = max(20, len(val) - excess - 5)
        payload[key] = _truncate_str(val, new_len)
        payload_changed = True
        candidate = record.model_copy(update={"raw_payload": payload})
        record_chars = _prompt_chars_for(
            [candidate], catalog, learned_knowledge, max_prompt_chars=prompt_char_limit
        )
        record = candidate
        if record_chars <= prompt_char_limit:
            meta: dict[str, Any] = {
                "raw_record_id": record.raw_record_id,
                "orig_chars": orig_chars,
                "final_chars": record_chars,
                "truncated_field": key,
            }
            _logger.warning(
                "ai_ingest_oversized_record_truncated",
                extra={**meta, "prompt_char_limit": prompt_char_limit},
            )
            return record, meta

    # ── Step 2: truncate raw_title ─────────────────────────────────────────
    orig_title = record.raw_title
    excess = record_chars - prompt_char_limit
    marker = _make_truncation_marker(len(orig_title))
    new_title_len = max(len(marker) + 1, len(orig_title) - excess - 5)
    candidate = record.model_copy(update={"raw_title": _truncate_str(orig_title, new_title_len)})
    record_chars = _prompt_chars_for(
        [candidate], catalog, learned_knowledge, max_prompt_chars=prompt_char_limit
    )
    if record_chars <= prompt_char_limit:
        meta = {
            "raw_record_id": record.raw_record_id,
            "orig_chars": orig_chars,
            "final_chars": record_chars,
            "truncated_field": "raw_title",
        }
        _logger.warning(
            "ai_ingest_oversized_record_truncated",
            extra={**meta, "prompt_char_limit": prompt_char_limit},
        )
        return candidate, meta

    # ── Step 3: aggressive binary-search title reduction ──────────────────
    lo, hi = len(marker) + 1, len(orig_title)
    best_record, best_chars = candidate, record_chars
    for _ in range(20):
        mid = (lo + hi) // 2
        if mid == lo:
            break
        t = record.model_copy(update={"raw_title": _truncate_str(orig_title, mid)})
        c = _prompt_chars_for(
            [t], catalog, learned_knowledge, max_prompt_chars=prompt_char_limit
        )
        if c <= prompt_char_limit:
            best_record, best_chars = t, c
            lo = mid + 1
        else:
            hi = mid - 1

    if best_chars <= prompt_char_limit:
        meta = {
            "raw_record_id": best_record.raw_record_id,
            "orig_chars": orig_chars,
            "final_chars": best_chars,
            "truncated_field": "raw_title",
        }
        _logger.warning(
            "ai_ingest_oversized_record_truncated",
            extra={**meta, "prompt_char_limit": prompt_char_limit},
        )
        return best_record, meta

    # ── Step 4: nothing fits — oversized single-record batch ──────────────
    # We proceed anyway rather than crashing; the provider will handle it or
    # the shrink-retry path will fall back. Never drop the record silently.
    meta = {
        "raw_record_id": record.raw_record_id,
        "orig_chars": orig_chars,
        "final_chars": record_chars,
        "truncated_field": "none",
        "oversized_single_batch": True,
    }
    _logger.warning(
        "ai_ingest_oversized_record_truncated",
        extra={**meta, "prompt_char_limit": prompt_char_limit},
    )
    return record, meta


_LABELING_PROMPT_PREFIX = [
    "WalletSavior raw product data labeling task.",
    "First reuse existing DB keywords/match terms when provided by system context.",
    "Return exactly one item for every input record. Never skip unfamiliar, non-food, gift-card, ticket, fashion, beauty, electronics, or household rows; use the safest broad category and a title-derived keyword when uncertain.",
    "Return only valid JSON with this shape:",
    '{"items":[{"raw_record_id":"...","canonical_name":"...",'
    '"source_title":"...","sale_price":null,"original_price":null,'
    '"discount_percent":null,"event_name":null,"valid_from":null,"valid_to":null,'
    '"source_url":null,"image_url":null,'
    '"brand":null,"category_id":"...","keywords":["..."],'
    '"aliases":["..."],"attributes":{},"package_quantity":null,'
    '"package_unit":null,"display_unit":null,"bundle_count":1,"standard_unit":null,'
    '"standard_unit_price":null,"price_per_100g":null,"confidence":0.0,"notes":"..."}]}',
    "Rules: preserve raw titles, do not invent prices, classify snacks as snacks even if the name contains seafood words.",
    "If no package size is explicit, use package_quantity=1, package_unit=\"개\", display_unit=\"1개\", bundle_count=1 so every review row has a unit signal.",
    "If source unit=100g but title has pack size like 300g/(200g) or 300g*2, raw price is pack price; set display unit from title and price_per_100g separately.",
    "For bundles like 300g*2, package_quantity=300, bundle_count=2, and standard_unit_price uses sale_price/(quantity*bundle_count).",
    "Put storage/origin/cut/grade facts such as 냉장, 냉동, 베트남, 불고기, 1+등급 in attributes, not keywords.",
    "Use a broad canonical keyword instead of promotional/country variants when possible (e.g. 두부, not 국산두부 or 행사두부).",
    "Records:",
]
_TEXT_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_PROMO_TITLE_TOKENS = (
    "행사",
    "특가",
    "할인",
    "쿠폰",
    "단독",
    "추가",
    "무료배송",
    "정상가",
    "추천",
    "기획",
)
_FALLBACK_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mobile_phone",   ("갤럭시", "아이폰", "iphone", "자급제", "휴대폰", "스마트폰")),
    ("home_appliance", ("냉장고", "세탁기", "건조기", "워시타워", "공기청정기", "정수기", "선풍기", "써큘레이터", "드라이기")),
    ("electronics",    ("블루투스", "이어폰", "스피커", "모니터", "충전기", "노트북", "어댑터")),
    ("fashion_apparel", ("가방", "캐리어", "토트백", "숄더백", "파우치", "백팩")),
    ("fashion_apparel", ("티셔츠", "저지", "팬츠", "쇼츠", "양말", "폴로", "선글라스", "나이키", "아디다스", "푸마")),
    ("skin_care",      ("세럼", "크림", "토닝", "스킨", "화장품", "마스크팩")),
    ("beauty_health",  ("샴푸", "트리트먼트", "헤어", "염색")),
    ("household",      ("세제", "수세미", "청소", "진드기", "필터")),
    ("household",      ("샤워기", "수건", "비데", "욕실")),
    ("home_kitchen",   ("식탁", "테이블웨어", "그릇", "컵", "냄비", "주방")),
    ("household",      ("행거", "수납", "정리함", "케이스")),
    # 서비스/상품권 — tree에 해당 노드 없음: 미분류 처리 후 escalation
    # ("service.voucher", ...) 제거 — 잡종 ID 자동 생성 분기 제거
    ("vegetable",      ("버섯", "당근", "양파", "감자", "고구마", "채소", "야채")),
    ("fruit",          ("과일", "참외", "사과", "감귤", "귤", "망고", "바나나", "복숭아")),
    ("processed_food", ("치즈",)),
    ("processed_food", ("커피", "마끼아또", "홍차", "티백")),
    ("convenience_meal", ("즉석밥", "햇반", "누룽지", "죽", "곰탕")),
    ("meat_egg",       ("훈제오리", "오리", "소시지", "햄")),
    ("seafood",        ("새우", "새우살")),
)


def _safe_error_message(message: str) -> str:
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_API_KEY]", message)
    redacted = re.sub(
        r"(?i)(api[_-]?key|key|token|authorization)(\s*[=:]\s*)['\"]?[^'\"\s,;}]+",
        r"\1\2[REDACTED]",
        redacted,
    )
    return redacted.strip()


def _is_transient_provider_error(exc: ProviderResponseError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_PROVIDER_MARKERS)


def _is_live_provider(provider: ProviderAdapter) -> bool:
    return getattr(provider, "provider_mode", None) == "live"


def _provider_limit(config: ProviderConfigContract, field: str, default: Any) -> Any:
    value = getattr(config, field, default)
    return default if value is None else value


def _reserve_live_provider_call(provider_id: str, config: ProviderConfigContract) -> None:
    min_interval_seconds = float(
        _provider_limit(
            config,
            "min_request_interval_seconds",
            _MIN_PROVIDER_REQUEST_INTERVAL_SECONDS,
        )
    )
    max_calls_per_minute = int(
        _provider_limit(
            config,
            "max_provider_calls_per_minute",
            _MAX_PROVIDER_CALLS_PER_MINUTE,
        )
    )
    max_calls_per_day = int(
        _provider_limit(
            config,
            "max_provider_calls_per_day",
            _MAX_PROVIDER_CALLS_PER_DAY,
        )
    )
    now = _monotonic()
    history = [
        timestamp
        for timestamp in _provider_call_history.get(provider_id, [])
        if now - timestamp < _PROVIDER_DAILY_WINDOW_SECONDS
    ]
    if len(history) >= max_calls_per_day:
        raise AIIngestionError(
            "provider daily call budget exhausted; add another configured API key/provider or wait for quota reset",
            stage="provider_rate_limit",
            status_code=429,
            provider_id=provider_id,
        )

    recent_minute = [
        timestamp
        for timestamp in history
        if now - timestamp < _PROVIDER_RATE_WINDOW_SECONDS
    ]
    wait_until = now
    if history:
        wait_until = max(wait_until, history[-1] + min_interval_seconds)
    if len(recent_minute) >= max_calls_per_minute:
        wait_until = max(wait_until, recent_minute[0] + _PROVIDER_RATE_WINDOW_SECONDS)
    if wait_until > now:
        _sleep(wait_until - now)
        now = max(wait_until, _monotonic())
        history = [
            timestamp
            for timestamp in history
            if now - timestamp < _PROVIDER_DAILY_WINDOW_SECONDS
        ]
    history.append(now)
    _provider_call_history[provider_id] = history


def _record_prompt_line(record: RawCrawlRecord, *, provider_raw_record_id: str | None = None) -> str:
    hints = []
    for key in (
        "unit",
        "quantity",
        "category_hint",
        "image_url",
        "image",
        "source",
        "store",
        "sale_price",
        "original_price",
        "discount_percent",
        "discount_rate",
        "event_name",
        "valid_from",
        "valid_to",
        "start_date",
        "end_date",
    ):
        value = record.raw_payload.get(key)
        if value not in (None, ""):
            hints.append(f"{key}={value}")
    source_url = f"; url={record.source_url}" if record.source_url else ""
    hint_text = f"; hints={', '.join(map(str, hints))}" if hints else ""
    return (
        f"- id={provider_raw_record_id or record.raw_record_id}; source={record.source_name}; "
        f"title={record.raw_title}; price={record.raw_price}{source_url}{hint_text}"
    )


def _catalog_prompt_lines(
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
) -> list[str]:
    lines: list[str] = []
    if catalog:
        lines.append("Existing DB keyword catalog (reuse these words/synonyms; do not propose duplicates):")
        safe_catalog = [keyword for keyword in catalog if _is_prompt_safe_catalog_keyword(keyword)]
        for keyword in safe_catalog[:80]:
            synonyms = ", ".join(getattr(keyword, "synonyms", ()) or [])
            category = getattr(keyword, "category_id", None) or ""
            suffix = f"; synonyms={synonyms}" if synonyms else ""
            cat = f"; category_id={category}" if category else ""
            lines.append(f"- keyword={keyword.word}{cat}{suffix}")
    approved = [
        item
        for item in (learned_knowledge or [])
        if getattr(item, "knowledge_type", "") == "keyword_alias_approved"
    ][:80]
    rejected = [
        item
        for item in (learned_knowledge or [])
        if getattr(item, "knowledge_type", "") == "keyword_rejected"
    ][:80]
    if approved:
        lines.append("Approved alias/synonym learning (reuse target word; do not create new keyword proposals):")
        for item in approved:
            target = item.target_value if isinstance(item.target_value, dict) else {}
            lines.append(f"- term={item.pattern} -> keyword={target.get('word')}")
    if rejected:
        lines.append("Rejected keyword learning (do not use these as canonical keywords):")
        for item in rejected:
            lines.append(f"- rejected_term={item.pattern}; reason={getattr(item, 'negative_examples', [])[:1]}")
    return lines


def _is_prompt_safe_catalog_keyword(keyword: Any) -> bool:
    word = str(getattr(keyword, "word", "") or "").strip()
    if not word:
        return False
    normalized = normalize_keyword(word)
    # Test/auth sentinel keywords can poison live prompts if a local DB was
    # reused after tests. They are not product taxonomy evidence.
    blocked_markers = (
        "test",
        "temp",
        "debug",
        "mock",
        "dummy",
        "local",
        "dev",
        "placeholder",
        "fixture",
        "sample",
        "sentinel",
        "unique",
    )
    if any(marker in normalized for marker in blocked_markers):
        return False
    synonyms = tuple(str(value) for value in (getattr(keyword, "synonyms", ()) or ()))
    if any(
        any(marker in normalize_keyword(value) for marker in blocked_markers)
        for value in synonyms
    ):
        return False
    return True


def _bounded_prompt_lines(
    records: list[RawCrawlRecord],
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
    *,
    max_prompt_chars: int = MAX_AI_BATCH_PROMPT_CHARS,
    provider_record_ids: dict[str, str] | None = None,
) -> list[str]:
    """Trim optional catalog/learning context before dropping a whole record."""
    base_lines = [*_LABELING_PROMPT_PREFIX[:-1]]
    provider_record_ids = provider_record_ids or provider_facing_raw_record_id_map(
        [record.raw_record_id for record in records]
    )
    record_lines = [
        _record_prompt_line(
            record,
            provider_raw_record_id=provider_record_ids.get(record.raw_record_id),
        )
        for record in records
    ]
    required_lines = [*base_lines, "Records:", *record_lines]
    if len("\n".join(required_lines)) > max_prompt_chars:
        return required_lines

    context_lines: list[str] = []
    optional_guidance = [
        seed_taxonomy_prompt_line(),
        "Prefer official IDs; do not invent dotted taxonomy paths when a broad hint fits.",
    ]
    for line in optional_guidance:
        candidate = [*base_lines, *context_lines, line, "Records:", *record_lines]
        if len("\n".join(candidate)) <= max_prompt_chars:
            context_lines.append(line)
    for line in _catalog_prompt_lines(catalog, learned_knowledge):
        candidate = [*base_lines, *context_lines, line, "Records:", *record_lines]
        if len("\n".join(candidate)) <= max_prompt_chars:
            context_lines.append(line)
    return [*base_lines, *context_lines, "Records:", *record_lines]


def _prompt_chars_for(
    records: list[RawCrawlRecord],
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
    *,
    max_prompt_chars: int = MAX_AI_BATCH_PROMPT_CHARS,
) -> int:
    return len(
        "\n".join(
            _bounded_prompt_lines(
                records,
                catalog,
                learned_knowledge,
                max_prompt_chars=max_prompt_chars,
            )
        )
    )


def _validate_ai_batch_limits(
    *,
    max_batch_items: int | None = None,
    max_prompt_chars: int | None = None,
) -> tuple[int, int]:
    batch_items = MAX_AI_BATCH_ITEMS if max_batch_items is None else int(max_batch_items)
    prompt_chars = MAX_AI_BATCH_PROMPT_CHARS if max_prompt_chars is None else int(max_prompt_chars)
    if batch_items < 1 or batch_items > MAX_AI_BATCH_ITEMS:
        raise ValueError(f"max AI batch items must be between 1 and {MAX_AI_BATCH_ITEMS}")
    if prompt_chars < 1 or prompt_chars > MAX_OPERATOR_AI_BATCH_PROMPT_CHARS:
        raise ValueError(
            f"max AI batch prompt chars must be between 1 and {MAX_OPERATOR_AI_BATCH_PROMPT_CHARS}"
        )
    return batch_items, prompt_chars


class ProviderAdapter(Protocol):
    config: ProviderConfigContract

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


def _provider_response_id_validation(
    *,
    batch_records: list[RawCrawlRecord],
    response: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop hallucinated IDs and use order mapping only when the full batch aligns."""
    items = response.get("items")
    if not isinstance(items, list):
        return response, {
            "item_count": None,
            "request_record_count": len(batch_records),
            "invalid_response_row_count": 0,
            "invalid_response_rows": [],
            "index_mapping_count": 0,
            "index_mappings": [],
            "reason": "provider response items is not a list",
        }

    record_by_id = {record.raw_record_id: record for record in batch_records}
    raw_to_provider_id = provider_facing_raw_record_id_map(
        [record.raw_record_id for record in batch_records]
    )
    provider_to_raw_id = {
        provider_id: raw_id for raw_id, provider_id in raw_to_provider_id.items()
    }
    can_index_map = len(items) == len(batch_records)
    if can_index_map:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                can_index_map = False
                break
            record_id = item.get("raw_record_id")
            if isinstance(record_id, str) and record_id in provider_to_raw_id:
                comparable_id = provider_to_raw_id[record_id]
            else:
                comparable_id = record_id
            if comparable_id in record_by_id and comparable_id != batch_records[index].raw_record_id:
                can_index_map = False
                break

    sanitized_items: list[Any] = []
    invalid_rows: list[dict[str, Any]] = []
    index_mappings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            sanitized_items.append(item)
            continue
        original_id = item.get("raw_record_id")
        record_id = original_id if isinstance(original_id, str) else None
        target_id: str | None = record_id if record_id in record_by_id else None
        if target_id is None and record_id in provider_to_raw_id:
            target_id = provider_to_raw_id[record_id]
            item = {**item, "raw_record_id": target_id}
            if record_id != target_id:
                index_mappings.append(
                    {
                        "item_index": index,
                        "original_raw_record_id": record_id,
                        "mapped_raw_record_id": target_id,
                        "reason": "provider_ascii_id",
                    }
                )
        if target_id is None and can_index_map and index < len(batch_records):
            target_id = batch_records[index].raw_record_id
            item = {**item, "raw_record_id": target_id}
            index_mappings.append(
                {
                    "item_index": index,
                    "original_raw_record_id": record_id,
                    "mapped_raw_record_id": target_id,
                    "reason": "response_order_count_exact",
                }
            )
        if target_id is None:
            invalid_rows.append(
                {
                    "item_index": index,
                    "raw_record_id": record_id,
                    "field": "raw_record_id",
                    "reason": "unknown_or_missing_raw_record_id",
                }
            )
            continue
        if target_id in seen_ids:
            invalid_rows.append(
                {
                    "item_index": index,
                    "raw_record_id": target_id,
                    "field": "raw_record_id",
                    "reason": "duplicate_raw_record_id",
                }
            )
            continue
        seen_ids.add(target_id)
        sanitized_items.append(item)

    summary = {
        "item_count": len(items),
        "request_record_count": len(batch_records),
        "valid_response_row_count": len(sanitized_items),
        "invalid_response_row_count": len(invalid_rows),
        "invalid_response_rows": invalid_rows,
        "index_mapping_count": len(index_mappings),
        "index_mappings": index_mappings,
        "missing_label_count": sum(
            1 for record in batch_records if record.raw_record_id not in seen_ids
        ),
        "reason": (
            "invalid provider raw_record_id rows were ignored; raw records retained for review"
            if invalid_rows
            else None
        ),
    }
    return {**response, "items": sanitized_items}, summary


class AIIngestionError(RuntimeError):
    """Safe, API-ready ingestion failure with enough context for operators."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        status_code: int,
        provider_id: str | None = None,
        model: str | None = None,
        raw_batch_id: str | None = None,
        ai_batch_id: str | None = None,
        row_count: int | None = None,
        invalid_rows: list[dict[str, Any]] | None = None,
        provider_error_detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(_safe_error_message(message))
        self.stage = stage
        self.status_code = status_code
        self.provider_id = provider_id
        self.model = model
        self.raw_batch_id = raw_batch_id
        self.ai_batch_id = ai_batch_id
        self.row_count = row_count
        self.invalid_rows = invalid_rows or []
        self.provider_error_detail = provider_error_detail

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "error": "ai_ingestion_error",
            "stage": self.stage,
            "message": str(self),
        }
        if self.provider_id:
            detail["provider_id"] = self.provider_id
        if self.model:
            detail["model"] = self.model
        if self.raw_batch_id:
            detail["raw_batch_id"] = self.raw_batch_id
        if self.ai_batch_id:
            detail["ai_batch_id"] = self.ai_batch_id
        if self.row_count is not None:
            detail["row_count"] = self.row_count
        if self.invalid_rows:
            detail["invalid_rows"] = self.invalid_rows
        if self.provider_error_detail:
            detail["provider_error"] = self.provider_error_detail
        return detail


def split_records_for_ai(
    records: list[RawCrawlRecord],
    *,
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
    max_batch_items: int | None = None,
    max_prompt_chars: int | None = None,
) -> tuple[list[list[RawCrawlRecord]], list[dict[str, Any]]]:
    """Split records into prompt-budget-safe batches without cutting a record across batches.

    Returns ``(batches, oversized_truncations)`` where *oversized_truncations*
    is a list of metadata dicts for any record whose prompt contribution
    exceeded the budget and had to be truncated (or forced into a solo batch).

    Design: a single record that exceeds the budget is NEVER rejected —
    we truncate it or put it in its own batch.  Killing the whole ingest
    because of one long record violates the operator contract.
    """
    batch_item_limit, prompt_char_limit = _validate_ai_batch_limits(
        max_batch_items=max_batch_items,
        max_prompt_chars=max_prompt_chars,
    )
    batches: list[list[RawCrawlRecord]] = []
    oversized_truncations: list[dict[str, Any]] = []
    current: list[RawCrawlRecord] = []
    for record in records:
        # Truncate this record if its solo prompt contribution exceeds budget.
        record, trunc_meta = _truncate_record_to_fit(
            record, prompt_char_limit, catalog, learned_knowledge
        )
        if trunc_meta is not None:
            oversized_truncations.append(trunc_meta)
            if trunc_meta.get("oversized_single_batch"):
                # Even after truncation it doesn't fit — flush and isolate.
                if current:
                    batches.append(current)
                    current = []
                batches.append([record])
                continue

        would_exceed = (
            len(current) >= batch_item_limit
            or _prompt_chars_for(
                [*current, record],
                catalog,
                learned_knowledge,
                max_prompt_chars=prompt_char_limit,
            ) > prompt_char_limit
        )
        if current and would_exceed:
            batches.append(current)
            current = []
        current.append(record)
    if current:
        batches.append(current)
    return batches, oversized_truncations


def build_labeling_prompt(
    records: list[RawCrawlRecord],
    *,
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
    max_prompt_chars: int | None = None,
) -> str:
    """Build a strict JSON prompt for product labeling/classification.

    If the assembled prompt exceeds *max_prompt_chars*, the catalog/context
    section is already trimmed by ``_bounded_prompt_lines``.  In the rare
    case where the record section itself is still over budget (shouldn't
    happen after ``split_records_for_ai`` pre-truncates), we emit a warning
    and return the prompt as-is rather than raising — never block the call.
    """
    _batch_items, prompt_char_limit = _validate_ai_batch_limits(max_prompt_chars=max_prompt_chars)
    prompt = "\n".join(
        _bounded_prompt_lines(
            records,
            catalog,
            learned_knowledge,
            max_prompt_chars=prompt_char_limit,
        )
    )
    if len(prompt) > prompt_char_limit:
        _logger.warning(
            "ai_ingest_oversized_record_truncated",
            extra={
                "stage": "build_labeling_prompt",
                "prompt_chars": len(prompt),
                "prompt_char_limit": prompt_char_limit,
                "record_count": len(records),
                "raw_record_ids": [r.raw_record_id for r in records],
            },
        )
    return prompt


def labeling_response_schema() -> dict[str, Any]:
    """Schema hint for providers that support JSON schema mode."""
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "raw_record_id": {"type": "string"},
                        "canonical_name": {"type": "string"},
                        "source_title": {"type": ["string", "null"]},
                        "sale_price": {"type": ["number", "null"]},
                        "original_price": {"type": ["number", "null"]},
                        "discount_percent": {"type": ["number", "null"]},
                        "event_name": {"type": ["string", "null"]},
                        "valid_from": {"type": ["string", "null"]},
                        "valid_to": {"type": ["string", "null"]},
                        "source_url": {"type": ["string", "null"]},
                        "image_url": {"type": ["string", "null"]},
                        "brand": {"type": ["string", "null"]},
                        "category_id": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "attributes": {"type": "object"},
                        "package_quantity": {"type": ["number", "null"]},
                        "package_unit": {"type": ["string", "null"]},
                        "display_unit": {"type": ["string", "null"]},
                        "bundle_count": {"type": ["integer", "null"]},
                        "standard_unit": {"type": ["string", "null"]},
                        "standard_unit_price": {"type": ["number", "null"]},
                        "price_per_100g": {"type": ["number", "null"]},
                        "confidence": {"type": ["number", "null"]},
                        "notes": {"type": ["string", "null"]},
                    },
                    "required": ["raw_record_id"],
                },
            }
        },
        "required": ["items"],
    }


def provider_from_config(config: ProviderConfigContract) -> ProviderAdapter:
    if config.provider_kind == ProviderKind.GEMINI:
        return GoogleGenAIProvider(config)
    raise ValueError(f"provider adapter not implemented: {config.provider_kind.value}")


def _provider_ref(config: ProviderConfigContract) -> AIProviderRef:
    return AIProviderRef(
        provider_kind=config.provider_kind,
        provider_name=config.provider_id,
        model_name=config.default_model,
        secret_alias=config.secret_alias,
    )


def _learned_match_provider_ref(match: ProductMatchContract) -> AIProviderRef:
    return AIProviderRef(
        provider_kind=ProviderKind.CUSTOM,
        provider_name="learned_match/product_match",
        model_name=match.match_id or "product_match",
    )


def _product_match_source_ids(record: RawCrawlRecord) -> list[str]:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    candidates = [
        raw_payload.get("source_id"),
        raw_payload.get("source"),
        raw_payload.get("store"),
        raw_payload.get("mall"),
        record.source_name,
    ]
    return _unique_non_empty_strings(candidates)


def _product_match_signature_keys(record: RawCrawlRecord) -> list[str]:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    candidates = [
        raw_payload.get("signature_key"),
        raw_payload.get("product_signature"),
        raw_payload.get("source_signature"),
        record.raw_title,
    ]
    return _unique_non_empty_strings(candidates)


def _product_match_package_signature(record: RawCrawlRecord) -> str | None:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    explicit = raw_payload.get("package_signature")
    if explicit:
        return str(explicit)
    quantity = raw_payload.get("package_quantity")
    unit = raw_payload.get("package_unit")
    bundle_count = raw_payload.get("bundle_count")
    if quantity is not None and unit:
        signature = f"package_quantity={quantity};package_unit={unit}"
        if bundle_count is not None:
            signature = f"{signature};bundle_count={bundle_count}"
        return signature
    package = raw_payload.get("package")
    return str(package) if package else None


def _source_product_id(record: RawCrawlRecord) -> str | None:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    for key in ("source_product_id", "product_id", "sku", "source_sku"):
        value = raw_payload.get(key)
        if value not in (None, ""):
            return str(value)
    if record.source_record_key:
        return record.source_record_key
    return None


def _unique_non_empty_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clean_fallback_title(title: str) -> str:
    cleaned = re.sub(r"[\[\(][^\]\)]*(?:할인|쿠폰|특가|증정|단독|청구)[^\]\)]*[\]\)]", " ", title or "")
    cleaned = re.sub(r"\b\d{1,3}\s*%\s*(?:할인|쿠폰)?\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or (title or "").strip()


def _compact_text(value: Any) -> str:
    return "".join(_TEXT_TOKEN_RE.findall(str(value or "").lower()))


def _fallback_category_id(record: RawCrawlRecord) -> str:
    payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    for key in ("category_id", "category_hint", "category", "category_name"):
        category_id = normalize_category_id(payload.get(key))
        if category_id and is_safe_seed_category(category_id):
            return category_id
    compact_title = _compact_text(record.raw_title)
    for category_id, tokens in _FALLBACK_CATEGORY_RULES:
        if any(_compact_text(token) in compact_title for token in tokens):
            return category_id
    return "processed_food"


def _fallback_keywords(record: RawCrawlRecord, *, limit: int = 2) -> list[str]:
    payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    raw_values: list[Any] = []
    for key in ("keywords", "keyword", "tags", "search_terms"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif value not in (None, ""):
            raw_values.append(value)
    title = _clean_fallback_title(record.raw_title)
    raw_values.extend(_TEXT_TOKEN_RE.findall(title))
    keywords: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        token = str(value or "").strip()
        normalized = normalize_keyword(token)
        if (
            len(normalized) < 2
            or normalized.isdigit()
            or normalized in _PROMO_TITLE_TOKENS
            or re.fullmatch(r"\d+(?:g|kg|ml|l|개입|개|입|p|gb)", normalized, flags=re.IGNORECASE)
        ):
            continue
        canonical = canonical_candidate(token)
        if not canonical:
            continue
        key = normalize_keyword(canonical)
        if key in seen:
            continue
        seen.add(key)
        keywords.append(canonical)
        if len(keywords) >= limit:
            break
    return keywords or ["상품"]


def _reviewer_safe_fallback_response_item(record: RawCrawlRecord) -> dict[str, Any]:
    """Create review-only proposals when a provider omits a row after retries."""
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    title = _clean_fallback_title(record.raw_title)
    unit = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=record.raw_price,
        raw_unit=raw_payload.get("unit"),
    )
    package_quantity = unit.get("package_quantity")
    package_unit = unit.get("package_unit")
    display_unit = unit.get("display_unit")
    bundle_count = int(unit.get("bundle_count") or 1)
    standard_unit = unit.get("standard_unit")
    standard_unit_price = unit.get("standard_unit_price")
    if package_quantity is None or not package_unit:
        package_quantity = 1
        package_unit = "개"
        display_unit = "1개"
        bundle_count = 1
        standard_unit = "개"
        standard_unit_price = record.raw_price
    else:
        standard_total = quantity_to_standard_total(package_quantity, package_unit, bundle_count)
        if standard_total is not None:
            total_quantity, standard_unit = standard_total
            if record.raw_price is not None and total_quantity:
                standard_unit_price = round(record.raw_price / total_quantity, 2)
    return {
        "raw_record_id": record.raw_record_id,
        "canonical_name": title,
        "source_title": record.raw_title,
        "sale_price": record.raw_price,
        "original_price": raw_payload.get("original_price"),
        "discount_percent": raw_payload.get("discount_percent"),
        "event_name": raw_payload.get("event_name"),
        "valid_from": raw_payload.get("valid_from") or raw_payload.get("start_date"),
        "valid_to": raw_payload.get("valid_to") or raw_payload.get("end_date"),
        "source_url": record.source_url,
        "image_url": raw_payload.get("image_url") or raw_payload.get("image"),
        "brand": None,
        "category_id": _fallback_category_id(record),
        "keywords": _fallback_keywords(record),
        "aliases": [record.raw_title] if title != record.raw_title else [],
        "attributes": unit.get("attributes") or {},
        "package_quantity": package_quantity,
        "package_unit": package_unit,
        "display_unit": display_unit,
        "bundle_count": bundle_count,
        "standard_unit": standard_unit,
        "standard_unit_price": standard_unit_price,
        "price_per_100g": unit.get("price_per_100g"),
        "confidence": 0.42,
        "notes": "reviewer-safe deterministic fallback for provider-omitted row; human approval required",
    }


def _fallback_proposals_for_missing_records(
    *,
    ai_batch_id: str,
    provider_ref: AIProviderRef,
    records: list[RawCrawlRecord],
    keyword_catalog: list[Any],
    learned_keyword_knowledge: list[Any],
) -> tuple[list[FieldProposal], list[dict[str, Any]], list[RawCrawlRecord], dict[str, Any]]:
    response = {"items": [_reviewer_safe_fallback_response_item(record) for record in records]}
    proposals, keyword_proposals, still_missing, validation = _proposals_from_batch_response(
        ai_batch_id=ai_batch_id,
        provider_ref=provider_ref,
        batch_records=records,
        response=response,
        keyword_catalog=keyword_catalog,
        learned_keyword_knowledge=learned_keyword_knowledge,
    )
    validation["fallback_recovered_count"] = len(records) - len(still_missing)
    validation["fallback_missing_count"] = len(still_missing)
    validation["reason"] = "reviewer_safe_deterministic_recovery_for_provider_omissions"
    return proposals, keyword_proposals, still_missing, validation


def _is_safe_approved_product_match(match: ProductMatchContract) -> bool:
    return (
        match.status == ProductMatchStatus.APPROVED
        and match.provenance_source == ProductMatchProvenanceSource.HUMAN
        and match.is_active
    )


def _find_approved_product_match(
    repository: ProductMatchStoreRepository,
    record: RawCrawlRecord,
) -> ProductMatchContract | None:
    for source_id in _product_match_source_ids(record):
        strict_match = repository.find_strict_approved_match(
            source_id=source_id,
            source_name=record.source_name,
            raw_title=record.raw_title,
            package_signature=_product_match_package_signature(record),
            source_product_id=_source_product_id(record),
        )
        if strict_match is not None and _is_safe_approved_product_match(strict_match):
            return strict_match
        for signature_key in _product_match_signature_keys(record):
            match = repository.get_by_source_signature(
                source_id=source_id,
                source_name=record.source_name,
                signature_key=signature_key,
            )
            if match is not None and _is_safe_approved_product_match(match):
                return match
    return None


def _product_match_response_item(
    *,
    match: ProductMatchContract,
    record: RawCrawlRecord,
) -> dict[str, Any]:
    unit_metadata = dict(match.unit_metadata or {})
    return {
        "raw_record_id": record.raw_record_id,
        "canonical_name": match.canonical_product_name,
        "source_title": record.raw_title,
        "sale_price": record.raw_price,
        "source_url": record.source_url,
        "category_id": match.category_id,
        "keywords": list(match.keywords),
        "aliases": [],
        "attributes": dict(unit_metadata.get("attributes") or {}),
        "package_quantity": unit_metadata.get("package_quantity"),
        "package_unit": unit_metadata.get("package_unit"),
        "display_unit": unit_metadata.get("display_unit"),
        "bundle_count": unit_metadata.get("bundle_count", 1),
        "standard_unit": unit_metadata.get("standard_unit"),
        "standard_unit_price": unit_metadata.get("standard_unit_price"),
        "price_per_100g": unit_metadata.get("price_per_100g"),
        "confidence": match.confidence,
        "notes": (
            "learned_match/product_match "
            f"{match.match_id or match.signature_key}: {match.audit_reason}"
        ),
    }


def _proposals_from_product_match(
    *,
    ai_batch_id: str,
    record: RawCrawlRecord,
    match: ProductMatchContract,
) -> list[FieldProposal]:
    proposals = proposals_from_labeling_response(
        batch_id=ai_batch_id,
        provider=_learned_match_provider_ref(match),
        records=[record],
        response={"items": [_product_match_response_item(match=match, record=record)]},
        require_all_labels=True,
    )
    return [
        proposal.model_copy(update={"status": PipelineStatus.APPROVED})
        for proposal in proposals
    ]


def product_match_precheck(
    *,
    repository: ProductMatchStoreRepository,
    records: list[RawCrawlRecord],
    root_batch_id: str,
) -> tuple[list[FieldProposal], list[RawCrawlRecord], list[dict[str, Any]]]:
    """Reuse human-approved exact source signature matches before provider calls.

    When ``WALLETSAVIOR_AI_LIVE_FORCE=1`` is set in the environment every
    record is treated as unmatched, forcing a real provider call.  Any cache
    hit that would have been returned is logged at WARNING level so auditors
    can measure the natural hit-ratio without requiring a separate dry-run.
    """
    force_live = os.environ.get("WALLETSAVIOR_AI_LIVE_FORCE", "").strip() == "1"
    proposals: list[FieldProposal] = []
    unmatched: list[RawCrawlRecord] = []
    matched: list[dict[str, Any]] = []
    for record in records:
        match = _find_approved_product_match(repository, record)
        if match is None:
            unmatched.append(record)
            continue
        if force_live:
            _logger.warning(
                "[FORCE_LIVE] cache hit bypassed for record %s (match_id=%s) — "
                "WALLETSAVIOR_AI_LIVE_FORCE=1",
                record.raw_record_id,
                match.match_id,
            )
            unmatched.append(record)
            continue
        _record_rule_hit(record.source_name, record.raw_title)
        ai_batch_id = f"{root_batch_id}:match:{record.raw_record_id}"
        proposals.extend(
            _proposals_from_product_match(
                ai_batch_id=ai_batch_id,
                record=record,
                match=match,
            )
        )
        matched.append(
            {
                "raw_record_id": record.raw_record_id,
                "match_id": match.match_id,
                "source": "learned_match/product_match",
                "status": match.status.value,
                "provenance_source": match.provenance_source.value,
            }
        )
    if force_live and unmatched:
        _logger.warning(
            "[FORCE_LIVE] WALLETSAVIOR_AI_LIVE_FORCE=1: all %d records sent to provider (cache bypassed)",
            len(unmatched),
        )
    return proposals, unmatched, matched


def _call_provider_with_retries(
    *,
    provider: ProviderAdapter,
    prompt: str,
    schema: dict[str, Any],
    provider_id: str,
    model: str,
    raw_batch_id: str,
    ai_batch_id: str,
    row_count: int,
    max_call_attempts: int | None = None,
) -> tuple[dict[str, Any], int]:
    last_exc: ProviderResponseError | None = None
    provider_config = provider.config
    max_attempts = int(
        _provider_limit(
            provider_config,
            "provider_retry_max_attempts",
            _MAX_PROVIDER_ATTEMPTS,
        )
    )
    if max_call_attempts is not None:
        max_attempts = min(max_attempts, max(0, int(max_call_attempts)))
    if max_attempts < 1:
        raise AIIngestionError(
            "provider call bound exhausted before request",
            stage="provider_call_bound",
            status_code=429,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            row_count=row_count,
        )
    min_delay_seconds = float(
        _provider_limit(
            provider_config,
            "provider_retry_min_delay_seconds",
            _MIN_PROVIDER_BACKOFF_SECONDS,
        )
    )
    max_delay_seconds = float(
        _provider_limit(
            provider_config,
            "provider_retry_max_delay_seconds",
            _MAX_PROVIDER_BACKOFF_SECONDS,
        )
    )
    for attempt in range(1, max_attempts + 1):
        if _is_live_provider(provider):
            _reserve_live_provider_call(provider_id, provider_config)
        try:
            return provider.call(prompt=prompt, schema=schema), attempt
        except ProviderResponseError as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_transient_provider_error(exc):
                raise AIIngestionError(
                    f"{str(exc)} (attempt {attempt}/{max_attempts})",
                    stage="provider_call",
                    status_code=502,
                    provider_id=exc.provider_id or provider_id,
                    model=exc.model or model,
                    raw_batch_id=raw_batch_id,
                    ai_batch_id=ai_batch_id,
                    row_count=row_count,
                    invalid_rows=getattr(exc, "invalid_rows", []),
                    provider_error_detail=exc.to_detail(),
                ) from exc
            delay = min(
                max_delay_seconds,
                min_delay_seconds * (2 ** (attempt - 1)),
            )
            _sleep(delay)
    raise AIIngestionError(
        str(last_exc) if last_exc else "provider call failed",
        stage="provider_call",
        status_code=502,
        provider_id=provider_id,
        model=model,
        raw_batch_id=raw_batch_id,
        ai_batch_id=ai_batch_id,
        row_count=row_count,
    )


def _call_provider_with_shrink_retries(
    *,
    records: list[RawCrawlRecord],
    provider: ProviderAdapter,
    provider_ref: AIProviderRef,
    provider_id: str,
    model: str,
    raw_batch_id: str,
    ai_batch_id: str,
    keyword_catalog: list[Any],
    learned_keyword_knowledge: list[Any],
    max_prompt_chars: int | None = None,
    _shrink_log: list[dict[str, Any]] | None = None,
) -> tuple[list[FieldProposal], list[dict[str, Any]], list[dict[str, Any]]]:
    """배치 크기를 절반씩 축소하며 재시도하는 provider 호출 함수.

    기존 _call_provider_with_retries는 동일 배치·동일 크기로 최대 3회 재시도한다.
    이 함수는 그 대신 실패 시 배치를 절반으로 분할해 각각 독립 호출한다.
    단일 아이템(N=1)이 retryable 실패하거나 빈 응답을 반환하면 더 이상 쪼갤 수 없으므로
    _fallback_proposals_for_missing_records()를 호출해 인간 리뷰 큐로 폴백한다.

    이렇게 설계한 이유: provider quota·timeout 오류는 배치가 클수록 자주 발생하며,
    절반씩 쪼개면 성공률이 올라가고 무한 재시도 루프 없이 전체 처리가 완료된다.
    분할 깊이는 log₂(N)으로 자연 상한되어 무한 분할이 발생하지 않는다.
    다음 AI가 이 함수를 "비효율적인 재시도 루프"로 오해해 리팩토링하지 않도록
    이 분할 전략이 의도적임을 명시한다.

    Returns:
        (proposals, keyword_proposals, shrink_log)
        shrink_log: 각 provider 호출 시도의 기록 목록.
            outcome 값:
              "ok"              — 호출 성공 (일부 items 누락 시에도 ok)
              "retryable_error" — 재시도 가능한 오류 또는 빈 응답
              "fallback"        — N=1 최종 실패로 인한 인간 큐 폴백
    """
    if _shrink_log is None:
        _shrink_log = []
    n = len(records)

    try:
        prompt = build_labeling_prompt(
            records,
            catalog=keyword_catalog,
            learned_knowledge=learned_keyword_knowledge,
            max_prompt_chars=max_prompt_chars,
        )
    except ValueError as exc:
        raise AIIngestionError(
            str(exc),
            stage="batch_validation",
            status_code=400,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            row_count=n,
        ) from exc

    if _is_live_provider(provider):
        _reserve_live_provider_call(provider_id, provider.config)

    try:
        response = provider.call(prompt=prompt, schema=labeling_response_schema())
    except ProviderConfigurationError as exc:
        raise AIIngestionError(
            str(exc),
            stage="provider_configuration",
            status_code=400,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            row_count=n,
        ) from exc
    except ProviderResponseError as exc:
        if not _is_transient_provider_error(exc):
            # non-retryable (400, schema error 등) — 즉시 raise, 분할하지 않는다.
            raise AIIngestionError(
                str(exc),
                stage="provider_call",
                status_code=502,
                provider_id=exc.provider_id or provider_id,
                model=exc.model or model,
                raw_batch_id=raw_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=n,
                invalid_rows=getattr(exc, "invalid_rows", []),
                provider_error_detail=exc.to_detail(),
            ) from exc
        # retryable (quota, timeout, 5xx) — 배치를 분할하거나 단일 아이템을 폴백한다.
        _shrink_log.append({"batch_size": n, "outcome": "retryable_error"})
        return _shrink_split_or_fallback(
            records=records,
            provider=provider,
            provider_ref=provider_ref,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_keyword_knowledge,
            max_prompt_chars=max_prompt_chars,
            shrink_log=_shrink_log,
        )

    # 호출 성공 — 응답을 파싱하고 누락 아이템을 확인한다.
    try:
        proposals, keyword_proposals, missing_records, _id_validation = _proposals_from_batch_response(
            ai_batch_id=ai_batch_id,
            provider_ref=provider_ref,
            batch_records=records,
            response=response,
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_keyword_knowledge,
        )
    except ProviderResponseError as exc:
        raise AIIngestionError(
            str(exc),
            stage="provider_response_validation",
            status_code=502,
            provider_id=exc.provider_id or provider_id,
            model=exc.model or model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            row_count=n,
            invalid_rows=getattr(exc, "invalid_rows", []),
        ) from exc

    if len(missing_records) == n:
        # 빈 응답: 호출은 성공했지만 모든 아이템이 누락 — retryable failure로 간주한다.
        _shrink_log.append({"batch_size": n, "outcome": "retryable_error"})
        return _shrink_split_or_fallback(
            records=records,
            provider=provider,
            provider_ref=provider_ref,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_keyword_knowledge,
            max_prompt_chars=max_prompt_chars,
            shrink_log=_shrink_log,
        )

    # 부분 또는 완전 성공
    _shrink_log.append({"batch_size": n, "outcome": "ok"})

    if missing_records:
        # 부분 성공: 누락된 아이템에 대해 동일한 shrink 메커니즘을 재귀 적용한다.
        missing_proposals, missing_kw, _ = _call_provider_with_shrink_retries(
            records=missing_records,
            provider=provider,
            provider_ref=provider_ref,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=f"{ai_batch_id}:missing",
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_keyword_knowledge,
            max_prompt_chars=max_prompt_chars,
            _shrink_log=_shrink_log,
        )
        proposals.extend(missing_proposals)
        keyword_proposals.extend(missing_kw)

    return proposals, keyword_proposals, _shrink_log


def _shrink_split_or_fallback(
    *,
    records: list[RawCrawlRecord],
    provider: ProviderAdapter,
    provider_ref: AIProviderRef,
    provider_id: str,
    model: str,
    raw_batch_id: str,
    ai_batch_id: str,
    keyword_catalog: list[Any],
    learned_keyword_knowledge: list[Any],
    max_prompt_chars: int | None,
    shrink_log: list[dict[str, Any]],
) -> tuple[list[FieldProposal], list[dict[str, Any]], list[dict[str, Any]]]:
    """retryable 실패 후 N>=2이면 절반씩 분할해 재귀 호출, N==1이면 인간 큐로 폴백하는 헬퍼.

    이 함수는 _call_provider_with_shrink_retries의 분할/폴백 경로를 분리해
    가독성을 높인다. shrink_log는 공유 참조로 전달되어 모든 재귀 호출이 동일 로그에
    기록된다. provider는 rate 보호를 위해 순차 호출(병렬 금지)한다.
    """
    n = len(records)
    if n == 1:
        # 더 이상 분할 불가 — 인간 리뷰 큐로 폴백
        return _shrink_fallback_single(
            record=records[0],
            provider_ref=provider_ref,
            provider_id=provider_id,
            model=model,
            raw_batch_id=raw_batch_id,
            ai_batch_id=ai_batch_id,
            keyword_catalog=keyword_catalog,
            learned_keyword_knowledge=learned_keyword_knowledge,
            shrink_log=shrink_log,
        )
    mid = n // 2
    left_proposals, left_kw, _ = _call_provider_with_shrink_retries(
        records=records[:mid],
        provider=provider,
        provider_ref=provider_ref,
        provider_id=provider_id,
        model=model,
        raw_batch_id=raw_batch_id,
        ai_batch_id=f"{ai_batch_id}:s0",
        keyword_catalog=keyword_catalog,
        learned_keyword_knowledge=learned_keyword_knowledge,
        max_prompt_chars=max_prompt_chars,
        _shrink_log=shrink_log,
    )
    right_proposals, right_kw, _ = _call_provider_with_shrink_retries(
        records=records[mid:],
        provider=provider,
        provider_ref=provider_ref,
        provider_id=provider_id,
        model=model,
        raw_batch_id=raw_batch_id,
        ai_batch_id=f"{ai_batch_id}:s1",
        keyword_catalog=keyword_catalog,
        learned_keyword_knowledge=learned_keyword_knowledge,
        max_prompt_chars=max_prompt_chars,
        _shrink_log=shrink_log,
    )
    return left_proposals + right_proposals, left_kw + right_kw, shrink_log


def _shrink_fallback_single(
    *,
    record: RawCrawlRecord,
    provider_ref: AIProviderRef,
    provider_id: str,
    model: str,
    raw_batch_id: str,
    ai_batch_id: str,
    keyword_catalog: list[Any],
    learned_keyword_knowledge: list[Any],
    shrink_log: list[dict[str, Any]],
) -> tuple[list[FieldProposal], list[dict[str, Any]], list[dict[str, Any]]]:
    """N=1 배치가 retryable 에러로 실패했을 때 인간 리뷰 큐로 폴백하는 헬퍼.

    더 이상 배치를 쪼갤 수 없는 단일 아이템은 confidence=0.42 reviewer-safe fallback
    proposal로 생성돼 인간 큐에 투입된다. shrink_log에 fallback=True를 기록해
    자동 라벨링이 아님을 명시한다.
    """
    fallback_batch_id = f"{ai_batch_id}:fallback"
    proposals, keyword_proposals, _still_missing, _validation = _fallback_proposals_for_missing_records(
        ai_batch_id=fallback_batch_id,
        provider_ref=provider_ref,
        records=[record],
        keyword_catalog=keyword_catalog,
        learned_keyword_knowledge=learned_keyword_knowledge,
    )
    shrink_log.append({"batch_size": 1, "outcome": "fallback", "fallback": True})
    return proposals, keyword_proposals, shrink_log


def _proposals_from_batch_response(
    *,
    ai_batch_id: str,
    provider_ref: AIProviderRef,
    batch_records: list[RawCrawlRecord],
    response: dict[str, Any],
    keyword_catalog: list[Any],
    learned_keyword_knowledge: list[Any],
) -> tuple[list[FieldProposal], list[dict[str, Any]], list[RawCrawlRecord], dict[str, Any]]:
    response, id_validation = _provider_response_id_validation(
        batch_records=batch_records,
        response=response,
    )
    items = response.get("items")
    matched_keywords_by_record: dict[str, list[dict[str, Any]]] = {}
    keyword_proposals: list[dict[str, Any]] = []
    if isinstance(items, list):
        matched_keywords_by_record, keyword_proposals = build_keyword_outputs(
            batch_id=ai_batch_id,
            records=batch_records,
            response_items=items,
            catalog=keyword_catalog,
            learned_knowledge=learned_keyword_knowledge,
        )
    proposals = proposals_from_labeling_response(
        batch_id=ai_batch_id,
        provider=provider_ref,
        records=batch_records,
        response=response,
        matched_keywords_by_record=matched_keywords_by_record,
        require_all_labels=False,
    )
    labeled_ids = {
        item.get("raw_record_id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("raw_record_id"), str)
    } if isinstance(items, list) else set()
    missing_records = [
        record
        for record in batch_records
        if record.raw_record_id not in labeled_ids
    ]
    return proposals, keyword_proposals, missing_records, id_validation


def _proposal(
    *,
    batch_id: str,
    provider: AIProviderRef,
    item: dict[str, Any],
    record: RawCrawlRecord,
    role: AIWorkerRole,
    proposal_type: ProposalType,
    target_field: str,
    proposed_value: Any,
    evidence_text: str,
    suffix: str,
) -> FieldProposal:
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    return FieldProposal(
        proposal_id=f"{batch_id}:{role.value}:{record.raw_record_id}:{target_field}:{suffix}",
        proposal_type=proposal_type,
        target_field=target_field,
        proposed_value=proposed_value,
        status=PipelineStatus.AI_PROPOSED,
        provenance=FieldProvenance(
            raw_record_id=record.raw_record_id,
            source_field="raw_title",
            evidence_text=evidence_text,
            worker_role=role,
            provider=provider,
            confidence=confidence,
        ),
    )


def proposals_from_labeling_response(
    *,
    batch_id: str,
    provider: AIProviderRef,
    records: list[RawCrawlRecord],
    response: dict[str, Any],
    matched_keywords_by_record: dict[str, list[dict[str, Any]]] | None = None,
    require_all_labels: bool = True,
) -> list[FieldProposal]:
    record_by_id = {record.raw_record_id: record for record in records}

    def response_error(
        message: str,
        *,
        item_index: int | None = None,
        raw_record_id: str | None = None,
        field: str | None = None,
    ) -> ProviderResponseError:
        invalid_rows = []
        if item_index is not None or raw_record_id is not None or field is not None:
            invalid_rows.append(
                {
                    "item_index": item_index,
                    "raw_record_id": raw_record_id,
                    "field": field,
                    "reason": message,
                }
            )
        return ProviderResponseError(
            message,
            provider_id=provider.provider_name,
            model=provider.model_name,
            invalid_rows=invalid_rows,
        )

    items = response.get("items")
    if not isinstance(items, list):
        raise response_error("provider response must contain items list", field="items")
    seen_ids: set[str] = set()
    proposals: list[FieldProposal] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise response_error(
                f"provider response item {index} must be an object",
                item_index=index,
            )
        record_id = item.get("raw_record_id")
        if not isinstance(record_id, str) or record_id not in record_by_id:
            raise response_error(
                f"provider response item {index} has unknown raw_record_id",
                item_index=index,
                raw_record_id=record_id if isinstance(record_id, str) else None,
                field="raw_record_id",
            )
        if record_id in seen_ids:
            raise response_error(
                f"provider response contains duplicate raw_record_id: {record_id}",
                item_index=index,
                raw_record_id=record_id,
                field="raw_record_id",
            )
        seen_ids.add(record_id)
        for list_field in ("keywords", "aliases"):
            value = item.get(list_field)
            if value is not None and (
                not isinstance(value, list)
                or not all(isinstance(entry, str) for entry in value)
            ):
                raise response_error(
                    f"provider response field {list_field} for {record_id} must be a list of strings",
                    item_index=index,
                    raw_record_id=record_id,
                    field=list_field,
                )
        attributes = item.get("attributes")
        if attributes is not None and not isinstance(attributes, dict):
            raise response_error(
                f"provider response field attributes for {record_id} must be an object",
                item_index=index,
                raw_record_id=record_id,
                field="attributes",
            )
        record = record_by_id[record_id]
        evidence = item.get("notes") or record.raw_title
        deterministic_unit = normalize_unit_metadata(
            name=record.raw_title,
            sale_price=record.raw_price,
            raw_unit=record.raw_payload.get("unit") if isinstance(record.raw_payload, dict) else None,
        )
        if deterministic_unit.get("package_quantity") is not None:
            bundle_count = int(deterministic_unit.get("bundle_count") or 1)
            item = {
                **item,
                "package_quantity": deterministic_unit["package_quantity"],
                "package_unit": deterministic_unit["package_unit"],
                "display_unit": deterministic_unit["display_unit"],
                "bundle_count": bundle_count,
                "price_per_100g": deterministic_unit["price_per_100g"],
            }
            standard_total = quantity_to_standard_total(
                deterministic_unit["package_quantity"],
                deterministic_unit["package_unit"],
                bundle_count,
            )
            if standard_total is not None:
                total_quantity, standard_unit = standard_total
                item["standard_unit"] = standard_unit
                if record.raw_price is not None:
                    item["standard_unit_price"] = round(record.raw_price / total_quantity, 2)
        if deterministic_unit.get("attributes"):
            attributes = {**(attributes or {}), **deterministic_unit["attributes"]}
        if item.get("category_id") not in (None, ""):
            item = {
                **item,
                "category_id": normalize_category_id(item.get("category_id")),
                "category_display_label": get_category_display_label(item.get("category_id")),
            }
        for positive_field in ("package_quantity", "bundle_count"):
            positive_value = item.get(positive_field)
            if positive_value in (None, ""):
                continue
            try:
                is_invalid_positive = float(positive_value) <= 0
            except (TypeError, ValueError):
                raise response_error(
                    f"provider response field {positive_field} for {record_id} must be a positive number",
                    item_index=index,
                    raw_record_id=record_id,
                    field=positive_field,
                )
            if is_invalid_positive:
                raise response_error(
                    f"provider response field {positive_field} for {record_id} must be greater than zero",
                    item_index=index,
                    raw_record_id=record_id,
                    field=positive_field,
                )

        scalar_fields: tuple[tuple[str, AIWorkerRole, ProposalType], ...] = (
            ("canonical_name", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("source_title", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("brand", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("category_id", AIWorkerRole.CLASSIFIER, ProposalType.CATEGORY),
            ("sale_price", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("original_price", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("discount_percent", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("event_name", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("valid_from", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("valid_to", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("source_url", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("image_url", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("package_quantity", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("package_unit", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("display_unit", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("bundle_count", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("standard_unit", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            (
                "standard_unit_price",
                AIWorkerRole.UNIT_CONVERTER,
                ProposalType.NORMALIZED_FIELD,
            ),
            ("price_per_100g", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
        )
        for field, role, proposal_type in scalar_fields:
            value = item.get(field)
            if value is not None and value != "":
                proposals.append(
                    _proposal(
                        batch_id=batch_id,
                        provider=provider,
                        item=item,
                        record=record,
                        role=role,
                        proposal_type=proposal_type,
                        target_field=field,
                        proposed_value=value,
                        evidence_text=str(evidence),
                        suffix=field,
                    )
                )

        if isinstance(attributes, dict):
            for attr_name, attr_value in sorted(attributes.items()):
                if attr_value is None or attr_value == "":
                    continue
                proposals.append(
                    _proposal(
                        batch_id=batch_id,
                        provider=provider,
                        item=item,
                        record=record,
                        role=AIWorkerRole.CLASSIFIER,
                        proposal_type=ProposalType.ATTRIBUTE_VALUE,
                        target_field=f"attributes.{attr_name}",
                        proposed_value=attr_value,
                        evidence_text=str(evidence),
                        suffix=f"attr:{attr_name}",
                    )
                )

        keyword_values = item.get("keywords") or []
        attribute_labels = {
            str(value).strip()
            for key, value in (attributes or {}).items()
            if key.endswith("_label") and str(value).strip()
        }
        keyword_values = [
            keyword
            for keyword in keyword_values
            if not (isinstance(keyword, str) and keyword.strip() in attribute_labels)
        ]
        catalog_matches = (
            matched_keywords_by_record.get(record.raw_record_id, [])
            if matched_keywords_by_record is not None
            else []
        )
        if catalog_matches:
            keyword_values = [match["word"] for match in catalog_matches if match.get("word")]
        for index, keyword in enumerate(keyword_values):
            if isinstance(keyword, str) and keyword.strip():
                alternatives = []
                if matched_keywords_by_record is not None:
                    alternatives = [
                        match
                        for match in matched_keywords_by_record.get(record.raw_record_id, [])
                        if match.get("word") == keyword.strip()
                    ]
                proposals.append(
                    _proposal(
                        batch_id=batch_id,
                        provider=provider,
                        item=item,
                        record=record,
                        role=AIWorkerRole.KEYWORD_GENERATOR,
                        proposal_type=ProposalType.KEYWORD,
                        target_field="keywords",
                        proposed_value=keyword.strip(),
                        evidence_text=str(evidence),
                        suffix=f"kw:{index}",
                    ).model_copy(update={"alternatives": alternatives})
                )
        for index, alias in enumerate(item.get("aliases") or []):
            if isinstance(alias, str) and alias.strip():
                proposals.append(
                    _proposal(
                        batch_id=batch_id,
                        provider=provider,
                        item=item,
                        record=record,
                        role=AIWorkerRole.KEYWORD_GENERATOR,
                        proposal_type=ProposalType.ALIAS,
                        target_field="aliases",
                        proposed_value=alias.strip(),
                        evidence_text=str(evidence),
                        suffix=f"alias:{index}",
                    )
                )
    missing_ids = set(record_by_id) - seen_ids
    if missing_ids and require_all_labels:
        missing = ", ".join(sorted(missing_ids)[:5])
        raise response_error(
            f"provider response missing labels for raw_record_id(s): {missing}",
            field="items",
        )
    return proposals


def ingest_and_label_records(
    *,
    session: Session,
    provider_id: str,
    records: list[RawCrawlRecord],
    source_name: str,
    crawler_name: str,
    schema_type: str,
    max_ai_batch_items: int | None = None,
    max_ai_batch_prompt_chars: int | None = None,
    max_provider_calls: int | None = None,
    provider_factory=None,
) -> dict[str, Any]:
    if not WALLETSAVIOR_LIVE_AI_ENABLED:
        raise AIIngestionError(
            "live AI pipeline is currently disabled; use external classification workflow",
            stage="deprecated",
            status_code=503,
            provider_id=provider_id,
            row_count=len(records),
        )
    
    provider_config = ProviderConfigRepository(session).get(provider_id)
    if provider_config is None:
        raise AIIngestionError(
            "provider not found",
            stage="provider_lookup",
            status_code=400,
            provider_id=provider_id,
            row_count=len(records),
        )
    factory = provider_factory or provider_from_config
    try:
        provider = factory(provider_config)
    except ValueError as exc:
        raise AIIngestionError(
            str(exc),
            stage="provider_setup",
            status_code=400,
            provider_id=provider_id,
            model=provider_config.default_model,
            row_count=len(records),
        ) from exc
    provider_ref = _provider_ref(provider_config)

    root_batch_id = f"raw-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    raw_repo = RawCrawlBatchRepository(session)
    try:
        raw_repo.save(
            RawCrawlBatchContract(
                batch_id=root_batch_id,
                source_name=source_name,
                crawler_name=crawler_name,
                item_count=len(records),
                schema_type=schema_type,
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo.save_records(root_batch_id, records)
        session.commit()
    except Exception as exc:
        raise AIIngestionError(
            "failed to store raw crawl records for AI ingestion",
            stage="raw_record_storage",
            status_code=500,
            provider_id=provider_id,
            model=provider_config.default_model,
            raw_batch_id=root_batch_id,
            row_count=len(records),
        ) from exc

    proposal_repo = FieldProposalRepository(session)
    keyword_proposal_repo = KeywordProposalRepository(session)
    keyword_catalog = KeywordCatalogAdapter().list_keywords()
    learned_keyword_knowledge = LearnedKnowledgeRepository(session).list(active_only=True)
    matched_proposals, provider_records, product_match_results = product_match_precheck(
        repository=ProductMatchStoreRepository(session),
        records=records,
        root_batch_id=root_batch_id,
    )
    try:
        configured_batch_items, configured_prompt_chars = _validate_ai_batch_limits(
            max_batch_items=max_ai_batch_items,
            max_prompt_chars=max_ai_batch_prompt_chars,
        )
        split_batches, split_truncations = split_records_for_ai(
            provider_records,
            catalog=keyword_catalog,
            learned_knowledge=learned_keyword_knowledge,
            max_batch_items=max_ai_batch_items,
            max_prompt_chars=max_ai_batch_prompt_chars,
        )
        # rd3-422-fix: 잘린 record 가 있으면 응답에 구조화 메타로 surface.
        # 사용자 헌법: "오류가 발생하면 정확히 어디서 어떤 종류의 에러가 발생한
        # 건지 검증할 수도 있어야". 단순 warning log 만으로는 검증 불가.
    except ValueError as exc:
        raise AIIngestionError(
            str(exc),
            stage="batch_validation",
            status_code=400,
            provider_id=provider_id,
            model=provider_config.default_model,
            raw_batch_id=root_batch_id,
            row_count=len(records),
        ) from exc
    all_proposals: list[FieldProposal] = list(matched_proposals)
    all_keyword_proposals: list[dict[str, Any]] = []
    missing_label_ids: list[str] = []
    provider_response_validations: list[dict[str, Any]] = []
    deterministic_recovery_count = 0
    calls = 0
    for index, batch_records in enumerate(split_batches, start=1):
        ai_batch_id = f"{root_batch_id}:ai:{index}"
        if max_provider_calls is not None and calls >= max_provider_calls:
            missing_label_ids.extend(record.raw_record_id for record in batch_records)
            continue
        try:
            prompt = build_labeling_prompt(
                batch_records,
                catalog=keyword_catalog,
                learned_knowledge=learned_keyword_knowledge,
                max_prompt_chars=max_ai_batch_prompt_chars,
            )
        except ValueError as exc:
            raise AIIngestionError(
                str(exc),
                stage="batch_validation",
                status_code=400,
                provider_id=provider_id,
                model=provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
            ) from exc
        try:
            response, attempts = _call_provider_with_retries(
                provider=provider,
                prompt=prompt,
                schema=labeling_response_schema(),
                provider_id=provider_id,
                model=provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
                max_call_attempts=(
                    None if max_provider_calls is None else max_provider_calls - calls
                ),
            )
        except ProviderConfigurationError as exc:
            raise AIIngestionError(
                str(exc),
                stage="provider_configuration",
                status_code=400,
                provider_id=provider_id,
                model=provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
            ) from exc
        except ProviderResponseError as exc:
            # rd5-partial-save-fix: 사용자 직격 "ai 요청 몇 번 발생했는데도 싹 다 결과물 날리네".
            # 한 sub-batch 가 504/quota 등으로 retry 다 소진했다고 해서 이미 성공한 다른
            # sub-batch 의 proposals 까지 통째로 날리지 않는다. 이 batch 의 record 만 missing
            # 으로 기록하고 루프를 계속한다. 마지막에 missing > 0 이면 status=partial_review_required.
            provider_response_validations.append(
                {
                    "ai_batch_id": ai_batch_id,
                    "provider_call_failed": True,
                    "error": str(exc),
                    "row_count": len(batch_records),
                }
            )
            missing_label_ids.extend(record.raw_record_id for record in batch_records)
            calls += getattr(exc, "attempts", 0) or 1
            continue
        except AIIngestionError as exc:
            # rd5-partial-save-fix-2: _call_provider_with_retries 가 3회 retry 소진 후 raise
            # 하는 경우는 ProviderResponseError 가 아니라 AIIngestionError(stage=provider_call,
            # status=502) 다. 사용자 직격 "504 DEADLINE_EXCEEDED ... ai 요청 몇 번 발생했는데도
            # 싹 다 결과물 날리네" 의 진짜 원인. 이 sub-batch 만 missing 으로 기록하고 다음
            # sub-batch 로 진행. provider_configuration / batch_validation / response_validation
            # 처럼 코드/스키마/설정 결함은 즉시 재raise — partial save 의미가 없다.
            partial_save_stages = {"provider_call", "provider_call_bound", "provider_rate_limit"}
            if exc.stage not in partial_save_stages:
                raise
            provider_response_validations.append(
                {
                    "ai_batch_id": ai_batch_id,
                    "provider_call_failed": True,
                    "error": str(exc),
                    "row_count": len(batch_records),
                    "stage": exc.stage,
                }
            )
            missing_label_ids.extend(record.raw_record_id for record in batch_records)
            calls += 1
            continue
        calls += attempts
        try:
            proposals, keyword_proposals, missing_records, response_validation = _proposals_from_batch_response(
                ai_batch_id=ai_batch_id,
                provider_ref=provider_ref,
                batch_records=batch_records,
                response=response,
                keyword_catalog=keyword_catalog,
                learned_keyword_knowledge=learned_keyword_knowledge,
            )
            response_validation["ai_batch_id"] = ai_batch_id
            provider_response_validations.append(response_validation)
        except ProviderResponseError as exc:
            raise AIIngestionError(
                str(exc),
                stage="provider_response_validation",
                status_code=502,
                provider_id=exc.provider_id or provider_id,
                model=exc.model or provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
                invalid_rows=getattr(exc, "invalid_rows", []),
            ) from exc
        for retry_index in range(1, _MISSING_LABEL_RETRY_BATCHES + 1):
            if not missing_records:
                break
            if max_provider_calls is not None and calls >= max_provider_calls:
                break
            retry_batch_id = f"{ai_batch_id}:retry:{retry_index}"
            try:
                retry_prompt = build_labeling_prompt(
                    missing_records,
                    catalog=keyword_catalog,
                    learned_knowledge=learned_keyword_knowledge,
                    max_prompt_chars=max_ai_batch_prompt_chars,
                )
                retry_response, retry_attempts = _call_provider_with_retries(
                    provider=provider,
                    prompt=retry_prompt,
                    schema=labeling_response_schema(),
                    provider_id=provider_id,
                    model=provider_config.default_model,
                    raw_batch_id=root_batch_id,
                    ai_batch_id=retry_batch_id,
                    row_count=len(missing_records),
                    max_call_attempts=(
                        None if max_provider_calls is None else max_provider_calls - calls
                    ),
                )
                calls += retry_attempts
                retry_proposals, retry_keyword_proposals, missing_records, retry_validation = _proposals_from_batch_response(
                    ai_batch_id=retry_batch_id,
                    provider_ref=provider_ref,
                    batch_records=missing_records,
                    response=retry_response,
                    keyword_catalog=keyword_catalog,
                    learned_keyword_knowledge=learned_keyword_knowledge,
                )
                retry_validation["ai_batch_id"] = retry_batch_id
                provider_response_validations.append(retry_validation)
            except ProviderResponseError as exc:
                raise AIIngestionError(
                    str(exc),
                    stage="provider_response_validation",
                    status_code=502,
                    provider_id=exc.provider_id or provider_id,
                    model=exc.model or provider_config.default_model,
                    raw_batch_id=root_batch_id,
                    ai_batch_id=retry_batch_id,
                    row_count=len(missing_records),
                    invalid_rows=getattr(exc, "invalid_rows", []),
                ) from exc
            proposals.extend(retry_proposals)
            keyword_proposals.extend(retry_keyword_proposals)
        if missing_records:
            fallback_batch_id = f"{ai_batch_id}:fallback"
            fallback_proposals, fallback_keyword_proposals, missing_records, fallback_validation = _fallback_proposals_for_missing_records(
                ai_batch_id=fallback_batch_id,
                provider_ref=provider_ref,
                records=missing_records,
                keyword_catalog=keyword_catalog,
                learned_keyword_knowledge=learned_keyword_knowledge,
            )
            fallback_validation["ai_batch_id"] = fallback_batch_id
            provider_response_validations.append(fallback_validation)
            deterministic_recovery_count += int(fallback_validation.get("fallback_recovered_count") or 0)
            proposals.extend(fallback_proposals)
            keyword_proposals.extend(fallback_keyword_proposals)
        missing_label_ids.extend(record.raw_record_id for record in missing_records)
        all_proposals.extend(proposals)
        all_keyword_proposals.extend(keyword_proposals)

    try:
        for proposal in all_proposals:
            proposal_repo.save(proposal)
        for keyword_proposal in all_keyword_proposals:
            keyword_proposal_repo.save(keyword_proposal)
    except Exception as exc:
        raise AIIngestionError(
            "failed to store AI review proposals",
            stage="review_queue_storage",
            status_code=500,
            provider_id=provider_id,
            model=provider_config.default_model,
            raw_batch_id=root_batch_id,
            row_count=len(records),
        ) from exc

    missing_label_ids = list(dict.fromkeys(missing_label_ids))
    invalid_response_rows = [
        row
        for validation in provider_response_validations
        for row in validation.get("invalid_response_rows", [])
    ]
    index_mappings = [
        row
        for validation in provider_response_validations
        for row in validation.get("index_mappings", [])
    ]
    return {
        "status": "partial_review_required" if missing_label_ids else "labeled",
        "raw_batch_id": root_batch_id,
        "records_stored": len(records),
        "ai_batches": len(split_batches),
        "max_ai_batch_items": configured_batch_items,
        "max_ai_batch_prompt_chars": configured_prompt_chars,
        "provider_calls": calls,
        "product_match_hits": len(product_match_results),
        "product_match_results": product_match_results,
        "deterministic_recovery_count": deterministic_recovery_count,
        "proposals_stored": len(all_proposals),
        "keyword_proposals_stored": len(all_keyword_proposals),
        "missing_label_count": len(missing_label_ids),
        "missing_label_raw_record_ids": missing_label_ids,
        "oversized_truncations": split_truncations,
        "oversized_truncations_count": len(split_truncations),
        "reviewer_retry_candidates": {
            "missing_label": [
                {
                    "raw_record_id": raw_record_id,
                    "reason": "provider returned no usable item for this row",
                }
                for raw_record_id in missing_label_ids
            ]
        },
        "provider_response_validation": {
            "invalid_response_row_count": len(invalid_response_rows),
            "invalid_response_rows": invalid_response_rows,
            "index_mapping_count": len(index_mappings),
            "index_mappings": index_mappings,
            "batch_summaries": provider_response_validations,
            "reason": (
                "provider returned unknown or missing raw_record_id values; known rows were retained and unknown rows were not stored"
                if invalid_response_rows
                else None
            ),
        },
        "proposal_ids": [proposal.proposal_id for proposal in all_proposals],
        "keyword_proposal_ids": [
            proposal["proposal_id"] for proposal in all_keyword_proposals
        ],
    }
