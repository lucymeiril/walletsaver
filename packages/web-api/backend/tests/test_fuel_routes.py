"""WalletSavior Phase F4 TDD — /fuels API 엔드포인트 테스트.

mini fuel snapshot SQLite를 conftest의 mini_snapshot_path에 추가하여
격리된 테스트 환경을 구성한다.

시나리오:
    1. GET /fuels/regions → sido_list / sigungu_list / brand_list / fuel_kinds
    2. GET /fuels/stations → 전체 목록
    3. GET /fuels/stations?sido=서울특별시 → 지역 필터
    4. GET /fuels/stations?fuel_kind=diesel → 유종 필터
    5. GET /fuels/stations/{id} → 상세 (prices 포함)
    6. GET /fuels/stations/{id} → 404 (존재하지 않는 id)
    7. fuel 테이블 없는 snapshot → 503
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest

# ── sys.path 설정 ──────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PACKAGES_DIR = Path(__file__).resolve().parents[3]
for _p in [str(_BACKEND_DIR), str(_PACKAGES_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ══════════════════════════════════════════════════════
# Fuel 스냅샷 픽스처 생성 헬퍼
# ══════════════════════════════════════════════════════

_OBSERVED_AT = "2025-01-15T06:00:00"

_FUEL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS fuel_station (
        id TEXT PRIMARY KEY, brand TEXT NOT NULL, name TEXT NOT NULL,
        address TEXT NOT NULL, sido TEXT NOT NULL, sigungu TEXT NOT NULL,
        lat REAL, lng REAL,
        self_service INTEGER NOT NULL DEFAULT 0,
        has_car_wash INTEGER NOT NULL DEFAULT 0,
        has_convenience INTEGER NOT NULL DEFAULT 0,
        opinet_id TEXT, created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fuel_price_latest (
        station_id TEXT NOT NULL, fuel_kind TEXT NOT NULL,
        price INTEGER NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY (station_id, fuel_kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fuel_price_grade (
        sido TEXT NOT NULL, sigungu TEXT NOT NULL, fuel_kind TEXT NOT NULL,
        sample_size INTEGER NOT NULL, p25 REAL, p50 REAL, p75 REAL,
        computed_at TEXT NOT NULL, sufficient INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (sido, sigungu, fuel_kind)
    )
    """,
]

_STATIONS = [
    ("st_001", "알뜰주유소", "강서알뜰주유소", "서울특별시 강서구 허준로 57",
     "서울특별시", "강서구", 37.5506, 126.8418, 1, 0, 0, "A0003461", "2025-01-15T00:00:00"),
    ("st_002", "SK에너지", "마곡SK주유소", "서울특별시 강서구 마곡중앙8로 111",
     "서울특별시", "강서구", 37.5588, 126.8326, 1, 0, 0, "A0014521", "2025-01-15T00:00:00"),
    ("st_003", "GS칼텍스", "화곡GS칼텍스", "서울특별시 강서구 화곡로 321",
     "서울특별시", "강서구", 37.5479, 126.8554, 0, 0, 0, "A0009876", "2025-01-15T00:00:00"),
    ("st_004", "현대오일뱅크", "등촌현대오일뱅크", "서울특별시 강서구 등촌로 175",
     "서울특별시", "강서구", 37.5534, 126.8639, 1, 0, 0, "A0002233", "2025-01-15T00:00:00"),
    ("st_005", "S-OIL", "공항S-OIL주유소", "서울특별시 강서구 하늘길 76",
     "서울특별시", "강서구", 37.5583, 126.7969, 0, 0, 0, "A0007788", "2025-01-15T00:00:00"),
    ("st_006", "SK에너지", "가양SK주유소", "서울특별시 강서구 강서로 400",
     "서울특별시", "강서구", 37.5608, 126.8472, 1, 0, 0, "A0005544", "2025-01-15T00:00:00"),
    ("st_007", "알뜰주유소", "염창자영알뜰주유소", "서울특별시 강서구 염창로 262",
     "서울특별시", "강서구", 37.5512, 126.8741, 1, 0, 0, "A0011234", "2025-01-15T00:00:00"),
]

