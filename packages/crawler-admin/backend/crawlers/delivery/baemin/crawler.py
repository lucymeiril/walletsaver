"""
배달의민족 크롤러 — 배민마트/배민 웹 공개 정보 수집.

배달의민족은 앱 기반 서비스로 직접 API 접근이 제한적이다.
배민마트(mart.baemin.com / bmart.baemin.com)와 메인 웹사이트에서 공개된 상품/프로모션 정보를 수집한다.

제한사항:
  - 배달의민족 앱 API는 인증 토큰이 필요하며 직접 접근이 불가하다
  - 배민마트/배민 웹은 주소 설정이 필요할 수 있어 상품 노출이 제한된다
  - 현재는 웹 공개 정보 기반으로 최선의 데이터를 수집한다

접근 전략:
  1차: 배민마트 웹 페이지 HTML 파싱 (requests)
  2차: 배달의민족 메인 웹사이트 공개 정보 수집 (requests)
  3차: Playwright 브라우저 렌더링 — 배민마트 → bmart → 메인 순서로 시도

데이터 흐름: 배민 웹 → HTML/JSON → DiscountItem dict → CrawlResult
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
    StrategyFailure, ErrorType,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)

# 배민마트 URL 후보 (순서대로 시도)
_MART_URLS = [
    "https://mart.baemin.com",
    "https://bmart.baemin.com",
]


class BaeminCrawler(CrawlerContract):
    """배달의민족 크롤러 — 배민마트 상품/가격 수집.

    배달의민족 앱 API는 인증이 필요하여 직접 접근이 불가하다.
    배민마트 웹과 메인 웹사이트를 통해 공개된 상품/프로모션 데이터를 수집한다.
    주소 설정이 필요한 경우 PARTIAL 상태로 보고한다.
    """

    BASE_URL = "https://www.baemin.com"
    STORE_URL = "https://mart.baemin.com"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.5, delay_max=3.0)

    # Retry helper — exponential backoff for transient failures
    def _retry_request(self, url: str, *, headers: dict | None = None,
                       params: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3,
                       **kwargs) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, params=params, timeout=timeout, **kwargs)
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

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="배달의민족",
            version="2.0.0",
            group=CrawlerGroup.FOOD,
            description="배민마트/배달의민족 웹 상품 가격 수집",
            target_url=self.BASE_URL,
            strategies=["requests", "playwright"],
        )

    # ------------------------------------------------------------------
    # 메인 크롤 로직
    # ------------------------------------------------------------------

    async def crawl(self) -> CrawlResult:
        """배달의민족 공개 정보를 크롤링한다.

        전략 순서:
          1차: 배민마트 웹 HTML (requests)
          2차: 배민 메인 웹사이트 HTML (requests)
          3차: Playwright 렌더링 — mart → bmart → 메인
        """
        started_at = datetime.now()
        logger.info("[배민] 크롤링 시작")

        all_items: list[dict] = []
        strategy_errors: list[StrategyFailure] = []
        strategy_used = "requests"

        try:
            # 1차: 배민마트 크롤링 시도 (requests)
            for mart_url in _MART_URLS:
                mart_items, mart_err = self._fetch_mart_items(mart_url)
                if mart_items:
                    all_items.extend(mart_items)
                    logger.info(f"[배민] 배민마트({mart_url}): {len(mart_items)}개 수집")
                    break
                if mart_err:
                    strategy_errors.append(mart_err)

            # 2차: 배민 메인 웹사이트 정보 수집 (requests)
            web_items, web_err = self._fetch_web_items()
            if web_items:
                all_items.extend(web_items)
                logger.info(f"[배민] 웹사이트: {len(web_items)}개 수집")
            if web_err:
                strategy_errors.append(web_err)

            # 3차: Playwright 렌더링
            if not all_items:
                logger.info("[배민] HTTP 전략 실패, Playwright 렌더링 시도")
                pw_items, pw_err = await self._fetch_via_playwright()
                if pw_items:
                    all_items.extend(pw_items)
                    strategy_used = "playwright"
                if pw_err:
                    strategy_errors.append(pw_err)

            valid_items = await self.validate(all_items)

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()

            # 상태 결정
            if valid_items:
                status = CrawlStatus.SUCCESS
                error_msg = None
            elif strategy_errors:
                status = CrawlStatus.PARTIAL
                msgs = [e.error_msg for e in strategy_errors]
                error_msg = "; ".join(msgs)
            else:
                status = CrawlStatus.FAILED
                error_msg = "모든 전략 실패 — 수집된 데이터 없음"

            logger.info(
                f"[배민] 크롤링 완료: {len(valid_items)}개, "
                f"{duration:.2f}초, 전략={strategy_used}"
            )

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used=strategy_used,
                items_count=len(valid_items),
                items=valid_items,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                errors=strategy_errors,
                error_msg=error_msg,
            )

        except Exception as e:
            logger.error(f"[배민] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
                errors=[StrategyFailure(
                    strategy_name="crawl",
                    error_type=ErrorType.UNKNOWN,
                    error_msg=str(e),
                )],
            )

    # ------------------------------------------------------------------
    # Playwright 전략
    # ------------------------------------------------------------------

    async def _fetch_via_playwright(
        self,
    ) -> tuple[list[dict], Optional[StrategyFailure]]:
        """Playwright로 배민마트/배민 웹을 렌더링하여 데이터를 수집한다."""
        items: list[dict] = []

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                # 배민마트 URL들 순서대로 시도
                for mart_url in _MART_URLS:
                    try:
                        html = await helper.get_rendered_html(
                            mart_url,
                            wait_selector=(
                                "[class*='product'], [class*='item'], "
                                "[class*='goods'], [class*='card']"
                            ),
                            wait_timeout=20000,
                            scroll_to_bottom=True,
                        )
                        parsed = self._parse_mart_html(html, mart_url)
                        if parsed:
                            items.extend(parsed)
                            logger.info(
                                f"[배민] Playwright 배민마트({mart_url}): "
                                f"{len(parsed)}개 수집"
                            )
                            break
                    except Exception as e:
                        logger.debug(f"[배민] Playwright {mart_url} 실패: {e}")

                # 배민마트 실패 시 메인 사이트 시도
                if not items:
                    try:
                        html = await helper.get_rendered_html(
                            self.BASE_URL,
                            wait_selector=(
                                "[class*='restaurant'], [class*='brand'], "
                                "[class*='promo'], [class*='event'], "
                                "[class*='banner']"
                            ),
                            wait_timeout=20000,
                        )
                        # JSON 기반 추출
                        json_data = self._extract_json_from_html(html)
                        for product in json_data:
                            item = self._json_product_to_discount_item(product)
                            if item:
                                items.append(item)

                        # DOM 기반 fallback
                        if not items:
                            items.extend(
                                self._parse_rendered_dom(html, self.BASE_URL)
                            )
                    except Exception as e:
                        logger.debug(f"[배민] Playwright 메인사이트 실패: {e}")

                logger.info(f"[배민] Playwright 총: {len(items)}개 수집")

            if not items:
                return items, StrategyFailure(
                    strategy_name="playwright",
                    error_type=ErrorType.EMPTY_RESPONSE,
                    error_msg=(
                        "Playwright 렌더링 완료했으나 상품 데이터 없음. "
                        "알려진 제한사항: 배민마트/배민 웹은 주소 설정이 필요하여 "
                        "상품이 표시되지 않을 수 있음"
                    ),
                )
            return items, None

        except ImportError:
            msg = "playwright 미설치 — pip install playwright && playwright install chromium"
            logger.warning(f"[배민] {msg}")
            return [], StrategyFailure(
                strategy_name="playwright",
                error_type=ErrorType.UNKNOWN,
                error_msg=msg,
            )
        except Exception as e:
            logger.warning(f"[배민] Playwright 크롤링 실패: {e}")
            return [], StrategyFailure(
                strategy_name="playwright",
                error_type=ErrorType.UNKNOWN,
                error_msg=str(e),
            )

    # ------------------------------------------------------------------
    # HTTP requests 전략
    # ------------------------------------------------------------------

    def _get_headers(self) -> dict:
        """배민 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.baemin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return base_headers

    def _fetch_mart_items(
        self, url: str,
    ) -> tuple[list[dict], Optional[StrategyFailure]]:
        """배민마트 웹 페이지에서 상품 정보 수집."""
        items: list[dict] = []
        try:
            headers = self._get_headers()
            resp = self._retry_request(url, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[배민] 배민마트({url}) HTTP {resp.status_code}")
                return items, StrategyFailure(
                    strategy_name=f"requests-mart({url})",
                    error_type=ErrorType.HTTP_ERROR,
                    error_msg=f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )

            items.extend(self._parse_mart_html(resp.text, url))
            if not items:
                return items, StrategyFailure(
                    strategy_name=f"requests-mart({url})",
                    error_type=ErrorType.EMPTY_RESPONSE,
                    error_msg="HTML 수신 성공, 파싱된 상품 없음",
                )
            return items, None

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[배민] 배민마트({url}) 연결 실패: {e}")
            return items, StrategyFailure(
                strategy_name=f"requests-mart({url})",
                error_type=ErrorType.NETWORK_ERROR,
                error_msg=f"연결 실패: {e}",
            )
        except Exception as e:
            logger.warning(f"[배민] 배민마트({url}) 접근 실패: {e}")
            return items, StrategyFailure(
                strategy_name=f"requests-mart({url})",
                error_type=ErrorType.UNKNOWN,
                error_msg=str(e),
            )

    def _fetch_web_items(
        self,
    ) -> tuple[list[dict], Optional[StrategyFailure]]:
        """배달의민족 메인 웹사이트에서 공개 정보 수집."""
        items: list[dict] = []
        try:
            headers = self._get_headers()
            resp = self._retry_request(
                self.BASE_URL, headers=headers, timeout=15,
            )
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[배민] 웹사이트 HTTP {resp.status_code}")
                return items, StrategyFailure(
                    strategy_name="requests-web",
                    error_type=ErrorType.HTTP_ERROR,
                    error_msg=f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )

            # __NEXT_DATA__ / embedded JSON 추출
            json_data = self._extract_json_from_html(resp.text)
            for product in json_data:
                item = self._json_product_to_discount_item(product)
                if item:
                    items.append(item)

            # HTML DOM 파싱 fallback
            if not items:
                items.extend(
                    self._parse_rendered_dom(resp.text, self.BASE_URL)
                )

            if not items:
                return items, StrategyFailure(
                    strategy_name="requests-web",
                    error_type=ErrorType.EMPTY_RESPONSE,
                    error_msg=(
                        "배민 메인 웹사이트 HTML 수신 성공, "
                        "파싱된 상품/프로모션 없음"
                    ),
                )
            return items, None

        except Exception as e:
            logger.warning(f"[배민] 웹사이트 접근 실패: {e}")
            return items, StrategyFailure(
                strategy_name="requests-web",
                error_type=ErrorType.NETWORK_ERROR,
                error_msg=str(e),
            )

    # ------------------------------------------------------------------
    # HTML 파싱 공통
    # ------------------------------------------------------------------

    def _parse_mart_html(self, html: str, source_url: str) -> list[dict]:
        """배민마트 HTML에서 DiscountItem 호환 상품 정보 추출."""
        items: list[dict] = []

        # __NEXT_DATA__ / embedded JSON
        json_data = self._extract_json_from_html(html)
        if json_data:
            for product in json_data:
                item = self._json_product_to_discount_item(product, source_url)
                if item:
                    items.append(item)
            if items:
                return items

        # HTML DOM 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            cards = soup.select(
                "[class*='product'], [class*='item'], [class*='goods'], "
                "[class*='menu'], [class*='card'], [class*='store'], "
                "[class*='shop']"
            )

            for card in cards[:50]:
                item = self._parse_product_card(card, source_url)
                if item:
                    items.append(item)

            del soup  # 메모리 해제

        except Exception as e:
            logger.debug(f"[배민] HTML 파싱 실패: {e}")

        return items

    def _parse_rendered_dom(self, html: str, source_url: str) -> list[dict]:
        """범용 렌더링된 DOM에서 상품/프로모션 정보 추출."""
        items: list[dict] = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            cards = soup.select(
                "[class*='product'], [class*='item'], [class*='goods'], "
                "[class*='promo'], [class*='event'], [class*='banner'], "
                "[class*='restaurant'], [class*='store'], [class*='brand'], "
                "[class*='shop'], [class*='card']"
            )

            for card in cards[:50]:
                item = self._parse_product_card(card, source_url)
                if item:
                    items.append(item)

            del soup  # 메모리 해제

        except Exception as e:
            logger.debug(f"[배민] DOM 파싱 실패: {e}")

        return items

    def _parse_product_card(
        self, card, source_url: str,
    ) -> Optional[dict]:
        """HTML 상품/음식 카드 → DiscountItem 호환 딕셔너리."""
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong"
        )
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        card_text = card.get_text(" ", strip=True)

        # 가격 추출 — 할인가 / 원래가 구분 시도
        sale_price = 0
        original_price = None
        prices = self._extract_all_prices(card_text)
        if len(prices) >= 2:
            original_price = max(prices[:2])
            sale_price = min(prices[:2])
        elif len(prices) == 1:
            sale_price = prices[0]

        # 할인율
        discount_percent = None
        pct_match = re.search(r"(\d{1,2})\s*%", card_text)
        if pct_match:
            discount_percent = float(pct_match.group(1))
        elif original_price and sale_price and original_price > sale_price:
            discount_percent = round(
                (1 - sale_price / original_price) * 100, 1,
            )

        # 이벤트명 추출
        event_name = ""
        for keyword in ["1+1", "2+1", "반값", "특가", "할인", "세일", "타임딜", "쿠폰"]:
            if keyword in card_text:
                event_name = keyword
                break

        # 카테고리 추론
        category = ""
        for cat in [
            "치킨", "피자", "한식", "중식", "일식", "양식", "분식",
            "카페", "디저트", "과일", "채소", "정육", "수산", "유제품",
            "음료", "간식", "냉동", "즉석",
        ]:
            if cat in card_text:
                category = cat
                break

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        link_el = card.select_one("a[href]")
        detail_url = source_url
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("http"):
                detail_url = href
            elif href.startswith("/"):
                detail_url = source_url.rstrip("/") + href

        return {
            "name": name,
            "normalized_name": "",
            "store": "배달의민족",
            "original_price": original_price,
            "sale_price": sale_price,
            "discount_percent": discount_percent,
            "unit": "",
            "category": category,
            "event_name": event_name,
            "valid_from": None,
            "valid_until": None,
            "image_url": image_url,
            "detail_url": detail_url,
            "crawled_at": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # JSON 기반 파싱
    # ------------------------------------------------------------------

    def _extract_json_from_html(self, html: str) -> list[dict]:
        """HTML 내 __NEXT_DATA__ 및 embedded JSON 데이터 추출."""
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                found = self._deep_search_product_list(data)
                if found:
                    return found
            except json.JSONDecodeError:
                pass

        # embedded JSON 패턴
        for pattern in [
            r'"products?"\s*:\s*(\[.*?\])',
            r'"items?"\s*:\s*(\[.*?\])',
            r'"goods"\s*:\s*(\[.*?\])',
            r'"restaurants?"\s*:\s*(\[.*?\])',
            r'"menus?"\s*:\s*(\[.*?\])',
        ]:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue

        return []

    def _deep_search_product_list(self, data, depth: int = 0) -> list[dict]:
        """JSON 트리에서 상품 배열을 재귀 탐색한다."""
        if depth > 6:
            return []

        target_keys = {
            "products", "items", "goods", "restaurants",
            "stores", "menus", "shops", "banners", "promotions",
        }

        if isinstance(data, dict):
            for key, val in data.items():
                if key in target_keys and isinstance(val, list) and val:
                    if isinstance(val[0], dict):
                        return val
                result = self._deep_search_product_list(val, depth + 1)
                if result:
                    return result

        if isinstance(data, list) and data and isinstance(data[0], dict):
            first = data[0]
            if any(k in first for k in ("name", "title", "price", "salePrice")):
                return data

        return []

    def _json_product_to_discount_item(
        self, product: dict, source_url: str = "",
    ) -> Optional[dict]:
        """JSON 상품 데이터 → DiscountItem 호환 딕셔너리."""
        name = (
            product.get("name")
            or product.get("title")
            or product.get("productName")
            or product.get("shopName")
            or product.get("restaurantName")
            or product.get("storeName", "")
        )
        if not name or len(name) < 2:
            return None

        sale_price = (
            self._to_int(product.get("salePrice"))
            or self._to_int(product.get("price"))
            or self._to_int(product.get("finalPrice"))
            or 0
        )
        original_price = (
            self._to_int(product.get("originalPrice"))
            or self._to_int(product.get("regularPrice"))
            or self._to_int(product.get("listPrice"))
        )

        discount_percent = self._to_float(
            product.get("discountRate") or product.get("discountPercent"),
        )
        if not discount_percent and original_price and sale_price and original_price > sale_price:
            discount_percent = round((1 - sale_price / original_price) * 100, 1)

        category = (
            product.get("category")
            or product.get("categoryName")
            or product.get("groupName", "")
        )
        image_url = (
            product.get("imageUrl")
            or product.get("thumbnailUrl")
            or product.get("image", "")
        )
        detail_url = (
            product.get("detailUrl")
            or product.get("url")
            or source_url
        )

        return {
            "name": name,
            "normalized_name": "",
            "store": "배달의민족",
            "original_price": original_price,
            "sale_price": sale_price,
            "discount_percent": discount_percent,
            "unit": product.get("unit", ""),
            "category": category,
            "event_name": product.get("eventName") or product.get("promotionName", ""),
            "valid_from": None,
            "valid_until": None,
            "image_url": image_url,
            "detail_url": detail_url,
            "crawled_at": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # 가격 추출 유틸
    # ------------------------------------------------------------------

    def _extract_all_prices(self, text: str) -> list[int]:
        """텍스트에서 가격으로 보이는 숫자를 모두 추출한다."""
        if not text:
            return []
        prices: list[int] = []
        # "1,000" 형태의 콤마 가격
        for m in re.finditer(r"(\d{1,3}(?:,\d{3})+)", text):
            prices.append(int(m.group(1).replace(",", "")))
        # "10000" 형태 (3자리 이상)
        if not prices:
            for m in re.finditer(r"(\d{3,})", text):
                val = int(m.group(1))
                if val >= 100:
                    prices.append(val)
        return prices

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격 하나 추출."""
        prices = self._extract_all_prices(text)
        return prices[0] if prices else None

    # ------------------------------------------------------------------
    # parse / validate (CrawlerContract 구현)
    # ------------------------------------------------------------------

    async def parse(self, raw_data: str) -> list[dict]:
        """원본 HTML/JSON에서 상품 정보 파싱."""
        items: list[dict] = []

        json_data = self._extract_json_from_html(raw_data)
        for product in json_data:
            item = self._json_product_to_discount_item(product)
            if item:
                items.append(item)

        if not items:
            items.extend(self._parse_mart_html(raw_data, self.STORE_URL))

        return items

    async def validate(self, items: list[dict]) -> list[dict]:
        """유효한 아이템만 필터링 (DiscountItem 스키마 호환 확인)."""
        valid = []
        seen: set[str] = set()

        for item in items:
            name = item.get("name", "")
            if not name or len(name) < 2:
                continue

            key = f"{name}_{item.get('sale_price', 0)}"
            if key in seen:
                continue
            seen.add(key)

            valid.append(item)

        return valid

    # ------------------------------------------------------------------
    # 유틸
    # ------------------------------------------------------------------

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
