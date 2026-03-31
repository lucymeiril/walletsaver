"""
무신사 크롤러 — 패션 할인 상품 정보 수집.

무신사는 국내 최대 온라인 패션 플랫폼으로, 세일/할인 상품 데이터를 API로 제공한다.
PLP(Product Listing Page) API를 통해 할인율 높은 순으로 상품을 가져온다.

접근 전략:
  1차: 무신사 PLP API (JSON) — /api2/dp/v1/plp/goods
  2차: 카테고리 페이지 HTML 파싱 fallback

데이터 흐름: 무신사 API → JSON → DiscountItem → CrawlResult
의존: core/ 만
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class MusinsaCrawler(CrawlerContract):
    """무신사 크롤러 — 할인율 높은 패션 상품 수집."""

    BASE_URL = "https://www.musinsa.com"
    # PLP API — 할인율 순 정렬, 세일 상품만 필터
    API_URL = "https://www.musinsa.com/api2/dp/v1/plp/goods"
    # 랭킹 API (fallback)
    RANKING_URL = "https://www.musinsa.com/api2/dp/v1/ranking/goods"

    # 주요 카테고리 코드 (상의, 하의, 아우터, 원피스)
    CATEGORY_CODES = ["001", "003", "002", "020"]

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="무신사",
            version="1.0.0",
            group=CrawlerGroup.SHOPPING,
            description="무신사 패션 할인 상품 수집 (PLP API 기반)",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """무신사 할인 상품을 크롤링한다."""
        started_at = datetime.now()
        logger.info("[무신사] 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []

        try:
            # 1차: PLP API 시도
            items = self._fetch_via_api()
            if items:
                all_items.extend(items)
            else:
                errors.append("PLP API 응답 없음")

            # 2차: API 실패 시 HTML 크롤링 fallback
            if not all_items:
                logger.info("[무신사] API 실패, HTML 크롤링 시도")
                html_items = self._fetch_via_html()
                if html_items:
                    all_items.extend(html_items)
                else:
                    errors.append("HTML 크롤링도 실패")

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()

            if valid_items:
                status = CrawlStatus.SUCCESS
            else:
                status = CrawlStatus.PARTIAL
                errors.append(
                    "무신사는 Next.js SPA로 전환되어 HTTP 크롤링으로 상품 데이터 수집 불가. "
                    "Selenium/Playwright 기반 브라우저 자동화 필요."
                )
            logger.info(f"[무신사] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="requests",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
            )

        except Exception as e:
            logger.error(f"[무신사] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _get_headers(self) -> dict:
        """무신사 API 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.musinsa.com/categories/item/001",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.musinsa.com",
        })
        return base_headers

    def _fetch_via_api(self) -> list[DiscountItem]:
        """PLP API로 할인 상품 목록을 가져온다."""
        items: list[DiscountItem] = []

        for cat_code in self.CATEGORY_CODES:
            try:
                params = {
                    "category": cat_code,
                    "gf": "A",
                    "sortCode": "SALE_RATE",
                    "page": 1,
                    "size": 30,
                }
                headers = self._get_headers()
                resp = requests.get(
                    self.API_URL, params=params, headers=headers, timeout=15
                )

                if resp.status_code != 200:
                    logger.warning(f"[무신사] API HTTP {resp.status_code} (카테고리 {cat_code})")
                    continue

                data = resp.json()
                goods_list = self._extract_goods_from_api(data)

                for product in goods_list:
                    item = self._api_product_to_item(product, cat_code)
                    if item:
                        items.append(item)

                logger.info(f"[무신사] 카테고리 {cat_code}: {len(goods_list)}개 발견")

                # 충분한 데이터 수집 시 중단
                if len(items) >= 50:
                    break

            except Exception as e:
                logger.warning(f"[무신사] API 요청 실패 (카테고리 {cat_code}): {e}")
                continue

        return items

    def _extract_goods_from_api(self, data: dict) -> list[dict]:
        """API 응답에서 상품 리스트 추출."""
        # 응답 구조 탐색 — 다양한 경로 시도
        for path in [
            lambda d: d.get("data", {}).get("goods", []),
            lambda d: d.get("data", {}).get("list", []),
            lambda d: d.get("data", {}).get("items", []),
            lambda d: d.get("goods", []),
            lambda d: d.get("list", []),
            lambda d: d.get("data", []) if isinstance(d.get("data"), list) else [],
        ]:
            try:
                result = path(data)
                if result and isinstance(result, list):
                    return result
            except Exception:
                continue
        return []

    def _api_product_to_item(self, product: dict, category_code: str) -> Optional[DiscountItem]:
        """API 상품 데이터 → DiscountItem 변환."""
        name = (
            product.get("goodsName")
            or product.get("goodsNm")
            or product.get("name", "")
        )
        if not name or len(name) < 2:
            return None

        # 가격 추출
        sale_price = self._to_int(
            product.get("salePrice")
            or product.get("price")
            or product.get("normalPrice")
        )
        if not sale_price or sale_price <= 0:
            return None

        original_price = self._to_int(
            product.get("normalPrice")
            or product.get("originPrice")
            or product.get("consumerPrice")
        )

        # 할인율
        discount_pct = self._to_float(product.get("saleRate") or product.get("discountRate"))
        if not discount_pct and original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        brand = product.get("brandName") or product.get("brand", "")
        image_url = product.get("imageUrl") or product.get("thumbnailImageUrl", "")
        if image_url and not image_url.startswith("http"):
            image_url = f"https://image.musinsa.com{image_url}"

        goods_no = product.get("goodsNo") or product.get("goodsId", "")
        detail_url = f"https://www.musinsa.com/products/{goods_no}" if goods_no else ""

        category_map = {
            "001": "상의", "002": "아우터", "003": "하의",
            "020": "원피스", "022": "신발", "023": "가방",
        }

        return DiscountItem(
            name=name,
            store="무신사",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category=f"{brand} > {category_map.get(category_code, '패션')}" if brand else category_map.get(category_code, "패션"),
            event_name="무신사 세일",
            image_url=image_url,
            detail_url=detail_url,
        )

    def _fetch_via_html(self) -> list[DiscountItem]:
        """HTML 페이지에서 할인 상품 추출 (API 실패 시 fallback)."""
        items: list[DiscountItem] = []
        url = "https://www.musinsa.com/categories/item/001?gf=A&sortCode=SALE_RATE"

        try:
            headers = self._get_headers()
            headers["Accept"] = "text/html,application/xhtml+xml"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                return items

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # 상품 카드 선택자 — 무신사 HTML 구조
            cards = soup.select(
                "[class*='goods-card'], [class*='product-card'], "
                ".list_info, .li_inner, [data-goods-no]"
            )
            logger.info(f"[무신사] HTML 상품 카드: {len(cards)}개")

            for card in cards[:50]:
                item = self._parse_html_card(card)
                if item:
                    items.append(item)

        except Exception as e:
            logger.warning(f"[무신사] HTML 크롤링 실패: {e}")

        return items

    def _parse_html_card(self, card) -> Optional[DiscountItem]:
        """HTML 상품 카드 → DiscountItem."""
        name_el = card.select_one(
            "[class*='title'], [class*='name'], .list_info a, a[href*='products']"
        )
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_from_card(
            card, "[class*='sale'], [class*='price'], .price"
        )
        original_price = self._extract_price_from_card(
            card, "[class*='origin'], [class*='normal'], .origin_price"
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 할인율 텍스트에서 추출
        rate_el = card.select_one("[class*='rate'], [class*='discount']")
        if rate_el and not discount_pct:
            rate_match = re.search(r"(\d+)", rate_el.get_text())
            if rate_match:
                discount_pct = float(rate_match.group(1))

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        link_el = card.select_one("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            detail_url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        brand_el = card.select_one("[class*='brand']")
        brand = brand_el.get_text(strip=True) if brand_el else ""

        return DiscountItem(
            name=name,
            store="무신사",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category=brand or "패션",
            event_name="무신사 세일",
            image_url=image_url,
            detail_url=detail_url,
        )

    def _extract_price_from_card(self, card, selectors: str) -> Optional[int]:
        """카드 내 CSS 셀렉터로 가격 추출."""
        for selector in selectors.split(","):
            el = card.select_one(selector.strip())
            if el:
                price = self._extract_price(el.get_text(strip=True))
                if price:
                    return price
        return None

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격(원) 추출."""
        if not text:
            return None
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)",
            r"(\d{3,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """JSON 또는 HTML 원본 데이터에서 상품 추출."""
        items: list[DiscountItem] = []

        # JSON 시도
        try:
            data = json.loads(raw_data)
            goods_list = self._extract_goods_from_api(data)
            for product in goods_list:
                item = self._api_product_to_item(product, "001")
                if item:
                    items.append(item)
            if items:
                return items
        except json.JSONDecodeError:
            pass

        # HTML fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            cards = soup.select(
                "[class*='goods-card'], [class*='product-card'], .list_info"
            )
            for card in cards:
                item = self._parse_html_card(card)
                if item:
                    items.append(item)
        except Exception as e:
            logger.warning(f"[무신사] parse 실패: {e}")

        return items

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        """유효한 할인 상품만 필터링."""
        valid = []
        seen = set()

        for item in items:
            key = f"{item.name}_{item.sale_price}"
            if key in seen:
                continue
            seen.add(key)

            if item.sale_price <= 0:
                continue
            if len(item.name) < 2:
                continue

            valid.append(item)

        return valid

    def _to_int(self, value) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _to_float(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
