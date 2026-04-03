"""
알구몬 핫딜 크롤러.

https://www.algumon.com/n/deal 에서 핫딜 게시글을 수집한다.
알구몬은 Svelte SPA이지만 SSR 렌더링하므로 requests로 HTML 파싱 가능.

데이터 구조 (2026-03 기준):
  <div class="deal-card-content">
    <div class="flex gap-0">
      <div class="avatar">...</div>     ← 아바타 (링크 있음)
      <div class="flex-1 min-w-0 ml-3">
        <소스> | <커뮤니티>                ← 구매처/커뮤니티
        <h3><a href="/l/d/...">제목</a></h3>
        <p class="deal-price-text">가격</p>
        <배송> | <시간> | <작성자>
      </div>
    </div>
  </div>

용도: 핫딜 참고 데이터 (baseline 오염 방지 — HotdealPost로 저장)
의존: core/ 만
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class AlgumonCrawler(CrawlerContract):
    """알구몬 핫딜 크롤러 — 여러 커뮤니티의 핫딜 통합."""

    BASE_URL = "https://www.algumon.com"
    DEAL_URL = "https://www.algumon.com/n/deal"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=1.5)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="알구몬",
            version="2.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="여러 커뮤니티의 핫딜 정보 통합 (뽐뿌, 어미새, 루리웹 등)",
            target_url=self.DEAL_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """알구몬 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[알구몬] 크롤링 시작: {self.DEAL_URL}")

        try:
            headers = self._anti_detect.get_random_headers()
            response = requests.get(self.DEAL_URL, headers=headers, timeout=15)
            response.encoding = "utf-8"

            if response.status_code != 200:
                logger.error(f"[알구몬] HTTP {response.status_code}")
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg=f"HTTP {response.status_code}",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            raw_data = response.text
            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            logger.info(f"[알구몬] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

            return CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name=self.info.name,
                strategy_used="requests",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
            )

        except Exception as e:
            logger.error(f"[알구몬] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다."""
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # deal-card-content 기반 파싱
        cards = soup.select(".deal-card-content")
        logger.info(f"[알구몬] deal-card-content 카드: {len(cards)}개")

        for card in cards:
            try:
                item = self._parse_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[알구몬] 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_card(self, card) -> Optional[HotdealPost]:
        """개별 핫딜 카드를 파싱한다."""

        # 1) 제목 + URL 추출
        title_el = card.select_one("h3 a[href*='/l/d/']")
        if not title_el:
            # fallback: 카드 내 모든 a 태그에서 href 포함하는 것
            title_el = card.select_one("a[href*='/l/d/']")

        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        href = title_el.get("href", "")
        url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        # 2) 가격 추출 — deal-price-text 클래스 또는 가격 패턴
        price = None
        price_el = card.select_one(".deal-price-text, [class*='price']")
        if price_el:
            price_text = price_el.get_text(strip=True)
            price = self._extract_price(price_text)

        # fallback: 카드 전체 텍스트에서 가격 추출
        if price is None:
            card_text = card.get_text(" ", strip=True)
            price = self._extract_price(card_text)

        # 3) 소스 커뮤니티 추출
        source = self._extract_source(card)

        return HotdealPost(
            title=title,
            url=url,
            source_community=source,
            price=price,
        )

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 최초 가격(원)을 추출한다."""
        if not text:
            return None

        # "무료" 처리
        if text.strip() == "무료":
            return 0

        # "15,470원", "50000원" 패턴
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)\s*원",  # 1,000원 이상
            r"(\d{3,})\s*원",                # 100원 이상
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    def _extract_source(self, card) -> str:
        """카드에서 소스 커뮤니티를 추출한다."""
        # deal-card-content의 텍스트에서 첫 "|" 전후로 소스 추출
        # 패턴: "G마켓 | 뽐뿌 | 제목" → 소스 = "뽐뿌"
        known_communities = [
            "뽐뿌", "어미새", "루리웹", "에펨코리아", "퀘이사존",
            "클리앙", "딜바다", "쿨엔조이", "보배드림",
        ]
        card_text = card.get_text(" ", strip=True)

        for community in known_communities:
            if community in card_text:
                return community

        return ""

    async def validate(self, items: list[HotdealPost]) -> list[HotdealPost]:
        """유효한 핫딜만 필터링한다."""
        valid = []
        seen_urls = set()

        for item in items:
            # URL 기반 중복 제거
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)

            # 너무 짧은 제목
            if len(item.title) < 3:
                continue

            valid.append(item)

        return valid
