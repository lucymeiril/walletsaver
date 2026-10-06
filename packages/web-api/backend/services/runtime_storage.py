"""Web-api-owned runtime storage split across multiple SQLite files."""
from __future__ import annotations

from datetime import datetime
import json
import math
import re
import sqlite3

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from services.account_database import AccountDatabase
from services.catalog_storage import CatalogUnavailable, PublicCatalogStore
from services.external_hotdeal_storage import ExternalHotdealStore
from services.interaction_storage import InteractionDatabase


def _like_contains(value: str) -> str:
    """Build a literal contains-pattern for SQLite LIKE with backslash escaping."""
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


class RuntimeStorage:
    """Compatibility facade over physically separated web-owned databases."""

    def __init__(self):
        self.catalog = PublicCatalogStore()
        self.accounts = AccountDatabase()
        self.external_hotdeals = ExternalHotdealStore()
        self.interactions = InteractionDatabase()
        self.SessionLocal = self.accounts.SessionLocal
        self.engine = self.accounts.engine

    def init_db(self) -> None:
        self.accounts.initialize()
        self.interactions.initialize()

    def catalog_health(self) -> dict:
        return self.catalog.health()

    def get_products(self) -> list[dict]:
        return self.search_products("", page=1, per_page=self.catalog.MAX_RESULT_LIMIT)

    def search_products_page(
        self,
        query: str,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """Search before pagination so rows beyond the old 1000-item cap remain reachable."""
        if self.catalog.has_normalized_catalog():
            return self.catalog.search_normalized_products_page(
                query, category=category, page=page, per_page=per_page
            )
        page = max(1, int(page or 1))
        per_page = max(1, min(int(per_page or 20), self.catalog.MAX_RESULT_LIMIT))
        clauses = ["p.is_active=1"]
        params: list[object] = []

        query_text = str(query or "").strip()
        if query_text:
            clauses.append(
                "LOWER(COALESCE(NULLIF(p.display_name, ''), p.name, '')) "
                "LIKE LOWER(?) ESCAPE '\\'"
            )
            params.append(_like_contains(query_text))

        category_text = str(category or "").strip()
        with self.catalog.connection() as connection:
            if category_text:
                pattern = _like_contains(category_text)
                category_clauses = [
                    "LOWER(COALESCE(p.unified_category_id, '')) LIKE LOWER(?) ESCAPE '\\'",
                    "LOWER(COALESCE(p.category_id, '')) LIKE LOWER(?) ESCAPE '\\'",
                ]
                category_params: list[object] = [pattern, pattern]
                if self.catalog._table(connection, "unified_categories"):
                    category_clauses.append(
                        "EXISTS (SELECT 1 FROM unified_categories uc "
                        "WHERE uc.id=p.unified_category_id "
                        "AND LOWER(COALESCE(uc.name_ko, '')) LIKE LOWER(?) ESCAPE '\\')"
                    )
                    category_params.append(pattern)
                if self.catalog._table(connection, "categories"):
                    category_clauses.append(
                        "EXISTS (SELECT 1 FROM categories c "
                        "WHERE c.id=p.category_id "
                        "AND LOWER(COALESCE(c.name, '')) LIKE LOWER(?) ESCAPE '\\')"
                    )
                    category_params.append(pattern)
                clauses.append("(" + " OR ".join(category_clauses) + ")")
                params.extend(category_params)

            where_sql = " AND ".join(clauses)
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM products p WHERE {where_sql}",
                tuple(params),
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT p.* FROM products p WHERE {where_sql} "
                "ORDER BY COALESCE(NULLIF(p.display_name, ''), p.name, '') COLLATE NOCASE, p.id "
                "LIMIT ? OFFSET ?",
                (*params, per_page, (page - 1) * per_page),
            ).fetchall()
            return [self.catalog._product(connection, row) for row in rows], total

    def search_products(self, *args, **kwargs):
        rows, _total = self.search_products_page(*args, **kwargs)
        return rows

    def get_product_detail(self, product_id):
        if self.catalog.has_normalized_catalog():
            return self.catalog.get_normalized_product_detail(str(product_id))
        return self.catalog.get_product_detail(int(product_id))

    def get_price_history(self, product_id: int, days: int = 30):
        return self.catalog.get_price_history(product_id, days)

    def get_price_compare(self, product_id: int):
        return self.catalog.get_price_compare(product_id)

    def get_category_tree(self):
        return self.catalog.get_category_tree()

    def get_category_children(self, category_id: str):
        return self.catalog.get_category_children(category_id)

    def get_category_products(self, category_id: str, page: int, per_page: int):
        return self.catalog.get_category_products(category_id, page, per_page)

    def get_mart_deals(self, store: str | None = None, limit: int = 50):
        return self.catalog.get_mart_deals(store=store, limit=limit)

    def get_hotdeals(
        self,
        category: str | None = None,
        source: str | None = None,
        sort: str = "recent",
        page: int = 1,
        per_page: int = 20,
        limit: int | None = None,
    ) -> list[dict]:
        if limit is not None:
            page = 1
            per_page = min(int(limit), 100)
        rows = self.external_hotdeals.list_hotdeals(
            category=category,
            source=source,
            sort=sort,
            page=page,
            per_page=per_page,
        )
        result = []
        for row in rows:
            hot, not_ = self.interactions.vote_counts(int(row["id"]))
            item = dict(row)
            item["votes_hot"] = hot
            item["votes_not"] = not_
            item["is_verified"] = (hot + not_) >= 10
            result.append(item)
        if sort in {"popular", "votes"}:
            result.sort(
                key=lambda row: row.get("votes_hot", 0) - row.get("votes_not", 0),
                reverse=True,
            )
        return result

    def get_hotdeal_detail(self, hotdeal_id: int) -> dict | None:
        row = self.external_hotdeals.get_hotdeal(hotdeal_id)
        if row is None:
            return None
        hot, not_ = self.interactions.vote_counts(hotdeal_id)
        row["votes_hot"] = hot
        row["votes_not"] = not_
        row["is_verified"] = (hot + not_) >= 10
        return row

    def vote_hotdeal(self, hotdeal_id: int, vote_type: str, identity_key: str = "unknown") -> dict:
        if self.external_hotdeals.get_hotdeal(hotdeal_id) is None:
            raise ValueError("hotdeal not found")
        if vote_type not in {"hot", "not"}:
            raise ValueError("invalid vote type")
        return self.interactions.toggle_vote(hotdeal_id, vote_type, identity_key)

    def get_user_favorites(self, user_id: str | int) -> list[dict]:
        uid = int(user_id)
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT product_id, created_at FROM favorites "
                    "WHERE user_id=:user_id ORDER BY created_at DESC, id DESC"
                ),
                {"user_id": uid},
            ).mappings().all()
        result = []
        for row in rows:
            product = self.catalog.get_product_detail(int(row["product_id"]))
            if product is None:
                continue
            result.append({
                "product_id": int(row["product_id"]),
                "name": product.get("name", ""),
                "cat": product.get("cat", ""),
                "unit": product.get("unit", ""),
                "added_at": row["created_at"],
            })
        return result

    def add_user_favorite(self, user_id: str | int, product_id: int) -> dict:
        uid = int(user_id)
        if not self.catalog.product_exists(product_id):
            raise ValueError("product not found")
        with self.SessionLocal() as session:
            try:
                session.execute(
                    text(
                        "INSERT INTO favorites (user_id, product_id, created_at) "
                        "VALUES (:user_id, :product_id, :created_at)"
                    ),
                    {
                        "user_id": uid,
                        "product_id": product_id,
                        "created_at": datetime.utcnow().isoformat(),
                    },
                )
                session.commit()
            except IntegrityError:
                session.rollback()
            row = session.execute(
                text(
                    "SELECT id FROM favorites "
                    "WHERE user_id=:user_id AND product_id=:product_id"
                ),
                {"user_id": uid, "product_id": product_id},
            ).first()
        return {
            "id": int(row.id) if row else None,
            "user_id": uid,
            "product_id": product_id,
            "status": "added",
        }

    def remove_user_favorite(self, user_id: str | int, product_id: int) -> dict:
        uid = int(user_id)
        with self.SessionLocal() as session:
            result = session.execute(
                text(
                    "DELETE FROM favorites WHERE user_id=:user_id AND product_id=:product_id"
                ),
                {"user_id": uid, "product_id": product_id},
            )
            session.commit()
        return {"status": "removed" if result.rowcount else "not_found"}

    @staticmethod
    def _alert_amount(value):
        if isinstance(value, bool) or value is None:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return amount if math.isfinite(amount) and amount > 0 else None

    @staticmethod
    def _alert_selection(product, variant_id, listing_id, offer_id):
        if not all(isinstance(value, str) and value.strip() and value == value.strip()
                   for value in (variant_id, listing_id, offer_id)):
            raise ValueError("catalog_selection_invalid")
        for variant in (product or {}).get("variants", []):
            if variant.get("id") != variant_id:
                continue
            for listing in variant.get("listings", []):
                if listing.get("id") != listing_id:
                    continue
                for offer in listing.get("offers", []):
                    if offer.get("id") == offer_id:
                        return variant, listing, offer
        raise ValueError("catalog_selection_invalid")

    @staticmethod
    def _alert_context(variant, listing, offer):
        context = {key: offer.get(key) for key in (
            "listed_price", "total_price", "comparable_price", "total_quantity", "quantity_unit",
            "per_item", "per_100g", "per_100ml", "per_100m", "minimum_quantity", "received_package_count",
            "promotion_type", "promotion_condition", "promotion_conditions", "membership_required",
            "coupon_required", "offer_state", "is_latest", "current_eligible", "crawled_at",
            "valid_from", "valid_to", "availability_reason",
            "quantity_comparison_reason",
            "observation_receipt_eligible", "observation_receipt_reason",
            "received_package_count_scope", "quantity_basis", "scalar_basis",
            "pricing_measure_quantity", "pricing_measure_unit", "pricing_measure_basis",
        )}
        context.update({key: variant.get(key) for key in (
            "display_unit", "package_quantity", "package_unit", "bundle_count",
        )})
        context.update(variant_name=variant.get("name"), source=listing.get("source"),
                       source_title=listing.get("title"), source_url=listing.get("url"))
        if variant.get("quantity_components"):
            context["quantity_components"] = variant["quantity_components"]
        return context

    @classmethod
    def _saved_receipt_state(cls, product, row, saved):
        """Validate saved specification against its own historical offer, without rewriting it."""
        selection = [row.get(key) for key in ("variant_id", "listing_id", "offer_id")]
        if not any(selection):
            return None, None  # Legacy/manual items have no normalized receipt.
        if not product:
            return None, "catalog_unavailable"
        if not isinstance(saved, dict) or not all(isinstance(value, str) and value.strip() for value in selection):
            return False, "selection_context_missing"
        try:
            variant, listing, offer = cls._alert_selection(product, *selection)
        except ValueError:
            variant = listing = offer = None
            for candidate in product.get("variants", []):
                matching = next((item for item in candidate.get("listings", [])
                                 if item.get("id") == row.get("listing_id")), None)
                if matching:
                    if candidate.get("id") != row.get("variant_id"):
                        return False, "selected_specification_revised"
                    latest = [item for item in matching.get("offers", []) if item.get("is_latest") is True]
                    if len(latest) != 1:
                        return None, "selected_offer_unavailable"
                    variant, listing, offer = candidate, matching, latest[0]
                    break
            if listing is None:
                return None, "selected_listing_unavailable"
            current = cls._alert_context(variant, listing, offer)
            if any(saved.get(key) != current.get(key) for key in (
                    "promotion_type", "minimum_quantity", "promotion_condition", "promotion_conditions",
                    "membership_required", "coupon_required")):
                return None, "selected_offer_unavailable"
        for key in ("package_quantity", "package_unit", "bundle_count"):
            if saved.get(key) != variant.get(key):
                return False, "selected_specification_revised"
        components = variant.get("quantity_components")
        if components and saved.get("quantity_components") != components:
            return False, "receipt_components_unconfirmed"
        historical = cls._alert_context(variant, listing, offer)
        if historical.get("observation_receipt_eligible") is False:
            return False, historical.get("observation_receipt_reason") or "receipt_basis_revised"
        if historical.get("quantity_basis") in {"reviewed_homogeneous_contents", "reviewed_declared_linear_contents"}:
            for key in ("quantity_basis", "scalar_basis", "received_package_count_scope",
                        "pricing_measure_quantity", "pricing_measure_unit", "pricing_measure_basis"):
                if saved.get(key) != historical.get(key):
                    return False, "receipt_basis_revised"
        comparison_reason = historical.get("quantity_comparison_reason")
        if isinstance(comparison_reason, str) and comparison_reason:
            return False, comparison_reason
        for key in ("total_quantity", "quantity_unit", "received_package_count"):
            if saved.get(key) != historical.get(key):
                return False, "receipt_basis_revised"
        # Price changes, expiry and today's eligibility do not invalidate an
        # accurately recorded historical specification or authorize a new one.
        return True, None

    @classmethod
    def _alert_current(cls, product, row, saved):
        # Price is an observation, not selection identity. Never search another
        # listing/variant for a cheaper event, or revive an older active quote.
        if (not isinstance(saved, dict) or not all(
                isinstance(row[key], str) and row[key].strip() and row[key] == row[key].strip()
                for key in ("variant_id", "listing_id", "offer_id"))):
            return None, None, None, "selection_context_missing"
        try:
            variant, listing, _ = cls._alert_selection(
                product, row["variant_id"], row["listing_id"], row["offer_id"]
            )
        except ValueError:
            # The original event may have aged out of an otherwise intact listing.
            variant = next((v for v in (product or {}).get("variants", [])
                            if v.get("id") == row["variant_id"]), None)
            listing = next((item for item in (variant or {}).get("listings", [])
                            if item.get("id") == row["listing_id"]), None)
            if listing is None:
                return None, None, None, "selected_listing_unavailable"
        latest = [offer for offer in listing.get("offers", []) if offer.get("is_latest") is True]
        if len(latest) != 1:
            return None, None, None, "latest_quote_unavailable"
        offer = latest[0]
        context = cls._alert_context(variant, listing, offer)
        if offer.get("offer_state") != "active":
            return None, offer.get("id"), context, "quote_unavailable"
        if offer.get("availability_reason"):
            return None, offer.get("id"), context, offer["availability_reason"]
        if offer.get("validity_eligible") is False:
            return None, offer.get("id"), context, "validity_unconfirmed"
        comparison_reason = context.get("quantity_comparison_reason")
        if isinstance(comparison_reason, str) and comparison_reason:
            return None, offer.get("id"), context, comparison_reason
        # A complete-vector wrapper alone cannot confirm its measured contents.
        # Validate the original receipt before following today's price; never
        # fill missing persisted proof from the current catalog silently.
        if variant.get("quantity_components") or context.get("quantity_basis") == "reviewed_declared_linear_contents":
            receipt_valid, receipt_reason = cls._saved_receipt_state(product, row, saved)
            if receipt_valid is False:
                return None, offer.get("id"), context, receipt_reason
        terms = context.get("promotion_conditions")
        terms = terms if isinstance(terms, dict) else {}
        # A reviewed advertised basket amount is a known source term, not the
        # selected user's paid receipt. Retain the complete terms in context;
        # distinguish its unresolved selection/payment from an absent quote.
        if terms.get("payable_price_unconfirmed") not in (None, False):
            reason = ("basket_selection_unconfirmed" if terms.get("basket_selection_required") is True
                      else "conditional_payment_unconfirmed")
            return None, offer.get("id"), context, reason
        if terms.get("eligible_selection_unconfirmed") not in (None, False):
            return None, offer.get("id"), context, "basket_selection_unconfirmed"
        if offer.get("current_eligible") is not True:
            return None, offer.get("id"), context, "quote_unavailable"
        amount = cls._alert_amount(offer.get("total_price"))
        comparable = cls._alert_amount(offer.get("comparable_price"))
        if amount is None or comparable is None:
            return None, offer.get("id"), context, "price_unconfirmed"
        # Unknown initial receipt is never upgraded silently to a newly known
        # quantity. The user must save that confirmed selected context explicitly.
        for receipt in (saved, context):
            if (cls._alert_amount(receipt.get("total_quantity")) is None
                    or not isinstance(receipt.get("quantity_unit"), str)
                    or not receipt.get("quantity_unit").strip()
                    or cls._alert_amount(receipt.get("received_package_count")) is None
                    or cls._alert_amount(receipt.get("package_quantity")) is None
                    or cls._alert_amount(receipt.get("bundle_count")) is None
                    or not isinstance(receipt.get("package_unit"), str)
                    or not receipt.get("package_unit").strip()):
                return None, offer.get("id"), context, "receipt_basis_unknown"
        receipt_fields = (
            "package_quantity", "package_unit", "bundle_count", "total_quantity", "quantity_unit",
            "received_package_count", "minimum_quantity", "promotion_type", "promotion_condition",
            "promotion_conditions", "membership_required", "coupon_required",
            "quantity_components", "quantity_basis", "scalar_basis", "received_package_count_scope",
            "pricing_measure_quantity", "pricing_measure_unit", "pricing_measure_basis",
        )
        if any(saved.get(key) != context.get(key) for key in receipt_fields):
            return None, offer.get("id"), context, "receipt_conditions_changed"
        benefit = context.get("promotion_type") == "buy_x_get_y"
        if (context.get("membership_required") is not False
                or context.get("coupon_required") is not False):
            return None, offer.get("id"), context, "membership_or_coupon_unverified"
        if benefit:
            terms = context.get("promotion_conditions")
            terms = terms if isinstance(terms, dict) else {}
            buy, free = terms.get("buy_quantity"), terms.get("free_quantity")
            # Confirm the actual transaction and whole receipt. A benefit label
            # alone cannot establish paid/free counts or user eligibility.
            allowed = {"buy_quantity", "free_quantity", "minimum_quantity", "condition_text",
                       "membership_required", "coupon_required"}
            declared = {key for key, value in terms.items() if value not in (None, "", False)}
            condition = re.sub(r"\s+", "", str(context.get("promotion_condition") or ""))
            if (type(buy) is not int or type(free) is not int or buy <= 0 or free <= 0
                    or declared - allowed
                    or context.get("minimum_quantity") != buy
                    or isinstance(context.get("minimum_quantity"), bool)
                    or context.get("received_package_count") != buy + free
                    or condition not in ("", f"{buy}+{free}")
                    or cls._alert_amount(offer.get("listed_price")) is None
                    or not math.isclose(amount, float(offer["listed_price"]) * buy)
                    or not math.isclose(amount, comparable)
                    or not math.isclose(float(context["total_quantity"]),
                                        float(context["package_quantity"]) * float(context["bundle_count"]) * (buy + free))):
                return None, offer.get("id"), context, "eligibility_unverified"
            return amount, offer.get("id"), context, None
        minimum = context.get("minimum_quantity")
        terms = context.get("promotion_conditions")
        if minimum != 1 and context.get("promotion_type") == "final_price":
            from core.promotion_semantics import comparable_transaction_or_none
            allowed = {"minimum_quantity", "condition_text", "source_title_purchase_condition",
                       "membership_required", "coupon_required"}
            terms = terms if isinstance(terms, dict) else {}
            declared = {key for key, value in terms.items() if value not in (None, "", False)}
            condition = re.sub(r"\s+", "", str(context.get("promotion_condition") or ""))
            transaction = comparable_transaction_or_none(
                current_price=offer.get("listed_price"), promotion_type="final_price",
                promotion_conditions=terms)
            if (type(minimum) is not int or minimum < 2 or declared - allowed
                    or terms.get("minimum_quantity") != minimum
                    or condition != f"최소구매{minimum}"
                    or transaction is None or transaction[1] != minimum
                    or context.get("received_package_count") != minimum
                    or not math.isclose(amount, transaction[0])
                    or not math.isclose(amount, comparable)
                    or not math.isclose(float(context["total_quantity"]),
                                        float(context["package_quantity"]) * float(context["bundle_count"]) * minimum)):
                return None, offer.get("id"), context, "eligibility_unverified"
            return amount, offer.get("id"), context, None
        if (minimum != 1
                or isinstance(minimum, bool)
                or context.get("promotion_type") not in ("normal", "final_price", "discount")
                or context.get("promotion_conditions") not in ({}, None)
                or context.get("promotion_condition")):
            return None, offer.get("id"), context, "eligibility_unverified"
        return amount, offer.get("id"), context, None

    def add_price_alert(
        self, user_id: str | int, product_id: str | int, target_price: int, *,
        variant_id: str | None = None, listing_id: str | None = None, offer_id: str | None = None,
    ) -> dict:
        uid = int(user_id)
        if isinstance(target_price, bool) or not isinstance(target_price, int) or target_price <= 0:
            raise ValueError("target_price_invalid")
        product = self.get_product_detail(product_id)
        if not product:
            raise ValueError("product not found")
        selected = any(value is not None for value in (variant_id, listing_id, offer_id))
        context = None
        if selected:
            if not self.catalog.has_normalized_catalog():
                raise ValueError("catalog_selection_invalid")
            variant, listing, offer = self._alert_selection(product, variant_id, listing_id, offer_id)
            # Structurally valid but unknown/inactive quotes are saved as held;
            # no client money/context, fabricated zero or substitute offer is used.
            context = self._alert_context(variant, listing, offer)
        now = datetime.utcnow().isoformat()
        params = {"user_id": uid, "product_id": str(product_id), "target_price": target_price,
                  "variant": variant_id, "listing": listing_id, "offer": offer_id,
                  "context": json.dumps(context, ensure_ascii=False) if context is not None else None,
                  "created_at": now}
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.execute(
                text(
                    "SELECT id FROM price_alerts "
                    "WHERE user_id=:user_id AND product_id=:product_id "
                    "AND COALESCE(variant_id,'')=COALESCE(:variant,'') "
                    "AND COALESCE(listing_id,'')=COALESCE(:listing,'') "
                    "AND COALESCE(offer_id,'')=COALESCE(:offer,'')"
                ),
                params,
            ).first()
            if row:
                alert_id = int(row.id)
                session.execute(
                    text(
                        "UPDATE price_alerts SET target_price=:target_price, offer_context=:context, is_active=1 "
                        "WHERE id=:id"
                    ),
                    {**params, "id": alert_id},
                )
            else:
                session.execute(
                    text(
                        "INSERT INTO price_alerts "
                        "(user_id, product_id, target_price, is_active, created_at, variant_id, listing_id, offer_id, offer_context) "
                        "VALUES (:user_id, :product_id, :target_price, 1, :created_at, :variant, :listing, :offer, :context)"
                    ),
                    params,
                )
                alert_id = int(session.execute(
                    text(
                        "SELECT last_insert_rowid()"
                    ),
                ).scalar_one())
            session.commit()
        return {**next(row for row in self.get_user_alerts(uid) if row["id"] == alert_id), "status": "active"}

    def get_user_alerts(self, user_id: str | int) -> list[dict]:
        uid = int(user_id)
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, product_id, target_price, is_active, created_at, "
                    "variant_id, listing_id, offer_id, offer_context "
                    "FROM price_alerts WHERE user_id=:user_id AND is_active=1 "
                    "ORDER BY created_at DESC, id DESC"
                ),
                {"user_id": uid},
            ).mappings().all()
        result = []
        for row in rows:
            catalog_id = str(row["product_id"])
            unavailable = False
            try:
                product = self.get_product_detail(catalog_id)
                normalized = self.catalog.has_normalized_catalog()
            except (CatalogUnavailable, sqlite3.DatabaseError):
                product, unavailable = None, True
            except (ValueError, TypeError):
                product = None
                normalized = True
            try:
                saved = json.loads(row["offer_context"]) if row["offer_context"] else None
            except (TypeError, ValueError):
                saved = None
            current_offer_id, current_context = None, None
            receipt_valid, receipt_reason = self._saved_receipt_state(product, dict(row), saved)
            if unavailable:
                current_price, reason = None, "catalog_unavailable"
            elif row["variant_id"] or row["listing_id"] or row["offer_id"]:
                current_price, current_offer_id, current_context, reason = self._alert_current(product, row, saved)
            elif normalized:
                current_price, reason = None, "selection_required"
            else:
                current_price = self._alert_amount((product or {}).get("cur")) or self._alert_amount((product or {}).get("price"))
                reason = None if current_price is not None else "price_unconfirmed"
            result.append({
                "id": int(row["id"]),
                "product_id": catalog_id,
                "product_name": product.get("name", "") if product else "",
                "target_price": row["target_price"],
                "current_price": current_price,
                "variant_id": row["variant_id"], "listing_id": row["listing_id"], "offer_id": row["offer_id"],
                "offer_context": saved, "current_offer_id": current_offer_id,
                "saved_receipt_valid": receipt_valid, "saved_receipt_reason": receipt_reason,
                "current_offer_context": current_context,
                "quoted_price": self._alert_amount((current_context or saved or {}).get("total_price")),
                "trigger_reason": reason,
                "is_triggered": bool(reason is None and current_price is not None and current_price <= row["target_price"]),
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
            })
        return result

    def remove_price_alert(self, user_id: str | int, alert_id: int) -> dict:
        uid = int(user_id)
        with self.SessionLocal() as session:
            result = session.execute(
                text("UPDATE price_alerts SET is_active=0 WHERE id=:id AND user_id=:user_id"),
                {"id": int(alert_id), "user_id": uid},
            )
            session.commit()
        return {"status": "removed" if result.rowcount else "not_found"}

    def close(self) -> None:
        self.accounts.close()
        self.interactions.close()
