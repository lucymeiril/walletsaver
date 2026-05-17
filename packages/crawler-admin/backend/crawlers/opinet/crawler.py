"""WalletSavior Phase F4 — 오피넷 주유소 크롤러.

오피넷(opinet.co.kr) 저가주유소 검색 페이지(searRgSelect.do)를 수집한다.
지역별(시도·시군구) POST 요청 → HTML 파싱 → FuelStation + FuelPriceObservation.

라이브 수집 전 operator 승인 필요 (live_ready: false).
현재 fixture 기반으로만 동작.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# shared 경로 보정
_CRAWLER_BACKEND = Path(__file__).resolve().parents[2]
_SHARED_DIR = _CRAWLER_BACKEND.parent.parent / "shared"
for _p in (str(_CRAWLER_BACKEND), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from core.fuel_canonicalize import (
        FuelCanonicalizationResult,
        canonicalize_opinet,
    )
    from .parser import parse_opinet_low_price_html

    _IMPORTS_OK = True
except ImportError as _e:
    logger.warning(f"[OpinetCrawler] import 실패 (graceful): {_e}")
    _IMPORTS_OK = False


# ── 오피넷 시도 코드 (searRgSelect.do area1 파라미터) ──────────────────────
SIDO_CODES: dict[str, str] = {
    "서울특별시": "01",
    "경기도": "41",
    "인천광역시": "28",
    "부산광역시": "26",
    "대구광역시": "27",
    "광주광역시": "29",
    "대전광역시": "30",
    "울산광역시": "31",
    "세종특별자치시": "36",
    "강원도": "42",
    "충청북도": "43",
    "충청남도": "44",
    "전라북도": "45",
    "전라남도": "46",
    "경상북도": "47",
    "경상남도": "48",
    "제주특별자치도": "50",
}

OPINET_BASE_URL = "https://www.opinet.co.kr"
SEARCH_URL = f"{OPINET_BASE_URL}/searRgSelect.do"


class OpinetCrawler:
    """오피넷 저가주유소 크롤러.

    현재는 fixture HTML 파싱만 지원.
    live_ready=False — 라이브 수집은 operator 승인 후 활성화.
    """

    name = "opinet"
    display_name = "오피넷 주유소"
    category = "fuel"
    version = "1.0.0"

    def crawl_from_fixture(
        self,
        fixture_path: Path,
        source_url: str = SEARCH_URL,
        observed_at: Optional[datetime] = None,
    ) -> list[FuelCanonicalizationResult]:
        """fixture HTML 파일 → FuelCanonicalizationResult 리스트.

        Args:
            fixture_path: opinet 저가주유소 페이지 HTML 파일 경로.
            source_url: 수집 출처 URL 기록용.
            observed_at: 관측 시각 (None이면 현재 시각).
        """
        if not _IMPORTS_OK:
            logger.error("[OpinetCrawler] 의존성 미충족 — 크롤링 불가")
            return []

        if observed_at is None:
            observed_at = datetime.now()

        try:
            html = fixture_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"[OpinetCrawler] fixture 파일 읽기 실패: {e}")
            return []

        raw_rows = parse_opinet_low_price_html(html, source_url=source_url)
        logger.info(f"[OpinetCrawler] fixture {fixture_path.name}: {len(raw_rows)}개 row 파싱")

        results: list[FuelCanonicalizationResult] = []
        for row in raw_rows:
            result = canonicalize_opinet(row, observed_at=observed_at)
            if result.error:
                logger.warning(f"[OpinetCrawler] canonicalize 실패: {result.error} — row={row}")
            results.append(result)

        ok = sum(1 for r in results if r.station is not None)
        logger.info(f"[OpinetCrawler] canonicalize: {ok}/{len(results)} 성공")
        return results

    def live_crawl(
        self,
        sido: str,
        sigungu: str = "",
        fuel_kind: str = "B027",
    ) -> list[dict]:
        """오피넷 라이브 수집 (현재 비활성화).

        live_ready=False 상태이며 operator 승인 전까지 호출하지 않는다.
        POST 파라미터:
            area1: 시도 코드 (SIDO_CODES[sido])
            area2: 시군구 코드 (별도 코드 테이블 필요)
            cnt: 표시 개수 (최대 20)
            sel_nm: 유종 코드 (B027=휘발유, B034=경유, B049=LPG)
        """
        logger.warning("[OpinetCrawler] live_crawl은 live_ready=False 상태에서 비활성화됨")
        return []


# Plugin registry 호환 alias
Crawler = OpinetCrawler
