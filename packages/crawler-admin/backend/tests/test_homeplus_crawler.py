"""홈플러스 entrypoints — mfront search API 슬림 fixture 회귀.

Fixture provenance
------------------
``tests/fixtures/homeplus/sale_listing_3items.json`` — 진짜 mfront search
API 응답 ``tests/fixtures/homeplus_probe_api.json`` (108 KB,
returnStatus 200, dataList 30 개) 에서 ``itemNm``/``salePrice``/
``docId``/``itemNo``/``unitPrice`` 등 모든 키를 보존한 상태로 처음 3개
행만 남긴 슬림화이다. 따라서 entrypoints 가 라이브 응답을 받았을 때와
완전히 동일한 키 경로로 ``DiscountItem`` 을 구성한다.

PC SSR HTML (homeplus.co.kr) 은 SPA shell 이라 본 fixture 가 가장
신뢰할 수 있는 라이브-검증된 데이터 소스다 (``homeplus_probe_search.html``
역시 92 KB 짜리 mfront SSR 캡처지만 자동 파싱은 mfront API 가 정도(正道)).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from crawlers.marts.entry_points import CollectionPath, CrawlIntent
from crawlers.marts.homeplus.crawler import HomeplusCrawler
from crawlers.marts.homeplus.entrypoints import (
    HomeplusEntrypoints,
    SALE_QUERY,
    _api_item_to_discount_item,
    _try_parse_mfront_envelope,
)


FIXTURE_JSON = pathlib.Path(__file__).parent / "fixtures" / "homeplus" / "sale_listing_3items.json"


@pytest.fixture
def raw_json() -> str:
    assert FIXTURE_JSON.exists(), f"missing slim API fixture: {FIXTURE_JSON}"
    return FIXTURE_JSON.read_text(encoding="utf-8")


@pytest.fixture
def parsed_envelope():
    return json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))


# ---------- mfront API JSON 매퍼 회귀 ----------
def test_envelope_parser_recognises_three_items(raw_json):
    items = _try_parse_mfront_envelope(raw_json)
    assert items is not None and len(items) == 3


def test_envelope_first_item_has_real_name_price_and_detail_url(raw_json, parsed_envelope):
    items = _try_parse_mfront_envelope(raw_json)
    raw_first = parsed_envelope["data"]["dataList"][0]
    first = items[0]
    assert first.name == raw_first["itemNm"]
    assert first.sale_price == int(raw_first["salePrice"])
    # 첫 fixture 행은 simplus 숯불닭꼬치 (itemNo=068769294)
    assert "itemNo=068769294" in first.detail_url
    assert first.detail_url.startswith("https://mfront.homeplus.co.kr/item?itemNo=")
    assert first.attributes["doc_id"] == raw_first["docId"]
    assert first.attributes["item_no"] == raw_first["itemNo"]
    assert first.attributes["source_record_key"]


def test_envelope_no_phantom_prices(raw_json):
    items = _try_parse_mfront_envelope(raw_json)
    for it in items:
        assert it.sale_price > 0
        # API fixture 의 모든 행이 dcPrice=None 이므로 original_price 도 없어야 한다
        assert it.original_price is None


def test_envelope_does_not_match_unrelated_json():
    """returnStatus 가 200 이 아닌 임의 JSON 은 None 을 반환해 폴백을 허용해야 한다."""
    assert _try_parse_mfront_envelope('{"returnStatus":500,"data":{}}') is None
    assert _try_parse_mfront_envelope("<html>not json</html>") is None
    assert _try_parse_mfront_envelope("[]") is None


# ---------- 4 entrypoints ----------
@pytest.mark.asyncio
async def test_sale_listing_tags_public_endpoint_and_sale_intent(raw_json):
    ep = HomeplusEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: raw_json)
    assert result.status.name == "SUCCESS"
    assert result.items_count == 3
    for it in result.items:
        assert it["attributes"]["collection_path"] == CollectionPath.PUBLIC_ENDPOINT.value
        assert it["attributes"]["crawl_intent"] == CrawlIntent.SALE.value
    from urllib.parse import quote
    assert quote(SALE_QUERY) in result.quality_details["entrypoint"]["source_url"]


@pytest.mark.asyncio
async def test_catalog_page_tags_catalog_intent(raw_json):
    ep = HomeplusEntrypoints()
    result = await ep.crawl_catalog_page("우유", page=2, fetch=lambda url: raw_json)
    assert result.items_count == 3
    assert result.quality_details["query"] == "우유"
    assert result.quality_details["page"] == 2
    for it in result.items:
        assert it["attributes"]["collection_path"] == "catalog_page"
        assert it["attributes"]["crawl_intent"] == "catalog"


@pytest.mark.asyncio
async def test_fetch_single_product_constructs_mfront_url(raw_json):
    ep = HomeplusEntrypoints()
    result = await ep.fetch_single_product("068769294", fetch=lambda url: raw_json)
    assert "itemNo=068769294" in result.quality_details["entrypoint"]["source_url"]
    for it in result.items:
        assert it["attributes"]["collection_path"] == "single_product"
        assert it["attributes"]["crawl_intent"] == "refresh"


@pytest.mark.asyncio
async def test_ingest_operator_capture_tags_capture_id_and_path(raw_json):
    ep = HomeplusEntrypoints()
    result = await ep.ingest_operator_capture(
        raw_json,
        source_url="https://mfront.homeplus.co.kr/search?keyword=할인",
        capture_id="op-homeplus-001",
    )
    assert result.items_count == 3
    for it in result.items:
        assert it["attributes"]["collection_path"] == "operator_capture"
        assert it["attributes"]["operator_capture_id"] == "op-homeplus-001"
    assert result.quality_details["operator_capture"] is True
    assert result.quality_details["source_host"] == "mfront.homeplus.co.kr"


# ---------- SPA-셸 / 빈 응답 정직 진단 ----------
@pytest.mark.asyncio
async def test_sale_listing_with_empty_datalist_reports_blocker():
    empty = json.dumps({"returnStatus": 200, "data": {"dataList": []}})
    ep = HomeplusEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: empty)
    assert result.items_count == 0
    assert result.errors
    assert "empty_mfront_datalist" in result.errors[0].error_msg


@pytest.mark.asyncio
async def test_sale_listing_against_spa_shell_html_reports_blocker():
    """PC SSR HTML 셸이 임베디드 JSON 패턴 없을 때 fallback parser 가 빈 결과."""
    shell = "<html><body><div id='__next'></div></body></html>"
    ep = HomeplusEntrypoints()
    result = await ep.crawl_catalog_page("우유", fetch=lambda url: shell)
    assert result.items_count == 0
    assert result.errors
    assert "spa_shell_no_embedded_json" in result.errors[0].error_msg or "no_recognised_payload" in result.errors[0].error_msg


# ---------- 모델 quirk 준수 ----------
@pytest.mark.asyncio
async def test_crawl_result_uses_finished_at_and_items_are_dicts(raw_json):
    ep = HomeplusEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: raw_json)
    assert result.finished_at is not None
    assert "quality_details" in result.model_dump()
    assert all(isinstance(it, dict) for it in result.items)


# ---------- 단가 / 카테고리 / 이벤트 메타 보존 ----------
def test_envelope_preserves_unit_price_doc_id_and_category(raw_json, parsed_envelope):
    items = _try_parse_mfront_envelope(raw_json)
    first_raw = parsed_envelope["data"]["dataList"][0]
    first = items[0]
    assert first.attributes["mfront_unit_price"] == first_raw["unitPrice"]
    # category 는 가장 구체적인 scate/mcate/lcate 우선
    expected = (
        first_raw.get("scateNm")
        or first_raw.get("mcateNm")
        or first_raw.get("lcateNm")
        or ""
    )
    assert first.category == expected
