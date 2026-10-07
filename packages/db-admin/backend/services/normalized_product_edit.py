"""Audited display metadata editing; source identity and observations stay immutable."""
from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select

from core.catalog_identity import attributes_of, validated_group_members
from core.reviewed_source_evidence import package_comparison_reason, valid_source_component_variant
from services.audit import log_action
from storage.models import (Keyword, MatchingEntry, NormalizedCanonicalProduct,
                            NormalizedProductVariant, NormalizedSourceListing, UnifiedCategory)

EDITABLE_FIELDS = ("display_name", "display_brand", "unified_category_id", "aliases",
                   "keyword_ids", "primary_image_url", "is_active")


def _row(obj):
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def _product(session, product_id):
    product = session.get(NormalizedCanonicalProduct, product_id)
    if product is None:
        raise HTTPException(404, "Normalized product not found")
    return product


def _display_members(session, product):
    cache = {product.public_product_id: product}

    def lookup(product_id):
        if product_id not in cache:
            cache[product_id] = session.get(NormalizedCanonicalProduct, product_id)
        return _row(cache[product_id]) if cache[product_id] is not None else None

    ids = validated_group_members(_row(product), lookup)
    return [cache[product_id] for product_id in ids]


def display_metadata(session, product):
    members = _display_members(session, product)
    ids = [member.public_product_id for member in members]
    group = attributes_of(_row(product)).get("catalog_group") if len(ids) > 1 else None
    override = (product.attributes or {}).get("admin_display_override")
    valid = (isinstance(override, Mapping) and override.get("version") == 1
             and override.get("member_product_ids") == ids
             and override.get("group_key") == (group.get("key") if group else None)
             and isinstance(override.get("display_name"), str) and override["display_name"].strip()
             and (override.get("display_brand") is None or isinstance(override["display_brand"], str))
             and all((member.attributes or {}).get("admin_display_override") == override for member in members))
    return {"display_name": override["display_name"] if valid else (group["canonical_name"] if group else product.canonical_name),
            "display_brand": override["display_brand"] if valid else (group.get("brand") if group else product.brand),
            "display_scope": "reviewed_group" if group else "selected_product",
            "display_member_ids": ids,
            "metadata_scope": "selected_product",
            "metadata_editable": True, "editable_fields": list(EDITABLE_FIELDS)}


def _leaf_ancestry(session, category_id):
    node = session.get(UnifiedCategory, category_id)
    if node is None:
        raise HTTPException(422, "Unknown unified_category_id")
    if session.scalar(select(UnifiedCategory.id).where(UnifiedCategory.parent_id == category_id).limit(1)):
        raise HTTPException(422, "unified_category_id must reference a leaf")
    chain = []
    while node is not None:
        if node.id in {item.id for item in chain} or len(chain) >= 4:
            raise HTTPException(422, "Invalid unified category ancestry")
        chain.append(node)
        if node.parent_id is None:
            break
        node = session.get(UnifiedCategory, node.parent_id)
        if node is None:
            raise HTTPException(422, "Missing unified category ancestor")
    if any(item.level != level for level, item in enumerate(reversed(chain))):
        raise HTTPException(422, "Invalid unified category level")
    return {item.id for item in chain}


