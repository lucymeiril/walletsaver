from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.models import CrawlResult, CrawlStatus
from crawlers.registry.registry import CrawlerRegistry
from pipeline.source_runs import SourceRunPipeline, SourceRunStore
from scheduler.scheduler import CrawlScheduler


class SequencedCrawler:
    def __init__(self, runs):
        self.runs = list(runs)
        self.seen_since = []

    async def crawl_incremental(self, *, since=None):
        self.seen_since.append(since)
        items = self.runs.pop(0)
        return CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name="emart",
            items_count=len(items),
            items=items,
        )


class Registry:
    def __init__(self, crawler):
        self.crawler = crawler

    def get_crawler(self, crawler_name):
        return self.crawler


def _crawler_registry():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    registry.discover()
    return registry


@pytest.mark.asyncio
async def test_repeated_source_runs_skip_unchanged_without_duplicate_handoff(tmp_path: Path):
    crawler = SequencedCrawler(
        [
            [
                {
                    "product_id": "milk-1l",
                    "name": "서울우유 1L",
                    "sale_price": 2980,
                    "detail_url": "https://emart.example/milk",
                }
            ],
            [
                {
                    "product_id": "milk-1l",
                    "name": "서울우유 1L",
                    "sale_price": 2980,
                    "detail_url": "https://emart.example/milk",
                }
            ],
        ]
    )
    pipeline = SourceRunPipeline(Registry(crawler), store=SourceRunStore(tmp_path))

    first = await pipeline.run_source_incremental("emart", source_name="emart", schema_type="mart_discount")
    second = await pipeline.run_source_incremental("emart", source_name="emart", schema_type="mart_discount")

    assert first.items_new == 1
    assert first.records_handed_off == 1
    assert second.since is not None
    assert crawler.seen_since == [None, second.since]
    assert second.items_new == 0
    assert second.items_changed == 0
    assert second.items_skipped == 1
    assert second.records_handed_off == 0

    handoff = json.loads(Path(second.ai_handoff_path).read_text(encoding="utf-8"))
    assert handoff["records"] == []
    assert handoff["batches"] == []


@pytest.mark.asyncio
async def test_changed_source_owned_facts_are_handed_off_and_preserved(tmp_path: Path):
    crawler = SequencedCrawler(
        [
            [
                {
                    "product_id": "tofu-300g",
                    "name": "국산콩 두부 300g",
                    "sale_price": 2990,
                    "detail_url": "https://emart.example/tofu",
                    "category_hint": "두부/콩나물",
                }
            ],
            [
                {
                    "product_id": "tofu-300g",
                    "name": "국산콩 두부 300g",
                    "sale_price": 2490,
                    "detail_url": "https://emart.example/tofu",
                    "category_hint": "두부/콩나물",
                    "event_name": "주간특가",
                }
            ],
        ]
    )
    pipeline = SourceRunPipeline(Registry(crawler), store=SourceRunStore(tmp_path))

    await pipeline.run_source_incremental("emart", source_name="emart", schema_type="mart_discount")
    changed = await pipeline.run_source_incremental("emart", source_name="emart", schema_type="mart_discount")

    assert changed.items_changed == 1
    assert changed.items_skipped == 0
    handoff = json.loads(Path(changed.ai_handoff_path).read_text(encoding="utf-8"))
    record = handoff["records"][0]
    assert record["source_record_key"] == "tofu-300g"
    assert record["raw_price"] == 2490
    assert record["raw_payload"]["event_name"] == "주간특가"
    assert record["raw_payload"]["category_hint"] == "두부/콩나물"
    assert handoff["batches"][0]["raw_artifact_uri"].endswith("raw_records.jsonl")


