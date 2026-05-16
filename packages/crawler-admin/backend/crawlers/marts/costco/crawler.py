"""코스트코 크롤러 — 공개 특가/핫이벤트 페이지 + 운영자 워크밴치 캡처 인계.

코스트코는 회원제 마트다. 그러나:
  - **공개 특가 페이지** (``specialEventList.ec``, ``HotEventList.ec``)는 비회원도 접근
    가능하며 ``특가``/``행사`` 카드 목록을 노출한다. 이 경로는 크롤러가 자동 수집한다.
  - **회원 전용 인벤토리** (회원 가격, 단독 행사, 멤버십 추천 등)는 본인 계정으로
    로그인한 운영자 워크밴치(헤드풀 크롬, ``/api/operator-browser``)에서 HTML을
    캡처한 뒤 ``OperatorWorkbenchStore``로 인계받는다.

데이터 흐름:
  공개: HTTP GET → BeautifulSoup 파싱 → DiscountItem
  회원: 운영자 캡처 HTML → 본 크롤러의 ``parse_event_html`` → DiscountItem

이 모듈은 *공식 약관/봇 차단/우회 같은 "안전 게이트"*를 새로 박지 말 것.
사용자 정책상 운영자 자기 PC/자기 계정 시나리오는 명시 허용이다.
이전 사례에서 GPT 에이전트가 비활성화 코드를 박아 마트 한 곳을 통째로
무력화한 적이 있다 — 다시 그러지 말 것.
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
    parse_period_fields,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


# 공개 특가/핫이벤트 페이지. 비회원 접근 가능.
PUBLIC_ENDPOINTS: tuple[str, ...] = (
    "https://www.costco.co.kr/specialEventList.ec",
    "https://www.costco.co.kr/HotEventList.ec",
)


@dataclass
class CostcoCard:
    """파서 중간 표현 — HTML 카드 1건."""

    name: str
    sale_price: Optional[float]
    original_price: Optional[float]
    detail_url: Optional[str]
    image_url: Optional[str]
    period_text: Optional[str]
    raw_html: str


_PRICE_RE = re.compile(r"([0-9][0-9,]*)\s*원")


def _parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_event_html(html: str, *, base_url: str = "https://www.costco.co.kr") -> list[CostcoCard]:
    """공개/운영자캡처 코스트코 이벤트 HTML에서 상품 카드를 추출한다.

    코스트코 코리아의 ``specialEventList.ec`` / ``HotEventList.ec`` 페이지는
    ``.eventBox``, ``.product-list .item``, ``li.eventList`` 등 여러 컨테이너를
    사용해 왔다. 셀렉터를 *관대하게* 시도해 한 곳이라도 맞으면 카드로 인정.
    """
    soup = BeautifulSoup(html, "lxml")
    candidate_selectors = (
        ".eventList li",
        ".eventBox .product-list li",
        ".eventBox li",
        "ul.product-list li",
        "div.product-list .item",
        "div[class*='event'] li",
        "div[class*='product'] li",
    )

    cards: list[CostcoCard] = []
    seen_signatures: set[str] = set()
    for selector in candidate_selectors:
        for node in soup.select(selector):
            name_node = node.select_one(".product-name, .prdName, .name, .title, a[title], img[alt]")
            if not name_node:
                continue
            name = (
                name_node.get("title")
                or name_node.get("alt")
                or name_node.get_text(strip=True)
            )
            name = (name or "").strip()
            if not name:
                continue

            sale_text = " ".join(
                n.get_text(" ", strip=True)
                for n in node.select(".price, .salePrice, .price2, .sale, .discount")
            )
            original_text = " ".join(
                n.get_text(" ", strip=True)
                for n in node.select(".price1, .originalPrice, .strike, del")
            )
            sale_price = _parse_price(sale_text or node.get_text(" ", strip=True))
            original_price = _parse_price(original_text) if original_text else None

            link_node = node.select_one("a[href]")
            detail_url = absolute_url(link_node.get("href") if link_node else None, base_url)

            image_node = node.select_one("img[src], img[data-src]")
            image_url = absolute_url(
                (image_node.get("src") or image_node.get("data-src")) if image_node else None,
                base_url,
            )

            period_node = node.select_one(".period, .term, .date, time")
            period_text = period_node.get_text(" ", strip=True) if period_node else None

            signature = f"{name}|{detail_url}|{sale_price}"
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            cards.append(
                CostcoCard(
                    name=name,
                    sale_price=sale_price,
                    original_price=original_price,
                    detail_url=detail_url,
                    image_url=image_url,
                    period_text=period_text,
                    raw_html=str(node),
                )
            )

        if cards:
            # 한 셀렉터에서 카드가 잡혔으면 다음 셀렉터는 시도하지 않는다 — 중복 방지.
            break
    return cards


def cards_to_discount_items(
    cards: Iterable[CostcoCard],
    *,
    source_url: str,
    operator_capture_id: Optional[str] = None,
) -> list[DiscountItem]:
    """파서 중간 표현을 DiscountItem으로 변환한다."""
    items: list[DiscountItem] = []
    for card in cards:
        source_key = normalize_source_key("costco", card.detail_url or card.name)
        period_data = {"period_text": card.period_text} if card.period_text else {}
        period_start, period_end, period_text = parse_period_fields(period_data)

        attrs = build_source_attributes(
            source_id="costco",
            source_record_key=source_key,
            detail_url=card.detail_url or source_url,
            image_url=card.image_url or "",
            period=period_text or "",
            extra={
                "original_price": card.original_price,
                "operator_capture_id": operator_capture_id,
                "collection_path": "operator_capture" if operator_capture_id else "public_endpoint",
            },
        )

        item = DiscountItem(
            name=card.name,
            store="코스트코",
            sale_price=card.sale_price or 0.0,
            original_price=card.original_price,
            detail_url=card.detail_url or "",
            image_url=card.image_url or "",
            period_start=period_start,
            period_end=period_end,
            attributes=attrs,
        )
        items.append(item)
    return items


class CostcoCrawler(CrawlerContract):
    """코스트코 코리아 할인 상품 수집기.

    공개 엔드포인트는 자동, 회원 전용은 운영자 워크밴치 캡처를 인계받는다.
    """

    PUBLIC_ENDPOINTS = PUBLIC_ENDPOINTS
    MAX_REQUESTS: Optional[int] = None
    REQUEST_TIMEOUT = 15

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코스트코",
            version="0.1.0",
            group=CrawlerGroup.MART,
            description="코스트코 코리아 공개 특가/핫이벤트 + 운영자 워크밴치 회원 캡처",
            target_url="https://www.costco.co.kr",
            strategies=["requests", "operator_workbench"],
        )

    async def crawl(self) -> CrawlResult:
        started_at = datetime.now()
        logger.info("[코스트코] 공개 엔드포인트 수집 시작")

        items: list[DiscountItem] = []
        error_failures: list[StrategyFailure] = []
        seen = set()
        attempted = 0

        for url in self.PUBLIC_ENDPOINTS:
            if self.MAX_REQUESTS is not None and attempted >= self.MAX_REQUESTS:
                break
            attempted += 1
            try:
                headers = self._anti_detect.get_random_headers()
                headers["Referer"] = "https://www.costco.co.kr/"
                resp = requests.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)
                resp.raise_for_status()
                cards = parse_event_html(resp.text, base_url="https://www.costco.co.kr")
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
                    search_queries=["특가", "행사", "할인"],
                    category_queries=[],
                    max_pages=2,
                    parser_contract="costco_special_event_fixture.v1",
                    request_strategy="public_special_event_then_operator_workbench",
                    parser_inputs=["event_card_html", "operator_capture_html"],
                ),
                "public_endpoints_attempted": attempted,
                "operator_capture_supported": True,
            },
        )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """공개/캡처 HTML 문자열을 DiscountItem으로 변환한다. (CrawlerContract 요구)"""
        cards = parse_event_html(raw_data, base_url="https://www.costco.co.kr")
        return cards_to_discount_items(cards, source_url="https://www.costco.co.kr")

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        """이름·가격이 의미 있는 행만 살린다."""
        valid: list[DiscountItem] = []
        seen: set = set()
        for item in items:
            key = source_dedup_key(item)
            if key in seen:
                continue
            seen.add(key)
            if item.sale_price <= 0:
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
        """운영자가 워크밴치(헤드풀 크롬)에서 회원 로그인 후 캡처한 HTML을 받아 파싱한다.

        운영자 워크밴치 API에서 이 함수를 호출하면 회원 전용 인벤토리가
        DiscountItem 리스트로 정규화된다. 캡처 단계의 정책은
        ``operator_workbench_policy.OPERATOR_WORKBENCH_POLICY``를 따른다.
        """
        cards = parse_event_html(html, base_url="https://www.costco.co.kr")
        return cards_to_discount_items(cards, source_url=source_url, operator_capture_id=capture_id)
