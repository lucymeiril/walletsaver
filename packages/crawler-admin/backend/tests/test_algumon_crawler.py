from __future__ import annotations

from pathlib import Path

from crawlers.hotdeals.algumon.crawler import AlgumonCrawler, HotdealRecord
from crawlers.hotdeals.algumon.entrypoints import crawl_list

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "algumon" / "sample_list.html"


def _records() -> list[HotdealRecord]:
    html = FIXTURE_HTML.read_text(encoding="utf-8")
    return AlgumonCrawler().crawl_list(html)


def test_fixture_parsing_returns_five_hotdeal_records():
    records = _records()
    assert len(records) == 5
    assert all(isinstance(record, HotdealRecord) for record in records)
    assert {record.source_site for record in records} == {"algumon"}
    assert all(record.title and record.url.startswith("https://www.algumon.com/") for record in records)


def test_dedup_hash_is_stable():
    first = _records()
    second = _records()
    assert [record.hash_dedup for record in first] == [record.hash_dedup for record in second]
    assert len({record.hash_dedup for record in first}) == len(first)


def test_url_normalization_strips_tracking_and_keeps_business_query():
    crawler = AlgumonCrawler()
    normalized = crawler.normalize_url("/l/d/100004?utm_campaign=fixture&ref=keep")
    assert normalized == "https://www.algumon.com/l/d/100004?ref=keep"
    upper = crawler.normalize_url("HTTPS://WWW.ALGUMON.COM/l/d/100005/?utm_content=x")
    assert upper == "https://www.algumon.com/l/d/100005"


def test_entrypoint_registered_for_crawl_list():
    records = crawl_list(FIXTURE_HTML.read_text(encoding="utf-8"))
    assert len(records) == 5
    assert records[0].source_native_id == "100001"


def test_async_parse_bridges_to_core_hotdeal_post():
    import asyncio

    posts = asyncio.run(AlgumonCrawler().parse(FIXTURE_HTML.read_text(encoding="utf-8")))
    assert len(posts) == 5
    assert posts[0].source_record_key == "algumon:post:100001"
    assert posts[2].price == 0
