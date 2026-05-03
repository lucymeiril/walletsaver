"""Raw crawl ingestion and provider-backed labeling service."""
from __future__ import annotations

from datetime import datetime
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
from providers.google_genai import ProviderResponseError
from storage.repositories import (
    FieldProposalRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
)


class ProviderAdapter(Protocol):
    config: ProviderConfigContract

    def call(self, *, prompt: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


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
        "Return only valid JSON with this shape:",
        '{"items":[{"raw_record_id":"...","canonical_name":"...",'
        '"brand":null,"category_id":"...","keywords":["..."],'
        '"aliases":["..."],"attributes":{},"package_quantity":null,'
        '"package_unit":null,"bundle_count":1,"standard_unit":null,'
        '"standard_unit_price":null,"confidence":0.0,"notes":"..."}]}',
        "Rules: preserve raw titles, do not invent prices, classify snacks as snacks even if the name contains seafood words.",
        "Records:",
    ]
    for record in records:
        lines.append(
            f"- id={record.raw_record_id}; source={record.source_name}; "
            f"title={record.raw_title}; price={record.raw_price}"
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
                        "bundle_count": {"type": ["integer", "null"]},
                        "standard_unit": {"type": ["string", "null"]},
                        "standard_unit_price": {"type": ["number", "null"]},
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

        scalar_fields: tuple[tuple[str, AIWorkerRole, ProposalType], ...] = (
            ("canonical_name", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("brand", AIWorkerRole.NORMALIZER, ProposalType.NORMALIZED_FIELD),
            ("category_id", AIWorkerRole.CLASSIFIER, ProposalType.CATEGORY),
            ("package_quantity", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("package_unit", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("bundle_count", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            ("standard_unit", AIWorkerRole.UNIT_CONVERTER, ProposalType.NORMALIZED_FIELD),
            (
                "standard_unit_price",
                AIWorkerRole.UNIT_CONVERTER,
                ProposalType.NORMALIZED_FIELD,
            ),
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

        for index, keyword in enumerate(item.get("keywords") or []):
            if isinstance(keyword, str) and keyword.strip():
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
                    )
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
        raise ValueError("provider not found")
    factory = provider_factory or provider_from_config
    provider = factory(provider_config)
    provider_ref = _provider_ref(provider_config)

    root_batch_id = f"raw-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    raw_repo = RawCrawlBatchRepository(session)
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

    proposal_repo = FieldProposalRepository(session)
    split_batches = split_records_for_ai(records)
    all_proposals: list[FieldProposal] = []
    calls = 0
    for index, batch_records in enumerate(split_batches, start=1):
        ai_batch_id = f"{root_batch_id}:ai:{index}"
        prompt = build_labeling_prompt(batch_records)
        response = provider.call(prompt=prompt, schema=labeling_response_schema())
        calls += 1
        proposals = proposals_from_labeling_response(
            batch_id=ai_batch_id,
            provider=provider_ref,
            records=batch_records,
            response=response,
        )
        for proposal in proposals:
            proposal_repo.save(proposal)
        all_proposals.extend(proposals)

    return {
        "raw_batch_id": root_batch_id,
        "records_stored": len(records),
        "ai_batches": len(split_batches),
        "provider_calls": calls,
        "proposals_stored": len(all_proposals),
        "proposal_ids": [proposal.proposal_id for proposal in all_proposals],
    }
