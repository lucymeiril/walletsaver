"""
유니클로 코리아 크롤러 — 기간한정가/SALE 상품 정보 수집.

유니클로는 SPA 기반 사이트로, 상품 데이터를 내부 API(JSON)로 제공한다.
상품 목록 API를 통해 세일 상품을 가져오고, DiscountItem으로 변환한다.

접근 전략:
  1차: 유니클로 상품 API — /kr/api/commerce/v5/kr/products
  2차: 카테고리 페이지 HTML 내 JSON 데이터 추출 fallback

데이터 흐름: 유니클로 API → JSON → DiscountItem → CrawlResult
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

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class UniqloCrawler(CrawlerContract):
    """유니클로 코리아 크롤러 — 기간한정가/SALE 상품 수집."""

    BASE_URL = "https://www.uniqlo.com/kr"
    # 유니클로 상품 API — 세일 상품 필터
    PRODUCT_API = "https://www.uniqlo.com/kr/api/commerce/v5/kr/products"
    # 세일 카테고리 페이지
    # 세일 카테고리 페이지 — feature/sale/{gender} 경로에 상품이 직접 렌더링된다
    SALE_PAGE = "https://www.uniqlo.com/kr/ko/sale"
    LIMITED_PAGE = "https://www.uniqlo.com/kr/ko/limited-offers"
    SALE_PAGES = [
        "https://www.uniqlo.com/kr/ko/feature/sale/men",
        "https://www.uniqlo.com/kr/ko/feature/sale/women",
        "https://www.uniqlo.com/kr/ko/feature/sale/kids",
    ]

    # 주요 카테고리 (남성, 여성, 키즈)
    CATEGORIES = {
        "men": {"path": "men", "label": "남성"},
        "women": {"path": "women", "label": "여성"},
        "kids": {"path": "kids", "label": "키즈"},
    }

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="유니클로",
            version="1.0.0",
            group=CrawlerGroup.SHOPPING,
            description="유니클로 코리아 기간한정가/SALE 상품 수집",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       params: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, params=params, timeout=timeout)
                if resp.status_code == 429:
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

    async def crawl(self) -> CrawlResult:
        """유니클로 세일 상품을 크롤링한다.

        전략 순서:
          1차: 상품 API (JSON)
          2차: Playwright 브라우저 렌더링 — Fast Retailing SPA 완전 렌더링
          3차: HTTP HTML fallback
        """
        started_at = datetime.now()
        logger.info("[유니클로] 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        strategy_used = "requests"

        try:
            # 1차: 상품 API로 세일 상품 조회
            api_items = self._fetch_via_api()
            if api_items:
                all_items.extend(api_items)
                logger.info(f"[유니클로] API에서 {len(api_items)}개 수집")
            else:
                errors.append("상품 API 응답 없음")

            # 2차: Playwright 브라우저 렌더링
            if not all_items:
                logger.info("[유니클로] API 실패, Playwright 렌더링 시도")
                pw_items = await self._fetch_via_playwright()
                if pw_items:
                    all_items.extend(pw_items)
                    strategy_used = "playwright"
                else:
                    errors.append("Playwright 렌더링 실패")

            # 3차: HTTP HTML fallback
            if not all_items:
                logger.info("[유니클로] Playwright 실패, HTML 크롤링 시도")
                html_items = self._fetch_via_html()
                if html_items:
                    all_items.extend(html_items)
                else:
                    errors.append("HTML 크롤링도 실패")

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.PARTIAL
            logger.info(f"[유니클로] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초, 전략={strategy_used}")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used=strategy_used,
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
            )

        except Exception as e:
            logger.error(f"[유니클로] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def _fetch_via_playwright(self) -> list[DiscountItem]:
        """Playwright로 유니클로 SPA를 렌더링하여 상품 데이터를 추출한다.

        유니클로 feature/sale 페이지는 상품이 HTML에 직접 렌더링되며(2M+ HTML),
        가격 패턴 "59,900원" 형태로 DOM에 다수 존재한다.
        API 인터셉트는 featured 4개만 반환하므로 DOM 파싱을 우선한다.
        """
        items: list[DiscountItem] = []
        seen_names: set[str] = set()

        try:
            from engine.playwright_helper import PlaywrightHelper
            from bs4 import BeautifulSoup

            async with PlaywrightHelper() as helper:
                for sale_url in self.SALE_PAGES:
                    try:
                        html = await helper.get_rendered_html(
                            sale_url,
                            wait_selector="body",
                            wait_timeout=15000,
                            scroll_to_bottom=False,
                        )
                        if not html or len(html) < 10000:
                            continue

                        soup = BeautifulSoup(html, "html.parser")

                        # 유니클로는 상품 링크가 /kr/ko/products/{ID} 패턴
                        product_links = soup.select('a[href*="/products/"]')
                        logger.info(f"[유니클로] {sale_url.split('/')[-1]}: 상품링크 {len(product_links)}개")

                        for link in product_links:
                            try:
                                href = link.get("href", "")
                                if not href or "/products/" not in href:
                                    continue

                                text = link.get_text(separator=" ", strip=True)
                                if not text or len(text) < 3:
                                    continue

                                # 상품명 추출 — 가격 패턴 앞의 텍스트
                                name_match = re.match(r"^(.+?)[\s]*[\d,]+원", text)
                                name = name_match.group(1).strip() if name_match else text[:80]

                                if not name or name in seen_names:
                                    continue

                                # 가격 추출 — "가격인하" 태그 후 원래가/할인가
                                prices = re.findall(r"([\d,]+)원", text)
                                if not prices:
                                    continue

                                # 가격이 2개면: 원래가, 할인가
                                if len(prices) >= 2:
                                    original = int(prices[0].replace(",", ""))
                                    sale = int(prices[1].replace(",", ""))
                                    if sale >= original:
                                        original, sale = sale, original
                                else:
                                    sale = int(prices[0].replace(",", ""))
                                    original = sale

                                if sale <= 0 or sale > 1000000:
                                    continue

                                discount = round((1 - sale / original) * 100, 1) if original > sale else 0

                                # 이미지 URL
                                img = link.select_one("img")
                                img_url = ""
                                if img:
                                    img_url = img.get("src", "") or img.get("data-src", "")

                                # 카테고리 — URL에서 추출
                                gender = "남성" if "/men" in sale_url else "여성" if "/women" in sale_url else "키즈"

                                full_url = href if href.startswith("http") else f"https://www.uniqlo.com{href}"

                                seen_names.add(name)
                                items.append(DiscountItem(
                                    name=name,
                                    normalized_name="",
                                    store="유니클로",
                                    original_price=original,
                                    sale_price=sale,
                                    discount_percent=discount,
                                    unit="",
                                    category=f"유니클로 > {gender}",
                                    event_name="유니클로 가격인하",
                                    image_url=img_url,
                                    detail_url=full_url,
                                    crawled_at=datetime.now(),
                                ))

                            except (ValueError, AttributeError):
                                continue

                    except Exception as e:
                        logger.warning(f"[유니클로] Playwright {sale_url} 실패: {e}")
                        continue

                logger.info(f"[유니클로] Playwright DOM 파싱: 총 {len(items)}개")

        except ImportError:
            logger.warning("[유니클로] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[유니클로] Playwright 크롤링 실패: {e}")

        return items

    def _get_headers(self) -> dict:
        """유니클로 API 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.uniqlo.com/kr/ko/sale",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.uniqlo.com",
            "X-Requested-With": "XMLHttpRequest",
        })
        return base_headers

    def _fetch_via_api(self) -> list[DiscountItem]:
        """유니클로 상품 API로 세일 상품 가져오기."""
        items: list[DiscountItem] = []

        # 여러 API 엔드포인트 시도
        api_urls = [
            # 세일 상품 API
            (
                "https://www.uniqlo.com/kr/api/commerce/v5/kr/products",
                {"offset": 0, "limit": 50, "salesStart": "sale", "httpFailure": "true"},
            ),
            # 추천 API (기간한정가)
            (
                "https://www.uniqlo.com/kr/api/commerce/v5/kr/recommend",
                {"offset": 0, "limit": 50, "salesStart": "sale", "httpFailure": "true"},
            ),
        ]

        # Session으로 TCP 커넥션 재사용 — API 반복 요청 최적화
        session = requests.Session()
        try:
            for api_url, params in api_urls:
                try:
                    headers = self._get_headers()
                    resp = self._retry_request(
                        api_url, params=params, headers=headers,
                        session=session, timeout=15,
                    )

                    if resp.status_code != 200:
                        logger.warning(f"[유니클로] API HTTP {resp.status_code}: {api_url}")
                        continue

                    data = resp.json()
                    products = self._extract_products_from_api(data)

                    for product in products:
                        item = self._api_to_discount_item(product)
                        if item:
                            items.append(item)

                    if items:
                        break

                except Exception as e:
                    logger.warning(f"[유니클로] API 실패: {e}")
                    continue
        finally:
            session.close()

        return items

    def _extract_products_from_api(self, data: dict) -> list[dict]:
        """API 응답에서 상품 리스트 추출."""
        # 유니클로 API 응답 구조 탐색
        for path_fn in [
            lambda d: d.get("result", {}).get("items", []),
            lambda d: d.get("result", {}).get("products", []),
            lambda d: d.get("data", {}).get("products", []),
            lambda d: d.get("data", {}).get("items", []),
            lambda d: d.get("items", []),
            lambda d: d.get("products", []),
            lambda d: d.get("result", []) if isinstance(d.get("result"), list) else [],
        ]:
            try:
                result = path_fn(data)
                if result and isinstance(result, list):
                    return result
            except Exception:
                continue
        return []

    def _api_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """API 상품 → DiscountItem 변환."""
        name = (
            product.get("name")
            or product.get("productName")
            or product.get("goodsNm", "")
        )
        if not name or len(name) < 2:
            return None

        # 가격 정보 추출 — prices 객체 또는 직접 필드
        prices = product.get("prices", {})
        sale_price = self._to_int(
            prices.get("base", {}).get("value")
            or prices.get("promo", {}).get("value")
            or product.get("salePrice")
            or product.get("price")
            or product.get("minPrice")
        )

        if not sale_price or sale_price <= 0:
            return None

        original_price = self._to_int(
            prices.get("original", {}).get("value")
            or product.get("originPrice")
            or product.get("normalPrice")
        )

        # 할인율 계산
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 이미지 URL
        image_url = ""
        images = product.get("images", {})
        if isinstance(images, dict):
            main_img = images.get("main", {})
            image_url = main_img.get("image", "") if isinstance(main_img, dict) else ""
        elif isinstance(images, list) and images:
            image_url = images[0].get("url", "") if isinstance(images[0], dict) else ""
        if not image_url:
            image_url = product.get("imageUrl") or product.get("thumbnailUrl", "")

        # 상세 URL
        product_id = product.get("productId") or product.get("id", "")
        detail_url = f"https://www.uniqlo.com/kr/ko/products/{product_id}" if product_id else ""

        # 카테고리
        category = product.get("genderName") or product.get("category", "패션")

        return DiscountItem(
            name=name,
            store="유니클로",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category=category,
            event_name="유니클로 기간한정가",
            image_url=image_url,
            detail_url=detail_url,
        )

    def _fetch_via_html(self) -> list[DiscountItem]:
        """세일 페이지 HTML에서 상품 추출 (fallback)."""
        items: list[DiscountItem] = []

        # Session으로 TCP 커넥션 재사용 — 페이지 반복 요청 최적화
        session = requests.Session()
        try:
            for url in [self.SALE_PAGE, self.LIMITED_PAGE]:
                try:
                    headers = self._get_headers()
                    headers["Accept"] = "text/html,application/xhtml+xml"
                    resp = self._retry_request(
                        url, headers=headers, session=session, timeout=15,
                    )
                    resp.encoding = "utf-8"

                    if resp.status_code != 200:
                        continue

                    # __NEXT_DATA__ 또는 embedded JSON 추출
                    page_items = self._extract_from_html(resp.text)
                    items.extend(page_items)

                    if items:
                        break

                except Exception as e:
                    logger.warning(f"[유니클로] HTML 크롤링 실패 ({url}): {e}")
        finally:
            session.close()

        return items

    def _extract_from_html(self, html: str) -> list[DiscountItem]:
        """HTML 내 JSON 데이터에서 상품 추출."""
        items: list[DiscountItem] = []

        # __NEXT_DATA__ JSON 추출 시도
        next_data_match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                # props.pageProps 에서 상품 데이터 탐색
                page_props = data.get("props", {}).get("pageProps", {})
                products = self._deep_find_products(page_props)
                for product in products:
                    item = self._api_to_discount_item(product)
                    if item:
                        items.append(item)
                if items:
                    return items
            except json.JSONDecodeError:
                pass

        # HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(
                "[class*='product'], [class*='item'], [class*='goods']"
            )
            for card in cards[:50]:
                item = self._parse_html_card(card)
                if item:
                    items.append(item)
            del soup  # 메모리 해제 — 대형 HTML 트리 조기 GC
        except Exception as e:
            logger.warning(f"[유니클로] HTML 파싱 실패: {e}")

        return items

    def _deep_find_products(self, data: dict, depth: int = 0) -> list[dict]:
        """중첩된 JSON 구조에서 상품 리스트를 재귀적으로 탐색."""
        if depth > 5:
            return []

        # 현재 레벨에서 상품 리스트 키 검색
        product_keys = ["products", "items", "goods", "productList"]
        for key in product_keys:
            val = data.get(key)
            if isinstance(val, list) and val:
                if isinstance(val[0], dict) and ("name" in val[0] or "productName" in val[0]):
                    return val

        # 재귀 탐색
        for key, val in data.items():
            if isinstance(val, dict):
                result = self._deep_find_products(val, depth + 1)
                if result:
                    return result
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        result = self._deep_find_products(item, depth + 1)
                        if result:
                            return result

        return []

    def _parse_html_card(self, card) -> Optional[DiscountItem]:
        """HTML 상품 카드 → DiscountItem."""
        name_el = card.select_one("[class*='name'], [class*='title'], h3, h4")
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_text(card.get_text(" ", strip=True))
        if not sale_price or sale_price <= 0:
            return None

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        return DiscountItem(
            name=name,
            store="유니클로",
            sale_price=sale_price,
            category="패션",
            event_name="유니클로 세일",
            image_url=image_url,
        )

    def _extract_price_text(self, text: str) -> Optional[int]:
        """텍스트에서 가격 추출."""
        if not text:
            return None
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)\s*원?",
            r"(\d{3,})\s*원?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """JSON 또는 HTML 데이터에서 상품 추출."""
        items: list[DiscountItem] = []
        try:
            data = json.loads(raw_data)
            products = self._extract_products_from_api(data)
            for product in products:
                item = self._api_to_discount_item(product)
                if item:
                    items.append(item)
            if items:
                return items
        except json.JSONDecodeError:
            pass

        items.extend(self._extract_from_html(raw_data))
        # 원본 raw_data 참조 해제 — 대형 문자열 조기 GC
        del raw_data
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
