"""
뽐뿌 핫딜 크롤러.

https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu 에서 핫딜 게시글을 수집한다.
뽐뿌는 국내 최대 핫딜 커뮤니티로, 비교적 단순한 HTML 테이블 구조를 사용한다.

데이터 구조 (2026 기준):
  <tr class="baseList-space">  ← 게시글 행 (공백 행, 무시)
  <tr class="baseList bbs_new1">
    <td class="baseList-space">...</td>     ← 번호
    <td>
      <a href="view.php?...">
        <font class="list_title">제목</font>
      </a>
    </td>
    <td class="baseList-price">가격</td>
    <td>추천/비추</td>
    ...
  </tr>

용도: 핫딜 참고 데이터 (baseline 오염 방지 — HotdealPost로 저장)
의존: core/ 만
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class PpomppuCrawler(CrawlerContract):
    """뽐뿌 핫딜 크롤러 — 국내 최대 핫딜 커뮤니티."""

    BASE_URL = "https://www.ppomppu.co.kr"
    DEAL_URL = "https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu"

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=1.5)

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="뽐뿌",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            description="뽐뿌 핫딜 게시판 크롤러 — 국내 최대 핫딜 커뮤니티",
            target_url=self.DEAL_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """뽐뿌 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[뽐뿌] 크롤링 시작: {self.DEAL_URL}")

        try:
            headers = self._anti_detect.get_random_headers()
            response = requests.get(self.DEAL_URL, headers=headers, timeout=15)
            # 뽐뿌는 EUC-KR 인코딩 사용 — UTF-8로 설정하면 한글이 깨진다
            response.encoding = "euc-kr"

            if response.status_code != 200:
                logger.error(f"[뽐뿌] HTTP {response.status_code}")
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
            logger.info(f"[뽐뿌] 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

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
            logger.error(f"[뽐뿌] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다.

        뽐뿌 게시판은 <tr> 기반 테이블 구조이다.
        각 행에서 제목·링크·가격·추천수를 추출한다.
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 게시글 행 선택 — class에 'baseList'가 포함된 tr
        rows = soup.select("tr.baseList")
        logger.info(f"[뽐뿌] 게시글 행: {len(rows)}개")

        for row in rows:
            try:
                item = self._parse_row(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[뽐뿌] 행 파싱 오류: {e}")
                continue

        return items

    def _parse_row(self, row) -> Optional[HotdealPost]:
        """개별 게시글 행을 파싱한다.

        2026 기준 HTML 구조:
          <tr class="baseList bbs_new1">
            <td class="baseList-space title">
              <a class="baseList-title" href="view.php?...">
                <span>
                  <em class="baseList-head subject_preface">[G마켓]</em>
                  상품명 (가격원/배송)
                </span>
              </a>
              <small class="baseList-small">[식품/건강]</small>
            </td>
          </tr>
        """

        # 공지·광고 행 스킵
        if row.get("class") and "baseList-space" in row.get("class", []):
            return None

        # 1) 제목 + URL 추출
        title_el = row.select_one("a.baseList-title") or row.select_one("a[href*='view.php']")
        if not title_el:
            return None

        # 제목 텍스트 — a.baseList-title 내 전체 텍스트 사용
        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        # 광고 게시글 스킵
        if self._is_ad(row, title):
            return None

        href = title_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL + "/zboard/", href)

        # 2) 가격 추출 — 제목 텍스트에 (39,800원/무배) 형태로 포함
        price = self._extract_price(title)
        if price is None:
            price = self._extract_price(row.get_text(" ", strip=True))

        # 3) 카테고리 추출 — em.baseList-head 또는 제목 앞 [카테고리]
        category = ""
        cat_el = row.select_one("em.baseList-head, em.subject_preface")
        if cat_el:
            category = cat_el.get_text(strip=True).strip("[]")
        else:
            cat_match = re.match(r"\[([^\]]+)\]", title)
            if cat_match:
                category = cat_match.group(1)

        # 서브 카테고리 (식품/건강 등)
        sub_cat = row.select_one("small.baseList-small")
        if sub_cat:
            sub_text = sub_cat.get_text(strip=True).strip("[]")
            if sub_text and not category:
                category = sub_text

        return HotdealPost(
            title=title,
            url=url,
            source_community="뽐뿌",
            price=price,
            category=category,
        )

    def _is_ad(self, row, title: str) -> bool:
        """광고/공지 게시글 여부를 판단한다."""
        # 공지 카테고리
        if "[공지]" in title or "[AD]" in title or "[광고]" in title:
            return True

        # class에 notice가 포함된 행
        row_classes = " ".join(row.get("class", []))
        if "notice" in row_classes:
            return True

        return False

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 최초 가격(원)을 추출한다."""
        if not text:
            return None

        # 가격 패턴을 먼저 시도 — "무료" 검사보다 우선
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)\s*원",  # 1,000원 이상 (콤마 포함)
            r"(\d{3,})\s*원",                # 100원 이상
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))

        # 숫자 가격이 없고 "무료"만 있으면 0원
        if "무료" in text and ("배송" not in text):
            return 0

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
