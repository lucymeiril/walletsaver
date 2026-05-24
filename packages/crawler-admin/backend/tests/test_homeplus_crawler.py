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
DC_MIXED_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "homeplus" / "sale_listing_5items_dc_mixed.json"
LIVE_DC_PROBE = pathlib.Path(__file__).parent / "fixtures" / "live_probe" / "homeplus_dc_행사.json"


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


# ---------- dc 분기 진본 fixture 회귀 (Phase A 게이트) ----------
@pytest.fixture
def dc_mixed_raw() -> str:
    assert DC_MIXED_FIXTURE.exists(), f"missing dc-mixed fixture: {DC_MIXED_FIXTURE}"
    return DC_MIXED_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def dc_mixed_envelope():
    return json.loads(DC_MIXED_FIXTURE.read_text(encoding="utf-8"))


def test_dc_mixed_fixture_yields_three_discount_and_two_sale_only(dc_mixed_raw):
    items = _try_parse_mfront_envelope(dc_mixed_raw)
    assert items is not None and len(items) == 5
    with_dc = [i for i in items if i.original_price is not None]
    sale_only = [i for i in items if i.original_price is None]
    assert len(with_dc) == 3, f"dcPrice 채워진 분기 3개여야 함 — 실제 {len(with_dc)}"
    assert len(sale_only) == 2, f"dcPrice null fallback 분기 2개여야 함 — 실제 {len(sale_only)}"


def test_dc_branch_maps_sale_price_to_dcPrice_and_original_to_salePrice(dc_mixed_raw, dc_mixed_envelope):
    """dcPrice 채워진 행은: sale_price=dcPrice, original_price=salePrice (정가).
    그래야만 사용자 화면에서 '50%↓' 가 정상적으로 표시된다."""
    items = _try_parse_mfront_envelope(dc_mixed_raw)
    by_no = {i.attributes["item_no"]: i for i in items}
    for raw in dc_mixed_envelope["data"]["dataList"]:
        if raw.get("dcPrice") is None:
            continue
        it = by_no[raw["itemNo"]]
        assert it.sale_price == int(raw["dcPrice"]), (
            f"dc 분기 sale_price 매핑 오류: {it.name} sale={it.sale_price} expect={raw['dcPrice']}"
        )
        assert it.original_price == int(raw["salePrice"])
        assert it.original_price > it.sale_price
        # discount_percent 도 0 이상으로 채워져야 한다
        assert it.discount_percent is not None and it.discount_percent > 0


def test_null_dcPrice_branch_falls_back_to_salePrice(dc_mixed_raw, dc_mixed_envelope):
    """dcPrice=null 행은: sale_price=salePrice(원가), original_price=None."""
    items = _try_parse_mfront_envelope(dc_mixed_raw)
    by_no = {i.attributes["item_no"]: i for i in items}
    for raw in dc_mixed_envelope["data"]["dataList"]:
        if raw.get("dcPrice") is not None:
            continue
        it = by_no[raw["itemNo"]]
        assert it.sale_price == int(raw["salePrice"])
        assert it.original_price is None
        assert it.discount_percent is None or it.discount_percent == 0


# ---------- 가짜 통과 방지: dcPrice 가 100% null 인 fixture 는 빌드를 깨야 한다 ----------
def test_negative_all_null_dcPrice_fixture_is_not_a_valid_phaseA_artifact(raw_json):
    """예전 슬라이스의 sale_listing_3items.json 처럼 dcPrice 가 전부 null 인
    fixture 만 갖고 Phase A 를 통과시키지 못하도록, 그런 fixture 에는 dc 분기
    회귀가 0건이라는 것을 명시적으로 확정한다.

    => Phase A 의 진정 통과 기준: dcPrice 채워진 행을 포함한 fixture 가 존재해야 한다.
    """
    items = _try_parse_mfront_envelope(raw_json)
    assert items is not None
    dc_branch = [i for i in items if i.original_price is not None and i.original_price > i.sale_price]
    assert dc_branch == [], (
        "sale_listing_3items.json 은 의도적으로 dcPrice=null 만 갖고 있으며 "
        "Phase A 진정 통과의 단독 근거가 될 수 없다. dc 분기를 가진 fixture "
        "(sale_listing_5items_dc_mixed.json) 가 필수."
    )
    # 따라서 두 fixture 가 모두 존재해야만 진정한 Phase A 통과.
    assert DC_MIXED_FIXTURE.exists(), "dc 분기 fixture 가 누락되면 Phase A 미통과"


