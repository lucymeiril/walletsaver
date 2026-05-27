"""롯데마트 4-진입점 어댑터 (Phase A).

기존 ``LottemartCrawler`` 가 가지고 있는 ``parse()``, ``_extract_from_initial_state``,
WAF 진단 (AWS WAF HTTP 202) 로직을 그대로 재사용해 다음 네 가지 collection_path
를 노출한다:

* sale_listing  — lottemartzetta.com/search?query=할인 (public_endpoint, intent=sale)
* catalog_page  — 검색/카테고리 1페이지 (catalog_page, intent=catalog)
* single_product — /products/<id> 상세 (single_product, intent=refresh)
* operator_capture — 운영자 저장 HTML/JSON (operator_capture)

라이브 PC SSR 페이지는 SPA 셸이라 __INITIAL_STATE__ 의 productEntities 가
실제로는 비어 있을 때가 많다. 이 경우 ``crawl_sale_listing`` /
``crawl_catalog_page`` 는 PARTIAL 상태로 ``empty_initial_state_spa_shell``
blocker 를 명시적으로 보고하며, 운영자가 ``ingest_operator_capture`` 로
이어받도록 안내한다 (WAF 202 일 때도 동일 패턴).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

import requests

from core.models import CrawlResult, DiscountItem, ErrorType, StrategyFailure
from crawlers.marts.lottemart.crawler import LottemartCrawler
from crawlers.marts.entry_points import (
    CollectionPath,
    CrawlIntent,
    EntrypointTag,
    build_result,
    tag_items,
)


SALE_QUERY = "할인"


class LottemartEntrypoints:
    """4-entry-point facade. WAF/SPA-셸 인식 포함."""

    REQUEST_TIMEOUT = 20

    def __init__(self, crawler: Optional[LottemartCrawler] = None) -> None:
        self._crawler = crawler or LottemartCrawler()

    # ----- helpers -----
    def _get(self, url: str) -> requests.Response:
        headers = self._crawler._anti_detect.get_random_headers()
        headers["Referer"] = f"{self._crawler.ZETTA_BASE}/"
        return self._crawler._retry_request(url, headers=headers, timeout=self.REQUEST_TIMEOUT)

    async def _parse(self, html: str) -> list[DiscountItem]:
        return await self._crawler.parse(html)

    def _diagnose_empty(self, html: str, url: str) -> Optional[StrategyFailure]:
        if self._crawler._is_aws_waf_challenge(html):
            return StrategyFailure(
                strategy_name="requests",
                error_type=ErrorType.HTTP_ERROR,
                error_msg=f"aws_waf_http_202: {url}",
            )
        if "__INITIAL_STATE__" in html:
            return StrategyFailure(
                strategy_name="requests",
                error_type=ErrorType.PARSE_ERROR,
                error_msg=f"empty_initial_state_spa_shell: {url}",
            )
        return StrategyFailure(
            strategy_name="requests",
            error_type=ErrorType.PARSE_ERROR,
            error_msg=f"no_initial_state_marker: {url}",
        )

    # ----- entry points -----
    async def crawl_sale_listing(self, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = f"{self._crawler.ZETTA_BASE}/search?query={quote(SALE_QUERY)}&page=1"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse(html)
            if not items:
                f = self._diagnose_empty(html, url)
                if f:
                    errors.append(f)
        except Exception as e:  # pragma: no cover (network)
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.PUBLIC_ENDPOINT, CrawlIntent.SALE, source_url=url)
        return build_result(crawler_name="롯데마트", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def crawl_catalog_page(self, category_or_query: str, page: int = 1, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = f"{self._crawler.ZETTA_BASE}/search?query={quote(category_or_query)}&page={int(page)}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse(html)
            if not items:
                f = self._diagnose_empty(html, url)
                if f:
                    errors.append(f)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.CATALOG_PAGE, CrawlIntent.CATALOG, source_url=url)
        return build_result(
            crawler_name="롯데마트",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"query": category_or_query, "page": int(page)},
            errors=errors,
        )

    async def fetch_single_product(self, url_or_id: str, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        if url_or_id.startswith("http"):
            url = url_or_id
        else:
            url = f"{self._crawler.ZETTA_BASE}/products/{url_or_id}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            html = fetch(url) if fetch else self._get(url).text
            items = await self._parse(html)
            if not items:
                f = self._diagnose_empty(html, url)
                if f:
                    errors.append(f)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.SINGLE_PRODUCT, CrawlIntent.REFRESH, source_url=url)
        return build_result(crawler_name="롯데마트", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def ingest_operator_capture(
        self,
        html: str,
        *,
        source_url: str,
        capture_id: Optional[str] = None,
        crawl_intent: CrawlIntent = CrawlIntent.SALE,
    ) -> CrawlResult:
        started = datetime.now()
        items = await self._parse(html)
        tag = EntrypointTag(CollectionPath.OPERATOR_CAPTURE, crawl_intent, source_url=source_url, operator_capture_id=capture_id)
        return build_result(
            crawler_name="롯데마트",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"operator_capture": True, "source_host": urlparse(source_url).netloc},
        )


__all__ = ["LottemartEntrypoints", "SALE_QUERY"]
