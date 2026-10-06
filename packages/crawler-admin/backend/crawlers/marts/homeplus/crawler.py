"""
홈플러스 크롤러 — requests-only legacy flow restored for mfront JSON APIs.

Round T keeps Homeplus on the old HTTP parser path: no Playwright, no added
concurrency, and 429 handling only by sleeping longer before retrying.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections import Counter
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, DiscountItem
from core.promotion_semantics import confirmed_price_or_none
from core.product_units import normalize_unit_metadata
from crawlers.marts.source_utils import (
    absolute_url,
    build_source_attributes,
    build_source_map_manifest,
    classify_external_seller_homeplus,
    compute_canon_hash,
    inject_source_field,
    normalize_homeplus_url,
    normalize_source_key,
    parse_period_fields,
    parse_unit_price,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)


class HomeplusCrawler(CrawlerContract):
    """홈플러스 크롤러 — legacy requests API + HTML parser."""

    BASE_URL = "https://www.homeplus.co.kr"
    MFRONT_URL = "https://mfront.homeplus.co.kr"
    CATEGORY_API = f"{MFRONT_URL}/category/item.json"
    EXPRESS_CATEGORY_API = f"{MFRONT_URL}/express/category/item.json"
    SEARCH_API = f"{MFRONT_URL}/totalsearch/total/search/item.json"
    EXPRESS_SEARCH_API = f"{MFRONT_URL}/express/search.json"
    EVENT_URL = "https://www.homeplus.co.kr/event/eventMain.do"

    SEARCH_QUERIES = [
        "과일", "채소", "정육", "계란", "쌀", "생수", "우유", "유제품",
        "간편식", "냉동식품", "라면", "과자", "커피", "세제", "화장지",
    ]
    CATEGORY_QUERIES = list(SEARCH_QUERIES)
    STORE_TYPES = ("HYPER", "EXP")
    # Round V: mfront top category IDs limited to food/fresh/daily/kitchen/baby scopes.
    CATEGORY_IDS = (1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 22, 23)
    DEFAULT_CATEGORY_DEPTH = 0
    DEFAULT_PER_PAGE = 100
    HYPER_DELIVERY_FILTER = "HYPER_DRCT"
    PRODUCT_CARD_SELECTOR = ".unitItemInner"
    PROMO_LABEL_RE = re.compile(r"\d+\s*\+\s*\d+")
    MAX_ITEMS: int | None = None
    MAX_PAGES: int | None = 3
    MAX_REQUESTS: int | None = None

    def __init__(self, anti_detect: Optional[AntiDetect] = None, max_scroll_attempts: int | None = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=2.5, delay_max=5.0)
        self.max_scroll_attempts = int(max_scroll_attempts or 30)
        import os
        env_cap = os.environ.get("HOMEPLUS_MEASUREMENT_MAX_ITEMS")
        if env_cap is not None:
            value = env_cap.strip().lower()
            if value in ("", "none", "null", "0"):
                self.MAX_ITEMS = None
            else:
                try:
                    self.MAX_ITEMS = int(value)
                except ValueError:
                    pass

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="홈플러스",
            version="3.0.0-round-t-legacy",
            group=CrawlerGroup.MART,
            description="홈플러스 할인 상품 정보 수집 (requests-only mfront JSON API)",
            target_url=self.MFRONT_URL,
            strategies=["requests", "json-api", "html-fallback"],
        )

    async def crawl(self) -> CrawlResult:
        started_at = datetime.now()
        logger.info("[홈플러스] requests-only 크롤링 시작")
        strategy = "requests_json_api"
        source_diagnostics = self._empty_source_diagnostics()
        try:
            items, requests_attempted, source_diagnostics = await self._fetch_via_playwright()
            items = self._dedupe_items(items)
            valid_items = await self.validate(items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            for _d in items_as_dict:
                _d["source"] = _d.get("source") or "homeplus"
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(items),
                invalid_count=max(0, len(items) - len(valid_items)),
                strategy_used=strategy,
                fallback_used=False,
                queries_attempted=requests_attempted,
                pages_attempted=source_diagnostics.get("pages_attempted"),
            )
            quality_details["fetch"]["source_map"] = self._source_map_summary()
            quality_details["fetch"]["source_distribution"] = source_diagnostics
            quality_details["source_breadth"] = self._source_breadth_summary(items_as_dict, source_diagnostics)
            quality_details["source_map"] = build_source_map_manifest(
                "homeplus",
                search_queries=self.SEARCH_QUERIES,
                category_queries=self.CATEGORY_QUERIES,
                max_pages=self.MAX_PAGES,
                max_requests=self.MAX_REQUESTS,
                max_items=self.MAX_ITEMS,
                parser_contract="homeplus_round_t_requests_api.v1",
                request_strategy="public_mfront_json_api_requests_only",
                parser_inputs=["category_item_json", "totalsearch_json", "mfront_unitItemInner_html", "legacy_product_card_html"],
                quality=quality_details,
            )
            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            return CrawlResult(
                status=CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED,
                crawler_name=self.info.name,
                strategy_used=strategy,
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg=None if valid_items else "상품 수집 실패",
                quality_score=quality_details["score"],
                quality_details=quality_details,
            )
        except Exception as exc:
            logger.error("[홈플러스] 크롤링 실패: %s", exc, exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(exc),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _retry_request(
        self,
        url: str,
        *,
        headers: dict | None = None,
        session: requests.Session | None = None,
        timeout: int = 20,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        requester = session or requests
        last_exc: BaseException | None = None
        last_resp: requests.Response | None = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout, **kwargs)
                last_resp = resp
                if resp.status_code == 429:
                    wait = 8 + (attempt * 8) + random.uniform(1.0, 3.0)
                    logger.warning("[홈플러스] 429 rate limit, sleeping %.1fs before retry", wait)
                    time.sleep(wait)
                    continue
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                if attempt >= max_retries - 1:
                    raise
                wait = 4 + (attempt * 4) + random.uniform(1.0, 2.0)
                logger.warning("[홈플러스] request failed (%s/%s), sleeping %.1fs: %s", attempt + 1, max_retries, wait, exc)
                time.sleep(wait)
        if last_resp is not None:
            return last_resp
        raise last_exc or requests.HTTPError("request retry exhausted")

    async def _fetch_via_playwright(self) -> tuple[list[DiscountItem], int, dict]:
        """Backward-compatible test hook; implementation is requests-only."""
        return await self._fetch_via_http()

    async def _fetch_via_http(self) -> tuple[list[DiscountItem], int, dict]:
        items: list[DiscountItem] = []
        seen_keys: set[tuple[str, str, str]] = set()
        requests_attempted = 0
        source_requests = self._build_source_requests()
        diagnostics = self._empty_source_diagnostics(source_requests)
        session = requests.Session()
        headers = self._headers()

        for source_request in source_requests:
            if self.MAX_REQUESTS is not None and requests_attempted >= self.MAX_REQUESTS:
                break
            max_pages_value = source_request.get("max_pages") if source_request.get("max_pages") is not None else self.MAX_PAGES
            max_pages = max(1, int(max_pages_value)) if max_pages_value is not None else None
            page_num = 1
            while max_pages is None or page_num <= max_pages:
                if self.MAX_REQUESTS is not None and requests_attempted >= self.MAX_REQUESTS:
                    break
                api_url, params = self._api_request_for_source(source_request, page_num)
                requests_attempted += 1
                diagnostics["queries_attempted"] = requests_attempted
                diagnostics["pages_attempted"] = diagnostics.get("pages_attempted", 0) + 1
                raw_count = 0
                new_count = 0
                try:
                    response = self._retry_request(
                        api_url,
                        headers=headers,
                        session=session,
                        timeout=20,
                        params=params,
                        allow_redirects=True,
                    )
                    if response.status_code != 200:
                        raise requests.HTTPError(f"HTTP {response.status_code}")
                    page_items = await self.parse(response.text, store_type=str(source_request.get("store_type") or "HYPER"))
                    raw_count = len(page_items)
                    for item in page_items:
                        if source_request.get("category_hint") and not item.category:
                            item.category = str(source_request["category_hint"])
                        attrs = item.attributes or {}
                        attrs.setdefault("mart_native_category_id", str(source_request.get("category_id") or ""))
                        attrs.setdefault("category_hint", item.category or str(source_request.get("category_hint") or ""))
                        item.attributes = attrs
                        key = source_dedup_key(item)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        items.append(item)
                        new_count += 1
                        if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                            diagnostics["item_cap_reached"] = True
                            self._record_source_request_result(diagnostics, source_request, page_num, raw_count, new_count)
                            return items[: self.MAX_ITEMS], requests_attempted, diagnostics
                    self._record_source_request_result(diagnostics, source_request, page_num, raw_count, new_count)
                    if not self._has_next_page(response.text, page_num):
                        break
                except Exception as exc:
                    logger.debug("[홈플러스] requests source failed: %s %s", source_request.get("url"), exc)
                    self._record_source_request_result(diagnostics, source_request, page_num, raw_count, new_count, error=str(exc))
                    break
                page_num += 1
                self._polite_sleep()
        return self._limit_items(items), requests_attempted, diagnostics

    def _headers(self) -> dict:
        headers = self._anti_detect.get_random_headers()
        headers.update({
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": f"{self.MFRONT_URL}/list?categoryDepth=0&categoryId=1&delivery={self.HYPER_DELIVERY_FILTER}",
            "Origin": self.MFRONT_URL,
        })
        return headers

    def _polite_sleep(self) -> None:
        delay_getter = getattr(self._anti_detect, "get_random_delay", None)
        delay = delay_getter() if callable(delay_getter) else random.uniform(2.5, 5.0)
        try:
            delay = float(delay or 0)
        except (TypeError, ValueError):
            delay = 0
        if delay > 0:
            time.sleep(delay)

    def _api_request_for_source(self, source_request: dict, page_num: int) -> tuple[str, dict[str, str | int]]:
        store_type = self._normalize_store_type(str(source_request.get("store_type") or "HYPER"))
        request_type = str(source_request.get("request_type") or "category_list")
        per_page = int(source_request.get("per_page") or self.DEFAULT_PER_PAGE)
        if request_type.startswith("search"):
            url = self.EXPRESS_SEARCH_API if store_type == "EXP" else self.SEARCH_API
            params: dict[str, str | int] = {"keyword": str(source_request.get("query") or ""), "page": page_num, "perPage": per_page}
            if store_type == "HYPER":
                params["delivery"] = self.HYPER_DELIVERY_FILTER
            return url, params
        url = self.EXPRESS_CATEGORY_API if store_type == "EXP" else self.CATEGORY_API
        params = {
            "categoryId": int(source_request.get("category_id") or 1),
            "categoryDepth": int(source_request.get("category_depth") or self.DEFAULT_CATEGORY_DEPTH),
            "page": page_num,
            "perPage": per_page,
        }
        if store_type == "HYPER":
            params["delivery"] = self.HYPER_DELIVERY_FILTER
        return url, params

    def _has_next_page(self, raw_data: str, page_num: int) -> bool:
        try:
            data = json.loads(raw_data)
            pagination = data.get("pagination") or (data.get("data") or {}).get("pagination") or {}
            total_page = int(pagination.get("totalPage") or 0)
            return total_page > page_num
        except Exception:
            return False

    def _build_homeplus_category_url(self, store_type: str, category_id: int) -> str:
        store_type = self._normalize_store_type(store_type)
        prefix = "/express/list" if store_type == "EXP" else "/list"
        params: dict[str, str | int] = {"categoryDepth": self.DEFAULT_CATEGORY_DEPTH, "categoryId": int(category_id)}
        if store_type == "HYPER":
            params["delivery"] = self.HYPER_DELIVERY_FILTER
        return f"{self.MFRONT_URL}{prefix}?{urlencode(params)}"

    def _build_source_requests(self) -> list[dict[str, str | int]]:
        legacy_overrides = (
            self.SEARCH_QUERIES != type(self).SEARCH_QUERIES
            or self.CATEGORY_QUERIES != type(self).CATEGORY_QUERIES
            or (self.MAX_PAGES is not None and self.MAX_PAGES != type(self).MAX_PAGES)
        )
        if legacy_overrides:
            return self._build_legacy_search_source_requests()
        requests_to_make: list[dict[str, str | int]] = []
        for store_type in self.STORE_TYPES:
            for category_id in self.CATEGORY_IDS:
                requests_to_make.append({
                    "query": store_type,
                    "page": 1,
                    "store_type": store_type,
                    "category_id": int(category_id),
                    "category_depth": self.DEFAULT_CATEGORY_DEPTH,
                    "category_hint": str(category_id),
                    "request_type": "category_list",
                    "per_page": self.DEFAULT_PER_PAGE,
                    "url": self._build_homeplus_category_url(store_type, int(category_id)),
                })
        return requests_to_make

    def _build_legacy_search_source_requests(self) -> list[dict[str, str | int]]:
        max_pages = self.MAX_PAGES if self.MAX_PAGES is not None else 1
        requests_to_make: list[dict[str, str | int]] = []
        index_by_key: dict[tuple[str, int], int] = {}
        for query in self.SEARCH_QUERIES:
            for page_num in range(1, max(1, int(max_pages)) + 1):
                key = (query, page_num)
                index_by_key[key] = len(requests_to_make)
                requests_to_make.append({
                    "query": query,
                    "page": page_num,
                    "store_type": "HYPER",
                    "category_hint": "",
                    "request_type": "search",
                    "per_page": self.DEFAULT_PER_PAGE,
                    "url": f"{self.MFRONT_URL}/search?keyword={quote(query)}&page={page_num}",
                })
        for query in self.CATEGORY_QUERIES:
            for page_num in range(1, max(1, int(max_pages)) + 1):
                key = (query, page_num)
                if key in index_by_key:
                    request = requests_to_make[index_by_key[key]]
                    request["category_hint"] = query
                    request["request_type"] = "search+category"
                    continue
                index_by_key[key] = len(requests_to_make)
                requests_to_make.append({
                    "query": query,
                    "page": page_num,
                    "store_type": "HYPER",
                    "category_hint": query,
                    "request_type": "category",
                    "per_page": self.DEFAULT_PER_PAGE,
                    "url": f"{self.MFRONT_URL}/search?keyword={quote(query)}&page={page_num}",
                })
        return requests_to_make

    def _source_map_summary(self) -> dict:
        requests_to_make = self._build_source_requests()
        pages = sorted({int(req.get("page", 1)) for req in requests_to_make}) or [1]
        return {
            "schema": "homeplus_source_map.v1",
            "search_queries": list(self.SEARCH_QUERIES),
            "category_queries": list(self.CATEGORY_QUERIES),
            "planned_requests": len(requests_to_make),
            "planned_pages": pages,
            "request_type_counts": dict(Counter(str(req.get("request_type") or "search") for req in requests_to_make)),
            "caps": {"max_items": self.MAX_ITEMS, "max_pages": self.MAX_PAGES, "max_requests": self.MAX_REQUESTS},
        }

    def harvest_category_tree_fixture(self) -> list[dict[str, str | int]]:
        return [
            {
                "mart": "homeplus",
                "storeType": store_type,
                "mart_native_category_id": int(category_id),
                "categoryDepth": self.DEFAULT_CATEGORY_DEPTH,
                "url": self._build_homeplus_category_url(store_type, int(category_id)),
            }
            for store_type in self.STORE_TYPES
            for category_id in self.CATEGORY_IDS
        ]

    def _empty_source_diagnostics(self, source_requests: list[dict[str, str | int]] | None = None) -> dict:
        source_requests = source_requests or self._build_source_requests()
        return {
            "schema": "homeplus_source_distribution.v1",
            "planned_requests": len(source_requests),
            "queries_attempted": 0,
            "pages_attempted": 0,
            "query_distribution": {},
            "category_distribution": {},
            "request_type_distribution": {},
            "request_results": [],
            "item_cap_reached": False,
        }

    def _record_source_request_result(self, diagnostics: dict, source_request: dict, page_num: int, raw_count: int, new_count: int, error: str | None = None) -> None:
        query = str(source_request.get("query") or source_request.get("store_type") or "")
        category_hint = str(source_request.get("category_hint") or "")
        request_type = str(source_request.get("request_type") or "category_list")
        record = {
            "query": query,
            "page": page_num,
            "category_hint": category_hint,
            "request_type": request_type,
            "raw_count": raw_count,
            "new_count": new_count,
        }
        if error:
            record["error"] = error
        diagnostics.setdefault("request_results", []).append(record)
        for key_name, value in (
            ("query_distribution", query),
            ("category_distribution", category_hint or "uncategorized"),
            ("request_type_distribution", request_type),
        ):
            bucket = diagnostics.setdefault(key_name, {})
            bucket[value] = int(bucket.get(value, 0)) + new_count

    def _source_breadth_summary(self, items: list[dict], source_diagnostics: dict) -> dict:
        category_counts: Counter[str] = Counter()
        for item in items:
            attrs = item.get("attributes") or {}
            category = item.get("category") or attrs.get("category_hint") or attrs.get("category") or "uncategorized"
            category_counts[str(category)] += 1
        item_count = len(items)
        return {
            "schema": "homeplus_source_breadth.v1",
            "valid_items": item_count,
            "category_distribution": dict(category_counts),
            "query_distribution": source_diagnostics.get("query_distribution") or {},
            "request_type_distribution": source_diagnostics.get("request_type_distribution") or {},
            "unique_categories": len([name for name, count in category_counts.items() if count > 0 and name != "uncategorized"]),
            "threshold_shape": {
                "near_200_count": 199 <= item_count <= 201,
                "item_cap_reached": bool(source_diagnostics.get("item_cap_reached")),
                "max_items": self.MAX_ITEMS,
                "source_complete_claim_allowed": False,
                "reason": "Counts near 200 are breadth diagnostics only; source completeness requires approved bounded live evidence.",
            },
        }

    async def parse(self, raw_data: str, store_type: str = "HYPER", *, source_url: str | None = None) -> list[DiscountItem]:
        items: list[DiscountItem] = []
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product, store_type=store_type, source_url=source_url)
                if item:
                    items.append(item)
            return items
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            items = self._parse_html(soup, store_type=store_type)
            del soup
        except Exception as exc:
            logger.warning("[홈플러스] HTML 파싱 실패: %s", exc)
        return items

    def _extract_json_items(self, raw_data: str) -> list[dict]:
        try:
            parsed = json.loads(raw_data)
            items = self._json_items_from_obj(parsed)
            if items:
                return items
        except Exception:
            pass
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_data, "html.parser")
        detail_rows = []
        for script in soup.find_all("script"):
            try:
                payload = json.loads(script.get_text())
            except (ValueError, TypeError):
                continue
            rows = self._json_items_from_obj(payload)
            detail_rows.extend(row for row in rows if isinstance(row, dict) and ("basic" in row or "sale" in row))
        if detail_rows:
            # A detail response must identify a single product container. Never
            # combine native/price/option siblings from separate scripts.
            return detail_rows if len(detail_rows) == 1 else [{}]
        patterns = [
            r'var\s+(?:itemList|prodList|goodsList)\s*=\s*(\[.*?\]);',
            r'"(?:itemList|goods|products|dataList)"\s*:\s*(\[.*?\])',
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_data, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    if isinstance(parsed, list):
                        return [row for row in parsed if isinstance(row, dict)]
                except json.JSONDecodeError:
                    continue
        return []

    def _json_items_from_obj(self, obj) -> list[dict]:
        if isinstance(obj, list):
            return [row for row in obj if isinstance(row, dict)]
        if not isinstance(obj, dict):
            return []
        if "basic" in obj:
            return [obj]
        if "item" in obj:
            return [obj["item"]] if isinstance(obj["item"], dict) else [{}]
        for key in ("dataList", "itemList", "goodsList", "products", "items"):
            value = obj.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        data = obj.get("data")
        if isinstance(data, dict):
            return self._json_items_from_obj(data)
        return []

    def _json_to_discount_item(self, product: dict, store_type: str = "HYPER", *, source_url: str | None = None) -> Optional[DiscountItem]:
        if "basic" in product or "sale" in product:
            return self._detail_to_discount_item(product, store_type=store_type, source_url=source_url)
        name = str(product.get("itemNm") or product.get("goodsNm") or product.get("prodNm") or product.get("name") or "").strip()
        if len(name) < 2:
            return None
        sale_price = self._to_int(product.get("dcPrice") or product.get("salePrice") or product.get("sellprc") or product.get("price"))
        original_price = self._to_int(product.get("singlePrice") or product.get("originPrice") or product.get("norprc") or product.get("original_price"))
        if original_price == sale_price:
            original_price = None
        if not sale_price or sale_price <= 0:
            return None
        discount_pct = self._to_float(product.get("dcRate") or product.get("frontDcRate"))
        if discount_pct is None and original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)
        item_no = self._extract_item_no_from_product(product)
        store_type = self._normalize_store_type(str(product.get("storeType") or store_type))
        category = self._category_from_product(product)
        category_path = [value for value in (product.get("lcateNm"), product.get("mcateNm"), product.get("scateNm"), product.get("dcateNm")) if value]
        legacy_detail_url = self._permanent_product_url(item_no, name) if item_no else self._normalize_legacy_detail_url(str(product.get("goodsUrl") or product.get("detail_url") or ""))
        canonical_url = normalize_homeplus_url(item_no, store_type) if item_no else legacy_detail_url
        detail_url = canonical_url or legacy_detail_url
        image_url = self._image_url_from_product(product)
        raw_unit = product.get("unit") or product.get("goodsUnit") or product.get("capacity") or self._display_unit_from_api(product)
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price, raw_unit=raw_unit or "")
        display_unit = unit_metadata.get("display_unit") or raw_unit or ""
        unit_price_info = self._unit_price_from_product(product)
        brand = str(product.get("brandNm") or self._extract_brand(name) or "").strip()
        normalized_name = re.sub(r"\[[^\]]+\]", "", name)
        normalized_name = re.sub(r"\s+", " ", normalized_name).strip()
        promo_label = self._extract_json_promo_label(product)
        valid_from, valid_until, period = parse_period_fields(product)
        event_info = product.get("eventInfo") if isinstance(product.get("eventInfo"), dict) else {}
        if not valid_until and event_info:
            _, valid_until, period = parse_period_fields({"valid_until": event_info.get("eventEndDt")})
        source_record_key = normalize_source_key("homeplus", item_no, product.get("goodsNo"), product.get("docId"), detail_url, name)
        pack_qty = unit_metadata.get("package_quantity") or ""
        pack_unit = unit_metadata.get("package_unit") or ""
        attrs = {
            **(unit_metadata.get("attributes") or {}),
            **unit_price_info,
            **build_source_attributes(
                "homeplus",
                source_record_key=source_record_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                period=period,
            ),
            "storeType": store_type,
            "mart_native_code": item_no,
            "canonical_url": canonical_url,
            "permanent_url": canonical_url,
            "legacy_detail_url": legacy_detail_url,
            "mart_native_category_id": str(product.get("rcateCd") or product.get("categoryId") or ""),
            "mart_native_category_path": " > ".join(category_path),
            "external_seller": classify_external_seller_homeplus(" ".join(map(str, product.get("deliveryLabelList") or [])) + " " + str(product.get("itemShipMethodNm") or "")),
            "canon_hash": compute_canon_hash(brand, normalized_name, pack_qty, pack_unit),
            "brand": brand,
            "raw_name": name,
            "normalized_name": normalized_name,
            "docId": product.get("docId") or "",
        }
        if promo_label:
            attrs["promo_label"] = promo_label
        attrs = inject_source_field(attrs, "homeplus")
        return DiscountItem(
            name=name,
            normalized_name=normalized_name,
            store="홈플러스",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=attrs,
            category=category,
            event_name=promo_label or product.get("stickerEvent") or "홈플러스 할인",
            valid_from=valid_from,
            valid_until=valid_until,
            image_url=image_url,
            detail_url=detail_url,
            promo_label=promo_label,
        )

    @staticmethod
    def _bounded_source_fields(node: dict, keys: tuple[str, ...]) -> dict:
        result = {}
        for key in keys:
            value = node.get(key)
            if key not in node:
                continue
            if value is None or isinstance(value, (str, bool, int)):
                result[key] = value[:256] if isinstance(value, str) else value
            elif isinstance(value, float) and value == value and abs(value) != float("inf"):
                result[key] = value
        return result

    @staticmethod
    def _detail_quantity_complete(text: str, metadata: dict) -> bool:
        # The common parser reports the declaration it consumed. An additional
        # sold count is not permission to guess an outer pack multiplier.
        matched = metadata.get("raw_match")
        remainder = text.replace(matched, "", 1) if matched else text
        if re.search(r"[xX×*]\s*\d", remainder):
            return False
        if matched and re.search(r"\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b", remainder, re.IGNORECASE):
            return False
        counts = re.findall(
            r"(?<![\d.,])(\d+(?:\.\d+)?)\s*"
            r"(개입|봉지|인분|세트|마리|회분|박스|스틱|티백|구|입|개|팩|봉|병|캔|손|매|롤|포|장|족|통|인|ct|pk|ea)"
            r"(?![A-Za-z0-9가-힣])", remainder, re.IGNORECASE,
        )
        if not counts:
            return True
        # One repeated count can corroborate a declared measure bundle (6병
        # alongside 2L×6). Additive terms or further counts remain unresolved.
        return (bool(matched) and metadata.get("package_unit") in {"L", "ml", "g", "kg"}
                and len(counts) == 1 and counts[0][0].isdigit()
                and counts[0][1] in {"병", "캔"}
                and int(counts[0][0]) == metadata.get("bundle_count")
                and "+" not in remainder)

    def _detail_event_source_fields(self, event: dict) -> dict:
        keys = ("eventNm", "eventName", "eventBtnText", "description", "dispEventLabel", "dispEventTitle",
                "dispDiscountItemNm", "eventSticker", "eventKind", "eventStartDt", "eventEndDt", "name",
                "buyItemCount", "buyItemCnt", "eventBenefitQty", "changeAmount", "changePercent", "changeType",
                "thresholdType", "thresholdQty", "thresholdAmount", "thresholdQtyMax", "thresholdAmountMax",
                "buyItemType", "buyItemValue", "evnItemKind", "eventGiveType")
        for key in keys:
            if key in event:
                value = event[key]
                if (not (value is None or type(value) in (str, bool, int, float))
                        or isinstance(value, str) and len(value) > 256
                        or type(value) is float and (value != value or abs(value) == float("inf"))):
                    raise ValueError("unbounded source event field")
        result = self._bounded_source_fields(event, keys)
        if "thresholdIntervals" in event:
            rows = event["thresholdIntervals"]
            if not isinstance(rows, list) or len(rows) > 40:
                raise ValueError("unbounded source event thresholds")
            result["thresholdIntervals"] = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("source event threshold is not an object")
                result["thresholdIntervals"].append(self._detail_event_source_fields({
                    key: row[key] for key in ("thresholdQty", "thresholdAmount", "changePercent", "changeAmount") if key in row}))
        return result

    def _detail_to_discount_item(self, node: dict, *, store_type: str, source_url: str | None) -> Optional[DiscountItem]:
        basic, sale, options = node.get("basic"), node.get("sale"), node.get("opt")
        if not isinstance(basic, dict) or not isinstance(sale, dict) or not isinstance(options, dict):
            return None
        native, name, declared_store = basic.get("itemNo"), basic.get("itemNm"), basic.get("storeType")
        if (not isinstance(native, str) or not re.fullmatch(r"\d{9}", native)
                or not isinstance(name, str) or len(name.strip()) < 2
                or declared_store not in {"HYPER", "EXP"} or declared_store != self._normalize_store_type(store_type)):
            return None
        identity_layers = [node, basic, sale, options]
        identity_layers.extend(node[key] for key in ("prop", "etc", "promo") if isinstance(node.get(key), dict))
        for layer in identity_layers:
            if (("itemNo" in layer and layer["itemNo"] != native)
                    or ("storeType" in layer and layer["storeType"] != declared_store)):
                return None
        declared_hrefs = [layer[key] for layer in identity_layers for key in ("detail_url", "source_url") if key in layer]
        for href in [source_url, *declared_hrefs]:
            if href is None:
                continue
            if not isinstance(href, str):
                return None
            try:
                parts = urlparse(href)
                query = parse_qs(parts.query, keep_blank_values=True)
            except ValueError:
                return None
            if (parts.scheme != "https" or parts.netloc != "mfront.homeplus.co.kr" or parts.path != "/item"
                    or query.get("itemNo") != [native] or query.get("storeType") != [declared_store]):
                return None
        # Actual no-option declarations are required; an omitted selection state
        # is not permission to attach the container's quote to a default variant.
        if any(options.get(key) != "N" for key in ("groupUseYn", "optSelUseYn", "optTxtUseYn")):
            return None
        if (options.get("optSelList") not in (None, []) or options.get("frontGroupItemList") not in (None, [])
                or any(options.get(key) is not None and (type(options[key]) is not int or options[key] != 0)
                       for key in ("optTitleDepth", "optTxtDepth"))):
            return None
        dc_raw = sale.get("dcPrice")
        dc = self._to_int(dc_raw, allow_zero=True) if dc_raw is not None else None
        if dc_raw is not None and dc is None:
            return None
        listed = self._to_int(sale.get("salePrice"))
        if listed is None:
            return None
        quote = dc if dc is not None and dc > 0 else listed
        prop = node.get("prop") if isinstance(node.get("prop"), dict) else {}
        notices = []
        notice_names = {"상품명", "상품코드/모델", "식품의 유형", "포장단위별 내용물의 용량(중량), 수량", "원재료 및 함량", "영양성분(영양정보)"}
        rows = []
        for key in ("noticeList", "notice_rows_original_pointers"):
            declared_rows = prop.get(key)
            if declared_rows is None:
                continue
            if not isinstance(declared_rows, list) or len(rows) + len(declared_rows) > 40:
                return None
            rows.extend(declared_rows)
        for entry in rows:
            fields = entry.get("raw_fields", entry) if isinstance(entry, dict) else {}
            if not isinstance(fields, dict) or fields.get("noticeNm") not in notice_names:
                continue
            desc = fields.get("noticeDesc")
            if not isinstance(desc, str):
                return None
            if fields["noticeNm"] == "포장단위별 내용물의 용량(중량), 수량" and len(desc) > 256:
                # Identity cannot be established from a truncated contents prefix.
                return None
            if fields["noticeNm"] == "상품코드/모델":
                codes = re.findall(r"(?<!\d)\d{9}(?!\d)", desc)
                if codes and codes != [native]:
                    return None
            if fields["noticeNm"] == "상품명" and desc.strip() != name.strip():
                return None
            notices.append({"noticeNm": fields["noticeNm"], "noticeDesc": desc[:256]})
        contents_declarations = [entry["noticeDesc"] for entry in notices if entry["noticeNm"] == "포장단위별 내용물의 용량(중량), 수량"]
        contents = contents_declarations[0] if contents_declarations else ""
        unit_metadata = normalize_unit_metadata(name=name)
        if not self._detail_quantity_complete(name, unit_metadata):
            return None
        def receipt(meta):
            quantity, unit = meta.get("package_quantity"), (meta.get("package_unit") or "").lower()
            if unit in {"l", "kg"}:
                quantity, unit = quantity * 1000, {"l": "ml", "kg": "g"}[unit]
            return quantity, unit, meta.get("bundle_count", 1)
        for declaration in contents_declarations:
            notice_metadata = normalize_unit_metadata(name="", raw_unit=declaration)
            if (notice_metadata.get("package_quantity") is None
                    or not self._detail_quantity_complete(declaration, notice_metadata)):
                return None
            if unit_metadata.get("package_quantity") is not None and receipt(unit_metadata) != receipt(notice_metadata):
                return None
            unit_metadata = notice_metadata
        etc = node.get("etc") if isinstance(node.get("etc"), dict) else {}
        disabled_unit_display = etc.get("unitDispYn") == "N"
        if disabled_unit_display and any(
                etc.get(key) is not None and (type(etc[key]) not in (int, float) or etc[key] != 0)
                for key in ("totalUnitQty", "unitQty", "unitPrice", "cardUnitPrice")):
            return None
        if not disabled_unit_display and etc.get("totalUnitQty") is not None and etc.get("unitMeasure") is not None and unit_metadata.get("package_quantity") is not None:
            raw_total = etc["totalUnitQty"]
            total = raw_total if type(raw_total) in (int, float) and raw_total > 0 and raw_total == raw_total and abs(raw_total) != float("inf") else None
            source_unit = str(etc["unitMeasure"]).lower()
            expected_quantity, expected_unit, count = receipt(unit_metadata)
            if source_unit in {"l", "kg"} and total is not None:
                total, source_unit = total * 1000, {"l": "ml", "kg": "g"}[source_unit]
            if total is None or source_unit != expected_unit or total != expected_quantity * count:
                return None
        # Only product business fields are curated. Public purchase declarations
        # are not account secrets; absence remains unknown, never minimum one.
        source = {
            "basic": self._bounded_source_fields(basic, ("itemNo", "itemNm", "storeKind", "storeType", "storeId", "docId", "itemType", "itemStatus", "mallType", "rcateCd", "rcateNm", "lcateNm", "mcateNm", "scateNm", "dcateNm")),
            "sale": self._bounded_source_fields(sale, ("salePrice", "dcPrice", "dcRate", "currency", "currencyCode", "priceCurrency", "priceSuffix", "giftYn", "rsvYn", "rsvStartDt", "rsvEndDt", "stickerEvent", "recomMsg", "frontDcPriceInfo", "frontCardDcPriceInfo", "clearanceYn", "clearanceDiscountRate", "saleUnit", "saleUnitMeasure", "totalUnitQty", "couponYn", "purchaseMinQty", "purchaseMin", "purchaseLimitYn", "purchaseLimitDuration", "purchaseLimitDay", "purchaseLimitQty", "cartLimitYn", "itemPurchaseLimitMessage", "salePeriodYn", "saleStartDt", "saleEndDt")),
            "opt": self._bounded_source_fields(options, ("groupUseYn", "optSelUseYn", "optTxtUseYn", "optTitleDepth", "optTxtDepth")),
            "notice": notices,
            "etc": self._bounded_source_fields(etc, ("totalUnitQty", "unitMeasure", "unitQty", "unitDispYn", "unitPrice", "cardUnitPrice", "sameClassLimitYn", "sameClassLimitQty", "scgLimitYn", "scgLimitQty", "scgUnitMeasure")),
        }
        # Preserve actual empty public business lists without copying opaque event
        # identifiers or arbitrary nested benefit/account objects.
        for key in ("dcPriceInfo", "eventList", "stickerEventList", "labelList"):
            if sale.get(key) == []:
                source["sale"][key] = []
        promo = node.get("promo") if isinstance(node.get("promo"), dict) else {}
        coupon_keys = ("displayCouponNm", "manageCouponNm", "storeType", "couponType", "purchaseMin", "discount", "discountType", "discountMax", "validType", "validDay", "validStartDt", "validEndDt", "issueStartDt", "issueEndDt", "downloadAvailYn", "issueYn", "issueLimitType", "issueMaxCnt", "issueTimeYn", "issueStartTime", "issueEndTime", "limitPerCnt", "limitPerDayYn", "limitPerDayCnt", "liquorExceptYn", "localLiquorExceptYn")
        source["promo"] = self._bounded_source_fields(promo, ("couponCnt",))
        if isinstance(promo.get("couponInfo"), dict):
            source["promo"]["couponInfo"] = self._bounded_source_fields(promo["couponInfo"], coupon_keys)
        if isinstance(promo.get("couponList"), list):
            source["promo"]["couponList"] = [self._bounded_source_fields(coupon, coupon_keys) for coupon in promo["couponList"][:8] if isinstance(coupon, dict)]
        event_values = []
        event_list = sale.get("eventList", []) if isinstance(sale.get("eventList"), list) else []
        if len(event_list) > 8:
            return None
        curated_events = []
        for entry in event_list:
            if isinstance(entry, str):
                if len(entry) > 256:
                    return None
                event_values.append(entry[:256])
                curated_events.append(entry)
            elif isinstance(entry, dict):
                try:
                    curated_events.append(self._detail_event_source_fields(entry))
                except ValueError:
                    return None
                event_values.extend(value for key, value in entry.items() if key in {"eventNm", "eventName", "eventBtnText", "description", "dispEventLabel"} and isinstance(value, str))
        if event_list:
            source["sale"]["eventList"] = curated_events
        event_info = promo.get("eventInfo")
        if isinstance(event_info, dict):
            try:
                source["promo"]["eventInfo"] = self._detail_event_source_fields(event_info)
            except ValueError:
                return None
            event_values.extend(value for key, value in event_info.items() if key in {"eventNm", "eventName", "eventBtnText", "description", "dispEventLabel"} and isinstance(value, str))
        if len(event_values) > 8:
            return None
        source["event_texts"] = event_values[:8]
        source["event_markers"] = {
            "sale_eventList_present": "eventList" in sale,
            "sale_eventList_count": len(sale["eventList"]) if isinstance(sale.get("eventList"), list) else None,
            "promo_eventInfo_present": "eventInfo" in promo,
            "promo_eventInfo_type": type(promo.get("eventInfo")).__name__,
        }
        detail_url = normalize_homeplus_url(native, declared_store)
        category_path = [basic[key] for key in ("lcateNm", "mcateNm", "scateNm", "dcateNm") if isinstance(basic.get(key), str)]
        display_unit = unit_metadata.get("display_unit") or contents
        attrs = build_source_attributes("homeplus", source_record_key=native, detail_url=detail_url,
                                        category=self._category_from_product(basic))
        attrs.update(unit_metadata.get("attributes") or {})
        attrs.update({"source": "homeplus", "storeType": declared_store, "mart_native_code": native,
                      "bundle_count": unit_metadata.get("bundle_count"),
                      "canonical_url": detail_url, "raw_name": name, "docId": basic.get("docId") or "",
                      "mart_native_category_id": str(basic.get("rcateCd") or ""),
                      "mart_native_category_path": " > ".join(category_path),
                      "homeplus_detail_source_fields": source,
                      "homeplus_detail_source_fields_sha256": hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                      "promotion_conditions": {"source_condition_kind": "source_quote_purchase_conditions_unverified",
                          "payable_price_unconfirmed": True, "minimum_purchase_quantity_unconfirmed": True,
                          "coupon_application_unconfirmed": True},
                      "source_event_absent": sale.get("eventList") in (None, []) and promo.get("eventInfo") is None})
        minimum = sale.get("purchaseMinQty")
        if type(minimum) is int and minimum > 0:
            # Product-level source minimum is separate from an unresolved basket
            # promotion's payable/selection conditions. Never default to one.
            attrs["source_minimum_purchase_quantity"] = minimum
        attrs["source_quote_currency"] = next((source["sale"][key] for key in ("currency", "currencyCode", "priceCurrency") if key in source["sale"]), None)
        return DiscountItem(name=name, store="홈플러스", source="homeplus", sale_price=quote,
                            original_price=None, discount_percent=None, unit=display_unit, display_unit=display_unit,
                            package_quantity=unit_metadata.get("package_quantity"), package_unit=unit_metadata.get("package_unit") or "",
                            price_per_100g=None, category=self._category_from_product(basic), attributes=attrs,
                            detail_url=detail_url, event_name=" · ".join(event_values[:8]), promo_type=None, promo_label=None)

    def _image_url_from_product(self, product: dict) -> str:
        for key in (
            "imgUrl", "goodsImg", "imageUrl", "itemImg", "itemImgUrl", "itemImgPath",
            "repImgUrl", "repImageUrl", "thumbnail", "thumbnailUrl", "thumImgUrl",
        ):
            value = str(product.get(key) or "").strip()
            if value:
                return self._absolute_url(value, self.MFRONT_URL)
        images = product.get("images") or product.get("imageList") or product.get("imgList")
        if isinstance(images, list):
            for row in images:
                if isinstance(row, str) and row.strip():
                    return self._absolute_url(row.strip(), self.MFRONT_URL)
                if isinstance(row, dict):
                    for key in ("url", "imgUrl", "imageUrl", "src"):
                        value = str(row.get(key) or "").strip()
                        if value:
                            return self._absolute_url(value, self.MFRONT_URL)
        return ""

    def _extract_item_no_from_product(self, product: dict) -> str:
        for key in ("itemNo", "itemId"):
            raw = product.get(key)
            digits = re.sub(r"\D", "", str(raw or ""))
            if digits:
                return digits.zfill(9) if len(digits) <= 9 else digits
        for key in ("goodsNo", "id"):
            raw = str(product.get(key) or "").strip()
            if re.fullmatch(r"\d{9,}", raw):
                return raw
        return ""

    def _category_from_product(self, product: dict) -> str:
        for key in ("categoryNm", "ctgNm", "dcateNm", "scateNm", "mcateNm", "lcateNm", "rcateNm", "category"):
            value = product.get(key)
            if value:
                return str(value).strip()
        return ""

    def _display_unit_from_api(self, product: dict) -> str:
        total = product.get("totalUnitQty")
        unit = product.get("unitMeasure")
        if total and unit:
            try:
                qty = int(float(total)) if float(total).is_integer() else float(total)
                return f"{qty}{unit}"
            except Exception:
                return f"{total}{unit}"
        return ""

    def _unit_price_from_product(self, product: dict) -> dict:
        unit_price = self._to_float(product.get("unitPrice"))
        unit_qty = product.get("unitQty")
        measure = product.get("unitMeasure")
        result: dict = {}
        if unit_price:
            result["unit_price_displayed"] = unit_price
        if unit_qty and measure:
            try:
                qty = int(float(unit_qty)) if float(unit_qty).is_integer() else float(unit_qty)
            except Exception:
                qty = unit_qty
            result["unit_price_basis_raw"] = f"{qty}{measure}"
        return result

    def _extract_json_promo_label(self, product: dict) -> str | None:
        candidates: list[str] = []
        for key in ("stickerEvent", "eventBtnText", "promoLabel", "promotionLabel"):
            value = product.get(key)
            if value:
                candidates.append(str(value))
        event_info = product.get("eventInfo")
        if isinstance(event_info, dict):
            candidates.extend(str(v) for v in event_info.values() if v)
        for key in ("stickerEventList", "eventFlagList", "benefitLabelList", "labelList", "eventInfoList"):
            value = product.get(key)
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        candidates.extend(str(v) for v in entry.values() if v)
                    elif entry:
                        candidates.append(str(entry))
        for value in candidates:
            match = self.PROMO_LABEL_RE.search(value)
            if match:
                return re.sub(r"\s*\+\s*", "+", match.group(0))
        return None

    def _permanent_product_url(self, item_no: str, name: str) -> str:
        slug_source = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-") or item_no
        slug = quote(slug_source[:80])
        return f"{self.MFRONT_URL}/p/{slug}/{item_no}"

    def _normalize_legacy_detail_url(self, raw_url: str) -> str:
        raw_url = str(raw_url or "").strip()
        if not raw_url:
            return ""
        parsed = urlparse(raw_url)
        path = parsed.path or ""
        query = parse_qs(parsed.query)
        if path.startswith("/p/"):
            return self._absolute_url(raw_url, self.MFRONT_URL)
        if "gnbNo" in query or "promoNo" in query:
            return ""
        if path == "/item" and re.fullmatch(r"\d+", (query.get("itemNo") or [""])[0]):
            return self._absolute_url(raw_url, self.MFRONT_URL)
        if path.startswith("/goods/detail"):
            return self._absolute_url(raw_url, self.BASE_URL)
        return self._absolute_url(raw_url, self.BASE_URL)

    def _parse_html(self, soup, store_type: str = "HYPER") -> list[DiscountItem]:
        items: list[DiscountItem] = []
        mfront_cards = soup.select(".unitItemInner")
        if mfront_cards:
            for card in mfront_cards:
                item = self._parse_mfront_card(card, store_type=store_type)
                if item:
                    items.append(item)
            return items
        for card in soup.select(".product-item, .goods_item, .event_item, .item_box, .prod_wrap"):
            item = self._parse_product_card(card)
            if item:
                items.append(item)
        return items

    def _parse_mfront_card(self, card, store_type: str = "HYPER") -> Optional[DiscountItem]:
        store_type = self._normalize_store_type(store_type)
        img_el = card.select_one("img")
        image_url = img_el.get("src") or img_el.get("data-src", "") if img_el else ""
        full_text = card.get_text(separator=" ", strip=True)
        item_no, link_store_type = self._extract_homeplus_item_identity(card, store_type)
        if not item_no:
            return None
        store_type = link_store_type or store_type
        canonical_url = normalize_homeplus_url(item_no, store_type)
        prices = []
        for pv in card.select(".priceValue"):
            price = self._extract_price(pv.get_text(strip=True))
            if price and price > 0:
                prices.append(price)
        if not prices:
            price_container = card.select_one(".price") or card
            for match in re.finditer(r"(\d{1,3}(?:,\d{3})+)\s*원", price_container.get_text(" ")):
                prices.append(int(match.group(1).replace(",", "")))
        unit_price_info = self._parse_homeplus_unit_price(full_text)
        prices = [price for price in prices if price != unit_price_info.get("unit_price_displayed")]
        if not prices:
            return None
        sale_price = min(prices)
        original_price = max(prices) if len(prices) >= 2 else None
        if sale_price <= 0:
            return None
        discount_pct = None
        pct_match = re.search(r"(\d{1,2})%", full_text)
        if pct_match:
            discount_pct = float(pct_match.group(1))
        elif original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)
        name = self._extract_mfront_name(card, img_el)
        if len(name) < 2:
            return None
        category = card.get("data-category") or card.get("data-ctg-nm") or card.get("data-category-name") or ""
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")
        brand = self._extract_brand(name)
        normalized_name = re.sub(r"\[[^\]]+\]", "", name)
        normalized_name = re.sub(r"\s+", " ", normalized_name).strip()
        pack_qty = unit_metadata.get("package_quantity") or ""
        pack_unit = unit_metadata.get("package_unit") or ""
        promo_label = self._extract_homeplus_promo_label(card)
        attrs = {
            **(unit_metadata.get("attributes") or {}),
            **unit_price_info,
            **build_source_attributes(
                "homeplus",
                source_record_key=normalize_source_key("homeplus", item_no, canonical_url, name),
                detail_url=canonical_url,
                image_url=image_url,
                category=category,
            ),
            "storeType": store_type,
            "mart_native_code": item_no,
            "canonical_url": canonical_url,
            "external_seller": classify_external_seller_homeplus(full_text),
            "canon_hash": compute_canon_hash(brand, normalized_name, pack_qty, pack_unit),
            "brand": brand,
            "raw_name": name,
            "normalized_name": normalized_name,
        }
        if promo_label:
            attrs["promo_label"] = promo_label
        attrs = inject_source_field(attrs, "homeplus")
        return DiscountItem(
            name=name,
            normalized_name=normalized_name,
            store="홈플러스",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=attrs,
            category=category,
            image_url=image_url,
            detail_url=canonical_url,
            event_name=promo_label or "홈플러스 할인",
            promo_label=promo_label,
        )

    def _extract_homeplus_promo_label(self, card) -> str | None:
        candidates = []
        for selector in (".promotionFlag .flag", ".moreBtnWrap .list-btn", ".recomComment", ".flag", ".badge"):
            for el in card.select(selector):
                candidates.extend(value for value in (str(el.get("title") or "").strip(), el.get_text(" ", strip=True)) if value)
        for value in candidates:
            match = self.PROMO_LABEL_RE.search(value)
            if match:
                return re.sub(r"\s*\+\s*", "+", match.group(0).strip())
        return None

    def _parse_homeplus_unit_price(self, text: str) -> dict:
        parsed = parse_unit_price(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, tuple) and len(parsed) >= 2:
            price, basis = parsed[0], parsed[1]
            if price is None or basis is None:
                return {}
            return {"unit_price_displayed": int(price), "unit_price_basis_raw": str(basis)}
        return {}

    def _extract_homeplus_item_identity(self, card, default_store_type: str = "HYPER") -> tuple[str, str]:
        default_store_type = self._normalize_store_type(default_store_type)
        for attr in ("data-item-no", "data-itemno", "data-item_no", "data-goods-no"):
            digits = re.sub(r"\D", "", str(card.get(attr) or ""))
            if re.fullmatch(r"\d{9}", digits):
                return digits, default_store_type
        for link in card.select("a[href]"):
            href = str(link.get("href") or "").strip()
            parsed = urlparse(href)
            path = parsed.path or href.split("?", 1)[0]
            if path != "/item" and not path.endswith("/item"):
                continue
            query = parse_qs(parsed.query)
            item_no = (query.get("itemNo") or [""])[0]
            if not re.fullmatch(r"\d{9}", item_no):
                continue
            return item_no, self._normalize_store_type((query.get("storeType") or [default_store_type])[0])
        return "", default_store_type

    def _extract_mfront_name(self, card, img_el) -> str:
        for selector in (".itemName", ".productName", ".unit_title", "[class*='name' i]", "[class*='Name']", "[class*='title' i]"):
            el = card.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                if len(text) >= 2:
                    return text
        if img_el:
            alt = (img_el.get("alt") or "").strip()
            if len(alt) >= 2:
                return alt
        full = card.get_text(separator="|", strip=True)
        name = re.sub(r"\d{1,3}(?:,\d{3})*\s*원", "", full)
        name = re.sub(r"\d{1,2}%", "", name)
        name = re.sub(r"\d+\.\d+/\d+", "", name)
        name = re.sub(r"(상품할인|매직배송|무료배송|당일배송|만원[↑↓]?)", "", name)
        name = re.sub(r"\|", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:100] if name else ""

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        name_el = card.select_one(".product-name, .goods_name, .item_name, .prod_name, a[href*='goods']")
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if len(name) < 2:
            return None
        sale_price = self._extract_price_from_element(card, ".sale_price, .price .num, .discount_price, .spc_price")
        original_price = self._extract_price_from_element(card, ".origin_price, .normal_price, .org_price, .before_price")
        if not sale_price or sale_price <= 0:
            return None
        discount_pct = round((1 - sale_price / original_price) * 100, 1) if original_price and original_price > sale_price else None
        img_el = card.select_one("img")
        image_url = img_el.get("src") or img_el.get("data-src", "") if img_el else ""
        link_el = card.select_one("a[href]")
        detail_url = self._normalize_legacy_detail_url(link_el.get("href", "")) if link_el else ""
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")
        category = card.get("data-category") or card.get("data-ctg-nm") or card.get("data-category-name") or ""
        if not category:
            category_el = card.select_one(".category, .breadcrumb, .location")
            category = category_el.get_text(" > ", strip=True) if category_el else ""
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
            attributes={
                **(unit_metadata.get("attributes") or {}),
                **build_source_attributes("homeplus", source_record_key=normalize_source_key("homeplus", detail_url, name), detail_url=detail_url, image_url=image_url, category=category),
            },
            category=category,
            image_url=image_url,
            detail_url=detail_url,
            event_name="홈플러스 할인",
        )

    def _absolute_url(self, url: str, base_url: str) -> str:
        return absolute_url(url, base_url)

    def _extract_price_from_element(self, card, selectors: str) -> Optional[int]:
        for selector in selectors.split(","):
            el = card.select_one(selector.strip())
            if el:
                price = self._extract_price(el.get_text(strip=True))
                if price is not None:
                    return price
        return None

    def _extract_price(self, text: str) -> Optional[int]:
        if not text:
            return None
        for pattern in (r"(\d{1,3}(?:,\d{3})+)", r"(\d{3,})"):
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    def _to_int(self, value, *, allow_zero: bool = False) -> int | float | None:
        """Legacy money helper name; retain fractions and validate complete quotes."""
        if isinstance(value, str):
            match = re.fullmatch(r"(?:₩\s*)?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:원)?", value.strip())
            if not match:
                return None
            value = match.group(1).replace(",", "")
        number = confirmed_price_or_none(value)
        if number is not None:
            return number
        if allow_zero and not isinstance(value, bool):
            if isinstance(value, (int, float)) and value == 0:
                return 0
            if isinstance(value, str) and re.fullmatch(r"0+(?:\.0+)?", value):
                return 0
        return None

    def _to_float(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _normalize_store_type(self, store_type: str | None) -> str:
        value = str(store_type or "HYPER").upper()
        return value if value in {"HYPER", "EXP"} else "HYPER"

    def _extract_brand(self, name: str) -> str:
        match = re.match(r"\[([^\]]+)\]", name or "")
        if match:
            return match.group(1).strip()
        parts = (name or "").split()
        return parts[0] if parts else ""

    @staticmethod
    def _homeplus_scroll_stop_signals(*, unchanged_streak: int, end_marker_present: bool, latest_xhr_empty: bool) -> dict:
        signals = {
            "unchanged_5": int(unchanged_streak) >= 5,
            "end_marker": bool(end_marker_present),
            "latest_xhr_empty": bool(latest_xhr_empty),
        }
        satisfied = sum(1 for value in signals.values() if value)
        return {**signals, "satisfied": satisfied, "stop": satisfied >= 2}

    def _dedupe_items(self, items: list[DiscountItem]) -> list[DiscountItem]:
        deduped: list[DiscountItem] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)
        return deduped

    def _limit_items(self, items: list[DiscountItem]) -> list[DiscountItem]:
        if self.MAX_ITEMS is None:
            return items
        return items[: max(0, int(self.MAX_ITEMS))]

    def count_raw_candidates(self, raw_data: str) -> int:
        json_items = self._extract_json_items(raw_data)
        if json_items:
            return len(json_items)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            count = len(soup.select(".unitItemInner, .product-item, .goods_item, .event_item, .item_box, .prod_wrap"))
            del soup
            return count
        except Exception:
            return 0

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen:
                continue
            seen.add(key)
            if item.sale_price <= 0 or len(item.name) < 2:
                continue
            valid.append(item)
        return valid
