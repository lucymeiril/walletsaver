"""Raw crawl ingestion and provider-backed labeling service."""
from __future__ import annotations

from datetime import datetime
import re
import time
from typing import Any, Protocol
from uuid import uuid4

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
from core.contracts.control_plane import ProviderConfigContract, RawCrawlBatchContract
from providers import GoogleGenAIProvider
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from core.product_units import normalize_unit_metadata, quantity_to_standard_total
from storage.repositories import (
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
)
from services.keyword_catalog import KeywordCatalogAdapter, build_keyword_outputs


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
_MIN_PROVIDER_BACKOFF_SECONDS = 0.25
_MAX_PROVIDER_BACKOFF_SECONDS = 2.0
_PROVIDER_COOLDOWN_SECONDS = 0.25
_provider_cooldown_until: dict[str, float] = {}
_sleep = time.sleep
_monotonic = time.monotonic


_LABELING_PROMPT_PREFIX = [
    "WalletSavior raw product data labeling task.",
    "First reuse existing DB keywords/match terms when provided by system context.",
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
    "If source hints say unit=100g but the title contains a package size like 300g/(200g), treat the raw price as pack price; set package/display unit from the title and calculate price_per_100g separately.",
    "Put storage/origin/cut/grade facts such as 냉장, 냉동, 베트남, 불고기, 1+등급 in attributes, not keywords.",
    "Use a broad canonical keyword instead of promotional/country variants when possible (e.g. 두부, not 국산두부 or 행사두부).",
    "Records:",
]


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


def _record_prompt_line(record: RawCrawlRecord) -> str:
    hints = []
    for key in (
        "unit",
        "quantity",
        "category",
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
        f"- id={record.raw_record_id}; source={record.source_name}; "
        f"title={record.raw_title}; price={record.raw_price}{source_url}{hint_text}"
    )


def _catalog_prompt_lines(
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
) -> list[str]:
    lines: list[str] = []
    if catalog:
        lines.append("Existing DB keyword catalog (reuse these words/synonyms; do not propose duplicates):")
        for keyword in catalog[:80]:
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


def _prompt_chars_for(
    records: list[RawCrawlRecord],
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
) -> int:
    context = _catalog_prompt_lines(catalog, learned_knowledge)
    if not records:
        return len("\n".join([*_LABELING_PROMPT_PREFIX[:-1], *context, "Records:"]))
    return len(
        "\n".join(
            [
                *_LABELING_PROMPT_PREFIX[:-1],
                *context,
                "Records:",
                *[_record_prompt_line(r) for r in records],
            ]
        )
    )


class ProviderAdapter(Protocol):
    config: ProviderConfigContract

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


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
        return detail


def split_records_for_ai(
    records: list[RawCrawlRecord],
    *,
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
) -> list[list[RawCrawlRecord]]:
    """Split records without cutting a record across batches."""
    batches: list[list[RawCrawlRecord]] = []
    current: list[RawCrawlRecord] = []
    for record in records:
        record_chars = _prompt_chars_for([record], catalog, learned_knowledge)
        if record_chars > MAX_AI_BATCH_PROMPT_CHARS:
            raise ValueError(
                f"record {record.raw_record_id} is {record_chars} chars; "
                f"max batch prompt chars is {MAX_AI_BATCH_PROMPT_CHARS}"
            )
        would_exceed = (
            len(current) >= MAX_AI_BATCH_ITEMS
            or _prompt_chars_for([*current, record], catalog, learned_knowledge) > MAX_AI_BATCH_PROMPT_CHARS
        )
        if current and would_exceed:
            batches.append(current)
            current = []
        current.append(record)
    if current:
        batches.append(current)
    return batches


