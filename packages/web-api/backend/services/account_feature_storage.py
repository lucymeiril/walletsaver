"""Server-owned cart, wishlist and activity persistence."""
from __future__ import annotations

import json
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

    def _product(self, product_id: int | None):
        if product_id is None:
            return None
        getter = getattr(self.storage, "get_product_detail", None)
        if getter is None:
            return None
        product = getter(int(product_id))
        if product is None:
            raise AccountFeatureStoreError("product_not_found")
        return product

    @staticmethod
    def _cart(row) -> dict:
        item = dict(row)
        item["cart_id"] = int(item["id"])
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
                if product:
                    item["unit"] = product.get("unit") or ""
            result.append(item)
        return result

    def _find_cart(self, session, user_id: int, item: dict):
        if item.get("product_id") is not None:
            return session.execute(text(
                "SELECT id,quantity FROM cart_items WHERE user_id=:uid AND product_id=:pid "
                "AND COALESCE(store_name,'')=:store LIMIT 1"
            ), {"uid": user_id, "pid": item["product_id"], "store": item.get("store_name") or ""}).mappings().first()
        return session.execute(text(
            "SELECT id,quantity FROM cart_items WHERE user_id=:uid AND product_id IS NULL "
            "AND item_name=:name AND COALESCE(store_name,'')=:store "
            "AND COALESCE(source_url,'')=:url LIMIT 1"
        ), {
            "uid": user_id, "name": item["item_name"],
            "store": item.get("store_name") or "", "url": item.get("source_url") or "",
        }).mappings().first()

    def _upsert_cart(self, session, user_id: int, item: dict, merge_quantity: bool) -> int:
        self._product(item.get("product_id"))
        existing = self._find_cart(session, user_id, item)
        quantity = max(1, int(item.get("quantity") or 1))
        params = {
            "uid": user_id, "pid": item.get("product_id"), "name": item["item_name"],
            "price": item["item_price"], "image": item.get("item_image_url"),
            "store": item.get("store_name"), "url": item.get("source_url"),
            "original": item.get("original_price"), "discount": item.get("discount_rate"),
            "category": item.get("category"), "now": datetime.utcnow().isoformat(),
        }
        if existing:
            params.update({
                "id": int(existing["id"]),
                "quantity": int(existing["quantity"] or 1) + quantity if merge_quantity else quantity,
            })
            session.execute(text(
                "UPDATE cart_items SET product_id=:pid,item_name=:name,item_price=:price,"
                "item_image_url=:image,store_name=:store,source_url=:url,original_price=:original,"
                "discount_rate=:discount,category=:category,quantity=:quantity WHERE id=:id AND user_id=:uid"
            ), params)
            return params["id"]
        params["quantity"] = quantity
        session.execute(text(
            "INSERT INTO cart_items "
            "(user_id,product_id,item_name,item_price,item_image_url,store_name,source_url,"
            "original_price,discount_rate,category,quantity,added_at) "
            "VALUES (:uid,:pid,:name,:price,:image,:store,:url,:original,:discount,:category,:quantity,:now)"
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

    def merge_cart(self, user_id: int, items: list[dict]) -> list[dict]:
        with self._session_factory() as session:
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
            product_id = item.get("product_id")
            if product_id:
                try:
                    product = self._product(product_id)
                except AccountFeatureStoreError:
                    product = None
                if product:
                    item["current_price"] = product.get("cur") or product.get("price") or item.get("current_price")
            item["notify_on_drop"] = bool(item.get("notify_on_drop"))
            result.append(item)
        return result

    def _find_wishlist(self, session, user_id: int, item: dict):
        if item.get("product_id") is not None:
            return session.execute(text(
                "SELECT id FROM wishlist_items WHERE user_id=:uid AND product_id=:pid LIMIT 1"
            ), {"uid": user_id, "pid": item["product_id"]}).first()
        return session.execute(text(
            "SELECT id FROM wishlist_items WHERE user_id=:uid AND product_id IS NULL "
            "AND item_name=:name AND COALESCE(store_name,'')=:store LIMIT 1"
        ), {"uid": user_id, "name": item["item_name"], "store": item.get("store_name") or ""}).first()

    def add_wishlist(self, user_id: int, item: dict) -> dict:
        self._product(item.get("product_id"))
        now = datetime.utcnow().isoformat()
        with self._session_factory() as session:
            existing = self._find_wishlist(session, user_id, item)
            params = {
                "uid": user_id, "pid": item.get("product_id"), "name": item["item_name"],
                "target": item.get("target_price"), "image": item.get("item_image_url"),
                "store": item.get("store_name"), "category": item.get("category"),
                "add_price": item.get("price_at_add"), "current": item.get("current_price"),
                "notify": 1 if item.get("notify_on_drop") else 0, "now": now,
            }
            if existing:
                wishlist_id = int(existing.id)
                params["id"] = wishlist_id
                session.execute(text(
                    "UPDATE wishlist_items SET item_name=:name,target_price=:target,item_image_url=:image,"
                    "store_name=:store,category=:category,price_at_add=:add_price,current_price=:current,"
                    "notify_on_drop=:notify WHERE id=:id AND user_id=:uid"
                ), params)
            else:
                session.execute(text(
                    "INSERT INTO wishlist_items "
                    "(user_id,product_id,item_name,target_price,item_image_url,store_name,category,"
                    "price_at_add,current_price,added_at,notify_on_drop) "
                    "VALUES (:uid,:pid,:name,:target,:image,:store,:category,:add_price,:current,:now,:notify)"
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
