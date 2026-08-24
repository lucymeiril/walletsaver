"""Compact offline smoke coverage for the registered hotdeal crawlers.

Per-source parser details live in focused tests where they exist.  This file
keeps only cross-crawler contracts plus the Quasarzone parser regression that
otherwise had no dedicated coverage.  It intentionally performs no live
network calls and writes no result artifacts.
"""
from __future__ import annotations

import asyncio

import pytest

from core.models import CrawlerGroup, HotdealPost
from crawlers.hotdeals.algumon.crawler import AlgumonCrawler
from crawlers.hotdeals.arca.crawler import ArcaCrawler
from crawlers.hotdeals.clien.crawler import ClienCrawler
from crawlers.hotdeals.cocodal.crawler import CocodalCrawler
from crawlers.hotdeals.fmkorea.crawler import FmkoreaCrawler
from crawlers.hotdeals.ppomppu.crawler import PpomppuCrawler
from crawlers.hotdeals.quasarzone.crawler import QuasarzoneCrawler


ACTIVE_CRAWLERS = [
    PpomppuCrawler,
    FmkoreaCrawler,
    ClienCrawler,
    ArcaCrawler,
    QuasarzoneCrawler,
    AlgumonCrawler,
]
ALL_CRAWLERS = [*ACTIVE_CRAWLERS, CocodalCrawler]


@pytest.mark.parametrize("crawler_cls", ALL_CRAWLERS)
def test_hotdeal_crawlers_expose_hotdeal_metadata(crawler_cls):
    crawler = crawler_cls()
    assert crawler.info.group == CrawlerGroup.HOTDEAL
    assert crawler.info.name
    assert crawler.info.target_url


@pytest.mark.parametrize("crawler_cls", ACTIVE_CRAWLERS)
def test_hotdeal_validation_rejects_short_titles_and_duplicate_urls(crawler_cls):
    crawler = crawler_cls()
    source = crawler.info.name
    rows = [
        HotdealPost(title="AB", url="https://example.test/short", source_community=source),
        HotdealPost(title="정상 핫딜 게시글", url="https://example.test/dup", source_community=source),
        HotdealPost(title="다른 제목 같은 URL", url="https://example.test/dup", source_community=source),
        HotdealPost(title="또 다른 정상 핫딜", url="https://example.test/ok", source_community=source),
    ]

    valid = asyncio.run(crawler.validate(rows))
    assert [row.url for row in valid] == ["https://example.test/dup", "https://example.test/ok"]


def test_quasarzone_parser_extracts_title_price_and_absolute_url():
    html = """
    <html><body>
      <div class="market-info-list">
        <div class="market-info-list-cont">
          <div class="market-info-sub">
            <p class="tit">
              <a href="/bbs/qb_saleinfo/views/1001">
                <span class="ellipsis-with-reply-cnt">
                  <span class="deal-condition"><span>진행중</span></span>
                  <span class="text">LG 모니터 27인치 IPS 특가</span>
                </span>
              </a>
            </p>
            <p class="market-info-sub-txt">PC/하드웨어 가격 ￦ 259,000 (KRW) 배송비 무료</p>
          </div>
        </div>
      </div>
    </body></html>
    """
    crawler = QuasarzoneCrawler()
    rows = asyncio.run(crawler.parse(html))

    assert len(rows) == 1
    assert rows[0].title == "LG 모니터 27인치 IPS 특가"
    assert rows[0].price == 259000
    assert rows[0].url.startswith("http")
