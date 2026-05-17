"""WalletSavior Phase F4 — 주유소 공개 스냅샷 빌더.

oneshot_public_db.py 보완 모듈 — 주유소 전용 테이블 3개를 public_snapshot.sqlite에 추가한다.
기존 4개 마트 테이블은 건드리지 않는다.

공개 스냅샷 추가 테이블:
    fuel_station         — 주유소 기본 정보 (brand/name/address/sido/sigungu/lat/lng)
    fuel_price_latest    — 주유소별 최신 가격 (station_id × fuel_kind)
    fuel_price_grade     — 시군구 × 유종별 분위수 등급 (P25/P50/P75)

공개 API:
    build_fuel_snapshot(stations, price_obs, snapshot_path) → dict
    seed_fuel_tables(conn, stations, price_obs)              → None
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.fuel_canonicalize import FuelCanonicalizationResult
from core.fuel_grading import compute_all_fuel_grades
from core.fuel_models import FuelKind, FuelPriceObservation, FuelStation


# ══════════════════════════════════════════════════════
# DDL
# ══════════════════════════════════════════════════════

_FUEL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS fuel_station (
        id              TEXT PRIMARY KEY,
        brand           TEXT NOT NULL,
        name            TEXT NOT NULL,
        address         TEXT NOT NULL,
        sido            TEXT NOT NULL,
        sigungu         TEXT NOT NULL,
        lat             REAL,
        lng             REAL,
        self_service    INTEGER NOT NULL DEFAULT 0,
        has_car_wash    INTEGER NOT NULL DEFAULT 0,
        has_convenience INTEGER NOT NULL DEFAULT 0,
        opinet_id       TEXT,
        created_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fuel_price_latest (
        station_id  TEXT NOT NULL,
        fuel_kind   TEXT NOT NULL,
        price       INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        PRIMARY KEY (station_id, fuel_kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fuel_price_grade (
        sido        TEXT NOT NULL,
        sigungu     TEXT NOT NULL,
        fuel_kind   TEXT NOT NULL,
        sample_size INTEGER NOT NULL,
        p25         REAL,
        p50         REAL,
        p75         REAL,
        computed_at TEXT NOT NULL,
        sufficient  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (sido, sigungu, fuel_kind)
    )
    """,
]


# ══════════════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════════════

def _latest_prices(
    observations: list[FuelPriceObservation],
) -> list[dict]:
    """station_id × fuel_kind 최신 가격만 추출."""
    latest: dict[tuple[str, str], dict] = {}
    for obs in sorted(observations, key=lambda o: o.observed_at):
        key = (obs.station_id, obs.fuel_kind.value)
        latest[key] = {
            "station_id": obs.station_id,
            "fuel_kind": obs.fuel_kind.value,
            "price": obs.price,
            "observed_at": obs.observed_at.isoformat(),
        }
    return list(latest.values())


def _grade_rows(
    observations: list[FuelPriceObservation],
    stations_by_id: dict[str, FuelStation],
) -> list[dict]:
    """fuel_price_grade 테이블 삽입 데이터 생성."""
    # (sido, sigungu, fuel_kind, price) 튜플 리스트 생성
    obs_tuples = []
    for obs in observations:
        station = stations_by_id.get(obs.station_id)
        if station is None:
            continue
        obs_tuples.append((station.sido, station.sigungu, obs.fuel_kind, float(obs.price)))

    grades = compute_all_fuel_grades(obs_tuples)
    computed_at = datetime.now().isoformat()

    rows = []
    for (sido, sigungu, fk_val), g in grades.items():
        rows.append({
            "sido": sido,
            "sigungu": sigungu,
            "fuel_kind": fk_val,
            "sample_size": g.sample_size,
            "p25": g.p25,
            "p50": g.p50,
            "p75": g.p75,
            "computed_at": computed_at,
            "sufficient": 1 if g.sufficient else 0,
        })
    return rows


# ══════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════

