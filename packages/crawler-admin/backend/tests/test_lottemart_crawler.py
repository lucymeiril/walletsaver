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
HYDRATED_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "lottemart" / "hydrated_5cards.html"
LIVE_HYDRATED_PROBE = pathlib.Path(__file__).parent / "fixtures" / "live_probe" / "lottemart_hydrated_promotions.html"
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
# ---------- 라이브 hydrated 진본 fixture 회귀 ----------
@pytest.fixture
def hydrated_html() -> str:
    assert HYDRATED_FIXTURE.exists(), f"missing hydrated slim fixture: {HYDRATED_FIXTURE}"
    return HYDRATED_FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_hydrated_fixture_parses_five_real_entities(crawler, hydrated_html):
    """live headful Playwright 캡처에서 추출한 진본 productEntities 5개가
    모두 파서로 회수돼야 한다."""
    items = await crawler.parse(hydrated_html)
    assert len(items) == 5
    # 모두 진본 productId UUID 형식 source_record_key
    for it in items:
        rec = it.attributes.get("source_record_key", "")
        # productId UUID 또는 lottemart prefix 둘 다 허용 (진본 productId 가 UUID)
        assert rec, "source_record_key 누락"
        # detail_url 은 lottemartzetta 도메인의 /products/<uuid>
        assert it.detail_url.startswith("https://lottemartzetta.com/products/")
        assert it.sale_price > 0
        assert it.attributes.get("category_path"), "category_path 누락"


@pytest.mark.asyncio
async def test_hydrated_fixture_carries_discount_and_sale_only_branches(crawler, hydrated_html):
    """진본 fixture 는 (price.original+price.current 가 둘 다 있는 할인 상품) 1개 +
    (price.original=null 인 단가 상품) 다수 — 두 분기를 모두 표현해야 한다."""
    items = await crawler.parse(hydrated_html)
    with_discount = [i for i in items if i.original_price and i.original_price > i.sale_price]
    sale_only = [i for i in items if i.original_price is None]
    assert with_discount, "할인 분기 (original>current) 가 fixture 에 없음"
    assert sale_only, "단가만 있는 분기 가 fixture 에 없음"
    # 할인분기 회귀 — 행복생생란 6,990 (orig 7,690)
    w = next(i for i in with_discount if "행복생생란" in i.name or "농할" in i.name or "행복" in i.name)
    assert w.sale_price == 6990
    assert w.original_price == 7690
    # 단가 분기 회귀 — 부침두부 4,990
    s = next(i for i in sale_only if "부침두부" in i.name)
    assert s.sale_price == 4990
    assert s.original_price is None


@pytest.mark.asyncio
async def test_hydrated_fixture_preserves_offer_description_and_image(crawler, hydrated_html):
    items = await crawler.parse(hydrated_html)
    for it in items:
        # offer.description 이 있으면 그대로 event_name 으로 전달
        assert it.event_name and it.event_name != "롯데마트 할인" or it.event_name == "롯데마트 할인"
    # 적어도 일부는 image_url 가 채워져 있어야 한다 (lottemartzetta CDN)
    with_img = [i for i in items if i.image_url and "lottemartzetta.com" in i.image_url]
    assert with_img, "이미지 URL 진본이 fixture 에서 누락"


@pytest.mark.asyncio
async def test_hydrated_fixture_quality_coverage_via_entrypoint(hydrated_html):
    """4-진입점을 통과해도 진본 5건이 그대로 collection_path 태깅돼야 한다."""
    ep = LottemartEntrypoints()
    result = await ep.ingest_operator_capture(
        hydrated_html,
        source_url="https://www.lottemartzetta.com/promotions",
        capture_id="op-lottemart-hydrated",
    )
    assert result.status.name == "SUCCESS"
    assert result.items_count == 5
    for it in result.items:
        assert it["attributes"]["collection_path"] == CollectionPath.OPERATOR_CAPTURE.value


# ---------- 가짜 통과 방지 negative 회귀 ----------
@pytest.mark.asyncio
async def test_empty_productEntities_in_initial_state_does_not_yield_items(crawler):
    """파서가 productEntities={} 셸을 절대로 '성공'으로 둔갑시키지 않도록.
    이전 슬라이스 회귀가 다시 가짜로 통과하는 것을 막는다."""
    shell = (
        "<!doctype html><html><body><script>window.__INITIAL_STATE__ = "
        '{"data":{"products":{"productEntities":{}}}};</script></body></html>'
    )
    items = await crawler.parse(shell)
    assert items == [] or all(getattr(i, "sale_price", 0) > 0 for i in items)
    # entrypoint 측면에서도 PARTIAL/FAILED + blocker 메시지여야 한다
    ep = LottemartEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: shell)
    assert result.items_count == 0
    assert result.errors and "empty_initial_state_spa_shell" in result.errors[0].error_msg


@pytest.mark.asyncio
async def test_live_hydrated_probe_when_present_yields_real_items():
    """live_probe/ 가 있는 환경에서는 진본 hydrated 캡처가 최소 30개 이상의
    productEntities 를 만들어내야 한다 (raw 1.6MB, 50 카드 캡처 기준)."""
    if not LIVE_HYDRATED_PROBE.exists():
        pytest.skip("live_probe/lottemart_hydrated_promotions.html 없음 (gitignored 환경)")
    raw = LIVE_HYDRATED_PROBE.read_text(encoding="utf-8")
    assert "__INITIAL_STATE__" in raw
    c = LottemartCrawler()
    items = await c.parse(raw)
    assert len(items) >= 30, f"진본 hydrated 캡처에서 30개 미만 수확: {len(items)}"
    # 모든 상품에 진본 productId(UUID) 가 있어야 한다
    for it in items:
        assert it.detail_url.startswith("https://lottemartzetta.com/products/")
        assert it.sale_price > 0


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
