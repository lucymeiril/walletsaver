"""Read-only access to the replaceable public catalog SQLite snapshot."""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import math
import re
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.promotion_semantics import comparable_transaction_or_none, confirmed_price_or_none
from core.reviewed_source_evidence import valid_linear_contents_variant, valid_source_component_variant, package_comparison_reason
from core.catalog_quantity import normalize_catalog_package, canonical_components, package_pricing_measure
from core.catalog_identity import attributes_of, validated_group_members


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BACKEND_ROOT / "storage" / "public_snapshot.sqlite"
_PUBLIC_SNAPSHOT_TABLES = {
    "categories",
    "unified_categories",
    "products",
    "keywords",
    "product_keywords",
    "baseline_prices",
    "discount_history",
    "price_history",
    "mart_category_mappings",
    "normalized_canonical_products",
    "normalized_product_variants",
    "normalized_source_listings",
    "normalized_offer_events",
    "normalized_week_buckets",
    "normalized_offer_week_links",
    "snapshot_meta",
}

# Units whose package quantity already means a count of individually received
# items.  Mass/volume variants keep ``per_item`` as the price per package while
# count variants (for example, 80 capsules) use the full received item count.
_COUNT_QUANTITY_UNITS = {
    "개입", "봉지", "인분", "세트", "마리", "회분", "구", "입", "개",
    "팩", "봉", "병", "캔", "손", "매", "롤", "포", "장", "족", "통",
    "인", "p", "t", "모", "두", "알", "미", "포기", "단", "망", "박스",
    "쌍", "켤레",
}


class CatalogUnavailable(RuntimeError):
    pass


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _homogeneous_contents(variant: dict) -> tuple[list[dict], tuple[float, str] | None]:
    """Validate a measured multiset separately from its whole-vector wrapper."""
    attributes = _json(variant.get("attributes"), {})
    if not isinstance(attributes, dict) or "package_components" not in attributes:
        return [], None
    if (attributes.get("component_basis") != "reviewed_homogeneous_contents"
            or isinstance(variant.get("package_quantity"), bool) or isinstance(variant.get("bundle_count"), bool)
            or variant.get("package_quantity") != 1 or variant.get("package_unit") != "세트"
            or variant.get("bundle_count") != 1):
        return [], None
    try:
        components = canonical_components(attributes["package_components"])
        measure = package_pricing_measure({**variant, "attributes": attributes})
    except (ValueError, TypeError, OverflowError):
        return [], None
    if measure is None or variant.get("standard_unit") != measure[1]:
        return [], None
    return components, measure


def _normalized_offer_sort_key(offer: dict) -> tuple[float, float, str]:
    unit_price = offer.get("per_100g") or offer.get("per_100ml") or offer.get("per_100m") or offer.get("per_item")
    return (
        float(unit_price) if unit_price is not None else float("inf"),
        float(offer.get("comparable_price") or float("inf")),
        str(offer.get("listing_id") or offer.get("source") or "") + ":" + str(offer.get("id") or ""),
    )


def _offer_reference_key(offer: dict) -> tuple[str, str, str]:
    return (str(offer.get("variant_id") or ""), str(offer.get("listing_id") or ""),
            str(offer.get("id") or ""))


def _offer_comparison_group(offer: dict) -> tuple[str, str | None, str]:
    unit = offer.get("quantity_unit")
    if (offer.get("pricing_measure_basis") == "reviewed_homogeneous_contents"
            and offer.get("received_package_count_scope") == "complete_declared_vector"
            and (offer.get("pricing_measure_quantity") or 0) > 0):
        unit = offer.get("pricing_measure_unit")
    for field, dimension, basis in (("per_100g", "g", "100g"),
                                    ("per_100ml", "ml", "100ml"),
                                    ("per_100m", "m", "100m")):
        if unit == dimension and offer.get(field) is not None and offer[field] > 0:
            return basis, basis, "same_measured_unit"
    variant_id = offer.get("variant_id")
    if (variant_id and unit in _COUNT_QUANTITY_UNITS and offer.get("per_item") is not None
            and offer["per_item"] > 0 and (offer.get("total_quantity") or 0) > 0):
        receipt = {field: offer.get(field) for field in (
            "total_quantity", "quantity_unit", "bundle_count", "received_package_count",
            "minimum_quantity", "membership_required", "coupon_required",
            "promotion_condition", "promotion_conditions",
        )}
        digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        basis = f"variant:{variant_id}"
        return f"{basis}:receipt:{digest}", basis, "same_variant_receipt"
    # A positive transaction quote alone does not prove an equal sold amount.
    return f"quote:{variant_id}:{offer.get('listing_id') or offer.get('id')}", None, "source_quote_only"


def rank_normalized_offers(offers: list[dict], *, reference_group: str | None = None) -> list[dict]:
    """Rank inside proven groups; group selection never uses a money amount."""
    if not offers:
        return []
    groups: dict[str, list[dict]] = {}
    metadata: dict[str, tuple[str | None, str]] = {}
    for offer in offers:
        group, basis, scope = _offer_comparison_group(offer)
        groups.setdefault(group, []).append(offer)
        metadata[group] = basis, scope
    if reference_group not in groups:
        reference_group = _offer_comparison_group(min(offers, key=_offer_reference_key))[0]
    ordered_groups = sorted(groups, key=lambda group: (
        group != reference_group, _offer_reference_key(min(groups[group], key=_offer_reference_key))))
    ranked = []
    for group in ordered_groups:
        basis, scope = metadata[group]
        members = sorted(groups[group], key=_offer_reference_key if basis is None else _normalized_offer_sort_key)
        for index, offer in enumerate(members):
            ranked.append({**offer, "comparison_group": group, "comparison_basis": basis,
                           "comparison_scope": scope, "is_reference_group": group == reference_group,
                           "rank_within_group": index + 1 if basis is not None else None})
    return ranked


