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

    # ── Fuel 주유소 조회 ────────────────────────────────────────────────────

    def has_fuel_tables(self) -> bool:
        """fuel_station 테이블이 존재하는지 확인."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fuel_station'"
        )
        return cur.fetchone() is not None

    def fuel_stations(
        self,
        sido: Optional[str] = None,
        sigungu: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> list[dict]:
        """주유소 목록 조회 (필터: sido, sigungu, brand)."""
        conn = self._get_conn()
        cur = conn.cursor()
        conditions: list[str] = []
        params: list = []
        if sido:
            conditions.append("sido = ?")
            params.append(sido)
        if sigungu:
            conditions.append("sigungu = ?")
            params.append(sigungu)
        if brand:
            conditions.append("brand = ?")
            params.append(brand)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"SELECT id, brand, name, address, sido, sigungu, lat, lng, "
            f"self_service, has_car_wash, has_convenience, opinet_id "
            f"FROM fuel_station {where} ORDER BY name",
            params,
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "id": r["id"], "brand": r["brand"], "name": r["name"],
                "address": r["address"], "sido": r["sido"], "sigungu": r["sigungu"],
                "lat": r["lat"], "lng": r["lng"],
                "self_service": bool(r["self_service"]),
                "has_car_wash": bool(r["has_car_wash"]),
                "has_convenience": bool(r["has_convenience"]),
                "opinet_id": r["opinet_id"],
            })
        return rows

    def fuel_station_by_id(self, station_id: str) -> Optional[dict]:
        """단일 주유소 조회."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, brand, name, address, sido, sigungu, lat, lng, "
            "self_service, has_car_wash, has_convenience, opinet_id "
            "FROM fuel_station WHERE id = ?",
            (station_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return {
            "id": r["id"], "brand": r["brand"], "name": r["name"],
            "address": r["address"], "sido": r["sido"], "sigungu": r["sigungu"],
            "lat": r["lat"], "lng": r["lng"],
            "self_service": bool(r["self_service"]),
            "has_car_wash": bool(r["has_car_wash"]),
            "has_convenience": bool(r["has_convenience"]),
            "opinet_id": r["opinet_id"],
        }

    def fuel_prices_for_station(self, station_id: str) -> list[dict]:
        """주유소의 최신 가격 목록."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT station_id, fuel_kind, price, observed_at "
            "FROM fuel_price_latest WHERE station_id = ?",
            (station_id,),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "fuel_kind": r["fuel_kind"],
                "price": r["price"],
                "observed_at": r["observed_at"],
            })
        return rows

    def fuel_prices_by_kind(self, fuel_kind: str) -> list[dict]:
        """전체 주유소의 특정 유종 최신 가격."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT station_id, fuel_kind, price, observed_at "
            "FROM fuel_price_latest WHERE fuel_kind = ?",
            (fuel_kind,),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "station_id": r["station_id"],
                "fuel_kind": r["fuel_kind"],
                "price": r["price"],
                "observed_at": r["observed_at"],
            })
        return rows

    def fuel_grade(self, sido: str, sigungu: str, fuel_kind: str) -> Optional[dict]:
        """특정 지역·유종 가격 등급 조회."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT sido, sigungu, fuel_kind, sample_size, p25, p50, p75, "
            "computed_at, sufficient "
            "FROM fuel_price_grade WHERE sido = ? AND sigungu = ? AND fuel_kind = ?",
            (sido, sigungu, fuel_kind),
        )
        r = cur.fetchone()
        if not r:
            return None
        return {
            "sido": r["sido"], "sigungu": r["sigungu"], "fuel_kind": r["fuel_kind"],
            "sample_size": r["sample_size"],
            "p25": r["p25"], "p50": r["p50"], "p75": r["p75"],
            "computed_at": r["computed_at"],
            "sufficient": bool(r["sufficient"]),
        }

    def fuel_sido_list(self) -> list[str]:
        """저장된 주유소의 시도 목록 (중복 제거, 정렬)."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT sido FROM fuel_station ORDER BY sido")
        return [r["sido"] for r in cur.fetchall()]

    def fuel_sigungu_list(self, sido: Optional[str] = None) -> list[str]:
        """저장된 주유소의 시군구 목록."""
        conn = self._get_conn()
        cur = conn.cursor()
        if sido:
            cur.execute(
                "SELECT DISTINCT sigungu FROM fuel_station WHERE sido = ? ORDER BY sigungu",
                (sido,),
            )
        else:
            cur.execute("SELECT DISTINCT sigungu FROM fuel_station ORDER BY sigungu")
        return [r["sigungu"] for r in cur.fetchall()]

    def fuel_brand_list(self) -> list[str]:
        """저장된 주유소의 브랜드 목록 (중복 제거, 정렬)."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT brand FROM fuel_station ORDER BY brand")
        return [r["brand"] for r in cur.fetchall()]

    # ── 미분류 raw 레코드 ───────────────────────────────────────────────────────

    def pending_raw_records(self) -> list[dict]:
        """matching miss인 raw_crawl_record 목록을 반환한다.

        raw_crawl_record 테이블이 없거나 비어 있으면 빈 리스트를 반환해
        기존 스냅샷과 하위 호환성을 유지한다.

        반환 항목 구조:
            id, raw_title, raw_price (int|None), mart (str|None), captured_at (str|None)
        """
        conn = self._get_conn()
        cur = conn.cursor()
        # 테이블 존재 여부 먼저 확인
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_crawl_record'"
        )
        if cur.fetchone() is None:
            return []
        cur.execute(
            "SELECT id, raw_title, raw_price, mart, captured_at "
            "FROM raw_crawl_record ORDER BY captured_at DESC"
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "id": r["id"],
                "raw_title": r["raw_title"],
                "raw_price": r["raw_price"],
                "mart": r["mart"],
                "captured_at": r["captured_at"],
            })
        return rows