@pytest.mark.asyncio
async def test_scheduler_source_run_records_manifest_and_retry_dead_letter(tmp_path: Path, monkeypatch):
    class FailingCrawler:
        async def crawl_incremental(self, *, since=None):
            raise RuntimeError("source offline")

    dead_letter_path = tmp_path / "dead_letter.jsonl"

    def fake_dead_letter(records, *, crawler_name="unknown", target="store", error_msg=""):
        dead_letter_path.write_text(
            json.dumps(
                {
                    "records": records,
                    "crawler_name": crawler_name,
                    "target": target,
                    "error": error_msg,
                }
            ),
            encoding="utf-8",
        )
        return dead_letter_path

    monkeypatch.setattr("pipeline.source_runs.write_dead_letter", fake_dead_letter)
    source_pipeline = SourceRunPipeline(
        Registry(FailingCrawler()),
        store=SourceRunStore(tmp_path / "runs"),
        retry_count=2,
    )
    scheduler = CrawlScheduler(pipeline=source_pipeline)

    result = await scheduler.run_source_now("emart", source_name="emart", schema_type="mart_discount")

    assert result["status"] == "failed"
    assert result["dead_letter_path"] == str(dead_letter_path)
    assert [attempt["status"] for attempt in result["retry_attempts"]] == ["failed", "failed"]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["dead_letter_path"] == str(dead_letter_path)
    assert manifest["counts"]["records_handed_off"] == 0
    history = scheduler.tracker.get_history(job_id="source:emart")
    assert history[0]["result"]["status"] == "failed"


@pytest.mark.asyncio
async def test_coupang_saved_source_input_runs_no_db_handoff(tmp_path: Path):
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "marketplace_skeleton" / "coupang.html"
    ).read_text(encoding="utf-8")
    pipeline = SourceRunPipeline(_crawler_registry(), store=SourceRunStore(tmp_path))

    result = await pipeline.run_source_incremental(
        "coupang",
        source_name="coupang",
        schema_type="marketplace_discount",
        source_url="https://www.coupang.com/np/search?q=fixture",
        source_input=fixture,
        source_input_label="tests/fixtures/marketplace_skeleton/coupang.html",
    )

    assert result.status == "success"
    assert result.items_found == 1
    assert result.records_handed_off == 1
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["collection_mode"] == "bounded_source_input_no_db"
    assert manifest["live_network_enabled"] is False
    assert manifest["source_input"]["provided"] is True
    assert manifest["counts"]["source_raw"] == 1
    assert manifest["counts"]["parsed_valid"] == 1

    handoff = json.loads(Path(result.ai_handoff_path).read_text(encoding="utf-8"))
    record = handoff["records"][0]
    assert handoff["collection_mode"] == "bounded_source_input_no_db"
    assert record["source_record_key"] == "fixture-coupang"
    assert record["source_url"] == "https://www.coupang.com/vp/products/fixture-coupang"
    assert record["raw_payload"]["attributes"]["collection_mode"] == "fixture_source_parser"


@pytest.mark.asyncio
async def test_lottemart_saved_source_input_runs_no_db_handoff(tmp_path: Path):
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "non_marketplace_crawlers" / "lottemart.html"
    ).read_text(encoding="utf-8")
    pipeline = SourceRunPipeline(_crawler_registry(), store=SourceRunStore(tmp_path))

    result = await pipeline.run_source_incremental(
        "lottemart",
        source_name="lottemart",
        schema_type="mart_discount",
        source_url="https://lottemartzetta.com/search?query=fixture",
        source_input=fixture,
        source_input_label="tests/fixtures/non_marketplace_crawlers/lottemart.html",
    )

    assert result.status == "success"
    assert result.items_found == 2
    assert result.records_handed_off == 2
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["collection_mode"] == "bounded_source_input_no_db"
    assert manifest["live_network_enabled"] is False
    assert manifest["source_input"]["provided"] is True
    assert manifest["counts"]["source_raw"] == 2
    assert manifest["counts"]["parsed_valid"] == 2

    handoff = json.loads(Path(result.ai_handoff_path).read_text(encoding="utf-8"))
    assert handoff["collection_mode"] == "bounded_source_input_no_db"
    assert handoff["fetch"]["strategy_used"] == "saved_source_input"
    assert handoff["records"][0]["source_url"].startswith("https://lottemartzetta.com/products/")


