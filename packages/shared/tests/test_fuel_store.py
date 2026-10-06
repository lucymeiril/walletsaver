from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_store import FuelStore


def _record(code: str, name: str, price: int, *, lat=None, lng=None, observed_at=None):
    at = observed_at or datetime(2026, 8, 25, 9, 0, 0)
    return {
        "station_code": code,
        "brand": "알뜰",
        "name": name,
        "address": "서울특별시 강서구 테스트로 1",
        "sido": "서울특별시",
        "sigungu": "강서구",
        "lat": lat,
        "lng": lng,
        "has_self_service": True,
        "updated_at": at,
        "prices": [
            {
                "fuel_type": "gasoline",
                "price": price,
                "observed_at": at,
                "source": "opinet",
            }
        ],
    }


def test_snapshot_upsert_keeps_price_history_and_returns_latest(tmp_path):
    store = FuelStore(tmp_path / "opinet.db")
    first = datetime(2026, 8, 18, 9, 0, 0)
    second = datetime(2026, 8, 25, 9, 0, 0)

    store.save_snapshot([_record("A1", "테스트주유소", 1650, observed_at=first)])
    store.save_snapshot([_record("A1", "테스트주유소", 1590, observed_at=second)])

    rows = store.current_prices(fuel_type="gasoline")
    assert len(rows) == 1
    assert rows[0]["station_code"] == "A1"
    assert rows[0]["gasoline"] == 1590


def test_current_prices_sort_by_requested_fuel_price(tmp_path):
    store = FuelStore(tmp_path / "opinet.db")
    store.save_snapshot([
        _record("A1", "비싼주유소", 1700),
        _record("A2", "싼주유소", 1550),
    ])

    rows = store.current_prices(fuel_type="gasoline", sort_by="price_asc")
    assert [row["station_code"] for row in rows] == ["A2", "A1"]


def test_radius_filter_never_treats_missing_coordinates_as_nearby(tmp_path):
    store = FuelStore(tmp_path / "opinet.db")
    store.save_snapshot([
        _record("A1", "좌표있음", 1550, lat=37.5, lng=127.0),
        _record("A2", "좌표없음", 1500),
        _record("A3", "변환되지 않은 좌표", 1400, lat=200000, lng=500000),
    ])

    rows = store.current_prices(
        fuel_type="gasoline",
        lat=37.5,
        lng=127.0,
        radius_m=1000,
    )
    assert [row["station_code"] for row in rows] == ["A1"]
    assert rows[0]["distance_m"] == 0


def test_price_freshness_uses_selected_fuel_observation_not_station_metadata(tmp_path):
    store = FuelStore(tmp_path / 'fuel.sqlite')
    record = _record('A1', '관측 주유소', 1590, observed_at=datetime(2026, 8, 18, 9))
    record['updated_at'] = datetime(2026, 10, 3, 12)
    record['prices'].append({'fuel_type': 'diesel', 'price': 1450,
                            'observed_at': datetime(2026, 9, 2, 10), 'source': 'opinet'})
    missing_service = _record('A2', '셀프 여부 미확인', 1600)
    missing_service.pop('has_self_service')
    negative_service = _record('A3', '기존 저장값 0', 1610)
    negative_service['has_self_service'] = False
    store.save_snapshot([record, missing_service, negative_service])
    gasoline = store.current_prices(fuel_type='gasoline')[0]
    diesel = store.current_prices(fuel_type='diesel')[0]
    assert gasoline['updated_at'] == '2026-08-18T09:00:00'
    assert diesel['updated_at'] == '2026-09-02T10:00:00'
    assert gasoline['station_updated_at'] == '2026-10-03T12:00:00'
    assert gasoline['price_observed_at']['diesel'] == diesel['updated_at']
    services = {row['station_code']: row['self_service'] for row in store.current_prices()}
    assert services == {'A1': True, 'A2': None, 'A3': None}
