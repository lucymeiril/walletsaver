"""Emart parser contracts using a representative saved first-party fixture."""

from __future__ import annotations

import asyncio
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
def crawler(tmp_path, monkeypatch) -> EmartCrawler:
    # Existing persistence/failure tests exercise the minimum interval.
    # The dedicated range test below overrides this deterministic draw.
    monkeypatch.setattr("crawlers.marts.emart.crawler.random.uniform", lambda low, high: low)
    return EmartCrawler(category_cursor_path=tmp_path / "emart_category_cursor.json")


@pytest.fixture
def category_context():
    page = MagicMock(
        goto=AsyncMock(return_value=MagicMock(status=200)),
        wait_for_selector=AsyncMock(),
        content=AsyncMock(return_value="<html><body></body></html>"),
        inner_text=AsyncMock(return_value=""),
        query_selector_all=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )
    return MagicMock(page=page, new_page=AsyncMock(return_value=page))


def _category_diagnostics():
    return {
        "strategy": "playwright_category",
        "requests_attempted": 0,
        "pages_attempted": 0,
        "categories_succeeded": 0,
        "blocked": False,
        "stop_reason": None,
        "requests": [],
    }


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
async def test_crawl_stops_after_first_403_response():
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

    assert crawler._retry_request.call_count == 1
    assert result.status.value == "failed"
    assert "HTTP 403" in (result.error_msg or "")


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
@pytest.mark.parametrize("interval", [360.0, 390.0, 420.0])
async def test_category_interval_draws_six_to_seven_minutes_once_per_attempt(
    crawler, monkeypatch, interval,
):
    clock = [1_000.0]
    sleeps = []
    draw = MagicMock(return_value=interval)
    monkeypatch.setattr("crawlers.marts.emart.crawler.random.uniform", draw)
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await crawler._wait_for_category_request_slot() == 0
    clock[0] += 75
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert await restored._wait_for_category_request_slot() == pytest.approx(interval - 75)
    assert sleeps == [pytest.approx(interval - 75)]
    assert restored._last_category_request_at == pytest.approx(1_000 + interval)
    assert draw.call_count == 2  # No redraw inside the wait loop.
    assert all(call.args == (360.0, 420.0) for call in draw.call_args_list)


@pytest.mark.asyncio
async def test_category_requests_are_spaced_360_seconds_and_saved_before_navigation(
    crawler,
    monkeypatch,
):
    clock = [1_000.0]
    sleeps = []

    monkeypatch.setattr(
        "crawlers.marts.emart.crawler.time.time",
        lambda: clock[0],
    )

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class FakeResponse:
        status = 200

    class FakePage:
        def __init__(self):
            self.goto_times = []

        async def goto(self, url, **kwargs):
            del url, kwargs
            state = json.loads(crawler._category_cursor_path.read_text(encoding="utf-8"))
            persisted_at = crawler._parse_category_request_at(
                state["last_category_request_at"]
            )
            assert persisted_at == pytest.approx(clock[0])
            self.goto_times.append(clock[0])
            return FakeResponse()

        async def wait_for_selector(self, *args, **kwargs):
            del args, kwargs
            return None

        async def content(self):
            return "<html><body></body></html>"

        async def inner_text(self, selector):
            return ""

        async def query_selector_all(self, selector):
            return []

        async def close(self):
            return None

    class FakeContext:
        def __init__(self):
            self.page = FakePage()

        async def new_page(self):
            return self.page

    context = FakeContext()
    requests = crawler._build_category_source_requests()[:2]
    diagnostics = {
        "strategy": "playwright_category",
        "requests_attempted": 0,
        "pages_attempted": 0,
        "categories_succeeded": 0,
        "blocked": False,
        "stop_reason": None,
        "requests": [],
    }

    await crawler._crawl_category_requests_in_context(context, requests, diagnostics)

    assert context.page.goto_times == [1_000.0, 1_360.0]
    assert sleeps == [pytest.approx(360.0)]
    assert diagnostics["requests"][0]["rate_limit_wait_seconds"] == 0
    assert diagnostics["requests"][1]["rate_limit_wait_seconds"] == pytest.approx(360)


