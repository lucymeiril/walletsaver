"""코스트코 크롤러 — 본 사이트(costco.co.kr) 전용. v0.6.0

## 수집 전략 (300+ 목표)

SAP Commerce Cloud OCC REST API 직접 호출 (requests 기반).

기본 전략 — OCC REST API 직접 호출:
  - /rest/v2/korea/products/search (baseSite=korea, lang=ko, curr=KRW)
  - 확인된 카테고리: SpecialPriceOffers(732건), OnlineDeals(995건)
  - 페이지당 최대 100건, pagination.totalPages 기반 자동 순회
  - Akamai 쿠키(_abck, bm_sz) 유지: 홈페이지 선행 요청

OCC REST API 탐색 경위:
  - Playwright 헤드리스: Akamai Bot Manager 탐지 → 0건 (차단됨)
  - /occ/v2/{baseSite}/: 404 Not Found
  - /rest/v2/central/: 400 (언어/통화 미지원, baseSite=central은 en/EUR만 지원)
  - cx-state JSON에서 baseSite=korea 발견 (lang=ko, curr=KRW 지원)
  - /rest/v2/korea/products/search → 200 OK, 8151건 반환 확인

페이지 간 sleep 10초 필수.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urlencode

import requests as _requests
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
from crawlers.marts.source_utils import (
    absolute_url,
    build_source_attributes,
    build_source_map_manifest,
    normalize_source_key,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)

BASE_URL = "https://www.costco.co.kr"

# OCC REST API 설정 (baseSite=korea: lang=ko, curr=KRW 지원 확인됨)
OCC_BASE_SITE = "korea"
OCC_SEARCH_URL = f"{BASE_URL}/rest/v2/{OCC_BASE_SITE}/products/search"
OCC_LANG = "ko"
OCC_CURR = "KRW"
OCC_PAGE_SIZE = 100   # 서버 측 최대 pageSize=100
OCC_MAX_PAGES = 20    # 카테고리당 안전 상한

# 확인된 OCC 카테고리 코드 (REST API에서 실제 응답 확인)
# SpecialPriceOffers: 732건, OnlineDeals: 995건
OCC_CATEGORY_CODES: tuple[str, ...] = (
    "SpecialPriceOffers",
    "OnlineDeals",
)

# SAP Commerce Cloud (Spartacus) OCC API 기본 사이트 ID 후보 (순서대로 시도)
OCC_BASE_SITES: tuple[str, ...] = ("korea", "central", "costco-kr")
# OCC API 제품 검색 엔드포인트 템플릿 (이전 호환성)
OCC_SEARCH_PATH = "/rest/v2/{baseSite}/products/search"

# 카테고리 코드 목록 (SAP Hybris /c/{categoryCode} 패턴)
CATEGORY_CODES: tuple[tuple[str, str], ...] = (
    ("Special-Price-Offers/c/SpecialPriceOffers", "SpecialPriceOffers"),
    ("c/FoodandBeverage", "FoodandBeverage"),
    ("c/FreshFood", "FreshFood"),
    ("c/FrozenRefrigerated", "FrozenRefrigerated"),
    ("c/HealthBeauty", "HealthBeauty"),
    ("c/Electronics", "Electronics"),
    ("c/Furniture", "Furniture"),
    ("c/ClothingFootwear", "ClothingFootwear"),
    ("c/OutdoorSports", "OutdoorSports"),
    ("c/KitchenDining", "KitchenDining"),
    ("c/PetSupplies", "PetSupplies"),
    ("c/BabyKids", "BabyKids"),
    ("c/Office", "Office"),
    ("c/CleaningProducts", "CleaningProducts"),
    ("c/Automotive", "Automotive"),
)

# 카테고리 URL 목록 (이전 호환성 유지)
CATEGORY_ENDPOINTS: tuple[str, ...] = tuple(
    f"{BASE_URL}/{path}" for path, _ in CATEGORY_CODES
)

# 핵심 생필품 검색 키워드
SEARCH_KEYWORDS: tuple[str, ...] = (
    "우유", "계란", "휴지", "세제", "샴푸",
    "라면", "과자", "음료", "커피", "치즈",
    "고기", "생선", "과일", "채소", "빵",
)

# Special-Price-Offers 최대 시도 페이지 수 (backward compat)
SPECIAL_OFFERS_MAX_PAGES: int = 8

# Playwright 카테고리당 최대 페이지 수 (OCC pagination 활용 시 자동 조정)
MAX_PAGES_PER_CATEGORY: int = 5

# PUBLIC_ENDPOINTS는 테스트 호환성을 위해 유지
PUBLIC_ENDPOINTS: tuple[str, ...] = CATEGORY_ENDPOINTS

_BAN_HTML_PATTERNS: tuple[str, ...] = (
    "access denied",
    "please enable javascript",
    "cf-browser-verification",
    "ddos protection by cloudflare",
    "checking your browser",
    "ray id",
)

_WON_RE = re.compile(r"([0-9][0-9,]*)\s*원")

# Chrome 최신 UA (Akamai 우회용)
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def parse_costco_listing(html: str) -> list[CostcoCard]:
    """코스트코 카탈로그 HTML(SSR/Playwright 렌더링)에서 상품 카드를 추출한다."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[CostcoCard] = []
    for li in soup.select("li.product-list-item"):
        thumb = li.select_one("a.thumb[href]")
        if not thumb:
            continue
        href = thumb.get("href") or ""
        if "/p/" not in href:
            continue
        name = (thumb.get("title") or "").strip()
        if not name:
            img = li.select_one("img[title], img[alt]")
            if img:
                name = (img.get("title") or img.get("alt") or "").strip()
        if not name:
            continue

        sale_node = li.select_one(".product-price-amount")
        original_node = li.select_one(".original-price")
        unit_node = li.select_one(".product-price-pre-unit-amount")
        member_only = bool(li.select_one(".price-panel-login"))

        sale_price = _parse_won(sale_node.get_text(" ", strip=True) if sale_node else None)
        original_price = _parse_won(original_node.get_text(" ", strip=True) if original_node else None)
        if sale_price is None and original_price is not None:
            sale_price = original_price
            original_price = None

        image_url = ""
        img = li.select_one(".product-image img[src], .product-image img[srcset], picture source[srcset]")
        if img:
            image_url = img.get("src") or (img.get("srcset") or "").split()[0] or ""

        cards.append(
            CostcoCard(
                name=name,
                sale_price=sale_price,
                original_price=original_price,
                unit_price_text=unit_node.get_text(" ", strip=True) if unit_node else None,
                detail_url=absolute_url(href, BASE_URL),
                image_url=absolute_url(image_url, BASE_URL),
                is_member_only=member_only,
                raw_html=str(li),
            )
        )
    return cards


