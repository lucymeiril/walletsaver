"""
클리앙 알뜰구매 크롤러.

https://www.clien.net/service/board/jirum 에서 핫딜 게시글을 수집한다.
클리앙은 IT/기술 중심 커뮤니티로, 알뜰구매(지름) 게시판이 활발하다.
비교적 깨끗한 HTML 구조를 가지고 있어 파싱이 용이하다.

데이터 구조 (2026 기준):
  <div class="list_item symph_row" data-board-sn="...">
    <div class="list_title">
      <a class="list_subject" href="/service/board/jirum/...">
        <span class="subject_fixed">제목</span>
      </a>
      <span class="reply_symph">댓글수</span>
    </div>
    <div class="list_author">...</div>
    <span class="hit">조회수</span>
    <span class="timestamp">시간</span>
  </div>

용도: 핫딜 참고 데이터 (baseline 오염 방지 — HotdealPost로 저장)
의존: core/ 만
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class ClienCrawler(CrawlerContract):
    """클리앙 알뜰구매 크롤러 — IT/기술 중심 커뮤니티 핫딜."""

    BASE_URL = "https://www.clien.net"
    DEAL_URL = "https://www.clien.net/service/board/jirum"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=2.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="클리앙",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="클리앙 알뜰구매 게시판 크롤러 — IT/기술 중심 커뮤니티",
            target_url=self.DEAL_URL,
            strategies=["requests"],
        )

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout)
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
        """클리앙 알뜰구매 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[클리앙] 크롤링 시작: {self.DEAL_URL}")

        try:
            headers = self._anti_detect.get_random_headers()
            response = self._retry_request(self.DEAL_URL, headers=headers, timeout=15)
            response.encoding = "utf-8"

            if response.status_code != 200:
                logger.error(f"[클리앙] HTTP {response.status_code}")
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
            logger.info(f"[클리앙] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

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
            logger.error(f"[클리앙] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 알뜰구매 게시글을 파싱한다.

        클리앙은 div.list_item 기반의 깨끗한 구조를 사용한다.
        각 항목에서 제목·링크·가격·조회수·댓글수를 추출한다.
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 게시글 항목 선택
        rows = soup.select("div.list_item.symph_row")
        if not rows:
            # 폴백: 범용 list_item 선택
            rows = soup.select("div.list_item")

        logger.info(f"[클리앙] 게시글 항목: {len(rows)}개")

        for row in rows:
            try:
                item = self._parse_item(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[클리앙] 항목 파싱 오류: {e}")
                continue

        del soup  # Free DOM tree memory
        return items

    def _parse_item(self, row) -> Optional[HotdealPost]:
        """개별 게시글 항목을 파싱한다."""

        # 공지 스킵
        if row.get("class") and "notice" in " ".join(row.get("class", [])):
            return None

        # 1) 제목 + URL 추출
        title_el = row.select_one("a.list_subject")
        if not title_el:
            title_el = row.select_one("a[href*='/service/board/jirum/']")
        if not title_el:
            return None

        # 제목 텍스트 — subject_fixed 스팬이 있으면 사용
        subject_span = title_el.select_one("span.subject_fixed")
        title = (subject_span or title_el).get_text(strip=True)
        if not title or len(title) < 3:
            return None

        # 광고/공지 스킵
        if self._is_ad(row, title):
            return None

        href = title_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        # 2) 가격 추출 — 제목 또는 행 전체 텍스트에서
        price_evidence = title
        price = self._extract_price(title)
        if price is None:
            price_evidence = row.get_text(" ", strip=True)
            price = self._extract_price(price_evidence)

        # 3) 카테고리 추출 — 제목 앞 [카테고리] 패턴
        category = ""
        cat_match = re.match(r"\[([^\]]+)\]", title)
        if cat_match:
            category = cat_match.group(1)

        image_el = row.select_one("img[src], img[data-src]")
        date_el = row.select_one(".timestamp, time")

        return HotdealPost(
            title=title,
            url=url,
            source_community="클리앙",
            price=price,
            price_evidence=price_evidence if price is not None else "",
            category=category,
            category_hints=[hint for hint in (category,) if hint],
            image_url=urljoin(self.BASE_URL, image_el.get("src") or image_el.get("data-src")) if image_el else "",
            period=date_el.get_text(" ", strip=True) if date_el else "",
        )

    def _is_ad(self, row, title: str) -> bool:
        """광고/공지 게시글 여부를 판단한다."""
        if "[공지]" in title or "[AD]" in title or "[광고]" in title:
            return True

        row_classes = " ".join(row.get("class", []))
        if "notice" in row_classes or "ad" in row_classes:
            return True

        return False

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 최초 가격(원)을 추출한다."""
        if not text:
            return None

        if "무료" in text and "배송" not in text:
            return 0

        patterns = [
            r"(\d{1,3}(?:,\d{3})+)\s*원",
            r"(\d{3,})\s*원",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    async def validate(self, items: list[HotdealPost]) -> list[HotdealPost]:
        """유효한 핫딜만 필터링한다."""
        valid = []
        seen_urls: set[str] = set()

        for item in items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)

            if len(item.title) < 3:
                continue

            valid.append(item)

        return valid
