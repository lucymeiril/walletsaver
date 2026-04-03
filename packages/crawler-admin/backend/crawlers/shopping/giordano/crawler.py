"""
지오다노 크롤러 — SALE/할인 상품 정보 수집.

지오다노 쇼핑몰은 shop/big_section.php 세일 페이지에서 할인 상품 목록을 제공한다.
메인 페이지에서 현재 진행 중인 세일 URL을 동적으로 발견한 뒤,
각 세일 페이지를 HTTP로 가져와 상품을 수집한다.

세일 페이지 구조 (big_section.php → promotion.php 리다이렉트):
  li.each_prd_box > div.box > div.info > p.name (상품명)
                             > div.price > span.consumer (원가)
                                         > span.sale_prc (할인율)
                                         > span.sell (할인가)

접근 전략:
  1차: 메인 페이지에서 세일 URL 동적 발견
  2차: HTTP HTML 크롤링 (세일 페이지는 SSR이므로 HTTP로 충분)
  3차: Playwright 브라우저 렌더링 fallback

데이터 흐름: 메인 페이지 → 세일 URL 발견 → HTTP/Playwright → BeautifulSoup → DiscountItem → CrawlResult
의존: core/ 만
"""

from __future__ import annotations

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

# 세일 관련 키워드 — 메인 페이지에서 세일 URL을 필터링할 때 사용
_SALE_KEYWORDS = re.compile(
    r"세일|SALE|할인|특가|시즌오프|재입고|UP\s*TO|%|이벤트|프로모션|클리어런스",
    re.IGNORECASE,
)


