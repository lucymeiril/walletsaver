"""Validated, idempotent import for the capstone normalized catalog bundle."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.promotion_semantics import (PriceState, PromotionPriceFacts, PromotionType,
                                      conditional_selection_facts_or_none,
                                      conditional_program_facts_or_none,
                                      conditional_basket_spend_facts_or_none)
from core.promotion_semantics import confirmed_price_or_none
from core.match_key import normalize_pack_identity
from core.catalog_quantity import canonical_components, component_signature, package_pricing_measure, normalize_catalog_package
from core.reviewed_source_evidence import valid_source_identity_context, source_identity_context_for_variant
from storage.models import (
    CatalogSyncLog,
    Keyword,
    MartCategoryMapping,
    MatchingEntry,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
    UnifiedCategory,
)

SCHEMA_VERSION = "walletsaver-catalog-v2"
ENTITY_KEYS = (
    "categories",
    "keywords",
    "products",
    "variants",
    "source_listings",
    "offers",
    "week_buckets",
    "offer_week_links",
    "match_rules",
    "mart_category_mappings",
    "unresolved",
)
MAX_CATEGORY_LEVEL = 3  # root level 0 => four levels total
LOW_CONFIDENCE = 0.80
PACKAGE_UNITS = {
    "g", "kg", "mg", "ml", "l", "cc", "m", "그램", "킬로그램", "리터", "밀리리터", "미리리터",
    "ea", "개", "개입", "봉지", "인분", "세트", "마리", "회분", "구", "입", "팩", "봉", "병",
    "캔", "손", "매", "롤", "포", "장", "족", "통", "인", "p", "t", "모", "두", "알", "미",
    "포기", "단", "망", "박스", "쌍", "켤레",
}


@dataclass
class BundleValidation:
    ok: bool
    file_hash: str
    counts: dict[str, int]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_version": SCHEMA_VERSION,
            "file_hash": self.file_hash,
            "counts": self.counts,
            "errors": self.errors,
            "warnings": self.warnings,
            "review_counts": self.review_counts,
        }


def parse_bundle(content: bytes, filename: str = "bundle.json") -> tuple[dict[str, Any], str]:
    if not content:
        raise ValueError("빈 catalog bundle은 가져올 수 없습니다")
    digest = hashlib.sha256(content).hexdigest()
    if filename.lower().endswith(".zip") or content.startswith(b"PK\x03\x04"):
        bundle = _parse_zip(content)
    else:
        try:
            bundle = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"catalog bundle JSON 파싱 실패: {exc}") from exc
    if not isinstance(bundle, dict):
        raise ValueError("catalog bundle 최상위 값은 object여야 합니다")
    for key in ENTITY_KEYS:
        bundle.setdefault(key, [])
        if not isinstance(bundle[key], list):
            raise ValueError(f"bundle.{key}는 배열이어야 합니다")
    return bundle, digest


def _parse_zip(content: bytes) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("손상된 catalog ZIP입니다") from exc
    names = set(archive.namelist())
    manifest_name = next((n for n in names if n.rstrip("/").endswith("manifest.json")), None)
    manifest: dict[str, Any] = {}
    if manifest_name:
        manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))
    bundle: dict[str, Any] = {
        "schema_version": manifest.get("schema_version"),
        "run_id": manifest.get("run_id") or manifest.get("export_id"),
    }
    file_map = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    for key in ENTITY_KEYS:
        configured = file_map.get(key)
        if isinstance(configured, dict):
            configured = configured.get("name") or configured.get("path")
        candidates = [str(configured)] if configured else []
        candidates.extend([f"{key}.jsonl", f"{key}.json"])
        member = next((n for n in candidates if n in names), None)
        if member is None:
            member = next((n for n in names if n.endswith("/" + f"{key}.jsonl") or n.endswith("/" + f"{key}.json")), None)
        bundle[key] = _read_entity_file(archive, member) if member else []
    return bundle


def _read_entity_file(archive: zipfile.ZipFile, member: str) -> list[dict[str, Any]]:
    text = archive.read(member).decode("utf-8-sig")
    if member.lower().endswith(".jsonl"):
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        rows = json.loads(text)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{member}에는 object 배열/JSONL만 허용됩니다")
    return rows


def validate_bundle(session: Session, bundle: dict[str, Any], file_hash: str) -> BundleValidation:
    errors: list[str] = []
    warnings: list[str] = []
    bundle = {**{key: [] for key in ENTITY_KEYS}, **bundle}
    for key in ENTITY_KEYS:
        if not isinstance(bundle[key], list) or any(not isinstance(row, dict) for row in bundle[key]):
            errors.append(f"bundle.{key}는 object 배열이어야 합니다")
    if errors:
        return BundleValidation(False, file_hash, {}, errors=errors)
    counts = {key: len(bundle.get(key, [])) for key in ENTITY_KEYS}
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version은 {SCHEMA_VERSION!r}이어야 합니다")
    run_id = str(bundle.get("run_id") or "").strip()
    if not run_id:
        errors.append("run_id가 필요합니다")

    incoming_categories = _unique_rows(bundle["categories"], "id", "categories", errors)
    existing_categories = {
        row.id: row for row in session.execute(select(UnifiedCategory)).scalars().all()
    }
    parent_map = {row.id: row.parent_id for row in existing_categories.values()}
    parent_map.update({key: _optional_text(row.get("parent_id")) for key, row in incoming_categories.items()})
    levels = _category_levels(parent_map, errors)
    for category_id, row in incoming_categories.items():
        if not _text(row.get("name_ko")):
            errors.append(f"categories[{category_id}].name_ko가 필요합니다")
        if levels.get(category_id, MAX_CATEGORY_LEVEL + 1) > MAX_CATEGORY_LEVEL:
            errors.append(f"카테고리 {category_id!r}가 루트 포함 4단계를 초과합니다")

    keyword_words: set[str] = set()
    for index, row in enumerate(bundle["keywords"]):
        word = _text(row.get("word"))
        category_id = _text(row.get("unified_category_id"))
        if not word:
            errors.append(f"keywords[{index}].word가 필요합니다")
        elif len(word) > 100:
            errors.append(f"keywords[{index}].word는 100자를 초과할 수 없습니다")
        elif word in keyword_words:
            errors.append(f"keywords[{index}] 중복 word {word!r}")
        keyword_words.add(word)
        if category_id not in parent_map:
            errors.append(f"keywords[{index}]가 없는 통합 카테고리 {category_id!r}를 참조합니다")
        synonyms = row.get("synonyms", [])
        if not isinstance(synonyms, list):
            errors.append(f"keywords[{index}].synonyms는 배열이어야 합니다")
            continue
        synonym_words: set[str] = set()
        for synonym_index, synonym in enumerate(synonyms):
            if not isinstance(synonym, str):
                errors.append(f"keywords[{index}].synonyms[{synonym_index}]는 문자열이어야 합니다")
                continue
            value = _text(synonym)
            if not value:
                errors.append(f"keywords[{index}].synonyms[{synonym_index}]가 비어 있습니다")
            elif len(value) > 100:
                errors.append(f"keywords[{index}].synonyms[{synonym_index}]는 100자를 초과할 수 없습니다")
            elif value == word or value in synonym_words:
                errors.append(f"keywords[{index}]에 중복 synonym {value!r}가 있습니다")
            synonym_words.add(value)

    child_ids = {parent for parent in parent_map.values() if parent}
    products = _unique_rows(bundle["products"], "public_product_id", "products", errors)
    variants = _unique_rows(bundle["variants"], "public_variant_id", "variants", errors)
    listings = _unique_rows(bundle["source_listings"], "public_source_listing_id", "source_listings", errors)
    offers = _unique_rows(bundle["offers"], "public_offer_event_id", "offers", errors)
    weeks = _unique_rows(bundle["week_buckets"], "public_week_bucket_id", "week_buckets", errors)
    malformed_attributes = [identity for identity, row in variants.items()
                            if row.get("attributes") is not None and not isinstance(row["attributes"], Mapping)]
    if malformed_attributes:
        errors.extend(f"variants[{identity}].attributes는 object 또는 null이어야 합니다"
                      for identity in malformed_attributes)
        return BundleValidation(False, file_hash, counts, errors=errors, warnings=warnings)

    existing_product_categories = dict(session.execute(select(
        NormalizedCanonicalProduct.public_product_id,
        NormalizedCanonicalProduct.unified_category_id,
    )).all())
    existing_product_ids = set(existing_product_categories)
    existing_variant_ids = set(session.execute(select(NormalizedProductVariant.public_variant_id)).scalars())
    existing_listing_ids = set(session.execute(select(NormalizedSourceListing.public_source_listing_id)).scalars())
    existing_offer_ids = set(session.execute(select(NormalizedOfferEvent.public_offer_event_id)).scalars())
    existing_week_ids = set(session.execute(select(NormalizedWeekBucket.public_week_bucket_id)).scalars())

    review_low = 0
    for product_id, row in products.items():
        category_id = _text(row.get("unified_category_id"))
        if category_id not in parent_map:
            errors.append(f"products[{product_id}]가 없는 통합 카테고리 {category_id!r}를 참조합니다")
        elif category_id in child_ids:
            errors.append(f"products[{product_id}]는 내부 노드 {category_id!r}가 아닌 리프에 귀속해야 합니다")
        for field in ('aliases', 'keywords'):
            value = row.get(field)
            if value is not None and (not isinstance(value, list)
                    or any(not isinstance(item, str) for item in value)):
                errors.append(f"products[{product_id}].{field}는 문자열 배열이어야 합니다")
        attributes = row.get('attributes')
        if attributes is not None and not isinstance(attributes, Mapping):
            errors.append(f"products[{product_id}].attributes는 객체여야 합니다")
            continue
        confidence_value, review_status = _product_classification(row)
        confidence = _confidence(confidence_value, f"products[{product_id}]", errors)
        if confidence < LOW_CONFIDENCE:
            review_low += 1
            if review_status != "approved":
                errors.append(f"products[{product_id}] 저신뢰 분류는 관리자 approved 상태가 필요합니다")
            else:
                warnings.append(f"products[{product_id}]는 승인된 저신뢰 분류로 공개 경고 대상입니다")
        if not _text(row.get("canonical_name")):
            errors.append(f"products[{product_id}].canonical_name이 필요합니다")

    all_product_ids = existing_product_ids | set(products)
    variant_products = dict(session.execute(select(
        NormalizedProductVariant.public_variant_id,
        NormalizedProductVariant.public_product_id,
    )).all())
    variant_signatures: dict[tuple, str] = {}
    for variant_id, row in variants.items():
        product_id = _text(row.get("public_product_id"))
        variant_products[variant_id] = product_id
        if product_id not in all_product_ids:
            errors.append(f"variants[{variant_id}]의 product 참조가 없습니다")
        category_id = products.get(product_id, {}).get(
            "unified_category_id", existing_product_categories.get(product_id))
        from core.reviewed_source_evidence import source_entitlement_specification, source_partial_retail_specification
        entitlement = source_entitlement_specification(row)
        partial_retail = source_partial_retail_specification(row)
        if (isinstance(category_id, str) and category_id.startswith("services.facility.")
                and not entitlement):
            _, purpose_issues = normalize_catalog_package(
                row, row.get("attributes") or {}, _text(row.get("variant_name")),
                category_id=category_id,
            )
            if "unit_service_occupancy_not_entitlement" in purpose_issues:
                errors.append(f"variants[{variant_id}]의 unit_service_occupancy_not_entitlement: 시설 정원은 판매 이용권 수량이 아닙니다")
                continue
        try:
            count = row.get("bundle_count", 1)
            if isinstance(count, bool) or float(count) != int(count) or int(count) < 1:
                raise ValueError
            count = int(count)
        except (TypeError, ValueError, OverflowError):
            errors.append(f"variants[{variant_id}].bundle_count는 1 이상의 정수여야 합니다")
            continue
        quantity, unit = row.get("package_quantity"), _text(row.get("package_unit"))
        from core.reviewed_source_evidence import source_outer_set_count, source_nonexact_contents_specification
        outer_count = source_outer_set_count(row)
        nonexact = source_nonexact_contents_specification(row)
        product = products.get(product_id, {})
        product_attributes = product.get('attributes')
        product_attributes = product_attributes if isinstance(product_attributes, Mapping) else {}
        incomplete_basis = ('source_partial_retail_observation' if partial_retail else
                            'source_incomplete_entitlement_observation' if entitlement else
                            'source_nonexact_contents_observation' if nonexact else
                            'source_incomplete_set_observation')
        if outer_count or nonexact or entitlement or partial_retail or product_attributes.get('identity_basis') in {
                'source_incomplete_set_observation', 'source_nonexact_contents_observation',
                'source_incomplete_entitlement_observation', 'source_partial_retail_observation'}:
            if (not (outer_count or nonexact or entitlement or partial_retail) or product_attributes.get('identity_basis') != incomplete_basis
                    or product_attributes.get('product_group_key')
                    or product.get('is_active') is not False or row.get('is_active') is not False):
                errors.append(f"variants[{variant_id}]의 외부 세트 개수는 완성 내용량/활성 규격이 아닙니다")
        from core.reviewed_source_evidence import (valid_count_interval_variant, valid_listing_title_history,
                                                  valid_source_component_variant, source_component_signature)
        vector_review = (row.get('attributes') or {}).get('source_component_listing')
        if vector_review is not None:
            if (not valid_source_component_variant(row)
                    or products.get(product_id, {}).get('unified_category_id') != vector_review.get('category_id')):
                errors.append(f"variants[{variant_id}]의 원문 구성 벡터 계약이 올바르지 않습니다")
            else:
                signature = (product_id, 'source_component_vector_v1', source_component_signature(vector_review['components']))
                if signature in variant_signatures:
                    errors.append(f"variants[{variant_id}] 중복 원문 구성 벡터 규격")
                variant_signatures[signature] = variant_id
            continue
        if (row.get('attributes') or {}).get('quantity_basis') == 'reviewed_source_component_vector_v1':
            errors.append(f"variants[{variant_id}]의 원문 구성 벡터 계약이 누락되었습니다")
            continue
        title_history = (row.get('attributes') or {}).get('source_title_history')
        if title_history is not None and (not valid_listing_title_history(title_history)
                or products.get(product_id, {}).get('unified_category_id') != title_history.get('category_id')):
            errors.append(f"variants[{variant_id}]의 원문 상품명 이력 계약이 올바르지 않습니다")
        interval_review = (row.get('attributes') or {}).get('count_interval_listing')
        if interval_review is not None:
            if (not valid_count_interval_variant(row)
                    or products.get(product_id, {}).get('unified_category_id') != interval_review.get('category_id')):
                errors.append(f"variants[{variant_id}]의 선언된 개수 범위 계약이 올바르지 않습니다")
            else:
                signature = (product_id, 'declared_count_interval_v1', tuple(interval_review['count_interval']))
                if signature in variant_signatures:
                    errors.append(f"variants[{variant_id}] 중복 개수 범위 규격")
                variant_signatures[signature] = variant_id
            continue
        if (row.get('attributes') or {}).get('quantity_basis') == 'reviewed_declared_count_interval_v1':
            errors.append(f"variants[{variant_id}]의 선언된 개수 범위 계약이 누락되었습니다")
            continue
        from core.reviewed_source_evidence import explicit_listing_category_compatible
        explicit_review = (row.get('attributes') or {}).get('explicit_listing_quantity_review')
        if explicit_review:
            if not explicit_listing_category_compatible(
                    row, products.get(product_id, {}).get('unified_category_id')):
                errors.append(f"variants[{variant_id}]의 명시적 listing 수량 계약이 올바르지 않습니다")
                continue
            if 'source_parent_selection' in explicit_review:
                from core.reviewed_source_evidence import source_parent_selection
                product = products.get(product_id, {})
                if (not source_parent_selection(row)
                        or (product.get('attributes') or {}).get('identity_basis')
                           != 'source_selectable_parent_observation'
                        or (product.get('attributes') or {}).get('product_group_key')
                        or product.get('is_active') is not False
                        or row.get('is_active') is not False):
                    errors.append(f"variants[{variant_id}]의 미선택 옵션 부모는 고정 상품이나 활성 규격이 아닙니다")
        from core.reviewed_source_evidence import original_quantity_assertion
        from core.reviewed_source_evidence import source_selection_alternatives
        if variant_id in existing_variant_ids:
            prior = session.get(NormalizedProductVariant, variant_id)
            prior_spec = {key: getattr(prior, key) for key in (
                'package_quantity', 'package_unit', 'bundle_count', 'standard_unit', 'attributes')}
            assertion = original_quantity_assertion(prior_spec)
            if assertion and original_quantity_assertion(row) != assertion:
                errors.append(f"variants[{variant_id}]의 원래 수량 버전과 미해결 이력을 지울 수 없습니다")
        alternatives = source_selection_alternatives(row)
        if alternatives or nonexact or entitlement or partial_retail:
            signature = ((product_id, 'source-partial-retail-observation-v1',
                          json.dumps(partial_retail, sort_keys=True, ensure_ascii=False)) if partial_retail else
                         (product_id, 'source-incomplete-entitlement-observation-v1',
                          json.dumps(entitlement, sort_keys=True, ensure_ascii=False)) if entitlement else
                         (product_id, 'source-nonexact-contents-observation-v1', nonexact['kind']) if nonexact
                         else (product_id, 'source-exclusive-alternatives-v1', alternatives))
            if signature in variant_signatures:
                errors.append(f"variants[{variant_id}] 중복 미선택 대안 규격")
            variant_signatures[signature] = variant_id
            continue
        from core.catalog_quantity import valid_physical_device_variant
        if (row.get('attributes') or {}).get('quantity_basis') == 'physical_device_specification_v1':
            proof = (row.get('attributes') or {}).get('physical_device_specification')
            if (not valid_physical_device_variant(row)
                    or products.get(product_id, {}).get('unified_category_id') != (proof or {}).get('category_id')):
                errors.append(f"variants[{variant_id}]의 기기 규격/판매 수량 계약이 올바르지 않습니다")
                continue
            signature = (product_id, 'physical_device_specification_v1', json.dumps(proof, sort_keys=True, ensure_ascii=False))
            if signature in variant_signatures:
                errors.append(f"variants[{variant_id}] 중복 기기 규격")
            variant_signatures[signature] = variant_id
            continue
        from core.reviewed_source_evidence import valid_nonmeasured_variant
        if valid_nonmeasured_variant(row):
            if products.get(product_id, {}).get('unified_category_id') != row['attributes']['nonmeasured_listing']['category_id']:
                errors.append(f"variants[{variant_id}] 비계량 listing 상품형태가 통합 리프와 다릅니다")
            signature = (product_id, 'nonmeasured_source_listing_v1', _text(row['attributes']['nonmeasured_listing']['title']))
            if signature in variant_signatures:
                errors.append(f"variants[{variant_id}] 중복 비계량 listing 규격")
            variant_signatures[signature] = variant_id
            continue
        if (row.get('attributes') or {}).get('quantity_basis') == 'nonmeasured_source_listing_v1':
            errors.append(f"variants[{variant_id}]의 비계량 listing 계약이 올바르지 않습니다")
            continue
        if quantity is None or unit.casefold() not in PACKAGE_UNITS:
            errors.append(f"variants[{variant_id}]의 수량/단위 미해석은 검수 대기열에 남겨야 합니다")
            continue
        if quantity is not None:
            try:
                if isinstance(quantity, bool) or not math.isfinite(float(quantity)) or float(quantity) <= 0 or not unit:
                    raise ValueError
                quantity, unit = normalize_pack_identity(float(quantity), unit)
            except (TypeError, ValueError, OverflowError):
                errors.append(f"variants[{variant_id}]의 포장 수량/단위가 올바르지 않습니다")
                continue
            try:
                components = component_signature(row)
                if components is not None:
                    attrs = row["attributes"]
                    measure = package_pricing_measure(row)
                    if (quantity, unit, count) != (1, "세트", 1) or row.get("standard_unit") != measure[1]:
                        raise ValueError("component set must retain whole-set scalar shape and pricing dimension")
                    if attrs.get("component_basis") != "reviewed_homogeneous_contents" or sum(c[2] for c in components) < 2:
                        raise ValueError("component set requires reviewed homogeneous contents")
                    if attrs["package_components"] != canonical_components(attrs["package_components"]):
                        raise ValueError("component set must use canonical normalized multiset")
                elif (row.get("attributes") or {}).get("component_basis"):
                    raise ValueError("component basis requires components")
            except (TypeError, ValueError, OverflowError) as exc:
                errors.append(f"variants[{variant_id}]의 component 규격이 올바르지 않습니다: {exc}")
                continue
            signature = (product_id, quantity, unit, count) if components is None else (product_id, quantity, unit, count, components)
            previous = variant_signatures.get(signature)
            if previous:
                errors.append(f"variants[{variant_id}]는 {previous!r}와 같은 상품군/규격의 중복 variant입니다")
            variant_signatures[signature] = variant_id

    all_variant_ids = existing_variant_ids | set(variants)
    source_keys: dict[tuple[str, str], list[str]] = {}
    for listing_id, row in listings.items():
        if _text(row.get("public_variant_id")) not in all_variant_ids:
            errors.append(f"source_listings[{listing_id}]의 variant 참조가 없습니다")
        if _text(row.get("source_name")) not in {"emart", "homeplus", "lottemart", "costco"}:
            errors.append(f"source_listings[{listing_id}].source_name은 4개 마트 중 하나여야 합니다")
        if not _text(row.get("source_title")):
            errors.append(f"source_listings[{listing_id}].source_title이 필요합니다")
        variant = variants.get(row.get("public_variant_id"), {})
        product = products.get(variant.get("public_product_id"), {})
        from core.reviewed_source_evidence import (source_parent_selection, source_outer_set_count,
                                                   source_nonexact_contents_specification, source_entitlement_specification, source_partial_retail_specification)
        if (source_parent_selection(variant) or source_outer_set_count(variant)
                or source_nonexact_contents_specification(variant) or source_entitlement_specification(variant)
                or source_partial_retail_specification(variant)):
            review = variant['attributes']['explicit_listing_quantity_review']
            if (row.get('source_name') != review['source_name']
                    or row.get('source_record_key') != review['source_record_key']
                    or row.get('source_title') != review['title']
                    or row.get('source_url') not in review['required_source']['source_urls']
                    or row.get('is_active') is not False):
                errors.append(f"source_listings[{listing_id}]의 미선택 옵션 부모 원문 문맥이 올바르지 않습니다")
        physical = (variant.get('attributes') or {}).get('physical_device_specification')
        vector = (variant.get('attributes') or {}).get('source_component_listing')
        if isinstance(vector, Mapping) and vector.get('measurement_role') == 'measured_food_with_nonmeasured_physical_companion':
            required = vector.get('required_source')
            urls = required.get('source_urls') if isinstance(required, Mapping) else None
            if (not isinstance(urls, list) or row.get('source_title') != vector.get('title')
                    or row.get('source_url') not in urls
                    or row.get('source_name') != vector.get('source_name')
                    or row.get('source_record_key') != vector.get('source_record_key')):
                errors.append(f"source_listings[{listing_id}]의 원문 구성 벡터 문맥이 올바르지 않습니다")
        if physical is not None:
            required = physical.get('required_source') if isinstance(physical, Mapping) else None
            urls = required.get('source_urls') if isinstance(required, Mapping) else None
            if (not isinstance(physical, Mapping) or not isinstance(urls, list)
                    or row.get('source_title') != physical.get('title')
                    or row.get('source_url') not in urls):
                errors.append(f"source_listings[{listing_id}]의 물품 규격 원본 문맥이 올바르지 않습니다")
        context = source_identity_context_for_variant(variant, row)
        if ("source_identity_context" in (variant.get("attributes") or {})
                and not valid_source_identity_context(variant, row, product.get("unified_category_id"))):
            errors.append(f"source_listings[{listing_id}]의 검수된 원본 식별 문맥이 올바르지 않습니다")
        source_key = _text(row.get("source_record_key"))
        if source_key:
            key = (_text(row.get("source_name")), source_key)
            for prior_listing_id in source_keys.get(key, []):
                previous = listings[prior_listing_id]
                prior_variant = variants.get(previous.get("public_variant_id"), {})
                prior_product = products.get(prior_variant.get("public_product_id"), {})
                prior_context = source_identity_context_for_variant(prior_variant, previous)
                # Registered source contexts, never price or a native-ID exception,
                # may separate an old graded listing from a later distinct product.
                partitioned = (valid_source_identity_context(variant, row, product.get("unified_category_id"))
                               and valid_source_identity_context(prior_variant, previous, prior_product.get("unified_category_id"))
                               and variant["public_product_id"] != prior_variant["public_product_id"]
                               and context["partition_key"] != prior_context["partition_key"]
                               and row["source_title"] != previous["source_title"])
                if not partitioned:
                    errors.append(f"source_listings[{listing_id}] 중복 마트 원본 ID {key!r}")
            source_keys.setdefault(key, []).append(listing_id)

    all_listing_ids = existing_listing_ids | set(listings)
    ambiguous_promotions = 0
    for offer_id, row in offers.items():
        if _text(row.get("public_source_listing_id")) not in all_listing_ids:
            errors.append(f"offers[{offer_id}]의 listing 참조가 없습니다")
        from core.reviewed_source_evidence import package_publication_reason
        listing = listings.get(row.get('public_source_listing_id'), {})
        variant = variants.get(listing.get('public_variant_id'), {})
        if not listing and row.get('public_source_listing_id') in existing_listing_ids:
            existing_listing = session.get(NormalizedSourceListing, row['public_source_listing_id'])
            variant = variants.get(existing_listing.public_variant_id, {})
            if not variant:
                existing_variant = session.get(NormalizedProductVariant, existing_listing.public_variant_id)
                if existing_variant is not None:
                    variant = {key: getattr(existing_variant, key) for key in (
                        'package_quantity', 'package_unit', 'bundle_count', 'standard_unit', 'attributes')}
        if package_publication_reason(variant) and row.get('offer_state') != 'pending_review':
            errors.append(f"offers[{offer_id}]의 미해결 원문 버전 수량은 공개 승인할 수 없습니다")
        from core.reviewed_source_evidence import source_observational_raw_hashes
        hashes = source_observational_raw_hashes(variant)
        if hashes:
            evidence = row.get('raw_evidence')
            observations = evidence.get('observations') if isinstance(evidence, Mapping) else None
            if (not isinstance(observations, list) or not observations
                    or any(not isinstance(obs, Mapping)
                           or not isinstance(obs.get('raw_payload'), Mapping)
                           or hashes.get(obs.get('raw_record_id'))
                              != obs.get('raw_payload_sha256')
                           or _review_digest(obs['raw_payload']) != obs.get('raw_payload_sha256')
                           for obs in observations)):
                errors.append(f"offers[{offer_id}]의 미선택 대안 원문 관측 근거가 올바르지 않습니다")
        try:
            facts = PromotionPriceFacts.from_source(
                current_price=row.get("price"),
                original_price=row.get("original_price"),
                discount_rate=row.get("discount_rate"),
                price_state=row.get("price_state"),
                promotion_type=row.get("promotion_type"),
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"offers[{offer_id}] 가격/프로모션 계약 오류: {exc}")
            continue
        if facts.promotion_type in {PromotionType.UNKNOWN, PromotionType.RATE_OFF_UNCLEAR}:
            ambiguous_promotions += 1
            warnings.append(f"offers[{offer_id}]의 모호한 프로모션은 비교 가격에서 제외됩니다")

    for week_id, row in weeks.items():
        if not row.get("week_start") or not row.get("week_end"):
            errors.append(f"week_buckets[{week_id}]에 week_start/week_end가 필요합니다")
        else:
            try:
                if _datetime(row["week_start"]) >= _datetime(row["week_end"]):
                    errors.append(f"week_buckets[{week_id}]의 종료 시각은 시작보다 뒤여야 합니다")
            except (TypeError, ValueError):
                errors.append(f"week_buckets[{week_id}]의 날짜 형식이 올바르지 않습니다")

    all_offer_ids = existing_offer_ids | set(offers)
    all_week_ids = existing_week_ids | set(weeks)
    link_seen: set[tuple[str, str]] = set()
    for index, row in enumerate(bundle["offer_week_links"]):
        key = (_text(row.get("public_offer_event_id")), _text(row.get("public_week_bucket_id")))
        if key in link_seen:
            errors.append(f"offer_week_links[{index}] 중복 키 {key!r}")
        link_seen.add(key)
        if key[0] not in all_offer_ids or key[1] not in all_week_ids:
            errors.append(f"offer_week_links[{index}] 참조가 없습니다")

    mapping_seen: set[tuple[str, str]] = set()
    for index, row in enumerate(bundle["mart_category_mappings"]):
        key = (_text(row.get("mart")), _text(row.get("mart_native_id")))
        if key in mapping_seen:
            errors.append(f"mart_category_mappings[{index}] 중복 native 키 {key!r}")
        mapping_seen.add(key)
        if key[0] not in {"emart", "homeplus", "lottemart", "costco"}:
            errors.append(f"mart_category_mappings[{index}].mart가 올바르지 않습니다")
        mapped_category = _text(row.get("unified_category_id"))
        if mapped_category not in parent_map:
            errors.append(f"mart_category_mappings[{index}]의 통합 카테고리가 없습니다")
        elif mapped_category in child_ids:
            errors.append(f"mart_category_mappings[{index}]은 통합 리프 카테고리에 매핑해야 합니다")
        if row.get("trust", "external-ai") not in {"human", "external-ai", "auto-aggregate"}:
            errors.append(f"mart_category_mappings[{index}].trust가 올바르지 않습니다")
        _confidence(row.get("confidence", 1.0), f"mart_category_mappings[{index}]", errors)

    all_product_ids |= set(products)
    all_variant_ids |= set(variants)
    match_keys: set[str] = set()
    for index, row in enumerate(bundle["match_rules"]):
        match_key = _text(row.get("match_key"))
        if not match_key:
            errors.append(f"match_rules[{index}].match_key가 필요합니다")
        elif match_key in match_keys:
            errors.append(f"match_rules[{index}] 중복 match_key {match_key!r}")
        match_keys.add(match_key)
        if _text(row.get("public_product_id")) not in all_product_ids:
            errors.append(f"match_rules[{index}]의 normalized product 참조가 없습니다")
        variant_id = _optional_text(row.get("public_variant_id"))
        if variant_id:
            from core.reviewed_source_evidence import (source_parent_selection, source_outer_set_count,
                                                   source_nonexact_contents_specification, source_entitlement_specification, source_partial_retail_specification)
            if (source_parent_selection(variants.get(variant_id, {})) or source_outer_set_count(variants.get(variant_id, {}))
                    or source_nonexact_contents_specification(variants.get(variant_id, {}))
                    or source_entitlement_specification(variants.get(variant_id, {}))
                    or source_partial_retail_specification(variants.get(variant_id, {}))):
                errors.append(f"match_rules[{index}]의 미선택 옵션 부모를 고정 상품 hit으로 사용할 수 없습니다")
        if variant_id and variant_id not in all_variant_ids:
            errors.append(f"match_rules[{index}]의 normalized variant 참조가 없습니다")
        elif variant_id and variant_products.get(variant_id) != _text(row.get("public_product_id")):
            errors.append(f"match_rules[{index}]의 variant가 지정한 상품군에 속하지 않습니다")
        confidence = _confidence(row.get("confidence", 1.0), f"match_rules[{index}]", errors)
        if confidence < LOW_CONFIDENCE:
            errors.append(f"match_rules[{index}]는 confidence 0.80 미만이라 자동 hit 규칙으로 적용할 수 없습니다")

    unresolved = len(bundle["unresolved"])
    try:
        _reviewed_offer_rows(session, bundle)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"offer_interpretation_review: {exc}")
    _validate_observation_accounting(bundle, errors)
    if unresolved:
        warnings.append(f"미분류 {unresolved}건은 공개 카탈로그에 적용되지 않습니다")
    return BundleValidation(
        ok=not errors,
        file_hash=file_hash,
        counts=counts,
        errors=errors,
        warnings=warnings,
        review_counts={
            "low_confidence_approved": review_low,
            "ambiguous_promotions": ambiguous_promotions,
            "unresolved": unresolved,
        },
    )


def apply_bundle(session: Session, bundle: dict[str, Any], file_hash: str, *, user: str) -> dict[str, Any]:
    bundle = {**{key: [] for key in ENTITY_KEYS}, **bundle}
    validation = validate_bundle(session, bundle, file_hash)
    if not validation.ok:
        raise ValueError("catalog bundle validation failed: " + "; ".join(validation.errors[:10]))
    prior = session.execute(
        select(CatalogSyncLog).where(
            CatalogSyncLog.operation == "apply_v2",
            CatalogSyncLog.file_hash == file_hash,
            CatalogSyncLog.ok.is_(True),
        ).order_by(CatalogSyncLog.id.desc())
    ).scalars().first()
    if prior:
        return {**validation.as_dict(), "applied": prior.counts or {}, "idempotent": True}

    reviewed_offers, reviewed_products = _reviewed_offer_rows(session, bundle)
    applied = {key: 0 for key in ENTITY_KEYS if key != "unresolved"}
    category_parent_map = {
        row.id: row.parent_id
        for row in session.execute(select(UnifiedCategory)).scalars().all()
    }
    category_parent_map.update({
        row["id"]: _optional_text(row.get("parent_id"))
        for row in bundle["categories"]
    })
    category_levels = _category_levels(category_parent_map, [])
    for row in bundle["categories"]:
        obj = _upsert(session, UnifiedCategory, row["id"])
        obj.parent_id = _optional_text(row.get("parent_id"))
        obj.slug = _text(row.get("slug")) or row["id"].split(".")[-1]
        obj.name_ko = _text(row.get("name_ko"))
        # Persist the validated tree topology, never a caller-supplied level
        # that can drift from parent_id.
        obj.level = category_levels[row["id"]]
        obj.sort_order = int(row.get("sort_order") or 0)
        obj.source_origin = _optional_text(row.get("source_origin")) or "external-ai"
        applied["categories"] += 1
    session.flush()

    for row in bundle["keywords"]:
        word = _text(row.get("word"))
        obj = session.execute(select(Keyword).where(Keyword.word == word)).scalar_one_or_none()
        if obj is None:
            obj = Keyword(word=word, search_count=0)
            session.add(obj)
        # Search count is mutable usage data and is deliberately not imported
        # from the static catalog definition bundle.
        obj.synonyms = [_text(value) for value in row.get("synonyms", [])]
        obj.unified_category_id = _text(row.get("unified_category_id"))
        obj.is_active = bool(row.get("is_active", True))
        applied["keywords"] += 1
    session.flush()

    for row in bundle["products"]:
        obj = _upsert(session, NormalizedCanonicalProduct, row["public_product_id"])
        confidence_value, review_status = _product_classification(row)
        confidence = float(confidence_value)
        attributes = dict(row.get("attributes") or {})
        attributes.update({
            "classification_confidence": confidence,
            "classification_warning": confidence < LOW_CONFIDENCE,
            "review_status": review_status,
        })
        obj.unified_category_id = row["unified_category_id"]
        obj.category_id = None
        obj.canonical_name = row["canonical_name"]
        obj.brand = _optional_text(row.get("brand"))
        obj.aliases = list(row.get("aliases") or [])
        obj.keywords = list(row.get("keywords") or [])
        obj.attributes = attributes
        obj.primary_image_url = _optional_text(row.get("primary_image_url"))
        obj.is_active = bool(row.get("is_active", True))
        obj.projection_version = SCHEMA_VERSION
        applied["products"] += 1
    session.flush()

    for row in bundle["variants"]:
        obj = _upsert(session, NormalizedProductVariant, row["public_variant_id"])
        for key in ("public_product_id", "variant_name", "package_quantity", "package_unit", "display_unit", "bundle_count", "standard_unit", "attributes", "is_active"):
            if key in row:
                setattr(obj, key, row[key])
        obj.variant_name = obj.variant_name or row["public_variant_id"]
        obj.bundle_count = int(obj.bundle_count or 1)
        obj.attributes = obj.attributes or {}
        obj.projection_version = SCHEMA_VERSION
        applied["variants"] += 1
    session.flush()

    superseded_variants: set[str] = set()
    for row in bundle["source_listings"]:
        obj = _upsert(session, NormalizedSourceListing, row["public_source_listing_id"])
        if obj.public_variant_id and obj.public_variant_id != row["public_variant_id"]:
            superseded_variants.add(obj.public_variant_id)
        for key in ("public_variant_id", "source_name", "source_record_key", "source_title", "source_url", "image_url", "source_unit_text", "is_active"):
            if key in row:
                setattr(obj, key, row[key])
        obj.projection_version = SCHEMA_VERSION
        applied["source_listings"] += 1
    session.flush()

    for incoming in bundle["offers"]:
        row = reviewed_offers.get(incoming["public_offer_event_id"], incoming)
        facts = PromotionPriceFacts.from_source(
            current_price=row.get("price"), original_price=row.get("original_price"),
            discount_rate=row.get("discount_rate"), price_state=row.get("price_state"),
            promotion_type=row.get("promotion_type"),
        ).with_safe_calculations()
        obj = _upsert(session, NormalizedOfferEvent, row["public_offer_event_id"])
        obj.public_source_listing_id = row["public_source_listing_id"]
        obj.price_state = facts.price_state.value
        obj.promotion_type = facts.promotion_type.value
        obj.price = facts.current_price
        obj.original_price = facts.original_price
        obj.discount_rate = facts.discount_rate
        for key in ("event_name", "standard_unit_price", "price_per_100g", "offer_state"):
            if key in row:
                setattr(obj, key, row[key])
        # Repeated sightings may have the same offer identity but a different
        # ingestion id. Upsert must accumulate evidence, never erase it.
        obj.raw_evidence, obj.audit_provenance = _merge_offer_evidence(
            obj.raw_evidence or {}, obj.audit_provenance or {},
            row.get("raw_evidence") or {}, row.get("audit_provenance") or {},
        )
        obj.raw_record_id = obj.raw_record_id or row.get("raw_record_id")
        obj.valid_from = _datetime(row.get("valid_from"))
        obj.valid_to = _datetime(row.get("valid_to"))
        obj.crawled_at = _datetime(row.get("crawled_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        obj.raw_evidence = obj.raw_evidence or {}
        obj.audit_provenance = obj.audit_provenance or {}
        obj.offer_state = obj.offer_state or "active"
        obj.projection_version = SCHEMA_VERSION
        applied["offers"] += 1
    session.flush()

    # Only a source-bound approved active offer may restore visibility after
    # an older official bundle repeats its original is_active=False product.
    for product_id in reviewed_products:
        session.get(NormalizedCanonicalProduct, product_id).is_active = True

    for row in bundle["week_buckets"]:
        obj = _upsert(session, NormalizedWeekBucket, row["public_week_bucket_id"])
        obj.week_start = _datetime(row.get("week_start"))
        obj.week_end = _datetime(row.get("week_end"))
        obj.projection_version = SCHEMA_VERSION
        applied["week_buckets"] += 1
    session.flush()

    for row in bundle["offer_week_links"]:
        key = (row["public_offer_event_id"], row["public_week_bucket_id"])
        obj = session.get(NormalizedOfferWeekLink, key)
        if obj is None:
            obj = NormalizedOfferWeekLink(public_offer_event_id=key[0], public_week_bucket_id=key[1])
            session.add(obj)
        obj.observed_min_price = row.get("observed_min_price")
        obj.observed_max_price = row.get("observed_max_price")
        applied["offer_week_links"] += 1

    for row in bundle["mart_category_mappings"]:
        obj = session.execute(select(MartCategoryMapping).where(
            MartCategoryMapping.mart == row["mart"],
            MartCategoryMapping.mart_native_id == str(row["mart_native_id"]),
        )).scalar_one_or_none()
        if obj is None:
            obj = MartCategoryMapping(mart=row["mart"], mart_native_id=str(row["mart_native_id"]), unified_category_id=row["unified_category_id"])
            session.add(obj)
        obj.mart_native_path = _optional_text(row.get("mart_native_path"))
        obj.unified_category_id = row["unified_category_id"]
        obj.trust = row.get("trust") or "external-ai"
        obj.confidence = float(row.get("confidence", 1.0))
        obj.decided_by = _optional_text(row.get("decided_by")) or user
        applied["mart_category_mappings"] += 1

    for row in bundle["match_rules"]:
        obj = session.execute(select(MatchingEntry).where(MatchingEntry.match_key == row["match_key"])).scalar_one_or_none()
        if obj is not None and obj.source == "human":
            continue
        if obj is None:
            obj = MatchingEntry(match_key=row["match_key"])
            session.add(obj)
        obj.public_product_id = row["public_product_id"]
        obj.public_variant_id = _optional_text(row.get("public_variant_id"))
        obj.canonical_product_id = None
        obj.category_id = None
        obj.brand = _optional_text(row.get("brand"))
        obj.name_core = _optional_text(row.get("name_core"))
        obj.pack_qty = row.get("pack_qty")
        obj.pack_unit = _optional_text(row.get("pack_unit"))
        obj.confidence = float(row.get("confidence", 1.0))
        obj.source = "external-ai"
        obj.notes = _optional_text(row.get("notes")) or f"bundle:{file_hash[:12]}"
        applied["match_rules"] += 1

    # Preserve the old ID/specification for audit and saved account references,
    # but do not present an unreferenced corrected specification as a sale option.
    # Only variants displaced by these exact listing updates are candidates;
    # unrelated omitted variants and other listings/rules remain untouched.
    incoming_variants = {row["public_variant_id"] for row in bundle["variants"]}
    retired_variants = []
    session.flush()
    for variant_id in sorted(superseded_variants - incoming_variants):
        listing = session.execute(select(NormalizedSourceListing.public_source_listing_id).where(
            NormalizedSourceListing.public_variant_id == variant_id).limit(1)).first()
        rule = session.execute(select(MatchingEntry.id).where(
            MatchingEntry.public_variant_id == variant_id).limit(1)).first()
        if listing is None and rule is None:
            old_variant = session.get(NormalizedProductVariant, variant_id)
            if old_variant is not None:
                old_variant.is_active = False
                retired_variants.append(variant_id)

    session.add(CatalogSyncLog(
        operation="apply_v2", entities=list(ENTITY_KEYS), mode="upsert",
        scope={"run_id": bundle.get("run_id")}, counts=applied,
        file_hash=file_hash, user=user, dry_run=False, ok=True,
    ))
    session.flush()
    return {**validation.as_dict(), "applied": applied, "idempotent": False,
            "preserved_inactive_superseded_variant_ids": retired_variants}


def _product_classification(row: Mapping) -> tuple[Any, str]:
    """Stored normalized products retain classification metadata in attributes."""
    attributes = row.get('attributes') or {}
    return (row.get('classification_confidence', attributes.get('classification_confidence', 1.0)),
            row.get('review_status') or attributes.get('review_status') or 'auto')


def product_bundle_row(product: NormalizedCanonicalProduct) -> dict:
    """Serialize the existing product-only model without SQL JSON string casts."""
    row = {column.name: deepcopy(getattr(product, column.name))
           for column in product.__table__.columns
           if column.name not in {'created_at', 'updated_at'}}
    confidence, review_status = _product_classification(row)
    row.update(classification_confidence=confidence, review_status=review_status)
    return row


def _review_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _review_quote(row: dict) -> dict:
    quote = {key: row.get(key) for key in ("price", "original_price", "price_state", "event_name")}
    for key in ("valid_from", "valid_to", "crawled_at"):
        stamp = _datetime(row.get(key))
        quote[key] = stamp.isoformat() + "Z" if stamp else None
    return quote


def _review_observations(evidence: dict) -> list[dict]:
    if not isinstance(evidence, dict):
        raise ValueError("original evidence must be an object")
    observations = evidence.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("original observations required")
    bindings = []
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError("original observation must be an object")
        raw_id = observation.get("raw_record_id")
        payload = observation.get("raw_payload")
        digest = observation.get("raw_payload_sha256")
        if not isinstance(raw_id, str) or not raw_id or not isinstance(payload, dict) or digest != _review_digest(payload):
            raise ValueError("original observation payload/hash mismatch")
        bindings.append({"raw_record_id": raw_id, "raw_payload_sha256": digest,
                         "observation_sha256": _review_digest(observation)})
    if len({row["raw_record_id"] for row in bindings}) != len(bindings):
        raise ValueError("duplicate original observation")
    return sorted(bindings, key=lambda row: row["raw_record_id"])


def _review_context(session: Session, bundle: dict, listing_id: str, *, incoming: bool) -> dict:
    def entity(key, model, primary_key, identity, fields):
        stored = session.get(model, identity)
        if stored is None:
            raise ValueError(f"existing {key} required: {identity}")
        row = {field: getattr(stored, field) for field in fields}
        if incoming:
            update = next((item for item in bundle[key] if item[primary_key] == identity), None)
            if update:
                row.update({field: update[field] for field in fields if field in update})
        return row
    listing = entity("source_listings", NormalizedSourceListing, "public_source_listing_id", listing_id,
                     ("public_variant_id", "source_name", "source_record_key", "source_title", "source_url"))
    variant_id = listing["public_variant_id"]
    variant = entity("variants", NormalizedProductVariant, "public_variant_id", variant_id,
                     ("public_product_id", "variant_name", "display_unit", "package_quantity",
                      "package_unit", "bundle_count", "standard_unit", "attributes"))
    product_id = variant["public_product_id"]
    product = entity("products", NormalizedCanonicalProduct, "public_product_id", product_id,
                     ("unified_category_id",))
    spec = {key: variant[key] for key in ("variant_name", "display_unit", "package_quantity",
                                        "package_unit", "bundle_count", "standard_unit")}
    spec["attributes_sha256"] = _review_digest(variant["attributes"] or {})
    return {"public_source_listing_id": listing_id, "public_variant_id": variant_id,
            "public_product_id": product_id, "unified_category_id": product["unified_category_id"],
            **{key: listing[key] for key in ("source_name", "source_record_key", "source_title", "source_url")},
            "variant_spec": spec}


def _review_source_title_matches(binding: dict, raw: dict, observed_title: Any) -> bool:
    if observed_title == binding['source_title']:
        return True
    from core.reviewed_source_evidence import listing_title_history
    history = listing_title_history(binding['source_name'], binding['source_record_key'], raw, observed_title)
    return (history is not None
            and history['category_id'] == binding['unified_category_id']
            and any(alias['title'] == binding['source_title'] for alias in history['aliases']))


def _native_quote_terms(binding: dict, evidence: dict, variant_attributes: dict | None) -> tuple[dict, dict]:
    """Review declared native quote nodes, without confirming a transaction.

    Quote hashes bind this historical event's money, never product identity.
    Only persisted source-context reviews can bridge a different observed URL.
    """
    from core.catalog_matching import _normalized_source_reason
    from core.product_units import parse_package_quantity
    from core.reviewed_source_evidence import source_review_evidence, source_review_matches

    source, native = binding['source_name'], binding['source_record_key']
    if source not in {'homeplus', 'costco', 'lottemart'} or not isinstance(variant_attributes, dict):
        raise ValueError('supported native source and persisted variant attributes required')

    def native_url(value):
        if not isinstance(value, str):
            raise ValueError('original native URL required')
        url = urlparse(value)
        valid = url.scheme == 'https' and not url.username and not url.password and not url.fragment
        if source == 'homeplus':
            query = parse_qs(url.query, keep_blank_values=True)
            valid = (valid and url.netloc == 'mfront.homeplus.co.kr' and url.path == '/item'
                     and query.get('itemNo') == [native] and query.get('storeType') in (['HYPER'], ['EXP']))
        elif source == 'costco':
            valid = (valid and url.netloc in {'www.costco.co.kr', 'costco.co.kr'}
                     and url.path.endswith('/p/' + native) and not url.query)
        else:
            valid = (valid and url.netloc == 'lottemartzetta.com'
                     and url.path == f'/products/OS{native}/details' and not url.query)
        if not valid:
            raise ValueError('native source URL/host/store mismatch')
        return url

    native_url(binding['source_url'])
    variant = {**binding['variant_spec'], 'attributes': variant_attributes,
               'public_variant_id': binding['public_variant_id'],
               'public_product_id': binding['public_product_id'],
               'unified_category_id': binding['unified_category_id'],
               'source_listings': [{key: binding[key] for key in
                                   ('source_name', 'source_record_key', 'source_title', 'source_url')}]}

    def count(value, *, optional=False):
        if value is None and optional:
            return None
        if type(value) is not int or value < 1:
            raise ValueError('source purchase/selection quantity must be a positive integer')
        return value

    def money(value):
        amount = confirmed_price_or_none(value)
        if amount is None or amount != binding['quote']['price']:
            raise ValueError('original source quote differs from historical event')

    def declared_package(text):
        package = parse_package_quantity(text) if isinstance(text, str) else None
        if (not package or text.strip() != package['raw_match']
                or normalize_pack_identity(package['package_quantity'], package['package_unit'])
                   != normalize_pack_identity(binding['variant_spec']['package_quantity'], binding['variant_spec']['package_unit'])
                or package.get('bundle_count', 1) != binding['variant_spec']['bundle_count']):
            raise ValueError('original source package declaration differs from reviewed specification')

    previous = expected = None
    for observation in evidence['observations']:
        raw = observation['raw_payload']
        attrs = raw.get('attributes')
        if not isinstance(attrs, dict):
            raise ValueError('original source attributes required')
        # Multiple money aliases are quotes for this SAME original event.
        # They are not inputs to the native/product/specification matcher.
        for layer in (raw, attrs):
            for key in ('price', 'sale_price'):
                if key in layer and layer[key] is not None:
                    money(layer[key])
        urls = source_review_evidence(raw)['source_urls']
        if len(urls) != 1:
            raise ValueError('one complete original source URL context required')
        observed_url = urls[0]
        url = native_url(observed_url)
        if observed_url != binding['source_url']:
            reviews = variant_attributes.get('source_evidence_reviews')
            if not isinstance(reviews, list) or not reviews or any(not isinstance(item, dict) for item in reviews):
                raise ValueError('persisted exact source context required for observed URL')
            bound = [item for item in reviews if item.get('source_name') == source
                     and item.get('source_record_key') == native]
            if (not bound or any(not source_review_matches(item, item) for item in bound)
                    or sum(source_review_matches(source_review_evidence(raw), item) for item in bound) != 1):
                raise ValueError('observed URL does not match one persisted source context')
        reason = _normalized_source_reason(raw, raw.get('match_key', ''), binding,
                                           {binding['public_variant_id']: variant})
        if reason is not None:
            raise ValueError('original native source/specification conflict: ' + reason)
        for layer in (raw, attrs):
            for key in ('raw_promo_type', 'discount_percent', 'minimum_quantity', 'received_package_count'):
                if layer.get(key) is not None and layer.get(key) != '':
                    raise ValueError('unreviewed source transaction/discount claim')
        marker = {'source_condition_kind': 'source_quote_purchase_conditions_unverified',
                  'payable_price_unconfirmed': True}
        extra = {'coupon_application_unconfirmed': True}
        event = binding['quote']['event_name']
        if source == 'homeplus':
            node = attrs.get('homeplus_detail_source_fields')
            if (not isinstance(node, dict)
                    or attrs.get('homeplus_detail_source_fields_sha256') != _review_digest(node)):
                raise ValueError('hashed original Homeplus source fields required')
            basic, sale = node.get('basic'), node.get('sale')
            store = parse_qs(url.query)['storeType'][0]
            if (not isinstance(basic, dict) or not isinstance(sale, dict)
                    or basic.get('itemNo') != native or basic.get('storeType') != store
                    or not _review_source_title_matches(binding, raw, basic.get('itemNm')) or event is not None):
                raise ValueError('original Homeplus native/title/store/event mismatch')
            for sibling in ('sale', 'opt', 'prop', 'etc', 'promo'):
                part = node.get(sibling)
                if part is not None:
                    if not isinstance(part, dict) or any(part.get(key) not in (None, expected) for key, expected in
                                                        (('itemNo', native), ('storeType', store))):
                        raise ValueError('original Homeplus sibling native/store conflict')
            options = node.get('opt') or {}
            if any(options.get(key) not in (None, 'N') for key in ('groupUseYn', 'optSelUseYn', 'optTxtUseYn')):
                raise ValueError('original Homeplus option selection unconfirmed')
            money(sale.get('salePrice'))
            if type(sale.get('dcPrice')) not in (int, float) or sale['dcPrice'] != 0:
                raise ValueError('supported undiscounted Homeplus source quote required')
            if sale.get('eventList') not in (None, []) or sale.get('dcPriceInfo') not in (None, []):
                raise ValueError('unsupported Homeplus source price event')
            minimum = count(sale.get('purchaseMinQty'), optional=True)
            maximum = count(sale.get('purchaseLimitQty')) if sale.get('purchaseLimitYn') == 'Y' else None
            if sale.get('purchaseLimitYn') not in ('Y', 'N', None):
                raise ValueError('source purchase limit flag malformed')
            if maximum is not None:
                duration, day = sale.get('purchaseLimitDuration'), sale.get('purchaseLimitDay')
                message = re.sub(r'\s+', '', str(sale.get('itemPurchaseLimitMessage', '')))
                if (duration == 'O' and (type(day) is not int or day != 0
                                        or message != f'최대{maximum}개구매가능')
                        or duration == 'P' and (type(day) is not int or day < 1
                                               or message != f'{day}일동안최대{maximum}개구매가능')
                        or duration not in {'O', 'P'}):
                    raise ValueError('source purchase limit declaration conflict')
            currencies = [layer[key] for layer in (basic, sale) for key in ('currency', 'currencyIso')
                          if layer.get(key) is not None]
            if any(value != 'KRW' for value in currencies):
                raise ValueError('unsupported source currency')
            currency = 'KRW' if currencies else None
            marker.update(coupon_application_unconfirmed=True,
                          minimum_purchase_quantity_unconfirmed=minimum is None,
                          source_minimum_purchase_quantity=minimum,
                          source_maximum_purchase_quantity=maximum, source_quote_currency=currency)
            extra['source_purchase_limit'] = {key: deepcopy(sale.get(key)) for key in
                ('purchaseLimitYn', 'purchaseLimitDuration', 'purchaseLimitDay', 'purchaseLimitQty',
                 'itemPurchaseLimitMessage', 'cartLimitYn')}
            notices = node.get('notice', [])
            if not isinstance(notices, list) or any(not isinstance(item, dict) for item in notices):
                raise ValueError('source quantity notices malformed')
            for notice in notices:
                if '용량' in str(notice.get('noticeNm', '')) or '수량' in str(notice.get('noticeNm', '')):
                    declared_package(notice.get('noticeDesc'))
            promo = node.get('promo') or {}
            if not isinstance(promo, dict) or not isinstance(promo.get('couponList', []), list):
                raise ValueError('public source coupon declarations malformed')
            keys = ('displayCouponNm', 'manageCouponNm', 'storeType', 'couponType', 'purchaseMin',
                    'discount', 'discountType', 'discountMax', 'validType', 'validDay', 'validStartDt',
                    'validEndDt', 'issueStartDt', 'issueEndDt', 'downloadAvailYn', 'issueYn',
                    'issueLimitType', 'issueMaxCnt', 'issueTimeYn', 'issueStartTime', 'issueEndTime',
                    'limitPerCnt', 'limitPerDayYn', 'limitPerDayCnt', 'liquorExceptYn', 'localLiquorExceptYn')
            def coupon(value):
                if value is None:
                    return None
                if not isinstance(value, dict) or value.get('storeType') != store:
                    raise ValueError('native store public coupon declaration required')
                if any(confirmed_price_or_none(value.get(key)) is None for key in ('purchaseMin', 'discount')):
                    raise ValueError('source coupon threshold/amount malformed')
                return {key: deepcopy(value[key]) for key in keys if key in value}
            extra['source_coupon_declarations'] = {'couponInfo': coupon(promo.get('couponInfo')),
                                                   'couponList': [coupon(item) for item in promo.get('couponList', [])]}
        elif source == 'costco':
            records = attrs.get('submission_business_evidence')
            if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
                raise ValueError('one original Costco native product node required')
            node = records[0].get('raw_product_node')
            fields = records[0].get('original_product_field_names')
            if (not isinstance(node, dict) or not isinstance(fields, list)
                    or any(not isinstance(key, str) for key in fields)
                    or node.get('code') != native or node.get('name') != raw.get('name')
                    or not _review_source_title_matches(binding, raw, node.get('name'))
                    or node.get('url') != url.path or event is not None):
                raise ValueError('original Costco native/title/URL/event mismatch')
            for price in (node.get('price'), node.get('basePrice')):
                if not isinstance(price, dict) or price.get('currencyIso') != 'KRW':
                    raise ValueError('original Costco KRW quote required')
                money(price.get('value'))
                if 'intValue' in price:
                    money(price['intValue'])
            missing = sorted(set(fields) - set(node))
            marker.update(membership_eligibility_unconfirmed=True,
                          source_minimum_purchase_quantity=count(node.get('minOrderQuantity'), optional=True),
                          source_maximum_order_quantity=count(node.get('maxOrderQuantity'), optional=True),
                          source_quote_currency='KRW', source_public_flag_values_unrecoverable=bool(missing))
            extra['source_unrecoverable_public_fields'] = missing
            extra['source_coupon_declaration'] = deepcopy(node.get('couponDiscount'))
        else:
            node = attrs.get('lottemart_detail_source_fields')
            if (not isinstance(node, dict)
                    or attrs.get('lottemart_detail_source_fields_sha256') != _review_digest(node)
                    or node.get('retailerProductId') != 'OS' + native or node.get('name') != raw.get('name')
                    or not _review_source_title_matches(binding, raw, node.get('name'))):
                raise ValueError('hashed original Lotte native/title product required')
            declared_package(node.get('packSizeDescription'))
            price = node.get('price')
            if not isinstance(price, dict) or price.get('currency') != 'KRW':
                raise ValueError('original Lotte KRW quote required')
            money(price.get('amount'))
            promotions = node.get('promotions')
            if (not isinstance(promotions, list) or len(promotions) != 1
                    or not isinstance(promotions[0], dict) or promotions[0].get('description') != event):
                raise ValueError('one original Lotte selection declaration required')
            facts = conditional_selection_facts_or_none(event)
            if facts is None or facts.get('source_condition_kind') != 'selected_free_item':
                raise ValueError('supported literal selection/free declaration required')
            quantity = count(promotions[0].get('requiredProductQuantity'))
            if quantity != facts['required_selection_quantity']:
                raise ValueError('source selection quantity/literal conflict')
            marker.update(selected_product_scope_unconfirmed=True, source_required_product_quantity=quantity,
                          source_free_quantity=facts['conditional_free_quantity'], source_quote_currency='KRW')
            extra['condition_text'] = event
        # The capture may retain several published product views. Never
        # discard a conflicting quote/specification in a supplemental view.
        if source != 'costco' and 'submission_business_evidence' in attrs:
            records = attrs['submission_business_evidence']
            if not isinstance(records, list) or not records:
                raise ValueError('original supplemental native views malformed')
            for record in records:
                view = record.get('raw_product_node') if isinstance(record, dict) else None
                if not isinstance(view, dict):
                    raise ValueError('original supplemental native product required')
                if source == 'homeplus':
                    basic_view, sale_view = view.get('basic'), view.get('sale')
                    if (not isinstance(basic_view, dict) or not isinstance(sale_view, dict)
                            or any(basic_view.get(key) != node['basic'].get(key) for key in
                                   ('itemNo', 'itemNm', 'storeType'))
                            or any(key in sale_view and _review_digest(sale_view[key]) != _review_digest(node['sale'].get(key))
                                   for key in ('salePrice', 'dcPrice', 'purchaseMinQty', 'purchaseLimitYn',
                                               'purchaseLimitDuration', 'purchaseLimitDay', 'purchaseLimitQty',
                                               'itemPurchaseLimitMessage'))):
                        raise ValueError('supplemental Homeplus native/quote/purchase facts conflict')
                    money(sale_view.get('salePrice'))
                    prop = view.get('prop') or {}
                    notices = prop.get('noticeList', []) if isinstance(prop, dict) else None
                    if not isinstance(notices, list) or any(not isinstance(item, dict) for item in notices):
                        raise ValueError('supplemental Homeplus quantity notices malformed')
                    for notice in notices:
                        if '용량' in str(notice.get('noticeNm', '')) or '수량' in str(notice.get('noticeNm', '')):
                            declared_package(notice.get('noticeDesc'))
                else:
                    if view.get('name') != node['name']:
                        raise ValueError('supplemental Lotte source title conflict')
                    if 'retailerProductId' in view:
                        if view['retailerProductId'] != 'OS' + native:
                            raise ValueError('supplemental Lotte native conflict')
                        declared_package(view.get('packSizeDescription'))
                        price_view = view.get('price')
                        if not isinstance(price_view, dict) or price_view.get('currency') != 'KRW':
                            raise ValueError('supplemental Lotte currency conflict')
                        money(price_view.get('amount'))
                        promos = view.get('promotions')
                        if (not isinstance(promos, list) or len(promos) != 1 or not isinstance(promos[0], dict)
                                or promos[0].get('description') != event
                                or _review_digest(promos[0].get('requiredProductQuantity')) != _review_digest(quantity)):
                            raise ValueError('supplemental Lotte selection facts conflict')
                    else:
                        offer_view = view.get('offers')
                        if (view.get('sku') != 'OS' + native or not isinstance(offer_view, dict)
                                or offer_view.get('priceCurrency') != 'KRW'):
                            raise ValueError('supplemental Lotte native/currency conflict')
                        declared_package(view.get('size'))
                        money(offer_view.get('price'))
        if _review_digest(attrs.get('promotion_conditions')) != _review_digest(marker):
            raise ValueError('original native quote markers differ from declared source facts')
        terms = {**marker, **extra, 'currency_unconfirmed': marker['source_quote_currency'] is None}
        if previous is not None and (_review_digest(previous) != _review_digest(marker)
                                     or _review_digest(expected) != _review_digest(terms)):
            raise ValueError('original native source conditions differ between observations')
        previous, expected = marker, terms
    return {'promotion_conditions': previous}, expected


def _review_terms(review: dict, binding: dict, evidence: dict,
                  variant_attributes: dict | None = None) -> tuple[dict, dict]:
    family = review.get("family")
    title, event = binding["source_title"], binding["quote"]["event_name"]
    url = urlparse(binding["source_url"])
    native = binding["source_record_key"]
    homeplus_conditional = (family == 'conditional_selection_observation'
                            and binding['source_name'] == 'homeplus')
    if re.search(r"\d\s*\+\s*\d|무료|증정|할인|쿠폰|회원|체크아웃|checkout|buy\s*\d|free", title, re.I):
        raise ValueError("source title contains unsupported promotion/eligibility terms")
    if family == 'native_source_quote_purchase_conditions_unverified':
        before, terms = _native_quote_terms(binding, evidence, variant_attributes)
    elif family == "minimum_order2_without_discount":
        if (binding["source_name"] != "costco" or url.hostname not in {"www.costco.co.kr", "costco.co.kr"}
                or url.path != url.path.rsplit("/p/", 1)[0] + "/p/" + native
                or not re.search(r"최소\s*구매\s*(?:수량\s*)?[:：]?\s*2(?=\s|$|[/,)])", title)
                or event is not None):
            raise ValueError("literal Costco native minimum purchase2 required")
        before = {"source_title_purchase_condition": title}
        terms = {**before, "minimum_quantity": 2, "condition_text": "최소구매 2"}
    elif family == "informationalannotations":
        informational = (event == "컷팅과일 구매 후 바로 드시길 권장합니다"
                         or bool(re.fullmatch(r"(?:산란일자가|유통기한이|소비기한이) [\d./~ -]+ 인 상품입니다\.", event or ""))
                         or event in {"포장이 파손된 상품입니다.", "일부 상품이 깨진 상품입니다."})
        if (binding["source_name"] != "lottemart" or url.hostname != "lottemartzetta.com"
                or url.path != f"/products/OS{native}/details" or not informational):
            raise ValueError("literal nonmonetary source annotation required")
        before, terms = {}, {}
    elif family == "observed_source_quote_purchase_conditions_unverified" or homeplus_conditional:
        query = parse_qs(url.query, keep_blank_values=True)
        if (binding["source_name"] != "homeplus" or url.scheme != "https"
                or url.hostname != "mfront.homeplus.co.kr" or url.path != "/item"
                or query.get("itemNo") != [native] or len(query.get("storeType", [])) != 1
                or query["storeType"][0] not in {"HYPER", "EXP"}
                or (not homeplus_conditional and event is not None)):
            raise ValueError("native-bound Homeplus source quote without inferred event required")
        unverified = {"source_condition_kind": "source_quote_purchase_conditions_unverified",
                 "payable_price_unconfirmed": True, "minimum_purchase_quantity_unconfirmed": True,
                 "coupon_application_unconfirmed": True}
        terms = conditional_selection_facts_or_none(event) if homeplus_conditional else unverified
        if homeplus_conditional and (terms is None or 'source_event_maximum_quantity' not in terms):
            raise ValueError('literal native Homeplus conditional basket total required')
        before = {"promotion_conditions": unverified}
        source_facts = None
        for observation in evidence["observations"]:
            raw = observation["raw_payload"]
            attrs = raw.get("attributes") or {}
            source = attrs.get("homeplus_detail_source_fields") if isinstance(attrs, dict) else None
            if (not isinstance(source, dict)
                    or attrs.get("homeplus_detail_source_fields_sha256") != _review_digest(source)
                    or _review_digest(attrs.get("promotion_conditions")) != _review_digest(unverified)):
                raise ValueError("original bounded source fields and unverified purchase facts required")
            basic, sale = source.get("basic"), source.get("sale")
            if not isinstance(basic, dict) or not isinstance(sale, dict):
                raise ValueError("original native-bound basic/sale source nodes required")
            declared = confirmed_price_or_none(sale.get("salePrice"))
            discount = sale.get("dcPrice")
            if discount is not None:
                if type(discount) not in (int, float) or not math.isfinite(discount) or discount < 0:
                    raise ValueError("original source discount quote malformed")
                if discount > 0:
                    declared = confirmed_price_or_none(discount)
            same_title = (basic.get('itemNm') == raw.get('name')
                          and _review_source_title_matches(binding, raw, basic.get('itemNm')))
            if (basic.get("itemNo") != native or not same_title
                    or basic.get("storeType") != query["storeType"][0]
                    or declared is None or declared != binding["quote"]["price"]):
                raise ValueError("original source native/title/store/quote differs from reviewed observation")
            if homeplus_conditional:
                events = sale.get('eventList')
                if (not isinstance(events, list) or len(events) != 1
                        or not isinstance(events[0], dict) or events[0].get('dispEventLabel') != event
                        or events[0].get('eventKind') != 'INTERVAL'
                        or events[0].get('changeType') != '2'):
                    raise ValueError('complete original Homeplus interval event required')
                node = events[0]
                intervals = node.get('thresholdIntervals')
                if (type(node.get('eventBenefitQty')) is not int
                        or node['eventBenefitQty'] != terms['required_selection_quantity']
                        or confirmed_price_or_none(node.get('changeAmount')) != terms['conditional_basket_total_won']
                        or not isinstance(intervals, list) or not intervals
                        or any(not isinstance(tier, dict) or type(tier.get('thresholdQty')) is not int
                               or tier['thresholdQty'] <= 0 or confirmed_price_or_none(tier.get('changeAmount')) is None
                               or tier.get('changePercent') is not None or tier.get('thresholdAmount') is not None
                               for tier in intervals)
                        or intervals[0]['thresholdQty'] != terms['required_selection_quantity']
                        or intervals[0]['changeAmount'] != terms['conditional_basket_total_won']
                        or intervals[-1]['thresholdQty'] != terms['source_event_maximum_quantity']
                        or [tier['thresholdQty'] for tier in intervals]
                           != sorted({tier['thresholdQty'] for tier in intervals})):
                    raise ValueError('original source threshold/total/maximum facts conflict')
                facts = {'source_order_minimum_quantity': sale.get('purchaseMinQty'),
                         'source_purchase_limit': {key: deepcopy(sale.get(key)) for key in
                             ('purchaseLimitYn', 'purchaseLimitDuration', 'purchaseLimitDay',
                              'purchaseLimitQty', 'itemPurchaseLimitMessage')},
                         'source_event_period': {'start_date': node.get('eventStartDt'),
                                                 'end_date': node.get('eventEndDt')},
                         'source_selection_price_intervals': deepcopy(intervals),
                         'coupon_application_unconfirmed': True}
                if (type(facts['source_order_minimum_quantity']) is not int
                        or facts['source_order_minimum_quantity'] < 1):
                    raise ValueError('original source order minimum malformed')
                limit = facts['source_purchase_limit']
                if limit['purchaseLimitYn'] == 'Y':
                    if (any(type(limit[key]) is not int or limit[key] < 1
                            for key in ('purchaseLimitDay', 'purchaseLimitQty'))
                            or not isinstance(limit['itemPurchaseLimitMessage'], str)
                            or re.sub(r'\s+', '', limit['itemPurchaseLimitMessage'])
                               != f"{limit['purchaseLimitDay']}일동안최대{limit['purchaseLimitQty']}개구매가능"):
                        raise ValueError('original source purchase limit facts conflict')
                period = facts['source_event_period']
                try:
                    start, end = (date.fromisoformat(period[key]) for key in ('start_date', 'end_date'))
                except (TypeError, ValueError):
                    raise ValueError('original source event period malformed')
                if start > end:
                    raise ValueError('original source event period reversed')
                if source_facts is not None and _review_digest(source_facts) != _review_digest(facts):
                    raise ValueError('original Homeplus source constraints differ between observations')
                source_facts = facts
        if source_facts is not None:
            terms = {**terms, **source_facts}
    elif family in {"conditional_selection_observation", "conditional_program_observation",
                    "conditional_basket_spend_observation"}:
        facts_reader = {"conditional_program_observation": conditional_program_facts_or_none,
                        "conditional_selection_observation": conditional_selection_facts_or_none,
                        "conditional_basket_spend_observation": conditional_basket_spend_facts_or_none}[family]
        terms = facts_reader(event)
        if (binding["source_name"] != "lottemart" or url.hostname != "lottemartzetta.com"
                or url.path != f"/products/OS{native}/details" or terms is None):
            raise ValueError("literal supported Lotte conditional observation required")
        before = {}
    else:
        raise ValueError("unsupported review family")
    for observation in evidence["observations"]:
        raw = observation["raw_payload"]
        attrs = raw.get("attributes") or {}
        if not isinstance(attrs, dict):
            raise ValueError("source attributes must be an object")
        for layer in (raw, attrs):
            for key in ("promo_label", "promo_type", "promotion_type", "promotion_conditions", "coupon_conditions",
                        "is_member_only", "member_only", "membership_required", "coupon_required",
                        "coupon_text", "membership_text", "minimum_purchase_quantity", "min_purchase_quantity",
                        "discount_rate", "checkout_price", "checkout_discount", "buy_quantity", "free_quantity"):
                if ((family in {"observed_source_quote_purchase_conditions_unverified",
                                "native_source_quote_purchase_conditions_unverified"} or homeplus_conditional)
                        and key == "promotion_conditions"
                        and _review_digest(layer.get(key)) == _review_digest(before['promotion_conditions'])):
                    continue
                if layer.get(key) is not None and layer.get(key) != "":
                    raise ValueError("unreviewed promotion/eligibility terms in original source")
        if (isinstance(raw.get("sale_price"), bool) or isinstance(raw.get("price"), bool)
                or raw.get("sale_price") != binding["quote"]["price"]
                or not _review_source_title_matches(binding, raw, raw.get('name'))
                or (raw.get("event_name") != event
                    and not (family in {"observed_source_quote_purchase_conditions_unverified",
                                       "native_source_quote_purchase_conditions_unverified"}
                             and event is None and raw.get("event_name") == ""))
                or raw.get("original_price") is not None
                or (family == "minimum_order2_without_discount" and raw.get("price") != raw.get("sale_price"))):
            raise ValueError("source quote/title/annotation mismatch")
        source_url = raw.get("source_url") or raw.get("canonical_url") or raw.get("detail_url") or attrs.get("source_url")
        if family != 'native_source_quote_purchase_conditions_unverified' and source_url != binding["source_url"]:
            raise ValueError("original source URL mismatch")
    return before, terms


def _review_category_context(review: dict, old: dict, row: dict | None,
                             current: dict, incoming: dict) -> tuple[dict, list[dict]]:
    """Append approved category refinements without replacing an offer review.

    This SAME historical event retains its source, specification and quote.
    Source-only replay may omit history; a stale product category may not erase it.
    """
    key = "offer_category_context_history"
    stored = (old.get("audit_provenance") or {}).get(key, [])
    proposed = ((row or {}).get("audit_provenance") or {}).get(key, stored)
    if (not isinstance(stored, list) or not isinstance(proposed, list)
            or len(proposed) < len(stored) or len(proposed) > len(stored) + 1
            or proposed[:len(stored)] != stored
            or (proposed and not (old.get("audit_provenance") or {}).get("offer_interpretation_review"))):
        raise ValueError("approved category context history is append-only")
    binding = review.get("binding")
    if not isinstance(binding, dict):
        raise ValueError("original historical offer binding required")
    original = {field: binding.get(field) for field in current}
    cursor = original
    for index, transition in enumerate(proposed):
        if not isinstance(transition, dict):
            raise ValueError("approved category context must be an object")
        stamp = datetime.fromisoformat(str(transition.get("approved_at", "")).replace("Z", "+00:00"))
        before, after = transition.get("before_context"), transition.get("after_context")
        if (type(transition.get("version")) is not int or transition["version"] != 1
                or transition.get("status") != "approved"
                or transition.get("reason") != "supported_category_form_refinement"
                or not isinstance(transition.get("approved_by"), str)
                or not _text(transition["approved_by"]) or stamp.tzinfo is None
                or transition.get("original_review_sha256") != _review_digest(review)
                or before != cursor or not isinstance(after, dict)
                or set(after) != set(before)
                or not isinstance(after.get("unified_category_id"), str)
                or not _text(after["unified_category_id"])
                or after["unified_category_id"] == before["unified_category_id"]
                or {k: v for k, v in after.items() if k != "unified_category_id"}
                   != {k: v for k, v in before.items() if k != "unified_category_id"}
                or transition.get("before_context_sha256") != _review_digest(before)
                or transition.get("after_context_sha256") != _review_digest(after)
                or transition.get("observations") != binding.get("observations")):
            raise ValueError("category refinement cannot change original review/source/spec binding")
        if index >= len(stored):
            from services.initial_taxonomy import classify_record
            classifications = [classify_record({**observation,
                               "source_name": current["source_name"],
                               "source_record_key": current["source_record_key"],
                               "source_title": current["source_title"]})
                               for observation in old["raw_evidence"]["observations"]]
            if any(result.get("review_status") != "classified"
                   or result.get("unified_category_id") != after["unified_category_id"]
                   for result in classifications):
                raise ValueError("new category form requires supported original source classification")
        cursor = after
        if index + 1 == len(stored) and current != cursor:
            raise ValueError("stored reviewed category context no longer matches source/spec")
    if (not stored and current != original) or incoming != cursor:
        raise ValueError("incoming source/spec/category context changed; new review required")
    return original, proposed


def _reviewed_offer_rows(session: Session, bundle: dict) -> tuple[dict, set[str]]:
    """Replay moderator-reviewed interpretation; source identity never matches on price.

    Quote/observation hashes protect this SAME historical offer's audit only.
    A new-price observation with another event ID never inherits its review.
    Moderator authentication remains the existing official bundle route boundary.
    """
    incoming = {row["public_offer_event_id"]: row for row in bundle["offers"]}
    if any(not isinstance(row.get("audit_provenance") or {}, dict) for row in incoming.values()):
        raise ValueError("offer audit provenance must be an object")
    stored_reviews = {row.public_offer_event_id: row for row in session.execute(
        select(NormalizedOfferEvent).where(
            NormalizedOfferEvent.audit_provenance["offer_interpretation_review"].as_string().is_not(None)
        )).scalars()}
    candidates = set(stored_reviews) | {identity for identity, row in incoming.items()
                                      if any(key in (row.get("audit_provenance") or {}) for key in
                                             ("offer_interpretation_review", "offer_category_context_history"))}
    effective, visible = {}, set()
    for identity in candidates:
        obj = stored_reviews.get(identity) or session.get(NormalizedOfferEvent, identity)
        if obj is None:
            raise ValueError("review requires the SAME existing original offer ID")
        old = {key: getattr(obj, key) for key in ("public_offer_event_id", "public_source_listing_id", "price",
               "original_price", "price_state", "event_name", "valid_from", "valid_to", "crawled_at",
               "promotion_type", "offer_state", "raw_evidence", "audit_provenance")}
        row = incoming.get(identity)
        old_review = (old["audit_provenance"] or {}).get("offer_interpretation_review")
        new_review = ((row or {}).get("audit_provenance") or {}).get("offer_interpretation_review")
        review = new_review if new_review is not None else old_review
        if not isinstance(review, dict) or (old_review is not None and new_review is not None and new_review != old_review):
            raise ValueError("review replacement or malformed review")
        approved_at = datetime.fromisoformat(str(review.get("approved_at", "")).replace("Z", "+00:00"))
        if (type(review.get("version")) is not int or review["version"] != 1
                or review.get("status") != "approved" or not isinstance(review.get("approved_by"), str)
                or not _text(review.get("approved_by"))
                or approved_at.tzinfo is None):
            raise ValueError("moderator-approved review metadata required")
        context = _review_context(session, bundle, old["public_source_listing_id"], incoming=False)
        original_context, category_history = _review_category_context(
            review, old, row, context,
            _review_context(session, bundle, old["public_source_listing_id"], incoming=True))
        binding = {"public_offer_event_id": identity, **original_context, "quote": _review_quote(old),
                   "observations": _review_observations(old["raw_evidence"] or {})}
        if review.get("binding") != binding:
            raise ValueError("original historical offer/source/spec binding changed")
        quote = binding["quote"]
        if (quote["price_state"] != "sale_price_only" or quote["original_price"] is not None
                or isinstance(quote["price"], bool) or not quote["price"] or quote["price"] <= 0):
            raise ValueError("supported positive source quote required")
        before_terms, expected_terms = _review_terms(
            review, binding, old["raw_evidence"],
            session.get(NormalizedProductVariant, context["public_variant_id"]).attributes)
        before = {"promotion_type": "unknown", "offer_state": "pending_review", "promotion_conditions": before_terms}
        conditional = review["family"] in {"conditional_selection_observation", "conditional_program_observation",
                                           "conditional_basket_spend_observation",
                                           "observed_source_quote_purchase_conditions_unverified",
                                           "native_source_quote_purchase_conditions_unverified"}
        reviewed_promotion = "unknown" if conditional else "final_price"
        after = review.get("interpretation")
        if not isinstance(after, dict) or set(after) != {"promotion_type", "offer_state", "promotion_conditions"}:
            raise ValueError("supported active interpretation required")
        terms = after["promotion_conditions"]
        if not isinstance(terms, dict):
            raise ValueError("reviewed terms must be an object")
        unknown = {key: terms[key] for key in ("membership_required", "coupon_required") if key in terms}
        if (any(value is not None for value in unknown.values())
                # JSON booleans, integers and floats are distinct source facts.
                # Python equality alone would accept True as 1 or 2.0 as 2.
                or _review_digest({key: value for key, value in terms.items() if key not in unknown}) != _review_digest(expected_terms)
                or ("minimum_quantity" in terms and type(terms["minimum_quantity"]) is not int)
                or after["promotion_type"] != reviewed_promotion or after["offer_state"] != "active"
                or _review_digest(review.get("before")) != _review_digest(before)):
            raise ValueError("review cannot invent promotion, discount or eligibility")
        for candidate in (old, row):
            if candidate is None:
                continue
            if not isinstance(candidate.get("raw_evidence") or {}, dict):
                raise ValueError("original evidence must be an object")
            state = {"promotion_type": candidate.get("promotion_type"), "offer_state": candidate.get("offer_state"),
                     "promotion_conditions": (candidate.get("raw_evidence") or {}).get("promotion_conditions", {})}
            state_digest = _review_digest(state)
            if (state_digest not in (_review_digest(before), _review_digest(after))
                    or (candidate is old and old_review is None and state_digest != _review_digest(before))
                    or _review_quote(candidate) != quote
                    or ("promotion_conditions" in candidate
                        and _review_digest(candidate["promotion_conditions"]) != _review_digest(state["promotion_conditions"]))
                    or candidate.get("public_source_listing_id") != binding["public_source_listing_id"]
                    or _review_observations(candidate.get("raw_evidence") or {}) != binding["observations"]):
                raise ValueError("changed historical source/price/interpretation; new event/review required")
        current = deepcopy(row or {**old, "valid_from": quote["valid_from"], "valid_to": quote["valid_to"],
                                   "crawled_at": quote["crawled_at"]})
        current.update(promotion_type=reviewed_promotion, offer_state="active", discount_rate=None)
        current.setdefault("raw_evidence", {})["promotion_conditions"] = deepcopy(terms)
        current.setdefault("audit_provenance", {})["offer_interpretation_review"] = deepcopy(review)
        if category_history:
            current["audit_provenance"]["offer_category_context_history"] = deepcopy(category_history)
        # A conditional source quote is historical money, not confirmed
        # payment, program eligibility or a same-SKU paid/free transaction.
        measure = None if conditional else package_pricing_measure({**context["variant_spec"], "attributes":
                                          session.get(NormalizedProductVariant, context["public_variant_id"]).attributes or {}})
        rate = round(quote["price"] / measure[0] * 100, 4) if measure else None
        current["standard_unit_price"] = rate
        current["price_per_100g"] = rate if measure and measure[1] == "g" else None
        if row is not None:
            effective[identity] = current
        visible.add(context["public_product_id"])
    return effective, visible


def _merge_offer_evidence(old: dict, old_audit: dict, new: dict, new_audit: dict) -> tuple[dict, dict]:
    evidence = {**old, **new}
    audit = {**old_audit, **new_audit}
    if "observations" in old or "observations" in new:
        observations = {}
        for row in [*old.get("observations", []), *new.get("observations", [])]:
            key = row.get("raw_record_id")
            if not key:
                raise ValueError("Offer observation is missing raw_record_id")
            if key in observations and observations[key] != row:
                raise ValueError(f"Conflicting raw evidence for {key}")
            observations[key] = row
        evidence["observations"] = [observations[key] for key in sorted(observations)]
        audit["observation_count"] = len(observations)
    for field in ("raw_record_ids", "source_ingestion_ids"):
        if field in old_audit or field in new_audit:
            audit[field] = sorted(set(old_audit.get(field, [])) | set(new_audit.get(field, [])))
    return evidence, audit


def _validate_observation_accounting(bundle: dict, errors: list[str]) -> None:
    """Initial rebuild manifests account for every original ingestion row."""
    manifest = bundle.get("source_manifest")
    if manifest is None:
        return  # Older catalog-v2 bundles have no raw-row manifest.
    try:
        expected = set()
        for ingestion in manifest["source_ingestions"]:
            count = ingestion["items_count"]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("invalid items_count")
            expected.update(f"ingestion:{int(ingestion['id'])}:{index}" for index in range(count))
        if len(expected) != manifest["observation_count"]:
            raise ValueError("manifest observation_count mismatch")
        seen = set()
        unresolved = {row["raw_record_id"] for row in bundle["unresolved"]}
        offers = {row["public_offer_event_id"]: row for row in bundle["offers"]}
        for row in bundle["observation_accounting"]:
            raw_id = row["raw_record_id"]
            if raw_id in seen:
                raise ValueError(f"duplicate accounting: {raw_id}")
            seen.add(raw_id)
            if row["status"] == "unresolved":
                if raw_id not in unresolved:
                    raise ValueError(f"unresolved evidence missing: {raw_id}")
            elif row["status"] == "included":
                offer = offers[row["public_offer_event_id"]]
                if not any(item.get("raw_record_id") == raw_id for item in offer.get("raw_evidence", {}).get("observations", [])):
                    raise ValueError(f"included raw evidence missing: {raw_id}")
            else:
                raise ValueError(f"unknown accounting status: {row['status']}")
        if seen != expected:
            raise ValueError(f"missing={len(expected - seen)}, unexpected={len(seen - expected)}")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"원본 행 누락/회계 오류: {exc}")


def _upsert(session: Session, model, primary_key: str):
    obj = session.get(model, primary_key)
    if obj is None:
        pk_name = list(model.__table__.primary_key.columns)[0].name
        obj = model(**{pk_name: primary_key})
        session.add(obj)
    return obj


def _unique_rows(rows: list[dict[str, Any]], key: str, label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        value = _text(row.get(key))
        if not value:
            errors.append(f"{label}[{index}].{key}가 필요합니다")
        elif value in result:
            errors.append(f"{label} 중복 {key}: {value!r}")
        else:
            result[value] = row
    return result


def _category_levels(parent_map: dict[str, str | None], errors: list[str]) -> dict[str, int]:
    levels: dict[str, int] = {}
    visiting: set[str] = set()
    def visit(node: str) -> int:
        if node in levels:
            return levels[node]
        if node in visiting:
            errors.append(f"카테고리 순환이 발견되었습니다: {node!r}")
            return MAX_CATEGORY_LEVEL + 1
        visiting.add(node)
        parent = parent_map.get(node)
        if parent and parent not in parent_map:
            errors.append(f"카테고리 {node!r}의 부모 {parent!r}가 없습니다")
            level = MAX_CATEGORY_LEVEL + 1
        else:
            level = 0 if not parent else visit(parent) + 1
        visiting.discard(node)
        levels[node] = level
        return level
    for node in parent_map:
        visit(node)
    return levels


def _confidence(value: Any, label: str, errors: list[str]) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label}.confidence가 숫자가 아닙니다")
        return 0.0
    if not 0.0 <= number <= 1.0:
        errors.append(f"{label}.confidence는 0..1 범위여야 합니다")
    return number


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
