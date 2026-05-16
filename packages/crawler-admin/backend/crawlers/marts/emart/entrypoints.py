"""이마트 4-진입점 어댑터 (Phase A).

이미 작성된 ``EmartCrawler``(SSG ``__NEXT_DATA__`` 파서)를 재사용해
다음 네 가지 collection_path 를 모두 노출한다:

* sale_listing  — 검색 "행사" (public_endpoint, intent=sale)
* catalog_page  — 임의 query 1페이지 (catalog_page, intent=catalog)
* single_product — 상품 상세 1건 (single_product, intent=refresh)
* operator_capture — 운영자 워크밴치/프론트가 붙여넣은 HTML (operator_capture)

본 모듈은 ``EmartCrawler`` 의 ``parse()`` 메서드만 사용하므로 라이브
네트워크 호출이 필요 없을 때(테스트, 운영자 캡처)도 곧바로 동작한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

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


SALE_QUERY = "행사"


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
        url = f"{self._crawler.SEARCH_URL}?target=all&query={quote(SALE_QUERY)}&page=1"
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
        url = f"{self._crawler.SEARCH_URL}?target=all&query={quote(category_or_query)}&page={int(page)}"
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
