"""Current OPINET contracts: canonical fixture parsing plus live API normalization."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from crawlers.opinet.crawler import (
    GasStationPriceRecord,
    GasStationRecord,
    OpinetCrawler,
    merge_station_records,
    normalize_brand,
    normalize_fuel_type,
    parse_api_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "opinet" / "sample_seoul.json"


def test_parse_fixture_records_and_prices():
    records = OpinetCrawler(FIXTURE, api_key="").parse_fixture()

    assert len(records) == 3
    assert records[0].station_code == "A0003461"
    assert records[0].brand == "알뜰"
    assert records[0].has_self_service is True
    assert records[0].prices[0].fuel_type == "gasoline"
    assert records[0].prices[0].price == 1598


def test_crawl_region_filters_saved_fixture_without_network():
    records = OpinetCrawler(FIXTURE, api_key="").crawl_region("서울")

    assert len(records) == 3
    assert {record.sido for record in records} == {"서울특별시"}


def test_brand_and_fuel_normalization_includes_opinet_codes():
    assert normalize_brand("현대오일뱅크") == "HD현대오일뱅크"
    assert normalize_brand("HDO") == "HD현대오일뱅크"
    assert normalize_brand("RTO") == "알뜰"
    assert normalize_brand("무인상표") == "기타"
    assert normalize_fuel_type("gasoline_regular") == "gasoline"
    assert normalize_fuel_type("B027") == "gasoline"
    assert normalize_fuel_type("B034") == "diesel"
    assert normalize_fuel_type("K015") == "lpg"


def test_low_top10_payload_maps_to_canonical_station_record():
    observed_at = datetime(2026, 8, 25, 9, 0, 0)
    payload = {
        "RESULT": {
            "OIL": [
                {
                    "UNI_ID": "A001",
                    "OS_NM": "테스트셀프주유소",
                    "POLL_DIV_CD": "SKE",
                    "NEW_ADR": "서울특별시 강남구 테헤란로 1",
                    "GIS_Y_COOR": "37.5001",
                    "GIS_X_COOR": "127.0301",
                    "PRICE": "1,615",
                    "SELF_YN": "Y",
                }
            ]
        }
    }

    records = parse_api_payload(payload, fuel_type="gasoline", observed_at=observed_at)

    assert len(records) == 1
    record = records[0]
    assert record.station_code == "A001"
    assert record.brand == "SK"
    assert record.sido == "서울특별시"
    assert record.sigungu == "강남구"
    assert record.lat == pytest.approx(37.5001)
    assert record.lng == pytest.approx(127.0301)
    assert record.has_self_service is True
    assert record.prices == [
        GasStationPriceRecord(
            fuel_type="gasoline",
            price=1615,
            observed_at=observed_at,
            source="opinet",
        )
    ]


def test_merge_station_records_combines_fuels_by_station_code():
    at = datetime(2026, 8, 25, 9, 0, 0)
    base = dict(
        station_code="A001",
        brand="GS",
        name="테스트주유소",
        address="서울특별시 강남구 테헤란로 1",
        sido="서울특별시",
        sigungu="강남구",
        lat=37.5,
        lng=127.03,
        updated_at=at,
    )
    records = merge_station_records([
        GasStationRecord(
            **base,
            prices=[GasStationPriceRecord("gasoline", 1600, at)],
        ),
        GasStationRecord(
            **base,
            prices=[GasStationPriceRecord("diesel", 1490, at)],
        ),
    ])

    assert len(records) == 1
    prices = {price.fuel_type: price.price for price in records[0].prices}
    assert prices == {"diesel": 1490, "gasoline": 1600}


def test_live_crawl_is_explicitly_disabled_without_api_key():
    crawler = OpinetCrawler(FIXTURE, api_key="")

    assert crawler.live_ready is False
    assert crawler.live_crawl() == []


def test_live_crawl_uses_api_rows_and_merges_fuel_prices(monkeypatch):
    crawler = OpinetCrawler(FIXTURE, api_key="configured")
    calls: list[tuple[str, str]] = []
    price_by_product = {"B027": "1600", "B034": "1490", "K015": "970"}

    def fake_request(session, *, product_code: str, area_code: str):
        calls.append((product_code, area_code))
        return {
            "RESULT": {
                "OIL": [{
                    "UNI_ID": "A001",
                    "OS_NM": "테스트주유소",
                    "POLL_DIV_CD": "GSC",
                    "NEW_ADR": "서울특별시 강남구 테헤란로 1",
                    "PRICE": price_by_product[product_code],
                }]
            }
        }

    monkeypatch.setattr(crawler, "_request_low_top10", fake_request)
    records = crawler.live_crawl(sido_codes=["01"])

    assert calls == [("B027", "01"), ("B034", "01"), ("K015", "01")]
    assert len(records) == 1
    assert records[0].brand == "GS"
    assert {p.fuel_type: p.price for p in records[0].prices} == {
        "gasoline": 1600,
        "diesel": 1490,
        "lpg": 970,
    }
