"""Read-only gateway to public_snapshot.sqlite."""
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DEFAULT_DB = (
    Path(__file__).parent.parent.parent.parent.parent
    / ".walletsavior"
    / "public_snapshot.sqlite"
)


def get_db_path() -> Path:
    env = os.environ.get("WALLETSAVIOR_PUBLIC_DB")
    return Path(env) if env else _DEFAULT_DB


def get_conn() -> sqlite3.Connection:
    db = get_db_path()
    if not db.exists():
        raise FileNotFoundError(f"Snapshot not found: {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class CanonicalProductRow:
    id: str
    brand: Optional[str]
    name_core: str
    pack_quantity: Optional[float]
    pack_unit: Optional[str]
    category_id: Optional[str]
    representative_image_url: Optional[str]
    created_at: Optional[str]


@dataclass
class PriceGradeRow:
    canonical_id: str
    window_months: int
    sample_size: int
    p10: Optional[float]
    p25: Optional[float]
    p50: Optional[float]
    p75: Optional[float]
    computed_at: Optional[str]
    sufficient: bool


@dataclass
class CategoryNodeRow:
    id: str
    parent_id: Optional[str]
    name_kr: str
    name_slug: str
    level: int
    path: str


@dataclass
class MartSkuAliasRow:
    id: str
    canonical_id: str
    mart: str
    mart_item_id: Optional[str]
    mart_item_name_raw: Optional[str]
    source_url: Optional[str]
    last_seen_at: Optional[str]


class SnapshotRepo:
    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        self._conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        return get_conn()

    def all_categories(self) -> list[CategoryNodeRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, parent_id, name_kr, name_slug, level, path "
            "FROM category_node ORDER BY level, id"
        )
        rows = []
        for r in cur.fetchall():
            rows.append(CategoryNodeRow(
                id=r["id"], parent_id=r["parent_id"], name_kr=r["name_kr"],
                name_slug=r["name_slug"], level=r["level"], path=r["path"],
            ))
        return rows

    def all_products(self) -> list[CanonicalProductRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, brand, name_core, pack_quantity, pack_unit, "
            "category_id, representative_image_url, created_at FROM canonical_product"
        )
        rows = []
        for r in cur.fetchall():
            rows.append(CanonicalProductRow(
                id=r["id"], brand=r["brand"], name_core=r["name_core"],
                pack_quantity=r["pack_quantity"], pack_unit=r["pack_unit"],
                category_id=r["category_id"],
                representative_image_url=r["representative_image_url"],
                created_at=r["created_at"],
            ))
        return rows

    def product_by_id(self, canonical_id: str) -> Optional[CanonicalProductRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, brand, name_core, pack_quantity, pack_unit, "
            "category_id, representative_image_url, created_at "
            "FROM canonical_product WHERE id = ?",
            (canonical_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return CanonicalProductRow(
            id=r["id"], brand=r["brand"], name_core=r["name_core"],
            pack_quantity=r["pack_quantity"], pack_unit=r["pack_unit"],
            category_id=r["category_id"],
            representative_image_url=r["representative_image_url"],
            created_at=r["created_at"],
        )

    def grade_by_id(self, canonical_id: str) -> Optional[PriceGradeRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT canonical_id, window_months, sample_size, p10, p25, p50, p75, "
            "computed_at, sufficient FROM price_grade WHERE canonical_id = ?",
            (canonical_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return PriceGradeRow(
            canonical_id=r["canonical_id"], window_months=r["window_months"],
            sample_size=r["sample_size"], p10=r["p10"], p25=r["p25"],
            p50=r["p50"], p75=r["p75"], computed_at=r["computed_at"],
            sufficient=bool(r["sufficient"]),
        )

    def all_grades(self) -> list[PriceGradeRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT canonical_id, window_months, sample_size, p10, p25, p50, p75, "
            "computed_at, sufficient FROM price_grade"
        )
        rows = []
        for r in cur.fetchall():
            rows.append(PriceGradeRow(
                canonical_id=r["canonical_id"], window_months=r["window_months"],
                sample_size=r["sample_size"], p10=r["p10"], p25=r["p25"],
                p50=r["p50"], p75=r["p75"], computed_at=r["computed_at"],
                sufficient=bool(r["sufficient"]),
            ))
        return rows

    def aliases_by_canonical(self, canonical_id: str) -> list[MartSkuAliasRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, canonical_id, mart, mart_item_id, mart_item_name_raw, "
            "source_url, last_seen_at FROM mart_sku_alias WHERE canonical_id = ?",
            (canonical_id,),
        )
        rows = []
        for r in cur.fetchall():
            rows.append(MartSkuAliasRow(
                id=r["id"], canonical_id=r["canonical_id"], mart=r["mart"],
                mart_item_id=r["mart_item_id"],
                mart_item_name_raw=r["mart_item_name_raw"],
                source_url=r["source_url"], last_seen_at=r["last_seen_at"],
            ))
        return rows

    def all_aliases(self) -> list[MartSkuAliasRow]:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, canonical_id, mart, mart_item_id, mart_item_name_raw, "
            "source_url, last_seen_at FROM mart_sku_alias"
        )
        rows = []
        for r in cur.fetchall():
            rows.append(MartSkuAliasRow(
                id=r["id"], canonical_id=r["canonical_id"], mart=r["mart"],
                mart_item_id=r["mart_item_id"],
                mart_item_name_raw=r["mart_item_name_raw"],
                source_url=r["source_url"], last_seen_at=r["last_seen_at"],
            ))
        return rows