def normalized_product_detail(session, product_id):
    product = _product(session, product_id)
    result = {**_row(product), **display_metadata(session, product)}
    result["source_scope"] = "admin_normalized_catalog"
    keywords = list(session.scalars(select(Keyword).where(Keyword.word.in_(product.keywords or [])).order_by(Keyword.id)))
    result["keyword_ids"] = [keyword.id for keyword in keywords]
    result["keyword_associations"] = [{"id": keyword.id, "word": keyword.word,
        "unified_category_id": keyword.unified_category_id, "is_active": keyword.is_active} for keyword in keywords]
    category = session.get(UnifiedCategory, product.unified_category_id) if product.unified_category_id else None
    result["category_name"] = category.name_ko if category else None
    variants = []
    for variant in session.scalars(select(NormalizedProductVariant).where(
            NormalizedProductVariant.public_product_id == product_id).order_by(NormalizedProductVariant.public_variant_id)):
        data = _row(variant)
        validation = {**data, "unified_category_id": product.unified_category_id}
        data["quantity_comparison_reason"] = package_comparison_reason(validation)
        data["quantity_components"] = ((variant.attributes or {})["source_component_listing"]["components"]
            if valid_source_component_variant(validation) else None)
        data["source_listings"] = [_row(listing) for listing in session.scalars(select(NormalizedSourceListing).where(
            NormalizedSourceListing.public_variant_id == variant.public_variant_id).order_by(NormalizedSourceListing.public_source_listing_id))]
        variants.append(data)
    result["variants"] = variants
    return result


def update_normalized_product(session, product_id, changes, *, identity, request=None):
    product = _product(session, product_id)
    members = _display_members(session, product)
    previous = normalized_product_detail(session, product_id)
    old = {field: previous.get(field) for field in EDITABLE_FIELDS}
    category_id = changes.get("unified_category_id", product.unified_category_id)
    if "unified_category_id" in changes and len(members) > 1 and category_id != product.unified_category_id:
        raise HTTPException(409, "Reviewed group category changes require /api/catalog-bundles")
    ancestry = _leaf_ancestry(session, category_id) if ("unified_category_id" in changes or "keyword_ids" in changes) else None
    selected_keywords = None
    if "keyword_ids" in changes:
        selected_keywords = list(session.scalars(select(Keyword).where(Keyword.id.in_(changes["keyword_ids"]))))
        if (len(selected_keywords) != len(changes["keyword_ids"]) or any(
                not keyword.is_active or keyword.unified_category_id not in ancestry for keyword in selected_keywords)):
            raise HTTPException(422, "keyword_ids must reference active keywords scoped to the selected leaf or ancestors")
    elif "unified_category_id" in changes and category_id != product.unified_category_id:
        # A category edit cannot carry an old dictionary association into an unrelated namespace.
        existing = list(session.scalars(select(Keyword).where(Keyword.word.in_(product.keywords or []))))
        if any(not keyword.is_active or keyword.unified_category_id not in ancestry for keyword in existing):
            raise HTTPException(422, "Select compatible keyword_ids when changing category")

    if "display_name" in changes or "display_brand" in changes:
        current = display_metadata(session, product)
        group = attributes_of(_row(product)).get("catalog_group") if len(members) > 1 else None
        override = {"version": 1, "display_name": changes.get("display_name", current["display_name"]),
                    "display_brand": changes.get("display_brand", current["display_brand"]),
                    "member_product_ids": current["display_member_ids"], "group_key": group.get("key") if group else None}
        for member in members:
            member.attributes = {**(member.attributes or {}), "admin_display_override": override}
    for field in ("unified_category_id", "aliases", "primary_image_url", "is_active"):
        if field in changes:
            setattr(product, field, changes[field])
    if selected_keywords is not None:
        product.keywords = sorted(keyword.word for keyword in selected_keywords)
        product.attributes = {**(product.attributes or {}), "catalog_keyword_words": []}
        for entry in session.scalars(select(MatchingEntry).where(MatchingEntry.public_product_id == product_id)):
            entry.keyword_ids = sorted(changes["keyword_ids"])
    session.flush()
    result = normalized_product_detail(session, product_id)
    log_action(session, action="update", entity_type="normalized_product_metadata", entity_id=product_id,
               old_value=old, new_value={field: result.get(field) for field in EDITABLE_FIELDS},
               request=request, user_id=str(identity.get("sub") or identity.get("username") or "moderator"),
               metadata={"display_member_ids": result["display_member_ids"], "identity_and_observations_preserved": True})
    return {**result, "snapshot_required": bool(changes)}
