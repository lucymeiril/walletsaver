"""worker placeholder 테스트 — 결정론/스키마/역할 검증."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.ai_workers import AIWorkerOutput
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIProviderRef,
    AIWorkerRole,
    PromptPackRef,
    ProposalType,
    ProviderKind,
    RawCrawlRecord,
)

from workers import build_default_registry
from workers.canonical_matcher import CanonicalMatcherWorker
from workers.classifier import ClassifierWorker
from workers.data_auditor import DataAuditorWorker
from workers.keyword_generator import KeywordGeneratorWorker
from workers.normalizer import NormalizerWorker
from workers.prompt_curator import PromptCuratorWorker
from workers.unit_converter import UnitConverterWorker
from services.ai_ingestion import _record_prompt_line


def _provider() -> AIProviderRef:
    return AIProviderRef(
        provider_kind=ProviderKind.OLLAMA,
        provider_name="local",
        model_name="placeholder",
    )


def _prompt_pack(role: AIWorkerRole) -> PromptPackRef:
    return PromptPackRef(role=role, pack_id="pack-1", version="1")


def test_labeling_prompt_omits_ambiguous_source_category_but_keeps_category_hint() -> None:
    record = RawCrawlRecord(
        raw_record_id="raw-ambiguous-category",
        source_name="emart",
        raw_title="성주 참외 2kg",
        raw_price=9900,
        raw_payload={
            "category": "파머스픽",
            "category_hint": "농산/과일",
            "sale_price": 9900,
        },
    )

    line = _record_prompt_line(record)

    assert "category=파머스픽" not in line
    assert "category_hint=농산/과일" in line


def _record(idx: int, *, title: str = "[행사] 서울우유 1L", price: int | None = 2500) -> RawCrawlRecord:
    return RawCrawlRecord(
        raw_record_id=f"rec-{idx}",
        source_name="emart",
        raw_title=title,
        raw_price=price,
    )


def _batch(role: AIWorkerRole, records: list[RawCrawlRecord], batch_id: str = "b1") -> AIJobBatch:
    return AIJobBatch(
        batch_id=batch_id,
        role=role,
        provider=_provider(),
        prompt_pack=_prompt_pack(role),
        records=records,
    )


# --- 단위 테스트 ---------------------------------------------------------------


def test_normalizer_proposes_cleaned_title_and_alias() -> None:
    batch = _batch(AIWorkerRole.NORMALIZER, [_record(1)])
    out = NormalizerWorker().run(batch)
    assert isinstance(out, AIWorkerOutput)
    assert out.role == AIWorkerRole.NORMALIZER
    fields = {p.target_field: p for p in out.field_proposals}
    assert set(fields) == {"canonical_name", "brand"}
    proposal = fields["canonical_name"]
    assert proposal.proposal_type == ProposalType.NORMALIZED_FIELD
    assert proposal.proposed_value == "서울우유 1L"
    assert fields["brand"].proposed_value == "서울우유"
    # alias must be raw title (different from cleaned)
    assert len(out.alias_proposals) == 1
    assert out.alias_proposals[0].proposed_value == "[행사] 서울우유 1L"


def _stable_dump(out: AIWorkerOutput) -> dict:
    """`created_at`은 placeholder worker가 결정론적으로 만들 수 없으므로 비교에서 제외."""
    data = out.model_dump(mode="json")
    for key in (
        "field_proposals",
        "alias_proposals",
        "keyword_proposals",
        "taxonomy_proposals",
    ):
        for proposal in data.get(key, []):
            proposal.pop("created_at", None)
    return data


def test_normalizer_deterministic() -> None:
    batch = _batch(AIWorkerRole.NORMALIZER, [_record(1)])
    a = NormalizerWorker().run(batch)
    b = NormalizerWorker().run(batch)
    assert _stable_dump(a) == _stable_dump(b)


def test_unit_converter_extracts_quantity_and_unit() -> None:
    batch = _batch(
        AIWorkerRole.UNIT_CONVERTER,
        [_record(1, title="감자칩 200g 3봉"), _record(2, title="콜라 1.5L")],
    )
    out = UnitConverterWorker().run(batch)
    fields = {(p.provenance.raw_record_id, p.target_field): p.proposed_value for p in out.field_proposals}
    assert fields[("rec-1", "package_quantity")] == 200.0
    assert fields[("rec-1", "package_unit")] == "g"
    assert fields[("rec-1", "display_unit")] == "200g"
    assert fields[("rec-1", "bundle_count")] == 3
    assert fields[("rec-1", "total_quantity")] == 0.6
    assert fields[("rec-1", "standard_unit")] == "kg"
    assert fields[("rec-1", "standard_unit_price")] == 4166.67
    assert fields[("rec-2", "package_quantity")] == 1.5
    assert fields[("rec-2", "standard_unit")] == "L"


def test_unit_converter_unmatched_records() -> None:
    batch = _batch(AIWorkerRole.UNIT_CONVERTER, [_record(1, title="브랜드 신상")])
    out = UnitConverterWorker().run(batch)
    assert out.field_proposals == []
    assert out.diagnostics["records_unmatched"] == 1


def test_unit_converter_emart_reference_100g_does_not_override_package() -> None:
    batch = _batch(
        AIWorkerRole.UNIT_CONVERTER,
        [
            _record(1, title="[냉장] 한우 불고기1+등급300g 100g당 4,950원", price=14850),
            _record(2, title="[냉동][베트남] 흰다리 새우살 (200g)", price=4488),
            _record(3, title="정육 행사 100g당 2,980원", price=2980),
        ],
    )
    out = UnitConverterWorker().run(batch)
    fields = {(p.provenance.raw_record_id, p.target_field): p.proposed_value for p in out.field_proposals}

    assert fields[("rec-1", "package_quantity")] == 300.0
    assert fields[("rec-1", "package_unit")] == "g"
    assert fields[("rec-1", "display_unit")] == "300g"
    assert fields[("rec-1", "price_per_100g")] == 4950
    assert fields[("rec-2", "package_quantity")] == 200.0
    assert fields[("rec-2", "display_unit")] == "200g"
    assert fields[("rec-2", "price_per_100g")] == 2244
    assert ("rec-3", "package_quantity") not in fields
    assert out.diagnostics["records_unmatched"] == 1


def test_unit_converter_live_emart_kimbap_kit_price_per_100g() -> None:
    batch = _batch(
        AIWorkerRole.UNIT_CONVERTER,
        [_record(1, title="한돈으로 만든 햄꼬마김밥키트157g", price=6980)],
    )
    out = UnitConverterWorker().run(batch)
    fields = {(p.provenance.raw_record_id, p.target_field): p.proposed_value for p in out.field_proposals}

    assert fields[("rec-1", "package_quantity")] == 157.0
    assert fields[("rec-1", "package_unit")] == "g"
    assert fields[("rec-1", "display_unit")] == "157g"
    assert fields[("rec-1", "standard_unit_price")] == 44458.6
    assert fields[("rec-1", "price_per_100g")] == 4445.86


def test_classifier_matches_known_keyword() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="서울우유 1L"), _record(2, title="???")])
    out = ClassifierWorker().run(batch)
    assert len(out.taxonomy_proposals) == 1
    assert out.taxonomy_proposals[0].proposed_value == "dairy.milk"
    assert out.diagnostics["records_unmatched"] == 1
    assert out.diagnostics["needs_human_review"] is True


def test_classifier_prefers_snack_phrase_over_seafood_token() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="오리온 오징어 땅콩 98g")])
    out = ClassifierWorker().run(batch)
    assert out.taxonomy_proposals[0].proposed_value == "snack.nut"
    assert out.taxonomy_proposals[0].alternatives[0]["evidence_class"] == "deterministic_keyword"
    assert out.taxonomy_proposals[0].alternatives[0]["trust_label"] == "taxonomy_hint_needs_review"


def test_classifier_does_not_reuse_short_catalog_token_inside_unrelated_snack() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="오리온 새우깡 90g")])
    out = ClassifierWorker().run(batch)
    category = next(p for p in out.taxonomy_proposals if p.target_field == "category_id")

    assert category.proposed_value == "snack.chip"
    assert category.provenance.evidence_text == "새우깡"


def test_classifier_holdout_like_titles_need_real_product_signal_not_exact_alias() -> None:
    batch = _batch(
        AIWorkerRole.CLASSIFIER,
        [
            _record(1, title="브랜드A 김밥 만들기 세트 180g"),
            _record(2, title="처음보는 그릭요거트볼 120g"),
            _record(3, title="미분류 신상품 ZZ-42 1개"),
        ],
    )
    out = ClassifierWorker().run(batch)
    categories = {
        p.provenance.raw_record_id: p.proposed_value
        for p in out.taxonomy_proposals
        if p.target_field == "category_id"
    }

    assert categories == {"rec-1": "prepared_food.deli.kimbap", "rec-2": "dairy.yogurt"}
    assert out.diagnostics["records_unmatched"] == 1
    assert out.diagnostics["needs_human_review"] is True


def test_classifier_uses_prepared_food_category_for_kimbap_kit() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="한돈으로 만든 햄꼬마김밥키트157g", price=6980)])
    out = ClassifierWorker().run(batch)
    category = next(p for p in out.taxonomy_proposals if p.target_field == "category_id")

    assert category.proposed_value == "prepared_food.meal_kit.kimbap"


def test_classifier_emits_attribute_values() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="국산 냉장 한우 등심 1등급 300g")])
    out = ClassifierWorker().run(batch)
    attrs = {p.target_field: p.proposed_value for p in out.taxonomy_proposals if p.proposal_type == ProposalType.ATTRIBUTE_VALUE}
    assert attrs["attributes.storage_type"] == "chilled"
    assert attrs["attributes.origin"] == "domestic"
    assert attrs["attributes.quality_grade"] == "1"


def test_classifier_preserves_emart_storage_origin_cut_grade_as_attributes() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="[냉동][베트남] 흰다리 새우살 (200g)")])
    out = ClassifierWorker().run(batch)
    attrs = {
        p.target_field: p.proposed_value
        for p in out.taxonomy_proposals
        if p.proposal_type == ProposalType.ATTRIBUTE_VALUE
    }

    assert attrs["attributes.storage_type"] == "frozen"
    assert attrs["attributes.origin"] == "vietnam"
    assert attrs["attributes.cut"] == "shrimp_meat"


def test_classifier_does_not_treat_thailand_as_domestic_origin() -> None:
    batch = _batch(AIWorkerRole.CLASSIFIER, [_record(1, title="태국산 무지개 망고 1.8kg 팩")])
    out = ClassifierWorker().run(batch)
    attrs = {
        p.target_field: p.proposed_value
        for p in out.taxonomy_proposals
        if p.proposal_type == ProposalType.ATTRIBUTE_VALUE
    }
    category = next(p for p in out.taxonomy_proposals if p.target_field == "category_id")

    assert attrs["attributes.origin"] == "thailand"
    assert attrs["attributes.storage_type"] == "ambient"
    assert category.proposed_value == "produce.fruit"


def test_canonical_matcher_emits_draft_and_alias() -> None:
    batch = _batch(
        AIWorkerRole.CANONICAL_MATCHER,
        [_record(1), _record(2, title="[특가] 서울우유 1L")],
    )
    out = CanonicalMatcherWorker().run(batch)
    assert len(out.canonical_drafts) == 1  # both clean to same canonical
    assert out.canonical_drafts[0].canonical_name == "서울우유 1L"
    assert out.canonical_drafts[0].brand == "서울우유"
    assert len(out.variant_drafts) == 1
    assert out.variant_drafts[0].package_quantity == 1.0
    assert out.variant_drafts[0].standard_unit == "L"
    assert all(p.proposal_type == ProposalType.CANONICAL_MATCH for p in out.field_proposals)
    assert out.field_proposals[0].alternatives[0]["trust_label"] == "raw_title_normalization_not_generalization"
    assert out.diagnostics["trust_label"] == "deterministic_raw_title_drafts_require_review"
    assert len(out.alias_proposals) == 2


def test_canonical_matcher_holdouts_do_not_auto_merge_renamed_package_or_typo_near_matches() -> None:
    batch = _batch(
        AIWorkerRole.CANONICAL_MATCHER,
        [
            _record(1, title="처음보는 플레인 요거트 100g"),
            _record(2, title="처음보는 플레인 요거트 300g"),
            _record(3, title="처음보는 플래인 요거트 100g"),
            _record(4, title="처음보는 저지방 플레인 요거트 100g"),
        ],
    )

    out = CanonicalMatcherWorker().run(batch)
    names = [draft.canonical_name for draft in out.canonical_drafts]
    variants = {
        (variant.variant_name, variant.package_quantity, variant.package_unit)
        for variant in out.variant_drafts
    }

    assert len(names) == 4
    assert "처음보는 플레인 요거트 100g" in names
    assert "처음보는 플래인 요거트 100g" in names
    assert "처음보는 저지방 플레인 요거트 100g" in names
    assert ("처음보는 플레인 요거트 100g", 100.0, "g") in variants
    assert ("처음보는 플레인 요거트 300g", 300.0, "g") in variants


def test_keyword_generator_dedupes_tokens() -> None:
    batch = _batch(AIWorkerRole.KEYWORD_GENERATOR, [_record(1, title="우유 우유 서울 1L")])
    out = KeywordGeneratorWorker().run(batch)
    values = [p.proposed_value for p in out.keyword_proposals]
    assert values == sorted(set(values), key=values.index)
    assert "우유" in values
    assert "서울" in values
    assert out.alias_proposals[0].proposed_value == "우유서울1L"


def test_keyword_generator_does_not_emit_generic_kit_or_ham_ingredient() -> None:
    batch = _batch(AIWorkerRole.KEYWORD_GENERATOR, [_record(1, title="한돈으로 만든 햄 키트 157g")])
    out = KeywordGeneratorWorker().run(batch)
    values = [p.proposed_value for p in out.keyword_proposals]
    aliases = [p.proposed_value for p in out.alias_proposals]

    assert "햄" not in values
    assert "키트" not in values
    assert "키트" not in aliases


def test_prompt_curator_does_not_activate_prompts() -> None:
    batch = _batch(AIWorkerRole.PROMPT_CURATOR, [_record(1)])
    out = PromptCuratorWorker().run(batch)
    assert out.diagnostics["activates_prompt"] is False
    assert out.diagnostics["needs_human_review"] is True
    assert all(p.proposal_type == ProposalType.NORMALIZED_FIELD for p in out.field_proposals)


def test_data_auditor_flags_missing_signals() -> None:
    rec = RawCrawlRecord(
        raw_record_id="rec-x",
        source_name="emart",
        raw_title="알 수 없는 신상품",
        raw_price=None,
    )
    batch = _batch(AIWorkerRole.DATA_AUDITOR, [rec])
    out = DataAuditorWorker().run(batch)
    assert out.diagnostics["missing_price"] == 1
    assert out.diagnostics["missing_unit"] == 1
    assert out.diagnostics["missing_category"] == 1
    issues = out.diagnostics["issues_per_record"]["rec-x"]
    assert "price_missing" in issues
    assert "unit_signal_missing" in issues
    assert "category_signal_missing" in issues


# --- 역할 검증 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "worker_factory,worker_role",
    [
        (NormalizerWorker, AIWorkerRole.NORMALIZER),
        (UnitConverterWorker, AIWorkerRole.UNIT_CONVERTER),
        (ClassifierWorker, AIWorkerRole.CLASSIFIER),
        (CanonicalMatcherWorker, AIWorkerRole.CANONICAL_MATCHER),
        (KeywordGeneratorWorker, AIWorkerRole.KEYWORD_GENERATOR),
        (PromptCuratorWorker, AIWorkerRole.PROMPT_CURATOR),
        (DataAuditorWorker, AIWorkerRole.DATA_AUDITOR),
    ],
)
def test_worker_rejects_wrong_role_batch(worker_factory, worker_role) -> None:
    other_role = (
        AIWorkerRole.NORMALIZER
        if worker_role != AIWorkerRole.NORMALIZER
        else AIWorkerRole.CLASSIFIER
    )
    batch = _batch(other_role, [_record(1)])
    with pytest.raises(ValueError):
        worker_factory().run(batch)


def test_default_registry_has_all_roles() -> None:
    registry = build_default_registry()
    assert set(registry.list_roles()) == set(AIWorkerRole)


def test_registry_rejects_duplicate_role() -> None:
    registry = build_default_registry()
    with pytest.raises(ValueError):
        registry.register(NormalizerWorker())


# --- 라우트 ---------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        yield c


def _batch_payload(role: AIWorkerRole, records: list[RawCrawlRecord]) -> dict:
    return _batch(role, records).model_dump(mode="json")


def test_dry_run_route_happy_path(client: TestClient) -> None:
    payload = _batch_payload(AIWorkerRole.NORMALIZER, [_record(1)])
    res = client.post("/api/workers/normalizer/dry-run", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "normalizer"
    assert body["field_proposals"]
    AIWorkerOutput.model_validate(body)


def test_dry_run_rejects_role_mismatch(client: TestClient) -> None:
    payload = _batch_payload(AIWorkerRole.NORMALIZER, [_record(1)])
    res = client.post("/api/workers/classifier/dry-run", json=payload)
    assert res.status_code == 400
    assert "does not match" in res.json()["detail"]


def test_list_workers_route(client: TestClient) -> None:
    res = client.get("/api/workers")
    assert res.status_code == 200
    assert set(res.json()["roles"]) == {r.value for r in AIWorkerRole}


# --- edge cases ----------------------------------------------------------------


def test_long_title_within_batch_limit_is_accepted() -> None:
    # 단일 record, 1900자 제목 — prompt limit 2000 미만.
    title = "우유 " * 400
    rec = RawCrawlRecord(raw_record_id="r1", source_name="emart", raw_title=title, raw_price=1000)
    batch = _batch(AIWorkerRole.NORMALIZER, [rec])
    out = NormalizerWorker().run(batch)
    assert len(out.field_proposals) == 1


def test_keyword_generator_handles_repeated_tokens() -> None:
    rec = RawCrawlRecord(
        raw_record_id="r1",
        source_name="emart",
        raw_title="사과 사과 사과 사과",
        raw_price=1000,
    )
    batch = _batch(AIWorkerRole.KEYWORD_GENERATOR, [rec])
    out = KeywordGeneratorWorker().run(batch)
    assert len(out.keyword_proposals) == 1
    assert out.keyword_proposals[0].proposed_value == "사과"


def test_data_auditor_handles_missing_price_only() -> None:
    rec = RawCrawlRecord(
        raw_record_id="r1",
        source_name="emart",
        raw_title="서울우유 1L",  # has unit + category signals
        raw_price=None,
    )
    batch = _batch(AIWorkerRole.DATA_AUDITOR, [rec])
    out = DataAuditorWorker().run(batch)
    assert out.diagnostics["missing_price"] == 1
    assert out.diagnostics["missing_unit"] == 0
    assert out.diagnostics["missing_category"] == 0
    issues = out.diagnostics["issues_per_record"]["r1"]
    assert issues == ["price_missing"]


def test_data_auditor_flags_zero_price_and_bad_seafood_category() -> None:
    rec = RawCrawlRecord(
        raw_record_id="r1",
        source_name="emart",
        raw_title="오리온 오징어 땅콩 98g",
        raw_price=0,
        raw_payload={"category_id": "seafood.squid"},
    )
    batch = _batch(AIWorkerRole.DATA_AUDITOR, [rec])
    out = DataAuditorWorker().run(batch)
    issues = out.diagnostics["issues_per_record"]["r1"]
    assert "price_outlier" in issues
    assert "suspicious_category_snack_marked_seafood" in issues
