"""코스트코 4-entry-point adapter (Round R G1)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests

from core.models import CrawlResult, DiscountItem, ErrorType, StrategyFailure
from crawlers.marts.costco.crawler import BASE_URL, CostcoCrawler, parse_costco_listing
from crawlers.marts.entry_points import CollectionPath, CrawlIntent, EntrypointTag, build_result, tag_items

SALE_CATEGORY = "cos_10"


class CostcoEntrypoints:
    """4-entry-point facade using the G1 HTML parser."""

    REQUEST_TIMEOUT = 20

    def __init__(self, crawler: Optional[CostcoCrawler] = None) -> None:
        self._crawler = crawler or CostcoCrawler()

    def _get(self, url: str) -> requests.Response:
        return requests.get(url, headers=self._crawler._headers(), timeout=self.REQUEST_TIMEOUT)

    async def _parse_to_items(self, html: str, *, category_id: str = "", category_path: str = "") -> list[DiscountItem]:
        return await self._crawler.parse(html, category_id=category_id, category_path=category_path)

    async def crawl_sale_listing(self, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = f"{BASE_URL}/c/{SALE_CATEGORY}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html, category_id=SALE_CATEGORY, category_path="식품")
        except Exception as exc:  # pragma: no cover
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {exc}"))
        tag = EntrypointTag(CollectionPath.PUBLIC_ENDPOINT, CrawlIntent.SALE, source_url=url)
        return build_result(crawler_name="코스트코", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def crawl_catalog_page(self, category_or_query: str, page: int = 1, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        category_id = category_or_query if category_or_query.startswith("cos_") else SALE_CATEGORY
        sep = "&" if "?" in category_id else "?"
        url = f"{BASE_URL}/c/{category_id}{sep}currentPage={max(0, int(page) - 1)}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html, category_id=category_id, category_path=category_id)
        except Exception as exc:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {exc}"))
        tag = EntrypointTag(CollectionPath.CATALOG_PAGE, CrawlIntent.CATALOG, source_url=url)
        return build_result(crawler_name="코스트코", items=tag_items(items, tag), tag=tag, started_at=started, extras={"query": category_or_query, "page": int(page)}, errors=errors)

    async def fetch_single_product(self, url_or_id: str, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = url_or_id if url_or_id.startswith("http") else f"{BASE_URL}/p/{url_or_id}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html)
        except Exception as exc:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {exc}"))
        tag = EntrypointTag(CollectionPath.SINGLE_PRODUCT, CrawlIntent.REFRESH, source_url=url)
        return build_result(crawler_name="코스트코", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def ingest_operator_capture(self, html: str, *, source_url: str, capture_id: Optional[str] = None, crawl_intent: CrawlIntent = CrawlIntent.SALE) -> CrawlResult:
        started = datetime.now()
        items = await self._parse_to_items(html)
        tag = EntrypointTag(CollectionPath.OPERATOR_CAPTURE, crawl_intent, source_url=source_url, operator_capture_id=capture_id)
        return build_result(crawler_name="코스트코", items=tag_items(items, tag), tag=tag, started_at=started, extras={"operator_capture": True, "source_host": urlparse(source_url).netloc})


__all__ = ["CostcoEntrypoints", "SALE_CATEGORY"]
