"""
요기요 크롤러 — 배달앱 음식점/메뉴 가격 정보 수집.

요기요는 웹 인터페이스(www.yogiyo.co.kr)를 제공하며,
내부 API를 통해 음식점 목록과 메뉴 데이터를 로드한다.

접근 전략:
  1차: 요기요 웹 API — /api/v1/restaurants 또는 유사 엔드포인트
  2차: 웹 페이지 HTML/__NEXT_DATA__ 파싱
  3차: cloudscraper를 통한 JS 챌린지 우회
  4차: Playwright 브라우저 렌더링 + API 인터셉트

제한사항 (2026-03 확인):
  - 요기요 API는 위치(좌표) 기반 조회가 필수이다
  - 인증 토큰 없이는 제한적인 응답만 받을 수 있다
  - 웹 렌더링이 React/SPA 기반이라 서버사이드 데이터가 제한적이다
  - 웹 접속 시 #/ hash 라우팅만 보이며 주소 설정 없이는 콘텐츠가 없다
  - ⚠ 현재 웹에서는 음식점/메뉴 데이터를 가져올 수 없음 (앱 전용 서비스)
  - 향후 모바일 앱 자동화(Appium) 또는 파트너 API 접근이 필요

데이터 흐름: 요기요 웹/API → JSON/HTML → dict → CrawlResult
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
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class YogiyoCrawler(CrawlerContract):
    """요기요 크롤러 — 음식점/메뉴 가격 수집.

    요기요 웹 API와 HTML을 통해 음식점 정보를 수집한다.
    위치 기반 조회가 필수이며, 서울 주요 지역 좌표를 기본값으로 사용한다.
    """

    BASE_URL = "https://www.yogiyo.co.kr"
    # 요기요 API 엔드포인트 (웹 앱에서 사용하는 API)
    API_URL = "https://www.yogiyo.co.kr/api/v1/restaurants-geo/"
    # 서울 강남역 좌표 (기본 검색 위치)
    DEFAULT_LAT = 37.4979
    DEFAULT_LNG = 127.0276

    # 카테고리 코드
    CATEGORIES = {
        1: "한식",
        2: "중식",
        3: "일식",
        4: "양식",
        5: "치킨",
        6: "피자",
        7: "분식",
        8: "카페/디저트",
    }

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
            name="요기요",
            version="1.0.0",
            group=CrawlerGroup.FOOD,
            description="요기요 음식점/메뉴 가격 수집 (웹 API 기반)",
            target_url=self.BASE_URL,
            strategies=["requests", "cloudscraper"],
        )

    async def crawl(self) -> CrawlResult:
        """요기요 음식점 정보를 크롤링한다.

        전략 순서:
          1차: 요기요 API (JSON)
          2차: 웹 HTML 파싱
          3차: cloudscraper
          4차: Playwright 브라우저 렌더링 — React SPA 완전 렌더링
        """
        started_at = datetime.now()
        logger.info("[요기요] 크롤링 시작")

        all_items: list[dict] = []
        errors: list[str] = []
        strategy_used = "requests"

        try:
            # 1차: 요기요 API 시도
            api_items = self._fetch_via_api()
            if api_items:
                all_items.extend(api_items)
                logger.info(f"[요기요] API: {len(api_items)}개 수집")
            else:
                errors.append("API 접근 실패 또는 인증 필요")

            # 2차: 웹 페이지 HTML에서 데이터 추출
            if not all_items:
                logger.info("[요기요] API 실패, 웹 크롤링 시도")
                web_items = self._fetch_via_web()
                if web_items:
                    all_items.extend(web_items)
                    logger.info(f"[요기요] 웹: {len(web_items)}개 수집")
                else:
                    errors.append("웹 크롤링도 실패")

            # 3차: cloudscraper 시도
            if not all_items:
                logger.info("[요기요] cloudscraper 시도")
                cs_items = self._fetch_with_cloudscraper()
                if cs_items:
                    all_items.extend(cs_items)
                    strategy_used = "cloudscraper"
                else:
                    errors.append("cloudscraper 접근도 실패")

            # 4차: Playwright 브라우저 렌더링
            if not all_items:
                logger.info("[요기요] Playwright 렌더링 시도")
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
            logger.info(f"[요기요] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초, 전략={strategy_used}")

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
            logger.error(f"[요기요] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def _fetch_via_playwright(self) -> list[dict]:
        """Playwright로 요기요 SPA를 렌더링하여 데이터를 수집한다.

        요기요 웹은 React SPA로 위치 기반 조회가 필수이다.
        Playwright로 브라우저를 띄워 내부 API 호출을 인터셉트하거나
        렌더링된 음식점 카드 DOM에서 데이터를 추출한다.
        """
        items: list[dict] = []

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                # API 인터셉트 — 요기요 내부 API 가로채기
                api_responses = await helper.intercept_api(
                    self.BASE_URL,
                    api_pattern="*api*restaurant*",
                    wait_timeout=20000,
                )

                for resp_data in api_responses:
                    restaurants = self._extract_restaurants_from_api(resp_data)
                    for restaurant in restaurants:
                        item = self._api_restaurant_to_item(restaurant)
                        if item:
                            items.append(item)

                if not items:
                    # 렌더링된 DOM에서 파싱
                    html = await helper.get_rendered_html(
                        self.BASE_URL,
                        wait_selector="[class*='restaurant'], [class*='store'], [class*='list-item']",
                        wait_timeout=20000,
                        scroll_to_bottom=True,
                    )
                    items.extend(self._extract_from_html(html))

                logger.info(f"[요기요] Playwright: {len(items)}개 수집")

        except ImportError:
            logger.warning("[요기요] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[요기요] Playwright 크롤링 실패: {e}")

        return items

    def _get_headers(self) -> dict:
        """요기요 API 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.yogiyo.co.kr/",
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://www.yogiyo.co.kr",
            # 요기요 API 키 (웹 앱에서 공개적으로 사용하는 키)
            "x-apikey": "iphoneap",
            "x-apisecret": "fe5183cc3dea12bd0ce299cf110a75a2",
        })
        return base_headers

    def _fetch_via_api(self) -> list[dict]:
        """요기요 API로 음식점 목록 조회."""
        items: list[dict] = []

        # 여러 API 경로 시도
        api_endpoints = [
            {
                "url": "https://www.yogiyo.co.kr/api/v1/restaurants-geo/",
                "params": {
                    "lat": self.DEFAULT_LAT,
                    "lng": self.DEFAULT_LNG,
                    "items": 20,
                    "order": "rank",
                    "page": 0,
                },
            },
            {
                "url": "https://www.yogiyo.co.kr/api/v1/restaurants/",
                "params": {
                    "lat": self.DEFAULT_LAT,
                    "lng": self.DEFAULT_LNG,
                    "items": 20,
                    "order": "rank",
                },
            },
        ]

        # Session 재사용으로 TCP 연결 오버헤드 절감
        session = requests.Session()
        try:
            for endpoint in api_endpoints:
                try:
                    headers = self._get_headers()
                    resp = self._retry_request(
                        endpoint["url"],
                        params=endpoint["params"],
                        headers=headers,
                        session=session,
                        timeout=15,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        restaurants = self._extract_restaurants_from_api(data)
                        for restaurant in restaurants:
                            item = self._api_restaurant_to_item(restaurant)
                            if item:
                                items.append(item)
                        if items:
                            return items
                    else:
                        logger.warning(f"[요기요] API HTTP {resp.status_code}: {endpoint['url']}")

                except Exception as e:
                    logger.warning(f"[요기요] API 요청 실패: {e}")
        finally:
            session.close()

        return items

    def _extract_restaurants_from_api(self, data) -> list[dict]:
        """API 응답에서 음식점 리스트 추출."""
        # data가 리스트인 경우
        if isinstance(data, list):
            return data

        # data가 딕셔너리인 경우 — 다양한 키 탐색
        if isinstance(data, dict):
            for key in ["restaurants", "items", "data", "results", "stores"]:
                val = data.get(key)
                if isinstance(val, list) and val:
                    return val

            # 중첩 구조 탐색
            for key, val in data.items():
                if isinstance(val, dict):
                    for sub_key in ["restaurants", "items", "data"]:
                        sub_val = val.get(sub_key)
                        if isinstance(sub_val, list) and sub_val:
                            return sub_val

        return []

    def _api_restaurant_to_item(self, restaurant: dict) -> Optional[dict]:
        """API 음식점 데이터 → 딕셔너리."""
        name = (
            restaurant.get("name")
            or restaurant.get("restaurant_name")
            or restaurant.get("title", "")
        )
        if not name or len(name) < 2:
            return None

        # 카테고리
        category_code = restaurant.get("categories", [])
        category = "기타"
        if isinstance(category_code, list) and category_code:
            if isinstance(category_code[0], str):
                category = category_code[0]
            elif isinstance(category_code[0], int):
                category = self.CATEGORIES.get(category_code[0], "기타")
        elif isinstance(category_code, str):
            category = category_code

        # 배달비
        delivery_fee = self._to_int(
            restaurant.get("delivery_fee")
            or restaurant.get("deliveryFee")
            or restaurant.get("fee")
        ) or 0

        # 최소주문금액
        min_order = self._to_int(
            restaurant.get("min_order_amount")
            or restaurant.get("minOrderAmount")
            or restaurant.get("minimum_order_amount")
        ) or 0

        # 평점
        rating = self._to_float(
            restaurant.get("review_avg")
            or restaurant.get("rating")
            or restaurant.get("score")
            or restaurant.get("star")
        ) or 0.0

        # 이미지
        image_url = (
            restaurant.get("logo_url")
            or restaurant.get("thumbnail_url")
            or restaurant.get("imageUrl", "")
        )

        # 대표 메뉴
        representative_menus = restaurant.get("representative_menus", [])
        menu_name = ""
        price = 0
        if representative_menus and isinstance(representative_menus, list):
            if isinstance(representative_menus[0], dict):
                menu_name = representative_menus[0].get("name", "")
                price = self._to_int(representative_menus[0].get("price")) or 0
            elif isinstance(representative_menus[0], str):
                menu_name = representative_menus[0]

        return {
            "restaurant_name": name,
            "menu_name": menu_name,
            "price": price,
            "category": category,
            "delivery_fee": delivery_fee,
            "min_order": min_order,
            "rating": rating,
            "source": "yogiyo",
            "image_url": image_url,
            "detail_url": f"https://www.yogiyo.co.kr/mobile/#/{restaurant.get('id', '')}/" if restaurant.get("id") else "",
        }

    def _fetch_via_web(self) -> list[dict]:
        """웹 페이지 HTML에서 음식점 정보 추출."""
        items: list[dict] = []

        try:
            headers = self._get_headers()
            headers["Accept"] = "text/html,application/xhtml+xml"
            resp = self._retry_request(self.BASE_URL, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[요기요] 웹 HTTP {resp.status_code}")
                return items

            items.extend(self._extract_from_html(resp.text))

        except Exception as e:
            logger.warning(f"[요기요] 웹 접근 실패: {e}")

        return items

    def _fetch_with_cloudscraper(self) -> list[dict]:
        """cloudscraper로 JS 챌린지 우회."""
        items: list[dict] = []

        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )

            resp = scraper.get(
                self.BASE_URL,
                headers={
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Referer": "https://www.yogiyo.co.kr/",
                },
                timeout=20,
            )

            if resp.status_code == 200:
                items.extend(self._extract_from_html(resp.text))
            else:
                logger.warning(f"[요기요] cloudscraper HTTP {resp.status_code}")

        except ImportError:
            logger.warning("[요기요] cloudscraper 미설치 — pip install cloudscraper")
        except Exception as e:
            logger.warning(f"[요기요] cloudscraper 실패: {e}")

        return items

    def _extract_from_html(self, html: str) -> list[dict]:
        """HTML에서 음식점 정보 추출."""
        items: list[dict] = []

        # __NEXT_DATA__ JSON
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                restaurants = self._deep_find_restaurants(page_props)
                for r in restaurants:
                    item = self._api_restaurant_to_item(r)
                    if item:
                        items.append(item)
                if items:
                    return items
            except json.JSONDecodeError:
                pass

        # embedded JSON
        for pattern in [
            r'"restaurants?"\s*:\s*(\[.*?\])',
            r'"stores?"\s*:\s*(\[.*?\])',
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    for r in data:
                        item = self._api_restaurant_to_item(r)
                        if item:
                            items.append(item)
                    if items:
                        return items
                except json.JSONDecodeError:
                    continue

        # HTML 파싱
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(
                "[class*='restaurant'], [class*='store'], "
                "[class*='shop'], [class*='list-item']"
            )
            for card in cards[:30]:
                item = self._parse_html_card(card)
                if item:
                    items.append(item)

            del soup  # 메모리 해제

        except Exception as e:
            logger.debug(f"[요기요] HTML 파싱 실패: {e}")

        return items

    def _deep_find_restaurants(self, data: dict, depth: int = 0) -> list[dict]:
        """중첩 JSON에서 음식점 리스트 탐색."""
        if depth > 5:
            return []

        for key in ["restaurants", "stores", "shops", "items", "data"]:
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                if "name" in val[0] or "restaurant_name" in val[0]:
                    return val

        for key, val in data.items():
            if isinstance(val, dict):
                result = self._deep_find_restaurants(val, depth + 1)
                if result:
                    return result

        return []

    def _parse_html_card(self, card) -> Optional[dict]:
        """HTML 음식점 카드 → 딕셔너리."""
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong"
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

        # 최소주문
        min_order = 0
        min_match = re.search(r"최소[\s]*주문[\s:]*(\d{1,3}(?:,\d{3})*)", card_text)
        if min_match:
            min_order = int(min_match.group(1).replace(",", ""))

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
            "min_order": min_order,
            "rating": rating,
            "source": "yogiyo",
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