def test_live_dc_probe_when_present_has_at_least_one_populated_row():
    """live_probe/homeplus_dc_행사.json 이 있는 환경에서는 적어도 1행 이상
    dcPrice 가 채워져 있어야 한다 — 진본 라이브 캡처 보장."""
    if not LIVE_DC_PROBE.exists():
        pytest.skip("live_probe/homeplus_dc_행사.json 없음 (gitignored)")
    env = json.loads(LIVE_DC_PROBE.read_text(encoding="utf-8"))
    assert env.get("returnStatus") == 200
    dl = env["data"]["dataList"]
    dc_rows = [r for r in dl if r.get("dcPrice") is not None]
    assert dc_rows, "라이브 캡처에 dcPrice 채워진 행이 0건 — Phase A 미통과"
    assert len(dl) >= 20, "라이브 캡처 행 수 너무 적음 — 페이지네이션 인식 의심"


@pytest.mark.asyncio
async def test_entrypoint_quality_on_dc_mixed_fixture(dc_mixed_raw):
    """4-진입점이 dc 분기 fixture 를 받았을 때 5건 모두 SUCCESS 로 통과."""
    ep = HomeplusEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: dc_mixed_raw)
    assert result.status.name == "SUCCESS"
    assert result.items_count == 5
    # 누락률: sale_price 채워진 비율 100%
    filled = sum(1 for it in result.items if it["sale_price"] > 0)
    assert filled == 5


# ---------- plugin.yaml 측정 기반 회귀 게이트 ----------
def test_plugin_yaml_minimum_rows_is_measurement_based():
    """plugin.yaml minimum_rows 가 실 라이브 측정(N=544) 기반 435 이상인지 검증.

    목적: cap(300) 기반 가짜 minimum_rows(195) 로 회귀하지 않도록 방지.
    기준: live-run-20260524T192330.json — N=544, floor(N×0.80)=435
    """
    import yaml
    import pathlib
    plugin_yaml_path = pathlib.Path(__file__).parent.parent / "crawlers" / "marts" / "homeplus" / "plugin.yaml"
    assert plugin_yaml_path.exists(), f"plugin.yaml 없음: {plugin_yaml_path}"
    config = yaml.safe_load(plugin_yaml_path.read_text(encoding="utf-8"))
    minimum_rows = config["output"]["minimum_rows"]
    max_items = config["source_map"]["max_items"]
    # N=544 기반: minimum_rows=435, max_items=653
    # 회귀 방지: cap(300) 기반 가짜값(195) 재진입 금지
    assert minimum_rows >= 435, (
        f"minimum_rows={minimum_rows} 가 실 측정 기반 435 미만. "
        f"cap(300)×0.65=195 수준으로 회귀 금지. live-run-20260524T192330.json 참조."
    )
    assert max_items >= 653, (
        f"max_items={max_items} 가 실 측정 기반 653 미만. "
        f"N=544, ceil(N×1.2)=653 이 최솟값."
    )


def test_plugin_yaml_measurement_override_env_documented():
    """plugin.yaml 에 측정 실행 환경변수 override 경로가 명시돼 있는지 검증."""
    import yaml
    import pathlib
    plugin_yaml_path = pathlib.Path(__file__).parent.parent / "crawlers" / "marts" / "homeplus" / "plugin.yaml"
    config = yaml.safe_load(plugin_yaml_path.read_text(encoding="utf-8"))
    source_map = config.get("source_map", {})
    assert "measurement_override_env" in source_map, (
        "source_map.measurement_override_env 가 plugin.yaml 에 없음. "
        "운영 cap 유지하며 측정 실행 경로(HOMEPLUS_MEASUREMENT_MAX_ITEMS)를 문서화해야 함."
    )


def test_homeplus_crawler_measurement_env_overrides_max_items():
    """HOMEPLUS_MEASUREMENT_MAX_ITEMS=5000 시 MAX_ITEMS=5000 으로 적용되는지 확인."""
    import os
    from crawlers.marts.homeplus.crawler import HomeplusCrawler

    old = os.environ.pop("HOMEPLUS_MEASUREMENT_MAX_ITEMS", None)
    try:
        os.environ["HOMEPLUS_MEASUREMENT_MAX_ITEMS"] = "5000"
        crawler = HomeplusCrawler()
        assert crawler.MAX_ITEMS == 5000, f"MAX_ITEMS={crawler.MAX_ITEMS} (expected 5000)"

        os.environ["HOMEPLUS_MEASUREMENT_MAX_ITEMS"] = "0"
        crawler2 = HomeplusCrawler()
        assert crawler2.MAX_ITEMS is None, f"MAX_ITEMS={crawler2.MAX_ITEMS} (expected None for cap 해제)"

        os.environ["HOMEPLUS_MEASUREMENT_MAX_ITEMS"] = "none"
        crawler3 = HomeplusCrawler()
        assert crawler3.MAX_ITEMS is None, f"MAX_ITEMS={crawler3.MAX_ITEMS} (expected None)"
    finally:
        if old is None:
            os.environ.pop("HOMEPLUS_MEASUREMENT_MAX_ITEMS", None)
        else:
            os.environ["HOMEPLUS_MEASUREMENT_MAX_ITEMS"] = old

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
