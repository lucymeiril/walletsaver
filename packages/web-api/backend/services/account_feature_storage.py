"""Server-owned cart, wishlist and activity persistence."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from sqlalchemy import text


class AccountFeatureStoreError(RuntimeError):
    pass


class AccountFeatureStore:
    def __init__(self, storage):
        self.storage = storage
        self._session_factory = getattr(storage, "SessionLocal", None)
        if self._session_factory is None:
            raise AccountFeatureStoreError("account DB session factory is unavailable")

    def _product(self, product_id: str | int | None):
        if product_id is None:
            return None
        getter = getattr(self.storage, "get_product_detail", None)
        if getter is None:
            return None
        try:
            product = getter(product_id)
        except (TypeError, ValueError) as exc:
            raise AccountFeatureStoreError("product_not_found") from exc
        if product is None:
            raise AccountFeatureStoreError("product_not_found")
        return product

    @staticmethod
    def _cart(row) -> dict:
        item = dict(row)
        item["cart_id"] = int(item["id"])
        context = item.get("offer_context")
        item["offer_context"] = json.loads(context) if context else None
        return item

    def list_cart(self, user_id: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(text(
                "SELECT * FROM cart_items WHERE user_id=:uid ORDER BY added_at DESC,id DESC"
            ), {"uid": user_id}).mappings().all()
        result = []
        for row in rows:
            item = self._cart(row)
            if item.get("product_id"):
                try:
                    product = self._product(item["product_id"])
                except AccountFeatureStoreError:
                    product = None
                if item.get("offer_context"):
                    item["unit"] = item["offer_context"].get("display_unit") or ""
                elif product:
                    item["unit"] = product.get("unit") or ""
                from services.runtime_storage import RuntimeStorage
                valid, reason = RuntimeStorage._saved_receipt_state(product, item, item.get("offer_context"))
                item.update(saved_receipt_valid=valid, saved_receipt_reason=reason)
            result.append(item)
        return result

    def _find_cart(self, session, user_id: int, item: dict):
        if item.get("product_id") is not None:
            return session.execute(text(
                "SELECT id,quantity FROM cart_items WHERE user_id=:uid AND product_id=:pid "
                "AND COALESCE(store_name,'')=:store "
                "AND COALESCE(variant_id,'')=:variant AND COALESCE(listing_id,'')=:listing "
                "AND COALESCE(offer_id,'')=:offer LIMIT 1"
            ), {"uid": user_id, "pid": item["product_id"], "store": item.get("store_name") or "",
                "variant": item.get("variant_id") or "", "listing": item.get("listing_id") or "",
                "offer": item.get("offer_id") or ""}).mappings().first()
        return session.execute(text(
            "SELECT id,quantity FROM cart_items WHERE user_id=:uid AND product_id IS NULL "
            "AND item_name=:name AND COALESCE(store_name,'')=:store "
            "AND COALESCE(source_url,'')=:url LIMIT 1"
        ), {
            "uid": user_id, "name": item["item_name"],
            "store": item.get("store_name") or "", "url": item.get("source_url") or "",
        }).mappings().first()

    @staticmethod
    def _selected_quote(product: dict | None, item: dict, *, price_field="item_price", allow_unknown=False) -> dict:
        selected = tuple(item.get(key) for key in ("variant_id", "listing_id", "offer_id"))
        if not any(selected):
            return item
        if not all(selected) or not product or not product.get("public_product_id"):
            raise AccountFeatureStoreError("catalog_selection_invalid")
        for variant in product.get("variants", []):
            if variant.get("id") != selected[0]:
                continue
            for listing in variant.get("listings", []):
                if listing.get("id") != selected[1]:
                    continue
                for offer in listing.get("offers", []):
                    if offer.get("id") != selected[2]:
                        continue
                    # Resolve the source identity first. Money validates the
                    # selected quote separately; never switch to product best.
                    quote = offer.get("total_price")
                    if quote is None or not math.isfinite(float(quote)) or float(quote) <= 0:
                        if allow_unknown:
                            quote = None
                        else:
                            raise AccountFeatureStoreError("catalog_price_missing")
                    declared = item.get(price_field)
                    if declared is not None and declared != quote:
                        raise AccountFeatureStoreError("catalog_quote_changed")
                    if not allow_unknown and quote is None:
                        raise AccountFeatureStoreError("catalog_price_missing")
                    context = {key: offer.get(key) for key in (
                        "listed_price", "total_price", "comparable_price", "total_quantity", "quantity_unit",
                        "per_item", "per_100g", "per_100ml", "per_100m",
                        "minimum_quantity", "received_package_count", "promotion_condition", "promotion_conditions",
                        "membership_required", "coupon_required", "promotion_type", "offer_state",
                        "crawled_at", "is_latest", "current_eligible",
                        "valid_from", "valid_to", "availability_reason",
                        "quantity_comparison_reason", "received_package_count_scope", "quantity_basis", "scalar_basis",
                        "pricing_measure_quantity", "pricing_measure_unit", "pricing_measure_basis",
                    )}
                    context.update({key: variant.get(key) for key in (
                        "display_unit", "package_quantity", "package_unit", "bundle_count",
                    )})
                    context.update(variant_name=variant.get("name"), source_title=listing.get("title"))
                    if variant.get("quantity_components"):
                        context["quantity_components"] = variant["quantity_components"]
                    return {**item, price_field: quote, "store_name": listing.get("source"),
                            "source_url": listing.get("url"), "offer_context": context}
        raise AccountFeatureStoreError("catalog_selection_invalid")

    def _upsert_cart(self, session, user_id: int, item: dict, merge_quantity: bool) -> int:
        product = self._product(item.get("product_id"))
        item = self._selected_quote(product, item)
        if product and product.get("public_product_id") and not item.get("offer_id") and item["item_price"] == 0:
            # Catalog price semantics treat 0 as an unconfirmed placeholder.
            # Unlinked, explicitly entered manual free items remain supported.
            raise AccountFeatureStoreError("catalog_price_missing")
        existing = self._find_cart(session, user_id, item)
        quantity = max(1, int(item.get("quantity") or 1))
        params = {
            "uid": user_id, "pid": item.get("product_id"), "name": item["item_name"],
            "price": item["item_price"], "image": item.get("item_image_url"),
            "store": item.get("store_name"), "url": item.get("source_url"),
            "original": item.get("original_price"), "discount": item.get("discount_rate"),
            "category": item.get("category"), "now": datetime.utcnow().isoformat(),
            "variant": item.get("variant_id"), "listing": item.get("listing_id"), "offer": item.get("offer_id"),
            "context": json.dumps(item["offer_context"], ensure_ascii=False) if item.get("offer_context") else None,
        }
        if existing:
            params.update({
                "id": int(existing["id"]),
                "quantity": int(existing["quantity"] or 1) + quantity if merge_quantity else quantity,
            })
            session.execute(text(
                "UPDATE cart_items SET product_id=:pid,item_name=:name,item_price=:price,"
                "item_image_url=:image,store_name=:store,source_url=:url,original_price=:original,"
                "discount_rate=:discount,category=:category,quantity=:quantity,variant_id=:variant,"
                "listing_id=:listing,offer_id=:offer,offer_context=:context WHERE id=:id AND user_id=:uid"
            ), params)
            return params["id"]
        params["quantity"] = quantity
        session.execute(text(
            "INSERT INTO cart_items "
            "(user_id,product_id,item_name,item_price,item_image_url,store_name,source_url,"
            "original_price,discount_rate,category,quantity,added_at,variant_id,listing_id,offer_id,offer_context) "
            "VALUES (:uid,:pid,:name,:price,:image,:store,:url,:original,:discount,:category,:quantity,:now,"
            ":variant,:listing,:offer,:context)"
        ), params)
        row = self._find_cart(session, user_id, item)
        if row is None:
            raise AccountFeatureStoreError("cart_insert_failed")
        return int(row["id"])

    def add_cart(self, user_id: int, item: dict) -> dict:
        with self._session_factory() as session:
            item_id = self._upsert_cart(session, user_id, item, True)
            session.commit()
        return next(row for row in self.list_cart(user_id) if int(row["id"]) == item_id)

    def merge_cart(self, user_id: int, items: list[dict], merge_id: str | None = None) -> list[dict]:
        with self._session_factory() as session:
            # Acquire the SQLite writer lock before checking a receipt or cart
            # quantity. Concurrent retries must not both read the old quantity.
            session.execute(text("BEGIN IMMEDIATE"))
            if merge_id is not None:
                payload_hash = hashlib.sha256(json.dumps(
                    items, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")).hexdigest()
                # Lazy additive schema supports existing account files. The
                # receipt and all cart writes commit or roll back together.
                session.execute(text(
                    "CREATE TABLE IF NOT EXISTS cart_merge_receipts ("
                    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
                    "merge_id TEXT NOT NULL,payload_hash TEXT NOT NULL,"
                    "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                    "PRIMARY KEY(user_id,merge_id))"
                ))
                receipt = session.execute(text(
                    "SELECT payload_hash FROM cart_merge_receipts "
                    "WHERE user_id=:uid AND merge_id=:merge"
                ), {"uid": user_id, "merge": merge_id}).scalar_one_or_none()
                if receipt is not None:
                    if receipt != payload_hash:
                        raise AccountFeatureStoreError("cart_merge_conflict")
                    session.commit()
                    return self.list_cart(user_id)
                session.execute(text(
                    "INSERT INTO cart_merge_receipts (user_id,merge_id,payload_hash) "
                    "VALUES (:uid,:merge,:hash)"
                ), {"uid": user_id, "merge": merge_id, "hash": payload_hash})
            for item in items:
                self._upsert_cart(session, user_id, item, True)
            session.commit()
        return self.list_cart(user_id)

    def update_cart_quantity(self, user_id: int, cart_id: int, quantity: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(text(
                "UPDATE cart_items SET quantity=:q WHERE id=:id AND user_id=:uid"
            ), {"q": quantity, "id": cart_id, "uid": user_id})
            session.commit()
            return bool(result.rowcount)

    def delete_cart_item(self, user_id: int, cart_id: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM cart_items WHERE id=:id AND user_id=:uid"),
                {"id": cart_id, "uid": user_id},
            )
            session.commit()
            return bool(result.rowcount)

    def clear_cart(self, user_id: int) -> int:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM cart_items WHERE user_id=:uid"), {"uid": user_id}
            )
            session.commit()
            return int(result.rowcount or 0)

    def list_wishlist(self, user_id: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(text(
                "SELECT * FROM wishlist_items WHERE user_id=:uid ORDER BY added_at DESC,id DESC"
            ), {"uid": user_id}).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            item["offer_context"] = json.loads(item["offer_context"]) if item.get("offer_context") else None
            product_id = item.get("product_id")
            if product_id:
                try:
                    product = self._product(product_id)
                except AccountFeatureStoreError:
                    product = None
                from services.runtime_storage import RuntimeStorage
                valid, receipt_reason = RuntimeStorage._saved_receipt_state(product, item, item.get("offer_context"))
                item.update(saved_receipt_valid=valid, saved_receipt_reason=receipt_reason)
                if product:
                    if product.get("public_product_id"):
                        from services.runtime_storage import RuntimeStorage
                        current, current_id, context, reason = RuntimeStorage._alert_current(
                            product, item, item.get("offer_context"))
                        item.update(current_price=current, current_offer_id=current_id,
                                    current_offer_context=context, comparison_reason=reason,
                                    quoted_price=(context or {}).get("total_price"))
                    else:
                        item["current_price"] = product.get("cur") or product.get("price") or item.get("current_price")
                else:
                    item.update(current_price=None, comparison_reason="selected_product_unavailable")
            item["notify_on_drop"] = bool(item.get("notify_on_drop"))
            item["price_change_eligible"] = item.get("current_price") is not None and not item.get("comparison_reason")
            result.append(item)
        return result

    def _find_wishlist(self, session, user_id: int, item: dict):
        if item.get("product_id") is not None:
            return session.execute(text(
                "SELECT id FROM wishlist_items WHERE user_id=:uid AND product_id=:pid "
                "AND COALESCE(variant_id,'')=:variant AND COALESCE(listing_id,'')=:listing "
                "LIMIT 1"
            ), {"uid": user_id, "pid": item["product_id"], "variant": item.get("variant_id") or "",
                "listing": item.get("listing_id") or "", "offer": item.get("offer_id") or ""}).first()
        return session.execute(text(
            "SELECT id FROM wishlist_items WHERE user_id=:uid AND product_id IS NULL "
            "AND item_name=:name AND COALESCE(store_name,'')=:store LIMIT 1"
        ), {"uid": user_id, "name": item["item_name"], "store": item.get("store_name") or ""}).first()

    def add_wishlist(self, user_id: int, item: dict) -> dict:
        product = self._product(item.get("product_id"))
        item = self._selected_quote(product, item, price_field="price_at_add", allow_unknown=True)
        now = datetime.utcnow().isoformat()
        with self._session_factory() as session:
            existing = self._find_wishlist(session, user_id, item)
            params = {
                "uid": user_id, "pid": item.get("product_id"), "name": item["item_name"],
                "target": item.get("target_price"), "image": item.get("item_image_url"),
                "store": item.get("store_name"), "category": item.get("category"),
                "add_price": item.get("price_at_add"), "current": item.get("current_price"),
                "notify": 1 if item.get("notify_on_drop") else 0, "now": now,
                "variant": item.get("variant_id"), "listing": item.get("listing_id"),
                "offer": item.get("offer_id"), "url": item.get("source_url"),
                "context": json.dumps(item["offer_context"], ensure_ascii=False) if item.get("offer_context") else None,
            }
            if existing:
                wishlist_id = int(existing.id)
                params["id"] = wishlist_id
                session.execute(text(
                    "UPDATE wishlist_items SET item_name=:name,target_price=:target,item_image_url=:image,"
                    "store_name=:store,category=:category,price_at_add=:add_price,current_price=:current,"
                    "notify_on_drop=:notify,variant_id=:variant,listing_id=:listing,offer_id=:offer,"
                    "source_url=:url,offer_context=:context WHERE id=:id AND user_id=:uid"
                ), params)
            else:
                session.execute(text(
                    "INSERT INTO wishlist_items "
                    "(user_id,product_id,item_name,target_price,item_image_url,store_name,category,"
                    "price_at_add,current_price,added_at,notify_on_drop,variant_id,listing_id,offer_id,source_url,offer_context) "
                    "VALUES (:uid,:pid,:name,:target,:image,:store,:category,:add_price,:current,:now,:notify,"
                    ":variant,:listing,:offer,:url,:context)"
                ), params)
                found = self._find_wishlist(session, user_id, item)
                if found is None:
                    raise AccountFeatureStoreError("wishlist_insert_failed")
                wishlist_id = int(found.id)
            session.commit()
        return next(row for row in self.list_wishlist(user_id) if int(row["id"]) == wishlist_id)

    def update_wishlist(self, user_id: int, wishlist_id: int, target_price: float | None, notify: bool) -> bool:
        with self._session_factory() as session:
            result = session.execute(text(
                "UPDATE wishlist_items SET target_price=:target,notify_on_drop=:notify "
                "WHERE id=:id AND user_id=:uid"
            ), {"target": target_price, "notify": 1 if notify else 0, "id": wishlist_id, "uid": user_id})
            session.commit()
            return bool(result.rowcount)

    def delete_wishlist(self, user_id: int, wishlist_id: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM wishlist_items WHERE id=:id AND user_id=:uid"),
                {"id": wishlist_id, "uid": user_id},
            )
            session.commit()
            return bool(result.rowcount)

    def track_activity(self, user_id: int, activity_type: str, target_type: str | None, target_id: str | None, metadata: dict | None) -> int:
        now = datetime.utcnow().isoformat()
        with self._session_factory() as session:
            session.execute(text(
                "INSERT INTO user_activities "
                "(user_id,activity_type,target_type,target_id,metadata,created_at) "
                "VALUES (:uid,:kind,:target_type,:target_id,:metadata,:now)"
            ), {
                "uid": user_id, "kind": activity_type, "target_type": target_type,
                "target_id": target_id, "metadata": json.dumps(metadata or {}, ensure_ascii=False),
                "now": now,
            })
            session.commit()
            return int(session.execute(text(
                "SELECT id FROM user_activities WHERE user_id=:uid ORDER BY id DESC LIMIT 1"
            ), {"uid": user_id}).scalar_one())

    def list_activity(self, user_id: int, page: int, per_page: int) -> tuple[list[dict], int]:
        with self._session_factory() as session:
            total = int(session.execute(
                text("SELECT COUNT(*) FROM user_activities WHERE user_id=:uid"), {"uid": user_id}
            ).scalar_one())
            rows = session.execute(text(
                "SELECT id,activity_type,target_type,target_id,metadata,created_at "
                "FROM user_activities WHERE user_id=:uid ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
            ), {"uid": user_id, "limit": per_page, "offset": (page - 1) * per_page}).mappings().all()
        data = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _metadata(item.get("metadata"))
            data.append(item)
        return data, total


def _metadata(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except Exception:
        return {}
