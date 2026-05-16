"""쿠팡 4-진입점 어댑터 (Phase A).

쿠팡 (Akamai 보호) 공개 PLP/PDP 페이지는 자동화 트래픽에 ``Access Denied``
(Akamai edgesuite ref) 또는 빈 챌린지 페이지(<400 bytes)를 반환한다 — 본 슬라이스
시점의 라이브 캡처도 313 ~ 397 bytes 차단 응답이었다 (tests/fixtures/live_probe/
coupang_search*.html). 따라서:

* ``crawl_sale_listing`` / ``crawl_catalog_page`` / ``fetch_single_product``
  은 호출 자체는 가능하지만 라이브 응답을 받으면 ``akamai_access_denied`` /
  ``empty_challenge_payload`` 와 같은 정확한 blocker 를 errors 에 보고하고
  PARTIAL 로 반환한다. 운영자에게 ``ingest_operator_capture`` 로 이어
  받도록 안내한다.
* ``ingest_operator_capture`` 가 본 사이트의 신뢰 가능한 유일한 데이터 경로다.
  운영자가 자신의 브라우저로 PLP/PDP 를 열고 HTML/JSON 을 캡처해 넣으면
  기존 ``MarketplaceSkeletonCrawler.parse`` (HTML + JSON 양쪽 인식) 가
  처리한다.

traceId 노트
------------
공개 PLP URL 은 ``component=&q=<query>&traceId=<hex>&channel=user`` 형식이지만
모든 라이브 시도가 Akamai 단계에서 차단되어 ``traceId`` 가 빈 값일 때, 임의
hex 일 때, 세션과 묶일 때 어떻게 분기되는지 본 슬라이스에서는 검증하지 못
했다. plugin.yaml::coupang_traceId_note 에 그대로 명시한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

import requests

from core.models import CrawlResult, DiscountItem, ErrorType, StrategyFailure
from crawlers.marts.entry_points import (
    CollectionPath,
    CrawlIntent,
    EntrypointTag,
    build_result,
    tag_items,
)
from crawlers.shopping.coupang.crawler import CoupangCrawler


SALE_QUERY = "할인특가"


def _detect_blocker(raw: str) -> Optional[str]:
    """라이브 응답이 명백한 Akamai 차단이면 blocker 키를 반환."""
    if raw is None:
        return "no_response_body"
    body = raw.strip()
    if not body:
        return "empty_response"
    lowered = body.lower()
    if "access denied" in lowered and (
        "edgesuite" in lowered
        or "akamai" in lowered
        or "permission to access" in lowered
    ):
        return "akamai_access_denied"
    if "edgesuite.net" in lowered:
        return "akamai_access_denied"
    # very short, challenge-shaped pages with no product markers
    has_product_marker = (
        "search-product" in lowered
        or "product-card" in lowered
        or '"products"' in lowered
        or '"productList"' in lowered
        or "data-product-id" in lowered
        or 'vp/products/' in lowered
    )
    if len(body) < 400 and not has_product_marker:
        return "empty_challenge_payload"
    return None


class CoupangEntrypoints:
    """4-entry-point facade. Akamai 차단 정직 진단 포함."""

    REQUEST_TIMEOUT = 20
    BASE_URL = "https://www.coupang.com"

    def __init__(self, crawler: Optional[CoupangCrawler] = None) -> None:
        self._crawler = crawler or CoupangCrawler()

    def _get(self, url: str) -> requests.Response:
        # Reuse marketplace skeleton's bounded fetcher headers via requests
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.coupang.com/",
        }
        return requests.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)

    async def _parse_any(self, raw: str) -> list[DiscountItem]:
        return await self._crawler.parse(raw)

    def _diagnose(self, raw: str, url: str) -> Optional[StrategyFailure]:
        blocker = _detect_blocker(raw)
        if blocker:
            err_type = ErrorType.IP_BANNED if blocker == "akamai_access_denied" else ErrorType.HTTP_ERROR
            return StrategyFailure(strategy_name="requests", error_type=err_type, error_msg=f"{blocker}: {url}")
        return StrategyFailure(strategy_name="requests", error_type=ErrorType.PARSE_ERROR, error_msg=f"no_recognised_payload: {url}")

    def _build_search_url(self, query: str, page: int = 1, trace_id: str = "") -> str:
        # plugin.yaml 의 traceId 노트와 동일하게 빈 traceId 도 허용.
        return (
            f"{self.BASE_URL}/np/search?component=&q={quote(query)}"
            f"&traceId={quote(trace_id)}&channel=user&page={int(page)}"
        )

    async def crawl_sale_listing(self, *, fetch=None, trace_id: str = "") -> CrawlResult:
        started = datetime.now()
        url = self._build_search_url(SALE_QUERY, page=1, trace_id=trace_id)
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                d = self._diagnose(raw, url)
                if d:
                    errors.append(d)
        except Exception as e:  # pragma: no cover (network)
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.PUBLIC_ENDPOINT, CrawlIntent.SALE, source_url=url)
        return build_result(crawler_name="쿠팡", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def crawl_catalog_page(self, category_or_query: str, page: int = 1, *, fetch=None, trace_id: str = "") -> CrawlResult:
        started = datetime.now()
        url = self._build_search_url(category_or_query, page=page, trace_id=trace_id)
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                d = self._diagnose(raw, url)
                if d:
                    errors.append(d)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.CATALOG_PAGE, CrawlIntent.CATALOG, source_url=url)
        return build_result(
            crawler_name="쿠팡",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"query": category_or_query, "page": int(page), "trace_id": trace_id},
            errors=errors,
        )

    async def fetch_single_product(self, product_id_or_url: str, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        if product_id_or_url.startswith("http"):
            url = product_id_or_url
        else:
            url = f"{self.BASE_URL}/vp/products/{product_id_or_url}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                d = self._diagnose(raw, url)
                if d:
                    errors.append(d)
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.SINGLE_PRODUCT, CrawlIntent.REFRESH, source_url=url)
        return build_result(crawler_name="쿠팡", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def ingest_operator_capture(
        self,
        raw: str,
        *,
        source_url: str,
        capture_id: Optional[str] = None,
        crawl_intent: CrawlIntent = CrawlIntent.SALE,
    ) -> CrawlResult:
        started = datetime.now()
        items = await self._parse_any(raw)
        tag = EntrypointTag(CollectionPath.OPERATOR_CAPTURE, crawl_intent, source_url=source_url, operator_capture_id=capture_id)
        return build_result(
            crawler_name="쿠팡",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"operator_capture": True, "source_host": urlparse(source_url).netloc},
        )


# Catalog seed SKUs for mart-comparable categories. plugin.yaml exposes the same
# list, kept here as a re-export so callers can stay decoupled from yaml at runtime.
CATALOG_SEEDS: list[str] = [
    "생수 2L",
    "우유 1L",
    "계란 30구",
    "라면 5입",
    "세탁세제 3L",
]


__all__ = ["CoupangEntrypoints", "SALE_QUERY", "CATALOG_SEEDS", "_detect_blocker"]
