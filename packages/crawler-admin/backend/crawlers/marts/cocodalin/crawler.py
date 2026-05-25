"""
코코달인 크롤러 (코스트코 할인 정보).

코코달인 REST API를 직접 호출하여 코스트코 할인 상품 데이터를 수집한다.
API 엔드포인트:
  - /api/front/bestLikeProducts: 인기 할인 상품 (~80건)
  - /api/front/productList/{category_id}: 카테고리별 할인 상품 (12 카테고리, ~392건)

용도: 순수 DB 구축 (discount_history) — baseline 오염 없음.
의존: core/ 만.
"""

from __future__ import annotations

import json
import logging
import random
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

# 12개 카테고리 전체 (2026-05-16 기준 총 392건)
CATEGORY_IDS: tuple[int, ...] = (7, 9, 10, 11, 8, 12, 1, 2, 3, 4, 5, 6)


class CocodalinCrawler(CrawlerContract):
    """코코달인 크롤러 — 코스트코 할인 정보 수집 (API 직접 호출)."""

    API_BASE = "https://www.cocodalin.com/api/front"
    ENDPOINTS = {
        "best": "/bestLikeProducts",
        "category": "/productList/{cat_id}",
    }
    SLEEP_SECONDS: float = 1.5  # 카테고리 호출 간 딜레이 (1-2초)

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

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="코코달인",
            version="2.1.0",
            group=CrawlerGroup.MART,
            description="코스트코 할인 정보 수집 (코코달인 API: bestLikeProducts + 12 productList 카테고리)",
            target_url="https://www.cocodalin.com/",
            strategies=["requests"],
        )

    def _headers(self) -> dict:
        headers = self._anti_detect.get_random_headers()
        headers.update({
            "Accept": "application/json",
            "Referer": "https://www.cocodalin.com/",
        })
        return headers

    def _fetch_json(self, url: str) -> list:
        """URL에서 JSON 리스트 반환, 실패 시 빈 리스트."""
        try:
            response = self._retry_request(url, headers=self._headers(), timeout=15)
            if response.status_code != 200:
                logger.warning(f"[코코달인] {url}: HTTP {response.status_code}")
                return []
            data = response.json()
            if isinstance(data, list):
                return data
            return []
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[코코달인] {url} fetch failed: {e}")
            return []

    def _crawl_all_product_lists(self) -> list[dict]:
        """12개 카테고리 productList API 호출."""
        all_products: list[dict] = []
        for cat_id in CATEGORY_IDS:
            url = self.API_BASE + self.ENDPOINTS["category"].format(cat_id=cat_id)
            products = self._fetch_json(url)
            all_products.extend(products)
            if self.SLEEP_SECONDS > 0:
                time.sleep(random.uniform(
                    self.SLEEP_SECONDS * 0.7,
                    self.SLEEP_SECONDS * 1.3,
                ))
        return all_products

    async def crawl(self) -> CrawlResult:
        """bestLikeProducts + 12 productList 카테고리 모두 호출, 중복 제거."""
        started_at = datetime.now()
        logger.info("[코코달인] API 크롤링 시작 (best + 12 카테고리)")

        try:
            # 1) bestLikeProducts
            best_url = self.API_BASE + self.ENDPOINTS["best"]
            best_products = self._fetch_json(best_url)
            logger.info(f"[코코달인] bestLikeProducts: {len(best_products)}건")

            # 2) 12 카테고리 productList
            cat_products = self._crawl_all_product_lists()
            logger.info(f"[코코달인] productList 합계: {len(cat_products)}건")

            # 합치고 변환 + 중복 제거 (product_id 기준)
            all_products = best_products + cat_products
            seen_ids: set = set()
            items: list[DiscountItem] = []
            for p in all_products:
                pid = p.get("product_id")
                if pid is not None:
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                item = self._product_to_discount_item(p)
                if item:
                    items.append(item)

            valid_items = await self.validate(items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]

            finished_at = datetime.now()
            logger.info(f"[코코달인] API 크롤링 완료: {len(valid_items)}건, "
                        f"{(finished_at - started_at).total_seconds():.2f}초")

            return CrawlResult(
                status=CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED,
                crawler_name=self.info.name,
                strategy_used="requests (API: best + 12 productList)",
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

        discount_pct = None
        if normal_price and normal_price > sale_price:
            discount_pct = round((1 - sale_price / normal_price) * 100, 1)

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
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        for fmt in ["%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    async def validate(self, items: list[DiscountItem]) -> list[DiscountItem]:
        valid = []
        seen = set()
        for item in items:
            # detail_url 우선 (product_id 기반 유일성), 없으면 이름+가격
            key = item.detail_url or f"{item.name}_{item.sale_price}"
            if key in seen:
                continue
            seen.add(key)
            if item.sale_price <= 0:
                continue
            if len(item.name) < 2:
                continue
            valid.append(item)
        return valid