def parse_costco_occ_response(data: dict) -> list[CostcoCard]:
    """SAP Commerce Cloud OCC API JSON 응답에서 CostcoCard 목록을 추출한다.

    Spartacus OCC /products/search 응답 구조:
      products[].code, name, price.value, images[].url, url
      pagination.currentPage, totalPages, totalResults
    """
    cards: list[CostcoCard] = []
    products = data.get("products") or []
    if not isinstance(products, list):
        return cards

    for product in products:
        if not isinstance(product, dict):
            continue
        name = (product.get("name") or "").strip()
        if not name or len(name) < 2:
            continue

        code = str(product.get("code") or "")
        product_url = product.get("url") or ""
        if product_url and not product_url.startswith("http"):
            product_url = f"{BASE_URL}{product_url}"
        elif not product_url and code:
            product_url = f"{BASE_URL}/p/{code}"

        # 가격 추출
        price_data = product.get("price") or {}
        sale_price: Optional[float] = None
        if isinstance(price_data, dict):
            val = price_data.get("value")
            if val is not None:
                try:
                    sale_price = float(val)
                except (TypeError, ValueError):
                    pass

        # 원가 (있으면) — Korea OCC API: basePrice, 폴백: wasPrice/originalPrice
        original_price: Optional[float] = None
        for orig_key in ("basePrice", "wasPrice", "originalPrice"):
            was_price = product.get(orig_key) or {}
            if isinstance(was_price, dict):
                val = was_price.get("value")
                if val is not None:
                    try:
                        original_price = float(val)
                        break
                    except (TypeError, ValueError):
                        pass

        # 이미지 (첫 번째)
        images = product.get("images") or []
        image_url = ""
        if isinstance(images, list):
            for img in images:
                if isinstance(img, dict):
                    raw = img.get("url") or ""
                    if raw:
                        image_url = raw if raw.startswith("http") else f"{BASE_URL}{raw}"
                        break

        cards.append(
            CostcoCard(
                name=name,
                sale_price=sale_price,
                original_price=original_price,
                unit_price_text=None,
                detail_url=product_url,
                image_url=image_url,
                is_member_only=False,
                raw_html="",
            )
        )
    return cards


