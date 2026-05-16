"""롯데마트 entrypoints — TDD regression against the operator-capture slim fixture.

Fixture provenance
------------------
``tests/fixtures/lottemart/operator_capture_3cards.html`` mirrors the
live-verified ``__INITIAL_STATE__.data.products.productEntities`` shape
that is already asserted by
``tests/test_mart_crawlers.py::TestLottemart::test_initial_state_preserves_count_and_source_owned_fields``
and ``...::test_lottemart_saved_json_envelope_parses_nested_state_and_product_rows``.

The public PC SSR captures saved in ``tests/fixtures/live_probe/lottemart_zetta_*.html``
(395 KB ~ 1.7 MB each, real lottemartzetta.com responses) all contain the
``__INITIAL_STATE__`` marker but their ``productEntities`` are empty — the
storefront ships a SPA shell and loads products via XHR after page load.
The lottemart entrypoints surface this honestly: ``crawl_sale_listing`` and
``crawl_catalog_page`` return a PARTIAL result with an
``empty_initial_state_spa_shell`` blocker, while
``ingest_operator_capture`` (the only path that actually carries data)
parses the same productEntity shape end-to-end.
"""

from __future__ import annotations

import pathlib

import pytest

from crawlers.marts.entry_points import CollectionPath, CrawlIntent
from crawlers.marts.lottemart.crawler import LottemartCrawler
from crawlers.marts.lottemart.entrypoints import LottemartEntrypoints, SALE_QUERY


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "lottemart" / "operator_capture_3cards.html"
LIVE_SHELL_DIR = pathlib.Path(__file__).parent / "fixtures" / "live_probe"
LIVE_SHELL_CANDIDATES = [
    "lottemart_zetta_promotions.html",
    "lottemart_zetta_best.html",
    "lottemart_zetta_search_sale.html",
    "lottemart_zetta_one_plus_one.html",
    "lottemart_zetta_browse_root.html",
    "lottemart_main.html",
]


@pytest.fixture
def html() -> str:
    assert FIXTURE.exists(), f"missing slim fixture: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def crawler() -> LottemartCrawler:
    return LottemartCrawler()


# ---------- 파서 회귀 (productEntity shape 보존) ----------
@pytest.mark.asyncio
async def test_parse_extracts_three_real_entities(crawler, html):
    items = await crawler.parse(html)
    assert len(items) == 3, f"슬림 fixture 3개 카드 — 실제 {len(items)}"


@pytest.mark.asyncio
async def test_parse_water_card_carries_real_fields(crawler, html):
    items = await crawler.parse(html)
    water = next(i for i in items if "생수" in i.name)
    assert water.sale_price == 2990
    assert water.original_price == 3990
    assert water.detail_url == "https://lottemartzetta.com/products/lzt-water-2L6"
    assert water.category == "생수/음료"
    assert water.event_name == "주간특가"
    assert water.attributes["source_record_key"] == "lzt-water-2L6"
    assert water.attributes["category_path"] == ["생수/음료", "생수"]


@pytest.mark.asyncio
async def test_parse_strips_promo_prefix_bracket(crawler, html):
    items = await crawler.parse(html)
    laundry = next(i for i in items if "테크" in i.name)
    assert not laundry.name.startswith("["), f"프로모션 접두사가 제거되어야 함: {laundry.name!r}"


@pytest.mark.asyncio
async def test_parse_no_phantom_zero_prices(crawler, html):
    items = await crawler.parse(html)
    for it in items:
        assert it.sale_price > 0
        assert it.original_price is None or it.original_price >= it.sale_price


# ---------- 4 entrypoints ----------
@pytest.mark.asyncio
async def test_ingest_operator_capture_tags_capture_id_and_path(html):
    ep = LottemartEntrypoints()
    result = await ep.ingest_operator_capture(
        html,
        source_url="https://lottemartzetta.com/search?query=할인",
        capture_id="op-lottemart-001",
    )
    assert result.status.name == "SUCCESS"
    assert result.items_count == 3
    for it in result.items:
        assert it["attributes"]["collection_path"] == CollectionPath.OPERATOR_CAPTURE.value
        assert it["attributes"]["operator_capture_id"] == "op-lottemart-001"
    assert result.quality_details["operator_capture"] is True
    assert result.quality_details["source_host"] == "lottemartzetta.com"