@pytest.mark.asyncio
async def test_coupang_source_url_runs_bounded_live_no_db_handoff(tmp_path: Path, monkeypatch):
    html = """
    <html><body>
      <li class="search-product" data-product-id="live-coupang">
        <a class="search-product-link" href="/vp/products/live-coupang">
          <span class="name">쿠팡 live 생수 2L</span>
        </a>
        <strong class="price-value">4,900원</strong>
      </li>
    </body></html>
    """

    class Response:
        status_code = 200
        url = "https://www.coupang.com/np/search?q=live"
        headers = {"content-type": "text/html; charset=utf-8"}
        content = html.encode("utf-8")
        text = html

    async def fake_render_pages(url, *, max_pages, max_requests, timeout_seconds):
        return [
            {
                "url": url,
                "final_url": Response.url,
                "status_code": 200,
                "html": html,
                "bytes": len(html.encode("utf-8")),
                "challenge_detected": False,
                "login_required": False,
                "persistent_context": False,
            }
        ]

    pipeline = SourceRunPipeline(_crawler_registry(), store=SourceRunStore(tmp_path))
    crawler = pipeline.registry.get_crawler("coupang")
    monkeypatch.setattr(crawler, "_render_public_pages", fake_render_pages)

    result = await pipeline.run_source_incremental(
        "coupang",
        source_name="coupang",
        schema_type="marketplace_discount",
        source_url="https://www.coupang.com/np/search?q=live",
    )

    assert result.status == "success"
    assert result.items_found == 1
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["collection_mode"] == "ordinary_browser_public_no_db"
    assert manifest["live_network_enabled"] is True
    assert manifest["source_url"] == "https://www.coupang.com/np/search?q=live"
    assert manifest["counts"]["source_raw"] == 1
    assert manifest["counts"]["parsed"] == 1
    assert manifest["counts"]["parsed_valid"] == 1
    assert manifest["counts"]["parsed_unique"] == 1
    assert manifest["fetch"]["auth_bypass_attempted"] is False

    handoff = json.loads(Path(result.ai_handoff_path).read_text(encoding="utf-8"))
    record = handoff["records"][0]
    assert handoff["collection_mode"] == "ordinary_browser_public_no_db"
    assert record["source_record_key"] == "live-coupang"
    assert record["source_url"] == "https://www.coupang.com/vp/products/live-coupang"
    assert record["raw_payload"]["attributes"]["source_request_url"] == "https://www.coupang.com/np/search?q=live"


@pytest.mark.asyncio
async def test_coupang_source_url_access_blocker_is_not_retried(tmp_path: Path, monkeypatch):
    pipeline = SourceRunPipeline(_crawler_registry(), store=SourceRunStore(tmp_path), retry_count=3)
    crawler = pipeline.registry.get_crawler("coupang")
    calls = []

    async def fake_render_pages(url, *, max_pages, max_requests, timeout_seconds):
        calls.append(url)
        return [
            {
                "url": url,
                "final_url": url,
                "status_code": 403,
                "html": "blocked",
                "bytes": 7,
                "challenge_detected": False,
                "login_required": False,
                "persistent_context": False,
            }
        ]

    monkeypatch.setattr(crawler, "_render_public_pages", fake_render_pages)

    result = await pipeline.run_source_incremental(
        "coupang",
        source_name="coupang",
        schema_type="marketplace_discount",
        source_url="https://www.coupang.com/np/search?q=blocked",
    )

    assert result.status == "failed"
    assert len(calls) == 1
    assert "HTTP 403" in "; ".join(result.errors or [])
    assert "no CAPTCHA solving" in "; ".join(result.errors or [])


@pytest.mark.asyncio
async def test_operator_saved_source_artifact_path_imports_html_no_db(tmp_path: Path):
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "marketplace_skeleton" / "coupang.html"
    ).read_text(encoding="utf-8")
    artifact = tmp_path / "operator-saved-coupang.html"
    artifact.write_text(fixture, encoding="utf-8")
    pipeline = SourceRunPipeline(_crawler_registry(), store=SourceRunStore(tmp_path / "runs"))

    result = await pipeline.run_source_incremental(
        "coupang",
        source_name="coupang",
        schema_type="marketplace_discount",
        source_url="https://www.coupang.com/np/search?q=operator",
        source_input_path=artifact,
    )

    assert result.status == "success"
    assert result.records_handed_off == 1
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["source_input"]["provided"] is True
    assert manifest["source_input"]["label"] == str(artifact)
    assert manifest["collection_mode"] == "bounded_source_input_no_db"


@pytest.mark.asyncio
async def test_source_input_fails_if_crawler_cannot_accept_saved_input(tmp_path: Path):
    pipeline = SourceRunPipeline(
        Registry(SequencedCrawler([[{"name": "should not live crawl", "sale_price": 1}]])),
        store=SourceRunStore(tmp_path),
        retry_count=1,
    )

    result = await pipeline.run_source_incremental(
        "legacy",
        source_name="legacy",
        source_input="<html>saved</html>",
        source_input_label="saved.html",
    )

    assert result.status == "failed"
    assert "source_input" in "; ".join(result.errors or [])
