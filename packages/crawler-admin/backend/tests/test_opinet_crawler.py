"""WalletSavior Phase F4 TDD — 오피넷 크롤러 파서 테스트.

픽스처 HTML (서울특별시 강서구, 7개 주유소):
    저가주유소 검색 결과의 tbody#tb_sub 파싱 검증.

시나리오:
    1. parse_opinet_low_price_html → 7개 row 반환
    2. 특정 브랜드/가격/opinet_id 검증
    3. 셀프여부 파싱 검증
    4. OpinetCrawler.crawl_from_fixture → FuelCanonicalizationResult 리스트
    5. 빈 HTML → 빈 리스트 반환
    6. 존재하지 않는 tbody → 빈 리스트 반환
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── sys.path 설정 ──────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
for _p in [str(_BACKEND_DIR), str(_SHARED_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# beautifulsoup4 필요 — 없으면 테스트 스킵
pytest.importorskip("bs4", reason="beautifulsoup4가 필요합니다")

from crawlers.opinet.parser import parse_opinet_low_price_html

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "opinet" / "low_price_seoul_gangseo.html"
)


@pytest.fixture(scope="module")
def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════
# parse_opinet_low_price_html — 기본 파싱
# ══════════════════════════════════════════════════════

def test_parse_returns_7_rows(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert len(rows) == 7


def test_parse_first_row_name(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["name"] == "강서알뜰주유소"


def test_parse_first_row_brand(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["brand"] == "알뜰(자영)"


def test_parse_first_row_opinet_id(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["opinet_id"] == "A0003461"


def test_parse_first_row_gasoline_price(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["gasoline_regular"] == "1,598"


def test_parse_first_row_diesel_price(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["diesel"] == "1,448"


def test_parse_first_row_premium_dash(fixture_html):
    """고급휘발유 '-' → 파서는 원문 그대로 '-' 반환 (변환은 canonicalize가 담당)."""
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["gasoline_premium"] in ("-", None, "")


def test_parse_self_service_flag(fixture_html):
    """셀프 여부: 1번(셀프)=True, 3번(일반)=False."""
    rows = parse_opinet_low_price_html(fixture_html)
    assert rows[0]["self_service"] is True   # 강서알뜰주유소 — 셀프
    assert rows[2]["self_service"] is False  # 화곡GS칼텍스 — 일반


def test_parse_brands(fixture_html):
    """fixture의 브랜드 종류 확인."""
    rows = parse_opinet_low_price_html(fixture_html)
    brands = {r["brand"] for r in rows}
    assert "알뜰(자영)" in brands
    assert "SK에너지" in brands
    assert "GS칼텍스" in brands
    assert "현대오일뱅크" in brands
    assert "S-OIL" in brands
    assert "자영알뜰" in brands


def test_parse_last_row(fixture_html):
    """7번째 row: 염창자영알뜰주유소."""
    rows = parse_opinet_low_price_html(fixture_html)
    last = rows[-1]
    assert last["name"] == "염창자영알뜰주유소"
    assert last["brand"] == "자영알뜰"
    assert last["opinet_id"] == "A0011234"
    assert last["gasoline_regular"] == "1,605"


def test_parse_all_rows_have_address(fixture_html):
    rows = parse_opinet_low_price_html(fixture_html)
    for row in rows:
        assert row["address"].startswith("서울특별시 강서구")


def test_parse_source_url(fixture_html):
    custom_url = "https://www.opinet.co.kr/searRgSelect.do"
    rows = parse_opinet_low_price_html(fixture_html, source_url=custom_url)
    for row in rows:
        assert row["source_url"] == custom_url


# ══════════════════════════════════════════════════════
# 엣지 케이스
# ══════════════════════════════════════════════════════

def test_empty_html_returns_empty():
    rows = parse_opinet_low_price_html("")
    assert rows == []


def test_no_tbody_returns_empty():
    html = "<html><body><p>결과 없음</p></body></html>"
    rows = parse_opinet_low_price_html(html)
    assert rows == []


def test_header_only_table_returns_empty():
    html = """<html><body>
    <table><thead><tr><th>순위</th><th>주유소명</th></tr></thead>
    <tbody id="tb_sub"></tbody></table>
    </body></html>"""
    rows = parse_opinet_low_price_html(html)
    assert rows == []


# ══════════════════════════════════════════════════════
# OpinetCrawler.crawl_from_fixture 통합 테스트
# ══════════════════════════════════════════════════════

def test_crawler_crawl_from_fixture():
    """crawl_from_fixture → FuelCanonicalizationResult 리스트 7개 이상."""
    from crawlers.opinet.crawler import OpinetCrawler

    results = OpinetCrawler().crawl_from_fixture(FIXTURE_PATH)
    assert len(results) >= 7


def test_crawler_results_have_no_errors():
    """모든 결과에 error=None."""
    from crawlers.opinet.crawler import OpinetCrawler

    results = OpinetCrawler().crawl_from_fixture(FIXTURE_PATH)
    errors = [r for r in results if r.error is not None]
    assert errors == [], f"예외 결과: {[e.error for e in errors]}"


def test_crawler_results_have_stations():
    from crawlers.opinet.crawler import OpinetCrawler

    results = OpinetCrawler().crawl_from_fixture(FIXTURE_PATH)
    stations = [r.station for r in results if r.station is not None]
    assert len(stations) == len(results)


def test_crawler_results_observations_nonzero():
    """각 station에 최소 1개 이상 observation."""
    from crawlers.opinet.crawler import OpinetCrawler

    results = OpinetCrawler().crawl_from_fixture(FIXTURE_PATH)
    for r in results:
        assert len(r.price_observations) >= 1, (
            f"관측값 없음: {r.station.name if r.station else 'unknown'}"
        )


def test_crawler_brand_normalization():
    """알뜰(자영) → 알뜰주유소, 자영알뜰 → 알뜰주유소 정규화 확인."""
    from crawlers.opinet.crawler import OpinetCrawler

    results = OpinetCrawler().crawl_from_fixture(FIXTURE_PATH)
    brands = {r.station.brand for r in results if r.station}
    # 정규화된 브랜드명만 있어야 함
    assert "알뜰(자영)" not in brands, "정규화 안 된 브랜드가 남아 있음"
    assert "자영알뜰" not in brands, "정규화 안 된 브랜드가 남아 있음"
    assert "알뜰주유소" in brands
