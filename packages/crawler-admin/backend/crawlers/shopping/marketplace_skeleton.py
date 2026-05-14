"""Safe marketplace crawler skeleton utilities.

These crawlers intentionally avoid live marketplace scraping. They register source
coverage and provide deterministic parser contracts for saved/mock fixtures.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import urljoin

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
    "price",
    "lowestPrice",
)
_ORIGINAL_PRICE_KEYS = (
    "originalPrice",
    "original_price",
    "normalPrice",
    "normal_price",
    "listPrice",
    "list_price",
)
_NAME_KEYS = ("name", "title", "productName", "product_name", "itemName", "goodsName")
_URL_KEYS = ("url", "detailUrl", "detail_url", "productUrl", "product_url", "link")
_IMAGE_KEYS = ("image", "imageUrl", "image_url", "thumbnail", "thumbnailUrl")
_CATEGORY_KEYS = ("category", "categoryName", "category_name", "brand", "brandName")
_CARD_SELECTOR = "[data-testid='product-card'], [data-product-card], .product-card, .goods-card, .item, li"
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
    "If fixture diagnostics pass, prepare a no-DB AI review artifact; do not mutate production data from skeleton output.",
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
    match = re.search(r"[\d,]+", str(value).replace("원", ""))
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


class MarketplaceSkeletonCrawler(CrawlerContract):
    """Base contract for marketplace source skeletons backed by mock fixtures."""

    SOURCE_ID: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    BASE_URL: ClassVar[str]
    DESCRIPTION: ClassVar[str]

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name=self.DISPLAY_NAME,
            version="0.1.0",
            group=CrawlerGroup.SHOPPING,
            description=(
                f"{self.DESCRIPTION} — skeleton/fixture-only; live_ready requires the fixture contract, "
                "bounded diagnostics evidence, run limits, and operator approval"
            ),
            target_url=self.BASE_URL,
            strategies=["mock-html", "mock-json"],
        )

    async def crawl(self, raw_data: str | None = None, fixture: str | None = None, **_: Any) -> CrawlResult:
        started_at = datetime.now()
        source = fixture if fixture is not None else raw_data
        source_errors: list[str] = []
        if not source:
            source_errors.append(
                f"{self.SOURCE_ID} skeleton has no configured safe fixture/input; live crawling is intentionally disabled."
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
                strategy_used="mock-fixture",
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                errors=[StrategyFailure(strategy_name="mock-fixture", error_type=ErrorType.PARSE_ERROR, error_msg=str(exc))],
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
    ) -> CrawlResult:
        items_as_dict = [item.model_dump(mode="json") for item in items]
        quality_details = summarize_discount_run(
            items_as_dict,
            raw_count=raw_count,
            source_raw_count=source_raw_count,
            invalid_count=invalid_count,
            errors=errors,
            strategy_used="mock-fixture",
            live_enabled=False,
            fixture_available=fixture_available,
        )
        quality_details["readiness_gate"] = {
            "status": "skeleton_fixture_only",
            "live_ready": False,
            "collecting_claim_allowed": False,
            "safe_db_mutation_allowed": False,
            "parser_contract": MARKETPLACE_PARSER_CONTRACT,
            "fixture_contract": MARKETPLACE_FIXTURE_CONTRACT,
            "fixture_contract_status": "passed",
            "bounded_diagnostics": {
                "status": "required_before_live_ready",
                "evidence_id": None,
                "captured_at": None,
                "run_limits": {
                    "max_requests": None,
                    "max_pages": None,
                    "timeout_seconds": None,
                },
            },
            "operator_approval": {"status": "required_before_live_ready"},
            "required_evidence_before_live_ready": MARKETPLACE_REQUIRED_EVIDENCE_BEFORE_LIVE,
            "next_actions": MARKETPLACE_OPERATOR_NEXT_ACTIONS,
            "downstream_flow": {
                "current_stage": "fixture_diagnostics_only",
                "next_stage": "no_db_ai_review",
                "db_mutation_allowed": False,
            },
            "message": (
                "This marketplace crawler is safe mocked fixture coverage only; it performs no live network collection."
            ),
        }
        status = CrawlStatus.SUCCESS if items else CrawlStatus.PARTIAL
        failures: list[StrategyFailure] = []
        if not items:
            diagnostic = quality_details.get("zero_result_diagnostic") or {}
            message = diagnostic.get("message") or "; ".join(errors or []) or "No marketplace fixture rows parsed."
            stage = diagnostic.get("stage")
            error_type = ErrorType.EMPTY_RESPONSE if stage == "source_zero_raw_rows" else ErrorType.PARSE_ERROR
            failures.append(StrategyFailure(strategy_name="mock-fixture", error_type=error_type, error_msg=message))
            if not errors:
                errors = [message]
        finished_at = datetime.now()
        return CrawlResult(
            status=status,
            crawler_name=self.info.name,
            strategy_used="mock-fixture",
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

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        text = (raw_data or "").strip()
        if not text:
            return []
        if text[0] in "[{":
            return self._parse_json(text)
        return self._parse_html(text)

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen: set[tuple[str, int, str]] = set()
        for item in items:
            if not item.name.strip() or item.sale_price <= 0:
                continue
            key = (item.name.strip().lower(), item.sale_price, item.detail_url)
            if key in seen:
                continue
            seen.add(key)
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
        return [item for data in _iter_dicts(payload) if (item := self._item_from_json_dict(data))]

    def _item_from_json_dict(self, data: dict[str, Any]) -> DiscountItem | None:
        name = _first_value(data, _NAME_KEYS)
        sale_price = _parse_int(_first_value(data, _PRICE_KEYS))
        if not name or not sale_price:
            return None
        original_price = _parse_int(_first_value(data, _ORIGINAL_PRICE_KEYS))
        discount_percent = _parse_float(data.get("discountPercent") or data.get("discount_percent") or data.get("discountRate"))
        detail_url = self._absolute_url(_first_value(data, _URL_KEYS))
        image_url = self._absolute_url(_first_value(data, _IMAGE_KEYS))
        return DiscountItem(
            name=str(name).strip(),
            store=self.DISPLAY_NAME,
            sale_price=sale_price,
            original_price=original_price,
            discount_percent=discount_percent,
            category=str(_first_value(data, _CATEGORY_KEYS) or ""),
            image_url=image_url,
            detail_url=detail_url,
            attributes={
                "source": self.SOURCE_ID,
                "parser_contract": MARKETPLACE_PARSER_CONTRACT,
                "fixture_contract": MARKETPLACE_FIXTURE_CONTRACT,
            },
        )

    def _parse_html(self, raw_data: str) -> list[DiscountItem]:
        soup = BeautifulSoup(raw_data, "html.parser")
        return [item for card in self._html_cards(soup) if (item := self._item_from_html_card(card))]

    def _html_cards(self, soup: BeautifulSoup) -> list[Any]:
        cards = soup.select(_CARD_SELECTOR)
        return cards if cards else soup.select("body")

    def _item_from_html_card(self, card: Any) -> DiscountItem | None:
        name = self._select_text(card, "[data-field='name'], .name, .title, .product-name, [itemprop='name']")
        sale_price = _parse_int(self._select_text(card, "[data-field='sale_price'], [data-field='price'], .sale-price, .price, [itemprop='price']"))
        if not name or not sale_price:
            return None
        original_price = _parse_int(self._select_text(card, "[data-field='original_price'], .original-price, .normal-price, .list-price"))
        discount_percent = _parse_float(self._select_text(card, "[data-field='discount_percent'], .discount, .discount-percent"))
        category = self._select_text(card, "[data-field='category'], .category, .brand, .brand-name")
        link = card.select_one("[data-field='detail_url'], a[href]")
        image = card.select_one("img[src], img[data-src]")
        return DiscountItem(
            name=name,
            store=self.DISPLAY_NAME,
            sale_price=sale_price,
            original_price=original_price,
            discount_percent=discount_percent,
            category=category,
            image_url=self._absolute_url(image.get("src") or image.get("data-src") if image else ""),
            detail_url=self._absolute_url(link.get("href") if link else ""),
            attributes={
                "source": self.SOURCE_ID,
                "parser_contract": MARKETPLACE_PARSER_CONTRACT,
                "fixture_contract": MARKETPLACE_FIXTURE_CONTRACT,
            },
        )

    def _select_text(self, card: Any, selector: str) -> str:
        node = card.select_one(selector)
        return node.get_text(" ", strip=True) if node else ""

    def _json_has_candidate_fields(self, data: dict[str, Any]) -> bool:
        return _first_value(data, _NAME_KEYS) is not None and _first_value(data, _PRICE_KEYS) is not None

    def _absolute_url(self, value: Any) -> str:
        if not value:
            return ""
        text = str(value).strip()
        return text if text.startswith(("http://", "https://")) else urljoin(self.BASE_URL, text)
