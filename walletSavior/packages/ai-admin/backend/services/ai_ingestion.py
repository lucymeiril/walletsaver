"""Raw crawl ingestion and provider-backed labeling service."""
from __future__ import annotations

from datetime import datetime
import re
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
    ProviderConfigRepository,
    RawCrawlBatchRepository,
)
from services.keyword_catalog import KeywordCatalogAdapter, build_keyword_outputs


def _safe_error_message(message: str) -> str:
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_API_KEY]", message)
    redacted = re.sub(
        r"(?i)(api[_-]?key|key|token|authorization)(\s*[=:]\s*)['\"]?[^'\"\s,;}]+",
        r"\1\2[REDACTED]",
        redacted,
    )
    return redacted.strip()


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


def split_records_for_ai(records: list[RawCrawlRecord]) -> list[list[RawCrawlRecord]]:
    """Split records without cutting a record across batches."""
    batches: list[list[RawCrawlRecord]] = []
    current: list[RawCrawlRecord] = []
    current_chars = 0
    for record in records:
        record_chars = len(record.prompt_text())
        if record_chars > MAX_AI_BATCH_PROMPT_CHARS:
            raise ValueError(
                f"record {record.raw_record_id} is {record_chars} chars; "
                f"max batch prompt chars is {MAX_AI_BATCH_PROMPT_CHARS}"
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


def build_labeling_prompt(records: list[RawCrawlRecord]) -> str:
    """Build a strict JSON prompt for product labeling/classification."""
    lines = [
        "WalletSavior raw product data labeling task.",
        "First reuse existing DB keywords/match terms when provided by system context.",
        "Return only valid JSON with this shape:",
        '{"items":[{"raw_record_id":"...","canonical_name":"...",'
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
    for record in records:
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
        ):
            value = record.raw_payload.get(key)
            if value not in (None, ""):
                hints.append(f"{key}={value}")
        source_url = f"; url={record.source_url}" if record.source_url else ""
        hint_text = f"; hints={', '.join(map(str, hints))}" if hints else ""
        lines.append(
            f"- id={record.raw_record_id}; source={record.source_name}; "
            f"title={record.raw_title}; price={record.raw_price}{source_url}{hint_text}"
        )
    return "\n".join(lines)


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
    items = response.get("items")
    if not isinstance(items, list):
        raise ProviderResponseError(
            "provider response must contain items list",
            provider_id=provider.provider_name,
            model=provider.model_name,
        )
    seen_ids: set[str] = set()
    proposals: list[FieldProposal] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ProviderResponseError(
                f"provider response item {index} must be an object",
                provider_id=provider.provider_name,
                model=provider.model_name,
            )
        record_id = item.get("raw_record_id")
        if not isinstance(record_id, str) or record_id not in record_by_id:
            raise ProviderResponseError(
                f"provider response item {index} has unknown raw_record_id",
                provider_id=provider.provider_name,
                model=provider.model_name,
            )
        if record_id in seen_ids:
            raise ProviderResponseError(
                f"provider response contains duplicate raw_record_id: {record_id}",
                provider_id=provider.provider_name,
                model=provider.model_name,
            )
        seen_ids.add(record_id)
        for list_field in ("keywords", "aliases"):
            value = item.get(list_field)
            if value is not None and (
                not isinstance(value, list)
                or not all(isinstance(entry, str) for entry in value)
            ):
                raise ProviderResponseError(
                    f"provider response field {list_field} for {record_id} must be a list of strings",
                    provider_id=provider.provider_name,
                    model=provider.model_name,
                )
        attributes = item.get("attributes")
        if attributes is not None and not isinstance(attributes, dict):
            raise ProviderResponseError(
                f"provider response field attributes for {record_id} must be an object",
                provider_id=provider.provider_name,
                model=provider.model_name,
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
            ("brand", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("category_id", AIWorkerRole.CLASSIFIER, ProposalType.CATEGORY),
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
        raise ProviderResponseError(
            f"provider response missing labels for raw_record_id(s): {missing}",
            provider_id=provider.provider_name,
            model=provider.model_name,
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
    try:
        split_batches = split_records_for_ai(records)
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
        prompt = build_labeling_prompt(batch_records)
        try:
            response = provider.call(prompt=prompt, schema=labeling_response_schema())
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
            raise AIIngestionError(
                str(exc),
                stage="provider_call",
                status_code=502,
                provider_id=exc.provider_id or provider_id,
                model=exc.model or provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
            ) from exc
        calls += 1
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
            ) from exc
        try:
            for proposal in proposals:
                proposal_repo.save(proposal)
            for keyword_proposal in keyword_proposals:
                keyword_proposal_repo.save(keyword_proposal)
        except Exception as exc:
            raise AIIngestionError(
                "failed to store AI review proposals",
                stage="review_queue_storage",
                status_code=500,
                provider_id=provider_id,
                model=provider_config.default_model,
                raw_batch_id=root_batch_id,
                ai_batch_id=ai_batch_id,
                row_count=len(batch_records),
            ) from exc
        all_proposals.extend(proposals)
        all_keyword_proposals.extend(keyword_proposals)

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
