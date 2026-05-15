import asyncio
import json
from pathlib import Path

from core.models import CrawlStatus
from crawlers.registry.registry import CrawlerRegistry


MARKETPLACE_SOURCES = {
    "coupang": "쿠팡",
    "naver_store": "네이버스토어",
    "gmarket": "G마켓",
    "11st": "11번가",
    "aliexpress": "알리익스프레스",
}
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "marketplace_skeleton"


def _run(coro):
    return asyncio.run(coro)


def _registry():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    registry.discover()
    return registry


def test_marketplace_skeleton_plugins_register_metadata():
    registry = _registry()
    crawlers = {crawler["name"]: crawler for crawler in registry.list_crawlers()}

    for source_id in MARKETPLACE_SOURCES:
        assert source_id in crawlers
        config = registry._registry[source_id]["config"]
        assert config["source_group"] == "marketplace"
        assert config["live_ready"] is False
        assert config["parser_contract"] == "marketplace_skeleton.v1"
        assert config["fixture_contract"] == "marketplace_skeleton_fixture_contracts.v1"
        assert config["live_readiness"]["status"] == "skeleton_fixture_only"
        assert config["live_readiness"]["fixture_contract_status"] == "passed"
        assert config["live_readiness"]["bounded_diagnostics"]["status"] == "required_before_live_ready"
        assert config["live_readiness"]["operator_approval"]["status"] == "required_before_live_ready"
        assert "Do not set live_ready=true" in config["notes"]


def test_marketplace_skeletons_parse_mock_json_schema():
    registry = _registry()
    payload = json.dumps(
        {
            "products": [
                {
                    "productName": "테스트 생수 2L",
                    "salePrice": "3,900원",
                    "originalPrice": 5900,
                    "discountPercent": "34%",
                    "detailUrl": "/product/123",
                    "imageUrl": "/image/123.jpg",
                    "brandName": "fixture-brand",
                }
            ]
        },
        ensure_ascii=False,
    )

    for source_id, display_name in MARKETPLACE_SOURCES.items():
        crawler = registry.get_crawler(source_id)
        items = _run(crawler.parse(payload))
        valid_items = _run(crawler.validate(items))

        assert len(valid_items) == 1
        item = valid_items[0]
        assert item.name == "테스트 생수 2L"
        assert item.store == display_name
        assert item.sale_price == 3900
        assert item.original_price == 5900
        assert item.detail_url.startswith(crawler.BASE_URL)
        assert item.attributes["source"] == source_id
        assert item.attributes["source_url"] == item.detail_url
        assert item.attributes["price_evidence"]
        assert item.attributes["category_hints"] == ["fixture-brand"]
        assert item.attributes["parser_contract"] == "marketplace_skeleton.v1"
        assert item.attributes["fixture_contract"] == "marketplace_skeleton_fixture_contracts.v1"


def test_marketplace_skeletons_parse_saved_fixture_contracts():
    registry = _registry()
    contracts = json.loads((FIXTURE_DIR / "contracts.json").read_text(encoding="utf-8"))

    for source_id, expected in contracts["fixtures"].items():
        crawler = registry.get_crawler(source_id)
        for extension in ("json", "html"):
            raw = (FIXTURE_DIR / f"{source_id}.{extension}").read_text(encoding="utf-8")
            items = _run(crawler.parse(raw))
            valid_items = _run(crawler.validate(items))

            assert len(valid_items) == 1
            item = valid_items[0]
            assert item.name == expected["name"]
            assert item.store == expected["display_name"]
            assert item.sale_price == expected["sale_price"]
            assert item.original_price == expected["original_price"]
            assert item.discount_percent == expected["discount_percent"]
            assert item.detail_url == expected["detail_url"]
            assert item.image_url == expected["image_url"]
            assert item.attributes["source"] == source_id
            assert item.attributes["source_url"] == expected["detail_url"]
            assert item.attributes["price_evidence"]
            assert item.attributes["category_hints"]
            assert item.attributes["parser_contract"] == expected["parser_contract"]
            assert item.attributes["fixture_contract"] == "marketplace_skeleton_fixture_contracts.v1"


def test_marketplace_skeletons_parse_mock_html_and_report_success():
    registry = _registry()
    html = """
    <html><body>
      <article data-testid="product-card">
        <a href="/deal/fixture"><span class="name">테스트 라면 5입</span></a>
        <span class="sale-price">4,980원</span>
        <span class="original-price">6,980원</span>
        <span class="discount">29%</span>
        <img src="/fixture.jpg" />
      </article>
    </body></html>
    """

    for source_id in MARKETPLACE_SOURCES:
        crawler = registry.get_crawler(source_id)
        result = _run(crawler.crawl(fixture=html))

        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count == 1
        assert result.items[0]["name"] == "테스트 라면 5입"
        assert result.items[0]["sale_price"] == 4980
        assert result.items[0]["detail_url"].startswith(crawler.BASE_URL)
        assert result.items[0]["attributes"]["source_url"].startswith(crawler.BASE_URL)
        assert result.items[0]["attributes"]["price_evidence"] == "4,980원"
        assert result.quality_details["quality_summary"]["status"] in {"collecting", "warning"}
        assert result.quality_details["readiness_gate"]["status"] == "skeleton_fixture_only"
        assert result.quality_details["readiness_gate"]["collecting_claim_allowed"] is False
        assert result.quality_details["readiness_gate"]["safe_db_mutation_allowed"] is False
        assert result.quality_details["readiness_gate"]["bounded_diagnostics"]["run_limits"] == {
            "max_requests": None,
            "max_pages": None,
            "timeout_seconds": None,
        }
        assert result.quality_details["readiness_gate"]["operator_approval"]["status"] == "required_before_live_ready"
        assert result.quality_details["readiness_gate"]["downstream_flow"] == {
            "current_stage": "fixture_diagnostics_only",
            "next_stage": "no_db_ai_review",
            "db_mutation_allowed": False,
        }
        assert any("no-DB AI review" in action for action in result.quality_details["readiness_gate"]["next_actions"])


def test_marketplace_skeletons_without_fixture_return_zero_result_diagnostics():
    registry = _registry()

    for source_id in MARKETPLACE_SOURCES:
        crawler = registry.get_crawler(source_id)
        result = _run(crawler.crawl())

        assert result.status == CrawlStatus.PARTIAL
        assert result.items_count == 0
        assert "live crawling is intentionally disabled" in result.error_msg
        diagnostic = result.quality_details["zero_result_diagnostic"]
        assert diagnostic["stage"] == "live_disabled_no_fixture"
        assert diagnostic["dry_run_safe"] is True
        assert diagnostic["live_enabled"] is False
        assert diagnostic["fixture_available"] is False
        assert result.quality_details["readiness_gate"]["live_ready"] is False
        assert result.quality_details["readiness_gate"]["safe_db_mutation_allowed"] is False
        assert "Attach a recent approved fixture or raw_data sample" in diagnostic["next_action"]
        assert diagnostic["counts"] == {"source_raw": 0, "parsed": 0, "valid": 0, "invalid_or_dropped": 0}
