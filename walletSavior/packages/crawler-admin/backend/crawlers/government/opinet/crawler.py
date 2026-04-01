"""
오피넷 크롤러 — 전국 주유소 가격 정보 수집.

오피넷(OPINET)은 한국석유공사가 운영하는 유가 정보 서비스로,
전국 주유소의 실시간 유류 가격을 제공한다.

전략:
  1차: 오피넷 REST API (lowTop10.do) — 시도별 최저가 주유소 수집
  2차: 웹 스크레이핑 fallback — 메인 페이지 가격 추출

데이터 흐름: 오피넷 API/웹 → JSON/HTML 파싱 → dict → GasStation → DB
의존: core/ 만
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

import requests

from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus
from engine.anti_detect import AntiDetect
from config import OPINET_API_KEY

logger = logging.getLogger(__name__)


class OpinetCrawler(CrawlerContract):
    """오피넷 크롤러 — 전국 주유소 유류 가격 수집."""

    BASE_URL = "https://www.opinet.co.kr"
    API_BASE = "https://www.opinet.co.kr/api"
    MAIN_PAGE = "https://www.opinet.co.kr/user/main/mainView.do"

    # 전국 17개 시도 코드
    SIDO_CODES = [
        "01", "02", "03", "04", "05", "06", "07", "08", "09",
        "10", "11", "14", "15", "16", "17", "18", "19",
    ]

    # 유종 코드
    PROD_GASOLINE = "B027"
    PROD_DIESEL = "B034"
    PROD_LPG = "K015"

    # 브랜드 코드 → 한글 매핑
    BRAND_MAP: dict[str, str] = {
        "SKE": "SK에너지",
        "GSC": "GS칼텍스",
        "HDO": "현대오일뱅크",
        "SOL": "S-OIL",
        "RTO": "알뜰주유소",
        "RTX": "알뜰주유소",
        "ETC": "기타",
        "E1G": "E1",
        "SKG": "SK가스",
        "NHO": "농협",
    }

    def __init__(self, anti_detect: Optional[AntiDetect] = None):
        self._anti_detect = anti_detect or AntiDetect(delay_min=0.5, delay_max=1.5)
        self._api_key = OPINET_API_KEY

    # ------------------------------------------------------------------
    # CrawlerContract 구현
    # ------------------------------------------------------------------

    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="오피넷",
            version="1.0.0",
            group=CrawlerGroup.PUBLIC_API,
            description="전국 주유소 가격 정보 수집 (오피넷 API)",
            target_url=self.BASE_URL,
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        """주유소 가격 크롤링 — API 우선, 웹 스크레이핑 fallback."""
        started_at = datetime.now()
        logger.info("[오피넷] 크롤링 시작")
        errors: list[str] = []

        try:
            # 전략 1: 오피넷 REST API
            if self._api_key:
                items = await self._crawl_via_api(errors)
                if items:
                    valid = await self.validate(items)
                    if valid:
                        return self._build_result(valid, started_at, "api", errors)
                logger.warning("[오피넷] API 수집 실패, 웹 스크레이핑으로 전환")
            else:
                logger.info("[오피넷] API 키 미설정, 웹 스크레이핑 시도")

            # 전략 2: 웹 스크레이핑
            items = await self._crawl_via_web(errors)
            valid = await self.validate(items)
            return self._build_result(valid, started_at, "web_scraping", errors)

        except Exception as e:
            logger.error(f"[오피넷] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                status=CrawlStatus.FAILED,
                crawler_name=self.info.name,
                error_msg=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def parse(self, raw_data: str) -> list[dict]:
        """오피넷 API JSON 응답 → 주유소 dict 리스트 변환."""
        items: list[dict] = []

        try:
            data = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            # JSON이 아니면 HTML로 간주
            return await self._parse_web_page(raw_data)

        # 오피넷 API 응답 구조: {"RESULT": {"OIL": [...]}}
        result = data.get("RESULT", data)
        oil_list = result.get("OIL", [])

        if not isinstance(oil_list, list):
            return items

        for station in oil_list:
            if not isinstance(station, dict):
                continue

            name = (
                station.get("OS_NM", "")
                or station.get("OSNAME", "")
                or ""
            ).strip()
            if not name:
                continue

            brand_code = (
                station.get("POLL_DIV_CO", "")
                or station.get("POLL_DIV_CD", "")
                or ""
            )
            brand = self.BRAND_MAP.get(brand_code, brand_code)

            address = (
                station.get("NEW_ADR", "")
                or station.get("VAN_ADR", "")
                or ""
            ).strip()

            lat = self._to_float(
                station.get("GIS_Y_COOR") or station.get("GIS_Y")
            )
            lng = self._to_float(
                station.get("GIS_X_COOR") or station.get("GIS_X")
            )

            price = self._to_float(
                station.get("PRICE") or station.get("OPRICE")
            )

            is_self = station.get("SELF_YN", "N") == "Y"

            uni_id = (
                station.get("UNI_ID", "")
                or station.get("UNITID", "")
                or name
            )

            items.append({
                "name": name,
                "brand": brand,
                "address": address,
                "lat": lat,
                "lng": lng,
                "gasoline_price": price,
                "diesel_price": None,
                "lpg_price": None,
                "is_self": is_self,
                "_uni_id": uni_id,
            })

        return items

    async def validate(self, items: list[dict]) -> list[dict]:
        """유효한 주유소 데이터만 필터링 — 중복·이상치 제거."""
        valid: list[dict] = []
        seen: set[str] = set()

        for item in items:
            name = item.get("name", "")
            if not name or len(name) < 2:
                continue

            # 가격이 하나도 없으면 제외
            has_price = any([
                item.get("gasoline_price"),
                item.get("diesel_price"),
                item.get("lpg_price"),
            ])
            if not has_price:
                continue

            # 비정상 가격 필터링 (리터당 500원~5000원 범위)
            for key in ("gasoline_price", "diesel_price", "lpg_price"):
                price = item.get(key)
                if price is not None and (price < 500 or price > 5000):
                    item[key] = None

            # 가격 필터링 후 다시 확인
            has_price = any([
                item.get("gasoline_price"),
                item.get("diesel_price"),
                item.get("lpg_price"),
            ])
            if not has_price:
                continue

            # 중복 제거 (주유소 이름 기준)
            if name in seen:
                continue
            seen.add(name)

            # 내부 필드 제거
            item.pop("_uni_id", None)
            valid.append(item)

        return valid

    # ------------------------------------------------------------------
    # 전략 1: 오피넷 REST API
    # ------------------------------------------------------------------

    async def _crawl_via_api(self, errors: list[str]) -> list[dict]:
        """오피넷 lowTop10 API로 시도별 최저가 주유소 수집."""
        station_map: dict[str, dict] = {}

        for fuel_type, prod_code, price_key in [
            ("휘발유", self.PROD_GASOLINE, "gasoline_price"),
            ("경유", self.PROD_DIESEL, "diesel_price"),
        ]:
            for sido in self.SIDO_CODES:
                try:
                    data = self._api_request(
                        "lowTop10.do",
                        prodcd=prod_code,
                        area=sido,
                        cnt="10",
                    )
                    if data is None:
                        continue

                    parsed = await self.parse(json.dumps(data))
                    for item in parsed:
                        uid = item.get("_uni_id", item.get("name", ""))
                        if uid in station_map:
                            # 기존 주유소에 가격 병합
                            price = item.get("gasoline_price")
                            if price:
                                station_map[uid][price_key] = price
                        else:
                            # 새 주유소 등록
                            if price_key != "gasoline_price":
                                item[price_key] = item.pop("gasoline_price", None)
                            station_map[uid] = item

                    await asyncio.sleep(self._anti_detect.get_random_delay())

                except Exception as e:
                    msg = f"시도 {sido} {fuel_type}: {e}"
                    logger.debug(f"[오피넷] {msg}")
                    errors.append(msg)

        results = list(station_map.values())
        logger.info(f"[오피넷] API 수집 완료: {len(results)}개 주유소")
        return results

    def _api_request(self, endpoint: str, **params) -> Optional[dict]:
        """오피넷 API 단일 호출."""
        url = f"{self.API_BASE}/{endpoint}"
        params.update({
            "code": self._api_key,
            "out": "json",
        })
        headers = self._anti_detect.get_random_headers()

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"[오피넷] API {endpoint} HTTP {resp.status_code}")
            return None

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"[오피넷] API {endpoint} JSON 디코딩 실패")
            return None

        # API 에러 응답 확인
        error_cd = data.get("RESULT", {}).get("ERROR_CD")
        if error_cd and error_cd != "0000":
            logger.warning(f"[오피넷] API 에러: {error_cd}")
            return None

        return data

    # ------------------------------------------------------------------
    # 전략 2: 웹 스크레이핑 fallback
    # ------------------------------------------------------------------

    async def _crawl_via_web(self, errors: list[str]) -> list[dict]:
        """메인 페이지 스크레이핑으로 유가 정보 수집."""
        items: list[dict] = []
        try:
            headers = self._anti_detect.get_random_headers()
            headers["Referer"] = self.BASE_URL

            resp = requests.get(self.MAIN_PAGE, headers=headers, timeout=20)
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                errors.append(f"메인 페이지 HTTP {resp.status_code}")
                return items

            items = await self._parse_web_page(resp.text)
            logger.info(f"[오피넷] 웹 스크레이핑 수집: {len(items)}개")

        except Exception as e:
            logger.warning(f"[오피넷] 웹 스크레이핑 실패: {e}")
            errors.append(f"웹 스크레이핑: {e}")

        return items

    async def _parse_web_page(self, html: str) -> list[dict]:
        """HTML에서 유가 정보 추출."""
        items: list[dict] = []

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("[오피넷] BeautifulSoup 미설치, HTML 파싱 불가")
            return items

        try:
            soup = BeautifulSoup(html, "html.parser")

            # 전국 평균 유가 추출 (메인 페이지)
            gasoline = self._find_price_in_soup(
                soup,
                "#gasoline_price, .gasoline .price, .oil_price_gasoline, "
                ".main_price .num, .price_info .gasoline",
            )
            diesel = self._find_price_in_soup(
                soup,
                "#diesel_price, .diesel .price, .oil_price_diesel, "
                ".price_info .diesel",
            )
            lpg = self._find_price_in_soup(
                soup,
                "#lpg_price, .lpg .price, .oil_price_lpg, "
                ".price_info .lpg",
            )

            if gasoline:
                items.append({
                    "name": "전국 평균 (오피넷)",
                    "brand": "",
                    "address": "전국",
                    "lat": 37.5665,
                    "lng": 126.9780,
                    "gasoline_price": gasoline,
                    "diesel_price": diesel,
                    "lpg_price": lpg,
                    "is_self": False,
                })

            # 텍스트에서 가격 패턴 추출 (fallback)
            if not items:
                prices = re.findall(
                    r"(\d{1,2}[,.]?\d{3}(?:\.\d{1,2})?)\s*원?",
                    soup.get_text(),
                )
                fuel_prices: list[float] = []
                for p in prices:
                    val = float(p.replace(",", ""))
                    if 500 <= val <= 3000:
                        fuel_prices.append(val)

                if fuel_prices:
                    items.append({
                        "name": "전국 평균 (오피넷)",
                        "brand": "",
                        "address": "전국",
                        "lat": 37.5665,
                        "lng": 126.9780,
                        "gasoline_price": fuel_prices[0] if len(fuel_prices) > 0 else None,
                        "diesel_price": fuel_prices[1] if len(fuel_prices) > 1 else None,
                        "lpg_price": fuel_prices[2] if len(fuel_prices) > 2 else None,
                        "is_self": False,
                    })

        except Exception as e:
            logger.warning(f"[오피넷] HTML 파싱 실패: {e}")

        return items

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def _build_result(
        self,
        items: list[dict],
        started_at: datetime,
        strategy: Optional[str],
        errors: Optional[list[str]] = None,
    ) -> CrawlResult:
        """CrawlResult 생성 헬퍼."""
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()

        if items and errors:
            status = CrawlStatus.PARTIAL
        elif items:
            status = CrawlStatus.SUCCESS
        else:
            status = CrawlStatus.FAILED

        logger.info(f"[오피넷] 크롤링 완료: {len(items)}개, {duration:.2f}초")

        return CrawlResult(
            status=status,
            crawler_name=self.info.name,
            strategy_used=strategy,
            items_count=len(items),
            items=items,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            error_msg="; ".join(errors) if errors and not items else None,
        )

    def _find_price_in_soup(self, soup, selectors: str) -> Optional[float]:
        """CSS 셀렉터로 가격 요소 탐색."""
        for selector in selectors.split(","):
            el = soup.select_one(selector.strip())
            if el:
                price = self._extract_price(el.get_text(strip=True))
                if price:
                    return price
        return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """안전한 float 변환."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_price(text: str) -> Optional[float]:
        """텍스트에서 가격(원) 추출."""
        if not text:
            return None
        cleaned = text.replace(",", "").replace("원", "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if match:
            return float(match.group(1))
        return None
