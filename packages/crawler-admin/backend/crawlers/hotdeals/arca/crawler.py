"""
아카라이브 핫딜 크롤러.

https://arca.live/b/hotdeal 에서 핫딜 게시글을 수집한다.
아카라이브는 응답 형태가 달라질 수 있어 cloudscraper + Playwright 폴백을 사용한다.

데이터 구조 (2026-07 기준):
  <div class="vrow hybrid">
    <div class="vrow-inner">
      <div class="vrow-top deal">
        <span class="vcol col-title">
          <span class="badges">
            <span class="deal-store">G마켓</span>
            <a class="badge" href="...">전자제품</a>
          </span>
          <a class="title hybrid-title" href="/b/hotdeal/12345?p=1">
            제목 텍스트
            <span class="info"><span class="comment-count">[5]</span></span>
          </a>
        </span>
      </div>
      <a class="title hybrid-bottom" href="/b/hotdeal/12345?p=1">
        <div class="vrow-bottom deal">
          <span class="deal-price">29,900원</span>
          <span class="deal-delivery">무료</span>
        </div>
      </a>
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

logger = logging.getLogger(__name__)


class ArcaCrawler(CrawlerContract):
    """아카라이브 핫딜 크롤러 — 커뮤니티 핫딜 채널."""

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
            strategies=["cloudscraper", "playwright"],
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
        """아카라이브 핫딜 목록을 크롤링한다."""
        started_at = datetime.now()
        logger.info(f"[아카라이브] 크롤링 시작: {self.DEAL_URL}")

        try:
            raw_data = self._fetch_page()
            if raw_data is None:
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg="소스 응답 부족 — cloudscraper로도 목록 수집 실패",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            # 응답은 왔지만 게시글 목록이 없는 경우
            if not valid_items and len(raw_data) < 50000:
                logger.warning("[아카라이브] 게시글 목록이 렌더링되지 않음")

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
        """cloudscraper → Playwright 순서로 페이지를 가져온다."""

        # 1차: cloudscraper 기반 수집 세션
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            headers = {
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.co.kr/",
            }
            # Retry via session-based backoff (cloudscraper extends requests.Session)
            response = self._retry_request(self.DEAL_URL, headers=headers, session=scraper, timeout=20)
            if response.status_code == 200 and len(response.text) > 1000:
                # 실제 게시글 목록(a.vrow)이 있는지 확인
                if "vrow" in response.text and "col-title" in response.text:
                    return response.text
            logger.warning(f"[아카라이브] cloudscraper 응답 부족: HTTP {response.status_code}, len={len(response.text)}")
        except ImportError:
            logger.warning("[아카라이브] cloudscraper 미설치 — pip install cloudscraper")
        except Exception as e:
            logger.warning(f"[아카라이브] cloudscraper 예외: {e}")

        # 2차: Playwright 렌더링 폴백
        html = self._fetch_with_playwright()
        if html:
            return html

        # 3차: 일반 requests 폴백
        try:
            headers = self._anti_detect.get_random_headers()
            response = self._retry_request(self.DEAL_URL, headers=headers, timeout=15)
            if response.status_code == 200 and len(response.text) > 1000:
                return response.text
        except Exception as e:
            logger.warning(f"[아카라이브] requests 폴백 실패: {e}")

        return None

    def _fetch_with_playwright(self) -> Optional[str]:
        """Playwright로 아카라이브를 렌더링한다.

        cloudscraper 기반 수집 세션이 충분한 목록 HTML을 반환하지 못할 때 사용.
        실제 브라우저로 JS Challenge를 통과한 뒤 HTML을 반환한다.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[아카라이브] playwright 미설치 — pip install playwright && playwright install")
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        user_agent=self._anti_detect.get_random_user_agent(),
                        locale="ko-KR",
                        viewport={"width": 1920, "height": 1080},
                    )
                    page = context.new_page()

                    # 렌더링 컨텍스트 초기화
                    page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    """)

                    page.goto(self.DEAL_URL, wait_until="networkidle", timeout=30000)

                    # 페이지 렌더링 대기
                    page.wait_for_timeout(3000)

                    # 게시글 목록이 로드될 때까지 대기
                    try:
                        page.wait_for_selector("a.vrow", timeout=10000)
                    except Exception:
                        logger.warning("[아카라이브] Playwright: a.vrow 셀렉터 대기 타임아웃")

                    html = page.content()
                finally:
                    browser.close()  # Ensure browser is always closed

                if html and len(html) > 1000 and "vrow" in html:
                    logger.info(f"[아카라이브] Playwright 성공: HTML {len(html)}자")
                    return html
                else:
                    logger.warning(f"[아카라이브] Playwright: 게시글 미발견 (HTML {len(html)}자)")

        except Exception as e:
            logger.warning(f"[아카라이브] Playwright 예외: {e}")

        return None

    async def parse(self, raw_data: str) -> list[HotdealPost]:
        """HTML에서 핫딜 게시글을 파싱한다.

        아카라이브 2026 구조:
          - 실제 핫딜 게시글: div.vrow.hybrid (새 하이브리드 레이아웃)
          - 공지/광고: a.vrow.notice (스킵)
        """
        soup = BeautifulSoup(raw_data, "html.parser")
        items: list[HotdealPost] = []

        # 1차: div.vrow.hybrid — 2026 신규 하이브리드 레이아웃
        rows = soup.select("div.vrow.hybrid")
        logger.info(f"[아카라이브] div.vrow.hybrid 항목: {len(rows)}개")

        # 2차 폴백: a.vrow.column (구형 레이아웃)
        if not rows:
            rows = soup.select("a.vrow.column")
            rows = [r for r in rows if "notice" not in " ".join(r.get("class", []))]
            logger.info(f"[아카라이브] a.vrow.column 폴백: {len(rows)}개")

        for row in rows:
            try:
                item = self._parse_item(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[아카라이브] 항목 파싱 오류: {e}")
                continue

        del soup  # Free DOM tree memory
        return items

    def _parse_item(self, row) -> Optional[HotdealPost]:
        """개별 핫딜 게시글을 파싱한다.

        2026 하이브리드 구조 (div.vrow.hybrid):
          <a class="title hybrid-title" href="/b/hotdeal/12345?p=1">제목</a>
          <span class="deal-store">G마켓</span>
          <a class="badge" href="...">전자제품</a>
          <span class="deal-price">29,900원</span>
        """

        # 공지/광고 스킵
        row_classes = " ".join(row.get("class", []))
        if "notice" in row_classes or "head" in row_classes:
            return None

        # 1) 제목 + URL 추출 — a.title.hybrid-title 또는 a.title
        title_el = (
            row.select_one("a.title.hybrid-title")
            or row.select_one("a.title")
            or row.select_one("span.title")
        )
        if not title_el:
            return None

        # 제목 텍스트 — comment-count 등 부가 정보 제외
        # clone 후 info 스팬 제거
        title_text_parts = []
        for child in title_el.children:
            if hasattr(child, 'get') and child.get("class"):
                child_classes = " ".join(child.get("class", []))
                if "info" in child_classes or "comment-count" in child_classes or "media-icon" in child_classes:
                    continue
            text = child.string if hasattr(child, 'string') and child.string else str(child) if isinstance(child, str) else ""
            text = text.strip()
            if text:
                title_text_parts.append(text)

        title = " ".join(title_text_parts).strip()
        if not title or len(title) < 3:
            return None

        href = title_el.get("href", "")
        if not href:
            # hybrid-bottom 링크에서 URL 가져오기
            bottom_el = row.select_one("a.hybrid-bottom, a.title.hybrid-bottom")
            if bottom_el:
                href = bottom_el.get("href", "")
        url = href if href.startswith("http") else urljoin(self.BASE_URL, href)

        # 2) 카테고리 — deal-store 배지에서 추출
        category = ""
        store_el = row.select_one("span.deal-store")
        if store_el:
            category = store_el.get_text(strip=True)

        # 서브 카테고리 — badge 링크에서 (식품, 전자제품 등)
        sub_category = ""
        badge_el = row.select_one("a.badge")
        if badge_el:
            sub_category = badge_el.get_text(strip=True)

        # 3) 가격 추출 — deal-price 스팬에서 직접 추출
        price = None
        price_evidence = ""
        price_el = row.select_one("span.deal-price")
        if price_el:
            price_evidence = price_el.get_text(" ", strip=True)
            price = self._extract_price(price_evidence)

        # 폴백: 제목에서 가격 추출
        if price is None:
            price_evidence = title
            price = self._extract_price(title)

        image_el = row.select_one("img[src], img[data-src]")
        date_el = row.select_one("time, .date, .vrow-time")

        return HotdealPost(
            title=title,
            url=url,
            source_community="아카라이브",
            price=price,
            price_evidence=price_evidence if price is not None else "",
            category=category,
            category_hints=[hint for hint in (category, sub_category) if hint],
            image_url=urljoin(self.BASE_URL, image_el.get("src") or image_el.get("data-src")) if image_el else "",
            period=date_el.get_text(" ", strip=True) if date_el else "",
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