_PRICES = [
    # (station_id, fuel_kind, price, observed_at)
    ("st_001", "gasoline_regular", 1598, _OBSERVED_AT),
    ("st_001", "diesel", 1448, _OBSERVED_AT),
    ("st_002", "gasoline_regular", 1625, _OBSERVED_AT),
    ("st_002", "gasoline_premium", 1798, _OBSERVED_AT),
    ("st_002", "diesel", 1465, _OBSERVED_AT),
    ("st_003", "gasoline_regular", 1648, _OBSERVED_AT),
    ("st_003", "gasoline_premium", 1820, _OBSERVED_AT),
    ("st_003", "diesel", 1488, _OBSERVED_AT),
    ("st_004", "gasoline_regular", 1659, _OBSERVED_AT),
    ("st_004", "diesel", 1498, _OBSERVED_AT),
    ("st_004", "lpg", 990, _OBSERVED_AT),
    ("st_005", "gasoline_regular", 1675, _OBSERVED_AT),
    ("st_005", "gasoline_premium", 1845, _OBSERVED_AT),
    ("st_005", "diesel", 1515, _OBSERVED_AT),
    ("st_006", "gasoline_regular", 1688, _OBSERVED_AT),
    ("st_006", "gasoline_premium", 1858, _OBSERVED_AT),
    ("st_006", "diesel", 1528, _OBSERVED_AT),
    ("st_007", "gasoline_regular", 1605, _OBSERVED_AT),
    ("st_007", "diesel", 1455, _OBSERVED_AT),
]

_GRADES = [
    # 서울특별시 강서구 휘발유: 7개 sample → sufficient
    ("서울특별시", "강서구", "gasoline_regular", 7, 1605.0, 1648.0, 1675.0, _OBSERVED_AT, 1),
    # 서울특별시 강서구 경유: 7개 sample → sufficient
    ("서울특별시", "강서구", "diesel", 7, 1455.0, 1488.0, 1515.0, _OBSERVED_AT, 1),
    # 서울특별시 강서구 고급휘발유: 3개 → insufficient
    ("서울특별시", "강서구", "gasoline_premium", 3, None, 1820.0, None, _OBSERVED_AT, 0),
    # 서울특별시 강서구 LPG: 1개 → insufficient
    ("서울특별시", "강서구", "lpg", 1, None, 990.0, None, _OBSERVED_AT, 0),
]