@pytest.mark.asyncio
async def test_category_request_cooldown_survives_restart_and_waits_only_remaining(
    crawler,
    monkeypatch,
):
    clock = [10_000.0]
    sleeps = []
    monkeypatch.setattr(
        "crawlers.marts.emart.crawler.time.time",
        lambda: clock[0],
    )

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    first_wait = await crawler._wait_for_category_request_slot()
    assert first_wait == 0
    assert sleeps == []

    clock[0] += 75
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    restart_wait = await restored._wait_for_category_request_slot()

    assert restart_wait == pytest.approx(285)
    assert sleeps == [pytest.approx(285)]
    payload = json.loads(crawler._category_cursor_path.read_text(encoding="utf-8"))
    assert restored._parse_category_request_at(
        payload["last_category_request_at"]
    ) == pytest.approx(10_360)


def test_category_request_slots_share_state_across_instances_and_event_loops(
    crawler, monkeypatch,
):
    clock = [1_000.0]
    saved_times = []
    real_sleep = asyncio.sleep
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])

    async def fake_sleep(seconds):
        clock[0] += seconds
        # Force competing callers to contend, including in a later loop.
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    original_save = EmartCrawler._save_category_cursor

    def record_save(instance, category_id=None, *, required=False):
        original_save(instance, category_id, required=required)
        if required:
            saved_times.append(instance._last_category_request_at)

    monkeypatch.setattr(EmartCrawler, "_save_category_cursor", record_save)
    peer = EmartCrawler(category_cursor_path=crawler._category_cursor_path)

    async def reserve_slots():
        await asyncio.gather(
            crawler._wait_for_category_request_slot(),
            peer._wait_for_category_request_slot(),
            crawler._wait_for_category_request_slot(),
        )

    asyncio.run(reserve_slots())
    asyncio.run(reserve_slots())

    assert len(saved_times) == 6
    assert saved_times[0] == 1_000
    assert all(later - earlier >= 360 for earlier, later in zip(saved_times, saved_times[1:]))


@pytest.mark.asyncio
async def test_late_cursor_advance_preserves_newer_request_timestamp(crawler, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])
    await crawler._wait_for_category_request_slot()
    peer = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    clock[0] += 360
    await peer._wait_for_category_request_slot()

    crawler._advance_category_cursor(next(iter(crawler.CATEGORY_IDS)))

    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert restored._last_category_request_at == pytest.approx(1_360)


@pytest.mark.asyncio
async def test_timestamp_reservation_preserves_another_instances_cursor(crawler, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])
    peer = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    await crawler._wait_for_category_request_slot()
    crawler._advance_category_cursor(next(iter(crawler.CATEGORY_IDS)))
    expected_next_id = crawler._next_category_id

    clock[0] += 360
    await peer._wait_for_category_request_slot()

    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert restored._next_category_id == expected_next_id
    assert restored._last_category_request_at == pytest.approx(1_360)


@pytest.mark.parametrize("failure", [403, 429, "challenge", "network", "cancelled"])
@pytest.mark.asyncio
async def test_failed_category_navigation_keeps_restart_cooldown(
    crawler, category_context, monkeypatch, failure,
):
    clock = [1_000.0]
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])
    if isinstance(failure, int):
        category_context.page.goto.return_value.status = failure
    elif failure == "challenge":
        category_context.page.content.return_value = "<html>access denied</html>"
        category_context.page.inner_text.return_value = "access denied"
    else:
        category_context.page.goto.side_effect = (
            asyncio.CancelledError() if failure == "cancelled" else RuntimeError("network failed")
        )

    first_category_id = crawler._next_category_id
    operation = crawler._crawl_category_requests_in_context(
        category_context,
        crawler._build_category_source_requests()[:1],
        _category_diagnostics(),
    )
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await operation
    else:
        await operation
    category_context.page.close.assert_awaited_once()

    clock[0] += 75
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    assert restored._next_category_id == first_category_id
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await restored._wait_for_category_request_slot() == pytest.approx(285)
    assert sleeps == [pytest.approx(285)]


