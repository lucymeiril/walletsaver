"""G마켓 marketplace crawler skeleton."""

from __future__ import annotations

from crawlers.shopping.marketplace_skeleton import MarketplaceSkeletonCrawler


class GmarketCrawler(MarketplaceSkeletonCrawler):
    SOURCE_ID = "gmarket"
    DISPLAY_NAME = "G마켓"
    BASE_URL = "https://www.gmarket.co.kr"
    DESCRIPTION = "G마켓 marketplace price source"


Crawler = GmarketCrawler
