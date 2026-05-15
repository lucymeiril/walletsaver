import asyncio
import json
from pathlib import Path
from urllib.parse import unquote

from core.models import CrawlStatus
from crawlers.registry.registry import CrawlerRegistry
from pipeline.ai_export import to_raw_records


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


def test_coupang_and_gmarket_parse_source_cards_edges_and_ai_handoff_rows():
    registry = _registry()
    fixtures = {
        "coupang": """
        <html><body>
          <ul id="product-list">
            <li class="search-product" data-product-id="111">
              <a class="search-product-link" href="/vp/products/111?vendorItemId=222">
                <img data-img-src="//image.example/coupang-111.jpg" />
                <span class="name">source 생수 2L 6개</span>
              </a>
              <strong class="price-value">10,900원</strong>
              <del class="base-price">12,900원</del>
            </li>
            <li class="search-product" data-product-id="112">
              <a class="search-product-link" href="/vp/products/112"><span class="name">source 라면 5입</span></a>
              <strong class="price-value">4,980원</strong>
            </li>
            <li class="search-product" data-product-id="113">
              <a class="search-product-link" href="/vp/products/113"><span class="name">가격 누락 상품</span></a>
            </li>
          </ul>
          <a class="next" href="/np/search?q=water&page=2">next</a>
        </body></html>
        """,
        "gmarket": """
        <html><body>
          <div class="box__item-container" data-goods-code="gm-111">
            <a class="link__item" href="/item?goodsCode=gm-111">
              <img data-original="/images/gm-111.jpg" />
              <span class="box__item-title">source 즉석밥 12입</span>
            </a>
            <span class="box__price-seller"><strong>13,500원</strong></span>
            <span class="text__price-original">15,900원</span>
          </div>
          <div class="box__item-container" data-goods-code="gm-112">
            <a class="link__item" href="/item?goodsCode=gm-112">
              <span class="box__item-title">source 세제 3L</span>
            </a>
            <span class="text__value">8,900원</span>
          </div>
          <div class="box__item-container" data-goods-code="gm-113">
            <a class="link__item" href="/item?goodsCode=gm-113"><span class="box__item-title">가격 누락 상품</span></a>
          </div>
          <link rel="next" href="https://browse.gmarket.co.kr/search?keyword=rice&p=2" />
        </body></html>
        """,
    }

    for source_id, raw in fixtures.items():
        crawler = registry.get_crawler(source_id)
        parsed = _run(crawler.parse(raw))
        valid = _run(crawler.validate(parsed))

        assert crawler.count_raw_candidates(raw) == 3
        assert len(valid) == 2
        assert valid[0].detail_url.startswith(crawler.BASE_URL)
        assert valid[0].attributes["source"] == source_id
        assert valid[0].attributes["source_record_key"]
        assert valid[0].attributes["dedup_key"].startswith(f"{source_id}:")
        assert valid[0].attributes["incremental_key"]
        assert valid[0].attributes["source_rank"] == 1
        assert valid[1].image_url == ""
        assert crawler.next_page_url(raw)

        rows, skipped = to_raw_records(
            [item.model_dump(mode="json") for item in valid],
            source_name=source_id,
            batch_id=f"{source_id}-fixture-source",
        )
        assert skipped == 0
        assert [row.source_record_key for row in rows] == [
            valid[0].attributes["source_record_key"],
            valid[1].attributes["source_record_key"],
        ]
        assert rows[0].source_url == valid[0].detail_url
        assert rows[0].raw_payload["attributes"]["source_url"] == valid[0].detail_url


def test_marketplace_source_connectors_build_search_and_category_urls():
    registry = _registry()
    cases = {
        "coupang": ("q=생수", "page=3"),
        "gmarket": ("keyword=생수", "p=3"),
        "11st": ("kwd=생수", "pageNo=3"),
        "naver_store": ("query=생수", "pagingIndex=3"),
        "aliexpress": ("SearchText=생수", "page=3"),
    }

    for source_id, expected_parts in cases.items():
        crawler = registry.get_crawler(source_id)
        search_url = crawler.build_search_url("생수", page=3)
        category_url = crawler.build_category_url("/category/source-owned", page=2)

        decoded_search_url = unquote(search_url)
        assert search_url.startswith("https://")
        assert all(part in decoded_search_url for part in expected_parts)
        assert category_url.startswith(crawler.BASE_URL)


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
