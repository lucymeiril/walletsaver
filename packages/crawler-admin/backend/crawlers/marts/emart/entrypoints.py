"""이마트 4-진입점 어댑터 (Phase A).

Round R G1 이후 ``EmartCrawler`` 는 카테고리 HTML 상품 카드 파서를
사용한다. 이 어댑터는 기존 네 가지 collection_path 계약을 유지한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests

from core.models import CrawlResult, DiscountItem, ErrorType, StrategyFailure
from crawlers.marts.emart.crawler import EmartCrawler
from crawlers.marts.entry_points import (
    CollectionPath,
    CrawlIntent,
    EntrypointTag,
    build_result,
    tag_items,
)


SALE_QUERY = "과일"


class EmartEntrypoints:
    """4-entry-point facade. 라이브 GET 사이 sleep ≥3초 보장."""

    REQUEST_TIMEOUT = 20
    SLEEP_BETWEEN_LIVE_GETS = 3.0

    def __init__(self, crawler: Optional[EmartCrawler] = None) -> None:
        self._crawler = crawler or EmartCrawler()

    # ----- helpers -----
    def _get(self, url: str) -> requests.Response:
        headers = self._crawler._anti_detect.get_random_headers()
        headers["Referer"] = "https://emart.ssg.com/"
        return self._crawler._retry_request(url, headers=headers, timeout=self.REQUEST_TIMEOUT)

    async def _parse_to_items(self, html: str) -> list[DiscountItem]:
        return await self._crawler.parse(html)

    # ----- entry points -----
    async def crawl_sale_listing(self, *, fetch=None) -> CrawlResult:
        """현재 할인 1페이지 — 라이브 호출 (또는 주입된 fetch 콜백)."""
        started = datetime.now()
        category_id = next(iter(self._crawler.CATEGORY_IDS), SALE_QUERY)
        url = self._crawler._category_url(category_id, 1)
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html)
        except Exception as e:  # pragma: no cover (network)
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.PUBLIC_ENDPOINT, CrawlIntent.SALE, source_url=url)
        return build_result(crawler_name="이마트", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def crawl_catalog_page(self, category_or_query: str, page: int = 1, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        category_id = category_or_query
        if category_or_query in self._crawler.CATEGORY_IDS.values():
            category_id = next((cid for cid, path in self._crawler.CATEGORY_IDS.items() if path == category_or_query), category_or_query)
        url = self._crawler._category_url(str(category_id), int(page))
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.CATALOG_PAGE, CrawlIntent.CATALOG, source_url=url)
        return build_result(
            crawler_name="이마트",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"query": category_or_query, "page": int(page)},
            errors=errors,
        )

    async def fetch_single_product(self, url_or_id: str, *, fetch=None) -> CrawlResult:
        """단일 상품 재수집 — itemId 또는 itemView.ssg URL 둘 다 허용."""
        started = datetime.now()
        if url_or_id.startswith("http"):
            url = url_or_id
        else:
            url = f"https://emart.ssg.com/item/itemView.ssg?itemId={url_or_id}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse_to_items(html)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.SINGLE_PRODUCT, CrawlIntent.REFRESH, source_url=url)
        return build_result(crawler_name="이마트", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def ingest_operator_capture(
        self,
        html: str,
        *,
        source_url: str,
        capture_id: Optional[str] = None,
        crawl_intent: CrawlIntent = CrawlIntent.SALE,
    ) -> CrawlResult:
        started = datetime.now()
        items = await self._parse_to_items(html)
        tag = EntrypointTag(CollectionPath.OPERATOR_CAPTURE, crawl_intent, source_url=source_url, operator_capture_id=capture_id)
        return build_result(
            crawler_name="이마트",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"operator_capture": True, "source_host": urlparse(source_url).netloc},
        )


__all__ = ["EmartEntrypoints", "SALE_QUERY"]