@pytest.mark.asyncio
async def test_cancelled_cooldown_does_not_claim_slot_or_navigate(
    crawler, category_context, monkeypatch,
):
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: 1_000.0)
    await crawler._wait_for_category_request_slot()
    initial_state = crawler._category_cursor_path.read_text(encoding="utf-8")
    sleep = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(asyncio, "sleep", sleep)
    diagnostics = _category_diagnostics()

    with pytest.raises(asyncio.CancelledError):
        await crawler._crawl_category_requests_in_context(
            category_context, crawler._build_category_source_requests()[:1], diagnostics,
        )

    assert crawler._category_cursor_path.read_text(encoding="utf-8") == initial_state
    assert diagnostics["requests_attempted"] == 0
    category_context.page.goto.assert_not_awaited()
    category_context.page.close.assert_awaited_once()


@pytest.mark.parametrize("state", [
    "{invalid json",
    '{"schema_version": 999, "last_category_request_at": "2026-09-03T00:00:00Z"}',
    '{"schema_version": 1, "last_category_request_at": "2026-09-03T00:00:00"}',
])
@pytest.mark.asyncio
async def test_invalid_throttle_state_fails_closed(crawler, category_context, state):
    crawler._category_cursor_path.write_text(state, encoding="utf-8")

    _, diagnostics = await crawler._crawl_category_requests_in_context(
        category_context, crawler._build_category_source_requests()[:2],
        _category_diagnostics(),
    )

    category_context.page.goto.assert_not_awaited()
    assert "읽을 수 없습니다" in diagnostics["stop_reason"]
    assert diagnostics["requests_attempted"] == 0
    assert len(diagnostics["requests"]) == 1
    assert crawler._category_cursor_path.read_text(encoding="utf-8") == state


@pytest.mark.parametrize("mode", ["full", "selected"])
@pytest.mark.asyncio
async def test_full_and_selected_runs_use_the_persistent_category_cooldown(
    crawler, category_context, monkeypatch, mode,
):
    clock = [1_000.0]
    sleeps = []
    monkeypatch.setattr("crawlers.marts.emart.crawler.time.time", lambda: clock[0])

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    category_context.page.content.return_value = CATEGORY_FIXTURE_HTML.read_text(encoding="utf-8")

    class FakeHelper:
        def __init__(self, **kwargs):
            self.context = category_context

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    monkeypatch.setattr("engine.playwright_helper.PlaywrightHelper", FakeHelper)

    async def run(instance):
        instance._warmup_session = MagicMock()
        instance.MAX_REQUESTS = 1
        if mode == "selected":
            instance._selected_category_request = instance._build_category_source_requests()[0]
            return await instance.crawl_selected_category()
        instance._build_source_requests = MagicMock(return_value=[])
        return await instance.crawl()

    first_result = await run(crawler)
    clock[0] += 75
    restored = EmartCrawler(category_cursor_path=crawler._category_cursor_path)
    second_result = await run(restored)

    assert first_result.status.name == second_result.status.name == "SUCCESS"
    assert category_context.page.goto.await_count == 2
    assert sleeps == [pytest.approx(285)]
    assert second_result.quality_details["category_browser"]["requests"][0][
        "rate_limit_wait_seconds"
    ] == pytest.approx(285)


@pytest.mark.asyncio
async def test_category_request_is_aborted_when_throttle_state_cannot_be_saved(crawler):
    class FakePage:
        def __init__(self):
            self.goto_calls = []

        async def goto(self, url, **kwargs):
            self.goto_calls.append((url, kwargs))
            return MagicMock(status=200)

        async def close(self):
            return None

    class FakeContext:
        def __init__(self):
            self.page = FakePage()

        async def new_page(self):
            return self.page

    context = FakeContext()
    diagnostics = {
        "strategy": "playwright_category",
        "requests_attempted": 0,
        "pages_attempted": 0,
        "categories_succeeded": 0,
        "blocked": False,
        "stop_reason": None,
        "requests": [],
    }

    with patch.object(
        pathlib.Path,
        "replace",
        side_effect=PermissionError("read-only state directory"),
    ):
        _, result = await crawler._crawl_category_requests_in_context(
            context,
            crawler._build_category_source_requests()[:2],
            diagnostics,
        )

    assert context.page.goto_calls == []
    assert "저장할 수 없습니다" in result["stop_reason"]
    assert len(result["requests"]) == 1
    assert result["requests_attempted"] == 0
    assert result["pages_attempted"] == 0
    assert crawler._last_category_request_at is None


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


