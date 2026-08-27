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

    def health(self) -> dict:
        with self.connection() as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            revision = built_at = None
            if self._table(connection, "snapshot_meta"):
                row = connection.execute(
                    "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
                ).fetchone()
                if row:
                    revision, built_at = row
            return {
                "ok": bool(result and result[0] == "ok"),
                "path": str(self.path),
                "revision": revision,
                "built_at": built_at,
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
        if self._table(connection, "discount_history"):
            for row in connection.execute(
                "SELECT source, price FROM discount_history WHERE product_id=? "
                "ORDER BY crawled_at DESC, id DESC",
                (product_id,),
            ):
                source = str(row["source"] or "")
                source = "lotte" if source == "lottemart" else source
                if source and source not in stores and row["price"] is not None:
                    stores[source] = float(row["price"])
        if self._table(connection, "baseline_prices"):
            for row in connection.execute(
                "SELECT source, price FROM baseline_prices WHERE product_id=? "
                "ORDER BY recorded_at DESC, id DESC",
                (product_id,),
            ):
                source = str(row["source"] or "")
                source = "lotte" if source == "lottemart" else source
                if source and source not in stores and row["price"] is not None:
                    stores[source] = float(row["price"])
        return stores

    def _product(self, connection, row) -> dict:
        product = dict(row)
        product_id = int(product["id"])
        category_id, category_name, icon = self._category(connection, product)
        latest_discount = self._latest(connection, "discount_history", product_id, "crawled_at")
        latest_baseline = self._latest(connection, "baseline_prices", product_id, "recorded_at")
        observations = self._observations(connection, product_id)
        values = [value for value, _, _ in observations]
        current_value = latest_discount.get("price")
        if current_value is None:
            current_value = latest_baseline.get("price")
        current = round(float(current_value)) if current_value is not None else 0
        avg = round(sum(values) / len(values)) if values else current
        low = round(min(values)) if values else current
        high = round(max(values)) if values else current
        ratio = current / avg if current and avg else 1
        tier = "ultra" if ratio <= .70 else "great" if ratio <= .85 else "good" if ratio <= 1.05 else "wait"

        raw = _json(latest_discount.get("raw_data"), {}) if latest_discount else {}
        attrs = _json(product.get("attributes"), {})
        image = product.get("image_url") or raw.get("image_url") or ""
        original = latest_discount.get("original_price")
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
            "source": latest_discount.get("source") if latest_discount else None,
            "source_url": latest_discount.get("source_url") or raw.get("source_url") or "",
            "source_title": raw.get("source_title") or raw.get("product_name") or "",
            "original_price": original,
            "discount_pct": discount_pct,
            "discount_rate": latest_discount.get("discount_rate") if latest_discount else None,
            "stores": stores,
            "stats": {
                "dataDays": len(days), "records": len(values),
                "confidence": [low, high], "outliers": 0,
                "avgDiscount": 0, "discFreq": 0,
            },
        }

    def product_exists(self, product_id: int) -> bool:
        with self.connection() as connection:
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
            if not categories:
                categories = [
                    {"id": row["id"], "parent_id": row["parent_id"], "name_ko": row["name"]}
                    for row in connection.execute(
                        "SELECT id, parent_id, name FROM categories ORDER BY sort_order, name"
                    )
                ]
                count_column = "category_id"
            else:
                count_column = "unified_category_id"

            counts = {
                row[0]: int(row[1])
                for row in connection.execute(
                    f"SELECT {count_column}, COUNT(*) FROM products "
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
            if not categories:
                return [], 0, category_id
            by_id = {row["id"]: row for row in categories}
            children = [row for row in categories if row.get("parent_id") == category_id]
            all_ids = self._descendants(categories, category_id)
            placeholders = ",".join("?" for _ in all_ids)
            total = connection.execute(
                f"SELECT COUNT(*) FROM products WHERE is_active=1 AND unified_category_id IN ({placeholders})",
                tuple(all_ids),
            ).fetchone()[0] if all_ids else 0

            result = []
            for child in children:
                ids = self._descendants(categories, child["id"])
                marks = ",".join("?" for _ in ids)
                count = connection.execute(
                    f"SELECT COUNT(*) FROM products WHERE is_active=1 AND unified_category_id IN ({marks})",
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
            sql = (
                "SELECT d.*, p.name AS product_name, p.unit AS product_unit "
                "FROM discount_history d "
                "JOIN products p ON p.id=d.product_id AND p.is_active=1 "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM discount_history newer "
                "WHERE newer.product_id=d.product_id AND newer.source=d.source "
                "AND (newer.crawled_at > d.crawled_at "
                "OR (newer.crawled_at = d.crawled_at AND newer.id > d.id))"
                ") "
                "AND (d.valid_to IS NULL OR date(d.valid_to) IS NULL OR date(d.valid_to) >= date(?)) "
            )
            params: list[object] = [datetime.utcnow().date().isoformat()]
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