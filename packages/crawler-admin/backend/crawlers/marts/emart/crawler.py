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
from typing import Optional
from urllib.parse import quote

import requests

from core.contracts.crawler import CrawlerContract
from core.models import (
    CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus,
    DiscountItem, ErrorType, StrategyFailure,
)
from core.product_units import normalize_unit_metadata
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
    # 다양한 검색어로 더 많은 할인 상품 수집
    SEARCH_QUERIES = ["행사", "할인", "특가", "1+1", "반값", "세일"]
    # 페이지네이션: 각 검색어당 최대 페이지 수 (페이지당 ~40개)
    MAX_PAGES = 3

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=1.0, delay_max=3.0)

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
            name="이마트",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="이마트 할인 상품 정보 수집 (SSG __NEXT_DATA__ 기반)",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """이마트 할인 상품을 크롤링한다.

        페이지네이션 전략:
          각 검색어(SEARCH_QUERIES)에 대해 MAX_PAGES 페이지까지 순회하며
          __NEXT_DATA__에서 상품을 추출한다. 중복은 validate()에서 제거한다.
          사이트 부하를 줄이기 위해 각 요청 사이에 AntiDetect 딜레이를 적용한다.
        """
        started_at = datetime.now()
        logger.info("[이마트] 크롤링 시작")

        all_items: list[DiscountItem] = []
        errors: list[str] = []
        strategy_failures: list[StrategyFailure] = []
        source_raw_count = 0
        pages_attempted = 0
        import asyncio as _asyncio

        try:
            for query in self.SEARCH_QUERIES:
                for page_num in range(1, self.MAX_PAGES + 1):
                    pages_attempted += 1
                    try:
                        url = f"{self.SEARCH_URL}?target=all&query={quote(query)}&page={page_num}"
                        headers = self._anti_detect.get_random_headers()
                        headers.update({
                            "Referer": "https://emart.ssg.com/",
                        })

                        # Anti-detection: randomized delay between pages with jitter
                        delay = self._anti_detect.get_random_delay()
                        await _asyncio.sleep(delay + random.uniform(0, 0.5))

                        response = self._retry_request(url, headers=headers, timeout=20)
                        response.encoding = "utf-8"

                        if response.status_code != 200:
                            message = f"검색 '{query}' p{page_num} HTTP {response.status_code}"
                            logger.warning(f"[이마트] {message}")
                            errors.append(message)
                            strategy_failures.append(StrategyFailure(
                                strategy_name="requests",
                                error_type=ErrorType.HTTP_ERROR,
                                error_msg=message,
                                status_code=response.status_code,
                            ))
                            break  # 이 검색어의 다음 페이지 스킵

                        raw_candidates = self._count_raw_candidates(response.text)
                        source_raw_count += raw_candidates
                        items = await self.parse(response.text)
                        logger.info(
                            f"[이마트] 검색 '{query}' p{page_num}: 원천 후보 {raw_candidates}개, 파싱 {len(items)}개"
                        )
                        all_items.extend(items)

                        # 결과가 없으면 이 검색어의 마지막 페이지
                        if not items:
                            break

                    except Exception as e:
                        message = f"검색 '{query}' p{page_num}: {e}"
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
                        break

            valid_items = await self.validate(all_items)
            items_as_dict = [item.model_dump(mode="json") for item in valid_items]
            quality_details = summarize_discount_run(
                items_as_dict,
                raw_count=len(all_items),
                source_raw_count=source_raw_count,
                invalid_count=max(0, len(all_items) - len(valid_items)),
                errors=errors,
                strategy_used="requests",
                queries_attempted=len(self.SEARCH_QUERIES),
                pages_attempted=pages_attempted,
            )

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            status = CrawlStatus.SUCCESS if valid_items else CrawlStatus.FAILED
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
                strategy_used="requests",
                items_count=len(valid_items),
                items=items_as_dict,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                errors=strategy_failures,
                error_msg="; ".join(errors) if errors and not valid_items else None,
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
            count = len(soup.select(".cunit_prod, .csct_deal, .mndtl_item, .item_box"))
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
                    logger.info(f"[이마트] __NEXT_DATA__ 상품 {len(data_list)}개 발견")
                    del data  # Free large JSON from memory
                    return data_list

        return []

    def _next_data_to_discount_item(self, product: dict) -> Optional[DiscountItem]:
        """SSG __NEXT_DATA__ 상품 → DiscountItem 변환.

        주요 필드:
          itemName, finalPrice, strikeOutPrice, priceInfo.primaryPrice,
          priceInfo.strikeOutPrice, priceInfo.discountRate,
          brandName, itemImgUrl, itemUrl, siteName
        """
        name = product.get("itemName", "")
        if not name or len(name) < 2:
            return None

        # 가격 추출 — finalPrice (쉼표 포함 문자열) 또는 priceInfo
        sale_price = self._parse_price_str(product.get("finalPrice"))

        # priceInfo에서도 시도
        if not sale_price:
            price_info = product.get("priceInfo", {})
            if price_info:
                sale_price = self._parse_price_str(price_info.get("primaryPrice"))

        if not sale_price or sale_price <= 0:
            return None

        # 원가
        original_price = self._parse_price_str(
            product.get("strikeOutPrice") or product.get("originalPrice")
        )
        if not original_price:
            price_info = product.get("priceInfo", {})
            if price_info:
                original_price = self._parse_price_str(price_info.get("strikeOutPrice"))

        # 할인율
        discount_pct = None
        if original_price and original_price > sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)
        else:
            # priceInfo.discountRate 에서 추출 (예: "2%")
            rate_str = product.get("priceInfo", {}).get("discountRate", "")
            if rate_str:
                rate_match = re.search(r"(\d+)", str(rate_str))
                if rate_match:
                    discount_pct = float(rate_match.group(1))

        image_url = self._absolute_url(
            product.get("itemImgUrl") or product.get("imageUrl") or product.get("imgUrl") or "",
            self.BASE_URL,
        )
        detail_url = self._absolute_url(
            product.get("itemUrl") or product.get("detailUrl") or product.get("linkUrl") or "",
            self.BASE_URL,
        )
        brand = product.get("brandName", "")
        site = product.get("siteName", "이마트")
        category = (
            product.get("categoryName")
            or product.get("dispCtgName")
            or product.get("ctgNm")
            or product.get("largeCategoryName")
            or ""
        )
        raw_unit = product.get("sellUnitCapacity", "")
        unit_metadata = normalize_unit_metadata(
            name=name,
            sale_price=sale_price,
            raw_unit=raw_unit,
        )
        display_unit = unit_metadata.get("display_unit") or raw_unit

        attributes = unit_metadata.get("attributes") or {}
        if brand:
            attributes = {**attributes, "collection": brand}
        source_record_key = str(product.get("itemId") or product.get("id") or "").strip()
        attributes = {
            **attributes,
            **({"source_record_key": source_record_key} if source_record_key else {}),
            **({"source_url": detail_url} if detail_url else {}),
            **({"image_url": image_url} if image_url else {}),
            **({"category_hint": category} if category else {}),
        }

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
            image_url=image_url,
            detail_url=detail_url,
        )

    def _absolute_url(self, url: str, base_url: str) -> str:
        """Normalize source-relative URLs while preserving absolute URLs."""
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return f"{base_url}{url}"
        return url

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
        source_record_key = str(product.get("itemId") or product.get("item_id") or product.get("id") or "").strip()
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
            attributes={
                **(unit_metadata.get("attributes") or {}),
                **({"source_record_key": source_record_key} if source_record_key else {}),
                **({"source_url": detail_url} if detail_url else {}),
                **({"image_url": image_url} if image_url else {}),
                **({"category_hint": category} if category else {}),
            },
            category=category,
            event_name=product.get("eventNm", "이마트 할인"),
            image_url=image_url,
            detail_url=detail_url,
        )

    def _parse_html(self, soup) -> list[DiscountItem]:
        """HTML에서 상품 정보를 파싱한다 (fallback)."""
        items: list[DiscountItem] = []
        product_cards = soup.select(
            ".cunit_prod, .csct_deal, .mndtl_item, .item_box"
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
        name_el = card.select_one(
            ".cunit_info .cunit_md, .title, .item_name, .prod_name, a[href*='item']"
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        sale_price = self._extract_price_from_element(
            card, ".new_price .ssg_price, .sale_price, .price .num, .opt_price"
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
            attributes=unit_metadata.get("attributes") or {},
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
            key = f"{item.name}_{item.sale_price}"
            if key in seen:
                continue
            seen.add(key)

            if item.sale_price <= 0:
                continue
            if len(item.name) < 2:
                continue

            valid.append(item)

        return valid
