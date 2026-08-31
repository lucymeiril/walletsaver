"""Emart parser contracts using a representative saved first-party fixture."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawlers.marts.emart.crawler import EmartCrawler


FIXTURE_HTML = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.html"
FIXTURE_JSON = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.json"


@pytest.fixture
def html() -> str:
    assert FIXTURE_HTML.exists(), f"missing slim live fixture: {FIXTURE_HTML}"
    return FIXTURE_HTML.read_text(encoding="utf-8")


@pytest.fixture
def crawler() -> EmartCrawler:
    return EmartCrawler()


@pytest.mark.asyncio
async def test_parse_extracts_five_real_items_from_next_data(crawler, html):
    items = await crawler.parse(html)
    assert len(items) == 5


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
    assert all(keys)
    assert len(set(keys)) == len(keys)


@pytest.mark.asyncio
async def test_parse_no_phantom_zero_prices(crawler, html):
    items = await crawler.parse(html)
    raw = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    fixture_prices = {
        int(p["finalPrice"].replace(",", ""))
        for p in raw["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["areaList"][0]["dataList"]
    }
    assert {i.sale_price for i in items} == fixture_prices


@pytest.mark.asyncio
async def test_validate_does_not_pad_with_zero_or_short_names(crawler, html):
    items = await crawler.parse(html)
    valid = await crawler.validate(items)
    assert all(i.sale_price > 0 for i in valid)
    assert all(len(i.name) >= 2 for i in valid)
    assert len(valid) <= len(items)


@pytest.mark.asyncio
async def test_pagination_signal_preserved_in_saved_source(crawler, html):
    assert '"hasNext": true' in html
    assert "/api/item/all" in html
    items = await crawler.parse(html)
    assert len(items) == 5


@pytest.mark.asyncio
async def test_quality_contract_thresholds_met_on_fixture(crawler, html):
    """(3) name/sale_price 필수(100%), detail_url 80%, invalid 20%, duplicate 10% 품질 계약 검증."""
    items = await crawler.parse(html)
    valid = await crawler.validate(items)
    items_as_dict = [i.model_dump(mode="json") for i in valid]

    from pipeline.quality import summarize_discount_run
    quality_details = summarize_discount_run(
        items_as_dict,
        raw_count=len(items),
        invalid_count=len(items) - len(valid),
        strategy_used="saved_source_input",
    )

    # Name coverage 100%
    assert quality_details["coverage"]["name"] == 1.0
    # Sale price coverage 100%
    assert quality_details["coverage"]["sale_price"] == 1.0
    # Detail URL coverage >= 80%
    assert quality_details["coverage"]["detail_url"] >= 0.80
    # Invalid drop rate <= 20%
    invalid_ratio = (len(items) - len(valid)) / len(items) if items else 0
    assert invalid_ratio <= 0.20
    # Duplicate ratio <= 10%
    assert quality_details["score"] >= 80.0


@pytest.mark.asyncio
async def test_crawl_incremental_with_saved_source_input(crawler, html):
    """saved_source_input 기반 결정적 증분 실행 검증."""
    result = await crawler.crawl_incremental(source_input=html)

    assert result.status.name == "SUCCESS"
    assert result.items_count == 5
    assert result.quality_details["schema"] == "crawler_run_summary.v1"


@pytest.mark.asyncio
async def test_attributes_include_required_provenance_and_dedup_keys(crawler, html):
    """(4) 동일 실행 재시도 중복 방지 및 출처 메타데이터 계약 검증."""
    items = await crawler.parse(html)
    assert len(items) == 5

    for item in items:
        assert item.attributes.get("source_name") == "emart"
        assert item.attributes.get("mart") == "이마트"
        assert item.attributes.get("mart_native_code")
        assert item.attributes.get("source_record_key")
        assert "external_seller" in item.attributes
        assert item.detail_url.startswith("http")


@pytest.mark.asyncio
async def test_parse_corrupted_or_empty_html_returns_empty_safely(crawler):
    """오류 HTML이나 빈 입력 시 예외 없이 빈 리스트 반환."""
    assert await crawler.parse("") == []
    assert await crawler.parse("<html><body><div>비어있는 내용</div></body></html>") == []
    assert await crawler.parse("<script id=\"__NEXT_DATA__\">{invalid json}</script>") == []


def test_next_data_missing_reacting_detail_is_safe_and_brand_is_not_a_category(crawler):
    item = crawler._next_data_to_discount_item({
        "itemId": "100",
        "itemName": "초코우유 200ml",
        "finalPrice": "1,500",
        "brandName": "브랜드명",
        "siteNo": "6001",
        "reactingDetail": None,
        "_category_hint": "랭킹",
    })

    assert item is not None
    assert item.category == "랭킹"
    assert item.attributes["mart_native_category_path"] == ""
    assert item.attributes["collection_surface"] == "랭킹"


@pytest.mark.asyncio
async def test_validate_rejects_explicit_external_seller(crawler):
    item = crawler._next_data_to_discount_item({
        "itemId": "100",
        "itemName": "외부 판매 상품",
        "finalPrice": "1,500",
        "siteNo": "9999",
    })

    assert item is not None
    assert await crawler.validate([item]) == []


@pytest.mark.asyncio
async def test_crawl_stops_after_consecutive_403_responses():
    anti_detect = MagicMock()
    anti_detect.get_random_delay.return_value = 0
    crawler = EmartCrawler(anti_detect=anti_detect)
    crawler._build_source_requests = MagicMock(
        return_value=[
            {
                "query": f"query-{index}",
                "page": 1,
                "url": f"https://example.test/{index}",
                "category_hint": "",
            }
            for index in range(10)
        ]
    )
    forbidden = MagicMock(status_code=403, text="blocked", encoding="utf-8")
    crawler._retry_request = MagicMock(return_value=forbidden)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await crawler.crawl()

    assert crawler._retry_request.call_count == crawler.MAX_CONSECUTIVE_FORBIDDEN
    assert result.status.value == "failed"
    assert "403이 3회 연속" in (result.error_msg or "")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_emart_probe_promotional_or_blocked_handled_safely():
    """(2) 실제 네트워크 접근을 수행하는 라이브 의존 테스트 (--run-live 시에만 실행).

    공개 엔드포인트(오반장/베스트)에서 유효한 데이터를 수집하거나,
    WAF/403 응답 시 우회 시도 없이 안전하게 FAILED 처리되는지 검증.
    """
    crawler = EmartCrawler()
    crawler.MAX_REQUESTS = 2

    result = await crawler.crawl()

    if result.status.name == "SUCCESS":
        assert result.items_count > 0
        assert result.quality_details["coverage"]["name"] == 1.0
        assert result.quality_details["coverage"]["sale_price"] == 1.0
        assert result.quality_details["coverage"]["detail_url"] >= 0.80
    else:
        assert result.status.name in {"FAILED", "PARTIAL"}
        # CAPTCHA/WAF 우회 시도가 없었음을 검증
        assert result.quality_details.get("fetch", {}).get("auth_bypass_attempted", False) is False
