"""Dedicated SQLite storage for OPINET station and fuel-price snapshots.

This database is intentionally separate from the mart/catalog database.  Both
crawler-admin and web-api use this module so station identity, price history and
query semantics cannot drift between services.
"""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def _default_db_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "opinet.db"


def resolve_opinet_db_path(path: str | Path | None = None) -> Path:
    raw = path or os.getenv("OPINET_DB_PATH") or _default_db_path()
    resolved = Path(raw).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec="seconds")
    if value:
        return str(value)
    return datetime.utcnow().isoformat(timespec="seconds")


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class FuelStore:
    """Small shared store for OPINET snapshots and current-price queries."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = resolve_opinet_db_path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fuel_stations (
                    station_code TEXT PRIMARY KEY,
                    brand TEXT NOT NULL,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL,
                    sido TEXT NOT NULL DEFAULT '',
                    sigungu TEXT NOT NULL DEFAULT '',
                    lat REAL,
                    lng REAL,
                    has_self_service INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_fuel_stations_region
                    ON fuel_stations(sido, sigungu);
                CREATE INDEX IF NOT EXISTS ix_fuel_stations_location
                    ON fuel_stations(lat, lng);

                CREATE TABLE IF NOT EXISTS fuel_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_code TEXT NOT NULL,
                    fuel_type TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'opinet',
                    FOREIGN KEY(station_code) REFERENCES fuel_stations(station_code)
                        ON DELETE CASCADE,
                    UNIQUE(station_code, fuel_type, observed_at, source)
                );
                CREATE INDEX IF NOT EXISTS ix_fuel_prices_station_observed
                    ON fuel_prices(station_code, observed_at);
                CREATE INDEX IF NOT EXISTS ix_fuel_prices_type_price
                    ON fuel_prices(fuel_type, price);
                """
            )

    def save_snapshot(self, records: Iterable[Any]) -> dict[str, int]:
        station_count = 0
        price_count = 0
        with self._connect() as conn:
            for record in records:
                station_code = str(_value(record, "station_code", "") or "").strip()
                name = str(_value(record, "name", "") or "").strip()
                if not station_code or not name:
                    continue

                conn.execute(
                    """
                    INSERT INTO fuel_stations (
                        station_code, brand, name, address, sido, sigungu,
                        lat, lng, has_self_service, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(station_code) DO UPDATE SET
                        brand = excluded.brand,
                        name = excluded.name,
                        address = excluded.address,
                        sido = excluded.sido,
                        sigungu = excluded.sigungu,
                        lat = COALESCE(excluded.lat, fuel_stations.lat),
                        lng = COALESCE(excluded.lng, fuel_stations.lng),
                        has_self_service = excluded.has_self_service,
                        updated_at = excluded.updated_at
                    """,
                    (
                        station_code,
                        str(_value(record, "brand", "기타") or "기타"),
                        name,
                        str(_value(record, "address", "") or ""),
                        str(_value(record, "sido", "") or ""),
                        str(_value(record, "sigungu", "") or ""),
                        _value(record, "lat"),
                        _value(record, "lng"),
                        1 if _value(record, "has_self_service", False) else 0,
                        _iso(_value(record, "updated_at")),
                    ),
                )
                station_count += 1

                for price in _value(record, "prices", []) or []:
                    fuel_type = str(_value(price, "fuel_type", "") or "").strip()
                    amount = _value(price, "price")
                    if not fuel_type or amount is None:
                        continue
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO fuel_prices (
                            station_code, fuel_type, price, observed_at, source
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            station_code,
                            fuel_type,
                            int(amount),
                            _iso(_value(price, "observed_at")),
                            str(_value(price, "source", "opinet") or "opinet"),
                        ),
                    )
                    if cursor.rowcount > 0:
                        price_count += 1
            conn.commit()
        return {"stations": station_count, "prices": price_count}

    def current_prices(
        self,
        *,
        fuel_type: str = "gasoline",
        lat: float | None = None,
        lng: float | None = None,
        radius_m: int | None = None,
        sido: str | None = None,
        sigungu: str | None = None,
        sort_by: str = "price_asc",
        limit: int = 200,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        clauses: list[str] = []
        params: list[Any] = []
        if sido:
            clauses.append("s.sido = ?")
            params.append(sido)
        if sigungu:
            clauses.append("s.sigungu = ?")
            params.append(sigungu)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                WITH latest AS (
                    SELECT station_code, fuel_type, MAX(observed_at) AS observed_at
                    FROM fuel_prices
                    GROUP BY station_code, fuel_type
                )
                SELECT
                    s.station_code, s.brand, s.name, s.address, s.sido, s.sigungu,
                    s.lat, s.lng, s.has_self_service, s.updated_at,
                    p.fuel_type, p.price, p.observed_at
                FROM fuel_stations s
                LEFT JOIN latest l ON l.station_code = s.station_code
                LEFT JOIN fuel_prices p
                  ON p.station_code = l.station_code
                 AND p.fuel_type = l.fuel_type
                 AND p.observed_at = l.observed_at
                {where}
                ORDER BY s.name, p.fuel_type
                """,
                params,
            ).fetchall()

        stations: dict[str, dict] = {}
        for row in rows:
            code = row["station_code"]
            item = stations.setdefault(
                code,
                {
                    "id": code,
                    "station_code": code,
                    "name": row["name"],
                    "addr": row["address"],
                    "address": row["address"],
                    "brand": row["brand"],
                    "sido": row["sido"],
                    "sigungu": row["sigungu"],
                    "lat": row["lat"],
                    "lng": row["lng"],
                    "self_service": bool(row["has_self_service"]),
                    "updated_at": row["updated_at"],
                    "gasoline": None,
                    "premium": None,
                    "diesel": None,
                    "kerosene": None,
                    "lpg": None,
                },
            )
            if row["fuel_type"]:
                item[row["fuel_type"]] = row["price"]

        result: list[dict] = []
        for item in stations.values():
            if item.get(fuel_type) is None:
                continue
            if lat is not None and lng is not None:
                if item["lat"] is None or item["lng"] is None:
                    if radius_m is not None:
                        continue
                else:
                    distance_m = _haversine_m(lat, lng, item["lat"], item["lng"])
                    if radius_m is not None and distance_m > radius_m:
                        continue
                    item["distance_m"] = round(distance_m)
                    item["distance"] = round(distance_m / 1000, 2)
            result.append(item)

        if sort_by == "distance":
            result.sort(key=lambda row: row.get("distance_m", float("inf")))
        else:
            result.sort(key=lambda row: (row.get(fuel_type) is None, row.get(fuel_type) or 0))
        return result[:limit]


__all__ = ["FuelStore", "resolve_opinet_db_path"]
