"""Persistence helpers for authenticated cart, wishlist and activity features."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, bindparam, text


class AccountFeatureStoreError(RuntimeError):
    pass


class AccountFeatureStore:
    def __init__(self, storage):
        self.storage = storage
        self._session_factory = getattr(storage, "SessionLocal", None)
        if self._session_factory is None:
            raise AccountFeatureStoreError("main DB session factory is unavailable")

    @staticmethod
    def _iso(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    @classmethod
    def _cart_dict(cls, row) -> dict:
        data = dict(row)
        data["cart_id"] = data["id"]
        data["added_at"] = cls._iso(data.get("added_at"))
        data["expires_at"] = cls._iso(data.get("expires_at"))
        return data

    @classmethod
    def _wishlist_dict(cls, row) -> dict:
        data = dict(row)
        data["added_at"] = cls._iso(data.get("added_at"))
        if data.get("live_current_price") is not None:
            data["current_price"] = data.pop("live_current_price")
        else:
            data.pop("live_current_price", None)
        return data

    def _require_product(self, session, product_id: int | None) -> None:
        if product_id is None:
            return
        exists = session.execute(
            text("SELECT id FROM products WHERE id = :product_id"),
            {"product_id": product_id},
        ).first()
        if exists is None:
            raise AccountFeatureStoreError("product_not_found")

    def list_cart(self, user_id: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT c.id, c.user_id, c.product_id, c.item_name, c.item_price, "
                    "c.item_image_url, c.store_name, c.source_url, c.original_price, "
                    "c.discount_rate, c.category, c.quantity, c.added_at, c.expires_at, "
                    "p.unit AS unit "
                    "FROM cart_items c LEFT JOIN products p ON p.id = c.product_id "
                    "WHERE c.user_id = :user_id ORDER BY c.added_at DESC, c.id DESC"
                ),
                {"user_id": user_id},
            ).mappings().all()
            return [self._cart_dict(row) for row in rows]

    def _find_cart_item(self, session, user_id: int, item: dict):
        product_id = item.get("product_id")
        store_name = item.get("store_name") or ""
        if product_id is not None:
            return session.execute(
                text(
                    "SELECT id, quantity FROM cart_items WHERE user_id = :user_id "
                    "AND product_id = :product_id AND COALESCE(store_name, '') = :store_name "
                    "ORDER BY id LIMIT 1"
                ),
                {"user_id": user_id, "product_id": product_id, "store_name": store_name},
            ).mappings().first()
        return session.execute(
            text(
                "SELECT id, quantity FROM cart_items WHERE user_id = :user_id "
                "AND product_id IS NULL AND item_name = :item_name "
                "AND COALESCE(store_name, '') = :store_name "
                "AND COALESCE(source_url, '') = :source_url ORDER BY id LIMIT 1"
            ),
            {
                "user_id": user_id,
                "item_name": item["item_name"],
                "store_name": store_name,
                "source_url": item.get("source_url") or "",
            },
        ).mappings().first()

    def _upsert_cart(self, session, user_id: int, item: dict, *, merge_quantity: bool) -> int:
        product_id = item.get("product_id")
        self._require_product(session, product_id)
        existing = self._find_cart_item(session, user_id, item)
        quantity = max(1, int(item.get("quantity") or 1))
        if existing:
            next_quantity = int(existing["quantity"] or 1) + quantity if merge_quantity else quantity
            session.execute(
                text(
                    "UPDATE cart_items SET item_name=:item_name, item_price=:item_price, "
                    "item_image_url=:item_image_url, store_name=:store_name, source_url=:source_url, "
                    "original_price=:original_price, discount_rate=:discount_rate, category=:category, "
                    "quantity=:quantity WHERE id=:id AND user_id=:user_id"
                ),
                {
                    **item,
                    "item_image_url": item.get("item_image_url"),
                    "store_name": item.get("store_name"),
                    "source_url": item.get("source_url"),
                    "original_price": item.get("original_price"),
                    "discount_rate": item.get("discount_rate"),
                    "category": item.get("category"),
                    "quantity": next_quantity,
                    "id": existing["id"],
                    "user_id": user_id,
                },
            )
            return int(existing["id"])

        session.execute(
            text(
                "INSERT INTO cart_items "
                "(user_id, product_id, item_name, item_price, item_image_url, store_name, source_url, "
                "original_price, discount_rate, category, quantity, added_at) "
                "VALUES (:user_id, :product_id, :item_name, :item_price, :item_image_url, :store_name, "
                ":source_url, :original_price, :discount_rate, :category, :quantity, :added_at)"
            ),
            {
                "user_id": user_id,
                "product_id": product_id,
                "item_name": item["item_name"],
                "item_price": item["item_price"],
                "item_image_url": item.get("item_image_url"),
                "store_name": item.get("store_name"),
                "source_url": item.get("source_url"),
                "original_price": item.get("original_price"),
                "discount_rate": item.get("discount_rate"),
                "category": item.get("category"),
                "quantity": quantity,
                "added_at": datetime.utcnow(),
            },
        )
        row = self._find_cart_item(session, user_id, item)
        if row is None:
            raise AccountFeatureStoreError("cart_insert_failed")
        return int(row["id"])

    def add_cart(self, user_id: int, item: dict) -> dict:
        with self._session_factory() as session:
            cart_id = self._upsert_cart(session, user_id, item, merge_quantity=True)
            session.commit()
        return next(row for row in self.list_cart(user_id) if int(row["id"]) == cart_id)

    def merge_cart(self, user_id: int, items: list[dict]) -> list[dict]:
        with self._session_factory() as session:
            for item in items:
                self._upsert_cart(session, user_id, item, merge_quantity=True)
            session.commit()
        return self.list_cart(user_id)

    def update_cart_quantity(self, user_id: int, cart_id: int, quantity: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text("UPDATE cart_items SET quantity=:quantity WHERE id=:id AND user_id=:user_id"),
                {"quantity": quantity, "id": cart_id, "user_id": user_id},
            )
            session.commit()
            return result.rowcount > 0

    def delete_cart_item(self, user_id: int, cart_id: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM cart_items WHERE id=:id AND user_id=:user_id"),
                {"id": cart_id, "user_id": user_id},
            )
            session.commit()
            return result.rowcount > 0

    def clear_cart(self, user_id: int) -> int:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM cart_items WHERE user_id=:user_id"),
                {"user_id": user_id},
            )
            session.commit()
            return int(result.rowcount or 0)

    def list_wishlist(self, user_id: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT w.id, w.user_id, w.product_id, w.item_name, w.target_price, "
                    "w.item_image_url, w.store_name, w.category, w.price_at_add, w.current_price, "
                    "w.added_at, w.notify_on_drop, "
                    "COALESCE(" 
                    "(SELECT dh.price FROM discount_history dh WHERE dh.product_id=w.product_id "
                    " ORDER BY dh.crawled_at DESC LIMIT 1), "
                    "(SELECT bp.price FROM baseline_prices bp WHERE bp.product_id=w.product_id "
                    " ORDER BY bp.recorded_at DESC LIMIT 1), w.current_price) AS live_current_price "
                    "FROM wishlist_items w WHERE w.user_id=:user_id "
                    "ORDER BY w.added_at DESC, w.id DESC"
                ),
                {"user_id": user_id},
            ).mappings().all()
            return [self._wishlist_dict(row) for row in rows]

    def _find_wishlist_item(self, session, user_id: int, item: dict):
        product_id = item.get("product_id")
        if product_id is not None:
            return session.execute(
                text(
                    "SELECT id FROM wishlist_items WHERE user_id=:user_id "
                    "AND product_id=:product_id ORDER BY id LIMIT 1"
                ),
                {"user_id": user_id, "product_id": product_id},
            ).mappings().first()
        return session.execute(
            text(
                "SELECT id FROM wishlist_items WHERE user_id=:user_id AND product_id IS NULL "
                "AND item_name=:item_name AND COALESCE(store_name, '')=:store_name ORDER BY id LIMIT 1"
            ),
            {
                "user_id": user_id,
                "item_name": item["item_name"],
                "store_name": item.get("store_name") or "",
            },
        ).mappings().first()

    def add_wishlist(self, user_id: int, item: dict) -> dict:
        with self._session_factory() as session:
            self._require_product(session, item.get("product_id"))
            existing = self._find_wishlist_item(session, user_id, item)
            if existing:
                wishlist_id = int(existing["id"])
                session.execute(
                    text(
                        "UPDATE wishlist_items SET item_name=:item_name, item_image_url=:item_image_url, "
                        "store_name=:store_name, category=:category, current_price=:current_price "
                        "WHERE id=:id AND user_id=:user_id"
                    ),
                    {
                        "item_name": item["item_name"],
                        "item_image_url": item.get("item_image_url"),
                        "store_name": item.get("store_name"),
                        "category": item.get("category"),
                        "current_price": item.get("current_price"),
                        "id": wishlist_id,
                        "user_id": user_id,
                    },
                )
            else:
                session.execute(
                    text(
                        "INSERT INTO wishlist_items "
                        "(user_id, product_id, item_name, target_price, item_image_url, store_name, category, "
                        "price_at_add, current_price, added_at, notify_on_drop) "
                        "VALUES (:user_id, :product_id, :item_name, :target_price, :item_image_url, :store_name, "
                        ":category, :price_at_add, :current_price, :added_at, :notify_on_drop)"
                    ),
                    {
                        "user_id": user_id,
                        "product_id": item.get("product_id"),
                        "item_name": item["item_name"],
                        "target_price": item.get("target_price"),
                        "item_image_url": item.get("item_image_url"),
                        "store_name": item.get("store_name"),
                        "category": item.get("category"),
                        "price_at_add": item.get("price_at_add"),
                        "current_price": item.get("current_price"),
                        "added_at": datetime.utcnow(),
                        "notify_on_drop": bool(item.get("notify_on_drop", False)),
                    },
                )
                row = self._find_wishlist_item(session, user_id, item)
                if row is None:
                    raise AccountFeatureStoreError("wishlist_insert_failed")
                wishlist_id = int(row["id"])
            session.commit()
        return next(row for row in self.list_wishlist(user_id) if int(row["id"]) == wishlist_id)

    def update_wishlist(self, user_id: int, wishlist_id: int, target_price: float | None, notify: bool) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text(
                    "UPDATE wishlist_items SET target_price=:target_price, notify_on_drop=:notify "
                    "WHERE id=:id AND user_id=:user_id"
                ),
                {
                    "target_price": target_price,
                    "notify": bool(notify),
                    "id": wishlist_id,
                    "user_id": user_id,
                },
            )
            session.commit()
            return result.rowcount > 0

    def delete_wishlist(self, user_id: int, wishlist_id: int) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                text("DELETE FROM wishlist_items WHERE id=:id AND user_id=:user_id"),
                {"id": wishlist_id, "user_id": user_id},
            )
            session.commit()
            return result.rowcount > 0

    def track_activity(
        self,
        user_id: int,
        activity_type: str,
        target_type: str | None,
        target_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> int:
        statement = text(
            "INSERT INTO user_activities "
            "(user_id, activity_type, target_type, target_id, metadata, created_at) "
            "VALUES (:user_id, :activity_type, :target_type, :target_id, :metadata, :created_at)"
        ).bindparams(bindparam("metadata", type_=JSON))
        with self._session_factory() as session:
            session.execute(
                statement,
                {
                    "user_id": user_id,
                    "activity_type": activity_type,
                    "target_type": target_type,
                    "target_id": target_id,
                    "metadata": metadata or {},
                    "created_at": datetime.utcnow(),
                },
            )
            session.commit()
            row = session.execute(
                text(
                    "SELECT id FROM user_activities WHERE user_id=:user_id "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"user_id": user_id},
            ).first()
            if row is None:
                raise AccountFeatureStoreError("activity_insert_failed")
            return int(row.id)

    def list_activity(self, user_id: int, page: int, per_page: int) -> tuple[list[dict], int]:
        offset = (page - 1) * per_page
        with self._session_factory() as session:
            total = int(session.execute(
                text("SELECT COUNT(*) FROM user_activities WHERE user_id=:user_id"),
                {"user_id": user_id},
            ).scalar() or 0)
            rows = session.execute(
                text(
                    "SELECT id, activity_type, target_type, target_id, metadata, created_at "
                    "FROM user_activities WHERE user_id=:user_id "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
                ),
                {"user_id": user_id, "limit": per_page, "offset": offset},
            ).mappings().all()
            data = []
            for row in rows:
                item = dict(row)
                item["created_at"] = self._iso(item.get("created_at"))
                data.append(item)
            return data, total
