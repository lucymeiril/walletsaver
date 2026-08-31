"""Web-api-owned runtime storage split across multiple SQLite files."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from services.account_database import AccountDatabase
from services.catalog_storage import PublicCatalogStore
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

    def add_price_alert(self, user_id: str | int, product_id: str | int, target_price: int) -> dict:
        uid = int(user_id)
        if not self.catalog.product_exists(product_id):
            raise ValueError("product not found")
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id FROM price_alerts "
                    "WHERE user_id=:user_id AND product_id=:product_id"
                ),
                {"user_id": uid, "product_id": product_id},
            ).first()
            if row:
                alert_id = int(row.id)
                session.execute(
                    text(
                        "UPDATE price_alerts SET target_price=:target_price, is_active=1 "
                        "WHERE id=:id"
                    ),
                    {"target_price": target_price, "id": alert_id},
                )
            else:
                session.execute(
                    text(
                        "INSERT INTO price_alerts "
                        "(user_id, product_id, target_price, is_active, created_at) "
                        "VALUES (:user_id, :product_id, :target_price, 1, :created_at)"
                    ),
                    {
                        "user_id": uid,
                        "product_id": product_id,
                        "target_price": target_price,
                        "created_at": now,
                    },
                )
                alert_id = int(session.execute(
                    text(
                        "SELECT id FROM price_alerts "
                        "WHERE user_id=:user_id AND product_id=:product_id"
                    ),
                    {"user_id": uid, "product_id": product_id},
                ).scalar_one())
            session.commit()
        return {
            "id": alert_id,
            "product_id": product_id,
            "target_price": target_price,
            "status": "active",
        }

    def get_user_alerts(self, user_id: str | int) -> list[dict]:
        uid = int(user_id)
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, product_id, target_price, is_active, created_at "
                    "FROM price_alerts WHERE user_id=:user_id AND is_active=1 "
                    "ORDER BY created_at DESC, id DESC"
                ),
                {"user_id": uid},
            ).mappings().all()
        result = []
        for row in rows:
            catalog_id = str(row["product_id"])
            product = (
                self.catalog.get_normalized_product_detail(catalog_id)
                if self.catalog.has_normalized_catalog()
                else self.catalog.get_product_detail(int(catalog_id))
            )
            current_price = (product or {}).get("cur") or (product or {}).get("price") or 0
            result.append({
                "id": int(row["id"]),
                "product_id": catalog_id,
                "product_name": product.get("name", "") if product else "",
                "target_price": row["target_price"],
                "current_price": current_price,
                "is_triggered": bool(current_price and current_price <= row["target_price"]),
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