class GiordanoCrawler(CrawlerContract):
    """지오다노 크롤러 — SALE/할인 상품 수집."""

    BASE_URL = "https://www.giordano.co.kr"
    # 세일 섹션 페이지 (big_section.php → promotion.php 리다이렉트)
    SALE_URLS = [
        "https://www.giordano.co.kr/shop/big_section.php?cno1=2956",  # 봄세일
        "https://www.giordano.co.kr/shop/big_section.php?cno1=2957",  # 봄세일
        "https://www.giordano.co.kr/shop/big_section.php?cno1=2947",  # 테리 재입고 SALE
    ]
    MAX_SALE_URLS = 5  # 동적 발견 시 최대 URL 수

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="지오다노",
            version="2.0.0",
            group=CrawlerGroup.SHOPPING,
            description="지오다노 SALE/할인 상품 수집",
            target_url=self.BASE_URL,
            strategies=["requests", "playwright"],
        )

    async def crawl(self) -> CrawlResult:
        """지오다노 할인 상품을 크롤링한다.

        전략:
          1단계: 메인 페이지에서 세일 URL 동적 발견
          2단계: HTTP로 각 세일 페이지 크롤링
          3단계: Playwright fallback
        """
        started_at = datetime.now()
        logger.info("[지오다노] 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        strategy_used = "requests"

        try:
            # 1단계: 메인 페이지에서 세일 URL 동적 발견
            sale_urls = self._discover_sale_urls()
            if not sale_urls:
                logger.info("[지오다노] 메인 페이지에서 세일 URL 발견 실패, 기본 URL 사용")
                sale_urls = list(self.SALE_URLS)
            else:
                logger.info(f"[지오다노] 세일 URL {len(sale_urls)}개 발견")

            # 2단계: HTTP로 세일 페이지 크롤링
            for url in sale_urls:
                try:
                    headers = self._get_headers()
                    resp = requests.get(url, headers=headers, timeout=30)
                    resp.encoding = "utf-8"

                    if resp.status_code != 200:
                        logger.warning(f"[지오다노] HTTP {resp.status_code}: {url}")
                        errors.append(f"HTTP {resp.status_code}: {url}")
                        continue

                    items = await self.parse(resp.text)
                    logger.info(f"[지오다노] {url}: {len(items)}개 수집")
                    all_items.extend(items)

                except Exception as e:
                    logger.warning(f"[지오다노] 요청 실패 ({url}): {e}")
                    errors.append(f"{url}: {e}")

            # 3단계: HTTP 실패 시 Playwright fallback
            if not all_items:
                logger.info("[지오다노] HTTP 실패, Playwright 렌더링 시도")
                pw_items = await self._fetch_via_playwright(sale_urls)
                if pw_items:
                    all_items.extend(pw_items)
                    strategy_used = "playwright"
                else:
                    errors.append("Playwright 렌더링도 실패")

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.PARTIAL
            logger.info(
                f"[지오다노] 크롤링 완료: {len(valid_items)}개, "
                f"{duration:.2f}초, 전략={strategy_used}"
            )

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
            logger.error(f"[지오다노] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    # ------------------------------------------------------------------
    # 세일 URL 동적 발견
    # ------------------------------------------------------------------

    def _discover_sale_urls(self) -> list[str]:
        """메인 페이지에서 세일 키워드가 포함된 big_section.php URL을 발견한다."""
        try:
            headers = self._get_headers()
            resp = requests.get(self.BASE_URL, headers=headers, timeout=15)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                return []

            urls: list[str] = []
            seen: set[str] = set()

            # <a href="...big_section.php?cno1=XXX" ...> 주변 텍스트에서 세일 키워드 탐색
            for m in re.finditer(
                r'<a[^>]*href=["\']([^"\']*big_section\.php\?cno1=\d+)["\'][^>]*>'
                r'(.*?)</a>',
                resp.text,
                re.DOTALL | re.IGNORECASE,
            ):
                href_raw = m.group(1)
                anchor_text = re.sub(r"<[^>]+>", "", m.group(2))  # strip inner HTML tags

                full = (
                    href_raw if href_raw.startswith("http")
                    else urljoin(self.BASE_URL, href_raw)
                )
                # m.giordano.co.kr 링크는 제외
                if "//m." in full:
                    continue
                if full in seen:
                    continue

                if _SALE_KEYWORDS.search(anchor_text):
                    seen.add(full)
                    urls.append(full)

            # 기본 SALE_URLS도 포함
            for u in self.SALE_URLS:
                if u not in seen:
                    seen.add(u)
                    urls.append(u)

            return urls[: self.MAX_SALE_URLS]
        except Exception as e:
            logger.warning(f"[지오다노] 메인 페이지 세일 URL 발견 실패: {e}")
            return []

    # ------------------------------------------------------------------
    # Playwright 렌더링 fallback
    # ------------------------------------------------------------------

    async def _fetch_via_playwright(
        self, sale_urls: list[str] | None = None,
    ) -> list[DiscountItem]:
        """Playwright로 세일 페이지를 렌더링하여 상품 데이터를 추출한다."""
        items: list[DiscountItem] = []
        urls = sale_urls or list(self.SALE_URLS)

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                for url in urls:
                    try:
                        html = await helper.get_rendered_html(
                            url,
                            wait_selector="li.each_prd_box, .info .price",
                            wait_timeout=30000,
                            scroll_to_bottom=True,
                        )

                        page_items = await self.parse(html)
                        logger.info(f"[지오다노] Playwright {url}: {len(page_items)}개")
                        items.extend(page_items)

                    except Exception as e:
                        logger.warning(f"[지오다노] 페이지 렌더링 실패 ({url}): {e}")
                        continue

                logger.info(f"[지오다노] Playwright 총: {len(items)}개")

        except ImportError:
            logger.warning(
                "[지오다노] playwright 미설치 — "
                "pip install playwright && playwright install chromium"
            )
        except Exception as e:
            logger.warning(f"[지오다노] Playwright 크롤링 실패: {e}")

        return items

    # ------------------------------------------------------------------
    # 헤더
    # ------------------------------------------------------------------

    def _get_headers(self) -> dict:
        """지오다노 요청용 헤더."""
        base_headers = self._anti_detect.get_random_headers()
        base_headers.update({
            "Referer": "https://www.giordano.co.kr/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return base_headers

    # ------------------------------------------------------------------
    # 파싱
    # ------------------------------------------------------------------

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다.

        지오다노 세일 페이지 구조:
          li.each_prd_box > div.box > div.info > p.name (상품명)
                                               > div.price > span.consumer (원가)
                                                            > span.sell (할인가)
        """
        items: list[DiscountItem] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")

            # 1차: li.each_prd_box 컨테이너 기반 파싱
            items = self._parse_product_boxes(soup)

            # 2차: 범용 .info + .price fallback
            if not items:
                items = self._parse_info_price_fallback(soup)

        except Exception as e:
            logger.warning(f"[지오다노] 파싱 실패: {e}")

        return items

    def _parse_product_boxes(self, soup) -> list[DiscountItem]:
        """li.each_prd_box 컨테이너에서 상품 정보를 추출한다."""
        items: list[DiscountItem] = []
        boxes = soup.select("li.each_prd_box")

        if not boxes:
            return items

        logger.info(f"[지오다노] each_prd_box: {len(boxes)}개")

        for box in boxes:
            item = self._parse_single_box(box)
            if item:
                items.append(item)

        return items

    def _parse_single_box(self, box) -> Optional[DiscountItem]:
        """개별 li.each_prd_box → DiscountItem."""
        # 상품명: p.name
        name_el = box.select_one("p.name")
        if not name_el:
            name_el = box.select_one(".info .name, .info a")
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        # 가격: span.consumer (원가), span.sell (할인가), span.sale_prc (할인율)
        price_div = box.select_one(".price")
        if not price_div:
            return None

        original_price = self._extract_span_price(
            price_div.select_one("span.consumer")
        )
        sale_price = self._extract_span_price(
            price_div.select_one("span.sell")
        )

        # 할인율
        discount_pct: Optional[float] = None
        pct_el = price_div.select_one("span.sale_prc")
        if pct_el:
            pct_text = pct_el.get_text(strip=True)
            pct_match = re.search(r"(\d+)\s*%", pct_text)
            if pct_match:
                discount_pct = float(pct_match.group(1))

        # span 셀렉터 실패 시 텍스트 기반 fallback
        if not sale_price:
            price_text = price_div.get_text("\n", strip=True)
            original_price, discount_pct, sale_price = self._parse_price_text(
                price_text
            )

        if not sale_price or sale_price <= 0:
            return None

        # 할인율 계산 (텍스트에 없는 경우)
        if (
            not discount_pct
            and original_price
            and sale_price
            and original_price > sale_price
        ):
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 이미지
        image_url = ""
        img_el = box.select_one("img")
        if img_el:
            image_url = (
                img_el.get("src")
                or img_el.get("data-src")
                or img_el.get("data-original", "")
            )
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.BASE_URL, image_url)

        # 상세 URL
        detail_url = ""
        link_el = box.select_one("a[href*='detail.php'], a[href*='shop/']")
        if not link_el:
            link_el = box.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            if href and href != "#":
                detail_url = (
                    href if href.startswith("http")
                    else urljoin(self.BASE_URL, href)
                )

        return DiscountItem(
            name=name,
            store="지오다노",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category="패션",
            event_name="지오다노 세일",
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_info_price_fallback(self, soup) -> list[DiscountItem]:
        """범용 .info + .price fallback: 컨테이너 기반 or 인덱스 매칭."""
        items: list[DiscountItem] = []

        # 방법 1: 컨테이너 안에서 p.name + .price 찾기
        containers = soup.select("li, div.box, div.item")
        for container in containers:
            name_el = container.select_one("p.name, .name, [class*='name']")
            price_el = container.select_one(".price")
            if not name_el or not price_el:
                continue

            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            price_text = price_el.get_text("\n", strip=True)
            original_price, discount_pct, sale_price = self._parse_price_text(
                price_text
            )
            if not sale_price or sale_price <= 0:
                continue

            image_url = ""
            img_el = container.select_one("img")
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src", "")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.BASE_URL, image_url)

            detail_url = ""
            link_el = container.select_one("a[href]")
            if link_el:
                href = link_el.get("href", "")
                if href and href != "#":
                    detail_url = (
                        href if href.startswith("http")
                        else urljoin(self.BASE_URL, href)
                    )

            items.append(DiscountItem(
                name=name,
                store="지오다노",
                original_price=original_price,
                sale_price=sale_price,
                discount_percent=discount_pct,
                category="패션",
                event_name="지오다노 세일",
                image_url=image_url,
                detail_url=detail_url,
            ))

        if items:
            logger.info(f"[지오다노] fallback 컨테이너 파싱: {len(items)}개")

        return items

    # ------------------------------------------------------------------
    # 가격 유틸리티
    # ------------------------------------------------------------------

    def _extract_span_price(self, el) -> Optional[int]:
        """span 요소에서 가격 추출 (예: '19,800원' → 19800)."""
        if not el:
            return None
        text = el.get_text(strip=True)
        m = re.search(r"(\d{1,3}(?:,\d{3})+)", text)
        if m:
            return int(m.group(1).replace(",", ""))
        m = re.search(r"(\d{3,})", text)
        if m:
            return int(m.group(1))
        return None

    def _parse_price_text(
        self, text: str,
    ) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """가격 텍스트 파싱.

        형식: "19,800원\\n20%\\n15,800원"
        반환: (original_price, discount_percent, sale_price)
        """
        prices: list[int] = []
        for m in re.finditer(r"(\d{1,3}(?:,\d{3})+)\s*원?", text):
            prices.append(int(m.group(1).replace(",", "")))

        discount_pct: Optional[float] = None
        pct_match = re.search(r"(\d+)\s*%", text)
        if pct_match:
            discount_pct = float(pct_match.group(1))

        original_price: Optional[int] = None
        sale_price: Optional[int] = None

        if len(prices) >= 2:
            original_price = prices[0]
            sale_price = prices[-1]
        elif len(prices) == 1:
            sale_price = prices[0]

        # original > sale 보장
        if original_price and sale_price and original_price < sale_price:
            original_price, sale_price = sale_price, original_price

        # 할인율 계산
        if (
            not discount_pct
            and original_price
            and sale_price
            and original_price > sale_price
        ):
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        return original_price, discount_pct, sale_price

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        """유효한 할인 상품만 필터링."""
        valid = []
        seen: set[str] = set()

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
