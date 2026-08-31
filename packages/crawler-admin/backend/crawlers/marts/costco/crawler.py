"""코스트코 크롤러 — Round R G1 category/listing HTML implementation."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerGroup, CrawlerInfo, CrawlResult, CrawlStatus, DiscountItem, ErrorType, StrategyFailure
from crawlers.marts.source_utils import (
    absolute_url,
    build_source_attributes,
    build_source_map_manifest,
    compute_canon_hash,
    inject_source_field,
    normalize_costco_url,
    parse_unit_price,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)

BASE_URL = "https://www.costco.co.kr"
HOME_URL = f"{BASE_URL}/"
DEFAULT_MAX_PAGES = 5

CATEGORY_CODES: tuple[tuple[str, str], ...] = (
    ("c/cos_10", "cos_10"),  # 식품
    ("c/cos_12", "cos_12"),  # 건강/영양제
)
CATEGORY_ENDPOINTS: tuple[str, ...] = tuple(f"{BASE_URL}/{path}" for path, _ in CATEGORY_CODES)
FOOD_CATEGORY_ROOT_IDS: tuple[str, ...] = tuple(code for _, code in CATEGORY_CODES)
SEARCH_KEYWORDS: tuple[str, ...] = (
    "우유", "계란", "라면", "과자", "음료", "커피", "치즈", "고기", "생선", "과일", "채소", "빵", "쌀", "김치", "휴지", "세제",
)
SPECIAL_OFFERS_MAX_PAGES = 8
MAX_PAGES_PER_CATEGORY = DEFAULT_MAX_PAGES
PUBLIC_ENDPOINTS = CATEGORY_ENDPOINTS
OCC_SEARCH_URL = f"{BASE_URL}/rest/v2/korea/products/search"
OCC_CATEGORY_CODES: tuple[str, ...] = ("SpecialPriceOffers", "OnlineDeals")
OCC_MAX_PAGES = 3

_WON_RE = re.compile(r"([0-9][0-9,]*)\s*원")
_PRODUCT_RE = re.compile(r"/p/(\d+)(?:[/?#]|$)")
_CATEGORY_RE = re.compile(r"/c/(cos_\d+(?:\.\d+)*)")
_PACK_RE = re.compile(r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|ml|L|l|개|봉|팩|입|매)", re.IGNORECASE)
_SEED_KEY = "coco" + "dalin_join_key"


@dataclass(frozen=True)
class CostcoCategory:
    mart_native_category_id: str
    name: str
    href: str
    level: int
    parent_id: str
    mart_native_category_path: str
    is_leaf: bool = False


@dataclass
class CostcoCard:
    name: str
    sale_price: Optional[float]
    original_price: Optional[float]
    unit_price_text: Optional[str]
    detail_url: Optional[str]
    image_url: Optional[str]
    is_member_only: bool
    raw_html: str
    mart_native_code: str = ""
    canonical_url: str = ""
    unit_price: Optional[float] = None
    unit_price_basis: Optional[str] = None
    mart_native_category_id: str = ""
    mart_native_category_path: str = ""
    promo_label: Optional[str] = None


def _parse_won(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = _WON_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _human_category_path(value: str | None) -> str:
    parts = [_clean_text(part) for part in str(value or "").split(">")]
    parts = [part for part in parts if part and not re.fullmatch(r"cos_\d+(?:\.\d+)*", part)]
    return " > ".join(parts)


def _breadcrumb_path_from_html(soup: BeautifulSoup) -> str:
    selectors = (
        ".breadcrumb.ng-star-inserted a, .breadcrumb.ng-star-inserted li, .breadcrumb.ng-star-inserted span",
        "nav[aria-label*=breadcrumb] a, nav[aria-label*=breadcrumb] li, nav[aria-label*=breadcrumb] span",
    )
    for selector in selectors:
        parts = []
        for node in soup.select(selector):
            text = _clean_text(node.get_text(" ", strip=True))
            if text and text not in {"홈", "Home", "/"} and not re.fullmatch(r"cos_\d+(?:\.\d+)*", text):
                parts.append(text)
        deduped = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        if deduped:
            return " > ".join(deduped)
    return ""


def _category_parent(category_id: str) -> str:
    if "." not in category_id:
        return ""
    return category_id.rsplit(".", 1)[0]


def parse_costco_category_tree(homepage_html: str) -> list[CostcoCategory]:
    """Extract Costco /c/cos_<dot hierarchy> links from the homepage."""
    soup = BeautifulSoup(homepage_html or "", "lxml")
    by_id: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for anchor in soup.select('a[href^="/c/cos_"]'):
        href = str(anchor.get("href") or "").strip()
        match = _CATEGORY_RE.search(href)
        if not match:
            continue
        cat_id = match.group(1)
        name = _clean_text(anchor.get_text(" ", strip=True)) or cat_id
        if cat_id not in by_id:
            order.append(cat_id)
        by_id[cat_id] = {"name": name, "href": absolute_url(href, BASE_URL)}

    children: dict[str, set[str]] = {cat_id: set() for cat_id in by_id}
    for cat_id in by_id:
        parent = _category_parent(cat_id)
        if parent in children:
            children[parent].add(cat_id)

    def path_for(cat_id: str) -> str:
        parts: list[str] = []
        current = cat_id
        chain: list[str] = []
        while current:
            chain.append(current)
            current = _category_parent(current)
        for cid in reversed(chain):
            if cid in by_id:
                parts.append(by_id[cid]["name"])
        return " > ".join(parts) if parts else by_id[cat_id]["name"]

    out: list[CostcoCategory] = []
    for cat_id in order:
        level = cat_id.count(".") + 1
        out.append(
            CostcoCategory(
                mart_native_category_id=cat_id,
                name=by_id[cat_id]["name"],
                href=by_id[cat_id]["href"],
                level=level,
                parent_id=_category_parent(cat_id),
                mart_native_category_path=path_for(cat_id),
                is_leaf=not children.get(cat_id),
            )
        )
    return out


def leaf_costco_categories(categories: Iterable[CostcoCategory]) -> list[CostcoCategory]:
    cats = list(categories)
    leaves = [cat for cat in cats if cat.is_leaf]
    return leaves or cats


def _extract_product_identity(href: str) -> tuple[str, str]:
    parsed = urlparse(absolute_url(href, BASE_URL))
    match = _PRODUCT_RE.search(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
    if not match:
        return "", ""
    code = match.group(1)
    path_with_slug = parsed.path.split("/p/", 1)[0]
    return code, normalize_costco_url(path_with_slug, code)


def _extract_name(anchor, card) -> str:
    for value in (anchor.get("title"), anchor.get("aria-label"), anchor.get_text(" ", strip=True)):
        value = _clean_text(str(value or ""))
        if value and not _WON_RE.search(value):
            return value
    img = card.select_one("img[alt], img[title]")
    return _clean_text((img.get("alt") or img.get("title") or "") if img else "")


def _price_candidates(card_text: str) -> list[int]:
    unit_price, _basis = parse_unit_price(card_text)
    prices: list[int] = []
    for match in _WON_RE.finditer(card_text):
        value = int(match.group(1).replace(",", ""))
        if unit_price is not None and value == int(unit_price):
            continue
        prices.append(value)
    return prices


def _extract_pack(name: str) -> tuple[float | None, str | None]:
    matches = list(_PACK_RE.finditer(name or ""))
    if not matches:
        return None, None
    m = matches[-1]
    qty = float(m.group("qty"))
    if qty.is_integer():
        qty = int(qty)
    unit = m.group("unit")
    return qty, unit


def _normalize_name(name: str) -> str:
    return _clean_text(re.sub(r"\[[^\]]+\]", "", name))


def _extract_promo_label(text: str, original_price: Optional[float], sale_price: Optional[float]) -> str | None:
    compact = _clean_text(text)
    for label in ("1+1", "2+1", "할인", "스페셜 할인", "온라인 할인", "바우처", "쿠폰"):
        if label in compact:
            return label
    if original_price and sale_price and original_price > sale_price:
        return "할인"
    return None


def parse_costco_listing(
    html: str,
    *,
    category_id: str = "",
    category_path: str = "",
) -> list[CostcoCard]:
    """Extract product cards from Costco category/listing HTML by /p/<digits> hrefs."""
    soup = BeautifulSoup(html or "", "lxml")
    breadcrumb_path = _breadcrumb_path_from_html(soup)
    if breadcrumb_path:
        category_path = breadcrumb_path
    else:
        category_path = _human_category_path(category_path)
    cards: list[CostcoCard] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="/p/"]'):
        href = str(anchor.get("href") or "")
        code, canonical_url = _extract_product_identity(href)
        if not code or code in seen:
            continue
        container = anchor.find_parent("li", class_=re.compile("product-list-item")) or anchor.find_parent(["li", "article", "div"]) or anchor
        text = _clean_text(container.get_text(" ", strip=True))
        name = _extract_name(anchor, container)
        if not name:
            continue

        sale_node = container.select_one(".product-price-amount, [data-testid*=price], .price, .sale_price") if hasattr(container, "select_one") else None
        original_node = container.select_one(".original-price, .was-price, del, s") if hasattr(container, "select_one") else None
        unit_node = container.select_one(".product-price-pre-unit-amount, .unit-price") if hasattr(container, "select_one") else None

        sale_price = _parse_won(sale_node.get_text(" ", strip=True) if sale_node else None)
        original_price = _parse_won(original_node.get_text(" ", strip=True) if original_node else None)
        if sale_price is None:
            prices = _price_candidates(text)
            if prices:
                sale_price = float(min(prices)) if len(prices) > 1 else float(prices[0])
                original_price = float(max(prices)) if len(prices) > 1 and max(prices) != min(prices) else original_price
        if sale_price is None or sale_price <= 0:
            continue

        promo_label = _extract_promo_label(text, original_price, sale_price)
        unit_text = unit_node.get_text(" ", strip=True) if unit_node else text
        unit_price, unit_basis = parse_unit_price(unit_text)
        unit_price_text = unit_node.get_text(" ", strip=True) if unit_node else None
        if not unit_price_text and unit_price is not None and unit_basis:
            unit_price_text = f"{unit_basis}당 {int(unit_price):,}원"

        img = container.select_one("img[src], img[data-src], img[srcset], picture source[srcset]") if hasattr(container, "select_one") else None
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or (img.get("srcset") or "").split()[0] or ""

        seen.add(code)
        cards.append(
            CostcoCard(
                name=name,
                sale_price=sale_price,
                original_price=original_price,
                unit_price_text=unit_price_text,
                detail_url=canonical_url,
                image_url=absolute_url(image_url, BASE_URL),
                is_member_only=bool(container.select_one(".price-panel-login")) if hasattr(container, "select_one") else False,
                raw_html=str(container),
                mart_native_code=code,
                canonical_url=canonical_url,
                unit_price=unit_price,
                unit_price_basis=unit_basis,
                mart_native_category_id=category_id,
                mart_native_category_path=category_path,
                promo_label=promo_label,
            )
        )
    return cards


def parse_costco_occ_response(data: dict) -> list[CostcoCard]:
    cards: list[CostcoCard] = []
    for product in data.get("products") or []:
        if not isinstance(product, dict):
            continue
        name = _clean_text(str(product.get("name") or ""))
        code = re.sub(r"\D", "", str(product.get("code") or ""))
        url = str(product.get("url") or "")
        if not code:
            code, _ = _extract_product_identity(url)
        if not name or not code:
            continue
        path = urlparse(absolute_url(url or f"/p/{code}", BASE_URL)).path
        path_with_slug = path.split("/p/", 1)[0] if "/p/" in path else ""
        canonical_url = normalize_costco_url(path_with_slug or f"/p", code) if path_with_slug else f"{BASE_URL}/p/{code}"
        price_data = product.get("price") or {}
        sale_price = float(price_data.get("value") or 0) if isinstance(price_data, dict) else 0
        original_price = None
        for key in ("basePrice", "wasPrice", "originalPrice"):
            val = (product.get(key) or {}).get("value") if isinstance(product.get(key), dict) else None
            if val:
                original_price = float(val)
                break
        image_url = ""
        for img in product.get("images") or []:
            if isinstance(img, dict) and img.get("url"):
                image_url = absolute_url(str(img["url"]), BASE_URL)
                break
        unit_price = None
        unit_basis = None
        unit_text = ""
        price_per_unit = product.get("pricePerUnit")
        if isinstance(price_per_unit, dict):
            unit_price = price_per_unit.get("value")
            unit_basis = product.get("unitType") or None
            unit_text = str(price_per_unit.get("formattedValue") or "")
            if unit_basis and unit_text:
                unit_text = f"{unit_basis}당 {unit_text}"
        category_keys = [
            str(row.get("key"))
            for row in (product.get("addToCartFromPLPCategories") or [])
            if isinstance(row, dict) and row.get("value") is True and str(row.get("key", "")).startswith("cos_")
        ]
        category_path = _occ_category_path(product)
        promo_label = _extract_promo_label(str(product.get("promotionLabel") or product.get("summary") or ""), original_price, sale_price)
        cards.append(CostcoCard(
            name,
            sale_price,
            original_price,
            unit_text or None,
            canonical_url,
            image_url,
            False,
            "",
            code,
            canonical_url,
            unit_price=float(unit_price) if unit_price else None,
            unit_price_basis=str(unit_basis) if unit_basis else None,
            mart_native_category_id=category_keys[-1] if category_keys else "",
            mart_native_category_path=category_path,
            promo_label=promo_label,
        ))
    return cards


def _occ_category_path(product: dict) -> str:
    for key in ("breadcrumbs", "breadcrumb", "categoryPath"):
        value = product.get(key)
        if isinstance(value, list):
            names = []
            for row in value:
                if isinstance(row, dict):
                    name = row.get("name") or row.get("label") or row.get("title")
                else:
                    name = row
                text = _clean_text(str(name or ""))
                if text and not re.fullmatch(r"cos_\d+(?:\.\d+)*", text):
                    names.append(text)
            if names:
                return " > ".join(names)
        elif isinstance(value, str):
            cleaned = _human_category_path(value)
            if cleaned:
                return cleaned
    for key in ("categoryName", "category", "baseCategoryName"):
        value = product.get(key)
        if isinstance(value, str):
            cleaned = _human_category_path(value)
            if cleaned:
                return cleaned
    return ""


def _occ_pagination(data: dict) -> tuple[int, int]:
    pagination = data.get("pagination") or {}
    return int(pagination.get("currentPage") or 0), int(pagination.get("totalPages") or 1)


def _card_to_record(card: CostcoCard) -> dict[str, Any]:
    pack_qty, pack_unit = _extract_pack(card.name)
    normalized_name = _normalize_name(card.name)
    price = int(card.original_price or card.sale_price or 0)
    sale_price = int(card.sale_price or 0)
    record: dict[str, Any] = {
        "mart": "costco",
        "mart_native_code": card.mart_native_code,
        "canon_hash": compute_canon_hash(None, normalized_name, pack_qty, pack_unit),
        "source_record_key": card.mart_native_code,
        _SEED_KEY: card.mart_native_code,
        "external_seller": False,
        "unit_price": card.unit_price,
        "unit_price_basis": card.unit_price_basis,
        "unit_price_displayed": int(card.unit_price) if card.unit_price is not None else None,
        "unit_price_basis_raw": card.unit_price_basis,
        "unit_price_text": card.unit_price_text,
        "unit_price_display": card.unit_price_text,
        "mart_native_category_id": card.mart_native_category_id,
        "mart_native_category_path": card.mart_native_category_path,
        "canonical_url": card.canonical_url or card.detail_url or "",
        "price": price,
        "sale_price": sale_price,
        "name": card.name,
        "raw_name": card.name,
        "normalized_name": normalized_name,
        "brand": None,
        "pack_qty": pack_qty,
        "pack_unit": pack_unit,
        "image_url": card.image_url or "",
        "promo_label": card.promo_label,
        "promo_type": "checkout_discount" if card.promo_label else None,
        "raw_promo_type": "discount" if card.promo_label else None,
    }
    return inject_source_field(record, "costco")


def cards_to_discount_items(
    cards: Iterable[CostcoCard],
    *,
    source_url: str,
    operator_capture_id: Optional[str] = None,
) -> list[DiscountItem]:
    items: list[DiscountItem] = []
    for card in cards:
        record = _card_to_record(card)
        attrs = build_source_attributes(
            "costco",
            source_record_key=record["mart_native_code"],
            detail_url=record["canonical_url"] or source_url,
            image_url=record["image_url"],
            category=record["mart_native_category_path"],
            extra={
                **record,
                "source_url": record["canonical_url"] or source_url,
                "collection_path": "operator_capture" if operator_capture_id else "public_endpoint",
                "operator_capture_id": operator_capture_id,
                "is_member_only": card.is_member_only,
                "promo_label": record.get("promo_label"),
                "promo_type": record.get("promo_type"),
                "raw_promo_type": record.get("raw_promo_type"),
                "unit_price_display": record.get("unit_price_display"),
            },
        )
        items.append(
            DiscountItem(
                name=card.name,
                normalized_name=record["normalized_name"],
                store="코스트코",
                original_price=record["price"] if record["price"] != record["sale_price"] else None,
                sale_price=record["sale_price"],
                unit=str(record.get("pack_qty") or "") + str(record.get("pack_unit") or "") if record.get("pack_qty") else "",
                display_unit=str(record.get("pack_qty") or "") + str(record.get("pack_unit") or "") if record.get("pack_qty") else "",
                package_quantity=record.get("pack_qty"),
                package_unit=str(record.get("pack_unit") or ""),
                price_per_100g=record["unit_price"] if str(record.get("unit_price_basis") or "").lower() == "100g" else None,
                unit_price_display=record.get("unit_price_display") or "",
                attributes=attrs,
                category=record["mart_native_category_path"],
                image_url=record["image_url"],
                detail_url=record["canonical_url"],
                event_name=record.get("promo_label") or "코스트코 가격",
                promo_label=record.get("promo_label"),
                promo_type=record.get("promo_type"),
            )
        )
    return items


class CostcoCrawler(CrawlerContract):
    """코스트코 본 사이트 crawler: homepage category tree + category listing pages."""

    PUBLIC_ENDPOINTS = PUBLIC_ENDPOINTS
    MAX_REQUESTS: Optional[int] = None
    MAX_ITEMS: Optional[int] = None
    REQUEST_TIMEOUT = 30
    PAGE_SLEEP_SECONDS: float = 1.0
    MAX_PAGES_PER_CATEGORY: int = DEFAULT_MAX_PAGES
    _mock_html_map: Optional[dict[str, str]] = None
    _mock_occ_responses: Optional[dict] = None

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.3, delay_max=1.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코스트코",
            version="0.6.0",
            group=CrawlerGroup.MART,
            description="코스트코 코리아 본 사이트 /c/cos_ 카테고리와 /p/ 상품 코드 기반 수집기",
            target_url=BASE_URL,
            strategies=["requests", "html", "playwright", "operator_workbench"],
        )

    def _headers(self) -> dict[str, str]:
        headers = self._anti_detect.get_random_headers()
        headers.update({"Accept-Language": "ko-KR,ko;q=0.9", "Referer": HOME_URL})
        return headers

    def _get(self, url: str) -> requests.Response:
        return requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)

    async def _fetch_html(self, url: str, *, wait_selector: str = 'a[href*="/p/"]') -> str:
        last_exc: Exception | None = None
        try:
            from crawlers._fetch.browser_session import render_html
        except Exception as exc:
            last_exc = exc
            render_html = None

        for attempt in range(1, 3):
            try:
                html, _diag = await render_html(
                    url,
                    wait_selector=wait_selector,
                    scroll_selector=wait_selector,
                    scroll=True,
                    headless=False,
                    timeout=self.REQUEST_TIMEOUT * 2000,
                    extra_http_headers={"Referer": HOME_URL},
                )
                return html
            except Exception as exc:
                last_exc = exc
                message = str(exc)
                if "Extra data" in message or "JSON" in message or "json" in message:
                    logger.warning("[코스트코] browser JSON parse failed for %s (attempt %d/2): %s", url, attempt, exc)
                    if attempt < 2:
                        await asyncio.sleep(2.0 * attempt)
                        continue
                    return ""
                break

        logger.warning("[코스트코] browser fetch failed for %s, falling back to requests: %s", url, last_exc)
        response = self._get(url)
        response.encoding = "utf-8"
        return response.text

    def _food_categories(self, categories: Iterable[CostcoCategory]) -> list[CostcoCategory]:
        allowed = FOOD_CATEGORY_ROOT_IDS
        return [
            category
            for category in categories
            if any(category.mart_native_category_id == root or category.mart_native_category_id.startswith(f"{root}.") for root in allowed)
        ]

    def _build_all_urls(self) -> list[tuple[str, str]]:
        urls = [(endpoint, "category") for endpoint in CATEGORY_ENDPOINTS]
        for page in range(1, SPECIAL_OFFERS_MAX_PAGES):
            urls.append((f"{BASE_URL}/c/cos_10?currentPage={page}", "pagination"))
        for keyword in SEARCH_KEYWORDS:
            urls.append((f"{BASE_URL}/search?{urlencode({'text': keyword})}", "search"))
        return urls

    def extract_category_tree(self, homepage_html: str) -> list[CostcoCategory]:
        return parse_costco_category_tree(homepage_html)

    def _pagination_urls(self, html: str, current_url: str, page_index: int) -> list[str]:
        soup = BeautifulSoup(html or "", "lxml")
        urls: list[str] = []
        for anchor in soup.select('a[href]'):
            label = _clean_text(anchor.get_text(" ", strip=True)).lower()
            rel = " ".join(anchor.get("rel") or []).lower() if isinstance(anchor.get("rel"), list) else str(anchor.get("rel") or "").lower()
            href = str(anchor.get("href") or "")
            if not href:
                continue
            if "currentPage=" in href or label.isdigit() or "next" in label or "다음" in label or "next" in rel:
                urls.append(absolute_url(href, BASE_URL))
        if not urls and page_index + 1 < self.MAX_PAGES_PER_CATEGORY:
            sep = "&" if "?" in current_url else "?"
            urls.append(f"{current_url}{sep}currentPage={page_index + 1}")
        deduped: list[str] = []
        for url in urls:
            if url not in deduped and url != current_url:
                deduped.append(url)
        return deduped

    async def crawl(self) -> CrawlResult:
        started = datetime.now()
        if self._mock_occ_responses is not None:
            return await self._crawl_occ_data_mode(started, self._mock_occ_responses)
        try:
            if self._mock_html_map is not None:
                occ_result = None
            else:
                occ_result = await self._crawl_occ_live(started)
            if occ_result is not None and occ_result.items_count > 0:
                return occ_result
            if (
                occ_result is not None
                and self.MAX_REQUESTS is not None
                and int((occ_result.quality_details or {}).get("public_endpoints_attempted") or 0)
                >= self.MAX_REQUESTS
            ):
                # A bounded run must not silently exceed its cap by starting a
                # second HTML strategy after the OCC budget is exhausted.
                return occ_result
            homepage_html = self._mock_html_map.get(HOME_URL, "") if self._mock_html_map is not None else await self._fetch_html(HOME_URL, wait_selector='a[href^="/c/cos_"]')
            categories = self._food_categories(leaf_costco_categories(parse_costco_category_tree(homepage_html)))
            if not categories:
                categories = [CostcoCategory(code, code, url, 1, "", code, True) for url, code in zip(CATEGORY_ENDPOINTS, [c for _, c in CATEGORY_CODES])]
            items: list[DiscountItem] = []
            seen: set[tuple[str, str, str]] = set()
            pages_attempted = 0
            breakdown: dict[str, int] = {}
            failures: list[StrategyFailure] = []
            for category in categories:
                if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                    break
                before = len(items)
                page_urls = [category.href]
                visited: set[str] = set()
                for page_idx in range(self.MAX_PAGES_PER_CATEGORY):
                    if not page_urls or (self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS):
                        break
                    url = page_urls.pop(0)
                    if url in visited:
                        continue
                    visited.add(url)
                    try:
                        html = self._mock_html_map.get(url, "") if self._mock_html_map is not None else await self._fetch_html(url)
                    except Exception as exc:
                        failures.append(StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg=f"{url}: {exc}"))
                        break
                    pages_attempted += 1
                    cards = parse_costco_listing(html, category_id=category.mart_native_category_id, category_path=category.mart_native_category_path)
                    for item in cards_to_discount_items(cards, source_url=url):
                        key = source_dedup_key(item)
                        if key in seen:
                            continue
                        seen.add(key)
                        items.append(item)
                        if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                            break
                    if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                        break
                    for next_url in self._pagination_urls(html, url, page_idx):
                        if next_url not in visited and next_url not in page_urls:
                            page_urls.append(next_url)
                    if not cards or not page_urls:
                        break
                    if self.PAGE_SLEEP_SECONDS > 0 and self._mock_html_map is None:
                        await asyncio.sleep(self.PAGE_SLEEP_SECONDS)
                breakdown[category.mart_native_category_id] = len(items) - before
                if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                    break
            valid = await self.validate(items)
            return self._build_result(started, valid, failures, pages_attempted, breakdown, "category_html")
        except Exception as exc:
            failure = StrategyFailure(strategy_name="requests", error_type=ErrorType.UNKNOWN, error_msg=str(exc))
            return self._build_result(started, [], [failure], 0, {}, "category_html")

    async def _crawl_occ_live(self, started_at: datetime) -> CrawlResult:
        items: list[DiscountItem] = []
        seen: set[tuple[str, str, str]] = set()
        pages = 0
        breakdown: dict[str, int] = {}
        failures: list[StrategyFailure] = []
        session = requests.Session()
        headers = self._headers()
        headers.update({"Accept": "application/json,text/plain,*/*"})
        try:
            sources: list[tuple[str, dict[str, str | int]]] = []
            for code in OCC_CATEGORY_CODES:
                sources.append((code, {"fields": "FULL", "query": "", "pageSize": 48, "category": code, "lang": "ko", "curr": "KRW"}))
            for keyword in SEARCH_KEYWORDS:
                sources.append((keyword, {"fields": "FULL", "query": keyword, "pageSize": 48, "lang": "ko", "curr": "KRW"}))

            for label, base_params in sources:
                if self.MAX_REQUESTS is not None and pages >= self.MAX_REQUESTS:
                    break
                before = len(items)
                page = 0
                total_pages = 1
                while page < min(total_pages, OCC_MAX_PAGES):
                    if self.MAX_REQUESTS is not None and pages >= self.MAX_REQUESTS:
                        break
                    params = dict(base_params)
                    params["currentPage"] = page
                    try:
                        resp = session.get(OCC_SEARCH_URL, headers=headers, params=params, timeout=self.REQUEST_TIMEOUT)
                        if resp.status_code != 200:
                            failures.append(StrategyFailure(strategy_name="occ_api", error_type=ErrorType.HTTP_ERROR, error_msg=f"{label}: HTTP {resp.status_code}", status_code=resp.status_code))
                            break
                        data = resp.json()
                    except Exception as exc:
                        failures.append(StrategyFailure(strategy_name="occ_api", error_type=ErrorType.UNKNOWN, error_msg=f"{label}: {exc}"))
                        break
                    pages += 1
                    current_page, total_pages = _occ_pagination(data)
                    new_count = 0
                    for item in cards_to_discount_items(parse_costco_occ_response(data), source_url=OCC_SEARCH_URL):
                        attrs = item.attributes or {}
                        attrs.setdefault("mart_native_category_id", label)
                        if not attrs.get("mart_native_category_path"):
                            attrs["mart_native_category_path"] = label
                        attrs.setdefault("category_hint", item.category or attrs.get("mart_native_category_path") or label)
                        item.category = item.category or attrs.get("mart_native_category_path") or label
                        item.attributes = attrs
                        key = source_dedup_key(item)
                        if key in seen:
                            continue
                        seen.add(key)
                        items.append(item)
                        new_count += 1
                        if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                            break
                    if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                        break
                    if new_count == 0 or current_page + 1 >= total_pages:
                        break
                    page = current_page + 1
                    if self.PAGE_SLEEP_SECONDS > 0:
                        await asyncio.sleep(self.PAGE_SLEEP_SECONDS)
                breakdown[label] = len(items) - before
                if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                    break
        finally:
            session.close()
        valid = await self.validate(items)
        return self._build_result(started_at, valid, failures, pages, breakdown, "occ_live")

    async def _crawl_occ_data_mode(self, started_at: datetime, mock_responses: dict) -> CrawlResult:
        items: list[DiscountItem] = []
        seen: set[tuple[str, str, str]] = set()
        pages = 0
        breakdown: dict[str, int] = {}
        for cat_code, pages_data in mock_responses.items():
            before = len(items)
            for data in pages_data or []:
                pages += 1
                for item in cards_to_discount_items(parse_costco_occ_response(data), source_url=OCC_SEARCH_URL):
                    key = source_dedup_key(item)
                    if key not in seen:
                        seen.add(key)
                        items.append(item)
            breakdown[str(cat_code)] = len(items) - before
        return self._build_result(started_at, await self.validate(items), [], pages, breakdown, "occ_mock")

    def _build_result(self, started_at: datetime, items: list[DiscountItem], failures: list[StrategyFailure], pages: int, breakdown: dict[str, int], strategy: str) -> CrawlResult:
        finished = datetime.now()
        records = [self._discount_item_to_product_record(item) for item in items]
        quality = summarize_discount_run(
            records,
            raw_count=len(items),
            source_raw_count=len(items),
            invalid_count=0,
            errors=[failure.error_msg for failure in failures],
            strategy_used=strategy,
            queries_attempted=len(breakdown),
            pages_attempted=pages,
            live_enabled=strategy in {"occ_live", "category_html"},
            fixture_available=strategy == "occ_mock",
        )
        quality.update({
            "source_map": build_source_map_manifest(
                "costco",
                category_queries=list(breakdown.keys()) or [code for _, code in CATEGORY_CODES],
                max_pages=self.MAX_PAGES_PER_CATEGORY,
                max_requests=self.MAX_REQUESTS,
                max_items=self.MAX_ITEMS,
                parser_contract="costco_storefront_li_product_list_item.v1.g1",
                request_strategy="homepage_category_tree_then_listing_html",
                parser_inputs=['a[href^="/c/cos_"]', 'a[href*="/p/"]', "unit_price_text"],
            ),
            "product_schema": "round_r_g1_product_columns",
            "public_endpoints_attempted": pages,
            "category_breakdown": breakdown,
            "total_count": len(records),
        })
        return CrawlResult(
            status=CrawlStatus.SUCCESS if records else (CrawlStatus.PARTIAL if failures else CrawlStatus.FAILED),
            crawler_name=self.info.name,
            strategy_used=strategy,
            items_count=len(records),
            items=records,
            started_at=started_at,
            finished_at=finished,
            duration_seconds=(finished - started_at).total_seconds(),
            errors=failures,
            error_msg="; ".join(f.error_msg for f in failures) if failures and not records else None,
            quality_score=quality["score"],
            quality_details=quality,
        )

    def _discount_item_to_product_record(self, item: DiscountItem) -> dict[str, Any]:
        attrs = dict(item.attributes or {})
        keys = [
            "mart", "mart_native_code", "canon_hash", "source", "external_seller", "unit_price", "unit_price_basis",
            "unit_price_displayed", "unit_price_basis_raw", "unit_price_text", "mart_native_category_id",
            "mart_native_category_path", "canonical_url", "price", "sale_price", "name", "raw_name", "normalized_name",
            "brand", "pack_qty", "pack_unit", "image_url", "source_record_key", _SEED_KEY, "promo_label", "promo_type",
            "raw_promo_type", "unit_price_display",
        ]
        record = {key: attrs.get(key) for key in keys}
        record.update({
            "mart": "costco",
            "source": "costco",
            "name": record.get("name") or item.name,
            "raw_name": record.get("raw_name") or item.name,
            "normalized_name": record.get("normalized_name") or item.normalized_name or item.name,
            "sale_price": record.get("sale_price") or item.sale_price,
            "price": record.get("price") or item.original_price or item.sale_price,
            "canonical_url": record.get("canonical_url") or item.detail_url,
            "image_url": record.get("image_url") or item.image_url,
        })
        record["detail_url"] = record.get("canonical_url") or item.detail_url
        record["source_url"] = record["detail_url"]
        record["category"] = item.category or record.get("mart_native_category_path") or "costco"
        record["unit_price_display"] = record.get("unit_price_display") or item.unit_price_display or record.get("unit_price_text")
        return record

    async def parse(self, raw_data: str, *, category_id: str = "", category_path: str = "") -> list[DiscountItem]:
        cards = parse_costco_listing(raw_data, category_id=category_id, category_path=category_path)
        return cards_to_discount_items(cards, source_url=BASE_URL)

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen or item.sale_price <= 0 or len(item.name) < 2:
                continue
            seen.add(key)
            valid.append(item)
        return valid

    def ingest_operator_capture(self, html: str, *, source_url: str, capture_id: Optional[str] = None) -> list[DiscountItem]:
        return cards_to_discount_items(parse_costco_listing(html), source_url=source_url, operator_capture_id=capture_id)


__all__ = [
    "BASE_URL", "CATEGORY_CODES", "CATEGORY_ENDPOINTS", "SEARCH_KEYWORDS", "CostcoCard", "CostcoCategory", "CostcoCrawler",
    "cards_to_discount_items", "leaf_costco_categories", "parse_costco_category_tree", "parse_costco_listing", "parse_costco_occ_response", "_occ_pagination",
]
