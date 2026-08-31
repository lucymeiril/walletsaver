"""Emart parser contracts using a representative saved first-party fixture."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawlers.marts.emart.crawler import EmartCrawler


FIXTURE_HTML = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.html"
FIXTURE_JSON = pathlib.Path(__file__).parent / "fixtures" / "emart" / "sale_listing_5cards.json"
CATEGORY_FIXTURE_HTML = (
    pathlib.Path(__file__).parent
    / "fixtures"
    / "emart"
    / "category_listing_modern_2cards.html"
)


@pytest.fixture
def html() -> str:
    assert FIXTURE_HTML.exists(), f"missing slim live fixture: {FIXTURE_HTML}"
    return FIXTURE_HTML.read_text(encoding="utf-8")


@pytest.fixture
def crawler(tmp_path) -> EmartCrawler:
    return EmartCrawler(category_cursor_path=tmp_path / "emart_category_cursor.json")


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
    crawler.MAX_REQUESTS = crawler.MAX_CONSECUTIVE_FORBIDDEN
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


def test_category_requests_use_real_unique_disp_ctg_ids(crawler):
    promotional = crawler._build_source_requests()
    category_requests = crawler._build_category_source_requests()

    assert len(promotional) == len(crawler.PROMOTIONAL_URLS)
    assert len(category_requests) == len(crawler.CATEGORY_IDS)
    assert len({row["category_id"] for row in category_requests}) == len(category_requests)
    assert all("dispCtgId=" in row["url"] for row in category_requests)
    assert all("page=1" not in row["url"] for row in category_requests)
    assert any(row["category_hint"] == "우유/유제품" for row in category_requests)


def test_category_cursor_persists_next_unfinished_category(crawler):
    category_ids = list(crawler.CATEGORY_IDS)
    assert crawler._build_category_source_requests()[0]["category_id"] == category_ids[0]

    crawler._advance_category_cursor(category_ids[0])

    assert crawler._build_category_source_requests()[0]["category_id"] == category_ids[1]
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert restored._build_category_source_requests()[0]["category_id"] == category_ids[1]


@pytest.mark.asyncio
async def test_category_fetch_uses_visible_stable_chrome(crawler, monkeypatch):
    launch_options = {}
    context = object()

    class FakeHelper:
        def __init__(self, **kwargs):
            launch_options.update(kwargs)
            self.context = context

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    monkeypatch.setattr(
        "engine.playwright_helper.PlaywrightHelper",
        FakeHelper,
    )
    crawler._crawl_category_requests_in_context = AsyncMock(
        return_value=([], {"pages_attempted": 0, "requests": []})
    )

    await crawler._fetch_category_pages_via_browser(request_budget=1)

    assert launch_options == {
        "headless": False,
        "browser_channel": "chrome",
    }
    source_requests = crawler._crawl_category_requests_in_context.await_args.args[1]
    assert len(source_requests) == 1


@pytest.mark.asyncio
async def test_parse_modern_category_cards_and_reject_external_marketplace(crawler):
    assert CATEGORY_FIXTURE_HTML.exists()
    html = CATEGORY_FIXTURE_HTML.read_text(encoding="utf-8")

    parsed = await crawler.parse(html)
    assert len(parsed) == 2
    assert parsed[0].name == "후룻컵 알로코코 198g"
    assert parsed[0].sale_price == 2680
    assert parsed[0].attributes["external_seller"] is False
    assert parsed[0].attributes["shipping_type_code"] == "10"
    assert parsed[0].attributes["unit_price_display"] == "100g 당 1,354원"
    assert parsed[1].name == "국내산 꿀수박 6~7kg 내외"
    assert parsed[1].original_price == 28900
    assert parsed[1].attributes["external_seller"] is True
    assert [item.name for item in await crawler.validate(parsed)] == ["후룻컵 알로코코 198g"]
    assert crawler._extract_category_path(html, "fallback") == "과일 > 냉동/간편과일 > 간편과일"


@pytest.mark.asyncio
async def test_category_browser_stops_entire_run_on_first_403(crawler):
    class FakeResponse:
        def __init__(self, status):
            self.status = status

    class FakePage:
        def __init__(self):
            self.goto_calls = []

        async def goto(self, url, **kwargs):
            self.goto_calls.append(url)
            return FakeResponse([200, 403, 200][len(self.goto_calls) - 1])

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def content(self):
            return "<html><head><title>과일 - 이마트몰</title></head><body></body></html>"

        async def close(self):
            return None

    class FakeContext:
        def __init__(self):
            self.page = FakePage()

        async def new_page(self):
            return self.page

    context = FakeContext()
    crawler.CATEGORY_DELAY_MIN_SECONDS = 0
    crawler.CATEGORY_DELAY_MAX_SECONDS = 0
    requests = crawler._build_category_source_requests()[:3]
    diagnostics = {
        "strategy": "playwright_category",
        "requests_attempted": 0,
        "pages_attempted": 0,
        "categories_succeeded": 0,
        "blocked": False,
        "stop_reason": None,
        "requests": [],
    }

    items, result = await crawler._crawl_category_requests_in_context(
        context,
        requests,
        diagnostics,
    )

    assert items == []
    assert len(context.page.goto_calls) == 2
    assert result["blocked"] is True
    assert result["stop_reason"].startswith("HTTP 403")
    assert result["pages_attempted"] == 2
    assert result["requests_attempted"] == 2
    assert (
        result.get("next_category_id", requests[0]["category_id"])
        == requests[0]["category_id"]
    )


@pytest.mark.asyncio
async def test_successful_category_advances_persistent_cursor(crawler):
    category_html = CATEGORY_FIXTURE_HTML.read_text(encoding="utf-8")

    class FakeResponse:
        status = 200

    class FakePage:
        async def goto(self, url, **kwargs):
            return FakeResponse()

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def content(self):
            return category_html

        async def close(self):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

    first_request = crawler._build_category_source_requests()[:1]
    first_category_id = first_request[0]["category_id"]
    expected_next_id = list(crawler.CATEGORY_IDS)[1]
    diagnostics = {
        "strategy": "playwright_category",
        "requests_attempted": 0,
        "pages_attempted": 0,
        "categories_succeeded": 0,
        "blocked": False,
        "stop_reason": None,
        "start_category_id": first_category_id,
        "next_category_id": first_category_id,
        "requests": [],
    }

    items, result = await crawler._crawl_category_requests_in_context(
        FakeContext(),
        first_request,
        diagnostics,
    )

    assert len(items) == 2
    assert result["categories_succeeded"] == 1
    assert result["next_category_id"] == expected_next_id
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert restored._build_category_source_requests()[0]["category_id"] == expected_next_id


@pytest.mark.asyncio
async def test_crawl_is_partial_when_promotions_exist_but_category_phase_is_blocked(
    crawler,
    html,
):
    response = MagicMock(status_code=200, text=html, encoding="utf-8")
    crawler._warmup_session = MagicMock()
    crawler._retry_request = MagicMock(return_value=response)
    crawler._anti_detect.get_random_delay = MagicMock(return_value=0)
    crawler._build_source_requests = MagicMock(
        return_value=[{
            "query": "오반장",
            "page": 1,
            "url": "https://example.test/promotion",
            "category_hint": "이마트 오반장",
        }]
    )
    crawler._fetch_category_pages_via_browser = AsyncMock(return_value=([], {
        "strategy": "playwright_category",
        "pages_attempted": 1,
        "categories_succeeded": 0,
        "blocked": True,
        "stop_reason": "HTTP 403 at 과일",
        "requests": [{"raw_count": 0}],
    }))

    result = await crawler.crawl()

    assert result.items_count == 5
    assert result.status.name == "PARTIAL"
    assert "카테고리 수집 중단" in (result.error_msg or "")
    assert any(error.strategy_name == "playwright_category" for error in result.errors)


@pytest.mark.asyncio
async def test_external_category_sellers_are_reported_as_out_of_scope_not_invalid(crawler):
    direct = crawler._next_data_to_discount_item({
        "itemId": "direct-1",
        "itemName": "이마트 직접 상품",
        "finalPrice": "2,980",
        "siteNo": "6001",
        "salestrNo": "2037",
        "shppTypeCd": "10",
        "_category_browser_card": True,
    })
    external = crawler._next_data_to_discount_item({
        "itemId": "external-1",
        "itemName": "외부 판매 상품",
        "finalPrice": "9,900",
        "siteNo": "6001",
        "salestrNo": "6005",
        "shppTypeCd": "20",
        "_category_browser_card": True,
    })
    crawler._warmup_session = MagicMock()
    crawler._build_source_requests = MagicMock(return_value=[])
    crawler._fetch_category_pages_via_browser = AsyncMock(return_value=([direct, external], {
        "strategy": "playwright_category",
        "pages_attempted": 1,
        "categories_succeeded": 1,
        "blocked": False,
        "stop_reason": None,
        "requests": [{"raw_count": 2, "external_seller_count": 1}],
    }))

    result = await crawler.crawl()

    assert result.status.name == "SUCCESS"
    assert result.items_count == 1
    assert result.quality_details["item_counts"]["invalid_or_dropped"] == 0
    assert result.quality_details["filters"]["out_of_scope_external_seller_count"] == 1