def _occ_pagination(data: dict) -> tuple[int, int]:
    """OCC 응답에서 (currentPage, totalPages) 를 반환한다."""
    pagination = data.get("pagination") or {}
    current = int(pagination.get("currentPage") or 0)
    total = int(pagination.get("totalPages") or 1)
    return current, total


def cards_to_discount_items(
    cards: Iterable[CostcoCard],
    *,
    source_url: str,
    operator_capture_id: Optional[str] = None,
) -> list[DiscountItem]:
    items: list[DiscountItem] = []
    for card in cards:
        source_key = normalize_source_key("costco", card.detail_url or card.name)
        attrs = build_source_attributes(
            source_id="costco",
            source_record_key=source_key,
            detail_url=card.detail_url or source_url,
            image_url=card.image_url or "",
            extra={
                "original_price": card.original_price,
                "unit_price_text": card.unit_price_text,
                "is_member_only": card.is_member_only,
                "operator_capture_id": operator_capture_id,
                "collection_path": "operator_capture" if operator_capture_id else "public_endpoint",
            },
        )
        items.append(
            DiscountItem(
                name=card.name,
                store="코스트코",
                sale_price=int(card.sale_price or 0),
                original_price=int(card.original_price) if card.original_price is not None else None,
                detail_url=card.detail_url or "",
                image_url=card.image_url or "",
                attributes=attrs,
            )
        )
    return items


