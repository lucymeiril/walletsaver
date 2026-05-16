"""Marketplace source connector utilities.

These connectors intentionally avoid unbounded live marketplace collection. They
provide deterministic parsing contracts for saved/source fixtures plus URL and
pagination helpers that can be used by bounded diagnostics after approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerGroup,
    CrawlerInfo,
    CrawlResult,
    CrawlStatus,
    DiscountItem,
    ErrorType,
    StrategyFailure,
)
from pipeline.quality import summarize_discount_run

_PRICE_KEYS = (
    "salePrice",
    "sale_price",
    "finalPrice",
    "final_price",
    "discountPrice",
    "discount_price",
    "couponPrice",
    "coupon_price",
    "salePriceText",
    "sale_price_text",
    "priceText",
    "price_text",
    "sellPrice",
    "sell_price",
    "lowestPrice",
    "price",
)
_ORIGINAL_PRICE_KEYS = (
    "originalPrice",
    "original_price",
    "normalPrice",
    "normal_price",
    "listPrice",
    "list_price",
    "basePrice",
    "base_price",
    "retailPrice",
)
_NAME_KEYS = ("name", "title", "productName", "product_name", "itemName", "goodsName", "goods_name")
_URL_KEYS = (
    "url",
    "detailUrl",
    "detail_url",
    "productUrl",
    "product_url",
    "sourceUrl",
    "source_url",
    "link",
    "landingUrl",
)
_IMAGE_KEYS = ("image", "imageUrl", "image_url", "thumbnail", "thumbnailUrl", "imgUrl", "imagePath")
_CATEGORY_KEYS = ("category", "categoryName", "category_name", "brand", "brandName", "mallName", "sellerName")
_RECORD_KEY_KEYS = (
    "source_record_key",
    "productId",
    "product_id",
    "itemId",
    "item_id",
    "goodsCode",
    "goods_code",
    "itemNo",
    "item_no",
    "sku",
    "id",
)
_CARD_SELECTOR = ", ".join(
    [
        "[data-testid='product-card']",
        "[data-product-card]",
        "[data-product-id]",
        "[data-item-id]",
        "[data-goods-code]",
        ".search-product",
        ".box__item-container",
        ".box__component-itemcard",
        ".c-card-item",
        ".basicList_item",
        ".product_item",
        ".search-item-card-wrapper",
        ".product-card",
        ".goods-card",
        ".item",
        "li",
    ]
)
_NAME_SELECTOR = ", ".join(
    [
        "[data-field='name']",
        ".name",
        ".title",
        ".product-name",
        "[itemprop='name']",
        ".search-product-wrap .name",
        ".descriptions-inner .name",
        ".box__item-title",
        ".text__item",
        ".c-card-item__name",
        ".pname",
        ".basicList_title",
        ".product_title",
        ".multi--titleText",
        "h3",
    ]
)
_PRICE_SELECTOR = ", ".join(
    [
        "[data-field='sale_price']",
        "[data-field='price']",
        ".sale-price",
        ".price-value",
        ".price .value",
        ".box__price-seller strong",
        ".text__value",
        ".c-card-item__price",
        ".sale_price",
        ".basicList_price .price_num",
        ".price_num",
        ".product_price",
        ".multi--price-sale",
        ".price-current",
        ".price",
        "[itemprop='price']",
    ]
)
_ORIGINAL_PRICE_SELECTOR = ", ".join(
    [
        "[data-field='original_price']",
        ".original-price",
        ".normal-price",
        ".list-price",
        ".base-price",
        ".text__price-original",
        ".c-card-item__price-original",
        ".price_original",
        "del",
        "s",
    ]
)
_IMAGE_SELECTOR = "img[src], img[data-src], img[data-original], img[data-img-src], img[data-lazy], img[srcset]"
MARKETPLACE_PARSER_CONTRACT = "marketplace_skeleton.v1"
MARKETPLACE_FIXTURE_CONTRACT = "marketplace_skeleton_fixture_contracts.v1"
MARKETPLACE_REQUIRED_EVIDENCE_BEFORE_LIVE = [
    "fixture_contract_passed",
    "bounded_live_diagnostics_passed",
    "bounded_run_limits_recorded",
    "operator_approval_recorded",
]
MARKETPLACE_OPERATOR_NEXT_ACTIONS = [
    "Run saved-fixture diagnostics and confirm source_raw, parsed, valid, validation-drop, duplicate, and critical-field evidence.",
    "If fixture diagnostics pass, prepare a no-DB AI review artifact; do not mutate production data from connector fixture output.",
    "Only after bounded live diagnostics record max_requests, max_pages, timeout_seconds, evidence_id, and operator approval may live_ready be reconsidered.",
]


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        return parsed if parsed > 0 else None
    match = re.search(r"[\d,]+", str(value).replace("원", "").replace("₩", ""))
    if not match:
        return None
    parsed = int(match.group(0).replace(",", ""))
    return parsed if parsed > 0 else None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class MarketplaceSkeletonCrawler(CrawlerContract):
    """Base parser contract for marketplace source connectors backed by fixtures."""

    SOURCE_ID: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    BASE_URL: ClassVar[str]
    DESCRIPTION: ClassVar[str]
    SEARCH_PATH: ClassVar[str] = "/search"
    SEARCH_QUERY_PARAM: ClassVar[str] = "q"
    PAGE_PARAM: ClassVar[str] = "page"
    MAX_LIVE_REQUESTS: ClassVar[int] = 1
    MAX_LIVE_PAGES: ClassVar[int] = 1
    LIVE_TIMEOUT_SECONDS: ClassVar[int] = 10

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name=self.DISPLAY_NAME,
            version="0.2.0",
            group=CrawlerGroup.SHOPPING,
            description=(
                f"{self.DESCRIPTION} — source connector parser; live_ready still requires the fixture contract, "
                "bounded diagnostics evidence, run limits, and operator approval"
            ),
            target_url=self.BASE_URL,
            strategies=["fixture-html", "fixture-json", "source-url-builder"],
        )

    def build_search_url(self, query: str, *, page: int = 1, **params: Any) -> str:
        query_params = {self.SEARCH_QUERY_PARAM: query, self.PAGE_PARAM: max(1, int(page)), **params}
        return urljoin(self.BASE_URL, self.SEARCH_PATH) + "?" + urlencode(query_params)

    def build_category_url(self, category_path: str, *, page: int = 1, **params: Any) -> str:
        url = category_path if category_path.startswith(("http://", "https://")) else urljoin(self.BASE_URL, category_path)
        separator = "&" if urlparse(url).query else "?"
        query_params = {self.PAGE_PARAM: max(1, int(page)), **params}
        return url + separator + urlencode(query_params)

    def next_page_url(self, raw_data: str, *, current_url: str = "") -> str:
        soup = BeautifulSoup(raw_data or "", "html.parser")
        next_node = soup.select_one("link[rel='next'][href], a[rel='next'][href], a.next[href], .pagination a.next[href]")
        if next_node and next_node.get("href"):
            return self._absolute_url(next_node.get("href"))
        marker = soup.select_one("[data-next-page]")
        if marker and marker.get("data-next-page"):
            return self.build_search_url("", page=_parse_int(marker.get("data-next-page")) or 1) if not current_url else self._replace_page(current_url, marker.get("data-next-page"))
        return ""

    async def crawl_incremental(
        self,
        *,
        since: str | None = None,
        source_input: str | None = None,
        source_url: str | None = None,
        max_pages: int | None = None,
        max_requests: int | None = None,
        timeout_seconds: int | None = None,
    ) -> CrawlResult:
        if source_input is not None:
            return await self.crawl(fixture=source_input)
        if source_url:
            return await self.crawl_bounded_source_url(
                source_url,
                max_pages=max_pages or self.MAX_LIVE_PAGES,
                max_requests=max_requests or self.MAX_LIVE_REQUESTS,
                timeout_seconds=timeout_seconds or self.LIVE_TIMEOUT_SECONDS,
            )
        return await self.crawl()

    async def crawl_bounded_source_url(
        self,
        source_url: str,
        *,
        max_pages: int = 1,
        max_requests: int = 1,
        timeout_seconds: int = 10,
    ) -> CrawlResult:
        started_at = datetime.now()
        max_pages = max(1, min(int(max_pages), self.MAX_LIVE_PAGES))
        max_requests = max(1, min(int(max_requests), self.MAX_LIVE_REQUESTS))
        timeout_seconds = max(1, min(int(timeout_seconds), self.LIVE_TIMEOUT_SECONDS))
        run_limits = {
            "max_requests": max_requests,
            "max_pages": max_pages,
            "timeout_seconds": timeout_seconds,
        }

        safe_url_error = self._validate_live_source_url(source_url)
        if safe_url_error:
            return self._blocked_live_result(started_at, source_url, safe_url_error, run_limits)

        fetch_diagnostics: dict[str, Any] = {
            "source_url": source_url,
            "requests_attempted": 1,
            "pages_attempted": 1,
            "run_limits": run_limits,
            "auth_bypass_attempted": False,
            "cookies_sent": False,
        }
        try:
            response = await asyncio.to_thread(self._fetch_live_source, source_url, timeout_seconds)
        except requests.RequestException as exc:
            blocker = f"{self.SOURCE_ID} bounded live fetch failed: {type(exc).__name__}: {exc}"
            fetch_diagnostics.update({"blocked": True, "blocker": blocker})
            return self._blocked_live_result(started_at, source_url, blocker, run_limits, fetch_diagnostics)

        final_url = str(response.url)
        fetch_diagnostics.update(
            {
                "status_code": response.status_code,
                "final_url": final_url,
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(response.content or b""),
            }
        )
        redirect_error = self._validate_live_source_url(final_url)
        if redirect_error:
            blocker = f"{self.SOURCE_ID} bounded live fetch redirected outside the approved source host: {final_url}"
            fetch_diagnostics.update({"blocked": True, "blocker": blocker})
            return self._blocked_live_result(started_at, source_url, blocker, run_limits, fetch_diagnostics)
        if response.status_code in {401, 403, 429}:
            blocker = (
                f"{self.SOURCE_ID} bounded live fetch blocked by public site response "
                f"HTTP {response.status_code}; no authentication/access-control bypass attempted."
            )
            fetch_diagnostics.update({"blocked": True, "blocker": blocker})
            return self._blocked_live_result(started_at, source_url, blocker, run_limits, fetch_diagnostics)
        if response.status_code >= 400:
            blocker = f"{self.SOURCE_ID} bounded live fetch returned HTTP {response.status_code}."
            fetch_diagnostics.update({"blocked": True, "blocker": blocker})
            return self._blocked_live_result(started_at, source_url, blocker, run_limits, fetch_diagnostics)

        raw_text = response.text or ""
        source_raw_count = self.count_raw_candidates(raw_text)
        parsed_items = await self.parse(raw_text)
        valid_items = await self.validate(parsed_items)
        valid_items = self._tag_collection_metadata(
            valid_items,
            collection_mode="bounded_live_http_no_db",
            source_request_url=source_url,
            source_final_url=final_url,
        )
        fetch_diagnostics.update(
            {
                "blocked": False,
                "source_raw": source_raw_count,
                "parsed": len(parsed_items),
                "valid": len(valid_items),
            }
        )
        return self._result(
            started_at,
            valid_items,
            raw_count=len(parsed_items),
            source_raw_count=source_raw_count,
            invalid_count=max(0, len(parsed_items) - len(valid_items)),
            errors=[],
            fixture_available=False,
            strategy_used="bounded-http-source-fetch",
            live_enabled=True,
            collection_mode="bounded_live_http_no_db",
            source_url=source_url,
            fetch_diagnostics=fetch_diagnostics,
            run_limits=run_limits,
        )

    async def crawl(self, raw_data: str | None = None, fixture: str | None = None, **_: Any) -> CrawlResult:
        started_at = datetime.now()
        source = fixture if fixture is not None else raw_data
        source_errors: list[str] = []
        if not source:
            source_errors.append(
                f"{self.SOURCE_ID} source connector has no configured safe fixture/input; "
                "live crawling is intentionally disabled and live collection remains blocked."
            )
            return self._result(
                started_at,
                [],
                raw_count=0,
                source_raw_count=0,
                errors=source_errors,
                fixture_available=False,
            )

        try:
            source_raw_count = self.count_raw_candidates(source)
            parsed_items = await self.parse(source)
            valid_items = await self.validate(parsed_items)
            return self._result(
                started_at,
                valid_items,
                raw_count=len(parsed_items),
                source_raw_count=source_raw_count,
                invalid_count=max(0, len(parsed_items) - len(valid_items)),
                errors=source_errors,
                fixture_available=True,
            )
        except Exception as exc:  # pragma: no cover - defensive contract guard
            finished_at = datetime.now()
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                strategy_used="fixture-source-parser",
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                errors=[StrategyFailure(strategy_name="fixture-source-parser", error_type=ErrorType.PARSE_ERROR, error_msg=str(exc))],
                error_msg=str(exc),
            )

    def _result(
        self,
        started_at: datetime,
        items: list[DiscountItem],
        *,
        raw_count: int,
        source_raw_count: int,
        invalid_count: int = 0,
        errors: list[str] | None = None,
        fixture_available: bool = True,
        strategy_used: str = "fixture-source-parser",
        live_enabled: bool = False,
        collection_mode: str = "fixture_source_parser",
        source_url: str | None = None,
        fetch_diagnostics: dict[str, Any] | None = None,
        run_limits: dict[str, Any] | None = None,
    ) -> CrawlResult:
        items_as_dict = [item.model_dump(mode="json") for item in items]
        quality_details = summarize_discount_run(
            items_as_dict,
            raw_count=raw_count,
            source_raw_count=source_raw_count,
            invalid_count=invalid_count,
            errors=errors,
            strategy_used=strategy_used,
            live_enabled=live_enabled,
            fixture_available=fixture_available,
        )
        effective_run_limits = run_limits or {
            "max_requests": None,
            "max_pages": None,
            "timeout_seconds": None,
        }
        quality_details.setdefault("fetch", {})
        quality_details["fetch"].update(fetch_diagnostics or {})
        quality_details["fetch"]["collection_mode"] = collection_mode
        quality_details["collection"] = {
            "mode": collection_mode,
            "source_url": source_url,
            "live_network_enabled": live_enabled,
            "no_db": True,
            "run_limits": effective_run_limits,
        }
        quality_details["readiness_gate"] = {
            "status": "bounded_live_diagnostic_no_db" if live_enabled else "skeleton_fixture_only",
            "live_ready": False,
            "collecting_claim_allowed": False,
            "safe_db_mutation_allowed": False,
            "parser_contract": MARKETPLACE_PARSER_CONTRACT,
            "fixture_contract": MARKETPLACE_FIXTURE_CONTRACT,
            "fixture_contract_status": "passed",
            "bounded_diagnostics": {
                "status": "completed_no_db" if live_enabled else "required_before_live_ready",
                "evidence_id": None,
                "captured_at": None,
                "run_limits": effective_run_limits,
                "fetch": fetch_diagnostics or {},
            },
            "operator_approval": {"status": "required_before_live_ready"},
            "required_evidence_before_live_ready": MARKETPLACE_REQUIRED_EVIDENCE_BEFORE_LIVE,
            "next_actions": MARKETPLACE_OPERATOR_NEXT_ACTIONS,
            "downstream_flow": {
                "current_stage": "bounded_live_no_db_diagnostics" if live_enabled else "fixture_diagnostics_only",
                "next_stage": "no_db_ai_review",
                "db_mutation_allowed": False,
            },
            "message": (
                "This marketplace source connector performed a bounded no-DB live diagnostic."
                if live_enabled
                else "This marketplace source connector parses saved/source fixtures only; it performs no live network collection."
            ),
        }
        status = CrawlStatus.SUCCESS if items else CrawlStatus.PARTIAL
        failures: list[StrategyFailure] = []
        if not items:
            diagnostic = quality_details.get("zero_result_diagnostic") or {}
            message = diagnostic.get("message") or "; ".join(errors or []) or "No marketplace fixture rows parsed."
            stage = diagnostic.get("stage")
            error_type = ErrorType.EMPTY_RESPONSE if stage == "source_zero_raw_rows" else ErrorType.PARSE_ERROR
            failures.append(StrategyFailure(strategy_name=strategy_used, error_type=error_type, error_msg=message))
            if not errors:
                errors = [message]
        finished_at = datetime.now()
        return CrawlResult(
            status=status,
            crawler_name=self.info.name,
            strategy_used=strategy_used,
            items_count=len(items),
            items=items_as_dict,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            errors=failures,
            error_msg="; ".join(errors or []) if not items else None,
            quality_score=quality_details["score"],
            quality_details=quality_details,
        )

    def _blocked_live_result(
        self,
        started_at: datetime,
        source_url: str,
        blocker: str,
        run_limits: dict[str, Any],
        fetch_diagnostics: dict[str, Any] | None = None,
    ) -> CrawlResult:
        diagnostics = {
            "blocked": True,
            "blocker": blocker,
            "run_limits": run_limits,
            **(fetch_diagnostics or {}),
        }
        return self._result(
            started_at,
            [],
            raw_count=0,
            source_raw_count=0,
            errors=[blocker],
            fixture_available=False,
            strategy_used="bounded-http-source-fetch",
            live_enabled=True,
            collection_mode="bounded_live_http_no_db",
            source_url=source_url,
            fetch_diagnostics=diagnostics,
            run_limits=run_limits,
        )

    def _fetch_live_source(self, source_url: str, timeout_seconds: int) -> requests.Response:
        return requests.get(
            source_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "User-Agent": "WalletSaviorCrawler/0.1 bounded-no-db-diagnostic",
            },
            timeout=timeout_seconds,
            allow_redirects=True,
        )

    def _validate_live_source_url(self, source_url: str) -> str:
        parsed = urlparse(source_url or "")
        base = urlparse(self.BASE_URL)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"{self.SOURCE_ID} bounded live fetch requires an absolute http(s) source_url."
        if parsed.username or parsed.password:
            return f"{self.SOURCE_ID} bounded live fetch refuses source_url credentials."
        if parsed.netloc.lower() != base.netloc.lower():
            return (
                f"{self.SOURCE_ID} bounded live fetch is limited to approved host "
                f"{base.netloc}; got {parsed.netloc}."
            )
        return ""

    def _tag_collection_metadata(
        self,
        items: list[DiscountItem],
        *,
        collection_mode: str,
        source_request_url: str,
        source_final_url: str,
    ) -> list[DiscountItem]:
        tagged: list[DiscountItem] = []
        for item in items:
            clone = item.model_copy(deep=True)
            attrs = dict(clone.attributes or {})
            attrs["collection_mode"] = collection_mode
            attrs["source_request_url"] = source_request_url
            attrs["source_final_url"] = source_final_url
            clone.attributes = attrs
            tagged.append(clone)
        return tagged

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        text = (raw_data or "").strip()
        if not text:
            return []
        if text[0] in "[{":
            return self._parse_json(text)
        return self._parse_html(text)

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen: set[str] = set()
        for item in items:
            if not item.name.strip() or item.sale_price <= 0:
                continue
            dedup_key = str(item.attributes.get("dedup_key") or "")
            if not dedup_key:
                dedup_key = f"{self.SOURCE_ID}:{item.name.strip().lower()}:{item.sale_price}:{item.detail_url}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            valid.append(item)
        return valid

    def count_raw_candidates(self, raw_data: str) -> int:
        text = (raw_data or "").strip()
        if not text:
            return 0
        if text[0] in "[{":
            try:
                return sum(1 for candidate in _iter_dicts(json.loads(text)) if self._json_has_candidate_fields(candidate))
            except json.JSONDecodeError:
                return 0
        soup = BeautifulSoup(text, "html.parser")
        return len(self._html_cards(soup))

    def _parse_json(self, raw_data: str) -> list[DiscountItem]:
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            return []
        items: list[DiscountItem] = []
        for rank, data in enumerate(_iter_dicts(payload), start=1):
            item = self._item_from_json_dict(data, rank=rank)
            if item:
                items.append(item)
        return items

    def _item_from_json_dict(self, data: dict[str, Any], *, rank: int | None = None) -> DiscountItem | None:
        name = _first_value(data, _NAME_KEYS)
        sale_price_raw = _first_value(data, _PRICE_KEYS)
        sale_price = _parse_int(sale_price_raw)
        if not name or not sale_price:
            return None
        original_price = _parse_int(_first_value(data, _ORIGINAL_PRICE_KEYS))
        discount_percent = _parse_float(data.get("discountPercent") or data.get("discount_percent") or data.get("discountRate"))
        detail_url = self._absolute_url(_first_value(data, _URL_KEYS))
        image_url = self._absolute_url(_first_value(data, _IMAGE_KEYS))
        category = str(_first_value(data, _CATEGORY_KEYS) or "")
        record_key = self._source_record_key(data=data, detail_url=detail_url)
        return DiscountItem(
            name=str(name).strip(),
            store=self.DISPLAY_NAME,
            sale_price=sale_price,
            original_price=original_price,
            discount_percent=discount_percent,
            category=category,
            image_url=image_url,
            detail_url=detail_url,
            attributes=self._attributes(
                name=str(name),
                detail_url=detail_url,
                price_evidence=str(sale_price_raw or sale_price),
                category=category,
                record_key=record_key,
                rank=rank,
                extra={
                    "post_date": data.get("postDate") or data.get("posted_at") or data.get("date"),
                    "period": data.get("period") or data.get("validPeriod") or data.get("eventPeriod"),
                    "seller_name": data.get("sellerName") or data.get("mallName"),
                },
            ),
        )

    def _parse_html(self, raw_data: str) -> list[DiscountItem]:
        soup = BeautifulSoup(raw_data, "html.parser")
        return [item for rank, card in enumerate(self._html_cards(soup), start=1) if (item := self._item_from_html_card(card, rank=rank))]

    def _html_cards(self, soup: BeautifulSoup) -> list[Any]:
        cards = [card for card in soup.select(_CARD_SELECTOR) if self._card_has_product_signal(card)]
        return cards if cards else soup.select("body")

    def _item_from_html_card(self, card: Any, *, rank: int | None = None) -> DiscountItem | None:
        name = self._select_text(card, _NAME_SELECTOR)
        price_evidence = self._select_text(card, _PRICE_SELECTOR)
        sale_price = _parse_int(price_evidence)
        if not name or not sale_price:
            return None
        detail_url = self._absolute_url(self._href(card))
        image_url = self._absolute_url(self._image_src(card))
        original_price = _parse_int(self._select_text(card, _ORIGINAL_PRICE_SELECTOR))
        discount_percent = _parse_float(self._select_text(card, "[data-field='discount_percent'], .discount, .discount-percent, .rate, .text__discount"))
        category = self._select_text(card, "[data-field='category'], .category, .brand, .brand-name, .text__brand, .mall")
        period = self._select_text(card, "[data-field='period'], .period, .valid-period, time")
        record_key = self._source_record_key(card=card, detail_url=detail_url)
        return DiscountItem(
            name=name,
            store=self.DISPLAY_NAME,
            sale_price=sale_price,
            original_price=original_price,
            discount_percent=discount_percent,
            category=category,
            image_url=image_url,
            detail_url=detail_url,
            attributes=self._attributes(
                name=name,
                detail_url=detail_url,
                price_evidence=price_evidence,
                category=category,
                record_key=record_key,
                rank=rank,
                extra={"period": period},
            ),
        )

    def _attributes(
        self,
        *,
        name: str,
        detail_url: str,
        price_evidence: str,
        category: str,
        record_key: str,
        rank: int | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dedup_value = record_key or detail_url or f"{name}:{price_evidence}"
        dedup_key = f"{self.SOURCE_ID}:{dedup_value}" if dedup_value else ""
        if not dedup_key:
            dedup_key = f"{self.SOURCE_ID}:fixture:{hashlib.sha1(price_evidence.encode('utf-8')).hexdigest()[:16]}"
        attrs = {
            "source": self.SOURCE_ID,
            "source_url": detail_url,
            "source_record_key": record_key,
            "source_product_id": record_key,
            "dedup_key": dedup_key,
            "incremental_key": record_key or detail_url,
            "source_rank": rank,
            "price_evidence": price_evidence,
            "category_hints": [category] if category else [],
            "parser_contract": MARKETPLACE_PARSER_CONTRACT,
            "fixture_contract": MARKETPLACE_FIXTURE_CONTRACT,
            "collection_mode": "fixture_source_parser",
        }
        for key, value in (extra or {}).items():
            if value not in (None, ""):
                attrs[key] = value
        return attrs

    def _card_has_product_signal(self, card: Any) -> bool:
        if card.select_one(_PRICE_SELECTOR) and (card.select_one(_NAME_SELECTOR) or card.select_one("a[href]")):
            return True
        attrs = getattr(card, "attrs", {}) or {}
        return any(key in attrs for key in ("data-product-id", "data-item-id", "data-goods-code"))

    def _select_text(self, card: Any, selector: str) -> str:
        node = card.select_one(selector)
        return _clean_text(node.get_text(" ", strip=True)) if node else ""

    def _href(self, card: Any) -> str:
        link = card.select_one("[data-field='detail_url'][href], a.search-product-link[href], a.link__item[href], a[href*='goodsCode='], a[href*='/vp/products/'], a[href*='/products/'], a[href*='/item/'], a[href]")
        return str(link.get("href") or "") if link else ""

    def _image_src(self, card: Any) -> str:
        image = card.select_one(_IMAGE_SELECTOR)
        if not image:
            return ""
        for attr in ("src", "data-src", "data-original", "data-img-src", "data-lazy"):
            value = image.get(attr)
            if value:
                return str(value)
        srcset = image.get("srcset")
        return str(srcset).split()[0] if srcset else ""

    def _json_has_candidate_fields(self, data: dict[str, Any]) -> bool:
        return _first_value(data, _NAME_KEYS) is not None and _first_value(data, _PRICE_KEYS) is not None

    def _source_record_key(
        self,
        *,
        data: dict[str, Any] | None = None,
        card: Any | None = None,
        detail_url: str = "",
    ) -> str:
        if data:
            value = _first_value(data, _RECORD_KEY_KEYS)
            if value not in (None, ""):
                return str(value).strip()
        if card is not None:
            for attr in ("data-product-id", "data-item-id", "data-goods-code", "data-id", "id"):
                value = card.get(attr)
                if value:
                    return str(value).strip()
        return self._record_key_from_url(detail_url)

    def _record_key_from_url(self, detail_url: str) -> str:
        if not detail_url:
            return ""
        parsed = urlparse(detail_url)
        query = parse_qs(parsed.query)
        for key in ("goodsCode", "goodsNo", "itemId", "itemNo", "productId", "vendorItemId"):
            if query.get(key):
                return query[key][0]
        patterns = [r"/vp/products/([^/?#]+)", r"/products/([^/?#]+)", r"/item/([^/?#]+)", r"/item/(\d+)\.html"]
        for pattern in patterns:
            match = re.search(pattern, parsed.path)
            if match:
                return match.group(1)
        return ""

    def _absolute_url(self, value: Any) -> str:
        if not value:
            return ""
        text = str(value).strip()
        if text.startswith("//"):
            return "https:" + text
        return text if text.startswith(("http://", "https://")) else urljoin(self.BASE_URL, text)

    def _replace_page(self, url: str, page: Any) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query[self.PAGE_PARAM] = [str(page)]
        return parsed._replace(query=urlencode(query, doseq=True)).geturl()
