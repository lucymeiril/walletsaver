"""Validated, idempotent import for the capstone normalized catalog bundle."""
from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.promotion_semantics import PriceState, PromotionPriceFacts, PromotionType
from core.match_key import normalize_pack_identity
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
    "g", "kg", "mg", "ml", "l", "cc", "그램", "킬로그램", "리터", "밀리리터", "미리리터",
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

    existing_product_ids = set(session.execute(select(NormalizedCanonicalProduct.public_product_id)).scalars())
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
        confidence = _confidence(row.get("classification_confidence", 1.0), f"products[{product_id}]", errors)
        if confidence < LOW_CONFIDENCE:
            review_low += 1
            if row.get("review_status") != "approved":
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
        try:
            count = row.get("bundle_count", 1)
            if isinstance(count, bool) or float(count) != int(count) or int(count) < 1:
                raise ValueError
            count = int(count)
        except (TypeError, ValueError, OverflowError):
            errors.append(f"variants[{variant_id}].bundle_count는 1 이상의 정수여야 합니다")
            continue
        quantity, unit = row.get("package_quantity"), _text(row.get("package_unit"))
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
            signature = (product_id, quantity, unit, count)
            previous = variant_signatures.get(signature)
            if previous:
                errors.append(f"variants[{variant_id}]는 {previous!r}와 같은 상품군/규격의 중복 variant입니다")
            variant_signatures[signature] = variant_id

    all_variant_ids = existing_variant_ids | set(variants)
    source_keys: dict[tuple[str, str], str] = {}
    for listing_id, row in listings.items():
        if _text(row.get("public_variant_id")) not in all_variant_ids:
            errors.append(f"source_listings[{listing_id}]의 variant 참조가 없습니다")
        if _text(row.get("source_name")) not in {"emart", "homeplus", "lottemart", "costco"}:
            errors.append(f"source_listings[{listing_id}].source_name은 4개 마트 중 하나여야 합니다")
        if not _text(row.get("source_title")):
            errors.append(f"source_listings[{listing_id}].source_title이 필요합니다")
        source_key = _text(row.get("source_record_key"))
        if source_key:
            key = (_text(row.get("source_name")), source_key)
            if key in source_keys:
                errors.append(f"source_listings[{listing_id}] 중복 마트 원본 ID {key!r}")
            source_keys[key] = listing_id

    all_listing_ids = existing_listing_ids | set(listings)
    ambiguous_promotions = 0
    for offer_id, row in offers.items():
        if _text(row.get("public_source_listing_id")) not in all_listing_ids:
            errors.append(f"offers[{offer_id}]의 listing 참조가 없습니다")
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
        if variant_id and variant_id not in all_variant_ids:
            errors.append(f"match_rules[{index}]의 normalized variant 참조가 없습니다")
        elif variant_id and variant_products.get(variant_id) != _text(row.get("public_product_id")):
            errors.append(f"match_rules[{index}]의 variant가 지정한 상품군에 속하지 않습니다")
        confidence = _confidence(row.get("confidence", 1.0), f"match_rules[{index}]", errors)
        if confidence < LOW_CONFIDENCE:
            errors.append(f"match_rules[{index}]는 confidence 0.80 미만이라 자동 hit 규칙으로 적용할 수 없습니다")

    unresolved = len(bundle["unresolved"])
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
        confidence = float(row.get("classification_confidence", 1.0))
        attributes = dict(row.get("attributes") or {})
        attributes.update({
            "classification_confidence": confidence,
            "classification_warning": confidence < LOW_CONFIDENCE,
            "review_status": row.get("review_status") or "auto",
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

    for row in bundle["source_listings"]:
        obj = _upsert(session, NormalizedSourceListing, row["public_source_listing_id"])
        for key in ("public_variant_id", "source_name", "source_record_key", "source_title", "source_url", "image_url", "source_unit_text", "is_active"):
            if key in row:
                setattr(obj, key, row[key])
        obj.projection_version = SCHEMA_VERSION
        applied["source_listings"] += 1
    session.flush()

    for row in bundle["offers"]:
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

    session.add(CatalogSyncLog(
        operation="apply_v2", entities=list(ENTITY_KEYS), mode="upsert",
        scope={"run_id": bundle.get("run_id")}, counts=applied,
        file_hash=file_hash, user=user, dry_run=False, ok=True,
    ))
    session.flush()
    return {**validation.as_dict(), "applied": applied, "idempotent": False}


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
