"""
홈플러스 크롤러 — 전단지 및 할인 행사 상품 정보 수집.

홈플러스 행사 상품 페이지에서 전단지/할인 데이터를 수집한다.
홈플러스는 행사 상품 목록을 내부 API(JSON) 또는 SSR HTML로 제공하므로
cloudscraper 전략으로 접근한다.

데이터 흐름: API JSON/HTML → DiscountItem → ProductPrice → DB
용도: 할인 이력 DB 구축 (discount_history)
의존: core/ 만
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class HomeplusCrawler(CrawlerContract):
    """홈플러스 크롤러 — 전단지/할인 행사 상품 수집."""

    BASE_URL = "https://www.homeplus.co.kr"
    EVENT_URL = "https://www.homeplus.co.kr/event/eventMain.do"
    # 홈플러스 전단지 API (모바일)
    LEAFLET_API = "https://www.homeplus.co.kr/app/event/leaflet.do"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="홈플러스",
            version="1.0.0",
            group=CrawlerGroup.MART,
            description="홈플러스 전단지 및 할인 행사 상품 정보 수집",
            target_url=self.BASE_URL,
            strategies=["cloudscraper", "requests"],
        )

    async def crawl(self) -> CrawlResult:
        """홈플러스 행사 상품 페이지를 크롤링한다.

        2025년 기준 homeplus.co.kr → mfront.homeplus.co.kr(SPA)로 전환됨.
        SPA 렌더링 없이 데이터를 가져올 수 있는 API를 우선 시도하고,
        실패 시 HTML 파싱으로 폴백한다.
        """
        started_at = datetime.now()
        logger.info("[홈플러스] 크롤링 시작")

        try:
            headers = self._anti_detect.get_random_headers()
            headers.update({
                "Referer": "https://www.homeplus.co.kr/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })

            response = requests.get(
                self.EVENT_URL, headers=headers, timeout=20,
                allow_redirects=True,
            )

            # SPA 감지 — 응답이 작고 JS 프레임워크 셸만 반환되는 경우
            if "mfront.homeplus" in response.url or len(response.text) < 15000:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, "html.parser")
                product_markers = soup.select(".product-item, .goods_item, .event_item")
                if not product_markers:
                    logger.warning("[홈플러스] SPA 셸만 반환됨 — 브라우저 자동화 필요")
                    return CrawlResult(
                        status=CrawlStatus.PARTIAL,
                        crawler_name=self.info.name,
                        strategy_used="requests",
                        error_msg="홈플러스가 SPA로 전환됨 (mfront.homeplus.co.kr). "
                                  "Selenium/Playwright 기반 브라우저 자동화 필요.",
                        started_at=started_at,
                        finished_at=datetime.now(),
                    )

            if response.status_code != 200:
                logger.error(f"[홈플러스] HTTP {response.status_code}")
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg=f"HTTP {response.status_code}",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            raw_data = response.text
            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            logger.info(f"[홈플러스] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name=self.info.name,
                strategy_used="cloudscraper",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error(f"[홈플러스] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML/JSON 응답에서 할인 상품을 파싱한다."""
        items: list[DiscountItem] = []

        # JSON 데이터 블록 추출 시도
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product)
                if item:
                    items.append(item)
            return items

        # HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            items = self._parse_html(soup)
        except Exception as e:
            logger.warning(f"[홈플러스] HTML 파싱 실패: {e}")

        return items

    def _extract_json_items(self, raw_data: str) -> list[dict]:
        """페이지 내 임베디드 JSON 데이터 추출."""
        patterns = [
            r'var\s+(?:itemList|prodList|goodsList)\s*=\s*(\[.*?\]);',
            r'"itemList"\s*:\s*(\[.*?\])',
            r'"goods"\s*:\s*(\[.*?\])',
            r'"products"\s*:\s*(\[.*?\])',
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_data, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return []

    def _json_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """JSON 상품 데이터 → DiscountItem 변환."""
        name = (
            product.get("goodsNm")
            or product.get("itemNm")
            or product.get("prodNm")
            or product.get("name", "")
        )
        if not name or len(name) < 2:
            return None

        sale_price = self._to_int(
            product.get("salePrice") or product.get("sellprc")
            or product.get("sale_price") or product.get("price")
        )
        original_price = self._to_int(
            product.get("originPrice") or product.get("norprc")
            or product.get("original_price")
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        image_url = product.get("imgUrl") or product.get("goodsImg", "")
        category = product.get("categoryNm") or product.get("ctgNm", "")
        detail_url = product.get("goodsUrl") or product.get("detail_url", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"{self.BASE_URL}{detail_url}"

        return DiscountItem(
            name=name,
            store="홈플러스",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category=category,
            event_name=product.get("eventNm", "홈플러스 할인"),
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_html(self, soup) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다 (fallback)."""
        items: list[DiscountItem] = []

        product_cards = soup.select(
            ".product-item, .goods_item, .event_item, .item_box, .prod_wrap"
        )
        logger.info(f"[홈플러스] HTML 상품 카드: {len(product_cards)}개")

        for card in product_cards:
            try:
                item = self._parse_product_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[홈플러스] 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        """개별 상품 카드 HTML → DiscountItem."""
        name_el = card.select_one(
            ".product-name, .goods_name, .item_name, .prod_name, a[href*='goods']"
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_from_element(
            card, ".sale_price, .price .num, .discount_price, .spc_price"
        )
        original_price = self._extract_price_from_element(
            card, ".origin_price, .normal_price, .org_price, .before_price"
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        link_el = card.select_one("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        return DiscountItem(
            name=name,
            store="홈플러스",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            image_url=image_url,
            detail_url=detail_url,
            event_name="홈플러스 할인",
        )

    def _extract_price_from_element(self, card, selectors: str) -> Optional[int]:
        """CSS 셀렉터로 가격 요소를 찾아 정수 변환."""
        for selector in selectors.split(","):
            el = card.select_one(selector.strip())
            if el:
                price = self._extract_price(el.get_text(strip=True))
                if price is not None:
                    return price
        return None

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격(원)을 추출한다."""
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

    def _to_int(self, value) -> Optional[int]:
        """안전한 정수 변환."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

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
