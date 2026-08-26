"""
롯데마트 크롤러 — requests 기반 legacy 수집 경로.

롯데마트 lottemartzetta.com 공개 HTML의 window.__INITIAL_STATE__
productEntities를 순차 GET으로 수집한다. browser 렌더링/인터셉트 없이
requests.Session, UA/Referer/Accept-Language, 3초 고정 sleep으로만 동작한다.

데이터 흐름: __INITIAL_STATE__ JSON / 저장 JSON / HTML 카드 → DiscountItem → Product → DB
의존: core/ 만 (DB 저장 메서드는 호출 시 db-admin 모델을 지연 import)
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path
from urllib.parse import urlencode

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
    compute_canon_hash,
    normalize_lottemart_url,
    parse_period_fields,
    parse_unit_price,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_LIVE_GETS_MIN = 5.0
SLEEP_BETWEEN_LIVE_GETS_MAX = 6.0
SLEEP_BETWEEN_CATEGORY_GETS_MIN = 10.0
SLEEP_BETWEEN_CATEGORY_GETS_MAX = 16.0
CATEGORY_GROUP_COOLDOWN_MIN = 14.0
CATEGORY_GROUP_COOLDOWN_MAX = 21.0
CATEGORY_CACHE_TTL_SECONDS = 12 * 60 * 60
PROMO_LABEL_RE = re.compile(r"(?<!\d)(\d+)\s*\+\s*(\d+)(?!\d)")



class LottemartCrawler(CrawlerContract):
    """롯데마트 크롤러 — requests-only legacy __INITIAL_STATE__ 수집.

    검색/프로모션 HTML을 순차 GET하고 상품은 productEntities, 저장 JSON,
    일반 HTML 카드에서만 파싱한다. 브라우저 렌더링/인터셉트는 사용하지 않는다.
    """

    BASE_URL = "https://www.lottemart.com"
    ZETTA_BASE = "https://lottemartzetta.com"
    PRODUCT_PAGE_API = f"{ZETTA_BASE}/api/webproductpagews/v6/product-pages"
    SEARCH_QUERIES = ["과일", "채소", "정육", "계란", "생수", "유제품", "간편식", "라면", "과자"]
    CATEGORY_QUERIES = ["과일", "채소", "정육", "계란", "생수", "유제품", "간편식", "라면", "과자"]
    FOOD_ROOT_CATEGORY_NAMES = {
        "과일", "채소", "쌀ㆍ잡곡ㆍ견과류", "정육ㆍ계란", "수산물ㆍ건해산물",
        "델리ㆍ즉석조리", "베이커리ㆍ빵ㆍ잼", "우유ㆍ유제품", "김치ㆍ반찬ㆍ젓갈",
        "라면ㆍ통조림ㆍ즉석밥", "건면ㆍ생면ㆍ면요리", "양념ㆍ오일ㆍ분말류",
        "간편식ㆍ밀키트", "햄ㆍ어묵ㆍ맛살ㆍ닭가슴살", "과자ㆍ스낵ㆍ간식",
        "아이스크림ㆍ빙과류", "생수ㆍ음료", "커피ㆍ원두", "차ㆍ액상차ㆍ핫초코",
        "수입식품",
    }
    FOOD_NAME_KEYWORDS = (
        "감귤", "사과", "배", "바나나", "키위", "포도", "과일",
        "대파", "양파", "감자", "고구마", "상추", "채소",
        "정육", "한우", "소고기", "돼지고기", "삼겹살", "목살", "닭", "계란",
        "생수", "음료", "우유", "요거트", "치즈",
        "라면", "즉석밥", "밀키트", "두부", "김치", "과자", "커피",
    )
    DEFAULT_PRODUCT_PAGE_SIZE = 300
    MAX_ITEMS: int | None = None
    MAX_PAGES: int | None = None
    MAX_REQUESTS: int | None = None
    MAX_PAGES_PER_CATEGORY = 3
    MAX_CATEGORY_URLS = 36
    UNIQUE_ITEM_CAP = 5000
    DUPLICATE_RATIO_STOP = 0.30
    NEW_ITEM_RATIO_STOP = 0.05

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=SLEEP_BETWEEN_LIVE_GETS_MIN, delay_max=SLEEP_BETWEEN_LIVE_GETS_MAX)

    def _request_delay(self, request_type: str = "html_search") -> float:
        if request_type == "html_category":
            if self._uses_fast_test_delay():
                return self._anti_detect.get_random_delay()
            return random.uniform(SLEEP_BETWEEN_CATEGORY_GETS_MIN, SLEEP_BETWEEN_CATEGORY_GETS_MAX)
        delay_getter = getattr(self._anti_detect, "get_random_delay", None)
        if callable(delay_getter):
            try:
                delay = float(delay_getter())
                if delay > 0:
                    return delay
            except (TypeError, ValueError):
                pass
        return random.uniform(SLEEP_BETWEEN_LIVE_GETS_MIN, SLEEP_BETWEEN_LIVE_GETS_MAX)

    def _category_group_cooldown(self) -> float:
        if self._uses_fast_test_delay():
            return 0.0
        return random.uniform(CATEGORY_GROUP_COOLDOWN_MIN, CATEGORY_GROUP_COOLDOWN_MAX)

    def _uses_fast_test_delay(self) -> bool:
        try:
            return float(getattr(self._anti_detect, "_delay_max", 1.0)) <= 0.05
        except (TypeError, ValueError):
            return False

    async def _publish_progress(self, **payload: Any) -> None:
        callback = getattr(self, "progress_callback", None)
        if not callback:
            return
        try:
            result = callback(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.debug("[롯데마트] progress callback failed", exc_info=True)

    def _live_headers(self, *, referer: str | None = None) -> dict[str, str]:
        headers = self._anti_detect.get_random_headers()
        headers.update({
            "User-Agent": headers.get("User-Agent") or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer or f"{self.ZETTA_BASE}/",
        })
        return headers

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3,
                       **kwargs) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc: BaseException | None = None
        last_resp: requests.Response | None = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout, **kwargs)
                last_resp = resp
                if resp.status_code == 429:  # Rate limited — back off
                    wait = (2 ** attempt)
                    logger.warning(f"[{self.info.name}] rate limited (429), retrying in {wait:.1f}s")
                    time.sleep(wait)
                    continue
                return resp
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = (2 ** attempt)
                    logger.warning(f"[{self.info.name}] Request failed (attempt {attempt+1}/{max_retries}), "
                                   f"retrying in {wait:.1f}s: {e}")
                    time.sleep(wait)
                else:
                    raise
        if last_resp is not None:
            logger.warning(f"[{self.info.name}] rate limited after {max_retries} retries; returning last 429 response")
            return last_resp
        raise last_exc or requests.HTTPError(f"[{self.info.name}] retry exhausted without response")

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="롯데마트",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="롯데마트 할인 상품 정보 수집 (requests legacy __INITIAL_STATE__ 기반)",
            target_url=self.BASE_URL,
            strategies=["requests"],
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
        if source_url is not None:
            return await self._crawl_source_url_once(source_url)
        return await self.crawl()

    async def _crawl_saved_source_input(self, source_input: str, *, source_url: str | None = None) -> CrawlResult:
        started_at = datetime.now()
        raw_count = self.count_raw_candidates(source_input)
        parsed = await self.parse(source_input)
        valid_items = await self.validate(parsed)
        items_as_dict = [item.model_dump(mode="json") for item in valid_items]
        for _d in items_as_dict:
            _d["source"] = _d.get("source") or "lottemart"
        quality_details = summarize_discount_run(
            items_as_dict,
            raw_count=len(parsed),
            source_raw_count=raw_count,
            invalid_count=max(0, len(parsed) - len(valid_items)),
            strategy_used="saved_source_input",
            fallback_used=False,
            queries_attempted=0,
            pages_attempted=0,
            live_enabled=False,
            fixture_available=True,
        )
        quality_details["collection"] = {
            "mode": "bounded_source_input_no_db",
            "live_network_enabled": False,
            "source_url": source_url,
            "auth_bypass_attempted": False,
        }
        quality_details["source_map"] = self._source_map_manifest(quality_details)
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
            error_msg=None if valid_items else "saved source input produced zero valid LotteMart items",
            quality_score=quality_details["score"],
            quality_details=quality_details,
        )

    async def _crawl_source_url_once(self, source_url: str) -> CrawlResult:
        """Fetch one public URL via requests only; no browser escalation."""
        started_at = datetime.now()
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        raw_count = 0
        parsed: list[DiscountItem] = []
        waf_blocker: dict[str, object] | None = None
        response: requests.Response | None = None

        session = requests.Session()
        try:
            response = self._retry_request(
                source_url,
                headers=self._live_headers(referer=f"{self.ZETTA_BASE}/"),
                session=session,
                timeout=20,
                max_retries=1,
                allow_redirects=True,
            )
            if response.status_code != 200:
                message = f"source_url HTTP {response.status_code}"
                if response.status_code in {202, 403, 429} and self._is_aws_waf_challenge(response.text):
                    message += " (AWS WAF challenge)"
                    waf_blocker = self._waf_blocker_details(
                        message,
                        request_url=source_url,
                        status_code=response.status_code,
                        blocker="aws_waf_http_202" if response.status_code == 202 else f"http_{response.status_code}",
                    )
                errors.append(message)
                strategy_failures.append(StrategyFailure(
                    strategy_name="requests",
                    error_type=ErrorType.HTTP_ERROR,
                    error_msg=message,
                    status_code=response.status_code,
                ))
            else:
                raw_count = self.count_raw_candidates(response.text)
                parsed = self._extract_from_initial_state(response.text) or await self.parse(response.text)
        finally:
            session.close()

        valid_items = await self.validate(parsed)
        items_as_dict = [item.model_dump(mode="json") for item in valid_items]
        for _d in items_as_dict:
            _d["source"] = _d.get("source") or "lottemart"
        quality_details = summarize_discount_run(
            items_as_dict,
            raw_count=len(parsed),
            source_raw_count=raw_count,
            invalid_count=max(0, len(parsed) - len(valid_items)),
            errors=errors,
            strategy_used="requests",
            fallback_used=False,
            queries_attempted=1,
            pages_attempted=1,
            live_enabled=True,
            fixture_available=None,
        )
        quality_details["collection"] = {
            "mode": "bounded_live_http_no_db",
            "live_network_enabled": True,
            "source_url": source_url,
            "auth_bypass_attempted": False,
            "max_requests": 1,
            "sleep_between_live_gets_sec": f"{SLEEP_BETWEEN_LIVE_GETS_MIN}-{SLEEP_BETWEEN_LIVE_GETS_MAX}",
        }
        quality_details.setdefault("fetch", {})
        quality_details["fetch"].update({
            "renderer": "requests",
            "status_code": response.status_code if response is not None else None,
            "bytes": len(response.content) if response is not None else 0,
            "challenge_solving_attempted": False,
            "auth_bypass_attempted": False,
        })
        if waf_blocker:
            self._annotate_waf_blocker(quality_details, waf_blocker, valid_count=len(valid_items))
        quality_details["source_map"] = self._source_map_manifest(quality_details, blocker=waf_blocker)
        finished_at = datetime.now()
        return CrawlResult(
            status=CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED,
            crawler_name=self.info.name,
            strategy_used="requests",
            items_count=len(valid_items),
            items=items_as_dict,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            error_msg="; ".join(errors) if errors and not valid_items else None,
            errors=strategy_failures,
            quality_score=quality_details["score"],
            quality_details=quality_details,
        )

    async def crawl(self) -> CrawlResult:
        """롯데마트 공개 페이지를 requests-only legacy 방식으로 순차 수집한다."""
        import asyncio as _asyncio

        started_at = datetime.now()
        logger.info("[롯데마트] requests legacy 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        seen_ids: set[tuple[str, ...]] = set()
        source_raw_count = 0
        pages_attempted = 0
        waf_blocker: dict[str, object] | None = None
        last_status_code: int | None = None
        last_bytes = 0
        previous_category_fingerprints: list[set[tuple[str, ...]]] = []
        category_html_blocked = False
        category_requests_attempted = 0
        consecutive_category_waf = 0

        session = requests.Session()
        try:
            for source_request in self._build_source_requests():
                if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                    break
                if self.MAX_ITEMS is not None and len(all_items) >= self.MAX_ITEMS:
                    break

                query = str(source_request["query"])
                page_num = int(source_request["page"])
                url = str(source_request["url"])
                category_hint = str(source_request.get("category_hint") or "")
                category_path_hint = source_request.get("category_path")
                if not isinstance(category_path_hint, list):
                    category_path_hint = [category_hint] if category_hint else []
                request_type = str(source_request.get("request_type") or "html_search")
                if request_type == "html_category" and category_html_blocked:
                    logger.info("[롯데마트] %s skipped: previous category HTML request hit WAF", query)
                    continue

                try:
                    pages_in_source = 0
                    while True:
                        if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                            break
                        if self.MAX_ITEMS is not None and len(all_items) >= self.MAX_ITEMS:
                            break
                        if len(seen_ids) >= self.UNIQUE_ITEM_CAP:
                            logger.warning("[롯데마트] unique cap %d reached; stopping crawl", self.UNIQUE_ITEM_CAP)
                            break
                        page_cap = self.MAX_PAGES if self.MAX_PAGES is not None else self.MAX_PAGES_PER_CATEGORY
                        if request_type == "product_pages" and pages_in_source >= page_cap:
                            logger.info("[롯데마트] %s page cap %d reached", query, page_cap)
                            break
                        if pages_attempted > 0:
                            delay = self._request_delay(request_type)
                            logger.info(
                                "[롯데마트] waiting %.2fs before %s request #%s (%s)",
                                delay,
                                request_type,
                                pages_attempted + 1,
                                query,
                            )
                            await _asyncio.sleep(delay)
                        if request_type == "html_category":
                            category_requests_attempted += 1
                            if category_requests_attempted > 1 and (category_requests_attempted - 1) % 3 == 0:
                                cooldown = self._category_group_cooldown()
                                logger.info(
                                    "[롯데마트] category group cooldown %.2fs before %s",
                                    cooldown,
                                    query,
                                )
                                await _asyncio.sleep(cooldown)
                        pages_attempted += 1
                        pages_in_source += 1

                        headers = self._live_headers(referer=f"{self.ZETTA_BASE}/promotions")
                        if request_type == "product_pages":
                            headers.update({"Accept": "application/json,text/plain,*/*", "Origin": self.ZETTA_BASE})
                        response = self._retry_request(
                            url,
                            headers=headers,
                            session=session,
                            timeout=30,
                            max_retries=1,
                            allow_redirects=True,
                        )
                        last_status_code = response.status_code
                        last_bytes = len(response.content)

                        if response.status_code != 200:
                            is_waf = response.status_code in {202, 403, 429} and self._is_aws_waf_challenge(response.text)
                            suffix = " (AWS WAF challenge)" if is_waf else ""
                            message = f"{query} p{page_num} HTTP {response.status_code}{suffix}"
                            logger.warning("[롯데마트] %s", message)
                            errors.append(message)
                            strategy_failures.append(StrategyFailure(
                                strategy_name="requests",
                                error_type=ErrorType.HTTP_ERROR,
                                error_msg=message,
                                status_code=response.status_code,
                            ))
                            if is_waf:
                                waf_blocker = self._waf_blocker_details(
                                    message,
                                    request_url=url,
                                    query=query,
                                    page=page_num,
                                    status_code=response.status_code,
                                    blocker="aws_waf_http_202" if response.status_code == 202 else f"http_{response.status_code}",
                                )
                                if request_type == "html_category":
                                    self._queue_waf_blocked_category(source_request, response.status_code)
                                    consecutive_category_waf += 1
                                    cooldown = self._category_group_cooldown()
                                    logger.warning(
                                        "[롯데마트] category HTML blocked at %s; closing session and cooling down %.2fs (consecutive=%d)",
                                        query,
                                        cooldown,
                                        consecutive_category_waf,
                                    )
                                    session.close()
                                    session = requests.Session()
                                    await _asyncio.sleep(cooldown)
                                    if consecutive_category_waf >= 3:
                                        category_html_blocked = True
                                        logger.warning(
                                            "[롯데마트] stopping category HTML after %d consecutive WAF blocks",
                                            consecutive_category_waf,
                                        )
                            break

                        if request_type == "product_pages":
                            page_items, next_page_token, raw_candidates = self._extract_product_page_api_items(response.text)
                            source_raw_count += raw_candidates
                            if not page_items:
                                source_raw_count += self.count_raw_candidates(response.text)
                                page_items = self._extract_from_initial_state(response.text) or await self.parse(response.text)
                                next_page_token = None
                        else:
                            source_raw_count += self.count_raw_candidates(response.text)
                            page_items = self._extract_from_initial_state(response.text) or await self.parse(response.text)
                            next_page_token = None
                            if request_type == "html_category":
                                consecutive_category_waf = 0
                                self._clear_waf_blocked_category(url)
                        page_items = [item for item in page_items if self._is_food_item(item)]
                        if request_type == "html_category":
                            fingerprint = {self._item_unique_key(item) for item in page_items}
                            duplicate_shell = self._is_repeated_category_fingerprint(
                                fingerprint,
                                previous_category_fingerprints,
                            )
                            if duplicate_shell:
                                logger.warning(
                                    "[롯데마트] %s skipped: category HTML fingerprint overlaps previous category shell",
                                    query,
                                )
                                errors.append(f"{query} p{page_num} repeated category shell")
                                page_items = []
                            elif fingerprint:
                                previous_category_fingerprints.append(fingerprint)
                        if category_hint:
                            for item in page_items:
                                if request_type == "html_category":
                                    item.category = category_hint
                                elif not item.category:
                                    item.category = category_hint
                                item.attributes.setdefault("category_hint", item.category or category_hint)
                                if category_path_hint:
                                    item.attributes["mart_native_category_path"] = list(category_path_hint)
                                    item.attributes["source_category_path"] = list(category_path_hint)

                        new_count = 0
                        duplicate_count = 0
                        for item in page_items:
                            key = self._item_unique_key(item)
                            if key in seen_ids:
                                duplicate_count += 1
                                continue
                            seen_ids.add(key)
                            all_items.append(item)
                            new_count += 1
                            if self.MAX_ITEMS is not None and len(all_items) >= self.MAX_ITEMS:
                                break
                            if len(seen_ids) >= self.UNIQUE_ITEM_CAP:
                                break

                        page_total = len(page_items)
                        duplicate_ratio = (duplicate_count / page_total) if page_total else 0.0
                        new_ratio = (new_count / page_total) if page_total else 0.0
                        logger.info(
                            "[롯데마트] %s p%s: %s개 신규/%s개 중복 (%s개 중)",
                            query,
                            page_num,
                            new_count,
                            duplicate_count,
                            page_total,
                        )
                        await self._publish_progress(
                            stage="source_page_parsed",
                            items_found=len(all_items),
                            pages_attempted=pages_attempted,
                            queries_attempted=len(self.SEARCH_QUERIES),
                            source_raw_count=source_raw_count,
                            strategy_used="requests",
                        )
                        if request_type != "product_pages" or not next_page_token or not page_items:
                            break
                        if duplicate_ratio > self.DUPLICATE_RATIO_STOP or new_ratio < self.NEW_ITEM_RATIO_STOP:
                            logger.info(
                                "[롯데마트] %s p%s stop: duplicate_ratio=%.2f new_ratio=%.2f",
                                query,
                                page_num,
                                duplicate_ratio,
                                new_ratio,
                            )
                            break
                        page_num += 1
                        url = self._product_page_api_url(page_token=next_page_token)
                except Exception as exc:
                    message = f"{query} p{page_num}: {type(exc).__name__}: {exc}"
                    logger.warning("[롯데마트] %s", message)
                    errors.append(message)
                    continue
                if waf_blocker and (request_type != "html_category" or category_html_blocked):
                    break

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            for _d in items_as_dict:
                _d["source"] = _d.get("source") or "lottemart"
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(all_items),
                source_raw_count=source_raw_count,
                invalid_count=max(0, len(all_items) - len(valid_items)),
                errors=errors,
                strategy_used="requests",
                fallback_used=False,
                queries_attempted=len(self.SEARCH_QUERIES),
                pages_attempted=pages_attempted,
                live_enabled=True,
            )
            quality_details.setdefault("fetch", {})
            quality_details["fetch"].update({
                "renderer": "requests",
                "fallback_used": False,
                "status_code": last_status_code,
                "bytes": last_bytes,
                "sleep_between_live_gets_sec": f"{SLEEP_BETWEEN_LIVE_GETS_MIN}-{SLEEP_BETWEEN_LIVE_GETS_MAX}",
                "challenge_solving_attempted": False,
                "auth_bypass_attempted": False,
            })
            quality_details["collection"] = {
                "mode": "requests_legacy_public_no_db",
                "live_network_enabled": True,
                "auth_bypass_attempted": False,
                "sleep_between_live_gets_sec": f"{SLEEP_BETWEEN_LIVE_GETS_MIN}-{SLEEP_BETWEEN_LIVE_GETS_MAX}",
            }
            if waf_blocker:
                self._annotate_waf_blocker(quality_details, waf_blocker, valid_count=len(valid_items))
            quality_details["source_map"] = self._source_map_manifest(quality_details, blocker=waf_blocker)

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="requests",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_msg="; ".join(errors) if errors and not valid_items else None,
                errors=strategy_failures,
                quality_score=quality_details["score"],
                quality_details=quality_details,
            )
        finally:
            session.close()

    def _is_food_item(self, item: DiscountItem) -> bool:
        category = str(item.category or "").strip()
        attrs = item.attributes or {}
        category_path = attrs.get("mart_native_category_path") or attrs.get("source_category_path") or []
        if isinstance(category_path, list) and category_path:
            category = str(category_path[0] or category).strip()
        if category in self.FOOD_ROOT_CATEGORY_NAMES:
            return True
        if any(category.startswith(name) for name in self.FOOD_ROOT_CATEGORY_NAMES):
            return True
        if not category:
            name = str(item.name or "")
            return any(keyword in name for keyword in self.FOOD_NAME_KEYWORDS)
        return False

    def _product_page_api_params(self, *, page_token: str | None = None) -> dict[str, str | int | list[str]]:
        params: dict[str, str | int | list[str]] = {
            "maxProductsToDecorate": self.DEFAULT_PRODUCT_PAGE_SIZE,
            "maxPageSize": self.DEFAULT_PRODUCT_PAGE_SIZE,
            "tag": ["web", "category-item"],
        }
        if page_token:
            params["pageToken"] = page_token
        else:
            params["includeAdditionalPageInfo"] = "true"
        return params

    def _product_page_api_url(self, *, page_token: str | None = None) -> str:
        return f"{self.PRODUCT_PAGE_API}?{urlencode(self._product_page_api_params(page_token=page_token), doseq=True)}"

    def _item_unique_key(self, item: DiscountItem) -> tuple[str, str]:
        attrs = item.attributes or {}
        for value in (
            attrs.get("mart_native_code"),
            attrs.get("source_record_key"),
            item.detail_url,
            attrs.get("source_url"),
        ):
            text = str(value or "").strip()
            if text:
                return ("id_or_url", text)
        return ("name_store", f"{item.name}|{item.store}")

    def _extract_product_page_api_items(self, raw_data: str) -> tuple[list[DiscountItem], str | None, int]:
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            return [], None, 0
        if not isinstance(payload, dict):
            return [], None, 0
        products: list[dict] = []
        for group in payload.get("productGroups") or []:
            if not isinstance(group, dict):
                continue
            for key in ("decoratedProducts", "products"):
                rows = group.get(key)
                if isinstance(rows, list):
                    products.extend(row for row in rows if isinstance(row, dict))
        items = [item for product in products if (item := self._api_product_to_discount_item(product))]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        next_page_token = metadata.get("nextPageToken") or payload.get("nextPageToken")
        return items, str(next_page_token) if next_page_token else None, len(products)

    def _build_source_requests(self) -> list[dict[str, str | int | list[str]]]:
        """Build bounded real product/category URLs instead of repeated search pages."""
        override_requests = getattr(self, "_source_requests_override", None)
        if isinstance(override_requests, list):
            return override_requests
        api_request: dict[str, str | int | list[str]] = {
            "query": "롯데마트 행사상품 API",
            "page": 1,
            "category_hint": "",
            "request_type": "product_pages",
            "url": self._product_page_api_url(),
        }
        if self._uses_fast_test_delay() and not getattr(self, "_include_categories_in_fast_tests", False):
            return [api_request]
        category_requests = self._build_category_requests_from_homepage()
        if category_requests:
            return [api_request, *category_requests]
        return [api_request]

    async def crawl_waf_blocked_categories(self) -> CrawlResult:
        queued = self.load_waf_blocked_categories()
        if not queued:
            now = datetime.now()
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                strategy_used="requests_waf_retry",
                items_count=0,
                items=[],
                started_at=now,
                finished_at=now,
                duration_seconds=0,
                error_msg="no WAF-blocked Lotte categories queued",
                errors=[],
                quality_score=0,
                quality_details={
                    "collection": {"mode": "waf_blocked_category_retry", "queued_count": 0},
                    "alerts": ["no_waf_blocked_categories"],
                },
            )

        self._source_requests_override = [
            {
                "query": str(row.get("query") or row.get("category_hint") or "WAF 재시도"),
                "page": 1,
                "category_hint": str(row.get("category_hint") or row.get("query") or ""),
                "category_path": row.get("category_path") if isinstance(row.get("category_path"), list) else [],
                "request_type": "html_category",
                "url": str(row.get("url")),
                "retry_reason": "aws_waf",
            }
            for row in queued
            if row.get("url")
        ]
        try:
            result = await self.crawl()
            if isinstance(result.quality_details, dict):
                result.quality_details.setdefault("collection", {})
                result.quality_details["collection"].update({
                    "mode": "waf_blocked_category_retry",
                    "queued_count": len(queued),
                })
            return result
        finally:
            self._source_requests_override = None

    def list_category_requests(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        requests_to_make = [] if refresh else self._load_cached_category_requests(max_age_seconds=None)
        if not requests_to_make:
            requests_to_make = self._build_category_requests_from_homepage()
        return [dict(row) for row in requests_to_make]

    async def crawl_selected_category(self) -> CrawlResult:
        source_request = getattr(self, "_selected_category_request", None)
        if not isinstance(source_request, dict) or not source_request.get("url"):
            now = datetime.now()
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                strategy_used="requests_selected_category",
                items_count=0,
                items=[],
                started_at=now,
                finished_at=now,
                duration_seconds=0,
                error_msg="no Lotte category selected",
                errors=[],
                quality_score=0,
                quality_details={
                    "collection": {"mode": "selected_category", "selected": None},
                    "alerts": ["no_lotte_category_selected"],
                },
            )
        self._source_requests_override = [source_request]
        try:
            result = await self.crawl()
            if isinstance(result.quality_details, dict):
                result.quality_details.setdefault("collection", {})
                result.quality_details["collection"].update({
                    "mode": "selected_category",
                    "selected": {
                        "query": source_request.get("query"),
                        "category_hint": source_request.get("category_hint"),
                        "category_path": source_request.get("category_path"),
                        "url": source_request.get("url"),
                    },
                })
            return result
        finally:
            self._source_requests_override = None
            self._selected_category_request = None

    def _build_category_requests_from_homepage(self) -> list[dict[str, str | int | list[str]]]:
        """Discover LotteMart Zetta category IDs from the homepage initial state."""
        cached = self._load_cached_category_requests(max_age_seconds=CATEGORY_CACHE_TTL_SECONDS)
        if cached:
            logger.info("[롯데마트] using cached food category URLs: %d", len(cached))
            return cached
        try:
            response = self._retry_request(
                f"{self.ZETTA_BASE}/",
                headers=self._live_headers(referer=f"{self.ZETTA_BASE}/"),
                timeout=20,
                max_retries=1,
                allow_redirects=True,
            )
        except Exception as exc:
            logger.warning("[롯데마트] category discovery homepage fetch failed: %s", exc)
            return []
        if response.status_code != 200:
            logger.warning("[롯데마트] category discovery homepage HTTP %s", response.status_code)
            stale = self._load_cached_category_requests(max_age_seconds=None)
            if stale:
                logger.warning("[롯데마트] using stale cached category URLs after homepage failure: %d", len(stale))
            return stale
        requests_to_make = self._extract_category_requests(response.text)
        if requests_to_make:
            self._save_category_requests_cache(requests_to_make)
        return requests_to_make

    def _category_cache_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "data" / "cache" / "lottemart_category_requests.json"

    def _waf_queue_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "data" / "cache" / "lottemart_waf_blocked_categories.json"

    def load_waf_blocked_categories(self) -> list[dict[str, Any]]:
        path = self._waf_queue_path()
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("blocked") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("url"):
                continue
            cleaned.append(row)
        return cleaned

    def _save_waf_blocked_categories(self, rows: list[dict[str, Any]]) -> None:
        path = self._waf_queue_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "blocked": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("[롯데마트] WAF retry queue write failed: %s", exc)

    def _queue_waf_blocked_category(self, source_request: dict[str, Any], status_code: int) -> None:
        if source_request.get("request_type") != "html_category":
            return
        url = str(source_request.get("url") or "").strip()
        if not url:
            return
        rows = self.load_waf_blocked_categories()
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if row.get("url") == url:
                row["last_blocked_at"] = now
                row["attempts"] = int(row.get("attempts") or 0) + 1
                row["status_code"] = status_code
                self._save_waf_blocked_categories(rows)
                return
        rows.append({
            "url": url,
            "query": source_request.get("query"),
            "category_hint": source_request.get("category_hint"),
            "category_path": source_request.get("category_path") if isinstance(source_request.get("category_path"), list) else [],
            "status_code": status_code,
            "attempts": 1,
            "first_blocked_at": now,
            "last_blocked_at": now,
        })
        self._save_waf_blocked_categories(rows)

    def _clear_waf_blocked_category(self, url: str) -> None:
        rows = self.load_waf_blocked_categories()
        remaining = [row for row in rows if row.get("url") != url]
        if len(remaining) != len(rows):
            self._save_waf_blocked_categories(remaining)

    def _load_cached_category_requests(self, *, max_age_seconds: int | None) -> list[dict[str, str | int | list[str]]]:
        path = self._category_cache_path()
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        created_at = float(payload.get("created_at") or 0)
        if max_age_seconds is not None and (time.time() - created_at) > max_age_seconds:
            return []
        requests_data = payload.get("requests")
        if not isinstance(requests_data, list):
            return []
        cleaned: list[dict[str, str | int | list[str]]] = []
        for row in requests_data:
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            query = row.get("query")
            if not isinstance(url, str) or not isinstance(query, str):
                continue
            category_path = row.get("category_path")
            if not isinstance(category_path, list):
                category_path = [str(row.get("category_hint") or query)]
            cleaned.append(
                {
                    "query": query,
                    "page": int(row.get("page") or 1),
                    "category_hint": str(row.get("category_hint") or (category_path[-1] if category_path else query)),
                    "category_path": [str(part) for part in category_path if str(part).strip()],
                    "request_type": "html_category",
                    "url": url,
                }
            )
        return cleaned

    def _save_category_requests_cache(self, requests_to_make: list[dict[str, str | int | list[str]]]) -> None:
        path = self._category_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "created_at": time.time(),
                        "source": self.ZETTA_BASE,
                        "requests": requests_to_make,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("[롯데마트] category cache write failed: %s", exc)

    def _extract_category_requests(self, html: str) -> list[dict[str, str | int | list[str]]]:
        json_str = self._extract_initial_state_json(html)
        if not json_str:
            return []
        try:
            payload = json.loads(json_str)
        except json.JSONDecodeError:
            return []
        categories_state = (
            payload.get("data", {}).get("categories", {})
            if isinstance(payload.get("data"), dict)
            else {}
        )
        categories = categories_state.get("categories") if isinstance(categories_state, dict) else {}
        root_ids = categories_state.get("root") if isinstance(categories_state, dict) else []
        if not isinstance(categories, dict) or not isinstance(root_ids, list):
            return []

        requests_to_make: list[dict[str, str | int | list[str]]] = []
        seen_ids: set[str] = set()

        def add_category(category_id: str, path: list[str]) -> None:
            if not category_id or category_id in seen_ids:
                return
            if len(requests_to_make) >= self.MAX_CATEGORY_URLS:
                return
            seen_ids.add(category_id)
            requests_to_make.append(
                {
                    "query": " > ".join(path),
                    "page": 1,
                    "category_hint": path[-1] if path else "",
                    "category_path": path,
                    "request_type": "html_category",
                    "url": f"{self.ZETTA_BASE}/categories/{category_id}",
                }
            )

        food_roots: list[tuple[str, dict[str, Any], str]] = []
        for root_id in root_ids:
            root = categories.get(root_id)
            if not isinstance(root, dict):
                continue
            root_name = str(root.get("name") or "").strip()
            if root_name not in self.FOOD_ROOT_CATEGORY_NAMES:
                continue
            food_roots.append((str(root_id), root, root_name))

        for root_id, _root, root_name in food_roots:
            add_category(str(root_id), [root_name])

        for _root_id, root, root_name in food_roots:
            for child_id in root.get("children") or []:
                child = categories.get(child_id)
                if not isinstance(child, dict):
                    continue
                child_name = str(child.get("name") or "").strip()
                if child_name:
                    add_category(str(child_id), [root_name, child_name])
                if len(requests_to_make) >= self.MAX_CATEGORY_URLS:
                    break
            if len(requests_to_make) >= self.MAX_CATEGORY_URLS:
                break

        logger.info("[롯데마트] discovered %d food category URLs", len(requests_to_make))
        return requests_to_make

    def _is_repeated_category_fingerprint(
        self,
        fingerprint: set[tuple[str, ...]],
        previous_fingerprints: list[set[tuple[str, ...]]],
    ) -> bool:
        if len(fingerprint) < 20:
            return False
        for previous in previous_fingerprints:
            if not previous:
                continue
            overlap = len(fingerprint & previous) / max(1, min(len(fingerprint), len(previous)))
            if overlap >= 0.85:
                return True
        return False

    def _source_map_manifest(self, quality_details: dict, blocker: dict[str, object] | None = None) -> dict[str, object]:
        return build_source_map_manifest(
            "lottemart",
            search_queries=self.SEARCH_QUERIES,
            category_queries=self.CATEGORY_QUERIES,
            max_pages=self.MAX_PAGES,
            max_requests=self.MAX_REQUESTS,
            max_items=self.MAX_ITEMS,
            parser_contract="lottemart_initial_state_fixture.v1",
            request_strategy="requests_initial_state_legacy",
            parser_inputs=["window.__INITIAL_STATE__", "embedded_json", "product_card_html"],
            quality=quality_details,
            blocker=dict(blocker) if blocker else None,
        )

    def _is_aws_waf_challenge(self, html: str) -> bool:
        """Return true for CloudFront/AWS WAF challenge shells, not product pages."""
        sample = (html or "")[:5000].lower()
        return "awswaf" in sample or "aws-waf" in sample or "aws waf" in sample

    def _waf_blocker_details(
        self,
        message: str,
        *,
        request_url: str,
        query: str | None = None,
        page: int | None = None,
        status_code: int | None = 202,
        blocker: str = "aws_waf_http_202",
    ) -> dict[str, object]:
        return {
            "blocked": True,
            "blocker": blocker,
            "status_code": status_code,
            "message": message,
            "request_url": request_url,
            "query": query,
            "page": page,
            "auth_bypass_attempted": False,
            "challenge_solving_attempted": False,
            "credential_use_attempted": False,
        }

    def _annotate_waf_blocker(
        self,
        quality_details: dict,
        waf_blocker: dict[str, object],
        *,
        valid_count: int,
    ) -> None:
        fetch = quality_details.setdefault("fetch", {})
        fetch.update(waf_blocker)
        alerts = quality_details.setdefault("alerts", [])
        source_alert = (
            "source_blocked_aws_waf_202"
            if waf_blocker.get("blocker") == "aws_waf_http_202"
            else "source_blocked_public_http"
        )
        for alert in (source_alert, "partial_lottemart_waf_blocker"):
            if alert not in alerts:
                alerts.append(alert)
        quality_summary = quality_details.setdefault("quality_summary", {})
        quality_summary["status"] = "blocked" if valid_count < 200 else quality_summary.get("status", "warning")
        quality_summary["registered_vs_collecting"] = quality_summary["status"]
        diagnostics = quality_details.setdefault("operator_diagnostics", [])
        diagnostics.append(
            {
                "code": str(waf_blocker.get("blocker") or "source_blocked"),
                "severity": "error" if valid_count < 200 else "warning",
                "stage": "source_fetch",
                "message": waf_blocker["message"],
                "counts": {
                    "valid": valid_count,
                    "target_minimum": 200,
                },
                "blocked": True,
                "status_code": waf_blocker.get("status_code"),
                "auth_bypass_attempted": False,
                "challenge_solving_attempted": False,
                "credential_use_attempted": False,
            }
        )
        quality_details["operator_diagnostics"] = diagnostics
        quality_summary["diagnostic_count"] = len(diagnostics)

    def _extract_from_initial_state(self, html: str) -> list[DiscountItem]:
        """window.__INITIAL_STATE__ Redux 상태에서 productEntities를 추출한다.

        lottemartzetta.com은 서버사이드에서 Redux 상태를 window.__INITIAL_STATE__에 직렬화한다.
        productEntities는 UUID 키 → 상품 데이터 dict 구조이며,
        price.original.amount / price.current.amount로 원가/할인가를 추출한다.
        """
        items: list[DiscountItem] = []

        json_str = self._extract_initial_state_json(html)
        if not json_str:
            return items
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[롯데마트] __INITIAL_STATE__ JSON 파싱 실패")
            return items

        product_entities = self._find_product_entities(data)

        if not product_entities:
            del data  # Free large JSON from memory
            return items

        logger.info(f"[롯데마트] __INITIAL_STATE__ productEntities: {len(product_entities)}개")

        for product_id, product in product_entities.items():
            item = self._entity_to_discount_item(product, product_id)
            if item:
                items.append(item)

        del data  # Free large JSON from memory
        return items

    def count_raw_candidates(self, raw_data: str) -> int:
        """Count source candidate rows before DiscountItem parsing/validation."""
        json_str = self._extract_initial_state_json(raw_data)
        if json_str:
            try:
                data = json.loads(json_str)
                product_entities = self._find_product_entities(data)
                if isinstance(product_entities, dict):
                    return len(product_entities)
            except json.JSONDecodeError:
                pass
        try:
            data = json.loads(raw_data)
            if isinstance(data, dict):
                product_entities = self._find_product_entities(data)
                if isinstance(product_entities, dict):
                    return len(product_entities)
            if isinstance(data, list):
                return len(data)
        except json.JSONDecodeError:
            pass
        json_items = self._extract_json_items(raw_data)
        if json_items:
            return len(json_items)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            count = len(soup.select(".product-card-container, .product-item, .goods_item, .event_item, .item_box, .prod_wrap"))
            del soup
            return count
        except Exception:
            return 0

    def _extract_initial_state_json(self, html: str) -> str:
        """Extract a LotteMart SPA initial-state object from saved or rendered HTML."""
        match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
        if not match:
            return ""
        start = match.end()
        script_end = html.find("</script>", start)
        candidate = html[start:script_end if script_end >= 0 else len(html)].strip()
        if not candidate:
            return ""
        try:
            _, end = json.JSONDecoder().raw_decode(candidate)
            return candidate[:end]
        except json.JSONDecodeError:
            return candidate.rstrip().rstrip(";")

    def _find_product_entities(
        self,
        data: Any,
        *,
        _seen: set[int] | None = None,
        _depth: int = 0,
        _max_depth: int = 40,
    ) -> dict[str, Any]:
        """Find productEntities even when an operator-saved export wraps app state."""
        if not isinstance(data, dict):
            return {}
        if _depth > _max_depth:
            return {}
        _seen = _seen or set()
        object_id = id(data)
        if object_id in _seen:
            return {}
        _seen.add(object_id)
        direct_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        products = direct_data.get("products") if isinstance(direct_data.get("products"), dict) else {}
        if isinstance(products.get("productEntities"), dict):
            return products["productEntities"]
        if isinstance(data.get("productEntities"), dict):
            return data["productEntities"]
        for value in data.values():
            if isinstance(value, dict):
                found = self._find_product_entities(value, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
                if found:
                    return found
        return {}

    def _extract_lottemart_ean13(self, product: dict | None = None, *, href: str = "") -> tuple[str, str]:
        product = product or {}
        for key in ("retailerProductId", "stdGoodsCd"):
            ean13 = self._coerce_lottemart_ean13(product.get(key))
            if ean13:
                return ean13, key
        href_candidates = [
            href,
            product.get("goodsUrl"),
            product.get("detail_url"),
            product.get("detailUrl"),
            product.get("productUrl"),
            product.get("url"),
        ]
        for candidate in href_candidates:
            ean13 = self._extract_ean13_from_lottemart_url(candidate)
            if ean13:
                return ean13, "href"
        return "", ""

    @staticmethod
    def _coerce_lottemart_ean13(value: Any) -> str:
        text = str(value or "").strip()
        if text.upper().startswith("OS"):
            text = text[2:]
        return text if re.fullmatch(r"\d{13}", text) else ""

    @staticmethod
    def _extract_ean13_from_lottemart_url(value: Any) -> str:
        match = re.search(r"(?:^|/)OS(\d{13})(?:/|$|[?#])", str(value or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _extract_promo_label(*values: Any) -> str | None:
        for value in values:
            text = str(value or "")
            match = PROMO_LABEL_RE.search(text)
            if match:
                return f"{match.group(1)}+{match.group(2)}"
        return None

    @staticmethod
    def _clean_product_name(name: str) -> str:
        text = str(name or "").strip()
        # Remove only leading promo bracket labels. Nested ']' can appear in malformed source text,
        # so look for the final closing bracket before the first product-space run.
        if text.startswith("[") and "]" in text[:80]:
            text = re.sub(r"^\[[^\n]{1,80}\]\s*", "", text).strip() or text
        return text

    def _lottemart_g1_attributes(
        self,
        *,
        ean13: str,
        ean_source_key: str,
        detail_url: str,
        image_url: str = "",
        category: str = "",
        category_path: list[str] | None = None,
        period: str = "",
        unit_metadata: dict[str, Any] | None = None,
        name: str = "",
        brand: str = "",
        unit_text: str = "",
        promo_label: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        unit_metadata = unit_metadata or {}
        source_extra = {**(unit_metadata.get("attributes") or {}), **(extra or {})}
        if brand:
            source_extra["brand"] = brand
        unit_price, unit_price_basis = parse_unit_price(unit_text or "")
        if unit_price is not None:
            source_extra["unit_price"] = int(unit_price) if float(unit_price).is_integer() else unit_price
        if unit_price_basis:
            source_extra["unit_price_basis"] = unit_price_basis
        if promo_label:
            source_extra["promo_label"] = promo_label
        source_extra.update(
            {
                "source": "lottemart",
                "mart_native_code": ean13,
                "ean_source_key": ean_source_key,
                "external_seller": False,
                "canonical_url": detail_url,
                "canon_hash": compute_canon_hash(
                    brand or None,
                    name,
                    unit_metadata.get("package_quantity"),
                    unit_metadata.get("package_unit") or None,
                ),
            }
        )
        return build_source_attributes(
            "lottemart",
            source_record_key=ean13,
            detail_url=detail_url,
            image_url=image_url,
            category=category,
            category_path=category_path,
            period=period,
            extra=source_extra,
        )

    def _entity_to_discount_item(self, product: dict, product_id: str = "") -> Optional[DiscountItem]:
        """lottemartzetta productEntity → DiscountItem 변환.

        필드 매핑:
          name → 상품명 (프로모션 접두사 제거)
          price.current.amount → 할인가
          price.original.amount → 원가
          image.src → 이미지 URL
          categoryPath → 카테고리
          size.value → 단위
          offer.description → 행사명
        """
        name = product.get("name", "")
        if not name or len(name) < 2:
            return None

        # 프로모션 접두사 제거: "[농할할인가 7,490원]" 같은 부분
        clean_name = self._clean_product_name(name)
        if not clean_name or len(clean_name) < 2:
            clean_name = name

        # 가격 추출
        price_data = product.get("price", {})
        current = price_data.get("current", {})
        original = price_data.get("original", {})

        sale_price = self._parse_price_str(current.get("amount"))
        original_price = self._parse_price_str(original.get("amount"))

        if not sale_price or sale_price <= 0:
            return None

        # 할인율 계산
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 이미지 URL
        image_data = product.get("image", {})
        image_url = image_data.get("src", "")

        # 카테고리 (categoryPath 배열에서 첫 번째)
        category_path = product.get("categoryPath", [])
        category = category_path[0] if category_path else ""

        # 단위 (size.value)
        size = product.get("size", {})
        unit = size.get("value", "") if isinstance(size, dict) else ""

        # 행사 정보 (offer.description)
        offer = product.get("offer", {})
        event_name = "롯데마트 할인"
        if isinstance(offer, dict) and offer.get("description"):
            event_name = offer["description"]
        promo_label = self._extract_promo_label(event_name, name, product.get("badges"), product.get("promotions"))

        ean13, ean_source_key = self._extract_lottemart_ean13(product)
        if not ean13:
            return None
        detail_url = normalize_lottemart_url(ean13)

        # 브랜드
        brand = product.get("brand", "")
        unit_metadata = normalize_unit_metadata(
            name=clean_name,
            sale_price=sale_price,
            raw_unit=unit,
        )
        display_unit = unit_metadata.get("display_unit") or unit
        valid_from, valid_until, period = parse_period_fields(product)
        attributes = self._lottemart_g1_attributes(
            ean13=ean13,
            ean_source_key=ean_source_key,
            detail_url=detail_url,
            image_url=image_url,
            category=category,
            category_path=category_path,
            period=period,
            unit_metadata=unit_metadata,
            name=clean_name,
            brand=brand,
            unit_text=unit,
            promo_label=promo_label,
        )

        return DiscountItem(
            name=clean_name,
            store="롯데마트",
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
            event_name=event_name,
            promo_label=promo_label,
            promo_type="buy_x_get_y" if promo_label else None,
            valid_from=valid_from,
            valid_until=valid_until,
            image_url=image_url,
            detail_url=detail_url,
        )

    def _api_product_to_discount_item(self, prod: dict) -> Optional[DiscountItem]:
        """LotteMart product API shaped JSON row → DiscountItem (no live API call)."""
        name = (prod.get("name") or "").strip()
        if not name or len(name) < 2:
            return None
        clean_name = self._clean_product_name(name) or name
        price_obj = prod.get("price") if isinstance(prod.get("price"), dict) else {}
        sale_price = self._to_int(price_obj.get("amount") or prod.get("salePrice") or prod.get("price"))
        if not sale_price or sale_price <= 0:
            return None
        ean13, ean_source_key = self._extract_lottemart_ean13(prod)
        if not ean13:
            return None
        detail_url = normalize_lottemart_url(ean13)
        image_obj = prod.get("image") if isinstance(prod.get("image"), dict) else {}
        image_url = image_obj.get("src") or prod.get("imageUrl") or ""
        promotions = prod.get("promotions") if isinstance(prod.get("promotions"), list) else []
        event_name = "롯데마트 할인"
        if promotions and isinstance(promotions[0], dict):
            event_name = promotions[0].get("description") or event_name
        promo_label = self._extract_promo_label(event_name, name, promotions)
        pack_size = (prod.get("packSizeDescription") or "").strip()
        unit_metadata = normalize_unit_metadata(name=clean_name, sale_price=sale_price, raw_unit=pack_size)
        display_unit = unit_metadata.get("display_unit") or pack_size
        category_path = prod.get("categoryPath") if isinstance(prod.get("categoryPath"), list) else []
        category = prod.get("categoryName") or prod.get("category") or (category_path[0] if category_path else "")
        return DiscountItem(
            name=clean_name,
            store="롯데마트",
            original_price=None,
            sale_price=sale_price,
            discount_percent=None,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=self._lottemart_g1_attributes(
                ean13=ean13,
                ean_source_key=ean_source_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                category_path=category_path,
                unit_metadata=unit_metadata,
                name=clean_name,
                brand=prod.get("brand", ""),
                unit_text=pack_size,
                promo_label=promo_label,
            ),
            category=category,
            image_url=image_url,
            detail_url=detail_url,
            event_name=event_name,
            promo_label=promo_label,
            promo_type="buy_x_get_y" if promo_label else None,
        )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML/JSON 응답에서 할인 상품을 파싱한다."""
        items: list[DiscountItem] = []

        # 1) __INITIAL_STATE__ 추출 (lottemartzetta.com)
        state_items = self._extract_from_initial_state(raw_data)
        if state_items:
            return state_items

        # 2) product-page API JSON 추출 시도
        api_items, _next_page_token, _raw_count = self._extract_product_page_api_items(raw_data)
        if api_items:
            return api_items

        # 3) JSON 데이터 블록 추출 시도
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product)
                if item:
                    items.append(item)
            return items

        # 4) HTML 파싱 fallback
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_data, "html.parser")
            items = self._parse_html(soup)
            del soup  # Free parsed HTML tree from memory
        except Exception as e:
            logger.warning(f"[롯데마트] HTML 파싱 실패: {e}")

        return items

    def _extract_json_items(self, raw_data: str) -> list[dict]:
        """페이지 내 임베디드 JSON 데이터 추출."""
        try:
            payload = json.loads(raw_data)
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, dict):
                product_entities = self._find_product_entities(payload)
                if product_entities:
                    return [
                        {"_source_product_id": product_id, **product}
                        for product_id, product in product_entities.items()
                        if isinstance(product, dict)
                    ]
                extracted = self._extract_product_lists(payload)
                if extracted:
                    return extracted
        except json.JSONDecodeError:
            pass
        patterns = [
            r'var\s+(?:itemList|prodList|goodsList)\s*=\s*(\[.*?\]);',
            r'"itemList"\s*:\s*(\[.*?\])',
            r'"goodsList"\s*:\s*(\[.*?\])',
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

    def _extract_product_lists(
        self,
        payload: Any,
        *,
        _seen: set[int] | None = None,
        _depth: int = 0,
        _max_depth: int = 40,
    ) -> list[dict]:
        """Extract product rows from common saved-source JSON envelopes."""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        if _depth > _max_depth:
            return []
        _seen = _seen or set()
        object_id = id(payload)
        if object_id in _seen:
            return []
        _seen.add(object_id)
        for key in ("items", "products", "records", "raw_items", "productList", "goodsList", "itemList"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = self._extract_product_lists(value, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
                if nested:
                    return nested
        for value in payload.values():
            nested = self._extract_product_lists(value, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
            if nested:
                return nested
        return []

    def _json_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """JSON 상품 데이터 → DiscountItem 변환."""
        name = (
            product.get("goodsNm")
            or product.get("itemNm")
            or product.get("prodNm")
            or product.get("productName")
            or product.get("title")
            or product.get("name", "")
        )
        if not name or len(name) < 2:
            return None

        price = product.get("price") if isinstance(product.get("price"), dict) else {}
        sale_price = self._to_int(
            product.get("salePrice")
            or product.get("sellprc")
            or product.get("sale_price")
            or product.get("currentPrice")
            or (price.get("current") or {}).get("amount")
            or (product.get("price") if not isinstance(product.get("price"), dict) else None)
        )
        original_price = self._to_int(
            product.get("originPrice")
            or product.get("norprc")
            or product.get("original_price")
            or product.get("originalPrice")
            or (price.get("original") or {}).get("amount")
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        image = product.get("image") if isinstance(product.get("image"), dict) else {}
        image_url = self._absolute_url(
            product.get("imgUrl")
            or product.get("goodsImg")
            or product.get("imageUrl")
            or image.get("src")
            or "",
            self.ZETTA_BASE,
        )
        category_path = product.get("categoryPath") if isinstance(product.get("categoryPath"), list) else None
        category = product.get("categoryNm") or product.get("ctgNm") or (category_path[0] if category_path else "")
        ean13, ean_source_key = self._extract_lottemart_ean13(product)
        if not ean13:
            return None
        detail_url = normalize_lottemart_url(ean13)
        valid_from, valid_until, period = parse_period_fields(product)
        size = product.get("size") if isinstance(product.get("size"), dict) else {}
        raw_unit = product.get("unit") or size.get("value") or product.get("size") or product.get("capacity") or ""
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit
        event_name = product.get("eventNm") or product.get("eventName") or "롯데마트 할인"
        promo_label = self._extract_promo_label(event_name, name, product.get("badge"), product.get("promotion"), product.get("promotions"))

        return DiscountItem(
            name=name,
            store="롯데마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=self._lottemart_g1_attributes(
                ean13=ean13,
                ean_source_key=ean_source_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                category_path=category_path,
                period=period,
                unit_metadata=unit_metadata,
                name=name,
                unit_text=str(raw_unit or ""),
                promo_label=promo_label,
            ),
            category=category,
            event_name=event_name,
            promo_label=promo_label,
            promo_type="buy_x_get_y" if promo_label else None,
            valid_from=valid_from,
            valid_until=valid_until,
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_html(self, soup) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다 (fallback)."""
        items: list[DiscountItem] = []

        product_cards = soup.select(
            ".product-card-container, .product-item, .goods_item, .event_item, .item_box, .prod_wrap"
        )
        logger.info(f"[롯데마트] HTML 상품 카드: {len(product_cards)}개")

        for card in product_cards:
            try:
                item = self._parse_product_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[롯데마트] 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_product_card(self, card) -> Optional[DiscountItem]:
        """개별 상품 카드 HTML → DiscountItem."""
        name_el = card.select_one(
            ".product-name, .goods_name, .item_name, .prod_name, a[href*='goods'], "
            "[class*='name'], [class*='title'], h3, h4, strong"
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_from_element(
            card, ".sale_price, .price .num, .discount_price, .spc_price"
        )
        original_price = self._extract_price_from_element(
            card, ".origin_price, .normal_price, .org_price, .before_price"
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

        link_el = card.select_one("a[href*='/products/OS']") or card.select_one("a[href*='products/OS']")
        href = link_el.get("href", "") if link_el else ""
        ean13, ean_source_key = self._extract_lottemart_ean13(href=href)
        if not ean13:
            return None
        detail_url = normalize_lottemart_url(ean13)
        card_text = card.get_text(" ", strip=True)
        promo_label = self._extract_promo_label(card_text, name)
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")
        category = card.get("data-category") or card.get("data-ctg-nm") or card.get("data-category-name") or ""
        if not category:
            category_el = card.select_one(".category, .breadcrumb, .location")
            category = category_el.get_text(" > ", strip=True) if category_el else ""
        category_path = [part.strip() for part in re.split(r"\s*>\s*", category) if part.strip()]

        return DiscountItem(
            name=name,
            store="롯데마트",
            original_price=original_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            unit=display_unit or "",
            display_unit=display_unit or "",
            package_quantity=unit_metadata.get("package_quantity"),
            package_unit=unit_metadata.get("package_unit") or "",
            price_per_100g=unit_metadata.get("price_per_100g"),
            attributes=self._lottemart_g1_attributes(
                ean13=ean13,
                ean_source_key=ean_source_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                category_path=category_path,
                unit_metadata=unit_metadata,
                name=name,
                unit_text=card_text,
                promo_label=promo_label,
            ),
            category=category,
            promo_label=promo_label,
            promo_type="buy_x_get_y" if promo_label else None,
            image_url=image_url,
            detail_url=detail_url,
            event_name="롯데마트 할인",
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
        """'29,780' 또는 '29780' 형태의 가격 문자열을 정수로 변환."""
        if value is None:
            return None
        text = str(value).replace(",", "").replace("원", "").strip()
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
        return None

    def _absolute_url(self, url: str, base_url: str) -> str:
        """Normalize source-relative URLs while preserving absolute URLs."""
        return absolute_url(url, base_url)

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
        if isinstance(value, str):
            value = value.replace(",", "").replace("원", "").strip()
            match = re.search(r"\d+", value)
            if match:
                value = match.group(0)
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

            valid.append(item)

        return valid
