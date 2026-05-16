"""
롯데마트 크롤러 — 전단지 및 할인 행사 상품 정보 수집.

롯데마트는 lottemartzetta.com SPA로 리다이렉트되며,
서버사이드에서 window.__INITIAL_STATE__ (Redux 상태)에 상품 데이터를 포함한다.
검색 페이지(/search?query=...)를 통해 상품 데이터를 수집하고,
__INITIAL_STATE__의 productEntities에서 직접 추출한다.

수집 전략:
  - 검색어별 1~3초 랜덤 딜레이
  - HTTP 요청 실패 시 일반 Playwright 브라우저 렌더링으로 폴백
  - AWS WAF/접근제어 응답은 우회하지 않고 차단 진단으로 기록

데이터 흐름: __INITIAL_STATE__ JSON → DiscountItem → ProductPrice → DB
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
    build_source_attributes,
    normalize_source_key,
    parse_period_fields,
    source_dedup_key,
)
from engine.anti_detect import AntiDetect
from pipeline.quality import summarize_discount_run

logger = logging.getLogger(__name__)


class LottemartCrawler(CrawlerContract):
    """롯데마트 크롤러 — lottemartzetta.com __INITIAL_STATE__ 기반 할인 상품 수집.

    수집 전략:
      - 검색어별 1~3초 랜덤 딜레이
      - HTTP 실패 시 일반 Playwright 브라우저 렌더링으로 자동 전환
      - AWS WAF/접근제어 응답은 우회하지 않고 차단 진단으로 기록
    """

    BASE_URL = "https://www.lottemart.com"
    ZETTA_BASE = "https://lottemartzetta.com"
    # 다양한 검색어로 더 많은 상품 수집
    SEARCH_QUERIES = ["할인", "특가", "과일", "채소", "정육", "세일", "우유", "음료"]
    CATEGORY_QUERIES = ["과일", "채소", "정육", "계란", "생수", "유제품", "간편식"]
    MAX_ITEMS: int | None = 300
    MAX_PAGES = 2
    MAX_REQUESTS: int | None = None
    PLAYWRIGHT_FALLBACK_QUERY_CAP = 3

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3,
                       **kwargs) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout, **kwargs)
                if resp.status_code == 429:  # Rate limited — back off
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

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="롯데마트",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="롯데마트 할인 상품 정보 수집 (lottemartzetta __INITIAL_STATE__ 기반)",
            target_url=self.BASE_URL,
            strategies=["requests", "playwright"],
        )

    async def crawl_incremental(
        self,
        *,
        since: str | None = None,
        source_input: str | None = None,
        source_url: str | None = None,
    ) -> CrawlResult:
        """Source-run entrypoint for bounded no-DB diagnostics.

        ``source_input`` replays saved HTML/JSON without network access. ``source_url``
        performs a single public GET so blocked responses can be captured without
        retry amplification.
        """
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
        started_at = datetime.now()
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        raw_count = 0
        parsed: list[DiscountItem] = []
        waf_blocker: dict[str, object] | None = None
        session = requests.Session()
        try:
            headers = self._anti_detect.get_random_headers()
            headers.update({
                "Referer": f"{self.ZETTA_BASE}/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            response = self._retry_request(
                source_url,
                headers=headers,
                session=session,
                timeout=20,
                max_retries=1,
                allow_redirects=True,
            )
            if response.status_code != 200:
                message = f"source_url HTTP {response.status_code}"
                if response.status_code == 202 and self._is_aws_waf_challenge(response.text):
                    message += " (AWS WAF challenge)"
                    waf_blocker = self._waf_blocker_details(message, request_url=source_url)
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
        }
        if waf_blocker:
            self._annotate_waf_blocker(quality_details, waf_blocker, valid_count=len(valid_items))
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
        """롯데마트 할인 상품을 크롤링한다.

        전략 순서:
          1차: HTTP 직접 요청으로 lottemartzetta.com/search 페이지의
               __INITIAL_STATE__ JSON에서 productEntities 추출
          2차: Playwright 브라우저 렌더링 (HTTP 실패 시 폴백)
        """
        started_at = datetime.now()
        logger.info("[롯데마트] 크롤링 시작")
        import asyncio as _asyncio

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        seen_ids: set[str] = set()
        source_raw_count = 0
        pages_attempted = 0
        waf_blocker: dict[str, object] | None = None

        # Reuse TCP connections across multiple search queries
        session = requests.Session()
        try:
            # 1차: __INITIAL_STATE__ 기반 추출 (HTTP 요청)
            for source_request in self._build_source_requests():
                if self.MAX_REQUESTS is not None and pages_attempted >= self.MAX_REQUESTS:
                    break
                query = str(source_request["query"])
                page_num = source_request["page"]
                url = str(source_request["url"])
                category_hint = str(source_request["category_hint"])
                pages_attempted += 1
                try:
                    headers = self._anti_detect.get_random_headers()
                    headers.update({
                        "Referer": f"{self.ZETTA_BASE}/",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    })

                    # Rate-limit requests with jitter; do not bypass WAF/access-control.
                    delay = self._anti_detect.get_random_delay()
                    await _asyncio.sleep(delay + random.uniform(0, 0.5))

                    response = self._retry_request(url, headers=headers, session=session, timeout=20, allow_redirects=True)

                    if response.status_code != 200:
                        message = f"검색 '{query}' p{page_num} HTTP {response.status_code}"
                        if response.status_code == 202 and self._is_aws_waf_challenge(response.text):
                            message += " (AWS WAF challenge)"
                            waf_blocker = self._waf_blocker_details(message, request_url=url, query=query, page=page_num)
                        logger.warning(f"[롯데마트] {message}")
                        errors.append(message)
                        strategy_failures.append(StrategyFailure(
                            strategy_name="requests",
                            error_type=ErrorType.HTTP_ERROR,
                            error_msg=message,
                            status_code=response.status_code,
                        ))
                        if response.status_code == 202:
                            logger.warning("[롯데마트] HTTP 202 challenge 감지, 추가 요청 중단")
                            break
                        continue

                    source_raw_count += self.count_raw_candidates(response.text)
                    # __INITIAL_STATE__에서 상품 데이터 추출
                    items = self._extract_from_initial_state(response.text)

                    # __INITIAL_STATE__ 추출 실패 시 HTML/JSON 파싱 폴백
                    if not items:
                        items = await self.parse(response.text)
                    if category_hint:
                        for item in items:
                            if not item.category:
                                item.category = category_hint
                            item.attributes.setdefault("category_hint", item.category or category_hint)

                    new_count = 0
                    for item in items:
                        key = source_dedup_key(item)
                        if key not in seen_ids:
                            seen_ids.add(key)
                            all_items.append(item)
                            new_count += 1
                            if self.MAX_ITEMS is not None and len(all_items) >= self.MAX_ITEMS:
                                break

                    logger.info(f"[롯데마트] 검색 '{query}' p{page_num}: {new_count}개 신규 ({len(items)}개 중)")
                    if self.MAX_ITEMS is not None and len(all_items) >= self.MAX_ITEMS:
                        logger.info(f"[롯데마트] bounded MAX_ITEMS={self.MAX_ITEMS} 도달, 조기 종료")
                        break

                except Exception as e:
                    logger.warning(f"[롯데마트] 검색 '{query}' 실패: {e}")
                    errors.append(f"검색 '{query}': {e}")
                    continue

            fallback_used = False

            # HTTP 수집 부족 시 일반 브라우저 렌더링 경로 1회 시도.
            # WAF/접근제어 응답은 브라우저로 우회하지 않고 차단 진단으로 남긴다.
            if waf_blocker is None and len(all_items) < 10:
                logger.info("[롯데마트] HTTP 수집 부족 → Playwright 폴백 시도")
                try:
                    pw_items = await self._fetch_via_playwright()
                    fallback_used = True
                    for item in pw_items:
                        key = source_dedup_key(item)
                        if key not in seen_ids:
                            seen_ids.add(key)
                            all_items.append(item)
                except Exception as e:
                    logger.warning(f"[롯데마트] Playwright 폴백 실패: {e}")
                    errors.append(f"Playwright: {e}")

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(all_items),
                source_raw_count=source_raw_count,
                invalid_count=max(0, len(all_items) - len(valid_items)),
                errors=errors,
                strategy_used="playwright" if fallback_used else "requests",
                fallback_used=fallback_used,
                queries_attempted=len(self.SEARCH_QUERIES),
                pages_attempted=pages_attempted,
            )
            if waf_blocker:
                self._annotate_waf_blocker(quality_details, waf_blocker, valid_count=len(valid_items))

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
            logger.info(f"[롯데마트] 크롤링 완료: {len(valid_items)}개, {duration:.2f}초")

            return CrawlResult(
                status=status,
                crawler_name=self.info.name,
                strategy_used="playwright" if fallback_used else "requests",
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

        except Exception as e:
            logger.warning(f"[롯데마트] HTTP 요청 실패, Playwright 시도: {e}")
            try:
                items = await self._fetch_via_playwright()
                valid_items = await self.validate(items)
                items_as_dict = [item.model_dump(mode="json") for item in valid_items]
                finished_at = datetime.now()
                duration = (finished_at - started_at).total_seconds()
                if valid_items:
                    items_as_dict = [item.model_dump(mode="json") for item in valid_items]
                    quality_details = summarize_discount_run(
                        items_as_dict,
                        raw_count=len(items),
                        invalid_count=max(0, len(items) - len(valid_items)),
                        strategy_used="playwright",
                        fallback_used=True,
                    )
                    return CrawlResult(
                        status=CrawlStatus.SUCCESS,
                        crawler_name=self.info.name,
                        strategy_used="playwright",
                        items_count=len(valid_items),
                        items=items_as_dict,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_seconds=duration,
                        quality_score=quality_details["score"],
                        quality_details=quality_details,
                    )
            except Exception as e2:
                logger.error(f"[롯데마트] Playwright 폴백도 실패: {e2}")
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )
        finally:
            session.close()  # Release TCP connections

    def _build_source_requests(self) -> list[dict[str, str | int]]:
        """Build bounded search/category pagination source requests."""
        requests_to_make: list[dict[str, str | int]] = []
        seen: set[tuple[str, int]] = set()
        queries = [*self.SEARCH_QUERIES, *self.CATEGORY_QUERIES]
        # Prefer breadth-first page-1 coverage across public search/category pages before
        # deeper pagination, so bounded diagnostics do not spend early requests on likely
        # duplicate page variants before discovering source blocking.
        for page_num in range(1, self.MAX_PAGES + 1):
            for query in queries:
                category_hint = query if query in self.CATEGORY_QUERIES else ""
                key = (query, page_num)
                if key in seen:
                    continue
                seen.add(key)
                requests_to_make.append(
                    {
                        "query": query,
                        "page": page_num,
                        "category_hint": category_hint,
                        "url": f"{self.ZETTA_BASE}/search?query={quote(query)}&page={page_num}",
                    }
                )
        return requests_to_make

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
    ) -> dict[str, object]:
        return {
            "blocked": True,
            "blocker": "aws_waf_http_202",
            "status_code": 202,
            "message": message,
            "request_url": request_url,
            "query": query,
            "page": page,
            "auth_bypass_attempted": False,
            "safe_next_action": (
                "Do not retry aggressively or attempt authentication/access-control/WAF bypass. "
                "Use an official/public feed/API, partner API, caller-supplied saved-source export, "
                "manual source import, or an alternate public source."
            ),
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
        for alert in ("source_blocked_aws_waf_202", "partial_lottemart_waf_blocker"):
            if alert not in alerts:
                alerts.append(alert)
        next_action = str(waf_blocker["safe_next_action"])
        next_actions = quality_details.setdefault("next_actions", [])
        if next_action not in next_actions:
            next_actions.append(next_action)
        quality_summary = quality_details.setdefault("quality_summary", {})
        quality_summary["status"] = "blocked" if valid_count < 200 else quality_summary.get("status", "warning")
        quality_summary["registered_vs_collecting"] = quality_summary["status"]
        summary_actions = quality_summary.setdefault("next_actions", [])
        if next_action not in summary_actions:
            summary_actions.append(next_action)
        diagnostics = quality_details.setdefault("operator_diagnostics", [])
        diagnostics.append(
            {
                "code": "aws_waf_http_202_blocker",
                "severity": "error" if valid_count < 200 else "warning",
                "stage": "source_fetch",
                "message": waf_blocker["message"],
                "next_action": next_action,
                "counts": {
                    "valid": valid_count,
                    "target_minimum": 200,
                },
                "blocked": True,
                "status_code": 202,
                "auth_bypass_attempted": False,
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

        # __INITIAL_STATE__ JSON 추출
        idx = html.find("window.__INITIAL_STATE__=")
        if idx < 0:
            return items

        start = idx + len("window.__INITIAL_STATE__=")
        script_end = html.find("</script>", start)
        if script_end < 0:
            return items

        json_str = html[start:script_end].rstrip().rstrip(";")
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[롯데마트] __INITIAL_STATE__ JSON 파싱 실패")
            return items

        # productEntities에서 상품 추출
        product_entities = (
            data.get("data", {})
            .get("products", {})
            .get("productEntities", {})
        )

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
        idx = raw_data.find("window.__INITIAL_STATE__=")
        if idx >= 0:
            start = idx + len("window.__INITIAL_STATE__=")
            script_end = raw_data.find("</script>", start)
            if script_end >= 0:
                try:
                    data = json.loads(raw_data[start:script_end].rstrip().rstrip(";"))
                    product_entities = (
                        data.get("data", {})
                        .get("products", {})
                        .get("productEntities", {})
                    )
                    if isinstance(product_entities, dict):
                        return len(product_entities)
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
        clean_name = re.sub(r"^\[.*?\]\s*", "", name).strip()
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

        # 상세 URL
        detail_url = self._absolute_url(
            product.get("url") or product.get("productUrl") or product.get("detailUrl") or "",
            self.ZETTA_BASE,
        )
        if not detail_url and product_id:
            detail_url = f"{self.ZETTA_BASE}/products/{product_id}"

        # 브랜드
        brand = product.get("brand", "")
        unit_metadata = normalize_unit_metadata(
            name=clean_name,
            sale_price=sale_price,
            raw_unit=unit,
        )
        display_unit = unit_metadata.get("display_unit") or unit
        attributes = unit_metadata.get("attributes") or {}
        if brand:
            attributes = {**attributes, "brand": brand}
        source_record_key = normalize_source_key("lottemart", product_id, detail_url, clean_name)
        valid_from, valid_until, period = parse_period_fields(product)
        attributes = build_source_attributes(
            "lottemart",
            source_record_key=source_record_key,
            detail_url=detail_url,
            image_url=image_url,
            category=category,
            category_path=category_path,
            period=period,
            extra=attributes,
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
            valid_from=valid_from,
            valid_until=valid_until,
            image_url=image_url,
            detail_url=detail_url,
        )

    async def _fetch_via_playwright(self) -> list[DiscountItem]:
        """Playwright로 롯데마트 SPA(lottemartzetta.com) 검색 페이지에서 상품을 수집한다.

        HTTP 요청으로 __INITIAL_STATE__ 추출이 실패할 경우의 폴백 전략.
        브라우저에서 실제 렌더링 후 product-card-container 요소를 파싱한다.
        """
        items: list[DiscountItem] = []

        try:
            from engine.playwright_helper import PlaywrightHelper

            async with PlaywrightHelper() as helper:
                request_cap = self.PLAYWRIGHT_FALLBACK_QUERY_CAP
                if self.MAX_REQUESTS is not None:
                    request_cap = max(1, min(request_cap, self.MAX_REQUESTS))
                for source_request in self._build_source_requests()[:request_cap]:
                    query = str(source_request["query"])
                    url = str(source_request["url"])
                    try:
                        html = await helper.get_rendered_html(
                            url,
                            wait_selector=".product-card-container",
                            wait_timeout=20000,
                            scroll_to_bottom=True,
                        )
                        # Playwright HTML에서도 __INITIAL_STATE__ 추출 시도
                        state_items = self._extract_from_initial_state(html)
                        if state_items:
                            items.extend(state_items)
                            logger.info(f"[롯데마트] Playwright '{query}': {len(state_items)}개 (state)")
                        else:
                            # HTML 파싱 폴백
                            page_items = self._parse_spa_html(html, query)
                            items.extend(page_items)
                            logger.info(f"[롯데마트] Playwright '{query}': {len(page_items)}개 (html)")
                        if self.MAX_ITEMS is not None and len(items) >= self.MAX_ITEMS:
                            break
                    except Exception as e:
                        logger.debug(f"[롯데마트] Playwright 검색 '{query}' 실패: {e}")
                        continue

                logger.info(f"[롯데마트] Playwright 총: {len(items)}개 수집")

        except ImportError:
            logger.warning("[롯데마트] playwright 미설치 — pip install playwright && playwright install chromium")
        except Exception as e:
            logger.warning(f"[롯데마트] Playwright 크롤링 실패: {e}")

        return items

    def _parse_spa_html(self, html: str, query: str = "") -> list[DiscountItem]:
        """lottemartzetta.com SPA에서 렌더링된 HTML의 상품 카드를 파싱한다."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        items: list[DiscountItem] = []

        cards = soup.select(".product-card-container")
        logger.info(f"[롯데마트] SPA 상품 카드: {len(cards)}개 (query={query})")

        for card in cards:
            try:
                item = self._parse_spa_card(card)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[롯데마트] SPA 카드 파싱 오류: {e}")
                continue

        return items

    def _parse_spa_card(self, card) -> Optional[DiscountItem]:
        """lottemartzetta.com SPA 상품 카드 → DiscountItem."""
        # 상품명: [class*="name"], [class*="title"], h3, h4, strong
        name_el = card.select_one(
            "[class*='name'], [class*='title'], h3, h4, strong"
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        # 가격 — "가격4,990원" 형태에서 "가격" 접두사 제거 후 숫자 추출
        prices: list[int] = []
        for el in card.select("[class*='price']"):
            text = el.get_text(strip=True)
            text = re.sub(r'^가격', '', text)
            price = self._extract_price(text)
            if price and price > 0:
                prices.append(price)

        if not prices:
            return None

        prices = sorted(set(prices))
        sale_price = prices[0]
        original_price = prices[-1] if len(prices) > 1 and prices[-1] != prices[0] else None

        # 상세 URL
        detail_url = ""
        link_el = card.select_one("a[href*='products']")
        if not link_el:
            link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("http"):
                detail_url = href
            elif href.startswith("/"):
                detail_url = f"{self.ZETTA_BASE}{href}"

        # 이미지
        image_url = ""
        img_el = card.select_one("img")
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src", "")

        # 할인/행사 정보
        card_text = card.get_text(" ", strip=True)
        discount_pct = None
        event_name = "롯데마트 할인"

        discount_match = re.search(r'(\d+)%\s*할인', card_text)
        if discount_match:
            discount_pct = float(discount_match.group(1))
            context_match = re.search(r'([^,]*,?\s*\d+%\s*할인)', card_text)
            if context_match:
                event_name = context_match.group(1).strip()

        if discount_pct is None and original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        # 단위 정보
        unit = ""
        unit_match = re.search(
            r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개|팩|봉|매|입)(?:\([^)]+\))?)',
            card_text, re.IGNORECASE,
        )
        if unit_match:
            unit = unit_match.group(1)
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=unit,
        )
        display_unit = unit_metadata.get("display_unit") or unit

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
            attributes=build_source_attributes(
                "lottemart",
                source_record_key=normalize_source_key("lottemart", detail_url, name),
                detail_url=detail_url,
                image_url=image_url,
                extra=unit_metadata.get("attributes") or {},
            ),
            image_url=image_url,
            detail_url=detail_url,
            event_name=event_name,
        )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """HTML/JSON 응답에서 할인 상품을 파싱한다."""
        items: list[DiscountItem] = []

        # 1) __INITIAL_STATE__ 추출 (lottemartzetta.com)
        state_items = self._extract_from_initial_state(raw_data)
        if state_items:
            return state_items

        # 2) JSON 데이터 블록 추출 시도
        json_items = self._extract_json_items(raw_data)
        if json_items:
            for product in json_items:
                item = self._json_to_discount_item(product)
                if item:
                    items.append(item)
            return items

        # 3) HTML 파싱 fallback
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

    def _json_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """JSON 상품 데이터 → DiscountItem 변환."""
        name = (
            product.get("goodsNm")
            or product.get("itemNm")
            or product.get("prodNm")
            or product.get("name", "")
        )
        if not name or len(name) < 2:
            return None

        sale_price = self._to_int(
            product.get("salePrice") or product.get("sellprc")
            or product.get("sale_price") or product.get("price")
        )
        original_price = self._to_int(
            product.get("originPrice") or product.get("norprc")
            or product.get("original_price")
        )

        if not sale_price or sale_price <= 0:
            return None

        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)

        image_url = self._absolute_url(product.get("imgUrl") or product.get("goodsImg", ""), self.BASE_URL)
        category = product.get("categoryNm") or product.get("ctgNm", "")
        detail_url = product.get("goodsUrl") or product.get("detail_url", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"{self.BASE_URL}{detail_url}"
        source_record_key = normalize_source_key(
            "lottemart",
            product.get("goodsNo"),
            product.get("itemId"),
            product.get("id"),
            detail_url,
            name,
        )
        valid_from, valid_until, period = parse_period_fields(product)
        raw_unit = product.get("unit") or product.get("size") or product.get("capacity") or ""
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit

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
            attributes=build_source_attributes(
                "lottemart",
                source_record_key=source_record_key,
                detail_url=detail_url,
                image_url=image_url,
                category=category,
                period=period,
                extra=unit_metadata.get("attributes") or {},
            ),
            category=category,
            event_name=product.get("eventNm", "롯데마트 할인"),
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

        link_el = card.select_one("a[href]")
        detail_url = ""
        if link_el:
            href = link_el.get("href", "")
            detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
        unit_metadata = normalize_unit_metadata(name=name, sale_price=sale_price)
        display_unit = unit_metadata.get("display_unit")

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
            attributes=build_source_attributes(
                "lottemart",
                source_record_key=normalize_source_key("lottemart", detail_url, name),
                detail_url=detail_url,
                image_url=image_url,
                extra=unit_metadata.get("attributes") or {},
            ),
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