@pytest.mark.asyncio
async def test_sale_listing_tags_public_endpoint_and_sale_intent(html):
    ep = LottemartEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: html)
    assert result.status.name == "SUCCESS"
    assert result.items_count == 3
    for it in result.items:
        assert it["attributes"]["collection_path"] == "public_endpoint"
        assert it["attributes"]["crawl_intent"] == "sale"
    from urllib.parse import quote
    assert quote(SALE_QUERY) in result.quality_details["entrypoint"]["source_url"]


@pytest.mark.asyncio
async def test_catalog_page_tags_catalog_intent(html):
    ep = LottemartEntrypoints()
    result = await ep.crawl_catalog_page("우유", page=2, fetch=lambda url: html)
    assert result.items_count == 3
    assert result.quality_details["query"] == "우유"
    assert result.quality_details["page"] == 2
    for it in result.items:
        assert it["attributes"]["collection_path"] == "catalog_page"
        assert it["attributes"]["crawl_intent"] == "catalog"


@pytest.mark.asyncio
async def test_fetch_single_product_uses_zetta_products_url(html):
    ep = LottemartEntrypoints()
    by_id = await ep.fetch_single_product("lzt-water-2L6", fetch=lambda url: html)
    assert "products/lzt-water-2L6" in by_id.quality_details["entrypoint"]["source_url"]
    assert by_id.items_count == 3
    for it in by_id.items:
        assert it["attributes"]["collection_path"] == "single_product"
        assert it["attributes"]["crawl_intent"] == "refresh"


# ---------- SPA-셸 / WAF 정직 진단 ----------
@pytest.mark.asyncio
async def test_sale_listing_against_real_spa_shell_either_yields_items_or_partial_blocker():
    """공개 PC SSR 캡처: productEntities 가 비어 있어도 SPA card HTML fallback
    파서가 아이템을 회수할 수 있다. 둘 중 어느 경로든 결과는 정직해야 한다:
      • items_count > 0  → status=SUCCESS, 모든 item 에 collection_path 태그.
      • items_count = 0  → status≠SUCCESS, errors 에 명시적 blocker.
    """
    shell_html = None
    for name in LIVE_SHELL_CANDIDATES:
        p = LIVE_SHELL_DIR / name
        if p.exists():
            shell_html = p.read_text(encoding="utf-8", errors="ignore")
            break
    if shell_html is None:
        pytest.skip("라이브 SPA 셸 캡처 없음 (live_probe/ 미존재) — gitignored 환경")
    assert "__INITIAL_STATE__" in shell_html

    ep = LottemartEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: shell_html)
    if result.items_count > 0:
        assert result.status.name == "SUCCESS"
        for it in result.items:
            assert it["attributes"]["collection_path"] == "public_endpoint"
            assert it["attributes"].get("source_record_key")
    else:
        assert result.status.name in {"FAILED", "PARTIAL"}
        assert result.errors
        msg = result.errors[0].error_msg
        assert (
            "empty_initial_state_spa_shell" in msg
            or "aws_waf_http_202" in msg
            or "no_initial_state_marker" in msg
        )


@pytest.mark.asyncio
async def test_aws_waf_202_diagnostic_message_is_precise():
    """롯데마트 WAF 202 챌린지를 그대로 받았을 때 blocker 가 정확해야 한다."""
    waf_html = "<html><head><title>aws-waf-token</title></head><body>awswaf challenge</body></html>"
    ep = LottemartEntrypoints()
    result = await ep.crawl_catalog_page("우유", fetch=lambda url: waf_html)
    assert result.items_count == 0
    assert result.errors
    assert "aws_waf_http_202" in result.errors[0].error_msg


# ---------- 모델 quirk 준수 ----------
@pytest.mark.asyncio
async def test_crawl_result_uses_finished_at_and_quality_details(html):
    ep = LottemartEntrypoints()
    result = await ep.ingest_operator_capture(
        html, source_url="https://lottemartzetta.com/search?query=할인",
    )
    assert result.finished_at is not None
    assert "quality_details" in result.model_dump()
    # items 는 dict 직렬화돼야 함 — 모델 quirk
    assert all(isinstance(it, dict) for it in result.items)
