from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

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


def test_gas_region_and_radius_filters_preserve_selected_price_observation(tmp_path, monkeypatch):
    path = tmp_path / 'fuel.sqlite'
    monkeypatch.setenv('OPINET_DB_PATH', str(path))
    near = _record('near', '선택 지역 가까운 역', 1700, lat=37.5, lng=127.0)
    far = _record('far', '선택 지역 먼 역', 1400, lat=37.52, lng=127.0)
    other = _record('other', '다른 지역 역', 1300, lat=37.5, lng=127.0)
    other['sigungu'] = '양천구'
    near['updated_at'] = datetime(2026, 10, 3, 12)
    FuelStore(path).save_snapshot([near, far, other])
    from api.app import create_app
    client = TestClient(create_app(storage=object()))
    response = client.get('/api/gas/nearby', params={'lat': 37.5, 'lng': 127.0, 'radius': 1000,
                          'sido': '서울특별시', 'sigungu': '강서구'})
    assert response.status_code == 200
    rows = response.json()['data']
    assert [row['station_code'] for row in rows] == ['near']
    assert rows[0]['distance_m'] == 0
    assert rows[0]['updated_at'] == '2026-08-25T09:00:00'
    assert rows[0]['self_service'] is None
    response = client.get('/api/gas/nearby', params={'sido': '없는 지역'})
    assert response.status_code == 200 and response.json()['data'] == []
    assert '선택한 지역' in response.json()['message']


@pytest.mark.parametrize('corrupt', [False, True])
def test_gas_missing_or_corrupt_snapshot_is_503_and_never_created(tmp_path, monkeypatch, corrupt):
    path = tmp_path / 'unavailable.sqlite'
    if corrupt:
        path.write_bytes(b'not a SQLite database')
    monkeypatch.setenv('OPINET_DB_PATH', str(path))
    before = path.read_bytes() if corrupt else None
    from api.app import create_app
    response = TestClient(create_app(storage=object())).get('/api/gas/nearby')
    assert response.status_code == 503
    assert path.read_bytes() == before if corrupt else not path.exists()


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
    record = _record("A1", "오피넷주유소", 1600, lat=37.5, lng=127.0)
    record["prices"].append({"fuel_type": "diesel", "price": 1500,
                             "observed_at": datetime(2026, 9, 2, 9), "source": "opinet"})
    FuelStore(db_path).save_snapshot([record])

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
    assert payload["items"][0]["petrol_info"]["price_observed_at"] == {
        "gasoline": "2026-08-25T09:00:00", "diesel": "2026-09-02T09:00:00",
    }
    assert payload["items"][0]["petrol_info"]["is_24h"] is None
    assert payload["items"][0]["petrol_info"]["has_car_wash"] is None


