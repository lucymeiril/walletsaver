"""알리익스프레스 marketplace crawler skeleton."""

from __future__ import annotations

from crawlers.shopping.marketplace_skeleton import MarketplaceSkeletonCrawler


class AliExpressCrawler(MarketplaceSkeletonCrawler):
    SOURCE_ID = "aliexpress"
    DISPLAY_NAME = "알리익스프레스"
    BASE_URL = "https://www.aliexpress.com"
    DESCRIPTION = "알리익스프레스 marketplace price source"
    SEARCH_PATH = "/wholesale"
    SEARCH_QUERY_PARAM = "SearchText"
    PAGE_PARAM = "page"


Crawler = AliExpressCrawler
