"""Read-only access to the replaceable public catalog SQLite snapshot."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


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
        clauses = ["p.is_active=1"]
        params: list[object] = []
        query = str(query or "").strip()
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(LOWER(p.canonical_name) LIKE LOWER(?) ESCAPE '\\' OR LOWER(COALESCE(p.brand,'')) LIKE LOWER(?) ESCAPE '\\')")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        category = str(category or "").strip()
        if category:
            clauses.append(
                "p.unified_category_id IN (WITH RECURSIVE tree(id) AS ("
                "SELECT id FROM unified_categories WHERE id=? UNION ALL "
                "SELECT c.id FROM unified_categories c JOIN tree t ON c.parent_id=t.id"
                ") SELECT id FROM tree)"
            )
            params.append(category)
        where = " AND ".join(clauses)
        with self.connection() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM normalized_canonical_products p WHERE {where}", tuple(params)
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT p.* FROM normalized_canonical_products p WHERE {where} "
                "ORDER BY p.canonical_name COLLATE NOCASE, p.public_product_id LIMIT ? OFFSET ?",
                (*params, per_page, (page - 1) * per_page),
            ).fetchall()
            return [self._normalized_product(connection, row, include_all=False) for row in rows], total

    def get_normalized_product_detail(self, public_product_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM normalized_canonical_products WHERE public_product_id=? AND is_active=1",
                (public_product_id,),
            ).fetchone()
            return self._normalized_product(connection, row, include_all=True) if row else None

    def _normalized_product(self, connection, product_row, *, include_all: bool) -> dict:
        product = dict(product_row)
        attributes = _json(product.get("attributes"), {})
        category = connection.execute(
            "SELECT name_ko FROM unified_categories WHERE id=?",
            (product.get("unified_category_id"),),
        ).fetchone()
        variants_payload: list[dict] = []
        comparable_offers: list[dict] = []
        variants = connection.execute(
            "SELECT * FROM normalized_product_variants WHERE public_product_id=? AND is_active=1 "
            "ORDER BY public_variant_id",
            (product["public_product_id"],),
        ).fetchall()
        for variant_row in variants:
            variant = dict(variant_row)
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
                    "AND offer_state='active' ORDER BY crawled_at DESC, public_offer_event_id DESC",
                    (listing["public_source_listing_id"],),
                ).fetchall()
                for event_row in events:
                    event = self._normalized_offer(dict(event_row), variant)
                    events_payload.append(event)
                    if event["comparable_price"] is not None:
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
                "bundle_count": int(variant.get("bundle_count") or 1),
                "display_unit": variant.get("display_unit"),
                "listings": listings_payload,
            })
        comparable_offers.sort(key=lambda row: (row["comparable_price"], row.get("source") or ""))
        best = comparable_offers[0] if comparable_offers else {}
        warning = bool(attributes.get("classification_warning"))
        return {
            "id": product["public_product_id"],
            "public_product_id": product["public_product_id"],
            "name": product["canonical_name"],
            "brand": product.get("brand") or "",
            "category_id": product.get("unified_category_id") or "",
            "cat": str(category["name_ko"] if category else ""),
            "img": product.get("primary_image_url") or "",
            "image_url": product.get("primary_image_url") or "",
            "cur": best.get("comparable_price") or 0,
            "price": best.get("comparable_price") or 0,
            "source": best.get("source") or "",
            "source_url": best.get("source_url") or "",
            "unit": (variants_payload[0].get("display_unit") if variants_payload else None) or "",
            "classification_warning": warning,
            "classification_label": "분류 확인 필요" if warning else None,
            "attributes": attributes,
            "variants": variants_payload if include_all else variants_payload[:3],
            "best_offer": best or None,
        }

    @staticmethod
    def _normalized_offer(event: dict, variant: dict) -> dict:
        comparable_types = {"final_price", "was_now_price", "bundle_price"}
        price = float(event["price"]) if event.get("price") is not None else None
        comparable = (
            price if price and price > 0
            and event.get("price_state") in {"normal", "sale_price_only"}
            and event.get("promotion_type") in comparable_types else None
        )
        quantity = float(variant["package_quantity"]) if variant.get("package_quantity") else None
        bundle = int(variant.get("bundle_count") or 1)
        total_quantity = quantity * bundle if quantity else None
        unit = str(variant.get("package_unit") or "").lower()
        per_100 = (round(comparable / total_quantity * 100) if comparable and total_quantity and unit in {"g", "ml"} else None)
        evidence = _json(event.get("raw_evidence"), {})
        condition = evidence.get("condition_text") or evidence.get("promotion_condition")
        return {
            "id": event["public_offer_event_id"],
            "price_state": event.get("price_state"),
            "promotion_type": event.get("promotion_type"),
            "total_price": price,
            "comparable_price": comparable,
            "original_price": event.get("original_price"),
            "discount_rate": event.get("discount_rate"),
            "total_quantity": total_quantity,
            "quantity_unit": unit or None,
            "bundle_count": bundle,
            "per_item": round(comparable / bundle) if comparable and bundle else None,
            "per_100g": per_100 if unit == "g" else None,
            "per_100ml": per_100 if unit == "ml" else None,
            "promotion_condition": condition,
            "minimum_quantity": evidence.get("minimum_quantity"),
            "membership_required": evidence.get("membership_required"),
            "coupon_required": evidence.get("coupon_required"),
            "event_name": event.get("event_name"),
            "crawled_at": event.get("crawled_at"),
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
            else:
                count_column = "unified_category_id"
                count_table = "normalized_canonical_products"

            counts = {
                row[0]: int(row[1])
                for row in connection.execute(
                    f"SELECT {count_column}, COUNT(*) FROM {count_table} "
                    f"WHERE is_active=1 AND {count_column} IS NOT NULL GROUP BY {count_column}"
                )
            }
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

    def get_category_children(self, category_id: str) -> tuple[list[dict], int, str]:
        with self.connection() as connection:
            categories = self._unified_rows(connection)
            if not self._normalized_schema(connection):
                return [], 0, category_id
            product_table = "normalized_canonical_products"
            by_id = {row["id"]: row for row in categories}
            children = [row for row in categories if row.get("parent_id") == category_id]
            all_ids = self._descendants(categories, category_id)
            placeholders = ",".join("?" for _ in all_ids)
            total = connection.execute(
                f"SELECT COUNT(*) FROM {product_table} WHERE is_active=1 AND unified_category_id IN ({placeholders})",
                tuple(all_ids),
            ).fetchone()[0] if all_ids else 0

            result = []
            for child in children:
                ids = self._descendants(categories, child["id"])
                marks = ",".join("?" for _ in ids)
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {product_table} WHERE is_active=1 AND unified_category_id IN ({marks})",
                    tuple(ids),
                ).fetchone()[0] if ids else 0
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
            "NOT EXISTS (SELECT 1 FROM normalized_offer_events newer "
            "WHERE newer.public_source_listing_id=e.public_source_listing_id "
            "AND newer.offer_state='active' AND (newer.crawled_at>e.crawled_at "
            "OR (newer.crawled_at=e.crawled_at "
            "AND newer.public_offer_event_id>e.public_offer_event_id)))",
        ]
        params: list[object] = []
        if store:
            clauses.append("l.source_name=?")
            params.append(store)
        params.append(max(1, min(int(limit), self.MAX_RESULT_LIMIT)))
        rows = connection.execute(
            "SELECT e.*, l.source_name, l.source_title, l.source_url, "
            "l.image_url AS listing_image_url, l.source_unit_text, "
            "v.public_variant_id, v.variant_name, v.package_quantity, "
            "v.package_unit, v.display_unit, v.bundle_count, "
            "p.canonical_name, p.primary_image_url, c.name_ko AS category_name "
            "FROM normalized_offer_events e "
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
            offer = self._normalized_offer(row, row)
            # Ambiguous or non-final promotion text is retained in the DB but
            # never ranked or presented as a calculable mart benefit.
            if offer["comparable_price"] is None:
                continue
            source = str(row.get("source_name") or "")
            grouped.setdefault(source, []).append({
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
