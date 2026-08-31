from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SHARED = BACKEND_ROOT.parent.parent / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from core.fuel_store import FuelStore


def _record(code: str, name: str, price: int, *, lat=None, lng=None):
    at = datetime(2026, 8, 25, 9, 0, 0)
    return {
        "station_code": code,
        "brand": "알뜰",
        "name": name,
        "address": "서울특별시 강서구 테스트로 1",
        "sido": "서울특별시",
        "sigungu": "강서구",
        "lat": lat,
        "lng": lng,
        "updated_at": at,
        "prices": [{
            "fuel_type": "gasoline",
            "price": price,
            "observed_at": at,
            "source": "opinet",
        }],
    }


def test_gas_api_reads_dedicated_opinet_db(tmp_path, monkeypatch):
    db_path = tmp_path / "opinet.db"
    monkeypatch.setenv("OPINET_DB_PATH", str(db_path))
    FuelStore(db_path).save_snapshot([
        _record("A1", "비싼주유소", 1700),
        _record("A2", "싼주유소", 1550),
    ])

    from api.app import create_app

    client = TestClient(create_app(storage=object()))
    response = client.get(
        "/api/gas/nearby",
        params={"fuel_type": "gasoline", "sido": "서울특별시"},
    )

    assert response.status_code == 200
    rows = response.json()["data"]
    assert [row["station_code"] for row in rows] == ["A2", "A1"]
    assert rows[0]["gasoline"] == 1550


def test_gas_radius_does_not_include_station_without_wgs84_coordinates(tmp_path, monkeypatch):
    db_path = tmp_path / "opinet.db"
    monkeypatch.setenv("OPINET_DB_PATH", str(db_path))
    FuelStore(db_path).save_snapshot([
        _record("A1", "좌표있음", 1600, lat=37.5, lng=127.0),
        _record("A2", "좌표없음", 1500),
    ])

    from api.app import create_app

    client = TestClient(create_app(storage=object()))
    response = client.get(
        "/api/gas/nearby",
        params={
            "fuel_type": "gasoline",
            "lat": 37.5,
            "lng": 127.0,
            "radius": 1000,
        },
    )

    assert response.status_code == 200
    rows = response.json()["data"]
    assert [row["station_code"] for row in rows] == ["A1"]


def test_local_area_explore_uses_opinet_snapshot_for_gas_category(tmp_path, monkeypatch):
    db_path = tmp_path / "opinet.db"
    monkeypatch.setenv("OPINET_DB_PATH", str(db_path))
    FuelStore(db_path).save_snapshot([
        _record("A1", "오피넷주유소", 1600, lat=37.5, lng=127.0),
    ])

    from api.app import create_app

    client = TestClient(create_app(storage=object()))
    response = client.get(
        "/api/local/area-explore-stream",
        params={"categories": "주유소", "lat": 37.5, "lng": 127.0, "max_items": 8},
    )

    assert response.status_code == 200
    first_event = next(
        line for line in response.text.splitlines() if line.startswith("data: ") and "done" not in line
    )
    payload = json.loads(first_event.removeprefix("data: "))
    assert payload["source"] == "opinet"
    assert payload["items"][0]["name"] == "오피넷주유소"
    assert payload["items"][0]["petrol_info"]["gasoline"] == 1600


def test_local_area_explore_finishes_without_browser_search_opt_in(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("NAVER_PLACE_BROWSER_SEARCH_ENABLED", raising=False)
    monkeypatch.setenv("OPINET_DB_PATH", str(tmp_path / "missing-opinet.db"))

    from api.app import create_app

    client = TestClient(create_app(storage=object()))
    response = client.get(
        "/api/local/area-explore-stream",
        params={"categories": "음식,카페", "lat": 37.5, "lng": 127.0},
    )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1] == {"done": True}
    assert [event["source"] for event in events[:-1]] == ["unavailable", "unavailable"]
