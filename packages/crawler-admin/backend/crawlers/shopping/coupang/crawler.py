"""쿠팡 marketplace crawler skeleton."""

from __future__ import annotations

from crawlers.shopping.marketplace_skeleton import MarketplaceSkeletonCrawler


class CoupangCrawler(MarketplaceSkeletonCrawler):
    SOURCE_ID = "coupang"
    DISPLAY_NAME = "쿠팡"
    BASE_URL = "https://www.coupang.com"
    DESCRIPTION = "쿠팡 marketplace price source"
    SEARCH_PATH = "/np/search"
    SEARCH_QUERY_PARAM = "q"
    PAGE_PARAM = "page"


Crawler = CoupangCrawler