class CostcoCrawler(CrawlerContract):
    """코스트코 코리아 본 사이트(costco.co.kr) 전용 수집기. v0.6.0

    기본 전략: OCC REST API 직접 호출 (requests 기반).
    /rest/v2/korea/products/search (baseSite=korea, lang=ko, curr=KRW)
    확인 카테고리: SpecialPriceOffers(732건) + OnlineDeals(995건) = 1,727건 이상.
    """

    PUBLIC_ENDPOINTS = PUBLIC_ENDPOINTS
    MAX_REQUESTS: Optional[int] = None
    REQUEST_TIMEOUT = 30
    PAGE_SLEEP_SECONDS: float = 10.0
    MAX_PAGES_PER_CATEGORY: int = MAX_PAGES_PER_CATEGORY

    # Playwright 비활성화 플래그 (테스트에서 mock 주입용)
    _playwright_disabled: bool = False
    # 테스트용 mock HTML 주입: {url: html_str}  (HTML mock 경로)
    _mock_html_map: Optional[dict] = None
    # 테스트용 mock OCC 응답 주입: {cat_code: [page0_data, page1_data, ...]}
    _mock_occ_responses: Optional[dict] = None

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)
        self._detected_base_site: Optional[str] = None

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코스트코",
            version="0.6.0",
            group=CrawlerGroup.MART,
            description=(
                "코스트코 코리아 본 사이트 전용. OCC REST API 직접 호출(requests). "
                "baseSite=korea, lang=ko, curr=KRW. "
                "SpecialPriceOffers + OnlineDeals: 1,700건 이상 수집 가능."
            ),
            target_url=BASE_URL,
            strategies=["occ_rest_api", "playwright", "operator_workbench"],
        )

    def _build_all_urls(self) -> list[tuple[str, str]]:
        """수집할 전체 URL 목록 (url, path_type) 반환. 테스트 호환성 유지."""
        urls: list[tuple[str, str]] = []
        for endpoint in CATEGORY_ENDPOINTS:
            urls.append((endpoint, "category"))
        base_spo = f"{BASE_URL}/Special-Price-Offers/c/SpecialPriceOffers"
        for page in range(1, SPECIAL_OFFERS_MAX_PAGES):
            urls.append((f"{base_spo}?currentPage={page}", "pagination"))
        for keyword in SEARCH_KEYWORDS:
            search_url = f"{BASE_URL}/search?{urlencode({'text': keyword})}"
            urls.append((search_url, "search"))
        return urls

    async def crawl(self) -> CrawlResult:
        """OCC REST API로 카테고리를 풀스캔한다.

        테스트 mock 경로:
          - _mock_html_map 설정 시: HTML 파싱 mock 경로 (15개 CATEGORY_CODES 순회)
          - _mock_occ_responses 설정 시: OCC 응답 mock 경로
        실 수집: requests.Session으로 /rest/v2/korea/products/search 직접 호출.
        """
        started_at = datetime.now()

        if self._mock_html_map is not None:
            return await self._crawl_html_mock_mode(started_at)

        if self._mock_occ_responses is not None:
            return await self._crawl_occ_data_mode(started_at, self._mock_occ_responses)

        return await self._crawl_occ_rest_api(started_at)

    async def _crawl_occ_rest_api(self, started_at: datetime) -> CrawlResult:
        """requests.Session으로 OCC REST API를 직접 호출해 수집한다."""
        items: list[DiscountItem] = []
        error_failures: list[StrategyFailure] = []
        seen: set = set()
        pages_attempted = 0
        category_breakdown: dict[str, int] = {}

        sess = _requests.Session()
        sess.headers.update({
            "User-Agent": _CHROME_UA,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": f"{BASE_URL}/",
        })

        try:
            sess.get(BASE_URL + "/", timeout=15)
        except Exception:
            pass

        for cat_code in OCC_CATEGORY_CODES:
            if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                break

            cat_before = len(items)
            page = 0

            while True:
                if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                    break

                try:
                    resp = sess.get(
                        OCC_SEARCH_URL,
                        params={
                            "query": f":relevanceByDate:allCategories:{cat_code}",
                            "currentPage": page,
                            "pageSize": OCC_PAGE_SIZE,
                            "lang": OCC_LANG,
                            "curr": OCC_CURR,
                            "fields": "FULL",
                        },
                        timeout=self.REQUEST_TIMEOUT,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.warning("[코스트코][%s] page=%d 실패: %s", cat_code, page, exc)
                    error_failures.append(
                        StrategyFailure(
                            strategy_name="occ_rest_api",
                            error_type=ErrorType.HTTP_ERROR,
                            error_msg=f"{cat_code} page={page}: {exc}",
                        )
                    )
                    break

                cards = parse_costco_occ_response(data)
                pages_attempted += 1

                if not cards:
                    logger.debug("[코스트코][%s] page=%d 빈 결과, 중단", cat_code, page)
                    break

                for di in cards_to_discount_items(cards, source_url=OCC_SEARCH_URL):
                    key = source_dedup_key(di)
                    if key not in seen:
                        seen.add(key)
                        items.append(di)

                logger.info(
                    "[코스트코][%s] page=%d: +%d건 (누적 %d건)",
                    cat_code, page, len(cards), len(items),
                )

                _, total_pages = _occ_pagination(data)
                page += 1
                if page >= total_pages or page >= OCC_MAX_PAGES:
                    break

                if self.PAGE_SLEEP_SECONDS > 0:
                    await asyncio.sleep(self.PAGE_SLEEP_SECONDS)

            category_breakdown[cat_code] = len(items) - cat_before
            logger.info(
                "[코스트코][%s] 완료: %d건 수집", cat_code, category_breakdown[cat_code]
            )

            if (
                self.PAGE_SLEEP_SECONDS > 0
                and cat_code != OCC_CATEGORY_CODES[-1]
            ):
                await asyncio.sleep(self.PAGE_SLEEP_SECONDS)

        logger.info("[코스트코] OCC REST API 수집 완료: 합계=%d건", len(items))
        return self._build_result(
            started_at=started_at,
            items=items,
            error_failures=error_failures,
            pages_attempted=pages_attempted,
            category_breakdown=category_breakdown,
            strategy_used="occ_rest_api",
        )

    async def _crawl_html_mock_mode(self, started_at: datetime) -> CrawlResult:
        """_mock_html_map 주입 시 HTML 파싱 mock 경로 (테스트 전용)."""
        items: list[DiscountItem] = []
        seen: set = set()
        pages_attempted = 0
        category_breakdown: dict[str, int] = {}

        for path, cat_code in CATEGORY_CODES:
            if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                break

            category_url = f"{BASE_URL}/{path}"
            html = self._mock_html_map.get(category_url, "")  # type: ignore[union-attr]
            cards = parse_costco_listing(html)
            pages_attempted += 1

            cat_before = len(items)
            for di in cards_to_discount_items(cards, source_url=category_url):
                key = source_dedup_key(di)
                if key not in seen:
                    seen.add(key)
                    items.append(di)
            category_breakdown[cat_code] = len(items) - cat_before

            if self.PAGE_SLEEP_SECONDS > 0:
                await asyncio.sleep(self.PAGE_SLEEP_SECONDS)

        return self._build_result(
            started_at=started_at,
            items=items,
            error_failures=[],
            pages_attempted=pages_attempted,
            category_breakdown=category_breakdown,
            strategy_used="html_mock",
        )

    async def _crawl_occ_data_mode(
        self,
        started_at: datetime,
        mock_responses: dict,
    ) -> CrawlResult:
        """_mock_occ_responses 주입 시 OCC mock 경로 (테스트 전용)."""
        items: list[DiscountItem] = []
        seen: set = set()
        pages_attempted = 0
        category_breakdown: dict[str, int] = {}

        for cat_code, pages_data in mock_responses.items():
            cat_before = len(items)
            for data in (pages_data or []):
                cards = parse_costco_occ_response(data)
                pages_attempted += 1
                for di in cards_to_discount_items(cards, source_url=OCC_SEARCH_URL):
                    key = source_dedup_key(di)
                    if key not in seen:
                        seen.add(key)
                        items.append(di)
            category_breakdown[cat_code] = len(items) - cat_before

        return self._build_result(
            started_at=started_at,
            items=items,
            error_failures=[],
            pages_attempted=pages_attempted,
            category_breakdown=category_breakdown,
            strategy_used="occ_mock",
        )

    def _build_result(
        self,
        *,
        started_at: datetime,
        items: list[DiscountItem],
        error_failures: list[StrategyFailure],
        pages_attempted: int,
        category_breakdown: dict[str, int],
        strategy_used: str,
    ) -> CrawlResult:
        status = (
            CrawlStatus.SUCCESS if items
            else CrawlStatus.PARTIAL if error_failures
            else CrawlStatus.FAILED
        )
        return CrawlResult(
            crawler_name=self.info.name,
            status=status,
            items=[item.model_dump(mode="json") for item in items],
            items_count=len(items),
            errors=error_failures,
            started_at=started_at,
            finished_at=datetime.now(),
            quality_details={
                "source_map": build_source_map_manifest(
                    source_id="costco",
                    search_queries=list(SEARCH_KEYWORDS),
                    category_queries=list(OCC_CATEGORY_CODES),
                    max_pages=OCC_MAX_PAGES,
                    parser_contract="costco_storefront_li_product_list_item.v1",
                    request_strategy="occ_rest_api_direct",
                    parser_inputs=[
                        "occ_v2_products_search_json",
                        "li.product-list-item",
                        "a.thumb[title]",
                        ".product-price-amount",
                    ],
                ),
                "strategy_used": strategy_used,
                "public_endpoints_attempted": pages_attempted,
                "operator_capture_supported": True,
                "requires_operator_capture": False,
                "path_category_count": sum(category_breakdown.values()),
                "path_occ_count": sum(category_breakdown.values()),
                "path_html_count": 0,
                "path_pagination_count": 0,
                "path_search_count": 0,
                "total_count": len(items),
                "category_breakdown": category_breakdown,
                "path_a_count": sum(category_breakdown.values()),
                "path_c_count": 0,
            },
        )

    async def _fetch_category(
        self,
        helper,
        cat_code: str,
        category_url: str,
    ) -> tuple[list[CostcoCard], int, str]:
        """카테고리 URL에서 Playwright로 카드를 수집한다.

        Returns:
            (cards, pages_attempted, strategy_name)
        """
        # 테스트 mock 주입
        if self._mock_html_map is not None:
            html = self._mock_html_map.get(category_url, "")
            return parse_costco_listing(html), 1, "html_parse"

        occ_cards: list[CostcoCard] = []
        html_cards: list[CostcoCard] = []
        pages_done = 0
        strategy = "html_parse"

        page = await helper._context.new_page()
        try:
            intercepted_occ: list[dict] = []

            async def _on_response(response):
                try:
                    url = response.url or ""
                    if "/occ/v2/" in url and "products" in url and response.status == 200:
                        ct = (response.headers.get("content-type") or "").lower()
                        if "json" in ct:
                            body = await response.json()
                            if isinstance(body, dict) and "products" in body:
                                intercepted_occ.append(body)
                except Exception:
                    pass

            page.on("response", _on_response)

            # 첫 페이지 로드
            await page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector("li.product-list-item", timeout=20000)
            except Exception:
                logger.debug("[코스트코][%s] li.product-list-item 셀렉터 타임아웃", cat_code)
            await page.wait_for_timeout(3000)
            pages_done += 1

            if intercepted_occ:
                # 경로 A: OCC API 인터셉트 성공
                strategy = "occ_intercept"
                first_data = intercepted_occ[0]
                occ_cards.extend(parse_costco_occ_response(first_data))
                _, total_pages = _occ_pagination(first_data)
                max_pages = min(total_pages, self.MAX_PAGES_PER_CATEGORY)
                logger.info(
                    "[코스트코][%s] OCC 인터셉트: 첫 페이지 %d건, totalPages=%d",
                    cat_code, len(occ_cards), total_pages,
                )

                # 추가 페이지 (currentPage=1, 2, ...)
                for page_num in range(1, max_pages):
                    if self.MAX_REQUESTS is not None:
                        break
                    await asyncio.sleep(self.PAGE_SLEEP_SECONDS)
                    page_intercepted: list[dict] = []

                    async def _on_page_response(response, _buf=page_intercepted):
                        try:
                            url = response.url or ""
                            if "/occ/v2/" in url and "products" in url and response.status == 200:
                                ct = (response.headers.get("content-type") or "").lower()
                                if "json" in ct:
                                    body = await response.json()
                                    if isinstance(body, dict) and "products" in body:
                                        _buf.append(body)
                        except Exception:
                            pass

                    page.on("response", _on_page_response)
                    page_url = f"{category_url}?currentPage={page_num}"
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                    page.remove_listener("response", _on_page_response)
                    pages_done += 1

                    if not page_intercepted:
                        logger.debug("[코스트코][%s] page=%d OCC 없음, 중단", cat_code, page_num)
                        break
                    new_cards = parse_costco_occ_response(page_intercepted[0])
                    if not new_cards:
                        logger.debug("[코스트코][%s] page=%d 빈 결과, 중단", cat_code, page_num)
                        break
                    occ_cards.extend(new_cards)
                    logger.debug(
                        "[코스트코][%s] page=%d +%d건 (OCC)", cat_code, page_num, len(new_cards)
                    )

                return occ_cards, pages_done, strategy

            else:
                # 경로 B: HTML 파싱 폴백
                html = await page.content()
                html_cards.extend(parse_costco_listing(html))
                logger.info(
                    "[코스트코][%s] HTML 파싱: 첫 페이지 %d건", cat_code, len(html_cards)
                )

                # 추가 페이지 (currentPage=1, 2, ...)
                for page_num in range(1, self.MAX_PAGES_PER_CATEGORY):
                    if self.MAX_REQUESTS is not None:
                        break
                    await asyncio.sleep(self.PAGE_SLEEP_SECONDS)
                    page_url = f"{category_url}?currentPage={page_num}"
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_selector("li.product-list-item", timeout=15000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2000)
                    pages_done += 1
                    page_html = await page.content()
                    new_cards = parse_costco_listing(page_html)
                    if not new_cards:
                        logger.debug("[코스트코][%s] page=%d 빈 결과, 중단", cat_code, page_num)
                        break
                    html_cards.extend(new_cards)
                    logger.debug(
                        "[코스트코][%s] page=%d +%d건 (HTML)", cat_code, page_num, len(new_cards)
                    )

                return html_cards, pages_done, "html_parse"

        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        cards = parse_costco_listing(raw_data)
        return cards_to_discount_items(cards, source_url=BASE_URL)

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen: set = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen:
                continue
            seen.add(key)
            if item.sale_price <= 0:
                continue
            if len(item.name) < 2:
                continue
            valid.append(item)
        return valid

    def ingest_operator_capture(
        self,
        html: str,
        *,
        source_url: str,
        capture_id: Optional[str] = None,
    ) -> list[DiscountItem]:
        cards = parse_costco_listing(html)
        return cards_to_discount_items(
            cards, source_url=source_url, operator_capture_id=capture_id
        )
