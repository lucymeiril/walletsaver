"""11번가 marketplace crawler skeleton."""

from __future__ import annotations

from crawlers.shopping.marketplace_skeleton import MarketplaceSkeletonCrawler


class ElevenstCrawler(MarketplaceSkeletonCrawler):
    SOURCE_ID = "11st"
    DISPLAY_NAME = "11번가"
    BASE_URL = "https://www.11st.co.kr"
    DESCRIPTION = "11번가 marketplace price source"


Crawler = ElevenstCrawler
