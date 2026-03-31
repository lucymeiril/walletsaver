"""
배달의민족 크롤러 — 배달앱 음식점/메뉴 가격 정보 수집.

배달의민족은 앱 기반 서비스로 직접 API 접근이 제한적이다.
웹 버전(baemin.com)과 배민스토어(smartstore.baemin.com)에서 공개된 정보를 수집한다.

제한사항:
  - 배달의민족 앱 API는 인증 토큰이 필요하며 직접 접근이 불가하다
  - 웹 버전은 제한적인 정보만 공개한다
  - 실질적으로 유용한 데이터 수집은 앱 API 리버스 엔지니어링이 필요하다
  - 현재는 웹 공개 정보 기반으로 최선의 데이터를 수집한다

접근 전략:
  1차: 배민스토어 웹 페이지 HTML 파싱
  2차: 배달의민족 웹 사이트 공개 정보 수집

데이터 흐름: 배민 웹 → HTML/JSON → dict → CrawlResult
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


class BaeminCrawler(CrawlerContract):
    """배달의민족 크롤러 — 음식점/메뉴 가격 수집.

    참고: 배달의민족 앱 API는 인증이 필요하여 직접 접근이 불가하다.
    웹 공개 정보와 배민스토어를 통해 제한적인 데이터를 수집한다.
    """

    BASE_URL = "https://www.baemin.com"
    STORE_URL = "https://smartstore.baemin.com"
    # 배민 웹에서 접근 가능한 페이지 — 카테고리별 인기 음식점
    CATEGORY_URLS = {
        "치킨": "https://www.baemin.com",
        "피자": "https://www.baemin.com",
        "한식": "https://www.baemin.com",
        "중식": "https://www.baemin.com",
    }

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.5, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="배달의민족",
            version="1.0.0",
            group=CrawlerGroup.FOOD,
            description="배달의민족 음식점/메뉴 가격 수집 (웹 공개 정보 기반)",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """배달의민족 공개 정보를 크롤링한다."""
        started_at = datetime.now()
        logger.info("[배민] 크롤링 시작")

        all_items: list[dict] = []
        errors: list[str] = []

        try:
            # 1차: 배민스토어 크롤링 시도
            store_items = self._fetch_store_items()
            if store_items:
                all_items.extend(store_items)
                logger.info(f"[배민] 배민스토어: {len(store_items)}개 수집")
            else:
                errors.append("배민스토어 접근 실패 또는 데이터 없음")

            # 2차: 배민 메인 웹사이트에서 추가 정보 수집 시도
            web_items = self._fetch_web_items()
            if web_items:
                all_items.extend(web_items)
                logger.info(f"[배민] 웹사이트: {len(web_items)}개 수집")
            else:
                errors.append("배민 웹사이트 크롤링 실패")

            valid_items = await self.validate(all_items)

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.PARTIAL
            if not valid_items and not errors:
                status = CrawlStatus.FAILED

            # 배달앱 크롤링 제한사항 로깅
            if not valid_items:
                logger.warning(
                    "[배민] 데이터 수집 실패 — 배달의민족 API는 앱 인증이 필요합니다. "
                    "웹 공개 정보가 제한적입니다."
                )

            logger.info(f"[배민] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="requests",
                items_count=len(valid_items),
                items=valid_items,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
            )

        except Exception as e:
            logger.error(f"[배민] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _get_headers(self) -> dict:
        """배민 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.baemin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return base_headers

    def _fetch_store_items(self) -> list[dict]:
        """배민스토어 웹 페이지에서 상품 정보 수집."""
        items: list[dict] = []

        try:
            headers = self._get_headers()
            resp = requests.get(self.STORE_URL, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[배민] 배민스토어 HTTP {resp.status_code}")
                return items

            # HTML 내 JSON 데이터 또는 상품 정보 추출
            items.extend(self._parse_store_html(resp.text))

        except Exception as e:
            logger.warning(f"[배민] 배민스토어 접근 실패: {e}")

        return items

    def _parse_store_html(self, html: str) -> list[dict]:
        """배민스토어 HTML에서 상품 정보 추출."""
        items: list[dict] = []

        # __NEXT_DATA__ 또는 embedded JSON 시도
        json_data = self._extract_json_from_html(html)
        if json_data:
            for product in json_data:
                item = self._product_to_item(product)
                if item:
                    items.append(item)
            if items:
                return items

        # HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # 배민스토어 상품 카드 탐색
            cards = soup.select(
                "[class*='product'], [class*='item'], [class*='menu'], "
                "[class*='store'], [class*='shop']"
            )

            for card in cards[:30]:
                item = self._parse_store_card(card)
                if item:
                    items.append(item)

        except Exception as e:
            logger.debug(f"[배민] HTML 파싱 실패: {e}")

        return items

    def _parse_store_card(self, card) -> Optional[dict]:
        """배민스토어 상품 카드 → 딕셔너리."""
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong"
        )
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        price = self._extract_price(card.get_text(" ", strip=True))

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        return {
            "restaurant_name": "배민스토어",
            "menu_name": name,
            "price": price or 0,
            "category": "배민스토어",
            "delivery_fee": 0,
            "min_order": 0,
            "rating": 0.0,
            "source": "baemin",
            "image_url": image_url,
            "detail_url": self.STORE_URL,
        }

    def _fetch_web_items(self) -> list[dict]:
        """배달의민족 메인 웹사이트에서 공개 정보 수집."""
        items: list[dict] = []

        try:
            headers = self._get_headers()
            resp = requests.get(self.BASE_URL, headers=headers, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                logger.warning(f"[배민] 웹사이트 HTTP {resp.status_code}")
                return items

            # __NEXT_DATA__ 에서 데이터 추출 시도
            json_data = self._extract_json_from_html(resp.text)
            for product in json_data:
                item = self._product_to_item(product)
                if item:
                    items.append(item)

            # HTML 내 음식점/메뉴 정보 추출
            if not items:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")

                    restaurant_cards = soup.select(
                        "[class*='restaurant'], [class*='store'], "
                        "[class*='shop'], [class*='brand']"
                    )

                    for card in restaurant_cards[:20]:
                        item = self._parse_restaurant_card(card)
                        if item:
                            items.append(item)

                except Exception as e:
                    logger.debug(f"[배민] 웹 HTML 파싱 실패: {e}")

        except Exception as e:
            logger.warning(f"[배민] 웹사이트 접근 실패: {e}")

        return items

    def _parse_restaurant_card(self, card) -> Optional[dict]:
        """음식점 카드 → 딕셔너리."""
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
        for cat in ["치킨", "피자", "한식", "중식", "일식", "양식", "분식", "카페", "디저트"]:
            if cat in card_text:
                category = cat
                break

        # 배달비 추출
        delivery_fee = 0
        fee_match = re.search(r"배달[\s]*(?:비|료)?[\s:]*(\d{1,3}(?:,\d{3})*)", card_text)
        if fee_match:
            delivery_fee = int(fee_match.group(1).replace(",", ""))
        elif "무료배달" in card_text or "배달비 무료" in card_text:
            delivery_fee = 0

        # 최소주문금액
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
            "source": "baemin",
            "image_url": image_url,
            "detail_url": self.BASE_URL,
        }

    def _extract_json_from_html(self, html: str) -> list[dict]:
        """HTML 내 JSON 데이터 추출."""
        # __NEXT_DATA__ 추출
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                # 다양한 키에서 상품/음식점 데이터 탐색
                for key in ["products", "items", "restaurants", "stores", "menus", "shops"]:
                    val = page_props.get(key)
                    if isinstance(val, list) and val:
                        return val
                    # 중첩 구조 탐색
                    for nested_key, nested_val in page_props.items():
                        if isinstance(nested_val, dict):
                            nested_items = nested_val.get(key)
                            if isinstance(nested_items, list) and nested_items:
                                return nested_items
            except json.JSONDecodeError:
                pass

        # 기타 embedded JSON 패턴
        for pattern in [
            r'"restaurants?"\s*:\s*(\[.*?\])',
            r'"products?"\s*:\s*(\[.*?\])',
            r'"menus?"\s*:\s*(\[.*?\])',
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        return []

    def _product_to_item(self, product: dict) -> Optional[dict]:
        """JSON 상품 데이터 → 배달 아이템 딕셔너리."""
        name = (
            product.get("name")
            or product.get("shopName")
            or product.get("restaurantName")
            or product.get("storeName", "")
        )
        if not name or len(name) < 2:
            return None

        menu_name = product.get("menuName") or product.get("productName", "")
        price = self._to_int(product.get("price") or product.get("salePrice"))
        category = product.get("category") or product.get("categoryName", "기타")
        delivery_fee = self._to_int(product.get("deliveryFee")) or 0
        min_order = self._to_int(product.get("minOrder") or product.get("minimumOrderPrice")) or 0
        rating = self._to_float(product.get("rating") or product.get("score")) or 0.0

        return {
            "restaurant_name": name,
            "menu_name": menu_name,
            "price": price or 0,
            "category": category,
            "delivery_fee": delivery_fee,
            "min_order": min_order,
            "rating": rating,
            "source": "baemin",
            "image_url": product.get("imageUrl") or product.get("thumbnailUrl", ""),
            "detail_url": product.get("detailUrl") or product.get("url", ""),
        }

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격 추출."""
        if not text:
            return None
        for pattern in [r"(\d{1,3}(?:,\d{3})+)", r"(\d{3,})"]:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    async def parse(self, raw_data: str) -> list[dict]:
        """원본 데이터에서 음식점/메뉴 정보 파싱."""
        items: list[dict] = []

        json_data = self._extract_json_from_html(raw_data)
        for product in json_data:
            item = self._product_to_item(product)
            if item:
                items.append(item)

        if not items:
            items.extend(self._parse_store_html(raw_data))

        return items

    async def validate(self, items: list[dict]) -> list[dict]:
        """유효한 배달 아이템만 필터링."""
        valid = []
        seen = set()

        for item in items:
            restaurant = item.get("restaurant_name", "")
            menu = item.get("menu_name", "")
            key = f"{restaurant}_{menu}_{item.get('price', 0)}"
            if key in seen:
                continue
            seen.add(key)

            # 최소 음식점명이 있어야 함
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