@pytest.mark.parametrize("blocked_status", [401, 403, 429])
@pytest.mark.asyncio
async def test_category_browser_stops_entire_run_on_first_block_response(
    crawler,
    blocked_status,
):
    class FakeResponse:
        def __init__(self, status):
            self.status = status

    class FakePage:
        def __init__(self):
            self.goto_calls = []

        async def goto(self, url, **kwargs):
            self.goto_calls.append(url)
            return FakeResponse([200, blocked_status, 200][len(self.goto_calls) - 1])

        async def wait_for_selector(self, *args, **kwargs):
            return None

        async def content(self):
            return "<html><head><title>과일 - 이마트몰</title></head><body></body></html>"

        async def inner_text(self, selector):
            return ""

        async def query_selector_all(self, selector):
            return []

        async def close(self):
            return None

    class FakeContext:
        def __init__(self):
            self.page = FakePage()

        async def new_page(self):
            return self.page

    context = FakeContext()
    crawler.CATEGORY_REQUEST_MIN_INTERVAL_SECONDS = 0
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
    assert result["stop_reason"].startswith(f"HTTP {blocked_status}")
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

        async def inner_text(self, selector):
            return "상품 목록"

        async def query_selector_all(self, selector):
            return []

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


@pytest.mark.parametrize("visible_text,blocked", [("상품 목록", False), ("Access denied", True)])
@pytest.mark.asyncio
async def test_category_sdk_is_not_challenge_but_visible_denial_stops(crawler, category_context, monkeypatch, visible_text, blocked):
    html = CATEGORY_FIXTURE_HTML.read_text(encoding="utf-8")
    category_context.page.content.return_value = html + '<script src="awswaf/captcha-sdk.js"></script>'
    category_context.page.inner_text.return_value = visible_text
    monkeypatch.setattr(crawler, "_wait_for_category_request_slot", AsyncMock(return_value=0))
    items, diagnostics = await crawler._crawl_category_requests_in_context(
        category_context, crawler._build_category_source_requests()[:1], _category_diagnostics())
    assert diagnostics["blocked"] is blocked
    assert len(items) == (0 if blocked else 2)
    assert diagnostics["requests_attempted"] == 1
    if blocked:
        assert diagnostics["stop_reason"].startswith("challenge detected:")
    category_context.page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_selected_category_run_skips_promotions_and_records_context(crawler):
    selected = crawler._build_category_source_requests()[0]
    direct_item = crawler._next_data_to_discount_item({
        "itemId": "selected-1",
        "itemName": "선택 카테고리 상품",
        "finalPrice": "2,980",
        "siteNo": "6001",
    })
    assert direct_item is not None
    crawler._selected_category_request = selected

    async def fake_fetch(*, request_budget=None):
        assert crawler._build_source_requests() == []
        assert crawler._build_category_source_requests() == [selected]
        return [direct_item], {
            "strategy": "playwright_category",
            "requests_attempted": 1,
            "pages_attempted": 1,
            "categories_succeeded": 1,
            "blocked": False,
            "stop_reason": None,
            "requests": [{"raw_count": 1}],
        }

    crawler._fetch_category_pages_via_browser = AsyncMock(side_effect=fake_fetch)
    crawler._warmup_session = MagicMock()

    result = await crawler.crawl_selected_category()

    assert result.status.name == "SUCCESS"
    assert result.items_count == 1
    assert result.quality_details["collection"]["mode"] == "selected_category"
    assert result.quality_details["collection"]["selected"]["category_id"] == selected["category_id"]
    assert crawler._selected_category_request is None
    assert crawler._promotional_source_requests_override is None
    assert crawler._category_source_requests_override is None


@pytest.mark.asyncio
async def test_selected_category_run_requires_an_allowlisted_selection(crawler):
    result = await crawler.crawl_selected_category()

    assert result.status.name == "FAILED"
    assert result.items_count == 0
    assert result.quality_details["alerts"] == ["no_emart_category_selected"]


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


