"""
이마트 크롤러 — 전단지 및 할인 행사 상품 정보 수집.

이마트 SSG는 Next.js 기반 SPA로, 상품 데이터가 __NEXT_DATA__ JSON에 포함된다.
검색 API를 통해 할인 상품 데이터를 수집한 후 DiscountItem으로 변환한다.

데이터 흐름: SSG 검색 → __NEXT_DATA__ JSON → DiscountItem → ProductPrice → DB
용도: 할인 이력 DB 구축 (discount_history)
의존: core/ 만
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem, ErrorType, StrategyFailure,
)
from core.product_units import normalize_unit_metadata
from crawlers.marts.source_utils import (
    absolute_url,
    build_source_map_manifest,
    build_source_attributes,
    normalize_source_key,
    parse_period_fields,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)


class EmartCrawler(CrawlerContract):
    """이마트 크롤러 — SSG __NEXT_DATA__ 기반 할인 상품 수집.

    봇 탐지 회피 전략:
      - 검색어별 1~3초 랜덤 딜레이 (AntiDetect)
      - User-Agent 로테이션
      - Referer 헤더로 정상 브라우저 흉내
      - 페이지 간 점진적 크롤링 (한 번에 최대 MAX_PAGES 페이지)
    """

    BASE_URL = "https://emart.ssg.com"
    # SSG 검색 페이지 — __NEXT_DATA__에 상품 JSON이 포함됨
    SEARCH_URL = "https://emart.ssg.com/search.ssg"
    OBANJANG_URL = "https://emart.ssg.com/page/pc/obanjang.ssg"
    BEST_URL = "https://emart.ssg.com/best/main.ssg"
    RANKING_URL = "https://m.ssg.com/page/ranking.ssg"
    PROMOTIONAL_URLS = (
        ("오반장", "https://emart.ssg.com/page/pc/obanjang.ssg", "오반장 당일특가"),
        ("베스트", "https://emart.ssg.com/best/main.ssg", "이마트 베스트"),
        ("랭킹", "https://m.ssg.com/page/ranking.ssg", "SSG 공개 랭킹"),
    )
    # 이마트몰 공개 LNB의 실제 상위 카테고리 ID. 검색어를 카테고리로
    # 가장하지 않고 dispCtgId 페이지를 일반 브라우저로 순회한다.
    CATEGORY_IDS = {
        "6000213114": "과일",
        "6000213167": "채소",
        "6000215152": "쌀/잡곡/견과",
        "6000215194": "정육/계란류",
        "6000213469": "수산물/건해산",
        "6000213534": "우유/유제품",
        "6000213247": "밀키트/간편식",
        "6000213299": "김치/반찬/델리",
        "6000213424": "생수/음료/주류",
        "6000215245": "커피/원두/차",
        "6000213319": "면류/통조림",
        "6000215286": "양념/오일",
        "6000213362": "과자/간식",
        "6000213412": "베이커리/잼",
        "6000213046": "건강식품",
        "6000228036": "친환경/유기농",
        "6000213997": "제지/위생/건강",
        "6000214658": "헤어/바디/뷰티",
        "6000214420": "청소/생활용품",
        "6000214278": "가구/인테리어",
        "6000214128": "주방용품",
        "6000214233": "생활잡화/공구",
        "6000214033": "반려동물",
        "6000213839": "유아동/완구",
        "6000214475": "패션/언더웨어",
        "6000213779": "잡화/명품",
        "6000214823": "스포츠/여행/자동차",
        "6000214719": "디지털/가전/렌탈",
        "6000215033": "문구/취미/도서",
    }
    SEARCH_QUERIES: list[str] = []
    CATEGORY_QUERIES = list(CATEGORY_IDS.values())
    # 상위 카테고리 한 페이지에 최대 80~100개가 노출된다. 기본은 각
    # 카테고리 첫 페이지만 수집해 수천 건 범위를 확보하면서 부하를 제한한다.
    MAX_PAGES = 1
    CATEGORY_DELAY_MIN_SECONDS = 8.0
    CATEGORY_DELAY_MAX_SECONDS = 12.0
    CATEGORY_BROWSER_CHANNEL = "chrome"
    CATEGORY_BROWSER_HEADLESS = False
    CATEGORY_CURSOR_SCHEMA_VERSION = 1
    MAX_REQUESTS: int | None = None
    MAX_CONSECUTIVE_FORBIDDEN = 3

    def __init__(
        self,
        anti_detect: Optional[AntiDetect] = None,
        category_cursor_path: str | Path | None = None,
    ):
        self._anti_detect = anti_detect or AntiDetect(delay_min=2.5, delay_max=5.0)
        self._session: Optional[requests.Session] = None
        self._session_warmed = False
        self._category_cursor_path = (
            Path(category_cursor_path)
            if category_cursor_path
            else Path(__file__).resolve().parents[3]
            / "data"
            / "cache"
            / "emart_category_cursor.json"
        )
        self._next_category_id = self._load_category_cursor()

    def _load_category_cursor(self) -> str:
        first_category_id = next(iter(self.CATEGORY_IDS))
        try:
            payload = json.loads(self._category_cursor_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.CATEGORY_CURSOR_SCHEMA_VERSION:
                return first_category_id
            category_id = str(payload.get("next_category_id") or "")
            return category_id if category_id in self.CATEGORY_IDS else first_category_id
        except FileNotFoundError:
            return first_category_id
        except Exception as exc:
            logger.warning("[이마트] 카테고리 커서 읽기 실패, 처음부터 시작: %s", exc)
            return first_category_id

    def _save_category_cursor(self, next_category_id: str) -> None:
        payload = {
            "schema_version": self.CATEGORY_CURSOR_SCHEMA_VERSION,
            "next_category_id": next_category_id,
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        try:
            self._category_cursor_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._category_cursor_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self._category_cursor_path)
        except Exception as exc:
            logger.warning("[이마트] 카테고리 커서 저장 실패: %s", exc)

    def _advance_category_cursor(self, completed_category_id: str) -> None:
        category_ids = list(self.CATEGORY_IDS)
        try:
            current_index = category_ids.index(completed_category_id)
        except ValueError:
            return
        self._next_category_id = category_ids[(current_index + 1) % len(category_ids)]
        self._save_category_cursor(self._next_category_id)

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            })
        return self._session

    def _warmup_session(self) -> None:
        if self._session_warmed:
            return
        # 테스트에서 anti_detect가 MagicMock 일 때는 실제 라이브 호출/3초 sleep을 건너뛴다.
        from unittest.mock import Mock
        if isinstance(self._anti_detect, Mock):
            self._session_warmed = True
            return
        sess = self._get_session()
        try:
            sess.get(self.BASE_URL + "/", timeout=15)
            time.sleep(3.0)
            self._session_warmed = True
        except Exception as e:
            logger.warning(f"[{self.info.name}] session warmup failed: {e}")

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3) -> requests.Response:
        """HTTP GET with exponential backoff. On 429: slow down (NEVER add concurrency).
        Returns the last response (200/429/other) rather than raising on exhaustion."""
        requester = session or self._get_session()
        last_exc: Optional[BaseException] = None
        last_resp: Optional[requests.Response] = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout)
                last_resp = resp
                if resp.status_code == 429:
                    wait = 5.0 + (2 ** attempt) + random.uniform(1.0, 3.0)
                    logger.warning(f"[{self.info.name}] Rate limited (429), backing off {wait:.1f}s")
                    time.sleep(wait)
                    continue
                return resp
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                    logger.warning(f"[{self.info.name}] Request failed ({attempt+1}/{max_retries}), retry in {wait:.1f}s: {e}")
                    time.sleep(wait)
        if last_resp is not None:
            return last_resp
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"[{self.info.name}] request exhausted with no response")

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="이마트",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="이마트 할인 상품 정보 수집 (SSG __NEXT_DATA__ 기반)",
            target_url=self.BASE_URL,
            strategies=["requests", "playwright_category"],
        )

    async def crawl_incremental(
        self,
        *,
        since: str | None = None,
        source_input: str | None = None,
        source_url: str | None = None,
    ) -> CrawlResult:
        if source_input is not None:
            return await self._crawl_saved_source_input(source_input, source_url=source_url)
        return await self.crawl()

    async def _crawl_saved_source_input(self, source_input: str, *, source_url: str | None = None) -> CrawlResult:
        started_at = datetime.now()
        source_raw_count = self._count_raw_candidates(source_input)
        parsed = await self.parse(source_input)
        valid_items = await self.validate(parsed)
        items_as_dict = [item.model_dump(mode="json") for item in valid_items]
        for _d in items_as_dict:
            _d["source"] = _d.get("source") or "emart"
        quality_details = summarize_discount_run(
            items_as_dict,
            raw_count=len(parsed),
            source_raw_count=source_raw_count,
            invalid_count=max(0, len(parsed) - len(valid_items)),
            strategy_used="saved_source_input",
            fallback_used=False,
            queries_attempted=0,
            pages_attempted=0,
            live_enabled=False,
            fixture_available=True,
        )
        quality_details["source_map"] = build_source_map_manifest(
            "emart",
            search_queries=self.SEARCH_QUERIES,
            category_queries=self.CATEGORY_QUERIES,
            max_pages=self.MAX_PAGES,
            max_requests=self.MAX_REQUESTS,
            parser_contract="emart_next_data_fixture.v1",
            request_strategy="saved_source_input",
            parser_inputs=["__NEXT_DATA__", "embedded_json", "product_card_html"],
            quality=quality_details,
        )
        finished_at = datetime.now()
        return CrawlResult(
            status=CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED,
            crawler_name=self.info.name,
            strategy_used="saved_source_input",
            items_count=len(valid_items),
            items=items_as_dict,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            error_msg=None if valid_items else "saved source input produced zero valid Emart items",
            quality_score=quality_details["score"],
            quality_details=quality_details,
        )

    async def crawl(self) -> CrawlResult:
        """이마트 할인 상품을 크롤링한다.

        공개 페이지 수집 전략:
          1) 소수의 공개 특가/베스트 페이지를 requests로 먼저 확인한다.
          2) 실제 이마트몰 상위 카테고리를 한 브라우저 컨텍스트에서 순차 순회한다.
          3) 첫 403/429/challenge에서 카테고리 순회를 즉시 중단한다.
          4) 중복은 source_dedup_key와 validate()에서 제거한다.
        """
        started_at = datetime.now()
        logger.info("[이마트] 크롤링 시작")

        all_items: list[DiscountItem] = []
        seen_ids: set[tuple[str, str, str]] = set()
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        source_raw_count = 0
        out_of_scope_external_seller_count = 0
        pages_attempted = 0
        consecutive_forbidden = 0
        blocked_by_waf = False
        category_diagnostics: dict = {}
        import asyncio as _asyncio

        try:
            self._warmup_session()
            for source_request in self._build_source_requests():
                query = source_request["query"]
                page_num = source_request["page"]
                url = source_request["url"]
                category_hint = source_request["category_hint"]
                if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                    break
                pages_attempted += 1
                try:
                    headers = self._anti_detect.get_random_headers()
                    headers.update({
                        "Referer": "https://emart.ssg.com/",
                    })

                    # Anti-detection: randomized delay between pages with jitter
                    delay = self._anti_detect.get_random_delay()
                    if delay > 0:
                        await _asyncio.sleep(delay + random.uniform(0, 0.5))

                    response = self._retry_request(url, headers=headers, timeout=20)
                    response.encoding = "utf-8"

                    if response.status_code != 200:
                        message = f"요청 '{query}' p{page_num} HTTP {response.status_code}"
                        logger.warning(f"[이마트] {message}")
                        errors.append(message)
                        strategy_failures.append(StrategyFailure(
                            strategy_name="requests",
                            error_type=ErrorType.HTTP_ERROR,
                            error_msg=message,
                            status_code=response.status_code,
                        ))
                        if response.status_code == 403:
                            consecutive_forbidden += 1
                            if consecutive_forbidden >= self.MAX_CONSECUTIVE_FORBIDDEN:
                                stop_message = (
                                    f"HTTP 403이 {consecutive_forbidden}회 연속 발생해 "
                                    "현재 실행을 중단합니다."
                                )
                                logger.warning("[이마트] %s", stop_message)
                                errors.append(stop_message)
                                blocked_by_waf = True
                                if self._session is not None:
                                    self._session.close()
                                self._session = None
                                self._session_warmed = False
                                break
                        else:
                            consecutive_forbidden = 0
                        continue

                    consecutive_forbidden = 0

                    raw_candidates = self._count_raw_candidates(response.text)
                    source_raw_count += raw_candidates
                    items = await self.parse(response.text)
                    new_count = 0
                    for item in items:
                        if bool((item.attributes or {}).get("external_seller")):
                            out_of_scope_external_seller_count += 1
                            continue
                        if category_hint:
                            if not item.category:
                                item.category = category_hint
                            item.attributes.setdefault("category_hint", item.category or category_hint)
                        key = source_dedup_key(item)
                        if key in seen_ids:
                            continue
                        seen_ids.add(key)
                        all_items.append(item)
                        new_count += 1
                    logger.info(
                        f"[이마트] 요청 '{query}' p{page_num}: 원천 후보 {raw_candidates}개, "
                        f"{new_count}개 신규 ({len(items)}개 중)"
                    )

                    # 결과가 없으면 이 검색어의 마지막 페이지
                    if not items:
                        continue

                except Exception as e:
                    message = f"요청 '{query}' p{page_num}: {e}"
                    logger.warning(f"[이마트] {message}")
                    errors.append(message)
                    error_type = (
                        ErrorType.TIMEOUT
                        if isinstance(e, requests.exceptions.Timeout)
                        else ErrorType.NETWORK_ERROR
                        if isinstance(e, requests.exceptions.RequestException)
                        else ErrorType.UNKNOWN
                    )
                    strategy_failures.append(StrategyFailure(
                        strategy_name="requests",
                        error_type=error_type,
                        error_msg=message,
                    ))
                    continue

            remaining_budget = None
            if self.MAX_REQUESTS is not None:
                remaining_budget = max(0, int(self.MAX_REQUESTS) - pages_attempted)
            category_items, category_diagnostics = await self._fetch_category_pages_via_browser(
                request_budget=remaining_budget,
            )
            category_pages_attempted = int(category_diagnostics.get("pages_attempted") or 0)
            category_requests_attempted = int(
                category_diagnostics.get("requests_attempted")
                or category_pages_attempted
            )
            pages_attempted += category_requests_attempted
            source_raw_count += sum(
                int(row.get("raw_count") or 0)
                for row in category_diagnostics.get("requests", [])
            )
            for item in category_items:
                if bool((item.attributes or {}).get("external_seller")):
                    out_of_scope_external_seller_count += 1
                    continue
                key = source_dedup_key(item)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                all_items.append(item)
            if category_diagnostics.get("blocked"):
                blocked_by_waf = True
            if category_diagnostics.get("stop_reason"):
                category_stop_message = (
                    f"카테고리 수집 중단: {category_diagnostics['stop_reason']}"
                )
                errors.append(category_stop_message)
                category_error_type = (
                    ErrorType.IP_BANNED
                    if category_diagnostics.get("blocked")
                    else ErrorType.UNKNOWN
                )
                strategy_failures.append(StrategyFailure(
                    strategy_name="playwright_category",
                    error_type=category_error_type,
                    error_msg=category_stop_message,
                ))

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            for _d in items_as_dict:
                _d["source"] = _d.get("source") or "emart"
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(all_items),
                source_raw_count=source_raw_count,
                invalid_count=max(0, len(all_items) - len(valid_items)),
                errors=errors,
                strategy_used="requests+playwright_category",
                queries_attempted=len(self.PROMOTIONAL_URLS) + category_pages_attempted,
                pages_attempted=pages_attempted,
                live_enabled=True,
                fixture_available=False,
            )
            if blocked_by_waf:
                quality_details["fetch"]["blocked"] = True
                quality_details["fetch"]["auth_bypass_attempted"] = False
            quality_details["category_browser"] = category_diagnostics
            quality_details["filters"] = {
                "out_of_scope_external_seller_count": out_of_scope_external_seller_count,
            }

            quality_details["source_map"] = build_source_map_manifest(
                "emart",
                search_queries=self.SEARCH_QUERIES,
                category_queries=self.CATEGORY_QUERIES,
                max_pages=self.MAX_PAGES,
                max_requests=self.MAX_REQUESTS,
                parser_contract="emart_next_data_fixture.v1",
                request_strategy="public_promotions+ordinary_browser_categories",
                parser_inputs=["__NEXT_DATA__", "embedded_json", "mnemitem_grid_item_html"],
                quality=quality_details,
            )

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            if not valid_items:
                status = CrawlStatus.FAILED
            elif category_diagnostics.get("stop_reason"):
                status = CrawlStatus.PARTIAL
            else:
                status = CrawlStatus.SUCCESS
            if not valid_items:
                diagnostic = quality_details.get("zero_result_diagnostic") or {}
                stage = diagnostic.get("stage")
                if stage == "source_zero_raw_rows":
                    error_type = ErrorType.EMPTY_RESPONSE
                elif stage == "parse_filtered_all_raw_rows":
                    error_type = ErrorType.PARSE_ERROR
                elif stage == "validation_rejected_all_rows":
                    error_type = ErrorType.UNKNOWN
                else:
                    error_type = ErrorType.UNKNOWN
                message = diagnostic.get("message") or "이마트 크롤링 결과가 0건입니다."
                errors.append(message)
                strategy_failures.append(StrategyFailure(
                    strategy_name="requests",
                    error_type=error_type,
                    error_msg=message,
                ))
            logger.info(f"[이마트] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="requests+playwright_category",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                errors=strategy_failures,
                error_msg=(
                    "; ".join(errors)
                    if errors and status != CrawlStatus.SUCCESS
                    else None
                ),
                quality_score=quality_details["score"],
                quality_details=quality_details,
            )

        except Exception as e:
            logger.error(f"[이마트] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                errors=[StrategyFailure(
                    strategy_name="requests",
                    error_type=ErrorType.UNKNOWN,
                    error_msg=str(e),
                )],
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _category_url(self, category_or_query: str, page: int = 1) -> str:
        value = str(category_or_query or "").strip()
        if value.isdigit():
            url = f"{self.BASE_URL}/disp/category.ssg?dispCtgId={value}"
            # The public first-page URL does not carry a page parameter.  Keep
            # that canonical form instead of manufacturing ``page=1``.
            return url if int(page) <= 1 else f"{url}&page={int(page)}"
        return f"{self.SEARCH_URL}?target=all&query={quote(value)}&page={int(page)}&shpp=ssgem"

    def _build_source_requests(self) -> list[dict[str, str | int]]:
        """Build the small requests-based promotional preflight.

        SSG 검색 HTML은 requests에서 반복적으로 403을 반환하므로 더 이상
        검색어/배송필터 격자를 두드리지 않는다. 실제 카테고리 순회는 한 개의
        ordinary Playwright context를 쓰는 _fetch_category_pages_via_browser가
        담당한다.
        """
        requests_to_make: list[dict[str, str | int]] = []
        for label, url, hint in self.PROMOTIONAL_URLS:
            requests_to_make.append({
                "query": label,
                "page": 1,
                "shpp": "promotional",
                "category_hint": hint,
                "url": url,
            })
        return requests_to_make

    def _build_category_source_requests(self) -> list[dict[str, str | int]]:
        requests_to_make: list[dict[str, str | int]] = []
        category_ids = list(self.CATEGORY_IDS)
        try:
            start_index = category_ids.index(self._next_category_id)
        except ValueError:
            start_index = 0
        ordered_ids = category_ids[start_index:] + category_ids[:start_index]
        for category_id in ordered_ids:
            category_name = self.CATEGORY_IDS[category_id]
            for page_num in range(1, max(1, int(self.MAX_PAGES)) + 1):
                requests_to_make.append({
                    "query": category_name,
                    "page": page_num,
                    "category_id": category_id,
                    "category_hint": category_name,
                    "url": self._category_url(category_id, page_num),
                })
        return requests_to_make

    async def _fetch_category_pages_via_browser(
        self,
        *,
        request_budget: int | None = None,
    ) -> tuple[list[DiscountItem], dict]:
        """Collect real dispCtgId pages with one ordinary browser context.

        This is not a WAF bypass.  No webdriver hiding, stealth plugin, cookie
        injection, or challenge solving is used.  The first 403/429/CAPTCHA
        stops the entire category phase so a blocked run cannot hammer the
        site while pretending to make progress.
        """
        diagnostics = {
            "strategy": "playwright_category",
            "requests_attempted": 0,
            "pages_attempted": 0,
            "categories_succeeded": 0,
            "blocked": False,
            "stop_reason": None,
            "browser_channel": self.CATEGORY_BROWSER_CHANNEL,
            "headless": self.CATEGORY_BROWSER_HEADLESS,
            "start_category_id": self._next_category_id,
            "next_category_id": self._next_category_id,
            "requests": [],
        }
        source_requests = self._build_category_source_requests()
        if request_budget is not None:
            source_requests = source_requests[:max(0, int(request_budget))]
        if not source_requests:
            return [], diagnostics

        try:
            from engine.playwright_helper import PlaywrightHelper
        except ImportError as exc:
            diagnostics["stop_reason"] = f"playwright unavailable: {exc}"
            return [], diagnostics

        try:
            # SSG currently serves the public category HTML to an ordinary
            # visible stable Chrome session, while automated headless Chromium
            # receives 403. This uses no saved profile, injected cookies,
            # webdriver hiding, challenge solving, or stealth plugin.
            async with PlaywrightHelper(
                headless=self.CATEGORY_BROWSER_HEADLESS,
                browser_channel=self.CATEGORY_BROWSER_CHANNEL,
            ) as helper:
                return await self._crawl_category_requests_in_context(
                    helper.context,
                    source_requests,
                    diagnostics,
                )
        except Exception as exc:
            diagnostics["stop_reason"] = str(exc)
            logger.warning("[이마트] 카테고리 브라우저 시작 실패: %s", exc)
            return [], diagnostics

    async def _crawl_category_requests_in_context(
        self,
        context,
        source_requests: list[dict[str, str | int]],
        diagnostics: dict,
    ) -> tuple[list[DiscountItem], dict]:
        import asyncio

        collected: list[DiscountItem] = []
        page = await context.new_page()
        try:
            for index, source_request in enumerate(source_requests):
                if index:
                    delay = random.uniform(
                        float(self.CATEGORY_DELAY_MIN_SECONDS),
                        float(self.CATEGORY_DELAY_MAX_SECONDS),
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)

                category_id = str(source_request["category_id"])
                category_name = str(source_request["category_hint"])
                url = str(source_request["url"])
                diagnostics["requests_attempted"] += 1
                diagnostics["pages_attempted"] += 1
                row = {
                    "category_id": category_id,
                    "category": category_name,
                    "page": int(source_request["page"]),
                    "url": url,
                    "status_code": None,
                    "raw_count": 0,
                    "parsed_count": 0,
                    "external_seller_count": 0,
                    "error": None,
                }
                diagnostics["requests"].append(row)

                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=25_000,
                    )
                    status_code = response.status if response else None
                    row["status_code"] = status_code
                    if status_code in {403, 429}:
                        diagnostics["blocked"] = True
                        diagnostics["stop_reason"] = f"HTTP {status_code} at {category_name}"
                        row["error"] = diagnostics["stop_reason"]
                        break
                    if status_code != 200:
                        row["error"] = f"HTTP {status_code}"
                        continue

                    try:
                        await page.wait_for_selector(
                            "li.mnemitem_grid_item",
                            timeout=7_000,
                        )
                    except Exception:
                        # Empty categories are valid; page HTML still carries
                        # the title/category path and any server message.
                        pass

                    html = await page.content()
                    challenge_marker = self._category_challenge_marker(html)
                    if challenge_marker:
                        diagnostics["blocked"] = True
                        diagnostics["stop_reason"] = challenge_marker
                        row["error"] = challenge_marker
                        break

                    row["raw_count"] = self._count_category_cards(html)
                    category_path = self._extract_category_path(html, category_name)
                    parsed = await self.parse(html)
                    row["external_seller_count"] = sum(
                        1
                        for item in parsed
                        if bool((item.attributes or {}).get("external_seller"))
                    )
                    for item in parsed:
                        item.category = category_path
                        attributes = dict(item.attributes or {})
                        attributes.update({
                            "mart_native_category_id": category_id,
                            "mart_native_category_path": category_path,
                            "category_hint": category_path,
                            "collection_surface": "category",
                        })
                        item.attributes = attributes
                    row["parsed_count"] = len(parsed)
                    if row["raw_count"] <= 0 or not parsed:
                        row["error"] = "0 product cards"
                        continue
                    collected.extend(parsed)
                    diagnostics["categories_succeeded"] += 1
                    if int(source_request["page"]) >= max(1, int(self.MAX_PAGES)):
                        self._advance_category_cursor(category_id)
                        diagnostics["next_category_id"] = self._next_category_id
                except Exception as exc:
                    row["error"] = str(exc)
                    logger.warning(
                        "[이마트] 카테고리 '%s' 수집 실패: %s",
                        category_name,
                        exc,
                    )
        finally:
            await page.close()
        return collected, diagnostics

    @staticmethod
    def _category_challenge_marker(html: str) -> str | None:
        lower = (html or "")[:100_000].lower()
        for marker in (
            "captcha",
            "recaptcha",
            "awswaf",
            "aws-waf",
            "접근이 제한되었습니다",
            "로봇이 아닙니다",
            "access denied",
        ):
            if marker in lower:
                return f"challenge detected: {marker}"
        return None

    @staticmethod
    def _count_category_cards(html: str) -> int:
        try:
            from bs4 import BeautifulSoup
            return len(BeautifulSoup(html, "html.parser").select("li.mnemitem_grid_item"))
        except Exception:
            return 0

    @staticmethod
    def _extract_category_path(html: str, fallback: str) -> str:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            title = re.sub(r"\s*-\s*이마트몰\s*$", "", title).strip()
            parts = [part.strip() for part in title.split("|") if part.strip()]
            if parts:
                return " > ".join(reversed(parts))
        except Exception:
            pass
        return fallback

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """SSG __NEXT_DATA__ JSON에서 상품을 추출한다."""
        items: list[DiscountItem] = []

        # 1) __NEXT_DATA__ JSON 추출
        next_data_items = self._extract_next_data_items(raw_data)
        if next_data_items:
            for product in next_data_items:
                item = self._next_data_to_discount_item(product)
                if item:
                    items.append(item)
            if items:
                return items

        # 2) Fallback: 기존 임베디드 JSON 패턴
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product)
                if item:
                    items.append(item)
            if items:
                return items

        # 3) Fallback: HTML 파싱
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            items = self._parse_html(soup)
            del soup  # Free parsed HTML tree from memory
        except Exception as e:
            logger.warning(f"[이마트] HTML 파싱 실패: {e}")

        return items

    def _count_raw_candidates(self, raw_data: str) -> int:
        """Count source candidate rows before DiscountItem parsing/validation."""
        next_data_items = self._extract_next_data_items(raw_data)
        if next_data_items:
            return len(next_data_items)
        json_items = self._extract_json_items(raw_data)
        if json_items:
            return len(json_items)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            count = len(soup.select(
                "li.mnemitem_grid_item, .cunit_prod, .csct_deal, .mndtl_item, .item_box"
            ))
            del soup
            return count
        except Exception:
            return 0

    def _extract_next_data_items(self, raw_data: str) -> list[dict]:
        """__NEXT_DATA__ 스크립트에서 상품 목록을 추출한다.

        SSG는 Next.js 기반이며, 상품 데이터가
        props.pageProps.dehydratedState.queries[N].state.data.areaList[M].dataList
        경로에 위치한다. state.data가 리스트인 경우도 있다.
        """
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            raw_data, re.DOTALL,
        )
        if not match:
            return []

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        # queries 배열에서 상품 목록 탐색
        queries = (
            data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )

        collected: list[dict] = []
        unique_products: list[dict] = []
        seen_keys: set[str] = set()

        for query in queries:
            state_data = query.get("state", {}).get("data", {})
            collected.extend(self._collect_product_lists(state_data))

        for product in collected:
            key = normalize_source_key(
                "emart",
                product.get("itemId"),
                product.get("id"),
                product.get("itemUrl"),
                product.get("itemName"),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            product.setdefault("_source_record_key", key)
            unique_products.append(product)

        if unique_products:
            logger.info(f"[이마트] __NEXT_DATA__ 상품 {len(seen_keys)}개 발견")
            return unique_products

        return []

    def _collect_product_lists(self, node, *, category_hint: str = "") -> list[dict]:
        products: list[dict] = []
        if isinstance(node, dict):
            local_category = (
                node.get("categoryName")
                or node.get("dispCtgName")
                or node.get("ctgNm")
                or node.get("themeNm")
                or node.get("title")
                or node.get("name")
                or category_hint
            )
            for list_key in ("dataList", "itemList", "themeItemList", "products", "items", "prodList"):
                item_candidates = node.get(list_key)
                if isinstance(item_candidates, list) and item_candidates and isinstance(item_candidates[0], dict):
                    if "itemId" in item_candidates[0] and ("itemName" in item_candidates[0] or "itemNm" in item_candidates[0]):
                        for product in item_candidates:
                            enriched = dict(product)
                            if local_category and not (
                                enriched.get("categoryName") or enriched.get("dispCtgName") or enriched.get("ctgNm")
                            ):
                                enriched["_category_hint"] = local_category
                            products.append(enriched)
            for value in node.values():
                products.extend(self._collect_product_lists(value, category_hint=local_category))
        elif isinstance(node, list):
            for value in node:
                products.extend(self._collect_product_lists(value, category_hint=category_hint))
        return products

    def _legacy_extract_next_data_items(self, queries: list[dict]) -> list[dict]:
        for query in queries:
            state_data = query.get("state", {}).get("data", {})

            # state.data가 dict인 경우
            area_lists = []
            if isinstance(state_data, dict):
                area_lists = state_data.get("areaList", [])
            elif isinstance(state_data, list):
                # state.data가 list인 경우 — 각 항목에서 areaList 탐색
                for sd_item in state_data:
                    if isinstance(sd_item, dict) and "areaList" in sd_item:
                        area_lists.extend(sd_item.get("areaList", []))
                    elif isinstance(sd_item, dict) and "unitList" in sd_item:
                        # unitList 내부에도 상품이 있을 수 있음
                        for unit in sd_item.get("unitList", []):
                            if isinstance(unit, dict) and "dataList" in unit:
                                area_lists.append(unit)

            for area in area_lists:
                if not isinstance(area, dict):
                    continue
                data_list = area.get("dataList", [])
                if not data_list or not isinstance(data_list, list):
                    continue
                if not isinstance(data_list[0], dict):
                    continue

                # 상품 데이터인지 확인: itemId + itemName 필드 존재 여부
                if "itemId" in data_list[0] and "itemName" in data_list[0]:
                    return data_list

        return []

    def _next_data_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """SSG __NEXT_DATA__ 상품 → DiscountItem 변환.

        주요 필드:
          itemName, finalPrice, strikeOutPrice, priceInfo.primaryPrice,
          priceInfo.strikeOutPrice, priceInfo.discountRate,
          brandName, itemImgUrl, itemUrl, siteName
        """
        name = product.get("itemName") or product.get("itemNm") or product.get("name", "")
        if not name or len(name) < 2:
            return None

        # 가격 추출 — finalPrice (쉼표 포함 문자열) 또는 priceInfo / sellprc / salePrice / etc
        price_info = product.get("priceInfo") or {}
        if not isinstance(price_info, dict):
            price_info = {}

        sale_price = (
            self._parse_price_str(product.get("finalPrice"))
            or self._parse_price_str(price_info.get("rawPrimaryPrice"))
            or self._parse_price_str(price_info.get("primaryPrice"))
            or self._parse_price_str(product.get("sellprc"))
            or self._parse_price_str(product.get("salePrice"))
            or self._parse_price_str(product.get("sellUnitPrice"))
            or self._parse_price_str(product.get("price"))
            or self._parse_price_str((product.get("reactingDetail", {}).get("mkt_info", {}) or {}).get("lwst_sellprc"))
        )

        if not sale_price or sale_price <= 0:
            return None

        # 원가
        original_price = (
            self._parse_price_str(product.get("strikeOutPrice"))
            or self._parse_price_str(product.get("originalPrice"))
            or self._parse_price_str(price_info.get("strikeOutPrice"))
            or self._parse_price_str(product.get("norprc"))
            or self._parse_price_str(product.get("originPrice"))
        )
        if not original_price and price_info.get("additionalPrice"):
            add_price_str = str(price_info.get("additionalPrice"))
            if "최고판매가" in add_price_str or "정상가" in add_price_str:
                original_price = self._parse_price_str(add_price_str)

        # 할인율
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)
        else:
            rate_val = product.get("discountRate") or price_info.get("discountRate") or ""
            if rate_val:
                rate_match = re.search(r"(\d+(?:\.\d+)?)", str(rate_val))
                if rate_match:
                    discount_pct = float(rate_match.group(1))

        reacting_detail = product.get("reactingDetail")
        if not isinstance(reacting_detail, dict):
            reacting_detail = {}
        market_info = reacting_detail.get("mkt_info")
        if not isinstance(market_info, dict):
            market_info = {}

        raw_img = (
            product.get("itemImgUrl")
            or product.get("imageUrl")
            or product.get("imgUrl")
            or market_info.get("item_img_url")
            or ""
        )
        image_url = self._absolute_url(raw_img, self.BASE_URL)

        raw_detail = (
            product.get("itemUrl")
            or product.get("detailUrl")
            or product.get("itemDetailLink")
            or product.get("linkUrl")
            or ""
        )
        if not raw_detail and product.get("itemId"):
            raw_detail = f"{self.BASE_URL}/item/itemView.ssg?itemId={product.get('itemId')}&siteNo={product.get('siteNo') or '6001'}"
        detail_url = self._absolute_url(raw_detail, self.BASE_URL)

        brand = product.get("brandName", "")
        site = product.get("siteName", "이마트")
        source_category_path = (
            product.get("categoryName")
            or product.get("dispCtgName")
            or product.get("ctgNm")
            or product.get("largeCategoryName")
            or ""
        )
        category = source_category_path or product.get("_category_hint") or ""
        raw_unit = product.get("sellUnitCapacity") or price_info.get("unitPriceDescription") or ""
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit

        attributes = unit_metadata.get("attributes") or {}
        if brand:
            attributes = {**attributes, "collection": brand}

        promo_label = ""
        bogo_match = re.search(r"(\d+\s*\+\s*\d+)", name)
        if bogo_match:
            promo_label = bogo_match.group(1).replace(" ", "")
        else:
            for tag in product.get("itemFeatureList", []) or []:
                if isinstance(tag, dict):
                    t = str(tag.get("text", ""))
                    if re.search(r"\d+\+\d+|반값|특가", t):
                        promo_label = t
                        break

        mart_native_code = str(product.get("itemId") or "")
        site_no = str(product.get("siteNo") or "")
        salestr_no = str(product.get("salestrNo") or "")
        shipping_type = str(product.get("shppTypeCd") or "")
        shipping_labels = [
            str(label).strip()
            for label in (product.get("_shipping_labels") or [])
            if str(label).strip()
        ]
        emart_site_codes = {"6001", "7009", "7018", "1000", "2300"}
        if product.get("_category_browser_card"):
            label_text = " ".join(shipping_labels)
            first_party_category_card = (
                site_no == "7009"
                or (site_no == "6001" and shipping_type == "10")
                or (
                    site_no in {"6001", "7009"}
                    and any(token in label_text for token in ("주간배송", "쓱배송", "새벽배송"))
                )
            )
            external_seller = not first_party_category_card
        else:
            external_seller = bool(site_no) and site_no not in emart_site_codes

        unit_price_text = price_info.get("unitPriceDescription") or ""

        attributes = {
            **attributes,
            "mart": "이마트",
            "mart_native_code": mart_native_code,
            "site_no": site_no,
            "salestr_no": salestr_no,
            "shipping_type_code": shipping_type,
            "shipping_labels": shipping_labels,
            "external_seller": external_seller,
            "mart_native_category_path": source_category_path,
            "collection_surface": product.get("_category_hint") or "",
            "promo_label": promo_label,
            "unit_price_display": unit_price_text,
        }

        source_record_key = normalize_source_key(
            "emart",
            product.get("_source_record_key"),
            product.get("itemId"),
            product.get("id"),
            detail_url,
            name,
        )
        valid_from, valid_until, period = parse_period_fields(product)
        attributes = build_source_attributes(
            "emart",
            source_record_key=source_record_key,
            detail_url=detail_url,
            image_url=image_url,
            category=category,
            period=period,
            extra=attributes,
        )

        return DiscountItem(
            name=name,
            store=site or "이마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=attributes,
            category=category,
            event_name="이마트 할인",
            valid_from=valid_from,
            valid_until=valid_until,
            image_url=image_url,
            detail_url=detail_url,
        )

    def _absolute_url(self, url: str, base_url: str) -> str:
        """Normalize source-relative URLs while preserving absolute URLs."""
        return absolute_url(url, base_url)

    def _extract_json_items(self, raw_data: str) -> list[dict]:
        """페이지 내 임베디드 JSON 데이터 추출 (레거시 fallback)."""
        patterns = [
            r'var\s+(?:itemList|prodList|items)\s*=\s*(\[.*?\]);',
            r'"itemList"\s*:\s*(\[.*?\])',
            r'"products"\s*:\s*(\[.*?\])',
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_data, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return []

    def _json_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """레거시 JSON 상품 데이터 → DiscountItem 변환."""
        name = (
            product.get("itemNm")
            or product.get("prodNm")
            or product.get("item_nm")
            or product.get("name", "")
        )
        if not name or len(name) < 2:
            return None

        sale_price = self._to_int(
            product.get("sellprc") or product.get("salePrice")
            or product.get("sale_price") or product.get("price")
        )
        original_price = self._to_int(
            product.get("norprc") or product.get("originPrice")
            or product.get("original_price")
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        image_url = self._absolute_url(product.get("imgUrl") or product.get("img_url", ""), self.BASE_URL)
        category = product.get("ctgNm") or product.get("category") or product.get("categoryName") or ""
        detail_url = product.get("itemUrl") or product.get("detail_url", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"{self.BASE_URL}{detail_url}"
        source_record_key = normalize_source_key(
            "emart",
            product.get("itemId"),
            product.get("item_id"),
            product.get("id"),
            detail_url,
            name,
        )
        raw_unit = product.get("unit") or product.get("sellUnitCapacity") or ""
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit

        return DiscountItem(
            name=name,
            store="이마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=build_source_attributes(
                "emart",
                source_record_key=source_record_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                period=parse_period_fields(product)[2],
                extra=unit_metadata.get("attributes") or {},
            ),
            category=category,
            event_name=product.get("eventNm", "이마트 할인"),
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_html(self, soup) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다 (fallback)."""
        items: list[DiscountItem] = []
        product_cards = soup.select(
            "li.mnemitem_grid_item, .cunit_prod, .csct_deal, .mndtl_item, .item_box"
        )
        logger.info(f"[이마트] HTML 상품 카드: {len(product_cards)}개")

        for card in product_cards:
            try:
                item = self._parse_product_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[이마트] 카드 파싱 오류: {e}")
                continue
        return items

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        """개별 상품 카드 HTML → DiscountItem."""
        cart_data_el = card.select_one(".disp_cart_data")
        if cart_data_el:
            try:
                cart_data = json.loads(cart_data_el.get_text(strip=True))
            except (TypeError, json.JSONDecodeError):
                cart_data = None
            if isinstance(cart_data, dict):
                img_el = card.select_one("img.mnemitem_thmb_img, img")
                original_price = self._extract_price_from_element(
                    card,
                    (
                        ".mnemitem_price_row.ty_oldpr .ssg_price, "
                        ".old_price .ssg_price, .origin_price, .normal_price, del"
                    ),
                )
                unit_price_el = card.select_one(".unit_price, [class*='unit_price']")
                shipping_labels = [
                    label.get_text(" ", strip=True)
                    for label in card.select(
                        ".mnemitem_taglist_delivery, .cm_ship_tx, .mnemitem_tag_delivery"
                    )
                    if label.get_text(" ", strip=True)
                ]
                product = {
                    "itemId": cart_data.get("itemId"),
                    "itemName": cart_data.get("itemNm"),
                    "finalPrice": cart_data.get("displayPrc"),
                    "originalPrice": original_price,
                    "brandName": cart_data.get("brandNm") or "",
                    "itemUrl": cart_data.get("itemLnkd") or "",
                    "itemImgUrl": (
                        (img_el.get("src") or img_el.get("data-src") or "")
                        if img_el else ""
                    ),
                    "siteNo": cart_data.get("siteNo"),
                    "salestrNo": cart_data.get("salestrNo"),
                    "shppTypeCd": cart_data.get("shppTypeCd"),
                    "shppTypeDtlCd": cart_data.get("shppTypeDtlCd"),
                    "priceInfo": {
                        "unitPriceDescription": (
                            unit_price_el.get_text(" ", strip=True)
                            if unit_price_el else ""
                        ),
                    },
                    "_category_browser_card": True,
                    "_shipping_labels": shipping_labels,
                }
                item = self._next_data_to_discount_item(product)
                if item:
                    return item

        name_el = card.select_one(
            (
                ".mnemitem_goods_tit, .cunit_info .cunit_md, .title, "
                ".item_name, .prod_name, a[href*='item']"
            )
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_from_element(
            card,
            (
                ".new_price .ssg_price, .mnemitem_price_row.ty_newpr .ssg_price, "
                ".sale_price, .price .num, .opt_price"
            ),
        )
        original_price = self._extract_price_from_element(
            card, ".old_price .ssg_price, .origin_price, .normal_price"
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        link_el = card.select_one("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")
        category = card.get("data-category") or card.get("data-ctg-nm") or card.get("data-category-name") or ""
        if not category:
            category_el = card.select_one(".category, .breadcrumb, .location")
            category = category_el.get_text(" > ", strip=True) if category_el else ""

        return DiscountItem(
            name=name,
            store="이마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=build_source_attributes(
                "emart",
                source_record_key=normalize_source_key("emart", detail_url, name),
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                extra=unit_metadata.get("attributes") or {},
            ),
            category=category,
            image_url=image_url,
            detail_url=detail_url,
            event_name="이마트 할인",
        )

    def _extract_price_from_element(self, card, selectors: str) -> Optional[int]:
        """CSS 셀렉터로 가격 요소를 찾아 정수 변환."""
        for selector in selectors.split(","):
            el = card.select_one(selector.strip())
            if el:
                price = self._extract_price(el.get_text(strip=True))
                if price is not None:
                    return price
        return None

    def _parse_price_str(self, value) -> Optional[int]:
        """'29,780원' 또는 '29780' 형태의 가격 문자열을 정수로 변환."""
        if value is None:
            return None
        text = str(value).replace(",", "").replace("원", "").strip()
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
        return None

    def _extract_price(self, text: str) -> Optional[int]:
        """텍스트에서 가격(원)을 추출한다."""
        if not text:
            return None
        patterns = [
            r"(\d{1,3}(?:,\d{3})+)",
            r"(\d{3,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None

    def _to_int(self, value) -> Optional[int]:
        """안전한 정수 변환."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        """유효한 할인 상품만 필터링."""
        valid = []
        seen = set()

        for item in items:
            key = source_dedup_key(item)
            if key in seen:
                continue
            seen.add(key)

            if item.sale_price <= 0:
                continue
            if len(item.name) < 2:
                continue
            if bool((item.attributes or {}).get("external_seller")):
                continue

            valid.append(item)

        return valid