def seed_fuel_tables(
    conn: sqlite3.Connection,
    stations: list[FuelStation],
    observations: list[FuelPriceObservation],
) -> None:
    """기존 SQLite 연결에 fuel 테이블 3개를 생성하고 데이터를 삽입한다.

    멱등: INSERT OR REPLACE 사용.

    Args:
        conn: public_snapshot.sqlite 연결 (쓰기 모드).
        stations: FuelStation 리스트.
        observations: FuelPriceObservation 리스트.
    """
    cursor = conn.cursor()

    for ddl in _FUEL_DDL:
        cursor.execute(ddl)

    # fuel_station
    station_rows = []
    for s in stations:
        station_rows.append({
            "id": s.id,
            "brand": s.brand,
            "name": s.name,
            "address": s.address,
            "sido": s.sido,
            "sigungu": s.sigungu,
            "lat": s.lat,
            "lng": s.lng,
            "self_service": 1 if s.self_service else 0,
            "has_car_wash": 1 if s.has_car_wash else 0,
            "has_convenience": 1 if s.has_convenience else 0,
            "opinet_id": s.opinet_id,
            "created_at": s.created_at.isoformat(),
        })
    cursor.executemany(
        "INSERT OR REPLACE INTO fuel_station "
        "(id, brand, name, address, sido, sigungu, lat, lng, self_service, "
        "has_car_wash, has_convenience, opinet_id, created_at) "
        "VALUES (:id, :brand, :name, :address, :sido, :sigungu, :lat, :lng, "
        ":self_service, :has_car_wash, :has_convenience, :opinet_id, :created_at)",
        station_rows,
    )

    # fuel_price_latest
    latest = _latest_prices(observations)
    cursor.executemany(
        "INSERT OR REPLACE INTO fuel_price_latest "
        "(station_id, fuel_kind, price, observed_at) "
        "VALUES (:station_id, :fuel_kind, :price, :observed_at)",
        latest,
    )

    # fuel_price_grade
    stations_by_id = {s.id: s for s in stations}
    grade_rows = _grade_rows(observations, stations_by_id)
    cursor.executemany(
        "INSERT OR REPLACE INTO fuel_price_grade "
        "(sido, sigungu, fuel_kind, sample_size, p25, p50, p75, computed_at, sufficient) "
        "VALUES (:sido, :sigungu, :fuel_kind, :sample_size, :p25, :p50, :p75, "
        ":computed_at, :sufficient)",
        grade_rows,
    )

    conn.commit()


def build_fuel_snapshot(
    canonicalized: list[FuelCanonicalizationResult],
    snapshot_path: Path,
    write_files: bool = True,
) -> dict:
    """FuelCanonicalizationResult 리스트로부터 연료 스냅샷을 빌드한다.

    Args:
        canonicalized: canonicalize_opinet() 결과 리스트.
        snapshot_path: 기존 public_snapshot.sqlite 경로 (연료 테이블 추가).
        write_files: False이면 계산만 수행, 파일 미생성.

    Returns:
        {
            "station_count": int,
            "price_obs_count": int,
            "grade_count": int,
            "errors": int,
        }
    """
    stations: list[FuelStation] = []
    observations: list[FuelPriceObservation] = []
    errors = 0

    for result in canonicalized:
        if result.error:
            errors += 1
            continue
        if result.station:
            stations.append(result.station)
        observations.extend(result.price_observations)

    # 중복 station 제거 (id 기준)
    seen: set[str] = set()
    unique_stations: list[FuelStation] = []
    for s in stations:
        if s.id not in seen:
            seen.add(s.id)
            unique_stations.append(s)

    stations_by_id = {s.id: s for s in unique_stations}
    obs_tuples = [
        (stations_by_id[o.station_id].sido, stations_by_id[o.station_id].sigungu,
         o.fuel_kind, float(o.price))
        for o in observations
        if o.station_id in stations_by_id
    ]
    grades = compute_all_fuel_grades(obs_tuples)

    if write_files:
        if not snapshot_path.exists():
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(snapshot_path))
        try:
            seed_fuel_tables(conn, unique_stations, observations)
        finally:
            conn.close()

    return {
        "station_count": len(unique_stations),
        "price_obs_count": len(observations),
        "grade_count": len(grades),
        "errors": errors,
    }