def _add_fuel_tables(db_path: str) -> None:
    """기존 test snapshot SQLite에 fuel 테이블과 데이터를 추가."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for ddl in _FUEL_DDL:
        cur.execute(ddl)
    cur.executemany(
        "INSERT OR REPLACE INTO fuel_station "
        "(id,brand,name,address,sido,sigungu,lat,lng,self_service,has_car_wash,has_convenience,opinet_id,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        _STATIONS,
    )
    cur.executemany(
        "INSERT OR REPLACE INTO fuel_price_latest (station_id,fuel_kind,price,observed_at) VALUES (?,?,?,?)",
        _PRICES,
    )
    cur.executemany(
        "INSERT OR REPLACE INTO fuel_price_grade "
        "(sido,sigungu,fuel_kind,sample_size,p25,p50,p75,computed_at,sufficient) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        _GRADES,
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
# pytest fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def fuel_snapshot_path(tmp_path_factory) -> str:
    """mini_snapshot + fuel 테이블이 포함된 임시 SQLite."""
    db = tmp_path_factory.mktemp("fuel_snap") / "fuel_test.sqlite"

    # 기본 product 테이블 생성 (conftest의 _create_mini_snapshot 함수 재사용)
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import _create_mini_snapshot
    _create_mini_snapshot(str(db))

    # fuel 테이블 추가
    _add_fuel_tables(str(db))
    return str(db)


@pytest.fixture
def fuel_client(fuel_snapshot_path, monkeypatch):
    """fuel 테이블이 있는 test client."""
    monkeypatch.setenv("WALLETSAVIOR_PUBLIC_DB", fuel_snapshot_path)
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app())


@pytest.fixture
def no_fuel_client(mini_snapshot_path, monkeypatch):
    """fuel 테이블이 없는 (기본 product 전용) test client — 503 테스트용."""
    monkeypatch.setenv("WALLETSAVIOR_PUBLIC_DB", mini_snapshot_path)
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app())


# mini_snapshot_path fixture는 conftest.py에서 제공됨
# no_fuel_client fixture가 이를 참조하므로 conftest.py가 자동으로 로드됨


# ══════════════════════════════════════════════════════
# GET /api/v1/fuels/regions
# ══════════════════════════════════════════════════════

def test_regions_200(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/regions")
    assert resp.status_code == 200


def test_regions_has_sido_list(fuel_client):
    data = fuel_client.get("/api/v1/fuels/regions").json()
    assert "sido_list" in data
    assert "서울특별시" in data["sido_list"]


def test_regions_has_sigungu_list(fuel_client):
    data = fuel_client.get("/api/v1/fuels/regions").json()
    assert "sigungu_list" in data
    assert "강서구" in data["sigungu_list"]


def test_regions_has_brand_list(fuel_client):
    data = fuel_client.get("/api/v1/fuels/regions").json()
    assert "brand_list" in data
    assert len(data["brand_list"]) > 0


def test_regions_has_fuel_kinds(fuel_client):
    data = fuel_client.get("/api/v1/fuels/regions").json()
    assert "fuel_kinds" in data
    kinds = [k["value"] for k in data["fuel_kinds"]]
    assert "gasoline_regular" in kinds
    assert "diesel" in kinds


def test_regions_sigungu_filter(fuel_client):
    """sido 파라미터로 필터링된 시군구 목록 반환."""
    data = fuel_client.get("/api/v1/fuels/regions?sido=서울특별시").json()
    assert "강서구" in data["sigungu_list"]


# ══════════════════════════════════════════════════════
# GET /api/v1/fuels/stations (검색)
# ══════════════════════════════════════════════════════

def test_stations_200(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations")
    assert resp.status_code == 200


def test_stations_returns_items(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations").json()
    assert "items" in data
    assert len(data["items"]) > 0


def test_stations_total_matches_items(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?page_size=100").json()
    assert data["total"] == len(data["items"])
    assert data["total"] == 7  # fixture에 7개 주유소


def test_stations_sido_filter(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?sido=서울특별시").json()
    for item in data["items"]:
        assert item["sido"] == "서울특별시"


def test_stations_sigungu_filter(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?sigungu=강서구").json()
    for item in data["items"]:
        assert item["sigungu"] == "강서구"


def test_stations_fuel_kind_gasoline(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?fuel_kind=gasoline_regular").json()
    assert data["total"] > 0
    for item in data["items"]:
        assert item["fuel_kind"] == "gasoline_regular"
        assert item["price"] is not None


def test_stations_fuel_kind_diesel(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?fuel_kind=diesel").json()
    assert data["total"] > 0


def test_stations_price_sorted_ascending(fuel_client):
    """price_asc 정렬 → 가격 오름차순."""
    data = fuel_client.get("/api/v1/fuels/stations?sort=price_asc&fuel_kind=gasoline_regular").json()
    prices = [item["price"] for item in data["items"] if item["price"] is not None]
    assert prices == sorted(prices)


def test_stations_has_grade_label(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?fuel_kind=gasoline_regular").json()
    for item in data["items"]:
        assert "grade_label" in item
        assert item["grade_label"] in ("CHEAP", "NORMAL", "EXPENSIVE", "INSUFFICIENT_DATA")


def test_stations_has_summary(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?fuel_kind=gasoline_regular").json()
    assert "summary" in data
    summary = data["summary"]
    assert summary["station_count"] > 0
    assert summary["min_price"] is not None
    assert summary["avg_price"] is not None


def test_stations_invalid_fuel_kind(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations?fuel_kind=invalid_fuel")
    assert resp.status_code == 422


def test_stations_invalid_sort(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations?sort=random_order")
    assert resp.status_code == 422


def test_stations_distance_sort_requires_coords(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations?sort=distance")
    assert resp.status_code == 422


def test_stations_pagination(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?page=1&page_size=3").json()
    assert len(data["items"]) <= 3
    assert data["page"] == 1
    assert data["total_pages"] >= 1


def test_stations_brand_filter(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations?brand=SK에너지").json()
    for item in data["items"]:
        assert item["brand"] == "SK에너지"


# ══════════════════════════════════════════════════════
# GET /api/v1/fuels/stations/{id} (상세)
# ══════════════════════════════════════════════════════

def test_station_detail_200(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations/st_001")
    assert resp.status_code == 200


def test_station_detail_has_prices(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations/st_001").json()
    assert "prices" in data
    assert len(data["prices"]) > 0


def test_station_detail_prices_have_grade(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations/st_001").json()
    for price in data["prices"]:
        assert "grade_label" in price
        assert "grade" in price
        assert price["grade_label"] in ("CHEAP", "NORMAL", "EXPENSIVE", "INSUFFICIENT_DATA")


def test_station_detail_correct_name(fuel_client):
    data = fuel_client.get("/api/v1/fuels/stations/st_001").json()
    assert data["name"] == "강서알뜰주유소"
    assert data["brand"] == "알뜰주유소"


def test_station_detail_404(fuel_client):
    resp = fuel_client.get("/api/v1/fuels/stations/nonexistent_id_xyz")
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════
# 503 — fuel 테이블 없음
# ══════════════════════════════════════════════════════

def test_stations_503_when_no_fuel_tables(no_fuel_client):
    resp = no_fuel_client.get("/api/v1/fuels/stations")
    assert resp.status_code == 503


def test_regions_503_when_no_fuel_tables(no_fuel_client):
    resp = no_fuel_client.get("/api/v1/fuels/regions")
    assert resp.status_code == 503


def test_station_detail_503_when_no_fuel_tables(no_fuel_client):
    resp = no_fuel_client.get("/api/v1/fuels/stations/st_001")
    assert resp.status_code == 503
