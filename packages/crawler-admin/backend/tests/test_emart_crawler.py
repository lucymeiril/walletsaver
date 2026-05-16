"""Emart crawler — TDD regression against the slim live-capture fixture.

Fixture provenance
------------------
``tests/fixtures/emart/sale_listing_5cards.html`` and ``.json`` were
extracted from the real live capture
``tests/fixtures/live_probe/emart_search.html`` (1.4 MB, search?query=행사,
captured 2026-05-16 from https://emart.ssg.com — Next.js SSR with a real
``__NEXT_DATA__`` payload). The slim file keeps only 5 ``dataList`` items
plus the original JSON wrapping so that ``EmartCrawler.parse`` (which
walks ``props.pageProps.dehydratedState.queries[*].state.data.areaList``)
recognises it byte-for-byte the same way it recognises a live response.

The five products are real SSG items (itemId 1000641687348 등) so any
selector / contract change against the live site breaks this regression.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from crawlers.marts.emart.crawler import EmartCrawler
from crawlers.marts.emart.entrypoints import EmartEntrypoints, SALE_QUERY
from crawlers.marts.entry_points import CollectionPath, CrawlIntent


FIXTURE_HTML = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.html"
FIXTURE_JSON = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.json"


@pytest.fixture
def html() -> str:
    assert FIXTURE_HTML.exists(), f"missing slim live fixture: {FIXTURE_HTML}"
    return FIXTURE_HTML.read_text(encoding="utf-8")


@pytest.fixture
def crawler() -> EmartCrawler:
    return EmartCrawler()


# ---------- 파서 회귀 ----------
@pytest.mark.asyncio
async def test_parse_extracts_five_real_items_from_next_data(crawler, html):
    items = await crawler.parse(html)
    assert len(items) == 5, f"슬림 fixture에는 5개 카드만 있어야 함 (실제 {len(items)})"


@pytest.mark.asyncio
async def test_parse_first_item_has_real_name_price_and_detail_url(crawler, html):
    items = await crawler.parse(html)
    first = next(i for i in items if "양배추" in i.name)
    assert first.sale_price == 2784
    assert first.original_price == 3480
    assert first.detail_url.endswith("itemId=1000641687348&siteNo=7009&salestrNo=2551")
    assert first.image_url.startswith("https://sitem.ssgcdn.com/")


@pytest.mark.asyncio
async def test_parse_emits_source_record_key_for_dedupe(crawler, html):
    items = await crawler.parse(html)
    keys = [i.attributes.get("source_record_key") for i in items]
    assert all(keys), "every item must carry source_record_key for incremental dedupe"
    assert len(set(keys)) == len(keys), "source_record_key must be unique per item"


@pytest.mark.asyncio
async def test_parse_no_phantom_zero_prices(crawler, html):
    items = await crawler.parse(html)
    # 가격이 진짜 fixture에 들어있는 값과 일치해야 한다 — 0원/빈문자열 채우기 금지.
    raw = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    fixture_prices = {
        int(p["finalPrice"].replace(",", ""))
        for p in raw["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["areaList"][0]["dataList"]
    }
    parsed_prices = {i.sale_price for i in items}
    assert parsed_prices == fixture_prices


# ---------- 4 entrypoints ----------
@pytest.mark.asyncio
async def test_sale_listing_tags_public_endpoint_and_sale_intent(html):
    ep = EmartEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: html)
    assert result.status.name == "SUCCESS"
    assert result.items_count == 5
    for it in result.items:
        assert it["attributes"]["collection_path"] == CollectionPath.PUBLIC_ENDPOINT.value
        assert it["attributes"]["crawl_intent"] == CrawlIntent.SALE.value
    qd = result.quality_details["entrypoint"]
    assert qd["collection_path"] == "public_endpoint"
    from urllib.parse import quote
    assert quote(SALE_QUERY) in qd["source_url"]


@pytest.mark.asyncio
async def test_catalog_page_tags_catalog_intent_and_page_query(html):
    ep = EmartEntrypoints()
    result = await ep.crawl_catalog_page("과일", page=2, fetch=lambda url: html)
    assert result.items_count == 5
    assert result.quality_details["query"] == "과일"
    assert result.quality_details["page"] == 2
    for it in result.items:
        assert it["attributes"]["collection_path"] == "catalog_page"
        assert it["attributes"]["crawl_intent"] == "catalog"


@pytest.mark.asyncio
async def test_fetch_single_product_accepts_item_id_or_url(html):
    ep = EmartEntrypoints()
    by_id = await ep.fetch_single_product("1000641687348", fetch=lambda url: html)
    assert "itemId=1000641687348" in by_id.quality_details["entrypoint"]["source_url"]
    by_url = await ep.fetch_single_product("https://emart.ssg.com/item/itemView.ssg?itemId=1000641687348", fetch=lambda url: html)
    assert by_url.items_count >= 1
    for it in by_id.items:
        assert it["attributes"]["collection_path"] == "single_product"
        assert it["attributes"]["crawl_intent"] == "refresh"


@pytest.mark.asyncio
async def test_ingest_operator_capture_tags_capture_id_and_path(html):
    ep = EmartEntrypoints()
    result = await ep.ingest_operator_capture(
        html,
        source_url="https://emart.ssg.com/search.ssg?query=행사",
        capture_id="op-emart-001",
    )
    assert result.items_count == 5
    for it in result.items:
        assert it["attributes"]["collection_path"] == "operator_capture"
        assert it["attributes"]["operator_capture_id"] == "op-emart-001"
    assert result.quality_details["operator_capture"] is True
    assert result.quality_details["source_host"] == "emart.ssg.com"


# ---------- 회귀 / 모델 quirk 준수 ----------
@pytest.mark.asyncio
async def test_validate_does_not_pad_with_zero_or_short_names(crawler, html):
    items = await crawler.parse(html)
    valid = await crawler.validate(items)
    assert all(i.sale_price > 0 for i in valid)
    assert all(len(i.name) >= 2 for i in valid)
    # validate 는 누락된 가격을 만들어 채우지 않음 — 길이가 줄지언정 늘지는 않는다.
    assert len(valid) <= len(items)


@pytest.mark.asyncio
async def test_pagination_signal_preserved_in_next_data(crawler, html):
    """fixture 안의 ``hasNext: true`` / ``moreUrl`` 가 살아있어 카탈로그 다음 페이지 진입이 가능함을 인지한다."""
    assert '"hasNext": true' in html
    assert "/api/item/all" in html  # next-page hint
    items = await crawler.parse(html)
    # parser 가 5개 다 살림 → 다음 페이지 호출은 entrypoints layer 의 책임.
    assert len(items) == 5


@pytest.mark.asyncio
async def test_crawl_result_uses_finished_at_not_ended_at(html):
    ep = EmartEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: html)
    assert result.finished_at is not None
    # 모델 quirk: ended_at / metadata 필드는 없다.
    assert not hasattr(result, "ended_at")
    assert "quality_details" in result.model_dump()