def build_labeling_prompt(
    records: list[RawCrawlRecord],
    *,
    catalog: list[Any] | None = None,
    learned_knowledge: list[Any] | None = None,
) -> str:
    """Build a strict JSON prompt for product labeling/classification."""
    lines = [*_LABELING_PROMPT_PREFIX[:-1], *_catalog_prompt_lines(catalog, learned_knowledge), "Records:"]
    for record in records:
        lines.append(_record_prompt_line(record))
    prompt = "\n".join(lines)
    if len(prompt) > MAX_AI_BATCH_PROMPT_CHARS:
        raise ValueError(
            f"AI batch prompt is {len(prompt)} chars; max is {MAX_AI_BATCH_PROMPT_CHARS}"
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
) -> tuple[dict[str, Any], int]:
    last_exc: ProviderResponseError | None = None
    for attempt in range(1, _MAX_PROVIDER_ATTEMPTS + 1):
        cooldown_until = _provider_cooldown_until.get(provider_id, 0.0)
        remaining = cooldown_until - _monotonic()
        if remaining > 0:
            _sleep(min(remaining, _MAX_PROVIDER_BACKOFF_SECONDS))
        try:
            return provider.call(prompt=prompt, schema=schema), attempt
        except ProviderResponseError as exc:
            last_exc = exc
            if attempt >= _MAX_PROVIDER_ATTEMPTS or not _is_transient_provider_error(exc):
                raise AIIngestionError(
                    f"{str(exc)} (attempt {attempt}/{_MAX_PROVIDER_ATTEMPTS})",
                    stage="provider_call",
                    status_code=502,
                    provider_id=exc.provider_id or provider_id,
                    model=exc.model or model,
                    raw_batch_id=raw_batch_id,
                    ai_batch_id=ai_batch_id,
                    row_count=row_count,
                    invalid_rows=getattr(exc, "invalid_rows", []),
                ) from exc
            delay = min(
                _MAX_PROVIDER_BACKOFF_SECONDS,
                _MIN_PROVIDER_BACKOFF_SECONDS * (2 ** (attempt - 1)),
            )
            _provider_cooldown_until[provider_id] = _monotonic() + _PROVIDER_COOLDOWN_SECONDS
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
            item = {
                **item,
                "package_quantity": deterministic_unit["package_quantity"],
                "package_unit": deterministic_unit["package_unit"],
                "display_unit": deterministic_unit["display_unit"],
                "price_per_100g": deterministic_unit["price_per_100g"],
            }
            standard_total = quantity_to_standard_total(
                deterministic_unit["package_quantity"],
                deterministic_unit["package_unit"],
            )
            if standard_total is not None:
                total_quantity, standard_unit = standard_total
                item["standard_unit"] = standard_unit
                if record.raw_price is not None:
                    item["standard_unit_price"] = round(record.raw_price / total_quantity, 2)
        if deterministic_unit.get("attributes"):
            attributes = {**(attributes or {}), **deterministic_unit["attributes"]}

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
    if missing_ids:
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
    provider_factory=None,
) -> dict[str, Any]:
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
    try:
        split_batches = split_records_for_ai(
            records,
            catalog=keyword_catalog,
            learned_knowledge=learned_keyword_knowledge,
        )
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
    all_proposals: list[FieldProposal] = []
    all_keyword_proposals: list[dict[str, Any]] = []
    calls = 0
    for index, batch_records in enumerate(split_batches, start=1):
        ai_batch_id = f"{root_batch_id}:ai:{index}"
        try:
            prompt = build_labeling_prompt(
                batch_records,
                catalog=keyword_catalog,
                learned_knowledge=learned_keyword_knowledge,
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
        calls += attempts
        try:
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
            )
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

    return {
        "raw_batch_id": root_batch_id,
        "records_stored": len(records),
        "ai_batches": len(split_batches),
        "provider_calls": calls,
        "proposals_stored": len(all_proposals),
        "keyword_proposals_stored": len(all_keyword_proposals),
        "proposal_ids": [proposal.proposal_id for proposal in all_proposals],
        "keyword_proposal_ids": [
            proposal["proposal_id"] for proposal in all_keyword_proposals
        ],
    }