@pytest.mark.asyncio
async def test_266_actual_receipt_and_original_business_survive_dto_export(crawler):
    from datetime import datetime, timezone
    import hashlib
    from api.routes.raw_batch_export import _record_to_export_row

    product = {"itemId": "266-source", "itemName": "원문 음료 500ml", "finalPrice": "2190",
               "siteNo": "7009", "priceInfo": {"primaryPrice": "2190", "minimumOrder": 2},
               "purchaseConditions": {"coupon": {"threshold": 70000, "deduction": 4000}},
               "customerToken": "synthetic-private-omitted"}
    body = '<script id="__NEXT_DATA__">' + json.dumps({"props": {"pageProps": {
        "dehydratedState": {"queries": [{"state": {"data": {"itemList": [product]}}}]}}}}) + '</script>'
    stamp = datetime(2026, 10, 6, 7, 0, tzinfo=timezone.utc)
    digest = hashlib.sha256(body.encode()).hexdigest()
    [item] = await crawler.parse(body, response_url="https://emart.ssg.com/source",
                                response_body_sha256=digest, received_at=stamp)
    evidence = item.attributes["submission_business_evidence"][0]
    assert evidence["raw_product_node"]["purchaseConditions"] == product["purchaseConditions"]
    assert "customerToken" not in evidence["raw_product_node"]
    assert evidence["removed_fields"]
    assert evidence["source_pointer"].endswith("/queries/0/state/data/itemList/0")
    assert item.crawled_at == stamp
    dto = item.to_product_price()
    assert dto.crawled_at == stamp and dto.attributes == item.attributes
    record = crawler._emit_item(item)
    row = _record_to_export_row({"raw_payload": record, "crawled_at": record["crawled_at"]}, None, None)
    assert row["raw_payload"]["attributes"]["submission_business_evidence"] == [evidence]
    assert row["crawled_at"] == stamp.isoformat().replace("+00:00", "Z")
    [saved] = await crawler.parse(body)
    assert "crawled_at" not in crawler._emit_item(saved)
    assert saved.attributes["submission_business_evidence"][0]["http_receipt_status"] == "not_recorded"


