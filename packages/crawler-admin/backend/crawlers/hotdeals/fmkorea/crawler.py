"""
FM코리아 핫딜 크롤러.

https://www.fmkorea.com/hotdeal 에서 핫딜 게시글을 수집한다.
FM코리아는 대형 커뮤니티로 핫딜 전용 게시판이 활발하다.
일부 응답은 축약될 수 있어 cloudscraper 기반 수집 폴백을 지원한다.

데이터 구조 (2026 기준):
  <li class="li li_best2_pop0 ...">
    <div class="li_inner">
      <h3 class="title">
        <a href="/핫딜번호">제목</a>
      </h3>
      <span class="hotdeal_info">
        쇼핑몰 | 가격 | 배송비 | 추천
      </span>
    </div>
  </li>

  또는 테이블 형태:
  <td class="title hotdeal_var8">
    <a href="...">제목</a>
  </td>

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


class FmkoreaCrawler(CrawlerContract):
    """FM코리아 핫딜 크롤러 — 대형 커뮤니티의 핫딜 게시판."""

    BASE_URL = "https://www.fmkorea.com"
    DEAL_URL = "https://www.fmkorea.com/hotdeal"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="FM코리아",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="FM코리아 핫딜 게시판 크롤러 — 대형 커뮤니티 핫딜 보드",
            target_url=self.DEAL_URL,
            strategies=["requests", "cloudscraper"],
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
        """FM코리아 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[FM코리아] 크롤링 시작: {self.DEAL_URL}")

        try:
            raw_data = self._fetch_with_fallback()
            if raw_data is None:
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg="모든 요청 전략 실패 (requests + cloudscraper)",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            logger.info(f"[FM코리아] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

            return CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name=self.info.name,
                strategy_used="cloudscraper",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
            )

        except Exception as e:
            logger.error(f"[FM코리아] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _fetch_with_fallback(self) -> Optional[str]:
        """cloudscraper → requests 순서로 시도하여 HTML을 가져온다.

        FM코리아는 일반 requests에서 축약된 HTML을 반환할 수 있다.
        cloudscraper를 먼저 시도하고, 실패 시 requests로 폴백한다.
        """
        # 1차: cloudscraper 기반 수집 세션
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            # Retry via session-based backoff (cloudscraper extends requests.Session)
            response = self._retry_request(self.DEAL_URL, session=scraper, timeout=20)
            if response.status_code == 200 and len(response.text) > 5000:
                return response.text
            logger.warning(f"[FM코리아] cloudscraper 응답 부족: HTTP {response.status_code}, len={len(response.text)}")
        except ImportError:
            logger.warning("[FM코리아] cloudscraper 미설치 — pip install cloudscraper")
        except Exception as e:
            logger.warning(f"[FM코리아] cloudscraper 예외: {e}")

        # 2차: 일반 requests 폴백
        try:
            headers = self._anti_detect.get_random_headers()
            response = self._retry_request(self.DEAL_URL, headers=headers, timeout=15)
            if response.status_code == 200 and len(response.text) > 5000:
                return response.text
            logger.warning(f"[FM코리아] requests 응답 부족: HTTP {response.status_code}, len={len(response.text)}")
        except Exception as e:
            logger.warning(f"[FM코리아] requests 예외: {e}")

        return None

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다.

        FM코리아 핫딜 게시판은 li 리스트 또는 테이블 구조를 사용한다.
        두 가지 레이아웃 모두 처리한다.
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 패턴 1: li 기반 레이아웃 (hotdeal_var8 등 클래스)
        list_items = soup.select("li.li_best2_pop0, li.li_best2_pop1, li.li_best2_pop2")
        if not list_items:
            list_items = soup.select("div.fm_best_widget li")

        # 패턴 2: 테이블 기반 레이아웃
        table_rows = soup.select("tr.bg1, tr.bg2") if not list_items else []

        # 패턴 3: hotdeal_var8 제목 td 기반 (새 레이아웃)
        if not list_items and not table_rows:
            table_rows = soup.select("table.bd_lst tr")

        # 패턴 4: 범용 — 핫딜 제목 링크 기반 탐색
        if not list_items and not table_rows:
            list_items = soup.select("li[class*='li']")

        # 패턴 5: div.content_list 내 게시글
        if not list_items and not table_rows:
            list_items = soup.select("div.content_list div.li")

        logger.info(f"[FM코리아] 리스트 항목: {len(list_items)}개, 테이블 행: {len(table_rows)}개")

        for li in list_items:
            try:
                item = self._parse_list_item(li)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[FM코리아] 리스트 파싱 오류: {e}")
                continue

        for tr in table_rows:
            try:
                item = self._parse_table_row(tr)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[FM코리아] 테이블 파싱 오류: {e}")
                continue

        del soup  # Free DOM tree memory
        return items

    def _parse_list_item(self, li) -> Optional[HotdealPost]:
        """리스트(li) 형태의 핫딜 항목을 파싱한다."""

        # 제목 + URL
        title_el = li.select_one("h3.title a") or li.select_one("a.title")
        if not title_el:
            title_el = li.select_one("a[href]")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        href = title_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        # 가격 추출 — hotdeal_info 스팬 또는 전체 텍스트에서
        price = None
        price_evidence = ""
        category = ""
        info_el = li.select_one("span.hotdeal_info, div.hotdeal_info")
        if info_el:
            price_evidence = info_el.get_text(" ", strip=True)
            price = self._extract_price(price_evidence)
            category = price_evidence.split("|", 1)[0].strip()

        if price is None:
            price_evidence = li.get_text(" ", strip=True)
            price = self._extract_price(price_evidence)

        image_el = li.select_one("img[src], img[data-src]")

        # 댓글 수 추출
        comment_el = li.select_one("span.comment_count, a.comment_count")
        comments = 0
        if comment_el:
            cm = re.search(r"(\d+)", comment_el.get_text())
            if cm:
                comments = int(cm.group(1))

        # 추천 수 추출
        vote_el = li.select_one("span.vote_count, div.vote")
        votes = 0
        if vote_el:
            vm = re.search(r"(\d+)", vote_el.get_text())
            if vm:
                votes = int(vm.group(1))

        return HotdealPost(
            title=title,
            url=url,
            source_community="FM코리아",
            price=price,
            price_evidence=price_evidence if price is not None else "",
            category=category,
            category_hints=[hint for hint in (category,) if hint],
            image_url=urljoin(self.BASE_URL, image_el.get("src") or image_el.get("data-src")) if image_el else "",
        )

    def _parse_table_row(self, tr) -> Optional[HotdealPost]:
        """테이블(tr) 형태의 핫딜 행을 파싱한다."""

        title_td = tr.select_one("td.title") or tr.select_one("td.title a")
        if not title_td:
            return None

        title_el = title_td.select_one("a[href]") if title_td.name == "td" else title_td
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        href = title_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        price_evidence = tr.get_text(" ", strip=True)
        price = self._extract_price(price_evidence)
        image_el = tr.select_one("img[src], img[data-src]")

        return HotdealPost(
            title=title,
            url=url,
            source_community="FM코리아",
            price=price,
            price_evidence=price_evidence if price is not None else "",
            image_url=urljoin(self.BASE_URL, image_el.get("src") or image_el.get("data-src")) if image_el else "",
        )

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
