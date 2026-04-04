"""
홈플러스 크롤러 — 전단지 및 할인 행사 상품 정보 수집.

홈플러스는 mfront.homeplus.co.kr SPA로 전환되어
서버사이드 HTML만으로는 상품 데이터를 추출할 수 없다.
Playwright 브라우저 렌더링으로 검색 결과를 수집하고,
.unitItemInner 카드에서 상품 정보를 파싱한다.

봇 탐지 회피 전략:
  - 검색어별 1~3초 랜덤 딜레이 (AntiDetect)
  - User-Agent 로테이션
  - Playwright stealth 모드로 자동화 탐지 우회
  - 검색어 간 점진적 크롤링

데이터 흐름: Playwright HTML → DiscountItem → ProductPrice → DB
용도: 할인 이력 DB 구축 (discount_history)
의존: core/ 만
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class HomeplusCrawler(CrawlerContract):
    """홈플러스 크롤러 — mfront.homeplus.co.kr SPA Playwright 기반 상품 수집.

    봇 탐지 회피 전략:
      - 검색어별 1~3초 랜덤 딜레이 (AntiDetect)
      - User-Agent 로테이션
      - Playwright stealth 모드로 봇 탐지 우회
      - 스크롤로 lazy-load 상품 트리거
    """

    BASE_URL = "https://www.homeplus.co.kr"
    MFRONT_URL = "https://mfront.homeplus.co.kr"
    # 다양한 검색어로 더 많은 할인 상품 수집
    SEARCH_QUERIES = ["할인", "특가", "세일", "1+1", "행사", "과일", "정육", "우유"]

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3,
                       **kwargs) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout, **kwargs)
                if resp.status_code == 429:  # Rate limited — back off
                    wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                    logger.warning(f"[{self.info.name}] Rate limited, retrying in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                return resp
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                    logger.warning(f"[{self.info.name}] Request failed (attempt {attempt+1}/{max_retries}), "
                                   f"retrying in {wait:.1f}s: {e}")
                    time.sleep(wait)
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="홈플러스",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="홈플러스 할인 상품 정보 수집 (mfront SPA Playwright 기반)",
            target_url=self.BASE_URL,
            strategies=["playwright", "requests"],
        )

    async def crawl(self) -> CrawlResult:
        """홈플러스 할인 상품을 크롤링한다.

        전략:
          mfront.homeplus.co.kr은 완전한 SPA이므로 Playwright 렌더링이 필수.
          /search?keyword= 검색 URL로 검색어별 상품을 수집한다.
          HTTP 요청은 SPA 셸만 반환하므로 Playwright를 기본 전략으로 사용한다.
        """
        started_at = datetime.now()
        logger.info("[홈플러스] 크롤링 시작")

        try:
            # Playwright 기반 크롤링 (SPA이므로 항상 Playwright 우선)
            items = await self._fetch_via_playwright()

            # Playwright 실패 시 HTTP fallback 시도
            if not items:
                logger.info("[홈플러스] Playwright 수집 실패, HTTP fallback 시도")
                items = await self._fetch_via_http()

            valid_items = await self.validate(items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
            strategy = "playwright" if items else "requests"
            logger.info(f"[홈플러스] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used=strategy,
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg=None if valid_items else "상품 수집 실패",
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

    async def _fetch_via_http(self) -> list[DiscountItem]:
        """HTTP 요청으로 홈플러스 상품 데이터를 수집한다 (fallback).

        mfront SPA가 아닌 front.homeplus.co.kr의 이벤트 페이지에서
        JSON/HTML 데이터 추출을 시도한다.
        """
        items: list[DiscountItem] = []
        headers = self._anti_detect.get_random_headers()
        headers.update({
            "Referer": "https://www.homeplus.co.kr/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        try:
            response = self._retry_request(
                f"{self.BASE_URL}/event/eventMain.do",
                headers=headers, timeout=20, allow_redirects=True,
            )
            if response.status_code == 200:
                items = await self.parse(response.text)
        except Exception as e:
            logger.debug(f"[홈플러스] HTTP fallback 실패: {e}")

        return items

    async def _fetch_via_playwright(self) -> list[DiscountItem]:
        """Playwright로 mfront.homeplus.co.kr 검색 페이지를 렌더링하여 상품 데이터를 추출한다.

        2025년 기준 홈플러스는 mfront.homeplus.co.kr SPA로 전환되어
        /search?keyword= 검색 URL이 유일하게 상품을 반환한다.
        .unitItemInner 카드에서 상품 정보를 파싱한다.
        """
        items: list[DiscountItem] = []
        seen_keys: set[str] = set()

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                for query in self.SEARCH_QUERIES:
                    url = f"{self.MFRONT_URL}/search?keyword={quote(query)}"
                    try:
                        html = await helper.get_rendered_html(
                            url,
                            wait_selector=".unitItemInner",
                            wait_timeout=20000,
                            extra_wait_ms=3000,
                            scroll_to_bottom=True,
                        )
                        page_items = await self.parse(html)
                        new_count = 0
                        for item in page_items:
                            key = f"{item.name}_{item.sale_price}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                items.append(item)
                                new_count += 1
                        logger.info(f"[홈플러스] '{query}' 검색: {new_count}개 신규 ({len(page_items)}개 중)")
                    except Exception as e:
                        logger.debug(f"[홈플러스] '{query}' 검색 실패: {e}")
                        continue

                logger.info(f"[홈플러스] Playwright 총: {len(items)}개 수집")

        except ImportError:
            logger.warning("[홈플러스] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[홈플러스] Playwright 크롤링 실패: {e}")

        return items

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
            del soup  # Free parsed HTML tree from memory
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
        """HTML에서 상품 정보를 파싱한다."""
        items: list[DiscountItem] = []

        # mfront.homeplus.co.kr 카드 (우선)
        mfront_cards = soup.select(".unitItemInner")
        if mfront_cards:
            logger.info(f"[홈플러스] mfront 상품 카드: {len(mfront_cards)}개")
            for card in mfront_cards:
                try:
                    item = self._parse_mfront_card(card)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.debug(f"[홈플러스] mfront 카드 파싱 오류: {e}")
                    continue
            return items

        # 기존 카드 (fallback)
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

    def _parse_mfront_card(self, card) -> Optional[DiscountItem]:
        """mfront.homeplus.co.kr 상품 카드(.unitItemInner) → DiscountItem."""
        # --- 이미지 ---
        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        # --- 링크 ---
        link_el = card.select_one("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            if href:
                detail_url = href if href.startswith("http") else f"{self.MFRONT_URL}{href}"

        # --- 가격: .priceValue 요소들 ---
        price_values = card.select(".priceValue")
        prices: list[int] = []
        for pv in price_values:
            p = self._extract_price(pv.get_text(strip=True))
            if p and p > 0:
                prices.append(p)

        # fallback: .price 컨테이너에서 가격 패턴 추출
        if not prices:
            price_container = card.select_one(".price")
            if price_container:
                for m in re.finditer(r"(\d{1,3}(?:,\d{3})+)\s*원", price_container.get_text()):
                    prices.append(int(m.group(1).replace(",", "")))

        if not prices:
            return None

        # 가격 할당: 2개 이상이면 (원가, 할인가), 1개면 할인가만
        if len(prices) >= 2:
            original_price = max(prices)
            sale_price = min(prices)
        else:
            sale_price = prices[0]
            original_price = None

        if sale_price <= 0:
            return None

        # --- 할인율 ---
        full_text = card.get_text(separator=" ", strip=True)
        discount_pct = None
        pct_match = re.search(r"(\d{1,2})%", full_text)
        if pct_match:
            discount_pct = float(pct_match.group(1))
        elif original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # --- 상품명 ---
        name = self._extract_mfront_name(card, img_el)
        if not name or len(name) < 2:
            return None

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

    def _extract_mfront_name(self, card, img_el) -> str:
        """mfront 카드에서 상품명을 추출한다."""
        # 1) 전용 이름 클래스 탐색
        for sel in (".itemName", ".productName", ".unit_title",
                    "[class*='name' i]", "[class*='Name']", "[class*='title' i]"):
            el = card.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) >= 2:
                    return txt

        # 2) 이미지 alt 텍스트
        if img_el:
            alt = (img_el.get("alt") or "").strip()
            if alt and len(alt) >= 2:
                return alt

        # 3) 전체 텍스트에서 가격/배송 정보 제거
        full = card.get_text(separator="|", strip=True)
        name = re.sub(r"\d{1,3}(?:,\d{3})*\s*원", "", full)
        name = re.sub(r"\d{1,2}%", "", name)
        name = re.sub(r"\d+\.\d+/\d+", "", name)
        name = re.sub(r"(상품할인|매직배송|무료배송|당일배송|만원[↑↓]?)", "", name)
        name = re.sub(r"\|", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:100] if name else ""

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