def test_local_area_explore_finishes_without_browser_search_opt_in(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPINET_DB_PATH", str(tmp_path / "missing-opinet.db"))

    from api.routes import naver_local

    browser_calls = []

    def fail_if_called(*args, **kwargs):
        browser_calls.append((args, kwargs))
        raise AssertionError("browser search must require request-level opt-in")

    monkeypatch.setattr(naver_local, "_search_via_playwright_sync", fail_if_called)

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
    assert browser_calls == []


def test_local_area_explore_runs_browser_search_after_explicit_opt_in(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPINET_DB_PATH", str(tmp_path / "missing-opinet.db"))

    from api.routes import naver_local

    def fake_browser_search(query, lat, lng, max_items):
        return [{
            "name": f"{query} 테스트 결과",
            "category": query,
            "address": "서울특별시 테스트로 1",
            "url": "https://map.naver.com/p/entry/place/1",
        }]

    monkeypatch.setattr(
        naver_local,
        "_search_via_playwright_sync",
        fake_browser_search,
    )

    from api.app import create_app

    client = TestClient(create_app(storage=object()))
    response = client.get(
        "/api/local/area-explore-stream",
        params={
            "categories": "음식",
            "lat": 37.5,
            "lng": 127.0,
            "browser_search": "true",
        },
    )

    assert response.status_code == 200
    first_event = next(
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and "done" not in line
    )
    assert first_event["source"] == "naver"
    assert first_event["items"][0]["name"] == "음식 테스트 결과"


def test_unknown_geocode_does_not_start_browser_without_opt_in(monkeypatch):
    from api.routes import naver_local

    browser_calls = []

    def fail_if_called(*args, **kwargs):
        browser_calls.append((args, kwargs))
        raise AssertionError("geocode browser search must require opt-in")

    monkeypatch.setattr(naver_local, "_search_via_playwright_sync", fail_if_called)

    from api.app import create_app

    response = TestClient(create_app(storage=object())).get(
        "/api/local/geocode",
        params={"query": "등록되지 않은 위치"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert browser_calls == []


def test_unknown_geocode_runs_browser_after_explicit_opt_in(monkeypatch):
    from api.routes import naver_local

    calls = []
    def search(query, lat, lng, max_items):
        calls.append((query, lat, lng, max_items))
        return [{"name": "테스트역", "x": "127.1", "y": "37.4"}]

    monkeypatch.setattr(
        naver_local,
        "_search_via_playwright_sync",
        search,
    )

    from api.app import create_app

    response = TestClient(create_app(storage=object())).get(
        "/api/local/geocode",
        params={"query": "테스트역", "browser_search": "true"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "name": "테스트역",
        "lat": 37.4,
        "lng": 127.1,
        "source": "naver",
    }
    assert calls == [("테스트역", None, None, 1)]


@pytest.mark.parametrize("reference", [(None, None), (37.5, 127.0)])
def test_public_browser_search_preserves_query_without_disguising_automation(monkeypatch, reference):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from urllib.parse import unquote, urlsplit
    from api.routes import naver_local

    page = MagicMock()
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    chromium = MagicMock()
    chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = SimpleNamespace(chromium=chromium)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=lambda: manager))

    response = SimpleNamespace(url="https://map.naver.com/observed/allSearch", status=200,
        json=lambda: {"result": {"place": {"list": [{"id": "native", "name": "실제 응답 형태",
                  "x": "127.1", "y": "37.4", "reviewCount": "9",
                  "petrolInfo": {"isSelf": False, "is24Opened": True}}]}}})
    page.goto.side_effect = lambda *args, **kwargs: page.on.call_args.args[1](response)

    query = "종로구 카페 & 식당#검색"
    items = naver_local._search_via_playwright_sync(query, *reference, 1)
    assert len(items) == 1 and items[0]["name"] == "실제 응답 형태"
    assert items[0]["review_count"] == 9 and items[0]["rating"] is None
    assert items[0]["petrol_info"]["is_self"] is False
    assert items[0]["petrol_info"]["is_24h"] is True
    assert items[0]["petrol_info"]["has_car_wash"] is None
    launch = chromium.launch.call_args.kwargs
    assert launch.get("headless") is True
    assert not any("AutomationControlled" in arg for arg in launch.get("args", []))
    assert "user_agent" not in browser.new_context.call_args.kwargs
    page.add_init_script.assert_not_called()
    options = browser.new_context.call_args.kwargs
    if reference == (None, None):
        assert "geolocation" not in options and "permissions" not in options
    else:
        assert options["geolocation"] == {"latitude": 37.5, "longitude": 127.0}
    url = urlsplit(page.goto.call_args.args[0])
    assert unquote(url.path) == "/p/search/" + query
    assert url.query == url.fragment == ""
    browser.close.assert_called_once()

    response.json = lambda: {"result": {"place": {"list": []}}}
    assert naver_local._search_via_playwright_sync(query, *reference, 1) == []
    response.json = lambda: {"result": {}}
    with pytest.raises(RuntimeError):
        naver_local._search_via_playwright_sync(query, *reference, 1)


@pytest.mark.parametrize("path", ["naver-search", "area-explore-stream", "subcategory-search"])
@pytest.mark.parametrize("available", [False, True])
def test_local_browser_unavailable_is_not_a_confirmed_empty_result(monkeypatch, path, available):
    from api.routes import naver_local
    from api.app import create_app

    def search(*args):
        if not available:
            raise RuntimeError("structured response unavailable")
        return []

    monkeypatch.setattr(naver_local, "_search_via_playwright_sync", search)
    response = TestClient(create_app(storage=object())).get('/api/local/' + path,
        params={"query": "카페", "subcategory": "카페", "categories": "카페",
                "lat": 37.5, "lng": 127.0, "browser_search": "true"})
    assert response.status_code == 200
    if path == "area-explore-stream":
        payload = next(json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines() if line.startswith("data: ") and "done" not in line)
    else:
        payload = response.json()["data"]
    assert payload["items"] == []
    assert payload["source"] == ("naver" if available else "unavailable")
