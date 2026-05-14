"""
네이버 플레이스 실시간 크롤러 — 위치 기반 주변 가게/식당/주유소 정보 수집.

네이버 플레이스는 공식 API를 제공하지 않는다.
Playwright로 네이버 지도 검색 결과를 렌더링하고 DOM에서 가게 정보를 추출한다.

접근 전략:
  - 네이버 지도 검색 URL에 쿼리와 좌표를 포함하여 접근
  - Playwright로 검색 결과 페이지를 렌더링
  - 가게 목록 DOM에서 이름, 카테고리, 주소, 평점, 가격 등을 파싱
  - 실시간 크롤링: 사용자 요청 시마다 즉시 크롤링 (스케줄 X)

데이터 흐름: 네이버 지도 검색 → Playwright 렌더링 → DOM 파싱 → 가게 정보 반환
의존: core/, playwright
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime
from typing import Optional

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class NaverPlaceCrawler(CrawlerContract):
    """네이버 플레이스 실시간 크롤러 — 위치 기반 가게/식당/주유소 정보.

    사용자가 검색하거나 지도를 이동할 때 호출된다.
    네이버 지도 검색 결과를 Playwright로 렌더링하여 가게 정보를 추출한다.
    """

    BASE_URL = "https://map.naver.com"
    # 네이버 지도 검색 URL 템플릿 — 쿼리와 좌표 포함
    SEARCH_URL = "https://map.naver.com/p/search/{query}?c={lng},{lat},15,0,0,0,dh"

    # 가게 카테고리 매핑
    CATEGORY_MAP = {
        "주유소": "gas_station",
        "셀프주유소": "gas_station",
        "식당": "restaurant",
        "한식": "restaurant",
        "중식": "restaurant",
        "일식": "restaurant",
        "양식": "restaurant",
        "카페": "cafe",
        "커피": "cafe",
        "편의점": "convenience",
        "마트": "mart",
        "슈퍼마켓": "mart",
    }

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=2.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="네이버 플레이스",
            version="1.0.0",
            group=CrawlerGroup.LOCAL,
            description="네이버 플레이스 실시간 크롤링 — 위치 기반 가게/식당/주유소 정보",
            target_url=self.BASE_URL,
            strategies=["playwright"],
        )

    async def crawl(self, **kwargs) -> CrawlResult:
        """실시간 크롤링 — 사용자 요청 기반.

        Args (kwargs):
            query: 검색어 (예: "주유소", "한식 맛집", "카페")
            lat: 위도 (기본: 37.4979 서울 강남)
            lng: 경도 (기본: 127.0276)
            max_items: 최대 수집 수 (기본: 20)
        """
        started_at = datetime.now()
        query = kwargs.get("query", "맛집")
        lat = kwargs.get("lat", 37.4979)
        lng = kwargs.get("lng", 127.0276)
        max_items = kwargs.get("max_items", 20)

        logger.info(f"[네이버 플레이스] 크롤링 시작: query='{query}', lat={lat}, lng={lng}")

        try:
            items = await self._fetch_via_playwright(query, lat, lng, max_items)
            valid_items = await self.validate(items)

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.PARTIAL

            logger.info(f"[네이버 플레이스] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="playwright",
                items_count=len(valid_items),
                items=valid_items,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg=None if valid_items else "검색 결과 없음 또는 크롤링 실패",
            )

        except Exception as e:
            logger.error(f"[네이버 플레이스] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def _fetch_via_playwright(
        self, query: str, lat: float, lng: float, max_items: int
    ) -> list[dict]:
        """Playwright로 네이버 지도 검색 결과를 크롤링한다.

        네이버 지도는 React SPA로 구현되어 있어 Playwright로
        브라우저를 띄워 검색 결과를 완전히 렌더링해야 한다.
        검색 결과 목록은 iframe 안에 있으므로 iframe 전환이 필요하다.
        """
        items: list[dict] = []
        search_url = self.SEARCH_URL.format(query=query, lat=lat, lng=lng)

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                page = await helper._context.new_page()

                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    # 네이버 지도 검색 결과 로딩 대기 (jitter for anti-detection)
                    await page.wait_for_timeout(3000 + int(random.uniform(0, 1000)))

                    # 네이버 지도는 검색 결과를 iframe 안에 렌더링한다
                    # searchIframe이 존재하는지 확인
                    search_iframe = None
                    for frame in page.frames:
                        if "search" in frame.url.lower() or "place-site" in frame.url.lower():
                            search_iframe = frame
                            break

                    target = search_iframe or page

                    # 검색 결과 리스트 셀렉터 — 네이버 지도 구조
                    selectors = [
                        "[class*='place_bluelink']",   # 가게명 링크
                        "[class*='TYaxT']",            # 검색 결과 아이템
                        "[class*='UEzoS']",            # 리스트 아이템 컨테이너
                        "li[class*='VLTHu']",          # 리스트 아이템
                        ".CHC5F a",                     # 가게 링크
                    ]

                    # 리스트 아이템 수집
                    for selector in selectors:
                        try:
                            await target.wait_for_selector(selector, timeout=5000)
                            elements = await target.query_selector_all(selector)
                            if elements and len(elements) >= 2:
                                break
                        except Exception:
                            elements = []
                            continue

                    if not elements:
                        # fallback: 전체 HTML에서 파싱
                        html = await target.content()
                        items = self._parse_search_html(html, query)
                    else:
                        # 각 검색 결과 아이템에서 정보 추출
                        for i, el in enumerate(elements[:max_items]):
                            try:
                                item = await self._extract_place_info(target, el, query)
                                if item:
                                    items.append(item)
                            except Exception as e:
                                logger.debug(f"[네이버 플레이스] 아이템 {i} 추출 실패: {e}")

                finally:
                    await page.close()

        except ImportError:
            logger.warning("[네이버 플레이스] playwright 미설치")
        except Exception as e:
            logger.warning(f"[네이버 플레이스] Playwright 크롤링 실패: {e}")

        return items

    async def _extract_place_info(self, frame, element, query: str) -> Optional[dict]:
        """검색 결과 아이템에서 가게 정보를 추출한다."""
        try:
            # 가게명
            name = await element.inner_text()
            name = name.strip().split("\n")[0]  # 첫 줄이 가게명
            if not name or len(name) < 2:
                return None

            # 부모 컨테이너에서 추가 정보 추출
            parent = element
            parent_text = await parent.inner_text()
            lines = [l.strip() for l in parent_text.split("\n") if l.strip()]

            # 카테고리 추론
            category = self._infer_category(query, " ".join(lines))

            # 평점 추출
            rating = 0.0
            for line in lines:
                rating_match = re.search(r"(\d\.\d{1,2})", line)
                if rating_match:
                    rating = float(rating_match.group(1))
                    break

            # 주소 추출 — "서울" 또는 "경기" 등으로 시작하는 줄
            addr = ""
            for line in lines:
                if any(line.startswith(p) for p in ["서울", "경기", "인천", "부산", "대구", "대전", "광주", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]):
                    addr = line
                    break

            # 가격 추출 (메뉴/유가)
            price = 0
            for line in lines:
                price_match = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원?", line)
                if price_match:
                    price = int(price_match.group(1).replace(",", ""))
                    break

            return {
                "name": name,
                "category": category,
                "addr": addr,
                "rating": rating,
                "price": price,
                "source": "naver_place",
                "query": query,
            }

        except Exception as e:
            logger.debug(f"[네이버 플레이스] 아이템 추출 오류: {e}")
            return None

    def _parse_search_html(self, html: str, query: str) -> list[dict]:
        """HTML에서 검색 결과를 파싱한다 (fallback)."""
        items: list[dict] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # 네이버 지도 검색 결과 카드
            cards = soup.select(
                "[class*='place_bluelink'], [class*='TYaxT'], "
                "[class*='UEzoS'], li[class*='VLTHu']"
            )

            for card in cards[:20]:
                text = card.get_text(" ", strip=True)
                lines = [l.strip() for l in text.split("\n") if l.strip()]

                if not lines:
                    continue

                name = lines[0]
                if len(name) < 2:
                    continue

                category = self._infer_category(query, text)

                # 평점
                rating = 0.0
                rating_match = re.search(r"(\d\.\d{1,2})", text)
                if rating_match:
                    rating = float(rating_match.group(1))

                # 주소
                addr = ""
                for line in lines:
                    if any(line.startswith(p) for p in ["서울", "경기", "인천", "부산"]):
                        addr = line
                        break

                # 가격
                price = 0
                price_match = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원?", text)
                if price_match:
                    price = int(price_match.group(1).replace(",", ""))

                items.append({
                    "name": name,
                    "category": category,
                    "addr": addr,
                    "rating": rating,
                    "price": price,
                    "source": "naver_place",
                    "query": query,
                })

            del soup  # 메모리 해제

        except Exception as e:
            logger.warning(f"[네이버 플레이스] HTML 파싱 실패: {e}")

        return items

    def _infer_category(self, query: str, text: str) -> str:
        """검색어와 텍스트에서 카테고리를 추론한다."""
        combined = f"{query} {text}".lower()
        for keyword, category in self.CATEGORY_MAP.items():
            if keyword in combined:
                return category
        return "etc"

    async def parse(self, raw_data: str) -> list[dict]:
        """원본 HTML에서 가게 정보 파싱."""
        return self._parse_search_html(raw_data, "")

    async def validate(self, items: list[dict]) -> list[dict]:
        """유효한 가게 정보만 필터링."""
        valid = []
        seen = set()

        for item in items:
            name = item.get("name", "")
            key = f"{name}_{item.get('addr', '')}"
            if key in seen:
                continue
            seen.add(key)

            if not name or len(name) < 2:
                continue

            valid.append(item)

        return valid
