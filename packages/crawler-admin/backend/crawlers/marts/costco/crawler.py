"""코스트코 크롤러 — 실제 라이브 DOM(Angular SSR storefront) 기반 파서.

## 어떻게 결정됐나 (TDD 기록)
2026-05-16 라이브 캡처:
  - `https://www.costco.co.kr/Special-Price-Offers/c/SpecialPriceOffers` (200 OK, 2.7MB)
  - 상품 카드: `li.product-list-item` (1페이지 ~48~158개)
  - 상품 링크/이름: `a.thumb` 의 `title` 속성 + `href="/.../p/{id}"`
  - 가격: `.product-price-amount` (예: "35,990원")
  - 단위가: `.product-price-pre-unit-amount` (예: "100㎖당 3,099원")
  - 회원 전용 가격은 `.price-panel-login` 텍스트가 "회원 전용 아이템" — 비회원 GET 응답에서도 *상품 자체와 정가는* 보인다.

이전 추정 URL(`specialEventList.ec`)은 **404**라는 사실이 라이브 테스트로 드러났다.
TDD 위반에 대한 사용자 피드백(2026-05-16)에 따라 fixture 기반으로 재작성됨.

## 회원/비회원 차이 (실제로 확인된 것)
비회원도 상품 목록·상품명·이미지·정가·단위가는 그대로 본다. 차이는 *일부* 상품의
세일가가 "회원 전용 아이템" 문구로 숨는 것뿐이다. 따라서 별도 회원 워크밴치 캡처
경로는 **선택적**이며, 라이브 백엔드에 우회 코드는 박지 않는다(운영자 정책 준수).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerGroup,
    CrawlerInfo,
    CrawlResult,
    CrawlStatus,
    DiscountItem,
    ErrorType,
    StrategyFailure,
)
from crawlers.marts.source_utils import (
    absolute_url,
    build_source_attributes,
    build_source_map_manifest,
    normalize_source_key,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


BASE_URL = "https://www.costco.co.kr"

# 라이브에서 200 OK로 검증된 카탈로그 페이지들 (2026-05-16).
# 새 페이지를 추가할 때는 반드시 fixture 캡처 후 셀렉터 동치성 확인 — 추정 금지.
PUBLIC_ENDPOINTS: tuple[str, ...] = (
    f"{BASE_URL}/Special-Price-Offers/c/SpecialPriceOffers",
    f"{BASE_URL}/events",
    f"{BASE_URL}/",
)


_WON_RE = re.compile(r"([0-9][0-9,]*)\s*원")


@dataclass
class CostcoCard:
    """fixture·라이브 응답 모두에서 사용되는 중간 표현."""

    name: str
    sale_price: Optional[float]
    original_price: Optional[float]
    unit_price_text: Optional[str]
    detail_url: Optional[str]
    image_url: Optional[str]
    is_member_only: bool
    raw_html: str


def _parse_won(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = _WON_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_costco_listing(html: str) -> list[CostcoCard]:
    """코스트코 카탈로그 HTML(공개 SSR 응답)에서 상품 카드를 추출한다.

    셀렉터는 ``tests/fixtures/costco/special_offers_5cards.html``로 회귀 보장된다.
    """
    soup = BeautifulSoup(html, "lxml")
    cards: list[CostcoCard] = []
    for li in soup.select("li.product-list-item"):
        thumb = li.select_one("a.thumb[href]")
        if not thumb:
            continue
        href = thumb.get("href") or ""
        if "/p/" not in href:
            continue
        name = (thumb.get("title") or "").strip()
        if not name:
            img = li.select_one("img[title], img[alt]")
            if img:
                name = (img.get("title") or img.get("alt") or "").strip()
        if not name:
            continue

        sale_node = li.select_one(".product-price-amount")
        original_node = li.select_one(".original-price")
        unit_node = li.select_one(".product-price-pre-unit-amount")
        member_only = bool(li.select_one(".price-panel-login"))

        sale_price = _parse_won(sale_node.get_text(" ", strip=True) if sale_node else None)
        original_price = _parse_won(original_node.get_text(" ", strip=True) if original_node else None)
        # original-price만 있고 product-price-amount가 없으면 그게 표시가
        if sale_price is None and original_price is not None:
            sale_price = original_price
            original_price = None

        image_url = ""
        img = li.select_one(".product-image img[src], .product-image img[srcset], picture source[srcset]")
        if img:
            image_url = img.get("src") or (img.get("srcset") or "").split()[0] or ""

        cards.append(
            CostcoCard(
                name=name,
                sale_price=sale_price,
                original_price=original_price,
                unit_price_text=unit_node.get_text(" ", strip=True) if unit_node else None,
                detail_url=absolute_url(href, BASE_URL),
                image_url=absolute_url(image_url, BASE_URL),
                is_member_only=member_only,
                raw_html=str(li),
            )
        )
    return cards


def cards_to_discount_items(
    cards: Iterable[CostcoCard],
    *,
    source_url: str,
    operator_capture_id: Optional[str] = None,
) -> list[DiscountItem]:
    """파서 중간 표현 → DiscountItem.

    회원 전용 가격 미공개 카드는 sale_price=0으로 들어가며 validate()에서 걸러진다.
    """
    items: list[DiscountItem] = []
    for card in cards:
        source_key = normalize_source_key("costco", card.detail_url or card.name)
        attrs = build_source_attributes(
            source_id="costco",
            source_record_key=source_key,
            detail_url=card.detail_url or source_url,
            image_url=card.image_url or "",
            extra={
                "original_price": card.original_price,
                "unit_price_text": card.unit_price_text,
                "is_member_only": card.is_member_only,
                "operator_capture_id": operator_capture_id,
                "collection_path": "operator_capture" if operator_capture_id else "public_endpoint",
            },
        )
        items.append(
            DiscountItem(
                name=card.name,
                store="코스트코",
                sale_price=card.sale_price or 0.0,
                original_price=card.original_price,
                detail_url=card.detail_url or "",
                image_url=card.image_url or "",
                attributes=attrs,
            )
        )
    return items


class CostcoCrawler(CrawlerContract):
    """코스트코 코리아 카탈로그 수집기. fixture 기반 셀렉터, 실제 라이브 URL 사용."""

    PUBLIC_ENDPOINTS = PUBLIC_ENDPOINTS
    MAX_REQUESTS: Optional[int] = None
    REQUEST_TIMEOUT = 20

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코스트코",
            version="0.2.0",
            group=CrawlerGroup.MART,
            description="코스트코 코리아 공개 카탈로그(스페셜 할인/이벤트/홈) + 운영자 워크밴치 옵션",
            target_url=BASE_URL,
            strategies=["requests", "operator_workbench"],
        )

    async def crawl(self) -> CrawlResult:
        started_at = datetime.now()
        items: list[DiscountItem] = []
        error_failures: list[StrategyFailure] = []
        seen: set = set()
        attempted = 0

        for url in self.PUBLIC_ENDPOINTS:
            if self.MAX_REQUESTS is not None and attempted >= self.MAX_REQUESTS:
                break
            attempted += 1
            try:
                headers = self._anti_detect.get_random_headers()
                headers["Referer"] = f"{BASE_URL}/"
                resp = requests.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)
                resp.raise_for_status()
                cards = parse_costco_listing(resp.text)
                for di in cards_to_discount_items(cards, source_url=url):
                    key = source_dedup_key(di)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(di)
            except requests.RequestException as e:
                error_failures.append(
                    StrategyFailure(
                        strategy_name="requests",
                        error_type=ErrorType.HTTP_ERROR,
                        error_msg=f"{url}: {e}",
                    )
                )

        status = CrawlStatus.SUCCESS if items else (CrawlStatus.PARTIAL if error_failures else CrawlStatus.FAILED)

        return CrawlResult(
            crawler_name=self.info.name,
            status=status,
            items=[item.model_dump(mode="json") for item in items],
            items_count=len(items),
            errors=error_failures,
            started_at=started_at,
            finished_at=datetime.now(),
            quality_details={
                "source_map": build_source_map_manifest(
                    source_id="costco",
                    search_queries=["스페셜할인", "이벤트"],
                    category_queries=[],
                    max_pages=1,
                    parser_contract="costco_storefront_li_product_list_item.v1",
                    request_strategy="public_storefront_ssr",
                    parser_inputs=["li.product-list-item", "a.thumb[title]", ".product-price-amount"],
                ),
                "public_endpoints_attempted": attempted,
                "operator_capture_supported": True,
            },
        )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        cards = parse_costco_listing(raw_data)
        return cards_to_discount_items(cards, source_url=BASE_URL)

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid: list[DiscountItem] = []
        seen: set = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen:
                continue
            seen.add(key)
            if item.sale_price <= 0:
                # 회원 전용 가격 미공개 카드 등 — 가격 데이터 없으면 드롭
                continue
            if len(item.name) < 2:
                continue
            valid.append(item)
        return valid

    def ingest_operator_capture(
        self,
        html: str,
        *,
        source_url: str,
        capture_id: Optional[str] = None,
    ) -> list[DiscountItem]:
        """운영자가 워크밴치(헤드풀 크롬)에서 본인 계정으로 캡처한 HTML 인계."""
        cards = parse_costco_listing(html)
        return cards_to_discount_items(cards, source_url=source_url, operator_capture_id=capture_id)
