"""
지오다노 크롤러 — SALE/할인 상품 정보 수집.

지오다노는 비교적 전통적인 이커머스 사이트로, HTML 기반 상품 목록을 제공한다.
세일 카테고리 페이지에서 할인 상품을 수집한다.

접근 전략:
  1차: 지오다노 세일 페이지 HTML 크롤링
  2차: 검색 API 또는 카테고리 API 시도

데이터 흐름: 지오다노 HTML → BeautifulSoup → DiscountItem → CrawlResult
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


class GiordanoCrawler(CrawlerContract):
    """지오다노 크롤러 — SALE/할인 상품 수집."""

    BASE_URL = "https://www.giordano.co.kr"
    # 세일 카테고리 페이지
    SALE_URLS = [
        "https://www.giordano.co.kr/product/list.html?cate_no=43",   # SALE
        "https://www.giordano.co.kr/category/sale/43/",               # 대안 URL
        "https://www.giordano.co.kr/product/list.html?cate_no=178",  # 특가
    ]

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="지오다노",
            version="1.0.0",
            group=CrawlerGroup.SHOPPING,
            description="지오다노 SALE/할인 상품 수집",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """지오다노 할인 상품을 크롤링한다."""
        started_at = datetime.now()
        logger.info("[지오다노] 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []

        try:
            for url in self.SALE_URLS:
                try:
                    headers = self._get_headers()
                    resp = requests.get(url, headers=headers, timeout=15)
                    resp.encoding = "utf-8"

                    if resp.status_code != 200:
                        logger.warning(f"[지오다노] HTTP {resp.status_code}: {url}")
                        errors.append(f"HTTP {resp.status_code}: {url}")
                        continue

                    items = await self.parse(resp.text)
                    logger.info(f"[지오다노] {url}: {len(items)}개 수집")
                    all_items.extend(items)

                    # 충분한 데이터 수집 시 중단
                    if len(all_items) >= 30:
                        break

                except Exception as e:
                    logger.warning(f"[지오다노] 요청 실패 ({url}): {e}")
                    errors.append(f"{url}: {e}")
                    continue

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
            if not valid_items:
                errors.append(
                    "지오다노는 Cafe24 SPA로 구현되어 HTTP 크롤링으로 상품 데이터 수집 불가. "
                    "Selenium/Playwright 기반 브라우저 자동화 필요."
                )
                status = CrawlStatus.PARTIAL
            logger.info(f"[지오다노] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

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
            logger.error(f"[지오다노] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _get_headers(self) -> dict:
        """지오다노 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.giordano.co.kr/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return base_headers

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다.

        지오다노는 cafe24 기반 쇼핑몰로, 일반적인 이커머스 HTML 구조를 사용한다.
        상품 리스트는 .prdList, .product-list, ul.prdList 등의 구조를 가진다.
        """
        items: list[DiscountItem] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")

            # cafe24 기반 상품 카드 셀렉터
            cards = soup.select(
                ".prdList li, .product-listnormal li, ul.prd_list li, "
                ".item_gallery_type li, .xans-product .xans-record-, "
                ".thumbnail, [class*='prd-item'], [class*='product-item']"
            )
            logger.info(f"[지오다노] 상품 카드: {len(cards)}개")

            for card in cards[:50]:
                item = self._parse_product_card(card)
                if item:
                    items.append(item)

            # 카드가 없으면 전체 텍스트에서 JSON 추출 시도
            if not items:
                json_items = self._extract_embedded_json(raw_data)
                for product in json_items:
                    item = self._json_to_discount_item(product)
                    if item:
                        items.append(item)

        except Exception as e:
            logger.warning(f"[지오다노] 파싱 실패: {e}")

        return items

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        """개별 상품 카드 → DiscountItem."""
        # 상품명 추출
        name_el = card.select_one(
            ".name a, .prd_name a, .product-name, .title a, "
            "[class*='name'] a, [class*='title'] a, strong a, p.name a"
        )
        if not name_el:
            name_el = card.select_one("a[href*='product']")
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        # 가격 추출 — 할인가와 원가
        card_text = card.get_text(" ", strip=True)

        # 할인가 (cafe24 구조: .sale, .discount, .ec-sale-price)
        sale_price = None
        sale_el = card.select_one(
            ".sale .price, [class*='sale'] .price, .ec-sale-price, "
            "[class*='discount'] .price, .prd_price .sale"
        )
        if sale_el:
            sale_price = self._extract_price(sale_el.get_text(strip=True))

        # 원가
        original_price = None
        orig_el = card.select_one(
            ".origin .price, [class*='origin'] .price, .ec-origin-price, "
            ".prd_price .origin, del, s, [class*='regular']"
        )
        if orig_el:
            original_price = self._extract_price(orig_el.get_text(strip=True))

        # 가격이 셀렉터로 안 잡히면 텍스트에서 추출
        if not sale_price:
            prices = self._extract_all_prices(card_text)
            if len(prices) >= 2:
                # 보통 원가가 먼저, 할인가가 뒤
                original_price = original_price or prices[0]
                sale_price = prices[-1]
            elif len(prices) == 1:
                sale_price = prices[0]

        if not sale_price or sale_price <= 0:
            return None

        # 할인율
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 할인율 텍스트
        rate_el = card.select_one("[class*='rate'], [class*='percent'], [class*='discount']")
        if rate_el and not discount_pct:
            rate_match = re.search(r"(\d+)\s*%", rate_el.get_text())
            if rate_match:
                discount_pct = float(rate_match.group(1))

        # 이미지
        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or img_el.get("data-original", "")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.BASE_URL, image_url)

        # 상세 URL
        link_el = card.select_one("a[href*='product'], a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            detail_url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        return DiscountItem(
            name=name,
            store="지오다노",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category="패션",
            event_name="지오다노 SALE",
            image_url=image_url,
            detail_url=detail_url,
        )

    def _extract_embedded_json(self, html: str) -> list[dict]:
        """HTML 내 임베디드 JSON에서 상품 데이터 추출."""
        patterns = [
            r'var\s+(?:product_list|prdList|items)\s*=\s*(\[.*?\]);',
            r'"products?"\s*:\s*(\[.*?\])',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return []

    def _json_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """JSON 상품 데이터 → DiscountItem."""
        name = product.get("name") or product.get("product_name", "")
        if not name or len(name) < 2:
            return None

        sale_price = self._to_int(product.get("sale_price") or product.get("price"))
        if not sale_price or sale_price <= 0:
            return None

        original_price = self._to_int(product.get("origin_price") or product.get("regular_price"))

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        return DiscountItem(
            name=name,
            store="지오다노",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category="패션",
            event_name="지오다노 SALE",
            image_url=product.get("image_url", ""),
            detail_url=product.get("detail_url", ""),
        )

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격 추출."""
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

    def _extract_all_prices(self, text: str) -> list[int]:
        """텍스트에서 모든 가격 추출."""
        prices = []
        for match in re.finditer(r"(\d{1,3}(?:,\d{3})+)", text):
            price = int(match.group(1).replace(",", ""))
            if price >= 1000:  # 의류 최소 가격 기준
                prices.append(price)
        return prices

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