class PublicCatalogStore:
    MAX_RESULT_LIMIT = 1000

    def __init__(self, path: str | Path | None = None):
        configured = str(path or os.getenv("WALLETSAVIOR_PUBLIC_DB", "")).strip()
        self.path = (Path(configured).expanduser() if configured else _DEFAULT_DB).resolve()

    @contextmanager
    def connection(self):
        if not self.path.is_file():
            raise CatalogUnavailable(f"catalog snapshot not found: {self.path}")
        connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=10
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _table(connection, name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    @classmethod
    def _normalized_schema(cls, connection) -> bool:
        return cls._table(connection, "unified_categories") and cls._table(
            connection, "normalized_canonical_products"
        )

    def health(self) -> dict:
        with self.connection() as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise CatalogUnavailable(f"catalog snapshot quick_check failed: {result}")

            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing = sorted(_PUBLIC_SNAPSHOT_TABLES - tables)
            if missing:
                raise CatalogUnavailable(
                    "catalog snapshot is missing required tables: " + ", ".join(missing)
                )

            meta = connection.execute(
                "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
            ).fetchone()
            if not meta:
                raise CatalogUnavailable("catalog snapshot metadata row is missing")

            return {
                "ok": True,
                "path": str(self.path),
                "revision": meta["revision"],
                "built_at": meta["built_at"],
            }

    def has_normalized_catalog(self) -> bool:
        with self.connection() as connection:
            if not self._table(connection, "normalized_canonical_products"):
                return False
            return bool(connection.execute(
                "SELECT 1 FROM normalized_canonical_products WHERE is_active=1 LIMIT 1"
            ).fetchone())

    def search_normalized_products_page(
        self,
        query: str = "",
        *,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """Search the four-level normalized catalog SSOT."""
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), self.MAX_RESULT_LIMIT))
        with self.connection() as connection:
            clauses = ["p.is_active=1"]
            params: list[object] = []
            categories = self._unified_rows(connection)
            query = str(query or "").strip()
            if query:
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                names = ("LOWER(p.canonical_name) LIKE LOWER(?) ESCAPE '\\' OR "
                         "LOWER(COALESCE(p.brand,'')) LIKE LOWER(?) ESCAPE '\\' OR "
                         "EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(p.aliases) "
                         "THEN CASE WHEN json_type(p.aliases)='array' THEN p.aliases ELSE '[]' END "
                         "ELSE '[]' END) a WHERE a.type='text' AND LOWER(a.value) LIKE LOWER(?) ESCAPE '\\')")
                scope = self._keyword_search_scope(connection, query, categories)
                if scope:
                    # An exact registered concept searches its category scope.
                    # A snack whose title mentions milk is not a milk product.
                    scoped = "p.unified_category_id IN (" + ",".join("?" for _ in scope) + ")"
                    if self._query_names_reviewed_identity(query):
                        # Named brand/group synonyms are not interchangeable
                        # with every product in the keyword's concept category.
                        names = "(" + names + ") AND " + scoped
                        params.extend([f"%{escaped}%"] * 3)
                    else:
                        names = scoped
                    params.extend(sorted(scope))
                else:
                    params.extend([f"%{escaped}%"] * 3)
                clauses.append("(" + names + ")")
            category = str(category or "").strip()
            if category:
                descendants = self._descendants(categories, category)
                clauses.append("p.unified_category_id IN (" + ",".join("?" for _ in descendants) + ")")
                params.extend(sorted(descendants))
            # Resolve reviewed groups before paging, using product metadata only.
            # Events/history are projected only for the selected page.
            rows = connection.execute(
                "SELECT p.public_product_id, p.unified_category_id, p.canonical_name, p.attributes, p.is_active "
                "FROM normalized_canonical_products p WHERE " + " AND ".join(clauses), params,
            ).fetchall()
            cache = {row["public_product_id"]: dict(row) for row in rows}
            representatives = {}
            for row in rows:
                members, canonical = self._catalog_group(connection, dict(row), cache)
                representative = self._product_lookup(connection, canonical, cache)
                review = attributes_of(representative).get("catalog_group")
                name = review["canonical_name"] if len(members) > 1 else representative["canonical_name"]
                representatives[canonical] = (name, members)
            ordered = sorted(representatives, key=lambda key: (representatives[key][0].casefold(), key))
            selected = ordered[(page - 1) * per_page:page * per_page]
            payloads = []
            for key in selected:
                full = connection.execute("SELECT * FROM normalized_canonical_products WHERE public_product_id=?", (key,)).fetchone()
                payloads.append(self._normalized_product(connection, full, include_all=False,
                                                        group_member_ids=representatives[key][1]))
            return payloads, len(ordered)

    @staticmethod
    def _query_names_reviewed_identity(query: str) -> bool:
        from core.catalog_identity import reviewed_registry
        text = unicodedata.normalize("NFKC", query).casefold()
        compact = "".join(text.split())
        registry = reviewed_registry()
        groups = registry.get("groups") if isinstance(registry, Mapping) else None
        if not isinstance(groups, list):
            return False
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            name = group.get("canonical_name")
            if isinstance(name, str) and compact == "".join(unicodedata.normalize("NFKC", name).casefold().split()):
                return True
            brand = group.get("brand")
            if not isinstance(brand, str):
                continue
            brand = unicodedata.normalize("NFKC", brand).strip().casefold()
            if len("".join(brand.split())) < 2:
                continue
            if (re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", text)
                    or re.fullmatch(r"[가-힣]{2,}", brand) and compact.startswith(brand)):
                return True
        return False

    def _keyword_search_scope(self, connection, query, categories) -> set[str]:
        if not self._table(connection, "keywords"):
            return set()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(keywords)")}
        if not {"word", "synonyms", "is_active", "unified_category_id"}.issubset(columns):
            return set()
        known = {row["id"] for row in categories}
        scope = set()
        for row in connection.execute("SELECT word, synonyms, unified_category_id FROM keywords WHERE is_active=1"):
            synonyms = _json(row["synonyms"], [])
            # Older JSON columns sometimes contain a JSON-encoded array string.
            # Decode that data layer once; never interpret arbitrary backslashes.
            if isinstance(synonyms, str):
                synonyms = _json(synonyms, [])
            terms = [row["word"]] + (synonyms if isinstance(synonyms, list) else [])
            if row["unified_category_id"] in known and any(
                    isinstance(term, str) and term.strip().casefold() == query.casefold() for term in terms):
                scope.update(self._descendants(categories, row["unified_category_id"]))
        return scope

    @staticmethod
    def _product_lookup(connection, product_id, cache):
        if product_id not in cache:
            row = connection.execute("SELECT * FROM normalized_canonical_products WHERE public_product_id=?", (product_id,)).fetchone()
            cache[product_id] = dict(row) if row else None
        return cache[product_id]

    def _catalog_group(self, connection, product, cache):
        if not isinstance(attributes_of(product).get("catalog_group"), Mapping):
            return (product["public_product_id"],), product["public_product_id"]
        members = validated_group_members(product, lambda key: self._product_lookup(connection, key, cache))
        if len(members) > 1:
            canonical = attributes_of(product)["catalog_group"]["canonical_product_id"]
            if self._product_lookup(connection, canonical, cache).get("is_active"):
                return members, canonical
        return (product["public_product_id"],), product["public_product_id"]

    def get_normalized_product_detail(self, public_product_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM normalized_canonical_products WHERE public_product_id=? AND is_active=1",
                (public_product_id,),
            ).fetchone()
            return self._normalized_product(connection, row, include_all=True) if row else None

    def _normalized_product(self, connection, product_row, *, include_all: bool, group_member_ids=None) -> dict:
        product = dict(product_row)
        members, canonical = self._catalog_group(connection, product, {})
        members = group_member_ids if group_member_ids is not None else members
        attributes = _json(product.get("attributes"), {})
        attributes = attributes if isinstance(attributes, dict) else {}
        group_review = attributes.get("catalog_group") if len(members) > 1 else None
        category = connection.execute(
            "SELECT name_ko FROM unified_categories WHERE id=?",
            (product.get("unified_category_id"),),
        ).fetchone()
        variants_payload: list[dict] = []
        comparable_offers: list[dict] = []
        variants = connection.execute(
            "SELECT * FROM normalized_product_variants WHERE public_product_id IN (" + ",".join("?" for _ in members) + ") AND is_active=1 "
            "ORDER BY public_variant_id",
            tuple(members),
        ).fetchall()
        for variant_row in variants:
            variant = dict(variant_row)
            variant_attributes = _json(variant.get("attributes"), {})
            variant_attributes = variant_attributes if isinstance(variant_attributes, dict) else {}
            quantity_components = []
            if variant_attributes.get("source_component_listing"):
                from core.reviewed_source_evidence import valid_source_component_variant
                if valid_source_component_variant({**variant, "attributes": variant_attributes}):
                    quantity_components = variant_attributes["source_component_listing"]["components"]
            else:
                quantity_components, _ = _homogeneous_contents(variant)
            listings_payload = []
            listings = connection.execute(
                "SELECT * FROM normalized_source_listings WHERE public_variant_id=? AND is_active=1",
                (variant["public_variant_id"],),
            ).fetchall()
            for listing_row in listings:
                listing = dict(listing_row)
                events_payload = []
                events = connection.execute(
                    "SELECT * FROM normalized_offer_events WHERE public_source_listing_id=? "
                    "ORDER BY crawled_at DESC, public_offer_event_id DESC" + ("" if include_all else " LIMIT 1"),
                    (listing["public_source_listing_id"],),
                ).fetchall()
                for event_row in events:
                    event = self._normalized_offer(
                        dict(event_row), variant,
                        category_id=product.get("unified_category_id"), source_listing=listing,
                    )
                    event["variant_id"] = variant["public_variant_id"]
                    event["listing_id"] = listing["public_source_listing_id"]
                    event["is_latest"] = not events_payload
                    event["current_eligible"] = (event["is_latest"] and event["comparable_price"] is not None
                                                 and event["validity_eligible"])
                    events_payload.append(event)
                    # Historical lows belong in history, not today's card.
                    # The newest event may itself be non-comparable; do not
                    # fall back to a prior price in that case.
                    if event["current_eligible"]:
                        comparable_offers.append({**event, "source": listing["source_name"], "source_url": listing.get("source_url"), "variant_id": variant["public_variant_id"]})
                listings_payload.append({
                    "id": listing["public_source_listing_id"],
                    "source": listing["source_name"],
                    "source_record_key": listing.get("source_record_key"),
                    "title": listing["source_title"],
                    "url": listing.get("source_url"),
                    "image_url": listing.get("image_url"),
                    "unit_text": listing.get("source_unit_text"),
                    "offers": events_payload if include_all else events_payload[:1],
                })
            variants_payload.append({
                "id": variant["public_variant_id"],
                "name": variant["variant_name"],
                "package_quantity": variant.get("package_quantity"),
                "package_unit": variant.get("package_unit"),
                "bundle_count": variant.get("bundle_count"),
                "display_unit": variant.get("display_unit"),
                "quantity_components": quantity_components,
                "listings": listings_payload,
            })
        comparable_offers = rank_normalized_offers(comparable_offers)
        best = comparable_offers[0] if comparable_offers else {}
        best_variant = next((variant for variant in variants_payload if variant["id"] == best.get("variant_id")), None)
        best_unit = ""
        if best_variant is not None:
            best_unit = best_variant.get("display_unit") or ""
            if not best_unit and best_variant.get("package_quantity") and best_variant.get("package_unit"):
                best_unit = f"{best_variant['package_quantity']:g}{best_variant['package_unit']}"
                if best_variant["bundle_count"] is not None and best_variant["bundle_count"] > 1:
                    best_unit += f"×{best_variant['bundle_count']}"
        warning = bool(attributes.get("classification_warning"))
        return {
            "id": product["public_product_id"],
            "public_product_id": product["public_product_id"],
            "canonical_public_product_id": canonical,
            "group_member_product_ids": list(members),
            "name": group_review["canonical_name"] if group_review else product["canonical_name"],
            "brand": (group_review.get("brand") or "") if group_review else (product.get("brand") or ""),
            "category_id": product.get("unified_category_id") or "",
            "cat": str(category["name_ko"] if category else ""),
            "img": product.get("primary_image_url") or "",
            "image_url": product.get("primary_image_url") or "",
            "cur": best.get("comparable_price"),
            "price": best.get("comparable_price"),
            "observed_at": max((str(listing["offers"][0].get("crawled_at") or "")
                                for variant in variants_payload for listing in variant["listings"]
                                if listing["offers"]), default=""),
            "source": best.get("source") or "",
            "source_url": best.get("source_url") or "",
            "unit": best_unit,
            "classification_warning": warning,
            "classification_label": "분류 확인 필요" if warning else None,
            "attributes": attributes,
            "variants": variants_payload if include_all else variants_payload[:3],
            "best_offer": best or None,
            "comparison_reference": {
                "group": best.get("comparison_group"), "basis": best.get("comparison_basis"),
                "scope": best.get("comparison_scope"),
                "selection_method": "stable_identity_group_then_within_group_price",
                "comparable_count": sum(offer["comparison_group"] == best["comparison_group"]
                                        for offer in comparable_offers),
            } if best else None,
        }

    @staticmethod
    def _offer_validity(event: dict, *, reference_time: datetime | None = None) -> tuple[bool, str | None]:
        now = (reference_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        for key in ("valid_from", "valid_to"):
            raw = event.get(key)
            if raw in (None, ""):
                continue
            try:
                value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return False, "validity_unconfirmed"
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            # A source date without a time denotes the whole calendar day.
            if len(str(raw)) == 10:
                outside = now.date() < value.date() if key == "valid_from" else now.date() > value.date()
            else:
                outside = now < value if key == "valid_from" else now > value
            if outside:
                return False, "not_yet_valid" if key == "valid_from" else "expired"
        return True, None

    @staticmethod
    def _normalized_offer(event: dict, variant: dict, *, category_id: str | None = None,
                          source_listing: dict | None = None) -> dict:
        price = confirmed_price_or_none(event.get("price"))
        evidence = _json(event.get("raw_evidence"), {})
        conditions = evidence.get("promotion_conditions") if isinstance(evidence.get("promotion_conditions"), dict) else evidence
        transaction = comparable_transaction_or_none(
            current_price=price,
            promotion_type=event.get("promotion_type"),
            promotion_conditions=conditions,
        ) if (event.get("price_state") in {"normal", "sale_price_only"}
              and event.get("offer_state", "active") == "active") else None
        # A quote collected after a purchase-count rule expired does not prove
        # the promotional spend or received amount, even as a historical receipt.
        # Preserve the quote, rule and immutable event; hold only their derived
        # transaction. Today's expiry alone does not invalidate an observation
        # that was actually made within the source period.
        receipt_eligible = None
        receipt_reason = None
        count_rule = (event.get("promotion_type") == "buy_x_get_y"
                      or (type(conditions.get("minimum_quantity")) is int
                          and conditions["minimum_quantity"] > 1))
        if count_rule and any(event.get(key) not in (None, "") for key in ("valid_from", "valid_to")):
            try:
                observed_raw = str(event.get("crawled_at") or "")
                observed = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                # A date-only observation cannot establish a time within a
                # partly valid day; do not silently assign it midnight.
                if len(observed_raw) == 10 and any(
                    value not in (None, "") and len(str(value)) != 10
                    for value in (event.get("valid_from"), event.get("valid_to"))
                ):
                    raise ValueError("observation time unconfirmed")
                receipt_eligible, observation_reason = PublicCatalogStore._offer_validity(
                    event, reference_time=observed)
                if not receipt_eligible:
                    receipt_reason = ("promotion_observation_outside_period"
                                      if observation_reason in {"expired", "not_yet_valid"}
                                      else "promotion_observation_validity_unconfirmed")
            except (TypeError, ValueError, OverflowError):
                receipt_eligible = False
                receipt_reason = "promotion_observation_validity_unconfirmed"
            if not receipt_eligible:
                transaction = None
        purpose_reason = None
        if isinstance(category_id, str) and category_id.startswith("services.facility."):
            listing = source_listing or {}
            attributes = _json(variant.get("attributes"), {})
            package = {**variant, "attributes": attributes if isinstance(attributes, dict) else {},
                       "source": listing.get("source_name"),
                       "source_record_key": listing.get("source_record_key"),
                       "source_url": listing.get("source_url")}
            _, purpose_issues = normalize_catalog_package(
                package, package["attributes"],
                listing.get("source_title") or variant.get("variant_name") or "",
                category_id=category_id,
            )
            if "unit_service_occupancy_not_entitlement" in purpose_issues:
                purpose_reason = "unit_service_occupancy_not_entitlement"
        comparable = float(transaction[0]) if transaction and not purpose_reason else None
        received_packages = int(transaction[1]) if transaction else 1
        quantity = float(variant["package_quantity"]) if variant.get("package_quantity") is not None else None
        quantity = quantity if quantity is not None and quantity > 0 else None
        bundle = int(variant["bundle_count"]) if variant.get("bundle_count") is not None else None
        bundle = bundle if bundle is not None and bundle > 0 else None
        total_quantity = quantity * bundle * received_packages if transaction and quantity and bundle and not purpose_reason else None
        attributes = _json(variant.get("attributes"), {})
        attributes = attributes if isinstance(attributes, dict) else {}
        declared_vector = valid_source_component_variant({**variant, "attributes": attributes})
        homogeneous_components, homogeneous_measure = _homogeneous_contents(variant)
        homogeneous_vector = bool(homogeneous_components)
        components_payload = (attributes["source_component_listing"]["components"]
                              if declared_vector else homogeneous_components)
        composition_reason = package_comparison_reason({
            **variant, 'attributes': attributes})
        if "package_components" in attributes and not homogeneous_vector:
            composition_reason = "quantity_evidence_unverified"
        unit = str(variant.get("package_unit") or "").strip().lower()
        linear_contents = unit == "m" and valid_linear_contents_variant({
            **variant, "attributes": _json(variant.get("attributes"), {})})
        per_100 = (round(comparable / total_quantity * 100)
                   if comparable is not None and total_quantity
                   and not composition_reason
                   and (unit in {"g", "ml"} or linear_contents) else None)
        pricing_quantity = (homogeneous_measure[0] * received_packages
                            if homogeneous_measure and transaction and not purpose_reason else None)
        if linear_contents:
            pricing_quantity = total_quantity
        if pricing_quantity is not None and not math.isfinite(pricing_quantity):
            pricing_quantity = None
        pricing_unit = ("m" if linear_contents else homogeneous_measure[1]) if pricing_quantity is not None else None
        if pricing_quantity and pricing_unit in {"g", "ml"} and comparable is not None:
            per_100 = round(comparable / pricing_quantity * 100)
        # Package count is not evidence of the unknown content/sold-piece count.
        # Known count products divide by received pieces. Known g/ml packages
        # retain the established per-package quote; all unknown bases stay NULL.
        per_item_divisor = None
        if total_quantity is not None and not composition_reason:
            if unit in _COUNT_QUANTITY_UNITS:
                per_item_divisor = total_quantity
            elif unit in {"g", "ml"}:
                per_item_divisor = bundle * received_packages
        condition = conditions.get("condition_text") or evidence.get("condition_text") or evidence.get("promotion_condition")
        validity_eligible, availability_reason = PublicCatalogStore._offer_validity(event)
        return {
            "id": event["public_offer_event_id"],
            "price_state": event.get("price_state"),
            "offer_state": event.get("offer_state"),
            "promotion_type": event.get("promotion_type"),
            "observation_receipt_eligible": receipt_eligible,
            "observation_receipt_reason": receipt_reason,
            "listed_price": price,
            "total_price": float(transaction[0]) if transaction else None,
            "comparable_price": comparable,
            "original_price": event.get("original_price"),
            "discount_rate": event.get("discount_rate"),
            "total_quantity": total_quantity,
            "quantity_unit": (unit or None) if not purpose_reason else None,
            "bundle_count": bundle if not purpose_reason else None,
            "per_item": round(comparable / per_item_divisor) if comparable is not None and per_item_divisor else None,
            "per_100g": per_100 if (pricing_unit or unit) == "g" else None,
            "per_100ml": per_100 if (pricing_unit or unit) == "ml" else None,
            "per_100m": per_100 if linear_contents else None,
            "pricing_measure_quantity": pricing_quantity,
            "pricing_measure_unit": pricing_unit,
            "pricing_measure_basis": (("reviewed_declared_linear_contents" if linear_contents else
                                       "reviewed_homogeneous_contents") if pricing_quantity is not None else None),
            "quantity_components": components_payload,
            "promotion_condition": condition,
            "promotion_conditions": conditions if isinstance(evidence.get("promotion_conditions"), dict) else {
                key: conditions[key] for key in (
                    "condition_text", "minimum_quantity", "buy_quantity", "free_quantity",
                    "membership_required", "coupon_required", "coupon_text", "membership_text",
                ) if key in conditions
            },
            "minimum_quantity": conditions.get("minimum_quantity", evidence.get("minimum_quantity")),
            "received_package_count": received_packages if transaction and not purpose_reason else None,
            # This integer repeats the whole declared contents vector. It does
            # not establish the number of physical containers or pieces.
            "received_package_count_scope": ("declared_linear_package_repetitions" if linear_contents else
                                             "complete_declared_vector" if declared_vector or homogeneous_vector else None),
            "quantity_basis": ("reviewed_declared_linear_contents" if linear_contents else
                               "reviewed_homogeneous_contents" if homogeneous_vector else
                               attributes.get("quantity_basis") if declared_vector else None),
            "scalar_basis": ("declared_linear_contents_not_physical_dimensions" if linear_contents else
                             "one_complete_declared_vector_not_piece_count" if homogeneous_vector else
                             attributes.get("scalar_basis") if declared_vector else None),
            "quantity_purpose_reason": purpose_reason,
            "quantity_comparison_reason": composition_reason,
            "membership_required": conditions.get("membership_required", evidence.get("membership_required")),
            "coupon_required": conditions.get("coupon_required", evidence.get("coupon_required")),
            "event_name": event.get("event_name"),
            "crawled_at": event.get("crawled_at"),
            "valid_from": event.get("valid_from"), "valid_to": event.get("valid_to"),
            "validity_eligible": validity_eligible, "availability_reason": availability_reason,
        }

    def _category(self, connection, product: dict) -> tuple[str, str, str]:
        unified_id = product.get("unified_category_id")
        if unified_id and self._table(connection, "unified_categories"):
            row = connection.execute(
                "SELECT id, name_ko FROM unified_categories WHERE id=?", (unified_id,)
            ).fetchone()
            if row:
                return str(row["id"]), str(row["name_ko"] or ""), ""
        category_id = product.get("category_id")
        if category_id:
            row = connection.execute(
                "SELECT id, name, icon FROM categories WHERE id=?", (category_id,)
            ).fetchone()
            if row:
                method = str(product.get("categorization_method") or "").lower()
                if method not in {"suggested", "none"} and str(row["name"] or "").strip() != str(product.get("name") or "").strip():
                    return str(row["id"]), str(row["name"] or ""), str(row["icon"] or "")
        return str(category_id or ""), "", ""

    def _latest(self, connection, table: str, product_id: int, order: str) -> dict:
        if not self._table(connection, table):
            return {}
        row = connection.execute(
            f"SELECT * FROM {table} WHERE product_id=? ORDER BY {order} DESC, id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return dict(row) if row else {}

    def _latest_active_discount(self, connection, product_id: int) -> dict:
        if not self._table(connection, "discount_history"):
            return {}
        today = datetime.utcnow().date().isoformat()
        row = connection.execute(
            "SELECT * FROM discount_history WHERE product_id=? "
            "AND (valid_from IS NULL OR date(valid_from) IS NULL OR date(valid_from) <= date(?)) "
            "AND (valid_to IS NULL OR date(valid_to) IS NULL OR date(valid_to) >= date(?)) "
            "ORDER BY crawled_at DESC, id DESC LIMIT 1",
            (product_id, today, today),
        ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def _is_newer_or_equal(left: dict, left_stamp: str, right: dict, right_stamp: str) -> bool:
        if not left:
            return False
        if not right:
            return True
        return str(left.get(left_stamp) or "") >= str(right.get(right_stamp) or "")

    def _observations(self, connection, product_id: int) -> list[tuple[float, str, str]]:
        rows: list[tuple[float, str, str]] = []
        if self._table(connection, "baseline_prices"):
            for row in connection.execute(
                "SELECT price, source, recorded_at FROM baseline_prices WHERE product_id=?",
                (product_id,),
            ):
                if row["price"] is not None:
                    rows.append((float(row["price"]), str(row["source"] or ""), str(row["recorded_at"] or "")))
        if self._table(connection, "discount_history"):
            for row in connection.execute(
                "SELECT price, source, crawled_at FROM discount_history WHERE product_id=?",
                (product_id,),
            ):
                if row["price"] is not None:
                    rows.append((float(row["price"]), str(row["source"] or ""), str(row["crawled_at"] or "")))
        return rows

    def _stores(self, connection, product_id: int) -> dict[str, float]:
        stores: dict[str, float] = {}
        candidates: list[tuple[str, float, str, int, int]] = []
        if self._table(connection, "discount_history"):
            today = datetime.utcnow().date().isoformat()
            for row in connection.execute(
                "SELECT source, price, crawled_at, id FROM discount_history "
                "WHERE product_id=? "
                "AND (valid_from IS NULL OR date(valid_from) IS NULL OR date(valid_from) <= date(?)) "
                "AND (valid_to IS NULL OR date(valid_to) IS NULL OR date(valid_to) >= date(?))",
                (product_id, today, today),
            ):
                if row["price"] is not None:
                    candidates.append((
                        str(row["source"] or ""),
                        float(row["price"]),
                        str(row["crawled_at"] or ""),
                        1,
                        int(row["id"]),
                    ))
        if self._table(connection, "baseline_prices"):
            for row in connection.execute(
                "SELECT source, price, recorded_at, id FROM baseline_prices WHERE product_id=?",
                (product_id,),
            ):
                if row["price"] is not None:
                    candidates.append((
                        str(row["source"] or ""),
                        float(row["price"]),
                        str(row["recorded_at"] or ""),
                        0,
                        int(row["id"]),
                    ))

        candidates.sort(key=lambda item: (item[2], item[3], item[4]), reverse=True)
        for source, price, _observed_at, _kind, _row_id in candidates:
            source = "lotte" if source == "lottemart" else source
            if source and source not in stores:
                stores[source] = price
        return stores

    def _product(self, connection, row) -> dict:
        product = dict(row)
        product_id = int(product["id"])
        category_id, category_name, icon = self._category(connection, product)
        latest_discount = self._latest(connection, "discount_history", product_id, "crawled_at")
        active_discount = self._latest_active_discount(connection, product_id)
        latest_baseline = self._latest(connection, "baseline_prices", product_id, "recorded_at")
        observations = self._observations(connection, product_id)
        values = [value for value, _, _ in observations]

        use_discount = self._is_newer_or_equal(
            active_discount,
            "crawled_at",
            latest_baseline,
            "recorded_at",
        )
        current_row = active_discount if use_discount else latest_baseline
        current_value = current_row.get("price") if current_row else None
        current = round(float(current_value)) if current_value is not None else 0
        avg = round(sum(values) / len(values)) if values else current
        low = round(min(values)) if values else current
        high = round(max(values)) if values else current
        ratio = current / avg if current and avg else 1
        tier = "ultra" if ratio <= .70 else "great" if ratio <= .85 else "good" if ratio <= 1.05 else "wait"

        latest_discount_raw = _json(latest_discount.get("raw_data"), {}) if latest_discount else {}
        current_discount_raw = _json(active_discount.get("raw_data"), {}) if use_discount else {}
        attrs = _json(product.get("attributes"), {})
        image = product.get("image_url") or latest_discount_raw.get("image_url") or ""
        original = active_discount.get("original_price") if use_discount else None
        discount_pct = (
            round((1 - current / float(original)) * 100)
            if current and original and float(original) > current else 0
        )
        unit_display = (
            attrs.get("unit_price_display") or attrs.get("unit_price_text")
            or product.get("pack_unit") or product.get("unit") or ""
        )
        stores = self._stores(connection, product_id)
        days = {stamp[:10] for _, _, stamp in observations if stamp}
        return {
            "id": product_id,
            "name": product.get("display_name") or product.get("name") or "",
            "icon": icon,
            "cat": category_name,
            "category_id": category_id,
            "unit": product.get("unit") or product.get("pack_unit") or "",
            "unit_price_display": unit_display,
            "display_unit": unit_display,
            "avg": avg, "cur": current, "price": current, "low": low, "high": high,
            "price_tier": tier,
            "img": image, "image_url": image,
            "brand": product.get("brand") or attrs.get("brand") or "",
            "attributes": attrs,
            "source": current_row.get("source") if current_row else None,
            "source_url": active_discount.get("source_url") or current_discount_raw.get("source_url") or "" if use_discount else "",
            "source_title": current_discount_raw.get("source_title") or current_discount_raw.get("product_name") or "" if use_discount else "",
            "original_price": original,
            "discount_pct": discount_pct,
            "discount_rate": active_discount.get("discount_rate") if use_discount else None,
            "stores": stores,
            "stats": {
                "dataDays": len(days), "records": len(values),
                "confidence": [low, high], "outliers": 0,
                "avgDiscount": 0, "discFreq": 0,
            },
        }

    def product_exists(self, product_id) -> bool:
        with self.connection() as connection:
            if self._table(connection, "normalized_canonical_products"):
                normalized = connection.execute(
                    "SELECT 1 FROM normalized_canonical_products WHERE public_product_id=? AND is_active=1",
                    (str(product_id),),
                ).fetchone()
                if normalized:
                    return True
            return connection.execute(
                "SELECT 1 FROM products WHERE id=? AND is_active=1", (product_id,)
            ).fetchone() is not None

    def get_product_detail(self, product_id: int) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)
            ).fetchone()
            return self._product(connection, row) if row else None

    def search_products(self, query: str, category: str | None = None, page: int = 1, per_page: int = 20) -> list[dict]:
        per_page = max(1, min(int(per_page), self.MAX_RESULT_LIMIT))
        query_fold = (query or "").strip().casefold()
        category_fold = (category or "").strip().casefold()
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY name LIMIT ?",
                (self.MAX_RESULT_LIMIT,),
            ).fetchall()
            items = []
            for row in rows:
                item = self._product(connection, row)
                if query_fold and query_fold not in item["name"].casefold():
                    continue
                category_text = f"{item['category_id']} {item['cat']}".casefold()
                if category_fold and category_fold not in category_text:
                    continue
                items.append(item)
        start = (max(1, page) - 1) * per_page
        return items[start:start + per_page]

    def _unified_rows(self, connection) -> list[dict]:
        if not self._table(connection, "unified_categories"):
            return []
        return [dict(row) for row in connection.execute(
            "SELECT id, parent_id, name_ko FROM unified_categories ORDER BY sort_order, name_ko"
        )]

    def _descendants(self, categories: list[dict], category_id: str) -> set[str]:
        children: dict[str | None, list[str]] = {}
        for row in categories:
            children.setdefault(row.get("parent_id"), []).append(row["id"])
        result: set[str] = set()
        def visit(value: str):
            if value in result:
                return
            result.add(value)
            for child in children.get(value, []):
                visit(child)
        visit(category_id)
        return result

    def get_category_tree(self) -> list[dict]:
        with self.connection() as connection:
            categories = self._unified_rows(connection)
            normalized_schema = self._normalized_schema(connection)
            if not normalized_schema:
                categories = [
                    {"id": row["id"], "parent_id": row["parent_id"], "name_ko": row["name"]}
                    for row in connection.execute(
                        "SELECT id, parent_id, name FROM categories ORDER BY sort_order, name"
                    )
                ]
                count_column = "category_id"
                count_table = "products"
                counts = {
                    row[0]: int(row[1])
                    for row in connection.execute(
                        f"SELECT {count_column}, COUNT(*) FROM {count_table} "
                        f"WHERE is_active=1 AND {count_column} IS NOT NULL GROUP BY {count_column}"
                    )
                }
            else:
                counts = self._normalized_category_counts(connection)
            by_id = {
                row["id"]: {
                    "id": row["id"], "name": row["name_ko"] or "",
                    "parent_id": row.get("parent_id"), "count": counts.get(row["id"], 0),
                    "icon": "", "children": [], "examples": [],
                }
                for row in categories
            }
            for node in list(by_id.values()):
                parent = by_id.get(node["parent_id"])
                if parent:
                    parent["children"].append(node)

            def total(node):
                node["count"] += sum(total(child) for child in node["children"])
                node["children"].sort(key=lambda value: (-value["count"], value["name"]))
                return node["count"]

            roots = [node for node in by_id.values() if node["parent_id"] not in by_id]
            for root in roots:
                total(root)
            for node in by_id.values():
                node.pop("parent_id", None)
            return sorted(roots, key=lambda value: (-value["count"], value["name"]))

    def _normalized_category_counts(self, connection, category_ids=None) -> dict[str, int]:
        """Count browse identities without projecting variants or observations."""
        where = "is_active=1 AND unified_category_id IS NOT NULL"
        params = ()
        if category_ids is not None:
            if not category_ids:
                return {}
            params = tuple(sorted(category_ids))
            where += " AND unified_category_id IN (" + ",".join("?" for _ in params) + ")"
        counts = {row[0]: int(row[1]) for row in connection.execute(
            "SELECT unified_category_id, COUNT(*) FROM normalized_canonical_products WHERE "
            + where + " GROUP BY unified_category_id", params,
        )}
        # Only explicit group candidates need metadata. All ordinary products
        # retain their SQL count, and malformed groups remain separate rows.
        candidates = [dict(row) for row in connection.execute(
            "SELECT public_product_id, unified_category_id, attributes, is_active "
            "FROM normalized_canonical_products WHERE " + where +
            " AND CASE WHEN json_valid(attributes) THEN "
            "json_type(attributes,'$.catalog_group')='object' ELSE 0 END", params,
        )]
        cache = {row["public_product_id"]: row for row in candidates}
        counted = set()
        for product in candidates:
            members, canonical = self._catalog_group(connection, product, cache)
            if len(members) < 2 or canonical in counted:
                continue
            counted.add(canonical)
            active_count = sum(bool(self._product_lookup(connection, key, cache).get("is_active"))
                               for key in members)
            counts[product["unified_category_id"]] -= max(0, active_count - 1)
        return counts

    def get_category_children(self, category_id: str) -> tuple[list[dict], int, str]:
        with self.connection() as connection:
            categories = self._unified_rows(connection)
            if not self._normalized_schema(connection):
                return [], 0, category_id
            by_id = {row["id"]: row for row in categories}
            children = [row for row in categories if row.get("parent_id") == category_id]
            all_ids = self._descendants(categories, category_id)
            counts = self._normalized_category_counts(connection, all_ids)
            total = sum(counts.values())

            result = []
            for child in children:
                ids = self._descendants(categories, child["id"])
                count = sum(counts.get(key, 0) for key in ids)
                result.append({"id": child["id"], "name": child["name_ko"], "count": int(count)})
            result.sort(key=lambda value: (-value["count"], value["name"]))

            names, cursor = [], by_id.get(category_id)
            while cursor:
                names.append(cursor["name_ko"])
                cursor = by_id.get(cursor.get("parent_id"))
            return result, int(total), " > ".join(reversed(names)) or category_id

    def get_category_products(self, category_id: str, page: int, per_page: int) -> tuple[list[dict], int]:
        with self.connection() as connection:
            if self._normalized_schema(connection):
                # Use the normalized path even when it is deliberately empty;
                # an empty approved SSOT must not resurrect the 542 legacy nodes.
                pass
            else:
                categories = self._unified_rows(connection)
                if not categories:
                    return self.search_products("", category=category_id, page=page, per_page=per_page), 0
                ids = self._descendants(categories, category_id)
                if not ids:
                    return [], 0
                marks = ",".join("?" for _ in ids)
                total = int(connection.execute(
                    f"SELECT COUNT(*) FROM products WHERE is_active=1 AND unified_category_id IN ({marks})",
                    tuple(ids),
                ).fetchone()[0])
                rows = connection.execute(
                    f"SELECT * FROM products WHERE is_active=1 AND unified_category_id IN ({marks}) "
                    "ORDER BY name LIMIT ? OFFSET ?",
                    (*ids, per_page, (page - 1) * per_page),
                ).fetchall()
                return [self._product(connection, row) for row in rows], total

        return self.search_normalized_products_page(
            "", category=category_id, page=page, per_page=per_page
        )

    def get_price_history(self, product_id: int, days: int = 30) -> list[dict]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        result = []
        with self.connection() as connection:
            if self._table(connection, "baseline_prices"):
                for row in connection.execute(
                    "SELECT price, source, recorded_at FROM baseline_prices "
                    "WHERE product_id=? AND recorded_at>=? ORDER BY recorded_at",
                    (product_id, cutoff),
                ):
                    result.append({
                        "date": str(row["recorded_at"] or "")[:10],
                        "price": round(float(row["price"])),
                        "source": row["source"] or "",
                        "recorded_at": row["recorded_at"] or "",
                        "observed_at": row["recorded_at"] or "",
                    })
            if self._table(connection, "discount_history"):
                for row in connection.execute(
                    "SELECT price, source, crawled_at, source_url FROM discount_history "
                    "WHERE product_id=? AND crawled_at>=? ORDER BY crawled_at",
                    (product_id, cutoff),
                ):
                    result.append({
                        "date": str(row["crawled_at"] or "")[:10],
                        "price": round(float(row["price"])),
                        "source": row["source"] or "",
                        "recorded_at": row["crawled_at"] or "",
                        "observed_at": row["crawled_at"] or "",
                        "source_url": row["source_url"] or "",
                    })
        return sorted(result, key=lambda value: value.get("observed_at") or "")

    def get_price_compare(self, product_id: int) -> list[dict]:
        product = self.get_product_detail(product_id)
        if product is None:
            return []
        avg = product.get("avg") or 0
        rows = []
        for source, price in product.get("stores", {}).items():
            rows.append({
                "source": source, "price": price,
                "reference_price": avg, "historical_average_price": avg,
                "price_vs_reference_rate": round((1 - price / avg) * 100, 1) if avg else None,
                "reference_method": "historical_average",
                "source_url": "", "url": "",
            })
        return sorted(rows, key=lambda value: value["price"])

    def get_mart_deals(self, store: str | None = None, limit: int = 50) -> dict:
        meta = {
            "emart": ("이마트", "#FFD700"), "homeplus": ("홈플러스", "#FF6B35"),
            "lottemart": ("롯데마트", "#E4002B"), "costco": ("코스트코", "#E31837"),
        }
        with self.connection() as connection:
            has_normalized = self._table(connection, "normalized_canonical_products") and bool(
                connection.execute(
                    "SELECT 1 FROM normalized_canonical_products WHERE is_active=1 LIMIT 1"
                ).fetchone()
            )
            if has_normalized:
                return self._get_normalized_mart_deals(
                    connection, meta=meta, store=store, limit=limit
                )
            sql = (
                "SELECT d.*, p.name AS product_name, p.unit AS product_unit "
                "FROM discount_history d "
                "JOIN products p ON p.id=d.product_id AND p.is_active=1 "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM discount_history newer "
                "WHERE newer.product_id=d.product_id AND newer.source=d.source "
                "AND (newer.valid_from IS NULL OR date(newer.valid_from) IS NULL OR date(newer.valid_from) <= date(?)) "
                "AND (newer.valid_to IS NULL OR date(newer.valid_to) IS NULL OR date(newer.valid_to) >= date(?)) "
                "AND (newer.crawled_at > d.crawled_at "
                "OR (newer.crawled_at = d.crawled_at AND newer.id > d.id))"
                ") "
                "AND (d.valid_from IS NULL OR date(d.valid_from) IS NULL OR date(d.valid_from) <= date(?)) "
                "AND (d.valid_to IS NULL OR date(d.valid_to) IS NULL OR date(d.valid_to) >= date(?)) "
            )
            today = datetime.utcnow().date().isoformat()
            params: list[object] = [today, today, today, today]
            if store:
                sql += "AND d.source=? "
                params.append(store)
            sql += "ORDER BY d.crawled_at DESC, d.id DESC LIMIT ?"
            params.append(limit)
            grouped: dict[str, list] = {}
            latest: dict[str, str] = {}
            for row in connection.execute(sql, params):
                raw = _json(row["raw_data"], {})
                published = raw.get("published_item") if isinstance(raw.get("published_item"), dict) else {}
                source = str(row["source"] or "")
                price_observation_only = bool(raw.get("price_observation_only", False))
                grouped.setdefault(source, []).append({
                    "name": row["product_name"] or published.get("name") or raw.get("product_name") or "",
                    "orig": row["original_price"], "sale": row["price"],
                    "disc": round(row["discount_rate"] or 0),
                    "source_url": row["source_url"] or published.get("detail_url") or raw.get("source_url") or "",
                    "image_url": raw.get("image_url") or published.get("image_url") or "",
                    "event_name": published.get("event_name") or raw.get("event_name") or "",
                    "unit": published.get("unit") or raw.get("unit") or row["product_unit"] or "",
                    "display_unit": published.get("display_unit") or raw.get("display_unit") or published.get("unit") or raw.get("unit") or row["product_unit"] or "",
                    "category": published.get("category") or raw.get("category") or "",
                    "valid_from": row["valid_from"] or published.get("valid_from") or raw.get("valid_from") or "",
                    "valid_to": row["valid_to"] or published.get("valid_to") or published.get("valid_until") or raw.get("valid_to") or raw.get("valid_until") or "",
                    "publication_kind": raw.get("publication_kind") or "",
                    "price_observation_only": price_observation_only,
                    "discount_claim_status": raw.get("discount_claim_status") or "",
                    "claim_basis": raw.get("claim_basis") or "",
                    "has_discount_metadata": bool(raw.get("has_discount_metadata", False)),
                    "record_label": raw.get("record_label") or ("관측 가격" if price_observation_only else ""),
                    "claim_status_label": raw.get("claim_status_label") or "",
                    "crawled_at": row["crawled_at"] or "",
                })
                latest.setdefault(source, row["crawled_at"] or "")
            result = {}
            for source, items in grouped.items():
                name, color = meta.get(source, (source, "#666"))
                result[source] = {
                    "name": name, "color": color, "items": items,
                    "last_crawled_at": latest.get(source, ""),
                }
            return result

    def _get_normalized_mart_deals(
        self,
        connection,
        *,
        meta: dict[str, tuple[str, str]],
        store: str | None,
        limit: int,
    ) -> dict:
        """Read the latest safe offer per source listing from the four-stage SSOT."""
        clauses = [
            "p.is_active=1", "v.is_active=1", "l.is_active=1",
            "e.offer_state='active'",
            "e.listing_recency=1",
        ]
        params: list[object] = []
        # Apply validity before LIMIT so expired observations cannot crowd out
        # later valid listings. Minimal legacy fixtures may omit these columns.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(normalized_offer_events)")}
        for key, operator in (("valid_from", "<="), ("valid_to", ">=")):
            if key in columns:
                clauses.append(f"(e.{key} IS NULL OR e.{key}='' OR "
                               f"(CASE WHEN length(e.{key})=10 THEN date(e.{key}) {operator} date('now') "
                               f"ELSE datetime(e.{key}) {operator} datetime('now') END))")
        if store:
            clauses.append("l.source_name=?")
            params.append(store)
        params.append(max(1, min(int(limit), self.MAX_RESULT_LIMIT)))
        # Rank once across every observation state before selecting active rows.
        # A pending/inactive latest observation must suppress an older active
        # offer; a correlated scan per candidate also stalls existing snapshots.
        variant_columns = {row[1] for row in connection.execute("PRAGMA table_info(normalized_product_variants)")}
        variant_attributes = "v.attributes" if "attributes" in variant_columns else "NULL"
        rows = connection.execute(
            "WITH ranked_events AS (SELECT events.*, ROW_NUMBER() OVER ("
            "PARTITION BY public_source_listing_id "
            "ORDER BY crawled_at DESC, public_offer_event_id DESC"
            ") AS listing_recency FROM normalized_offer_events events) "
            "SELECT e.*, l.source_name, l.source_title, l.source_url, "
            "l.image_url AS listing_image_url, l.source_unit_text, "
            "v.public_variant_id, v.variant_name, v.package_quantity, "
            "v.package_unit, v.display_unit, v.bundle_count, "
            f"{variant_attributes} AS variant_attributes, "
            "p.public_product_id, p.unified_category_id, p.canonical_name, p.primary_image_url, c.name_ko AS category_name "
            "FROM ranked_events e "
            "JOIN normalized_source_listings l "
            "ON l.public_source_listing_id=e.public_source_listing_id "
            "JOIN normalized_product_variants v "
            "ON v.public_variant_id=l.public_variant_id "
            "JOIN normalized_canonical_products p "
            "ON p.public_product_id=v.public_product_id "
            "LEFT JOIN unified_categories c ON c.id=p.unified_category_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY e.crawled_at DESC, e.public_offer_event_id DESC LIMIT ?",
            tuple(params),
        ).fetchall()

        grouped: dict[str, list[dict]] = {}
        latest: dict[str, str] = {}
        for raw_row in rows:
            row = dict(raw_row)
            offer = self._normalized_offer(
                row, {**row, "attributes": row.get("variant_attributes")},
                category_id=row.get("unified_category_id"), source_listing=row,
            )
            # Ambiguous or non-final promotion text is retained in the DB but
            # never ranked or presented as a calculable mart benefit.
            if offer["comparable_price"] is None or not offer["validity_eligible"]:
                continue
            source = str(row.get("source_name") or "")
            selected_offer = {
                **offer, "variant_id": row["public_variant_id"],
                "listing_id": row["public_source_listing_id"],
                "source": source, "source_url": row.get("source_url") or "",
                "is_latest": True, "current_eligible": True,
            }
            grouped.setdefault(source, []).append({
                "id": row["public_product_id"],
                "product_id": row["public_product_id"],
                "public_product_id": row["public_product_id"],
                "category_id": row.get("unified_category_id"),
                "variant_id": row["public_variant_id"],
                "listing_id": row["public_source_listing_id"],
                "offer_id": offer["id"],
                "best_offer": selected_offer,
                "current_eligible": True,
                "valid_from": offer.get("valid_from"),
                "valid_to": offer.get("valid_to"),
                "availability_reason": offer.get("availability_reason"),
                "package_quantity": row.get("package_quantity"),
                "package_unit": row.get("package_unit"),
                "bundle_count": row.get("bundle_count"),
                "name": row.get("source_title") or row.get("canonical_name") or "",
                "canonical_name": row.get("canonical_name") or "",
                "orig": row.get("original_price"),
                "sale": offer["total_price"],
                "disc": round(float(row.get("discount_rate") or 0) * 100),
                "source_url": row.get("source_url") or "",
                "image_url": row.get("listing_image_url") or row.get("primary_image_url") or "",
                "event_name": row.get("event_name") or "",
                "unit": row.get("source_unit_text") or row.get("display_unit") or "",
                "display_unit": row.get("display_unit") or row.get("source_unit_text") or "",
                "category": row.get("category_name") or "",
                "total_quantity": offer.get("total_quantity"),
                "quantity_unit": offer.get("quantity_unit"),
                "per_item": offer.get("per_item"),
                "per_100g": offer.get("per_100g"),
                "per_100ml": offer.get("per_100ml"),
                "per_100m": offer.get("per_100m"),
                "promotion_condition": offer.get("promotion_condition"),
                "minimum_quantity": offer.get("minimum_quantity"),
                "membership_required": offer.get("membership_required"),
                "coupon_required": offer.get("coupon_required"),
                "crawled_at": row.get("crawled_at") or "",
            })
            latest.setdefault(source, str(row.get("crawled_at") or ""))

        result = {}
        for source, items in grouped.items():
            name, color = meta.get(source, (source, "#666"))
            result[source] = {
                "name": name,
                "color": color,
                "items": items,
                "last_crawled_at": latest.get(source, ""),
            }
        return result
