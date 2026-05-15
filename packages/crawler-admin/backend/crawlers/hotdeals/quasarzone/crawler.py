"""
퀘이사존 핫딜 크롤러.

https://quasarzone.com/bbs/qb_saleinfo 에서 핫딜 게시글을 수집한다.
퀘이사존은 PC/하드웨어 중심 커뮤니티로, 핫딜(세일정보) 게시판이 활발하다.
비교적 봇 방어가 약해 일반 requests로 수집 가능하다.

데이터 구조 (2026 기준):
  <div class="market-info-list">
    <div class="market-info-list-cont">
      <div class="market-info-sub">
        <p class="tit">
          <a href="/bbs/qb_saleinfo/views/...">
            <span class="ellipsis-with-reply-cnt">
              <span class="deal-condition"><span>진행중</span></span>
              <span class="text">제목</span>
            </span>
          </a>
        </p>
        <p class="market-info-sub-txt">
          카테고리  가격 ￦ 59,000 (KRW)  배송비 무료
        </p>
      </div>
    </div>
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
from crawlers.hotdeals.common import HotdealCollectorMixin, apply_source_facts, dedupe_hotdeal_posts

logger = logging.getLogger(__name__)


class QuasarzoneCrawler(HotdealCollectorMixin, CrawlerContract):
    """퀘이사존 핫딜 크롤러 — PC/하드웨어 중심 커뮤니티."""

    BASE_URL = "https://quasarzone.com"
    SOURCE_ID = "quasarzone"
    PAGE_ENCODING = "utf-8"
    DEAL_URL = "https://quasarzone.com/bbs/qb_saleinfo"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=1.5)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="퀘이사존",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="퀘이사존 핫딜 게시판 크롤러 — PC/하드웨어 중심 커뮤니티",
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
        """퀘이사존 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[퀘이사존] 크롤링 시작: {self.DEAL_URL}")

        try:
            headers = self._anti_detect.get_random_headers()
            headers["Referer"] = "https://quasarzone.com/"
            response = self._retry_request(self.DEAL_URL, headers=headers, timeout=15)
            response.encoding = "utf-8"

            if response.status_code != 200:
                logger.error(f"[퀘이사존] HTTP {response.status_code}")
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
            logger.info(f"[퀘이사존] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

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
            logger.error(f"[퀘이사존] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다.

        퀘이사존 핫딜은 market-info-list 기반 구조이다.
        각 항목에서 제목·링크·가격·카테고리를 추출한다.
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 게시글 컨테이너 선택
        rows = soup.select("div.market-info-list-cont")
        if not rows:
            # 폴백: 제목 링크 기반 탐색
            rows = soup.select("div.market-info-sub")
        logger.info(f"[퀘이사존] 게시글 항목: {len(rows)}개")

        for row in rows:
            try:
                item = self._parse_item(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[퀘이사존] 항목 파싱 오류: {e}")
                continue

        del soup  # Free DOM tree memory
        return items

    def _parse_item(self, row) -> Optional[HotdealPost]:
        """개별 핫딜 항목을 파싱한다."""

        # 1) 제목 + URL 추출
        title_el = row.select_one("p.tit a") or row.select_one("a[href*='/bbs/qb_saleinfo/views/']")
        if not title_el:
            return None

        # 제목 텍스트 — span.text 우선, 없으면 a 전체
        text_span = title_el.select_one("span.text")
        title = (text_span or title_el).get_text(strip=True)
        if not title or len(title) < 3:
            return None

        # 종료/품절 게시글도 포함하되 상태 표시
        status_el = title_el.select_one("span.deal-condition span")
        if status_el:
            status_text = status_el.get_text(strip=True)
            # 제목에서 상태 텍스트 제거
            title = title.replace(status_text, "").strip()

        href = title_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        # 2) 가격 + 카테고리 추출 — market-info-sub-txt 텍스트에서
        price = None
        category = ""
        price_evidence = ""
        sub_txt_el = row.select_one("p.market-info-sub-txt")
        if sub_txt_el:
            sub_text = sub_txt_el.get_text(" ", strip=True)
            price_evidence = sub_text
            price = self._extract_price(sub_text)

            # 카테고리 — 첫 번째 텍스트 조각 (가격 전)
            cat_match = re.match(r"^([^\d￦$]+?)(?:\s*가격|\s*￦)", sub_text)
            if cat_match:
                category = cat_match.group(1).strip()

        # 가격이 없으면 제목에서 추출 시도
        if price is None:
            price_evidence = title
            price = self._extract_price(title)

        image_el = row.select_one("img[src], img[data-src]")
        date_el = row.select_one("time, .date, .timestamp")

        date_text = date_el.get("datetime") if date_el and date_el.name == "time" else (date_el.get_text(" ", strip=True) if date_el else None)

        return apply_source_facts(HotdealPost(
            title=title,
            url=url,
            source_community="퀘이사존",
            price=price,
            price_evidence=price_evidence if price is not None else "",
            category=category,
            category_hints=[hint for hint in (category,) if hint],
            image_url=urljoin(self.BASE_URL, image_el.get("src") or image_el.get("data-src")) if image_el else "",
            period=date_el.get_text(" ", strip=True) if date_el else "",
        ), source_id=self.SOURCE_ID, source_url=url, post_date_text=date_text)

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 최초 가격(원)을 추출한다."""
        if not text:
            return None

        # 퀘이사존 특유의 "￦ 59,000" 패턴
        won_match = re.search(r"￦\s*([0-9,]+)", text)
        if won_match:
            return int(won_match.group(1).replace(",", ""))

        # 일반 가격 패턴
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)\s*원",
            r"(\d{3,})\s*원",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))

        # "무료" 처리
        if "무료" in text and "배송" not in text:
            return 0

        return None

    async def validate(self, items: list[HotdealPost]) -> list[HotdealPost]:
        """유효한 핫딜만 필터링한다."""
        return dedupe_hotdeal_posts(items)
