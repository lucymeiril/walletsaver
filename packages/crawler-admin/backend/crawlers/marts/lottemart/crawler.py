"""
롯데마트 크롤러 — 전단지 및 할인 행사 상품 정보 수집.

롯데마트는 lottemartzetta.com SPA로 리다이렉트되며,
서버사이드에서 window.__INITIAL_STATE__ (Redux 상태)에 상품 데이터를 포함한다.
검색 페이지(/search?query=...)를 통해 상품 데이터를 수집하고,
__INITIAL_STATE__의 productEntities에서 직접 추출한다.

봇 탐지 회피 전략:
  - 검색어별 1~3초 랜덤 딜레이 (AntiDetect)
  - User-Agent 로테이션
  - Referer 헤더로 정상 브라우저 흉내
  - HTTP 요청 실패 시 Playwright 브라우저 렌더링으로 폴백

데이터 흐름: __INITIAL_STATE__ JSON → DiscountItem → ProductPrice → DB
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
from core.product_units import normalize_unit_metadata
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)


class LottemartCrawler(CrawlerContract):
    """롯데마트 크롤러 — lottemartzetta.com __INITIAL_STATE__ 기반 할인 상품 수집.

    봇 탐지 회피 전략:
      - 검색어별 1~3초 랜덤 딜레이 (AntiDetect)
      - User-Agent 로테이션
      - HTTP 실패 시 Playwright 브라우저 렌더링으로 자동 전환
    """

    BASE_URL = "https://www.lottemart.com"
    ZETTA_BASE = "https://lottemartzetta.com"
    # 다양한 검색어로 더 많은 상품 수집
    SEARCH_QUERIES = ["할인", "특가", "과일", "채소", "정육", "세일", "우유", "음료"]

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
            name="롯데마트",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="롯데마트 할인 상품 정보 수집 (lottemartzetta __INITIAL_STATE__ 기반)",
            target_url=self.BASE_URL,
            strategies=["requests", "playwright"],
        )

    async def crawl(self) -> CrawlResult:
        """롯데마트 할인 상품을 크롤링한다.

        전략 순서:
          1차: HTTP 직접 요청으로 lottemartzetta.com/search 페이지의
               __INITIAL_STATE__ JSON에서 productEntities 추출
          2차: Playwright 브라우저 렌더링 (HTTP 실패 시 폴백)
        """
        started_at = datetime.now()
        logger.info("[롯데마트] 크롤링 시작")
        import asyncio as _asyncio

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        seen_ids: set[str] = set()

        # Reuse TCP connections across multiple search queries
        session = requests.Session()
        try:
            # 1차: __INITIAL_STATE__ 기반 추출 (HTTP 요청)
            for query in self.SEARCH_QUERIES:
                try:
                    url = f"{self.ZETTA_BASE}/search?query={quote(query)}"
                    headers = self._anti_detect.get_random_headers()
                    headers.update({
                        "Referer": f"{self.ZETTA_BASE}/",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    })

                    # 봇 탐지 회피 딜레이 + jitter
                    delay = self._anti_detect.get_random_delay()
                    await _asyncio.sleep(delay + random.uniform(0, 0.5))

                    response = self._retry_request(url, headers=headers, session=session, timeout=20, allow_redirects=True)

                    if response.status_code != 200:
                        logger.warning(f"[롯데마트] 검색 '{query}' HTTP {response.status_code}")
                        errors.append(f"검색 '{query}' HTTP {response.status_code}")
                        continue

                    # __INITIAL_STATE__에서 상품 데이터 추출
                    items = self._extract_from_initial_state(response.text)

                    # __INITIAL_STATE__ 추출 실패 시 HTML/JSON 파싱 폴백
                    if not items:
                        items = await self.parse(response.text)

                    new_count = 0
                    for item in items:
                        # productId 기반 중복 제거
                        key = f"{item.name}_{item.sale_price}"
                        if key not in seen_ids:
                            seen_ids.add(key)
                            all_items.append(item)
                            new_count += 1

                    logger.info(f"[롯데마트] 검색 '{query}': {new_count}개 신규 ({len(items)}개 중)")

                except Exception as e:
                    logger.warning(f"[롯데마트] 검색 '{query}' 실패: {e}")
                    errors.append(f"검색 '{query}': {e}")
                    continue

            fallback_used = False

            # HTTP로 충분한 데이터를 수집하지 못한 경우 Playwright 폴백
            if len(all_items) < 10:
                logger.info("[롯데마트] HTTP 수집 부족 → Playwright 폴백 시도")
                try:
                    pw_items = await self._fetch_via_playwright()
                    fallback_used = True
                    for item in pw_items:
                        key = f"{item.name}_{item.sale_price}"
                        if key not in seen_ids:
                            seen_ids.add(key)
                            all_items.append(item)
                except Exception as e:
                    logger.warning(f"[롯데마트] Playwright 폴백 실패: {e}")
                    errors.append(f"Playwright: {e}")

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(all_items),
                invalid_count=max(0, len(all_items) - len(valid_items)),
                errors=errors,
                strategy_used="playwright" if fallback_used else "requests",
                fallback_used=fallback_used,
                queries_attempted=len(self.SEARCH_QUERIES),
            )

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
            logger.info(f"[롯데마트] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="playwright" if fallback_used else "requests",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
                quality_score=quality_details["score"],
                quality_details=quality_details,
            )

        except Exception as e:
            logger.warning(f"[롯데마트] HTTP 요청 실패, Playwright 시도: {e}")
            try:
                items = await self._fetch_via_playwright()
                valid_items = await self.validate(items)
                items_as_dict = [item.model_dump(mode="json") for item in valid_items]
                finished_at = datetime.now()
                duration = (finished_at - started_at).total_seconds()
                if valid_items:
                    items_as_dict = [item.model_dump(mode="json") for item in valid_items]
                    quality_details = summarize_discount_run(
                        items_as_dict,
                        raw_count=len(items),
                        invalid_count=max(0, len(items) - len(valid_items)),
                        strategy_used="playwright",
                        fallback_used=True,
                    )
                    return CrawlResult(
                        status=CrawlStatus.SUCCESS,
                        crawler_name=self.info.name,
                        strategy_used="playwright",
                        items_count=len(valid_items),
                        items=items_as_dict,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_seconds=duration,
                        quality_score=quality_details["score"],
                        quality_details=quality_details,
                    )
            except Exception as e2:
                logger.error(f"[롯데마트] Playwright 폴백도 실패: {e2}")
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )
        finally:
            session.close()  # Release TCP connections

    def _extract_from_initial_state(self, html: str) -> list[DiscountItem]:
        """window.__INITIAL_STATE__ Redux 상태에서 productEntities를 추출한다.

        lottemartzetta.com은 서버사이드에서 Redux 상태를 window.__INITIAL_STATE__에 직렬화한다.
        productEntities는 UUID 키 → 상품 데이터 dict 구조이며,
        price.original.amount / price.current.amount로 원가/할인가를 추출한다.
        """
        items: list[DiscountItem] = []

        # __INITIAL_STATE__ JSON 추출
        idx = html.find("window.__INITIAL_STATE__=")
        if idx < 0:
            return items

        start = idx + len("window.__INITIAL_STATE__=")
        script_end = html.find("</script>", start)
        if script_end < 0:
            return items

        json_str = html[start:script_end].rstrip().rstrip(";")
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[롯데마트] __INITIAL_STATE__ JSON 파싱 실패")
            return items

        # productEntities에서 상품 추출
        product_entities = (
            data.get("data", {})
            .get("products", {})
            .get("productEntities", {})
        )

        if not product_entities:
            del data  # Free large JSON from memory
            return items

        logger.info(f"[롯데마트] __INITIAL_STATE__ productEntities: {len(product_entities)}개")

        for product_id, product in product_entities.items():
            item = self._entity_to_discount_item(product, product_id)
            if item:
                items.append(item)

        del data  # Free large JSON from memory
        return items

    def _entity_to_discount_item(self, product: dict, product_id: str = "") -> Optional[DiscountItem]:
        """lottemartzetta productEntity → DiscountItem 변환.

        필드 매핑:
          name → 상품명 (프로모션 접두사 제거)
          price.current.amount → 할인가
          price.original.amount → 원가
          image.src → 이미지 URL
          categoryPath → 카테고리
          size.value → 단위
          offer.description → 행사명
        """
        name = product.get("name", "")
        if not name or len(name) < 2:
            return None

        # 프로모션 접두사 제거: "[농할할인가 7,490원]" 같은 부분
        clean_name = re.sub(r"^\[.*?\]\s*", "", name).strip()
        if not clean_name or len(clean_name) < 2:
            clean_name = name

        # 가격 추출
        price_data = product.get("price", {})
        current = price_data.get("current", {})
        original = price_data.get("original", {})

        sale_price = self._parse_price_str(current.get("amount"))
        original_price = self._parse_price_str(original.get("amount"))

        if not sale_price or sale_price <= 0:
            return None

        # 할인율 계산
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 이미지 URL
        image_data = product.get("image", {})
        image_url = image_data.get("src", "")

        # 카테고리 (categoryPath 배열에서 첫 번째)
        category_path = product.get("categoryPath", [])
        category = category_path[0] if category_path else ""

        # 단위 (size.value)
        size = product.get("size", {})
        unit = size.get("value", "") if isinstance(size, dict) else ""

        # 행사 정보 (offer.description)
        offer = product.get("offer", {})
        event_name = "롯데마트 할인"
        if isinstance(offer, dict) and offer.get("description"):
            event_name = offer["description"]

        # 상세 URL
        detail_url = self._absolute_url(
            product.get("url") or product.get("productUrl") or product.get("detailUrl") or "",
            self.ZETTA_BASE,
        )
        if not detail_url and product_id:
            detail_url = f"{self.ZETTA_BASE}/products/{product_id}"

        # 브랜드
        brand = product.get("brand", "")
        unit_metadata = normalize_unit_metadata(
            name=clean_name,
            sale_price=sale_price,
            raw_unit=unit,
        )
        display_unit = unit_metadata.get("display_unit") or unit
        attributes = unit_metadata.get("attributes") or {}
        if brand:
            attributes = {**attributes, "brand": brand}

        return DiscountItem(
            name=clean_name,
            store="롯데마트",
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
            image_url=image_url,
            detail_url=detail_url,
        )

    async def _fetch_via_playwright(self) -> list[DiscountItem]:
        """Playwright로 롯데마트 SPA(lottemartzetta.com) 검색 페이지에서 상품을 수집한다.

        HTTP 요청으로 __INITIAL_STATE__ 추출이 실패할 경우의 폴백 전략.
        브라우저에서 실제 렌더링 후 product-card-container 요소를 파싱한다.
        """
        items: list[DiscountItem] = []

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                for query in self.SEARCH_QUERIES[:3]:  # Playwright는 느리므로 3개만
                    url = f"{self.ZETTA_BASE}/search?query={quote(query)}"
                    try:
                        html = await helper.get_rendered_html(
                            url,
                            wait_selector=".product-card-container",
                            wait_timeout=20000,
                            scroll_to_bottom=True,
                        )
                        # Playwright HTML에서도 __INITIAL_STATE__ 추출 시도
                        state_items = self._extract_from_initial_state(html)
                        if state_items:
                            items.extend(state_items)
                            logger.info(f"[롯데마트] Playwright '{query}': {len(state_items)}개 (state)")
                        else:
                            # HTML 파싱 폴백
                            page_items = self._parse_spa_html(html, query)
                            items.extend(page_items)
                            logger.info(f"[롯데마트] Playwright '{query}': {len(page_items)}개 (html)")
                    except Exception as e:
                        logger.debug(f"[롯데마트] Playwright 검색 '{query}' 실패: {e}")
                        continue

                logger.info(f"[롯데마트] Playwright 총: {len(items)}개 수집")

        except ImportError:
            logger.warning("[롯데마트] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[롯데마트] Playwright 크롤링 실패: {e}")

        return items

    def _parse_spa_html(self, html: str, query: str = "") -> list[DiscountItem]:
        """lottemartzetta.com SPA에서 렌더링된 HTML의 상품 카드를 파싱한다."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        items: list[DiscountItem] = []

        cards = soup.select(".product-card-container")
        logger.info(f"[롯데마트] SPA 상품 카드: {len(cards)}개 (query={query})")

        for card in cards:
            try:
                item = self._parse_spa_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[롯데마트] SPA 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_spa_card(self, card) -> Optional[DiscountItem]:
        """lottemartzetta.com SPA 상품 카드 → DiscountItem."""
        # 상품명: [class*="name"], [class*="title"], h3, h4, strong
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong"
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        # 가격 — "가격4,990원" 형태에서 "가격" 접두사 제거 후 숫자 추출
        prices: list[int] = []
        for el in card.select("[class*='price']"):
            text = el.get_text(strip=True)
            text = re.sub(r'^가격', '', text)
            price = self._extract_price(text)
            if price and price > 0:
                prices.append(price)

        if not prices:
            return None

        prices = sorted(set(prices))
        sale_price = prices[0]
        original_price = prices[-1] if len(prices) > 1 and prices[-1] != prices[0] else None

        # 상세 URL
        detail_url = ""
        link_el = card.select_one("a[href*='products']")
        if not link_el:
            link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("http"):
                detail_url = href
            elif href.startswith("/"):
                detail_url = f"{self.ZETTA_BASE}{href}"

        # 이미지
        image_url = ""
        img_el = card.select_one("img")
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        # 할인/행사 정보
        card_text = card.get_text(" ", strip=True)
        discount_pct = None
        event_name = "롯데마트 할인"

        discount_match = re.search(r'(\d+)%\s*할인', card_text)
        if discount_match:
            discount_pct = float(discount_match.group(1))
            context_match = re.search(r'([^,]*,?\s*\d+%\s*할인)', card_text)
            if context_match:
                event_name = context_match.group(1).strip()

        if discount_pct is None and original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 단위 정보
        unit = ""
        unit_match = re.search(
            r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개|팩|봉|매|입)(?:\([^)]+\))?)',
            card_text, re.IGNORECASE,
        )
        if unit_match:
            unit = unit_match.group(1)
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=unit,
        )
        display_unit = unit_metadata.get("display_unit") or unit

        return DiscountItem(
            name=name,
            store="롯데마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=unit_metadata.get("attributes") or {},
            image_url=image_url,
            detail_url=detail_url,
            event_name=event_name,
        )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML/JSON 응답에서 할인 상품을 파싱한다."""
        items: list[DiscountItem] = []

        # 1) __INITIAL_STATE__ 추출 (lottemartzetta.com)
        state_items = self._extract_from_initial_state(raw_data)
        if state_items:
            return state_items

        # 2) JSON 데이터 블록 추출 시도
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product)
                if item:
                    items.append(item)
            return items

        # 3) HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            items = self._parse_html(soup)
            del soup  # Free parsed HTML tree from memory
        except Exception as e:
            logger.warning(f"[롯데마트] HTML 파싱 실패: {e}")

        return items

    def _extract_json_items(self, raw_data: str) -> list[dict]:
        """페이지 내 임베디드 JSON 데이터 추출."""
        patterns = [
            r'var\s+(?:itemList|prodList|goodsList)\s*=\s*(\[.*?\]);',
            r'"itemList"\s*:\s*(\[.*?\])',
            r'"goodsList"\s*:\s*(\[.*?\])',
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
        raw_unit = product.get("unit") or product.get("size") or product.get("capacity") or ""
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit

        return DiscountItem(
            name=name,
            store="롯데마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=unit_metadata.get("attributes") or {},
            category=category,
            event_name=product.get("eventNm", "롯데마트 할인"),
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_html(self, soup) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다 (fallback)."""
        items: list[DiscountItem] = []

        product_cards = soup.select(
            ".product-card-container, .product-item, .goods_item, .event_item, .item_box, .prod_wrap"
        )
        logger.info(f"[롯데마트] HTML 상품 카드: {len(product_cards)}개")

        for card in product_cards:
            try:
                item = self._parse_product_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[롯데마트] 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        """개별 상품 카드 HTML → DiscountItem."""
        name_el = card.select_one(
            ".product-name, .goods_name, .item_name, .prod_name, a[href*='goods'], "
            "[class*='name'], [class*='title'], h3, h4, strong"
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
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")

        return DiscountItem(
            name=name,
            store="롯데마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=unit_metadata.get("attributes") or {},
            image_url=image_url,
            detail_url=detail_url,
            event_name="롯데마트 할인",
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

    def _parse_price_str(self, value) -> Optional[int]:
        """'29,780' 또는 '29780' 형태의 가격 문자열을 정수로 변환."""
        if value is None:
            return None
        text = str(value).replace(",", "").replace("원", "").strip()
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
        return None

    def _absolute_url(self, url: str, base_url: str) -> str:
        """Normalize source-relative URLs while preserving absolute URLs."""
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return f"{base_url}{url}"
        return url

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
