"""
쿠팡이츠 크롤러 — 배달앱 음식점/메뉴 가격 정보 수집.

쿠팡이츠는 웹 버전(www.coupangeats.com)이 있으나, 대부분의 데이터는
앱 API를 통해 제공되며 웹에서는 제한적인 정보만 접근 가능하다.

제한사항 (2026-03 확인):
  - 쿠팡이츠 웹은 주소 설정 후에만 음식점 목록을 보여준다
  - API 엔드포인트는 인증 토큰이 필요할 수 있다
  - 웹 렌더링이 JavaScript 기반이라 requests만으로는 한계가 있다
  - cloudscraper로 안티봇 우회를 시도한다
  - ⚠ 웹사이트는 "앱 다운로드" 랜딩 페이지만 제공 — 음식점/메뉴 없음
  - 향후 모바일 앱 자동화(Appium) 또는 파트너 API가 필요

접근 전략:
  1차: 쿠팡이츠 웹 API 엔드포인트 탐색
  2차: 웹 페이지 HTML/__NEXT_DATA__ 파싱
  3차: 공개된 음식점 정보 페이지 크롤링
  4차: Playwright 브라우저 렌더링 + API 인터셉트

데이터 흐름: 쿠팡이츠 웹 → HTML/JSON → dict → CrawlResult
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
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class CoupangEatsCrawler(CrawlerContract):
    """쿠팡이츠 크롤러 — 음식점/메뉴 가격 수집.

    참고: 쿠팡이츠 웹은 주소 기반 조회가 필수이며,
    API는 인증이 필요할 수 있어 수집이 제한적이다.
    """

    BASE_URL = "https://www.coupangeats.com"
    # 쿠팡이츠 웹 API (주소 기반 음식점 목록)
    API_BASE = "https://api.coupangeats.com"
    # 공개 접근 가능한 페이지
    MAIN_PAGE = "https://www.coupangeats.com"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.5, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="쿠팡이츠",
            version="1.0.0",
            group=CrawlerGroup.FOOD,
            description="쿠팡이츠 음식점/메뉴 가격 수집 (웹 기반)",
            target_url=self.BASE_URL,
            strategies=["requests", "cloudscraper"],
        )

    async def crawl(self) -> CrawlResult:
        """쿠팡이츠 음식점 정보를 크롤링한다.

        전략 순서:
          1차: HTTP 메인 페이지 데이터 추출
          2차: cloudscraper JS 챌린지 우회
          3차: Playwright 브라우저 렌더링 — React SPA 완전 렌더링
        """
        started_at = datetime.now()
        logger.info("[쿠팡이츠] 크롤링 시작")

        all_items: list[dict] = []
        errors: list[str] = []
        strategy_used = "requests"

        try:
            # 1차: 메인 페이지에서 데이터 추출 시도
            web_items = self._fetch_web_data()
            if web_items:
                all_items.extend(web_items)
                logger.info(f"[쿠팡이츠] 웹: {len(web_items)}개 수집")
            else:
                errors.append("웹 페이지에서 데이터 추출 실패")

            # 2차: cloudscraper로 재시도 (JS 챌린지 우회)
            if not all_items:
                logger.info("[쿠팡이츠] cloudscraper로 재시도")
                cs_items = self._fetch_with_cloudscraper()
                if cs_items:
                    all_items.extend(cs_items)
                    strategy_used = "cloudscraper"
                    logger.info(f"[쿠팡이츠] cloudscraper: {len(cs_items)}개 수집")
                else:
                    errors.append("cloudscraper 접근도 실패")

            # 3차: Playwright 브라우저 렌더링
            if not all_items:
                logger.info("[쿠팡이츠] Playwright 렌더링 시도")
                pw_items = await self._fetch_via_playwright()
                if pw_items:
                    all_items.extend(pw_items)
                    strategy_used = "playwright"
                else:
                    errors.append("Playwright 렌더링 실패")

            valid_items = await self.validate(all_items)

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.PARTIAL
            logger.info(f"[쿠팡이츠] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초, 전략={strategy_used}")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used=strategy_used,
                items_count=len(valid_items),
                items=valid_items,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
            )

        except Exception as e:
            logger.error(f"[쿠팡이츠] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def _fetch_via_playwright(self) -> list[dict]:
        """Playwright로 쿠팡이츠 SPA를 렌더링하여 데이터를 수집한다.

        쿠팡이츠 웹은 주소 설정 후에만 음식점 목록을 보여주므로,
        Playwright로 브라우저를 띄워 주소 설정 과정을 시뮬레이션하거나
        내부 API 호출을 인터셉트하여 음식점 데이터를 수집한다.
        """
        items: list[dict] = []

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                # API 인터셉트 — 쿠팡이츠 내부 API 가로채기
                api_responses = await helper.intercept_api(
                    self.MAIN_PAGE,
                    api_pattern="*api*restaurant*",
                    wait_timeout=20000,
                )

                for resp_data in api_responses:
                    restaurants = self._find_restaurants_in_json(resp_data)
                    for restaurant in restaurants:
                        item = self._restaurant_to_item(restaurant)
                        if item:
                            items.append(item)

                if not items:
                    # 렌더링된 DOM에서 파싱
                    html = await helper.get_rendered_html(
                        self.MAIN_PAGE,
                        wait_selector="[class*='restaurant'], [class*='store']",
                        wait_timeout=20000,
                        scroll_to_bottom=True,
                    )
                    items.extend(self._extract_from_html(html))

                logger.info(f"[쿠팡이츠] Playwright: {len(items)}개 수집")

        except ImportError:
            logger.warning("[쿠팡이츠] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[쿠팡이츠] Playwright 크롤링 실패: {e}")

        return items

    def _get_headers(self) -> dict:
        """쿠팡이츠 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.coupangeats.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return base_headers

    def _fetch_web_data(self) -> list[dict]:
        """쿠팡이츠 메인 페이지에서 데이터 추출."""
        items: list[dict] = []

        try:
            headers = self._get_headers()
            resp = requests.get(self.MAIN_PAGE, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[쿠팡이츠] HTTP {resp.status_code}")
                return items

            # __NEXT_DATA__ 또는 embedded JSON에서 음식점 데이터 추출
            items.extend(self._extract_from_html(resp.text))

        except Exception as e:
            logger.warning(f"[쿠팡이츠] 웹 접근 실패: {e}")

        return items

    def _fetch_with_cloudscraper(self) -> list[dict]:
        """cloudscraper로 JS 챌린지 우회하여 데이터 수집."""
        items: list[dict] = []

        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )

            resp = scraper.get(
                self.MAIN_PAGE,
                headers={
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Referer": "https://www.coupangeats.com/",
                },
                timeout=20,
            )

            if resp.status_code != 200:
                logger.warning(f"[쿠팡이츠] cloudscraper HTTP {resp.status_code}")
                return items

            items.extend(self._extract_from_html(resp.text))

        except ImportError:
            logger.warning("[쿠팡이츠] cloudscraper 미설치 — pip install cloudscraper")
        except Exception as e:
            logger.warning(f"[쿠팡이츠] cloudscraper 실패: {e}")

        return items

    def _extract_from_html(self, html: str) -> list[dict]:
        """HTML에서 음식점/메뉴 정보 추출."""
        items: list[dict] = []

        # __NEXT_DATA__ JSON 추출
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                restaurants = self._find_restaurants_in_json(page_props)
                for restaurant in restaurants:
                    item = self._restaurant_to_item(restaurant)
                    if item:
                        items.append(item)
                if items:
                    return items
            except json.JSONDecodeError:
                pass

        # embedded JSON 패턴 탐색
        for pattern in [
            r'"restaurants?"\s*:\s*(\[.*?\])',
            r'"stores?"\s*:\s*(\[.*?\])',
            r'"shops?"\s*:\s*(\[.*?\])',
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    restaurant_list = json.loads(match.group(1))
                    for r in restaurant_list:
                        item = self._restaurant_to_item(r)
                        if item:
                            items.append(item)
                    if items:
                        return items
                except json.JSONDecodeError:
                    continue

        # HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(
                "[class*='restaurant'], [class*='store'], "
                "[class*='shop'], [class*='merchant']"
            )
            for card in cards[:30]:
                item = self._parse_card(card)
                if item:
                    items.append(item)
        except Exception as e:
            logger.debug(f"[쿠팡이츠] HTML 파싱 실패: {e}")

        return items

    def _find_restaurants_in_json(self, data: dict, depth: int = 0) -> list[dict]:
        """중첩 JSON에서 음식점 리스트 탐색."""
        if depth > 5:
            return []

        for key in ["restaurants", "stores", "shops", "merchants", "items"]:
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val

        for key, val in data.items():
            if isinstance(val, dict):
                result = self._find_restaurants_in_json(val, depth + 1)
                if result:
                    return result
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        result = self._find_restaurants_in_json(item, depth + 1)
                        if result:
                            return result

        return []

    def _restaurant_to_item(self, restaurant: dict) -> Optional[dict]:
        """JSON 음식점 데이터 → 딕셔너리."""
        name = (
            restaurant.get("name")
            or restaurant.get("shopName")
            or restaurant.get("restaurantName")
            or restaurant.get("storeName", "")
        )
        if not name or len(name) < 2:
            return None

        category = (
            restaurant.get("category")
            or restaurant.get("categoryName")
            or restaurant.get("cuisineType", "기타")
        )
        rating = self._to_float(
            restaurant.get("rating") or restaurant.get("score")
        ) or 0.0
        delivery_fee = self._to_int(
            restaurant.get("deliveryFee") or restaurant.get("delivery_fee")
        ) or 0

        return {
            "restaurant_name": name,
            "menu_name": restaurant.get("representativeMenu", ""),
            "price": self._to_int(restaurant.get("price") or restaurant.get("averagePrice")) or 0,
            "category": category,
            "delivery_fee": delivery_fee,
            "min_order": self._to_int(restaurant.get("minOrderPrice")) or 0,
            "rating": rating,
            "source": "coupangeats",
            "image_url": restaurant.get("imageUrl") or restaurant.get("thumbnailUrl", ""),
            "detail_url": restaurant.get("detailUrl", ""),
        }

    def _parse_card(self, card) -> Optional[dict]:
        """HTML 음식점 카드 → 딕셔너리."""
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong, span"
        )
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        card_text = card.get_text(" ", strip=True)

        # 카테고리 추론
        category = "기타"
        for cat in ["치킨", "피자", "한식", "중식", "일식", "양식", "분식", "카페", "디저트", "버거"]:
            if cat in card_text:
                category = cat
                break

        # 배달비
        delivery_fee = 0
        fee_match = re.search(r"배달[\s]*(?:비|료)?[\s:]*(\d{1,3}(?:,\d{3})*)", card_text)
        if fee_match:
            delivery_fee = int(fee_match.group(1).replace(",", ""))

        # 평점
        rating = 0.0
        rating_match = re.search(r"(\d\.\d)", card_text)
        if rating_match:
            rating = float(rating_match.group(1))

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        return {
            "restaurant_name": name,
            "menu_name": "",
            "price": 0,
            "category": category,
            "delivery_fee": delivery_fee,
            "min_order": 0,
            "rating": rating,
            "source": "coupangeats",
            "image_url": image_url,
            "detail_url": self.BASE_URL,
        }

    async def parse(self, raw_data: str) -> list[dict]:
        """원본 데이터에서 음식점/메뉴 파싱."""
        return self._extract_from_html(raw_data)

    async def validate(self, items: list[dict]) -> list[dict]:
        """유효한 아이템만 필터링."""
        valid = []
        seen = set()

        for item in items:
            restaurant = item.get("restaurant_name", "")
            menu = item.get("menu_name", "")
            key = f"{restaurant}_{menu}"
            if key in seen:
                continue
            seen.add(key)

            if not restaurant or len(restaurant) < 2:
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
