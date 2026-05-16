"""홈플러스 4-진입점 어댑터 (Phase A).

기존 ``HomeplusCrawler.parse()`` 의 HTML 카드 파서와 임베디드 JSON 파서는
공식 mfront.homeplus.co.kr 검색 API 응답 (``{"returnStatus":200,
"data":{"dataList":[...]}}``) 의 키 (``itemNm``/``salePrice``/``dcPrice``/
``docId``/``itemNo``/``unitPrice``) 를 직접 매핑하지 않는다.

이 어댑터는 그 API JSON 봉투를 우선 인식하여 ``DiscountItem`` 으로 매핑하고,
실패시 기존 ``HomeplusCrawler.parse()`` (HTML SPA card → goods/items JSON 회로)
로 안전하게 폴백한다.

4 collection_path:
  * sale_listing  — mfront /search?keyword=할인 (public_endpoint, intent=sale)
  * catalog_page  — 동일 search 다른 키워드/페이지 (catalog_page, intent=catalog)
  * single_product — /item?itemNo={no} (single_product, intent=refresh)
  * operator_capture — 운영자 캡처 HTML/JSON (operator_capture, intent=any)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

import requests

from core.models import CrawlResult, DiscountItem, ErrorType, StrategyFailure
from core.product_units import normalize_unit_metadata
from crawlers.marts.entry_points import (
    CollectionPath,
    CrawlIntent,
    EntrypointTag,
    build_result,
    tag_items,
)
from crawlers.marts.homeplus.crawler import HomeplusCrawler
from crawlers.marts.source_utils import (
    build_source_attributes,
    normalize_source_key,
    parse_period_fields,
)


SALE_QUERY = "할인"


def _mfront_detail_url(item_no: str) -> str:
    return f"https://mfront.homeplus.co.kr/item?itemNo={item_no}&storeType=HYPER"


def _api_item_to_discount_item(product: dict) -> Optional[DiscountItem]:
    """mfront search API dataList 항목 → DiscountItem.

    키 매핑 (실제 응답 검증):
      name       ← itemNm
      sale_price ← dcPrice if not None else salePrice
      original_price ← salePrice (dcPrice 있을 때만)
      detail_url ← /item?itemNo={itemNo}&storeType=HYPER
      image      ← (응답에 없음; 빈 문자열)
      category   ← lcateNm / mcateNm / scateNm 중 가장 구체적인 것
      docId      ← attributes["source_record_key"] 의 입력으로 사용
      unitPrice  ← attributes["mfront_unit_price"]
    """
    name = product.get("itemNm") or ""
    if not name or len(name) < 2:
        return None

    sale_price_raw = product.get("dcPrice") or product.get("salePrice") or product.get("singlePrice")
    try:
        sale_price = int(sale_price_raw) if sale_price_raw is not None else 0
    except (TypeError, ValueError):
        return None
    if sale_price <= 0:
        return None

    original_price = None
    if product.get("dcPrice") and product.get("salePrice"):
        try:
            original_price = int(product["salePrice"])
        except (TypeError, ValueError):
            original_price = None

    discount_pct = product.get("frontDcRate") or product.get("dcRate")
    try:
        discount_pct = float(discount_pct) if discount_pct is not None else None
    except (TypeError, ValueError):
        discount_pct = None

    item_no = str(product.get("itemNo") or "").strip()
    doc_id = str(product.get("docId") or "").strip()
    detail_url = _mfront_detail_url(item_no) if item_no else ""

    category = (
        product.get("scateNm")
        or product.get("mcateNm")
        or product.get("lcateNm")
        or product.get("rcateNm")
        or ""
    )

    event_name = "홈플러스 할인"
    event_info = product.get("eventInfo") or {}
    if isinstance(event_info, dict) and event_info.get("eventBtnText"):
        event_name = event_info["eventBtnText"]

    source_record_key = normalize_source_key(
        "homeplus",
        doc_id or None,
        item_no or None,
        detail_url,
        name,
    )
    valid_from, valid_until, period = parse_period_fields(product)

    raw_unit = product.get("saleUnit") or product.get("itemQty") or ""
    unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price, raw_unit=str(raw_unit))
    display_unit = unit_metadata.get("display_unit") or str(raw_unit)

    extras: dict = dict(unit_metadata.get("attributes") or {})
    if doc_id:
        extras["doc_id"] = doc_id
    if item_no:
        extras["item_no"] = item_no
    unit_price = product.get("unitPrice")
    if unit_price is not None:
        extras["mfront_unit_price"] = unit_price
    if not detail_url:
        extras["detail_url_unknown"] = True

    attributes = build_source_attributes(
        "homeplus",
        source_record_key=source_record_key,
        detail_url=detail_url,
        image_url="",
        category=category,
        period=period,
        extra=extras,
    )

    return DiscountItem(
        name=name,
        store="홈플러스",
        original_price=original_price,
        sale_price=sale_price,
        discount_percent=discount_pct,
        unit=display_unit or "",
        display_unit=display_unit or "",
        package_quantity=unit_metadata.get("package_quantity"),
        package_unit=unit_metadata.get("package_unit") or "",
        price_per_100g=unit_metadata.get("price_per_100g"),
        attributes=attributes,
        category=category,
        event_name=event_name,
        valid_from=valid_from,
        valid_until=valid_until,
        image_url="",
        detail_url=detail_url,
    )


def _try_parse_mfront_envelope(raw: str) -> Optional[list[DiscountItem]]:
    """returnStatus:200 + data.dataList JSON 봉투 인식.

    실패하면 ``None`` 을 반환해 호출자가 기본 parser 로 폴백하도록 한다.
    """
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(envelope, dict) or envelope.get("returnStatus") != 200:
        return None
    data = envelope.get("data") or {}
    if not isinstance(data, dict):
        return None
    data_list = data.get("dataList") or []
    if not isinstance(data_list, list):
        return None
    items: list[DiscountItem] = []
    for product in data_list:
        if not isinstance(product, dict):
            continue
        it = _api_item_to_discount_item(product)
        if it:
            items.append(it)
    return items


class HomeplusEntrypoints:
    """4-entry-point facade. mfront JSON 봉투 우선, HTML 폴백."""

    REQUEST_TIMEOUT = 20

    def __init__(self, crawler: Optional[HomeplusCrawler] = None) -> None:
        self._crawler = crawler or HomeplusCrawler()

    def _get(self, url: str) -> requests.Response:
        headers = self._crawler._anti_detect.get_random_headers()
        headers["Referer"] = "https://mfront.homeplus.co.kr/"
        return self._crawler._retry_request(url, headers=headers, timeout=self.REQUEST_TIMEOUT)

    async def _parse_any(self, raw: str) -> list[DiscountItem]:
        items = _try_parse_mfront_envelope(raw)
        if items is not None:
            return items
        return await self._crawler.parse(raw)

    def _diagnose_empty(self, raw: str, url: str) -> StrategyFailure:
        snippet = raw.strip()[:80] if isinstance(raw, str) else ""
        is_empty_datalist = False
        try:
            envelope = json.loads(raw)
            if isinstance(envelope, dict) and envelope.get("returnStatus") == 200:
                data = envelope.get("data") or {}
                if isinstance(data, dict) and isinstance(data.get("dataList"), list) and not data["dataList"]:
                    is_empty_datalist = True
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        if is_empty_datalist:
            msg = f"empty_mfront_datalist: {url}"
        elif snippet.startswith("<"):
            msg = f"spa_shell_no_embedded_json: {url}"
        else:
            msg = f"no_recognised_payload: {url}"
        return StrategyFailure(strategy_name="requests", error_type=ErrorType.PARSE_ERROR, error_msg=msg)

    async def crawl_sale_listing(self, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = f"https://mfront.homeplus.co.kr/search?keyword={quote(SALE_QUERY)}&page=1"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                errors.append(self._diagnose_empty(raw, url))
        except Exception as e:  # pragma: no cover (network)
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.PUBLIC_ENDPOINT, CrawlIntent.SALE, source_url=url)
        return build_result(crawler_name="홈플러스", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

    async def crawl_catalog_page(self, category_or_query: str, page: int = 1, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        url = f"https://mfront.homeplus.co.kr/search?keyword={quote(category_or_query)}&page={int(page)}"
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                errors.append(self._diagnose_empty(raw, url))
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.CATALOG_PAGE, CrawlIntent.CATALOG, source_url=url)
        return build_result(
            crawler_name="홈플러스",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"query": category_or_query, "page": int(page)},
            errors=errors,
        )

    async def fetch_single_product(self, item_no_or_url: str, *, fetch=None) -> CrawlResult:
        started = datetime.now()
        if item_no_or_url.startswith("http"):
            url = item_no_or_url
        else:
            url = _mfront_detail_url(item_no_or_url)
        errors: list[StrategyFailure] = []
        items: list[DiscountItem] = []
        try:
            raw = fetch(url) if fetch else self._get(url).text
            items = await self._parse_any(raw)
            if not items:
                errors.append(self._diagnose_empty(raw, url))
        except Exception as e:
            errors.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {e}"))
        tag = EntrypointTag(CollectionPath.SINGLE_PRODUCT, CrawlIntent.REFRESH, source_url=url)
        return build_result(crawler_name="홈플러스", items=tag_items(items, tag), tag=tag, started_at=started, errors=errors)

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
            crawler_name="홈플러스",
            items=tag_items(items, tag),
            tag=tag,
            started_at=started,
            extras={"operator_capture": True, "source_host": urlparse(source_url).netloc},
        )


__all__ = [
    "HomeplusEntrypoints",
    "SALE_QUERY",
    "_api_item_to_discount_item",
    "_try_parse_mfront_envelope",
]