@pytest.mark.asyncio
async def test_266_html_projection_is_partial_and_browser_transport_is_real(crawler):
    import hashlib
    body = b"actual transport body, distinct from rendered DOM"
    html = '<li class="mnemitem_grid_item"><span class="title">음료 500ml</span><span class="sale_price">2190</span><a href="/item/itemView.ssg?itemId=266-html">상품</a></li>'
    page = MagicMock(goto=AsyncMock(return_value=MagicMock(status=200, url="https://emart.ssg.com/category",
                        body=AsyncMock(return_value=body))), content=AsyncMock(return_value=html),
                     wait_for_selector=AsyncMock(), close=AsyncMock())
    context = MagicMock(new_page=AsyncMock(return_value=page))
    crawler._wait_for_category_request_slot = AsyncMock(return_value=0)
    crawler._advance_category_cursor = MagicMock()
    crawler._category_challenge_marker = AsyncMock(return_value=None)
    items, diagnostics = await crawler._crawl_category_requests_in_context(
        context, crawler._build_category_source_requests()[:1], _category_diagnostics())
    [item] = items
    marker = item.attributes["source_response_metadata"]
    assert marker["source_projection"] == "html_card_projection_only"
    assert marker["native_business_node_status"] == "unavailable"
    assert marker["source_response_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert "submission_business_evidence" not in item.attributes
    assert item.crawled_at.tzinfo is not None and "crawled_at" in crawler._emit_item(item)
    [saved] = await crawler.parse(html)
    assert "crawled_at" not in crawler._emit_item(saved)
    assert saved.attributes["source_response_metadata"]["http_receipt_status"] == "not_recorded"


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.asyncio
async def test_266_promotional_denial_retains_prior_rows_without_browser(crawler, html, status):
    crawler._warmup_session = MagicMock()
    crawler._anti_detect = MagicMock()
    crawler._anti_detect.get_random_delay.return_value = 0
    crawler._build_source_requests = MagicMock(return_value=[
        {"query": "first", "page": 1, "url": "https://emart.ssg.com/first", "category_hint": ""},
        {"query": "denied", "page": 1, "url": "https://emart.ssg.com/denied", "category_hint": ""},
        {"query": "must-not-request", "page": 1, "url": "https://emart.ssg.com/later", "category_hint": ""}])
    crawler._retry_request = MagicMock(side_effect=[
        MagicMock(status_code=200, text=html, content=html.encode(), url="https://emart.ssg.com/first"),
        MagicMock(status_code=status, text="denied")])
    crawler._fetch_category_pages_via_browser = AsyncMock()
    result = await crawler.crawl()
    assert result.status.name == "PARTIAL" and result.items_count == 5
    assert crawler._retry_request.call_count == 2
    crawler._fetch_category_pages_via_browser.assert_not_awaited()
    assert f"HTTP {status}" in result.error_msg
    assert all("crawled_at" in row for row in result.items)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_266_explicit_denial_never_retries_or_warms_again(crawler, status):
    from crawlers.marts.emart.crawler import _SourceAccessStopped
    response = MagicMock(status_code=status, text="denied")
    session = MagicMock(get=MagicMock(return_value=response))
    with patch("time.sleep") as sleep:
        assert crawler._retry_request("https://emart.ssg.com/source", session=session) is response
        session.get.assert_called_once()
        sleep.assert_not_called()
        # Plain object prevents the historical test-Mock warmup bypass.
        crawler._anti_detect = object()
        crawler._get_session = MagicMock(return_value=session)
        with pytest.raises(_SourceAccessStopped, match=f"HTTP {status}"):
            crawler._warmup_session()
        assert not crawler._session_warmed
        sleep.assert_not_called()


def test_266_visible_challenge_not_sdk_string(crawler):
    assert crawler._html_challenge_marker('<script>captchaSDK(); access denied</script><body>상품</body>') is None
    assert crawler._html_challenge_marker('<body>Verify you are human</body>')


@pytest.mark.asyncio
async def test_266_partial_card_json_and_naive_receipt_remain_unconfirmed(crawler):
    from datetime import datetime
    from bs4 import BeautifulSoup
    import hashlib
    html = CATEGORY_FIXTURE_HTML.read_text()
    [first, *others] = await crawler.parse(html, response_url="https://emart.ssg.com/category",
        response_body_sha256=hashlib.sha256(html.encode()).hexdigest(), received_at=datetime(2026, 10, 6))
    original = json.loads(BeautifulSoup(html, "html.parser").select_one(".disp_cart_data").get_text())
    evidence = first.attributes["submission_business_evidence"][0]
    assert evidence["raw_product_node"] == original
    assert evidence["source_node_scope"] == "available_card_declaration_partial"
    assert evidence["purchase_declaration_completeness"] == "unconfirmed"
    assert evidence["http_receipt_status"] == "not_recorded"
    assert evidence["source_response_received_at"] is None
    assert "crawled_at" not in crawler._emit_item(first)


@pytest.mark.asyncio
async def test_266_warmup_denial_ends_whole_empty_source(crawler):
    crawler._anti_detect = object()
    crawler._get_session = MagicMock(return_value=MagicMock(get=MagicMock(
        return_value=MagicMock(status_code=429, text="denied"))))
    crawler._build_source_requests = MagicMock()
    crawler._retry_request = MagicMock()
    crawler._fetch_category_pages_via_browser = AsyncMock()
    with patch("time.sleep") as sleep:
        result = await crawler.crawl()
    assert result.status.name == "FAILED" and result.items_count == 0
    assert any(error.status_code == 429 for error in result.errors)
    assert result.quality_details["source_stopped"] is True
    assert result.quality_details["source_stop_status"] == 429
    assert result.quality_details["source_stop_reason"] == "HTTP 429 at session warmup"
    crawler._build_source_requests.assert_not_called()
    crawler._retry_request.assert_not_called()
    crawler._fetch_category_pages_via_browser.assert_not_awaited()
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_266_visible_200_challenge_exports_pipeline_stop_marker(crawler):
    crawler._warmup_session = MagicMock()
    crawler._anti_detect = MagicMock()
    crawler._anti_detect.get_random_delay.return_value = 0
    crawler._retry_request = MagicMock(return_value=MagicMock(
        status_code=200, text='<html><body>Verify you are human</body></html>'))
    crawler._fetch_category_pages_via_browser = AsyncMock()
    result = await crawler.crawl()
    assert result.status.name == "FAILED" and result.items_count == 0
    assert result.quality_details["source_stopped"] is True
    assert result.quality_details["source_stop_status"] is None
    assert result.quality_details["source_stop_reason"] == "visible source access challenge"
    assert result.quality_details["fetch"]["blocked"] is True
    crawler._retry_request.assert_called_once()
    crawler._fetch_category_pages_via_browser.assert_not_awaited()
