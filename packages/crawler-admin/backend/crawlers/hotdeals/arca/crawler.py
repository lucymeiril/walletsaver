"""
아카라이브 핫딜 크롤러.

https://arca.live/b/hotdeal 에서 핫딜 게시글을 수집한다.
아카라이브는 Cloudflare 보호가 강해 cloudscraper가 필수이다.

데이터 구조 (2026 기준):
  <a class="vrow column" href="/b/hotdeal/...">
    <span class="vrow-top">
      <span class="vcol col-title">
        <span class="title">
          <span class="deal-store badge">[G마켓]</span>
          제목 텍스트
        </span>
      </span>
    </span>
    <span class="vrow-bottom">
      <span class="vcol col-author">작성자</span>
      <span class="vcol col-time">시간</span>
      <span class="vcol col-view">조회</span>
      <span class="vcol col-rate">추천</span>
    </span>
  </a>

용도: 핫딜 참고 데이터 (baseline 오염 방지 — HotdealPost로 저장)
의존: core/ 만
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class ArcaCrawler(CrawlerContract):
    """아카라이브 핫딜 크롤러 — Cloudflare 보호 사이트."""

    BASE_URL = "https://arca.live"
    DEAL_URL = "https://arca.live/b/hotdeal"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="아카라이브",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="아카라이브 핫딜 채널 크롤러 — 커뮤니티 핫딜 정보",
            target_url=self.DEAL_URL,
            strategies=["cloudscraper"],
        )

    async def crawl(self) -> CrawlResult:
        """아카라이브 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[아카라이브] 크롤링 시작: {self.DEAL_URL}")

        try:
            raw_data = self._fetch_page()
            if raw_data is None:
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg="Cloudflare 차단 — cloudscraper로도 접근 실패",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            # Cloudflare 부분 차단 감지: HTML 반환되나 게시글이 없는 경우
            if not valid_items and len(raw_data) < 50000:
                logger.warning("[아카라이브] Cloudflare 부분 차단 — 게시글 목록이 렌더링되지 않음")

            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            logger.info(f"[아카라이브] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

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
            logger.error(f"[아카라이브] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _fetch_page(self) -> Optional[str]:
        """cloudscraper로 페이지를 가져온다. Cloudflare 우회 시도."""
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            headers = {
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.co.kr/",
            }
            response = scraper.get(self.DEAL_URL, headers=headers, timeout=20)
            if response.status_code == 200 and len(response.text) > 1000:
                return response.text
            logger.warning(f"[아카라이브] HTTP {response.status_code}, 본문 길이: {len(response.text)}")
        except ImportError:
            logger.warning("[아카라이브] cloudscraper 미설치 — pip install cloudscraper")
        except Exception as e:
            logger.warning(f"[아카라이브] cloudscraper 예외: {e}")

        # 폴백: 일반 requests
        try:
            import requests as req
            headers = self._anti_detect.get_random_headers()
            response = req.get(self.DEAL_URL, headers=headers, timeout=15)
            if response.status_code == 200 and len(response.text) > 1000:
                return response.text
        except Exception as e:
            logger.warning(f"[아카라이브] requests 폴백 실패: {e}")

        return None

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다.

        아카라이브는 a.vrow 기반의 게시글 구조를 사용한다.
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 게시글 행 — a.vrow (공지 제외)
        rows = soup.select("a.vrow.column")
        if not rows:
            rows = soup.select("a.vrow")
        logger.info(f"[아카라이브] 게시글 항목: {len(rows)}개")

        for row in rows:
            try:
                item = self._parse_item(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[아카라이브] 항목 파싱 오류: {e}")
                continue

        return items

    def _parse_item(self, row) -> Optional[HotdealPost]:
        """개별 게시글 항목을 파싱한다."""

        # 공지 스킵
        row_classes = " ".join(row.get("class", []))
        if "notice" in row_classes:
            return None

        # 1) URL 추출
        href = row.get("href", "")
        if not href or "/b/hotdeal/" not in href:
            return None
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        # 2) 제목 추출
        title_el = row.select_one("span.title") or row.select_one("span.col-title")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        # 3) 카테고리 — 스토어 배지에서 추출
        category = ""
        badge_el = row.select_one("span.deal-store, span.badge")
        if badge_el:
            category = badge_el.get_text(strip=True).strip("[]")
            # 제목에서 카테고리 태그 제거
            title = title.replace(badge_el.get_text(strip=True), "").strip()

        # 4) 가격 추출 — 제목에서
        price = self._extract_price(title)

        # 5) 추천수 — col-rate에서
        vote_el = row.select_one("span.col-rate")
        # 추천수는 HotdealPost에 별도 필드 없으므로 패스

        return HotdealPost(
            title=title,
            url=url,
            source_community="아카라이브",
            price=price,
            category=category,
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
