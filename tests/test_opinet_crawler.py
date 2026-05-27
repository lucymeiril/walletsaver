"""Round R G5-c 오피넷 fixture 크롤러 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_BACKEND = ROOT / "packages" / "crawler-admin" / "backend"
for path in (CRAWLER_BACKEND, ROOT / "packages" / "shared"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from crawlers.opinet.crawler import OpinetCrawler, normalize_brand, normalize_fuel_type

FIXTURE = ROOT / "tests" / "fixtures" / "opinet" / "sample_seoul.json"


def test_parse_fixture_records_and_prices():
    records = OpinetCrawler(FIXTURE).parse_fixture()

    assert len(records) == 3
    assert records[0].station_code == "A0003461"
    assert records[0].brand == "알뜰"
    assert records[0].has_self_service is True
    assert records[0].prices[0].fuel_type == "gasoline"
    assert records[0].prices[0].price == 1598


def test_crawl_region_filters_sido():
    records = OpinetCrawler(FIXTURE).crawl_region("서울")

    assert len(records) == 3
    assert {record.sido for record in records} == {"서울특별시"}


def test_brand_and_fuel_normalization():
    assert normalize_brand("현대오일뱅크") == "HD현대오일뱅크"
    assert normalize_brand("알뜰(자영)") == "알뜰"
    assert normalize_brand("무인상표") == "기타"
    assert normalize_fuel_type("gasoline_regular") == "gasoline"
    assert normalize_fuel_type("kerosene") == "kerosene"
