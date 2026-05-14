"""네이버스토어 marketplace crawler skeleton."""

from __future__ import annotations

from crawlers.shopping.marketplace_skeleton import MarketplaceSkeletonCrawler


class NaverStoreCrawler(MarketplaceSkeletonCrawler):
    SOURCE_ID = "naver_store"
    DISPLAY_NAME = "네이버스토어"
    BASE_URL = "https://smartstore.naver.com"
    DESCRIPTION = "네이버스토어 marketplace price source"


Crawler = NaverStoreCrawler
