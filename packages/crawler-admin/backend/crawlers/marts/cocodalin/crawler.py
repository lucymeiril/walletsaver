"""
코코달인 크롤러 (코스트코 할인 정보).

코코달인 REST API를 직접 호출하여 코스트코 할인 상품 데이터를 수집한다.
API 엔드포인트: https://www.cocodalin.com/api/front

할인 상품 데이터 필드:
  - product_name: 상품명
  - normal_price: 정가
  - sale_price: 할인가
  - discount: 할인액 (절댓값)
  - from_date: 할인 시작일
  - to_date: 할인 종료일
  - category_name: 카테고리
  - product_id: 상품 고유 ID

용도: 순수 DB 구축 (discount_history)
  - 할인 빈도, 평균 할인율, 가격 추이 분석의 원천 데이터
  - DataSource.MART_DISCOUNT로 분류 → baseline 오염 없음

의존: core/ 만
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Optional

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem,
)
from engine.anti_detect import AntiDetect

logger = logging.getLogger(__name__)


class CocodalinCrawler(CrawlerContract):
    """코코달인 크롤러 — 코스트코 할인 정보 수집 (API 직접 호출)."""

    API_BASE = "https://www.cocodalin.com/api/front"
    ENDPOINTS = {
        "best": "/bestLikeProducts",
        "categories": "/saleSummary",
    }

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.3, delay_max=1.0)

    def _retry_request(self, url: str, *, headers: dict | None = None,
                       session: requests.Session | None = None,
                       timeout: int = 15, max_retries: int = 3) -> requests.Response:
        """HTTP GET with exponential backoff for transient failures."""
        requester = session or requests
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requester.get(url, headers=headers, timeout=timeout)
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
            name="코코달인",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="코스트코 할인 정보 수집 (코코달인 API)",
            target_url="https://www.cocodalin.com/",
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """코코달인 API를 호출하여 코스트코 할인 상품을 수집한다."""
        started_at = datetime.now()
        logger.info("[코코달인] API 크롤링 시작")

        try:
            headers = self._anti_detect.get_random_headers()
            headers.update({
                "Accept": "application/json",
                "Referer": "https://www.cocodalin.com/",
            })

            # 인기 할인 상품 API 호출 (retry with backoff)
            url = self.API_BASE + self.ENDPOINTS["best"]
            response = self._retry_request(url, headers=headers, timeout=15)

            if response.status_code != 200:
                logger.error(f"[코코달인] API HTTP {response.status_code}")
                return CrawlResult(
                    status=CrawlStatus.FAILED,
                    crawler_name=self.info.name,
                    error_msg=f"API HTTP {response.status_code}",
                    started_at=started_at,
                    finished_at=datetime.now(),
                )

            raw_data = response.text
            items = await self.parse(raw_data)
            valid_items = await self.validate(items)

            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            logger.info(f"[코코달인] API 크롤링 완료: {len(valid_items)}개, {(finished_at - started_at).total_seconds():.2f}초")

            return CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name=self.info.name,
                strategy_used="requests (API)",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
            )

        except Exception as e:
            logger.error(f"[코코달인] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[DiscountItem]:
        """JSON 응답을 DiscountItem 리스트로 파싱한다."""
        import json
        items: list[DiscountItem] = []

        try:
            products = json.loads(raw_data)
        except json.JSONDecodeError as e:
            logger.error(f"[코코달인] JSON 파싱 실패: {e}")
            return items

        if not isinstance(products, list):
            logger.warning(f"[코코달인] 예상과 다른 응답 형식: {type(products)}")
            return items

        for product in products:
            item = self._product_to_discount_item(product)
            if item:
                items.append(item)

        return items

    def _product_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """API 상품 JSON → DiscountItem 변환."""
        name = product.get("product_name", "")
        if not name or len(name) < 2:
            return None

        sale_price = self._to_int(product.get("sale_price"))
        normal_price = self._to_int(product.get("normal_price"))

        if not sale_price or sale_price <= 0:
            return None

        # 할인율 계산
        discount_pct = None
        if normal_price and normal_price > sale_price:
            discount_pct = round((1 - sale_price / normal_price) * 100, 1)

        # 날짜 파싱
        valid_from = self._parse_date(product.get("from_date"))
        valid_until = self._parse_date(product.get("to_date"))

        return DiscountItem(
            name=name,
            store="코스트코",
            original_price=normal_price,
            sale_price=sale_price,
            discount_percent=discount_pct,
            category=product.get("category_name", ""),
            event_name="코스트코 할인",
            valid_from=valid_from,
            valid_until=valid_until,
            detail_url=f"https://www.cocodalin.com/product.html?id={product.get('product_id', '')}",
        )

    def _to_int(self, value) -> Optional[int]:
        """안전한 정수 변환."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """날짜 문자열 → datetime 변환."""
        if not date_str:
            return None
        for fmt in ["%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        """유효한 할인 상품만 필터링."""
        valid = []
        seen = set()

        for item in items:
            # 중복 제거 (상품명 + 가격)
            key = f"{item.name}_{item.sale_price}"
            if key in seen:
                continue
            seen.add(key)

            # 가격 유효성
            if item.sale_price <= 0:
                continue

            # 이름 최소 길이
            if len(item.name) < 2:
                continue

            valid.append(item)

        return valid
