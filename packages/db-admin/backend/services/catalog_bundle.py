"""Validated, idempotent import for the capstone normalized catalog bundle."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.promotion_semantics import PriceState, PromotionPriceFacts, PromotionType
from storage.models import (
    CatalogSyncLog,
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
    for variant_id, row in variants.items():
        if _text(row.get("public_product_id")) not in all_product_ids:
            errors.append(f"variants[{variant_id}]의 product 참조가 없습니다")
        if int(row.get("bundle_count") or 1) < 1:
            errors.append(f"variants[{variant_id}].bundle_count는 1 이상이어야 합니다")

    all_variant_ids = existing_variant_ids | set(variants)
    for listing_id, row in listings.items():
        if _text(row.get("public_variant_id")) not in all_variant_ids:
            errors.append(f"source_listings[{listing_id}]의 variant 참조가 없습니다")
        if _text(row.get("source_name")) not in {"emart", "homeplus", "lottemart", "costco"}:
            errors.append(f"source_listings[{listing_id}].source_name은 4개 마트 중 하나여야 합니다")
        if not _text(row.get("source_title")):
            errors.append(f"source_listings[{listing_id}].source_title이 필요합니다")

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
        if _text(row.get("unified_category_id")) not in parent_map:
            errors.append(f"mart_category_mappings[{index}]의 통합 카테고리가 없습니다")
        _confidence(row.get("confidence", 1.0), f"mart_category_mappings[{index}]", errors)

    all_product_ids |= set(products)
    all_variant_ids |= set(variants)
    for index, row in enumerate(bundle["match_rules"]):
        if not _text(row.get("match_key")):
            errors.append(f"match_rules[{index}].match_key가 필요합니다")
        if _text(row.get("public_product_id")) not in all_product_ids:
            errors.append(f"match_rules[{index}]의 normalized product 참조가 없습니다")
        variant_id = _optional_text(row.get("public_variant_id"))
        if variant_id and variant_id not in all_variant_ids:
            errors.append(f"match_rules[{index}]의 normalized variant 참조가 없습니다")
        confidence = _confidence(row.get("confidence", 1.0), f"match_rules[{index}]", errors)
        if confidence < LOW_CONFIDENCE:
            errors.append(f"match_rules[{index}]는 confidence 0.80 미만이라 자동 hit 규칙으로 적용할 수 없습니다")

    unresolved = len(bundle["unresolved"])
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
        for key in ("event_name", "standard_unit_price", "price_per_100g", "raw_record_id", "raw_evidence", "audit_provenance", "offer_state"):
            if key in row:
                setattr(obj, key, row[key])
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
        return value.replace(tzinfo=None) if value.tzinfo else value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
